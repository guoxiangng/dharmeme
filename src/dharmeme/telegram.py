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
from .feedback import weight
from .prompt import TOPIC_MAX, write_meme

HELP = (
    "dharmeme: Buddhist memes. All memes are impermanent.\n\n"
    "/random - a random meme\n"
    "/meme <topic> - a meme about your topic\n\n"
    "Or just send me a topic."
)
# Callback data is a 3-character prefix followed by the meme id.
APPROVE, REJECT = "ok:", "no:"  # the owner's buttons
UP, DOWN, REPORT = "up:", "dn:", "rp:"  # everyone's buttons under a pool meme
VOTES = {UP: "up", DOWN: "down", REPORT: "report"}
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
                 owner_chat_id: int | None = None, feedback=None) -> None:
        self.pool = pool
        self.limits = limits
        self.get_llm = get_llm
        self.templates = {t["id"]: t for t in templates}
        self.renderer = renderer
        self.telegram = telegram
        self.owner_chat_id = owner_chat_id  # the only chat that is asked to approve memes
        self.feedback = feedback  # None = memes are sent without vote buttons

    def ask_owner(self, meme: dict, caption: str = "Pending. Publish it?",
                  labels: tuple[str, str] = ("Approve", "Reject")) -> None:
        """Send the owner a meme to decide on: two buttons, in their chat only."""
        if self.owner_chat_id is None:
            return
        buttons = [{"text": label, "callback_data": f"{prefix}{meme['id']}"}
                   for label, prefix in zip(labels, (APPROVE, REJECT))]
        photo = self.renderer.render(self.templates[meme["template_id"]], meme["slots"])
        self.telegram.send_photo(self.owner_chat_id, photo, caption,
                                 {"inline_keyboard": [buttons]})

    def ask_owner_to_review(self, meme: dict, reason: str) -> None:
        """A live meme was reported or rated poorly: keep it in the pool, or remove it?"""
        self.ask_owner(meme, f"{reason} Keep it in the pool?", ("Keep", "Remove"))

    def handle_button(self, query: dict) -> None:
        data = query.get("data") or ""
        prefix, meme_id = data[:3], data[3:]
        if prefix in VOTES:
            self.handle_vote(query, VOTES[prefix], meme_id)
        else:
            self.handle_decision(query, prefix, meme_id)

    def handle_vote(self, query: dict, kind: str, meme_id: str) -> None:
        """Thumbs up, thumbs down or Report, from anyone."""
        voter = f"tg-{(query.get('from') or {}).get('id')}"
        if self.feedback is None or not self.limits.allow_vote(voter):
            text = "Not now, sorry."
        else:
            result = self.feedback.vote(voter, meme_id, kind)
            text = {"ok": "Reported. Thank you." if kind == "report" else "Thanks!",
                    "already": "You already did that for this one.",
                    "unknown": "That meme is no longer in the pool."}[result]
        self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": text})

    def handle_decision(self, query: dict, prefix: str, meme_id: str) -> None:
        """The owner's Approve/Reject (or Keep/Remove). Only their chat's presses count."""
        chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
        status = {APPROVE: "approved", REJECT: "rejected"}.get(prefix)
        if self.owner_chat_id is None or chat_id != self.owner_chat_id or status is None:
            text = "Not allowed."
        elif self.pool.set_status(meme_id, status):
            text = "In the pool." if status == "approved" else "Not in the pool."
        else:
            text = "That meme is not in the pool."
        self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": text})
        if status and text != "Not allowed.":
            # Replace the buttons with the outcome, so the chat shows what is decided.
            message = query["message"]
            self.telegram.call("editMessageCaption", {
                "chat_id": chat_id, "message_id": message.get("message_id"), "caption": text})

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
        markup = None
        if self.feedback is not None and "id" in meme:  # a pool meme; topic memes have no id
            buttons = [{"text": label, "callback_data": f"{prefix}{meme['id']}"}
                       for label, prefix in (("👍", UP), ("👎", DOWN), ("Report", REPORT))]
            markup = {"inline_keyboard": [buttons]}
        self.telegram.send_photo(chat_id, photo, caption, markup)

    def send_random(self, chat_id: int, caption: str = "") -> None:
        memes = [m for m in self.pool.approved() if m["template_id"] in self.templates]
        if not memes:
            self.telegram.send_message(chat_id, caption or "The meme pool is empty.")
            return
        self.send(chat_id, random.choices(memes, [weight(m) for m in memes])[0], caption)

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
