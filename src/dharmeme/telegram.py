"""Telegram front end over the same engine as the website (SPEC.md §8).

    /random         a meme from the approved pool (no LLM)
    /meme <topic>   a meme for the topic; plain text without a command means the same

The prompt feature counts against the same limits as the website, per chat instead of
per IP. Telegram needs a real image, so memes are drawn here with render.py.
"""
import hashlib
import json
import random
import urllib.request
import uuid

from .api import MESSAGES
from .prompt import TOPIC_MAX, write_meme

HELP = (
    "dharmeme: Buddhist memes. All memes are impermanent.\n\n"
    "/random - a random meme\n"
    "/meme <topic> - a meme about your topic\n\n"
    "Or just send me a topic."
)
REMOVE = "rm:"  # callback data prefix on the owner's Remove button
COMMANDS = [
    {"command": "random", "description": "A random meme"},
    {"command": "meme", "description": "A meme about your topic"},
]


def webhook_secret(token: str) -> str:
    """The secret Telegram sends back with each update, derived from the bot token."""
    return hashlib.sha256(f"dharmeme-webhook:{token}".encode()).hexdigest()[:48]


class TelegramApi:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.base + method, data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def send_message(self, chat_id: int, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_photo(self, chat_id: int, photo: bytes, caption: str = "",
                   reply_markup: dict | None = None) -> None:
        boundary = uuid.uuid4().hex
        parts = [("chat_id", str(chat_id))] + ([("caption", caption)] if caption else [])
        if reply_markup:
            parts.append(("reply_markup", json.dumps(reply_markup)))
        body = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in parts
        )
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
            f'filename="meme.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode() + photo + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            self.base + "sendPhoto", data=body,
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=30):
            pass


class Bot:
    def __init__(self, pool, limits, get_llm, templates: list[dict], renderer, telegram,
                 owner_chat_id: int | None = None) -> None:
        self.pool = pool
        self.limits = limits
        self.get_llm = get_llm
        self.templates = {t["id"]: t for t in templates}
        self.renderer = renderer
        self.telegram = telegram
        self.owner_chat_id = owner_chat_id  # gets the generator's memes, and may remove them

    def notify_new(self, meme: dict) -> None:
        """Show the owner a meme the generator just added, with a button to remove it."""
        button = {"text": "Remove", "callback_data": f"{REMOVE}{meme['id']}"}
        photo = self.renderer.render(self.templates[meme["template_id"]], meme["slots"])
        self.telegram.send_photo(self.owner_chat_id, photo, "New in the pool.",
                                 {"inline_keyboard": [[button]]})

    def handle_button(self, query: dict) -> None:
        data = query.get("data") or ""
        chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
        if chat_id != self.owner_chat_id or not data.startswith(REMOVE):
            text = "Not allowed."
        elif self.pool.set_status(data[len(REMOVE):], "rejected"):
            text = "Removed from the pool."
        else:
            text = "That meme is not in the pool."
        self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": text})

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            self.handle_button(update["callback_query"])
            return
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat_id = (message.get("chat") or {}).get("id")
        if not text or chat_id is None:
            return  # photos, stickers, edits, joins: nothing to do
        command, _, rest = text.partition(" ")
        command = command.split("@")[0].lower()  # "/meme@dharmeme_bot" in groups
        if command in ("/start", "/help"):
            self.telegram.send_message(chat_id, HELP)
        elif command == "/id":  # for setting OwnerChatId in the SAM template
            self.telegram.send_message(chat_id, f"This chat's id is {chat_id}")
        elif command == "/random":
            self.send_random(chat_id)
        elif command == "/meme":
            self.send_for_topic(chat_id, rest.strip())
        elif command.startswith("/"):
            self.telegram.send_message(chat_id, HELP)
        else:
            self.send_for_topic(chat_id, text)

    def send(self, chat_id: int, meme: dict, caption: str = "") -> None:
        photo = self.renderer.render(self.templates[meme["template_id"]], meme["slots"])
        self.telegram.send_photo(chat_id, photo, caption)

    def send_random(self, chat_id: int, caption: str = "") -> None:
        memes = [m for m in self.pool.approved() if m["template_id"] in self.templates]
        if not memes:
            self.telegram.send_message(chat_id, caption or "The meme pool is empty.")
            return
        self.send(chat_id, random.choice(memes), caption)

    def send_for_topic(self, chat_id: int, topic: str) -> None:
        if not 1 <= len(topic) <= TOPIC_MAX:
            self.telegram.send_message(
                chat_id, f"Send a topic of up to {TOPIC_MAX} characters, e.g. /meme my inbox")
            return
        if not self.limits.allow(f"tg-{chat_id}"):
            self.send_random(chat_id, MESSAGES["limit"])
            return
        result = write_meme(topic, self.get_llm(), list(self.templates.values()))
        if "fallback" in result:
            self.send_random(chat_id, MESSAGES[result["fallback"]])
            return
        self.send(chat_id, result)
