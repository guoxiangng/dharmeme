"""The prompt feature: topic -> a meme the LLM chose a template for and wrote (SPEC.md §5).

`write_meme` never raises for a bad model reply: it returns either a meme
({"template_id", "slots"}) or {"fallback": reason}, and the caller serves a random meme.
"""
import json

TOPIC_MAX = 200
ATTEMPTS = 2  # one retry after invalid JSON or a meme that fails validation

TONE = """\
You write captions for dharmeme, a Buddhist meme generator.

Tone: affectionate humour about the practitioner's own struggle: attachment,
impermanence, the middle way, monkey mind, karma, suffering, letting go. The joke is
on the person trying to practise, never on the teaching.
Never ridicule the Buddha, the Sangha, sacred objects, or any other religion. Never
target a group of people. If the topic can't be done within these rules, decline."""

OUTPUT = """\
Pick the one template whose joke format fits the topic best, then write the text for
every one of its slots. The character limits are hard limits and a longer text is
rejected, so aim for about half the limit; short is funnier anyway. Write plain text
only, no emoji or hashtags.

Reply with JSON only, nothing before or after it:
{"template_id": "<id>", "slots": {"<slot name>": "<text>", ...}}
or, to decline:
{"declined": true}"""


class MemeError(ValueError):
    pass


def system_prompt(templates: list[dict]) -> str:
    lines = []
    for t in templates:
        slots = ", ".join(f"{s['name']} (max {s['max_chars']} chars)" for s in t["slots"])
        lines.append(f"- {t['id']}: {t['format']}\n  slots: {slots}")
    return f"{TONE}\n\nTemplates:\n" + "\n".join(lines) + f"\n\n{OUTPUT}"


def validate(data, templates: list[dict]) -> dict:
    """Return the meme as {"template_id", "slots"}, or raise MemeError."""
    if not isinstance(data, dict):
        raise MemeError("not an object")
    template = next((t for t in templates if t["id"] == data.get("template_id")), None)
    if template is None:
        raise MemeError(f"unknown template {data.get('template_id')!r}")
    slots = data.get("slots")
    limits = {s["name"]: s["max_chars"] for s in template["slots"]}
    if not isinstance(slots, dict) or sorted(slots) != sorted(limits):
        raise MemeError(f"slots must be {sorted(limits)}")
    for name, text in slots.items():
        if not isinstance(text, str) or not text.strip():
            raise MemeError(f"{name} is empty")
        if len(text) > limits[name]:
            raise MemeError(f"{name} is {len(text)} chars, max {limits[name]}")
    return {"template_id": template["id"], "slots": {k: v.strip() for k, v in slots.items()}}


def _parse(text: str):
    """The JSON object in a reply, tolerating a code fence or stray words around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise MemeError("no JSON object in reply")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise MemeError(f"invalid JSON: {exc}") from exc


def write_meme(topic: str, llm, templates: list[dict]) -> dict:
    system = system_prompt(templates)
    user = topic
    for _ in range(ATTEMPTS):
        try:
            reply = llm.complete(system, user)
        except Exception as exc:  # noqa: BLE001 — any provider failure is a fallback
            print(f"prompt: LLM call failed: {exc!r}")
            return {"fallback": "error"}
        if reply.refused:
            return {"fallback": "declined"}
        try:
            data = _parse(reply.text)
            if isinstance(data, dict) and data.get("declined"):
                return {"fallback": "declined"}
            return validate(data, templates)
        except MemeError as exc:
            print(f"prompt: rejected reply: {exc}")
            # Tell the model what was wrong, so the retry isn't the same mistake again.
            user = (f"{topic}\n\nYour previous reply was rejected: {exc}.\n"
                    f"Previous reply: {reply.text}\nSend a corrected reply.")
    return {"fallback": "error"}
