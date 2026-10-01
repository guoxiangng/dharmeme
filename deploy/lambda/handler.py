"""Lambda entry point. scripts/build_lambda.py puts this file, the dharmeme package,
catalog.json, the seed memes, the template images and the font side by side in the
deployment package.
"""
import json
import os
from functools import cache
from pathlib import Path

from dharmeme.api import Api
from dharmeme.limits import Limits
from dharmeme.llm.factory import get_provider
from dharmeme.pool import Pool
from dharmeme.store import DynamoStore

HERE = Path(__file__).parent
TEMPLATES = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
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
        renderer = Renderer(HERE / "images", HERE / "Anton-Regular.ttf")
        _bot = (Bot(pool, limits, get_llm, TEMPLATES, renderer, TelegramApi(token)),
                webhook_secret(token))
    return _bot


@cache
def _api() -> Api:
    pool, limits = _engine()
    return Api(pool, limits, get_llm, TEMPLATES, get_bot)


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
        "allowed_updates": ["message"],
    })
    telegram.call("setMyCommands", {"commands": COMMANDS})
    bot = telegram.call("getMe", {})["result"]
    return {"ok": result.get("ok", False), "bot": bot.get("username")}


def handler(event, context):
    # A direct `aws lambda invoke`, which needs IAM permission; a Function URL request
    # always arrives wrapped in requestContext, so it can never reach this branch.
    if "requestContext" not in event and event.get("admin") == "set_telegram_webhook":
        return set_telegram_webhook(event["url"])
    return _api().handle(event)
