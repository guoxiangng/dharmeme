"""Telegram front end over the same engine as the website (SPEC.md §8).

    /random   a meme from the approved pool (no LLM)
    /meme     a list of themes to tap; the model writes a fresh meme on the one chosen

The public picks a theme and never types a topic. Only the owner's chat may send free
text as a topic. A fresh meme counts against the same limits as the website, per user
instead of per IP. Telegram needs a real image, so memes are drawn here with render.py.
"""
import hashlib
import json
import random
import urllib.request
import uuid

from .api import MESSAGES
from .feedback import weight
from .prompt import TOPIC_MAX, write_meme
from .themes import as_topic

HELP = (
    "dharmeme: Buddhist memes. All memes are impermanent.\n\n"
    "/random - a random meme\n"
    "/meme - pick a theme and get a fresh one\n"
    "/chinesememe - 中文梗圖（漢傳佛教、人間佛教）"
)
PICK = "Pick a theme:"
PICK_ZH = "選一個主題："
RANDOM_ZH = "random"  # the "any theme" button in the Chinese list
# The Chinese feature has no pool to fall back on, so a fallback is a message alone.
MESSAGES_ZH = {
    "limit": "今天的梗圖發完了。諸行無常，明天再來。",
    "declined": "這個題目，還是保持聖默然吧。",
    "error": "剛剛打妄想了，請再試一次。",
}
# Callback data is a 3-character prefix followed by a meme id or a theme id.
APPROVE, REJECT = "ok:", "no:"  # the owner's buttons
UP, DOWN, REPORT = "up:", "dn:", "rp:"  # everyone's buttons under a pool meme
VOTES = {UP: "up", DOWN: "down", REPORT: "report"}
THEME, THEME_ZH = "th:", "zh:"  # a button in the English / Chinese theme list
COMMANDS = [
    {"command": "random", "description": "A random meme"},
    {"command": "meme", "description": "Pick a theme and get a fresh one"},
    {"command": "chinesememe", "description": "中文梗圖"},
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
                 owner_chat_id: int | None = None, feedback=None,
                 themes: list[dict] = (), themes_zh: list[dict] = ()) -> None:
        self.themes = {t["id"]: t for t in themes}
        self.themes_zh = {t["id"]: t for t in themes_zh}
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
        elif prefix in (THEME, THEME_ZH):
            self.handle_theme(query, meme_id, "zh" if prefix == THEME_ZH else "en")
        else:
            self.handle_decision(query, prefix, meme_id)

    def send_theme_list(self, chat_id: int, lang: str = "en") -> None:
        if lang == "zh":
            themes, prefix, text, per_row = self.themes_zh, THEME_ZH, PICK_ZH, 3
            buttons = [{"text": "隨機一張", "callback_data": f"{THEME_ZH}{RANDOM_ZH}"}]
        else:
            themes, prefix, text, per_row = self.themes, THEME, PICK, 2
            buttons = []
        buttons += [{"text": t["label"], "callback_data": f"{prefix}{t['id']}"}
                    for t in themes.values()]
        rows = [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]
        self.telegram.call("sendMessage", {"chat_id": chat_id, "text": text,
                                           "reply_markup": {"inline_keyboard": rows}})

    def handle_theme(self, query: dict, theme_id: str, lang: str = "en") -> None:
        """A tap on a theme: write a fresh meme on it for the chat the list is in."""
        chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
        themes = self.themes_zh if lang == "zh" else self.themes
        if lang == "zh" and theme_id == RANDOM_ZH and themes:
            theme_id = random.choice(list(themes))
        theme = themes.get(theme_id)
        if lang == "zh":
            note = f"{theme['label']}：參究中…" if theme else "這個主題不在了。"
        else:
            note = f"{theme['label']}: contemplating…" if theme else "That theme is gone."
        self.telegram.call("answerCallbackQuery", {"callback_query_id": query["id"],
                                                   "text": note})
        if theme and chat_id is not None:
            voter = f"tg-{(query.get('from') or {}).get('id')}"
            self.send_fresh(chat_id, as_topic(theme), voter, lang)

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
        elif command == "/chinesememe":
            self.send_theme_list(chat_id, "zh")
        elif command.startswith("/") and command != "/meme":
            self.telegram.send_message(chat_id, HELP)
        else:
            # Free text is a topic only in the owner's own chat; everyone else gets the
            # theme list, so nothing a stranger types reaches the model.
            topic = rest.strip() if command == "/meme" else text
            if topic and chat_id == self.owner_chat_id and len(topic) <= TOPIC_MAX:
                self.send_fresh(chat_id, topic, f"tg-{chat_id}")
            else:
                self.send_theme_list(chat_id)

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

    def send_fresh(self, chat_id: int, topic: str, voter: str, lang: str = "en") -> None:
        """Have the model write a meme on `topic` and send it, within `voter`'s limit."""
        if lang == "zh":
            result = ({"fallback": "limit"} if not self.limits.allow(voter) else
                      write_meme(topic, self.get_llm(), list(self.templates.values()), "zh"))
            if "fallback" in result:
                self.telegram.send_message(chat_id, MESSAGES_ZH[result["fallback"]])
            else:
                self.send(chat_id, result)
            return
        if not self.limits.allow(voter):
            self.send_random(chat_id, MESSAGES["limit"])
            return
        result = write_meme(topic, self.get_llm(), list(self.templates.values()))
        if "fallback" in result:
            self.send_random(chat_id, MESSAGES[result["fallback"]])
            return
        self.send(chat_id, result)
