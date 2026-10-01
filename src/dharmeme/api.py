"""HTTP API behind the Lambda Function URL (SPEC.md §5).

    GET  /memes  -> the approved pool, for the page's Random button (no LLM)
    POST /meme   -> {"topic": "..."} -> a meme for the topic, or a fallback

CORS is configured on the Function URL, so no CORS headers are added here.
"""
import base64
import json

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


def _fallback(reason: str) -> dict:
    return _response(200, {"fallback": reason, "message": MESSAGES[reason]})


class Api:
    def __init__(self, pool, limits, get_llm, templates: list[dict]) -> None:
        self.pool = pool
        self.limits = limits
        self.get_llm = get_llm  # called only for a prompt request, so /memes stays light
        self.templates = templates

    def handle(self, event: dict) -> dict:
        http = event["requestContext"]["http"]
        method, path = http["method"], event.get("rawPath", "/").rstrip("/")
        if path == "/memes":
            if method != "GET":
                return _response(405, {"error": "use GET"})
            return _response(200, self.pool.approved(),
                             {"cache-control": f"public, max-age={POOL_CACHE_SECONDS}"})
        if path == "/meme":
            if method != "POST":
                return _response(405, {"error": "use POST"})
            return self.meme(event, http["sourceIp"])
        return _response(404, {"error": "not found"})

    def meme(self, event: dict, ip: str) -> dict:
        try:
            raw = event.get("body") or ""
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            topic = json.loads(raw)["topic"]
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
