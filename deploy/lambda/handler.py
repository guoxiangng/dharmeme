"""Lambda entry point. scripts/build_lambda.py puts this file, the dharmeme package,
catalog.json, the seed memes, the template images and the font side by side in the
deployment package.
"""
import json
import os
import time
from functools import cache
from pathlib import Path

from dharmeme.api import Api
from dharmeme.limits import Limits
from dharmeme.llm.factory import get_provider
from dharmeme.pool import Pool
from dharmeme.store import DynamoStore

HERE = Path(__file__).parent
TEMPLATES = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
THEMES = json.loads((HERE / "themes.json").read_text(encoding="utf-8"))
THEMES_ZH = json.loads((HERE / "themes_zh.json").read_text(encoding="utf-8"))
THEMES_HANS = json.loads((HERE / "themes_zh_hans.json").read_text(encoding="utf-8"))
get_llm = cache(get_provider)


@cache
def _engine() -> tuple[Pool, Limits]:
    store = DynamoStore(os.environ["DHARMEME_TABLE"])
    pool = Pool(store)
    seed = [json.loads(line) for line in
            (HERE / "seed.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    added = pool.add_missing(seed)
    if added:
        print(f"Added {added} seed memes to the pool.")
    limits = Limits(
        store,
        per_ip=int(os.environ.get("DHARMEME_LIMIT_PER_IP", "5")),
        per_day=int(os.environ.get("DHARMEME_LIMIT_PER_DAY", "200")),
        utc_offset=int(os.environ.get("DHARMEME_UTC_OFFSET", "8")),
    )
    return pool, limits


def _telegram_token() -> str | None:
    """The bot token from SSM Parameter Store, or None while no bot is configured."""
    import boto3

    ssm = boto3.client("ssm")
    try:
        return ssm.get_parameter(Name=os.environ["DHARMEME_TELEGRAM_PARAM"],
                                 WithDecryption=True)["Parameter"]["Value"].strip()
    except ssm.exceptions.ParameterNotFound:
        return None


_bot = None  # (Bot, webhook secret) once a token exists; "not configured" is not cached


def get_bot():
    global _bot
    if _bot is None:
        token = _telegram_token()
        if token is None:
            return None
        # Imported here so the website's requests never load Pillow.
        from dharmeme.render import Renderer
        from dharmeme.telegram import Bot, TelegramApi, webhook_secret

        pool, limits = _engine()
        renderer = Renderer(HERE / "images", HERE / "Anton-Regular.ttf",
                            HERE / "NotoSansTC.ttf", HERE / "NotoSansSC.ttf")
        owner = os.environ.get("DHARMEME_OWNER_CHAT", "").strip()
        _bot = (Bot(pool, limits, get_llm, TEMPLATES, renderer, TelegramApi(token),
                    int(owner) if owner else None, _feedback(), THEMES, THEMES_ZH,
                    THEMES_HANS),
                webhook_secret(token))
    return _bot


def _owner_bot():
    configured = get_bot()
    return configured[0] if configured and configured[0].owner_chat_id else None


def _ask_owner_to_review(meme: dict, reason: str) -> None:
    """A reported or poorly rated meme goes to the owner's chat; it is never auto-hidden."""
    bot = _owner_bot()
    if bot:
        bot.ask_owner_to_review(meme, reason)


@cache
def _feedback():
    from dharmeme.feedback import Feedback

    pool, _ = _engine()
    return Feedback(pool.store, _ask_owner_to_review)


def ask_owner(memes: list[dict]) -> int:
    """Send pending memes to the owner's chat for approval. Returns how many were sent.

    Each meme sent is marked as asked, so no meme is ever sent to the owner twice.
    """
    bot = _owner_bot()
    pool, _ = _engine()
    sent = 0
    for meme in memes if bot else []:
        try:
            bot.ask_owner(meme)
            pool.mark_asked(meme["id"])
            sent += 1
        except Exception as exc:  # noqa: BLE001 — it stays pending and unasked
            print(f"could not send {meme['id']} to the owner: {exc!r}")
        time.sleep(0.4)  # stay under Telegram's per-chat rate limit
    return sent


def generate(langs: tuple[str, ...] = ("en", "zh")) -> dict:
    """The daily run (SPEC.md §4), once per language: the English pool, and the Chinese
    pool at half the size. New memes are always pending: nothing generated is published
    until the owner approves it in their own chat."""
    from dharmeme import generator

    pool, _ = _engine()
    count = int(os.environ.get("DHARMEME_GENERATE_COUNT", "10"))
    added = []
    for lang in langs:
        added += generator.run(pool, get_llm(), TEMPLATES, status="pending", lang=lang,
                               count=count if lang == "en" else max(1, count // 2))
    return {"added": [m["id"] for m in added], "sent_to_owner": ask_owner(added)}


def send_pending(limit: int) -> dict:
    """Send the owner up to `limit` pending memes they have not been sent yet.

    Safe to run repeatedly and while the owner is answering: a meme already sent is
    never picked again, whatever the owner has done with it since.
    """
    pool, _ = _engine()
    waiting = sorted(pool.unasked_pending(), key=lambda m: m["id"])
    sent = ask_owner(waiting[:limit])
    return {"sent_to_owner": sent, "not_yet_sent": len(waiting) - sent}


def mark_pending_asked() -> dict:
    """Mark every pending meme as already sent to the owner, without sending anything."""
    pool, _ = _engine()
    waiting = pool.unasked_pending()
    for meme in waiting:
        pool.mark_asked(meme["id"])
    return {"marked": len(waiting)}


@cache
def _api() -> Api:
    pool, limits = _engine()
    return Api(pool, limits, get_llm, TEMPLATES, get_bot, _feedback(), THEMES)


def set_telegram_webhook(url: str) -> dict:
    """Point the bot at this API. Run once after storing the token (see README)."""
    from dharmeme.telegram import COMMANDS, TelegramApi, webhook_secret

    token = _telegram_token()
    if token is None:
        return {"ok": False, "error": "no bot token in the parameter store"}
    telegram = TelegramApi(token)
    result = telegram.call("setWebhook", {
        "url": url.rstrip("/") + "/telegram",
        "secret_token": webhook_secret(token),
        "allowed_updates": ["message", "callback_query"],
    })
    telegram.call("setMyCommands", {"commands": COMMANDS})
    bot = telegram.call("getMe", {})["result"]
    return {"ok": result.get("ok", False), "bot": bot.get("username")}


def handler(event, context):
    # The daily schedule, or a direct `aws lambda invoke` (which needs IAM permission).
    # A Function URL request always arrives wrapped in requestContext, so it can never
    # reach this branch.
    if "requestContext" not in event:
        if event.get("admin") == "set_telegram_webhook":
            return set_telegram_webhook(event["url"])
        if event.get("admin") == "generate":  # optional "langs": ["zh"] to run one
            return generate(tuple(event.get("langs") or ("en", "zh")))
        if event.get("admin") == "send_pending":
            return send_pending(int(event.get("limit", 20)))
        if event.get("admin") == "mark_pending_asked":
            return mark_pending_asked()
        return {"ok": False, "error": "unknown admin event"}
    return _api().handle(event)
