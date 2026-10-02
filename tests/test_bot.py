"""The Telegram bot and the server-side renderer, with Telegram and the LLM stubbed."""
import io
import json
from pathlib import Path

from PIL import Image

from dharmeme.api import MESSAGES, Api
from dharmeme.catalog import load_catalog
from dharmeme.limits import Limits
from dharmeme.pool import Pool
from dharmeme.render import Renderer, fit_text, wrap
from dharmeme.store import MemoryStore
from dharmeme.telegram import HELP, Bot, webhook_secret
from test_engine import GOOD, StubLLM

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = load_catalog()
RENDERER = Renderer(ROOT / "templates" / "images", ROOT / "templates" / "fonts" / "Anton-Regular.ttf")
SEED = {"id": "a1", "status": "approved", "created": "2026-10-01", **GOOD}

# Monospace stand-in for font metrics, as in web/render.test.js.
measure = lambda text, size: len(text) * size * 0.5  # noqa: E731


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.markups = []  # the reply_markup of each photo, in order
        self.calls = []

    def send_message(self, chat_id, text):
        self.sent.append(("message", chat_id, text))

    def send_photo(self, chat_id, photo, caption="", reply_markup=None):
        self.sent.append(("photo", chat_id, photo, caption))
        self.markups.append(reply_markup)

    def call(self, method, payload):
        self.calls.append((method, payload))


def make_bot(llm=None, per_ip=5, seed=True):
    store = MemoryStore()
    pool = Pool(store)
    if seed:
        pool.add(SEED)
    telegram = FakeTelegram()
    bot = Bot(pool, Limits(store, per_ip=per_ip), lambda: llm, TEMPLATES, RENDERER, telegram)
    return bot, telegram


def update(text, chat_id=42):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def is_jpeg(data):
    return Image.open(io.BytesIO(data)).format == "JPEG"


def test_fit_text_matches_the_browser_rules():
    fit = fit_text(measure, "Letting go of attachment", 200, 400)
    assert fit["font_size"] == 40 and "attachment" in fit["lines"]
    long = fit_text(measure, " ".join(["suffering"] * 50), 200, 60)
    assert long["truncated"] and long["lines"][-1].endswith("…")
    assert all(measure(line, 20) <= 100 for line in wrap(measure, "x" * 40, 20, 100))


def test_every_template_renders_at_its_own_size():
    for t in TEMPLATES:
        slots = {s["name"]: "Letting go of attachment" for s in t["slots"]}
        image = Image.open(io.BytesIO(RENDERER.render(t, slots)))
        assert list(image.size) == t["size"], t["id"]


def test_start_and_unknown_commands_send_help():
    bot, telegram = make_bot()
    bot.handle(update("/start"))
    bot.handle(update("/nonsense"))
    assert telegram.sent == [("message", 42, HELP)] * 2


def test_random_sends_a_photo_without_the_llm():
    bot, telegram = make_bot(llm=StubLLM())
    bot.handle(update("/random@dharmeme_bot"))
    kind, chat_id, photo, caption = telegram.sent[0]
    assert (kind, chat_id, caption) == ("photo", 42, "") and is_jpeg(photo)


def test_topic_by_command_or_plain_text_sends_the_llm_meme():
    llm = StubLLM(GOOD, GOOD)
    bot, telegram = make_bot(llm)
    bot.handle(update("/meme my inbox"))
    bot.handle(update("my inbox"))
    assert llm.calls == ["my inbox", "my inbox"]
    assert [s[0] for s in telegram.sent] == ["photo", "photo"]


def test_limit_and_declined_send_a_random_meme_with_the_message():
    bot, telegram = make_bot(StubLLM(GOOD, {"declined": True}), per_ip=2)
    for _ in range(3):
        bot.handle(update("my inbox"))
    assert telegram.sent[1][3] == MESSAGES["declined"]
    assert telegram.sent[2][3] == MESSAGES["limit"]
    assert all(s[0] == "photo" for s in telegram.sent)


def test_limits_are_per_chat():
    llm = StubLLM(GOOD, GOOD)
    bot, telegram = make_bot(llm, per_ip=1)
    bot.handle(update("x", chat_id=1))
    bot.handle(update("x", chat_id=2))
    assert len(llm.calls) == 2


def test_meme_without_a_topic_and_non_text_updates():
    bot, telegram = make_bot(StubLLM())
    bot.handle(update("/meme"))
    assert telegram.sent[0][0] == "message"
    bot.handle({"message": {"chat": {"id": 42}, "sticker": {}}})
    bot.handle({"edited_message": {"text": "x"}})
    assert len(telegram.sent) == 1


def test_webhook_needs_the_secret_and_is_off_without_a_bot():
    bot, telegram = make_bot()
    secret = webhook_secret("123:token")
    store = MemoryStore()

    def event(header):
        return {"rawPath": "/telegram", "headers": header, "body": json.dumps(update("/start")),
                "requestContext": {"http": {"method": "POST", "sourceIp": "1.1.1.1"}}}

    api = Api(Pool(store), Limits(store), lambda: None, TEMPLATES, lambda: (bot, secret))
    assert api.handle(event({}))["statusCode"] == 403
    assert api.handle(event({"x-telegram-bot-api-secret-token": "wrong"}))["statusCode"] == 403
    assert telegram.sent == []
    assert api.handle(event({"x-telegram-bot-api-secret-token": secret}))["statusCode"] == 200
    assert telegram.sent == [("message", 42, HELP)]

    off = Api(Pool(store), Limits(store), lambda: None, TEMPLATES)
    assert off.handle(event({"x-telegram-bot-api-secret-token": secret}))["statusCode"] == 404


def test_a_failing_update_still_answers_200():
    class Broken:
        def handle(self, update):
            raise RuntimeError("boom")

    store = MemoryStore()
    api = Api(Pool(store), Limits(store), lambda: None, TEMPLATES, lambda: (Broken(), "s"))
    event = {"rawPath": "/telegram", "headers": {"x-telegram-bot-api-secret-token": "s"},
             "body": "{}", "requestContext": {"http": {"method": "POST", "sourceIp": "1.1.1.1"}}}
    assert api.handle(event)["statusCode"] == 200
