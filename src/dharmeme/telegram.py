"""Telegram front end over the same engine as the website (SPEC.md §8).

    /random           a meme from the approved pool (no LLM)
    /meme             a list of themes to tap; the model writes a fresh meme on the one chosen
    /chineserandom    a meme from the approved Chinese pool, in Simplified characters
    /chinesememe      a list of Chinese themes to tap, in Simplified characters
    /chineserandom_tw, /chinesememe_tw   the same two, in Traditional characters

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
from .prompt import HANS, TOPIC_MAX, to_simplified, write_meme
from .themes import as_topic

HELP = (
    "dharmeme: Buddhist memes. All memes are impermanent.\n\n"
    "/random - a random meme\n"
    "/meme - pick a theme and get a fresh one\n"
    "/chineserandom - 随机中文梗图（简体）\n"
    "/chinesememe - 选主题，现写一张（简体）\n"
    "/chineserandom_tw · /chinesememe_tw - 繁體版"
)
PICK = "Pick a theme:"
RANDOM_ZH = "random"  # the "any" button in a Chinese list: a meme from the Chinese pool
MESSAGES_ZH = {
    "limit": "今天的梗圖發完了。諸行無常，明天再來。",
    "declined": "這個題目，還是保持聖默然吧。",
    "error": "剛剛打妄想了，請再試一次。",
}
MESSAGES_HANS = {
    "limit": "今天的梗图发完了。诸行无常，明天再来。",
    "declined": "这个题目，还是保持圣默然吧。",
    "error": "刚刚打妄想了，请再试一次。",
}
# Callback data is a 3-character prefix followed by a meme id or a theme id.
APPROVE, REJECT = "ok:", "no:"  # the owner's buttons
UP, DOWN, REPORT = "up:", "dn:", "rp:"  # everyone's buttons under a pool meme
VOTES = {UP: "up", DOWN: "down", REPORT: "report"}
THEME = "th:"  # a button in the English theme list
# The Chinese feature in its two scripts: same themes, same pool, same context. Chinese
# is stored once, in Traditional ("zh"); Simplified is that text converted.
CHINESE = {
    "zh": {"prefix": "zh:", "script": "tc", "pick": "選一個主題：", "random": "隨機一張",
           "working": "{label}：參究中…", "gone": "這個主題不在了。", "report": "檢舉",
           "empty": "梗圖庫還是空的。用 /chinesememe_tw 選個主題吧。", "messages": MESSAGES_ZH},
    HANS: {"prefix": "zs:", "script": "sc", "pick": "选一个主题：", "random": "随机一张",
           "working": "{label}：参究中…", "gone": "这个主题不在了。", "report": "举报",
           "empty": "梗图库还是空的。用 /chinesememe 选个主题吧。", "messages": MESSAGES_HANS},
}
# command -> (what it does, in which script)
CHINESE_COMMANDS = {
    "/chineserandom": ("random", HANS), "/chineserandom_tw": ("random", "zh"),
    "/chinesememe": ("themes", HANS), "/chinesememe_tw": ("themes", "zh"),
}
THEME_PREFIXES = {THEME: "en", **{c["prefix"]: lang for lang, c in CHINESE.items()}}
OWNER_READS = HANS  # the script pending Chinese memes are shown to the owner in
COMMANDS = [
    {"command": "random", "description": "A random meme"},
    {"command": "meme", "description": "Pick a theme and get a fresh one"},
    {"command": "chineserandom", "description": "随机中文梗图（简体）"},
    {"command": "chinesememe", "description": "选主题，现写一张（简体）"},
    {"command": "chineserandom_tw", "description": "隨機中文梗圖（繁體）"},
    {"command": "chinesememe_tw", "description": "選主題，現寫一張（繁體）"},
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
                 themes: list[dict] = (), themes_zh: list[dict] = (),
                 themes_hans: list[dict] = ()) -> None:
        self.themes = {
            "en": {t["id"]: t for t in themes},
            "zh": {t["id"]: t for t in themes_zh},
            HANS: {t["id"]: t for t in themes_hans},
        }
        self.pool = pool
        self.limits = limits
        self.get_llm = get_llm
        self.templates = {t["id"]: t for t in templates}
        self.renderer = renderer
        self.telegram = telegram
        self.owner_chat_id = owner_chat_id  # the only chat that is asked to approve memes
        self.feedback = feedback  # None = memes are sent without vote buttons

    def draw(self, meme: dict, lang: str = "en") -> bytes:
        """The meme as a picture. A Chinese meme is drawn in the script of `lang`."""
        slots, script = meme["slots"], "tc"
        if lang in CHINESE:
            script = CHINESE[lang]["script"]
            if lang == HANS:
                slots = {name: to_simplified(text) for name, text in slots.items()}
        return self.renderer.render(self.templates[meme["template_id"]], slots, script)

    def ask_owner(self, meme: dict, caption: str = "Pending. Publish it?",
                  labels: tuple[str, str] = ("Approve", "Reject")) -> None:
        """Send the owner a meme to decide on: two buttons, in their chat only."""
        if self.owner_chat_id is None:
            return
        buttons = [{"text": label, "callback_data": f"{prefix}{meme['id']}"}
                   for label, prefix in zip(labels, (APPROVE, REJECT))]
        lang = OWNER_READS if meme.get("lang") == "zh" else "en"
        self.telegram.send_photo(self.owner_chat_id, self.draw(meme, lang), caption,
                                 {"inline_keyboard": [buttons]})

    def ask_owner_to_review(self, meme: dict, reason: str) -> None:
        """A live meme was reported or rated poorly: keep it in the pool, or remove it?"""
        self.ask_owner(meme, f"{reason} Keep it in the pool?", ("Keep", "Remove"))

    def handle_button(self, query: dict) -> None:
        data = query.get("data") or ""
        prefix, meme_id = data[:3], data[3:]
        if prefix in VOTES:
            self.handle_vote(query, VOTES[prefix], meme_id)
        elif prefix in THEME_PREFIXES:
            self.handle_theme(query, meme_id, THEME_PREFIXES[prefix])
        else:
            self.handle_decision(query, prefix, meme_id)

    def answer(self, query: dict, text: str) -> None:
        """Show the small notice on a button press. Telegram rejects this once the press
        is more than a few seconds old; that must not stop the action itself."""
        try:
            self.telegram.call("answerCallbackQuery",
                               {"callback_query_id": query["id"], "text": text})
        except Exception as exc:  # noqa: BLE001
            print(f"telegram: could not answer a button press: {exc!r}")

    def send_theme_list(self, chat_id: int, lang: str = "en") -> None:
        if lang in CHINESE:
            ui = CHINESE[lang]
            prefix, text, per_row = ui["prefix"], ui["pick"], 3
            buttons = [{"text": ui["random"], "callback_data": f"{prefix}{RANDOM_ZH}"}]
        else:
            prefix, text, per_row, buttons = THEME, PICK, 2, []
        buttons += [{"text": t["label"], "callback_data": f"{prefix}{t['id']}"}
                    for t in self.themes[lang].values()]
        rows = [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]
        self.telegram.call("sendMessage", {"chat_id": chat_id, "text": text,
                                           "reply_markup": {"inline_keyboard": rows}})

    def chinese_pool(self) -> list[dict]:
        return [m for m in self.pool.approved("zh") if m["template_id"] in self.templates]

    def handle_theme(self, query: dict, theme_id: str, lang: str = "en") -> None:
        """A tap on a theme: write a fresh meme on it for the chat the list is in."""
        chat_id = ((query.get("message") or {}).get("chat") or {}).get("id")
        themes = self.themes[lang]
        if lang in CHINESE and theme_id == RANDOM_ZH:
            # 隨機一張: a vetted meme from the Chinese pool, with no LLM call. Until the
            # pool has any, a fresh one on a random theme.
            pool = self.chinese_pool()
            if pool and chat_id is not None:
                self.answer(query, CHINESE[lang]["random"])
                self.send(chat_id, random.choices(pool, [weight(m) for m in pool])[0],
                          lang=lang)
                return
            theme_id = random.choice(list(themes)) if themes else ""
        theme = themes.get(theme_id)
        if lang in CHINESE:
            ui = CHINESE[lang]
            note = ui["working"].format(label=theme["label"]) if theme else ui["gone"]
        else:
            note = f"{theme['label']}: contemplating…" if theme else "That theme is gone."
        self.answer(query, note)
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
        self.answer(query, text)

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
        self.answer(query, text)
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
        elif command in CHINESE_COMMANDS:
            action, lang = CHINESE_COMMANDS[command]
            if action == "random":
                self.send_chinese_random(chat_id, lang)
            else:
                self.send_theme_list(chat_id, lang)
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

    def send(self, chat_id: int, meme: dict, caption: str = "", lang: str = "en") -> None:
        markup = None
        if self.feedback is not None and "id" in meme:  # a pool meme; fresh memes have no id
            report = CHINESE[lang]["report"] if lang in CHINESE else "Report"
            buttons = [{"text": label, "callback_data": f"{prefix}{meme['id']}"}
                       for label, prefix in (("👍", UP), ("👎", DOWN), (report, REPORT))]
            markup = {"inline_keyboard": [buttons]}
        self.telegram.send_photo(chat_id, self.draw(meme, lang), caption, markup)

    def send_random(self, chat_id: int, caption: str = "") -> None:
        memes = [m for m in self.pool.approved() if m["template_id"] in self.templates]
        if not memes:
            self.telegram.send_message(chat_id, caption or "The meme pool is empty.")
            return
        self.send(chat_id, random.choices(memes, [weight(m) for m in memes])[0], caption)

    def send_chinese_random(self, chat_id: int, lang: str) -> None:
        """/chineserandom: a vetted meme from the Chinese pool, with no LLM call."""
        pool = self.chinese_pool()
        if not pool:
            self.telegram.send_message(chat_id, CHINESE[lang]["empty"])
            return
        self.send(chat_id, random.choices(pool, [weight(m) for m in pool])[0], lang=lang)

    def send_fresh(self, chat_id: int, topic: str, voter: str, lang: str = "en") -> None:
        """Have the model write a meme on `topic` and send it, within `voter`'s limit.

        Any fallback (limit reached, declined, error) is a short message with a meme from
        the pool of that language, or the message alone if that pool is empty.
        """
        result = ({"fallback": "limit"} if not self.limits.allow(voter) else
                  write_meme(topic, self.get_llm(), list(self.templates.values()), lang))
        if "fallback" not in result:
            self.send(chat_id, result, lang=lang)
            return
        if lang not in CHINESE:
            self.send_random(chat_id, MESSAGES[result["fallback"]])
            return
        message = CHINESE[lang]["messages"][result["fallback"]]
        pool = self.chinese_pool()
        if pool:
            self.send(chat_id, random.choice(pool), message, lang)
        else:
            self.telegram.send_message(chat_id, message)
