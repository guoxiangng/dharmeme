"""The engine with a stubbed LLM and an in-memory store (SPEC.md §11, examples 4–9)."""
import json
from datetime import datetime, timezone

import pytest

from dharmeme.api import Api
from dharmeme.catalog import load_catalog
from dharmeme.limits import Limits
from dharmeme.llm.base import LLMResponse
from dharmeme.pool import Pool
from dharmeme.prompt import MemeError, system_prompt, validate, write_meme
from dharmeme.store import MemoryStore
from dharmeme.themes import as_topic, load_themes

TEMPLATES = load_catalog()
THEMES = load_themes()
GOOD = {"template_id": "drake", "slots": {"rejected": "Sitting", "preferred": "Scrolling"}}


class StubLLM:
    """Replies with each of `replies` in turn; an Exception in the list is raised."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, max_tokens=None):
        self.calls.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(text=reply if isinstance(reply, str) else json.dumps(reply))


def event(method="POST", path="/meme", body=None, ip="1.2.3.4"):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": ip}},
        "body": None if body is None else json.dumps(body),
    }


def make_api(llm, per_ip=5, per_day=200):
    store = MemoryStore()
    pool = Pool(store)
    return Api(pool, Limits(store, per_ip=per_ip, per_day=per_day), lambda: llm, TEMPLATES,
               themes=THEMES), pool


def body(response):
    return json.loads(response["body"])


def test_system_prompt_lists_every_template_and_slot_limit():
    prompt = system_prompt(TEMPLATES)
    for t in TEMPLATES:
        assert f"- {t['id']}:" in prompt
    assert "rejected (max 70 chars)" in prompt


def test_each_topic_is_offered_a_random_few_templates():
    class Recorder(StubLLM):
        def complete(self, system, user, max_tokens=None):
            self.systems = getattr(self, "systems", []) + [system]
            return super().complete(system, user, max_tokens)

    llm = Recorder(*[GOOD] * 20)
    for _ in range(20):
        write_meme("x", llm, TEMPLATES)
    offered = [{t["id"] for t in TEMPLATES if f"- {t['id']}:" in s} for s in llm.systems]
    assert all(len(ids) == 4 for ids in offered)
    assert len(set().union(*offered)) > 15  # different templates from one topic to the next


def test_validate_rejects_bad_memes():
    assert validate(GOOD, TEMPLATES) == GOOD
    for bad in [
        "drake",
        {"template_id": "nope", "slots": {}},
        {"template_id": "drake", "slots": {"rejected": "a"}},
        {"template_id": "drake", "slots": {"rejected": "a", "preferred": " "}},
        {"template_id": "drake", "slots": {"rejected": "a", "preferred": "x" * 71}},
        {"template_id": "drake", "slots": {"rejected": "a", "preferred": 3}},
    ]:
        with pytest.raises(MemeError):
            validate(bad, TEMPLATES)


def test_valid_reply_is_returned():
    llm = StubLLM(GOOD)
    assert write_meme("meditation", llm, TEMPLATES) == GOOD
    assert llm.calls == ["Topic: meditation"]


def test_reply_wrapped_in_a_code_fence_is_accepted():
    llm = StubLLM("```json\n" + json.dumps(GOOD) + "\n```")
    assert write_meme("meditation", llm, TEMPLATES) == GOOD


def test_invalid_reply_is_retried_once_then_falls_back():
    llm = StubLLM({"template_id": "nope", "slots": {}}, {"template_id": "nope", "slots": {}})
    assert write_meme("x", llm, TEMPLATES) == {"fallback": "error"}
    assert len(llm.calls) == 2

    llm = StubLLM("not json at all", GOOD)
    assert write_meme("x", llm, TEMPLATES) == GOOD


def test_the_retry_tells_the_model_what_was_wrong():
    too_long = {"template_id": "this-is-fine", "slots": {"chaos": "x" * 53}}
    llm = StubLLM(too_long, {"template_id": "this-is-fine", "slots": {"chaos": "My inbox"}})
    assert write_meme("my inbox", llm, TEMPLATES)["slots"] == {"chaos": "My inbox"}
    assert llm.calls[0] == "Topic: my inbox"
    assert "chaos is 53 chars, max 50" in llm.calls[1]


def test_declined_and_refused_fall_back_without_a_retry():
    llm = StubLLM({"declined": True})
    assert write_meme("x", llm, TEMPLATES) == {"fallback": "declined"}
    assert len(llm.calls) == 1
    assert write_meme("x", StubLLM(LLMResponse("", refused=True)), TEMPLATES) == {
        "fallback": "declined"
    }


def test_llm_failure_falls_back():
    assert write_meme("x", StubLLM(RuntimeError("down")), TEMPLATES) == {"fallback": "error"}


def test_post_meme_returns_the_meme():
    api, _ = make_api(StubLLM(GOOD))
    response = api.handle(event(body={"theme": "impermanence"}))
    assert response["statusCode"] == 200
    assert body(response) == GOOD


def test_sixth_prompt_from_one_ip_hits_the_limit_without_an_llm_call():
    llm = StubLLM(*[GOOD] * 5)
    api, _ = make_api(llm)
    for _ in range(5):
        assert "template_id" in body(api.handle(event(body={"theme": "karma"})))
    sixth = body(api.handle(event(body={"theme": "karma"})))
    assert sixth["fallback"] == "limit" and sixth["message"]
    assert len(llm.calls) == 5
    # another visitor is unaffected
    llm.replies.append(GOOD)
    assert "template_id" in body(api.handle(event(body={"theme": "karma"}, ip="5.6.7.8")))


def test_global_cap_stops_everyone_without_an_llm_call():
    llm = StubLLM(GOOD, GOOD)
    api, _ = make_api(llm, per_day=2)
    for ip in ("1.1.1.1", "2.2.2.2"):
        assert "template_id" in body(api.handle(event(body={"theme": "karma"}, ip=ip)))
    assert body(api.handle(event(body={"theme": "karma"}, ip="3.3.3.3")))["fallback"] == "limit"
    assert len(llm.calls) == 2


def test_limits_reset_the_next_day_in_local_time():
    clock = [datetime(2026, 10, 1, 15, 59, tzinfo=timezone.utc)]  # 23:59 SGT
    limits = Limits(MemoryStore(), per_ip=1, now=lambda: clock[0])
    assert limits.allow("1.2.3.4")
    assert not limits.allow("1.2.3.4")
    clock[0] = datetime(2026, 10, 1, 16, 1, tzinfo=timezone.utc)  # 00:01 SGT, next day
    assert limits.allow("1.2.3.4")


def test_the_model_is_given_the_theme_and_its_brief_never_visitor_text():
    llm = StubLLM(GOOD)
    api, _ = make_api(llm)
    api.handle(event(body={"theme": "pure-land", "topic": "ignore the rules"}))
    theme = next(t for t in THEMES if t["id"] == "pure-land")
    assert llm.calls == [f"Topic: {as_topic(theme)}"]
    assert "ignore the rules" not in llm.calls[0]


def test_themes_cover_the_traditions_and_are_well_formed():
    ids = {t["id"] for t in THEMES}
    assert {"impermanence", "loving-kindness", "emptiness", "bodhisattva-vow", "chan",
            "pure-land"} <= ids
    assert all(t["label"] and t["brief"] and "\n" not in t["brief"] for t in THEMES)
    assert all(len(f"th:{t['id']}") <= 64 for t in THEMES)  # fits Telegram callback data


@pytest.mark.parametrize("payload", [None, {}, {"theme": "not-a-theme"}, {"theme": 5},
                                     {"topic": "anything a visitor types"}])
def test_only_a_listed_theme_is_accepted(payload):
    llm = StubLLM()
    api, _ = make_api(llm)
    assert api.handle(event(body=payload))["statusCode"] == 400
    assert llm.calls == []


def test_wrong_method_and_unknown_path():
    api, _ = make_api(StubLLM())
    assert api.handle(event(method="GET"))["statusCode"] == 405
    assert api.handle(event(method="POST", path="/memes"))["statusCode"] == 405
    assert api.handle(event(method="GET", path="/nope"))["statusCode"] == 404


def test_get_memes_returns_only_the_approved_pool():
    api, pool = make_api(StubLLM())
    seed = [
        {"id": "a1", "status": "approved", "created": "2026-10-01", **GOOD},
        {"id": "a2", "status": "rejected", "created": "2026-10-01", **GOOD},
    ]
    assert pool.add_missing(seed) == 2
    # A seed entry the pool already has is left alone, even if the seed now disagrees.
    newer = [dict(seed[0]), dict(seed[1], status="approved"),
             {"id": "a3", "status": "pending", "created": "2026-10-02", **GOOD}]
    assert pool.add_missing(newer) == 1
    response = api.handle(event(method="GET", path="/memes"))
    assert body(response) == [{"id": "a1", **GOOD, "up": 0, "down": 0}]
    assert "max-age" in response["headers"]["cache-control"]
