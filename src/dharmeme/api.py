"""HTTP API behind the Lambda Function URL (SPEC.md §5).

    GET  /memes     -> the approved pool, for the page's Random button (no LLM)
    POST /meme      -> {"topic": "..."} -> a meme for the topic, or a fallback
    POST /vote      -> {"id": "...", "vote": "up|down|report"} on a pool meme (no LLM)
    POST /telegram  -> a Telegram update (webhook), if a bot is configured

CORS is configured on the Function URL, so no CORS headers are added here.
"""
import base64
import hmac
import json

from .feedback import KINDS
from .prompt import TOPIC_MAX, write_meme

MESSAGES = {
    "limit": "The meme well is empty. All things are impermanent — try tomorrow.",
    "declined": "Some topics are best met with noble silence. Here is another one instead.",
    "error": "The mind wandered. Here is another one instead.",
}
POOL_CACHE_SECONDS = 300


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


def _fallback(reason: str) -> dict:
    return _response(200, {"fallback": reason, "message": MESSAGES[reason]})


class Api:
    def __init__(self, pool, limits, get_llm, templates: list[dict], get_bot=None,
                 feedback=None) -> None:
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
            return _response(200, self.pool.approved(),
                             {"cache-control": f"public, max-age={POOL_CACHE_SECONDS}"})
        if path == "/meme":
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.meme(event, http["sourceIp"])
        if path == "/vote" and self.feedback is not None:
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.vote(event, http["sourceIp"])
        return _response(404, {"error": "not found"})

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
        try:
            topic = json.loads(_body(event))["topic"]
        except (ValueError, KeyError, TypeError):
            return _response(400, {"error": 'send {"topic": "..."}'})
        if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= TOPIC_MAX:
            return _response(400, {"error": f"topic must be 1 to {TOPIC_MAX} characters"})

        if not self.limits.allow(ip):
            return _fallback("limit")
        result = write_meme(topic.strip(), self.get_llm(), self.templates)
        if "fallback" in result:
            return _fallback(result["fallback"])
        return _response(200, result)
