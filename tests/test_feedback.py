"""Thumbs up, thumbs down and Report (SPEC.md §4a), on the API and in the bot."""
import json

from dharmeme.api import Api
from dharmeme.catalog import load_catalog
from dharmeme.feedback import Feedback, up_rate, weight
from dharmeme.limits import Limits
from dharmeme.pool import Pool
from dharmeme.store import MemoryStore
from dharmeme.telegram import Bot
from test_bot import RENDERER, FakeTelegram
from test_engine import GOOD

TEMPLATES = load_catalog()
SEED = {"id": "a1", "status": "approved", "created": "2026-10-01", **GOOD}


def make():
    store = MemoryStore()
    pool = Pool(store)
    pool.add(SEED)
    asked = []
    feedback = Feedback(store, lambda meme, reason: asked.append((meme["id"], reason)))
    return store, pool, feedback, asked


def counts(pool):
    meme = pool.approved()[0]
    return meme["up"], meme["down"]


def test_votes_are_counted_once_per_voter():
    _, pool, feedback, _ = make()
    assert feedback.vote("ip-1", "a1", "up") == "ok"
    assert feedback.vote("ip-1", "a1", "up") == "already"
    assert feedback.vote("ip-1", "a1", "down") == "already"  # no changing sides either
    assert feedback.vote("ip-2", "a1", "down") == "ok"
    assert counts(pool) == (1, 1)
    assert feedback.vote("ip-1", "nope", "up") == "unknown"


def test_a_report_goes_to_the_owner_once_and_hides_nothing():
    _, pool, feedback, asked = make()
    assert feedback.vote("ip-1", "a1", "report") == "ok"
    assert feedback.vote("ip-1", "a1", "report") == "already"
    assert feedback.vote("ip-2", "a1", "report") == "ok"
    assert asked == [("a1", "Reported by a user.")]  # the second report doesn't nag again
    assert len(pool.approved()) == 1  # still served; the owner decides
    assert feedback.vote("ip-1", "a1", "up") == "ok"  # a report doesn't use up the thumb


def test_a_poorly_rated_meme_goes_to_the_owner_once():
    _, pool, feedback, asked = make()
    for n in range(4):
        feedback.vote(f"up-{n}", "a1", "up")
    for n in range(15):
        feedback.vote(f"down-{n}", "a1", "down")
    assert asked == []  # 19 votes: not enough yet
    feedback.vote("down-15", "a1", "down")  # 4 up, 16 down
    feedback.vote("down-16", "a1", "down")
    assert asked == [("a1", "Rated poorly: 4 up, 16 down.")]
    assert len(pool.approved()) == 1


def test_a_well_rated_or_thinly_voted_meme_is_left_alone():
    _, _, feedback, asked = make()
    for n in range(30):
        feedback.vote(f"v-{n}", "a1", "up" if n % 2 else "down")
    assert asked == []


def test_rating_ignores_how_many_votes_there_are():
    assert up_rate(9, 0) is None
    assert up_rate(10, 0) == up_rate(1000, 0) == 1
    assert weight({"up": 3, "down": 0}) == weight({}) == 1.0
    assert weight({"up": 1000, "down": 0}) == 1.5
    assert weight({"up": 0, "down": 1000}) == 0.5


def event(body, ip="1.2.3.4", method="POST"):
    return {"rawPath": "/vote", "body": json.dumps(body),
            "requestContext": {"http": {"method": method, "sourceIp": ip}}}


def test_vote_endpoint():
    store, pool, feedback, _ = make()
    api = Api(pool, Limits(store), lambda: None, TEMPLATES, feedback=feedback)
    ok = api.handle(event({"id": "a1", "vote": "up"}))
    assert (ok["statusCode"], json.loads(ok["body"])) == (200, {"result": "ok"})
    again = api.handle(event({"id": "a1", "vote": "down"}))
    assert json.loads(again["body"]) == {"result": "already"}
    assert api.handle(event({"id": "nope", "vote": "up"}))["statusCode"] == 404
    for bad in ({}, {"id": "a1", "vote": "sideways"}, {"id": 5, "vote": "up"},
                {"id": "x" * 65, "vote": "up"}):
        assert api.handle(event(bad))["statusCode"] == 400
    assert api.handle(event({"id": "a1", "vote": "up"}, method="GET"))["statusCode"] == 405
    assert counts(pool) == (1, 0)
    listed = json.loads(api.handle({"rawPath": "/memes", "requestContext": {
        "http": {"method": "GET", "sourceIp": "1.1.1.1"}}})["body"])
    assert listed[0]["up"] == 1  # the page gets the counts with the pool


def test_votes_have_a_daily_allowance():
    store, pool, feedback, _ = make()
    limits = Limits(store)
    assert all(limits.allow_vote("ip-1", per_day=3) for _ in range(3))
    assert not limits.allow_vote("ip-1", per_day=3)
    assert limits.allow_vote("ip-2", per_day=3)


def make_bot():
    store, pool, feedback, asked = make()
    telegram = FakeTelegram()
    bot = Bot(pool, Limits(store), lambda: None, TEMPLATES, RENDERER, telegram, 99, feedback)
    return bot, telegram, pool, asked


def press(data, user=7):
    return {"callback_query": {"id": "q", "data": data, "from": {"id": user},
                               "message": {"chat": {"id": user}}}}


def test_pool_memes_carry_three_buttons_and_topic_memes_none():
    bot, telegram, _, _ = make_bot()
    bot.handle({"message": {"chat": {"id": 7}, "text": "/random"}})
    buttons = telegram.markups[0]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["up:a1", "dn:a1", "rp:a1"]
    bot.send(7, GOOD)  # a topic meme has no id
    assert telegram.markups[1] is None


def test_anyone_can_vote_in_the_bot_but_only_once():
    bot, telegram, pool, asked = make_bot()
    bot.handle(press("up:a1"))
    bot.handle(press("dn:a1"))
    bot.handle(press("dn:a1", user=8))
    assert [p["text"] for _, p in telegram.calls] == [
        "Thanks!", "You already did that for this one.", "Thanks!"]
    assert counts(pool) == (1, 1)
    bot.handle(press("rp:a1"))
    assert telegram.calls[-1][1]["text"] == "Reported. Thank you."
    assert asked == [("a1", "Reported by a user.")]


def test_a_voter_cannot_use_the_owners_buttons():
    bot, telegram, pool, _ = make_bot()
    bot.handle(press("no:a1"))  # Remove, pressed from a chat that isn't the owner's
    assert telegram.calls[-1][1]["text"] == "Not allowed."
    assert len(pool.approved()) == 1


def test_owner_is_asked_to_keep_or_remove_a_reported_meme():
    bot, telegram, pool, _ = make_bot()
    bot.ask_owner_to_review(SEED, "Reported by a user.")
    kind, chat, _, caption = telegram.sent[0]
    assert (chat, caption) == (99, "Reported by a user. Keep it in the pool?")
    labels = [b["text"] for b in telegram.markups[0]["inline_keyboard"][0]]
    assert labels == ["Keep", "Remove"]
    bot.handle(press("no:a1", user=99))
    assert pool.approved() == []
