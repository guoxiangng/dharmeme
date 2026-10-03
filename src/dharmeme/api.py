"""HTTP API behind the Lambda Function URL (SPEC.md §5).

    GET  /memes?lang=  -> the approved pool in that language, for Random (no LLM)
    POST /meme         -> {"theme": "<id>", "lang": "..."} -> a fresh meme, or a fallback
    POST /vote         -> {"id": "...", "vote": "up|down|report"} (no LLM)
    POST /telegram     -> a Telegram update (webhook), if a bot is configured

`lang` is "en" (the default), "zh" (Traditional Chinese) or "zh-hans" (Simplified).
CORS is configured on the Function URL, so no CORS headers are added here.
"""
import base64
import hmac
import json

from .feedback import KINDS
from .prompt import HANS, to_simplified, write_meme
from .themes import as_topic

# Every fallback comes with a meme from the vetted pool, so each message says so: a
# visitor should never take the pool meme for the AI's answer, or the limit for a fault.
MESSAGES = {
    "limit": "You've used up your free AI memes for today. They reset at midnight "
             "Singapore time (SGT). Meanwhile, here's one from the vetted pool.",
    "cap": "Fresh AI memes are closed for today. They open again at midnight Singapore "
           "time (SGT). Meanwhile, here's one from the vetted pool.",
    "declined": "Some topics are best met with noble silence. Here's one from the vetted "
                "pool instead.",
    "error": "The mind wandered and no fresh meme came out. Here's one from the vetted "
             "pool instead.",
}
MESSAGES_ZH = {
    "limit": "你今天的免費 AI 梗圖已經用完了，新加坡時間午夜 12 點重置。先送你一張梗圖庫裡的。",
    "cap": "今天的 AI 新梗圖已經圓滿結束，新加坡時間午夜 12 點再開張。先送你一張梗圖庫裡的。",
    "declined": "這個題目，還是保持聖默然吧。先送你一張梗圖庫裡的。",
    "error": "剛剛打妄想了，沒寫出新的。先送你一張梗圖庫裡的。",
}
MESSAGES_HANS = {
    "limit": "你今天的免费 AI 梗图已经用完了，新加坡时间午夜 12 点重置。先送你一张梗图库里的。",
    "cap": "今天的 AI 新梗图已经圆满结束，新加坡时间午夜 12 点再开张。先送你一张梗图库里的。",
    "declined": "这个题目，还是保持圣默然吧。先送你一张梗图库里的。",
    "error": "刚刚打妄想了，没写出新的。先送你一张梗图库里的。",
}
MESSAGES_BY_LANG = {"en": MESSAGES, "zh": MESSAGES_ZH, HANS: MESSAGES_HANS}
POOL_CACHE_SECONDS = 300


def pool_lang(lang: str) -> str:
    """The language a meme is written and stored in. Both Chinese scripts share one
    source, in Traditional; Simplified is converted on the way out."""
    return "en" if lang == "en" else "zh"


def in_script(meme: dict, lang: str) -> dict:
    """The meme as `lang` should read it: Simplified readers get converted text."""
    if lang != HANS:
        return meme
    return {**meme, "slots": {k: to_simplified(v) for k, v in meme["slots"].items()}}


def _response(status: int, body: dict | list, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **(headers or {})},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _body(event: dict) -> str:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return raw


def _fallback(reason: str, lang: str = "en") -> dict:
    return _response(200, {"fallback": reason, "message": MESSAGES_BY_LANG[lang][reason]})


class Api:
    def __init__(self, pool, limits, get_llm, templates: list[dict], get_bot=None,
                 feedback=None, themes: list[dict] = (), themes_zh: list[dict] = ()) -> None:
        # Themes by the language they are written in. Simplified requests use the
        # Traditional theme of the same id; only the output is converted.
        self.themes = {"en": {t["id"]: t for t in themes},
                       "zh": {t["id"]: t for t in themes_zh}}
        self.pool = pool
        self.limits = limits
        self.get_llm = get_llm  # called only for a prompt request, so /memes stays light
        self.templates = templates
        self.feedback = feedback
        # Returns (bot, webhook secret), or None while no Telegram bot is configured.
        self.get_bot = get_bot or (lambda: None)

    def telegram(self, event: dict) -> dict:
        configured = self.get_bot()
        if configured is None:
            return _response(404, {"error": "not found"})
        bot, secret = configured
        sent = (event.get("headers") or {}).get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(sent, secret):
            return _response(403, {"error": "forbidden"})
        try:
            bot.handle(json.loads(_body(event)))
        except Exception as exc:  # noqa: BLE001 — a non-200 makes Telegram resend the update
            print(f"telegram: update failed: {exc!r}")
        return _response(200, {"ok": True})

    def handle(self, event: dict) -> dict:
        http = event["requestContext"]["http"]
        method, path = http["method"], event.get("rawPath", "/").rstrip("/")
        if path == "/telegram":
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.telegram(event)
        if path == "/memes":
            if method != "GET":
                return _response(405, {"error": "use GET"})
            return self.memes(event)
        if path == "/meme":
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.meme(event, http["sourceIp"])
        if path == "/vote" and self.feedback is not None:
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.vote(event, http["sourceIp"])
        return _response(404, {"error": "not found"})

    def memes(self, event: dict) -> dict:
        lang = (event.get("queryStringParameters") or {}).get("lang", "en")
        if lang not in MESSAGES_BY_LANG:
            return _response(400, {"error": "lang must be en, zh or zh-hans"})
        memes = [in_script(m, lang) for m in self.pool.approved(pool_lang(lang))]
        return _response(200, memes, {"cache-control": f"public, max-age={POOL_CACHE_SECONDS}"})

    def vote(self, event: dict, ip: str) -> dict:
        try:
            data = json.loads(_body(event))
            meme_id, kind = data["id"], data["vote"]
        except (ValueError, KeyError, TypeError):
            return _response(400, {"error": 'send {"id": "...", "vote": "up|down|report"}'})
        if not isinstance(meme_id, str) or len(meme_id) > 64 or kind not in KINDS:
            return _response(400, {"error": 'send {"id": "...", "vote": "up|down|report"}'})
        voter = f"ip-{ip}"
        if not self.limits.allow_vote(voter):
            return _response(429, {"error": "too many votes today"})
        result = self.feedback.vote(voter, meme_id, kind)
        return _response(404 if result == "unknown" else 200, {"result": result})

    def meme(self, event: dict, ip: str) -> dict:
        # The public picks a theme from the fixed list; nothing a visitor types reaches
        # the model.
        try:
            data = json.loads(_body(event))
            lang = data.get("lang", "en")
            theme = self.themes[pool_lang(lang)][data["theme"]]
            if lang not in MESSAGES_BY_LANG:
                raise KeyError(lang)
        except (ValueError, KeyError, TypeError, AttributeError):
            return _response(400, {"error": 'send {"theme": "<id of a listed theme>"}'})

        refused = self.limits.check(ip)
        if refused:
            return _fallback(refused, lang)
        result = write_meme(as_topic(theme), self.get_llm(), self.templates, pool_lang(lang))
        if "fallback" in result:
            return _fallback(result["fallback"], lang)
        if self.feedback is not None:
            # Held outside the pool; its id lets the requester's thumbs up nominate it.
            result = {"id": self.feedback.keep_fresh(result, pool_lang(lang)), **result}
        return _response(200, in_script(result, lang))
