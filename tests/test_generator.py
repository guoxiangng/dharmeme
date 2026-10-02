"""The scheduled generator and the owner's Remove button, with the LLM stubbed."""
from datetime import datetime, timezone

from dharmeme import generator
from dharmeme.catalog import load_catalog
from dharmeme.limits import Limits
from dharmeme.pool import Pool
from dharmeme.store import MemoryStore
from dharmeme.telegram import APPROVE, REJECT, Bot
from test_bot import RENDERER, FakeTelegram
from test_engine import GOOD, StubLLM

TEMPLATES = load_catalog()
NOW = lambda: datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)  # noqa: E731
SEED = {"id": "a1", "status": "approved", "created": "2026-10-01", **GOOD}
NEW = {"template_id": "drake", "slots": {"rejected": "Chanting", "preferred": "Humming"}}
OTHER = {"template_id": "this-is-fine", "slots": {"chaos": "My to-do list"}}


def make_pool():
    pool = Pool(MemoryStore())
    pool.add(SEED)
    return pool


def verdicts(*passes):
    return [{"n": n, "pass": p, "reason": "ok"} for n, p in enumerate(passes, 1)]


def test_pick_templates_prefers_the_least_used():
    existing = [{"template_id": t["id"]} for t in TEMPLATES if t["id"] != "drake"]
    assert generator.pick_templates(TEMPLATES, existing, 1)[0]["id"] == "drake"
    assert len(generator.pick_templates(TEMPLATES, [], len(TEMPLATES) + 3)) == len(TEMPLATES) + 3


def test_run_adds_the_memes_that_pass_review():
    pool = make_pool()
    llm = StubLLM([NEW, OTHER], verdicts(True, False))
    added = generator.run(pool, llm, TEMPLATES, len(TEMPLATES), "approved", NOW)
    assert [m["id"] for m in added] == ["gen-20261002-0100-01"]
    assert added[0]["slots"] == NEW["slots"] and added[0]["created"] == "2026-10-02"
    assert len(pool.approved()) == 2
    assert "already in the pool" in llm.calls[0]  # the writer is shown what exists
    assert "Chanting" in llm.calls[1]  # the reviewer is shown the batch


def test_invalid_and_duplicate_memes_never_reach_the_reviewer():
    pool = make_pool()
    same_as_seed = {"template_id": "drake",
                    "slots": {"rejected": " sitting ", "preferred": "SCROLLING"}}
    bad = {"template_id": "nope", "slots": {}}
    llm = StubLLM([same_as_seed, bad, NEW, NEW], verdicts(True))
    added = generator.run(pool, llm, TEMPLATES, 4, "approved", NOW)
    assert len(added) == 1
    assert llm.calls[1].count("template drake") == 1


def test_an_unreadable_review_adds_nothing():
    for review_reply in ("looks good to me!", RuntimeError("down"), verdicts()):
        pool = make_pool()
        assert generator.run(pool, StubLLM([NEW], review_reply), TEMPLATES, 1, "approved", NOW) == []
        assert len(pool.all()) == 1


def test_nothing_written_means_no_review_call():
    llm = StubLLM([])
    assert generator.run(make_pool(), llm, TEMPLATES, 1, "approved", NOW) == []
    assert len(llm.calls) == 1


def test_pending_memes_are_not_served():
    pool = make_pool()
    generator.run(pool, StubLLM([NEW], verdicts(True)), TEMPLATES, 1, "pending", NOW)
    assert len(pool.all()) == 2 and len(pool.approved()) == 1


def make_owner_bot(pool):
    telegram = FakeTelegram()
    telegram.calls = []
    telegram.call = lambda method, payload: telegram.calls.append((method, payload))
    telegram.send_photo = lambda chat, photo, caption="", reply_markup=None: telegram.sent.append(
        ("photo", chat, caption, reply_markup))
    return Bot(pool, Limits(pool.store), lambda: None, TEMPLATES, RENDERER, telegram, 99), telegram


def button(prefix, meme_id, chat_id):
    return {"callback_query": {"id": "q1", "data": f"{prefix}{meme_id}",
                               "message": {"chat": {"id": chat_id}}}}


def pending_pool():
    pool = Pool(MemoryStore())
    pool.add(dict(SEED, status="pending"))
    return pool


def test_owner_is_asked_about_a_pending_meme():
    bot, telegram = make_owner_bot(pending_pool())
    bot.ask_owner(SEED)
    kind, chat, caption, markup = telegram.sent[0]
    assert (kind, chat) == ("photo", 99)
    assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == ["ok:a1", "no:a1"]


def test_only_the_owner_can_approve_or_reject():
    pool = pending_pool()
    bot, telegram = make_owner_bot(pool)
    answers = lambda: [p["text"] for m, p in telegram.calls if m == "answerCallbackQuery"]  # noqa: E731
    bot.handle(button(APPROVE, "a1", chat_id=7))
    assert pool.approved() == []
    assert answers()[-1] == "Not allowed."
    assert [m for m, _ in telegram.calls] == ["answerCallbackQuery"]  # message left alone

    bot.handle(button(APPROVE, "a1", chat_id=99))
    assert len(pool.approved()) == 1
    # the buttons are replaced by the outcome
    assert telegram.calls[-1] == ("editMessageCaption",
                                  {"chat_id": 99, "message_id": None, "caption": "In the pool."})
    bot.handle(button(REJECT, "a1", chat_id=99))
    assert pool.approved() == [] and pool.all()[0]["status"] == "rejected"
    bot.handle(button(APPROVE, "missing", chat_id=99))
    assert answers()[-1] == "That meme is not in the pool."


def test_a_meme_is_only_ever_offered_to_the_owner_once():
    pool = pending_pool()
    pool.add(dict(SEED, id="a2", status="pending"))
    assert [m["id"] for m in pool.unasked_pending()] == ["a1", "a2"]
    pool.mark_asked("a1")
    assert [m["id"] for m in pool.unasked_pending()] == ["a2"]
    # Whatever the owner then does with a1, it is not offered again.
    pool.set_status("a1", "approved")
    pool.set_status("a1", "pending")
    assert [m["id"] for m in pool.unasked_pending()] == ["a2"]


def test_buttons_do_nothing_while_no_owner_is_set():
    pool = pending_pool()
    bot, telegram = make_owner_bot(pool)
    bot.owner_chat_id = None
    bot.handle({"callback_query": {"id": "q1", "data": f"{APPROVE}a1", "message": {}}})
    assert pool.approved() == []


def test_id_command_reports_the_chat_id():
    bot, telegram = make_owner_bot(make_pool())
    bot.handle({"message": {"chat": {"id": 1234}, "text": "/id"}})
    assert "1234" in telegram.sent[0][2]
