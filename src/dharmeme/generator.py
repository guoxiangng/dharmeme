"""The scheduled generator: grows the pool by a fixed number of memes a day (SPEC.md §4).

Two LLM calls per run, whatever the traffic: one writes a batch, a second one reviews
it against the tone rules. Only memes that are valid, new and pass the review are added.
"""
import json
import random
from datetime import datetime, timezone

from .prompt import TONE, MemeError, validate

SEEN_PER_TEMPLATE = 15  # existing captions shown to the writer, so it doesn't repeat them
MAX_TOKENS = 3000

WRITE = """\
You are adding ready-made memes to the pool. Write exactly one new meme for each
template listed below, on a different subject each time. Do not repeat or lightly
rephrase a meme that is already in the pool.

The character limits are hard limits and a longer text is rejected, so aim for about
half the limit; short is funnier anyway. Write plain text only, no emoji or hashtags.

Reply with JSON only, nothing before or after it:
[{"template_id": "<id>", "slots": {"<slot name>": "<text>", ...}}, ...]"""

REVIEW = """\
You are the reviewer. Another writer produced the memes below; nobody else reads them
before they are published under the owner's name, so be strict.

Fail a meme if it breaks any tone rule above, if the text does not fit the template's
joke format, if it would not make sense to someone seeing it cold, or if it is not
funny. Pass the rest.

Reply with JSON only, one entry per meme, in order:
[{"n": 1, "pass": true, "reason": "<a few words>"}, ...]"""


def _key(meme: dict) -> tuple:
    """What makes two memes the same: the template and the text, ignoring case and spacing."""
    return (meme["template_id"],
            tuple(" ".join(str(meme["slots"][k]).lower().split()) for k in sorted(meme["slots"])))


def _describe(template: dict) -> str:
    slots = ", ".join(f"{s['name']} (max {s['max_chars']} chars)" for s in template["slots"])
    return f"{template['id']}: {template['format']}\n  slots: {slots}"


def _json_list(text: str) -> list:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("no JSON list in reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("not a list")
    return data


def pick_templates(templates: list[dict], existing: list[dict], count: int) -> list[dict]:
    """The `count` templates with the fewest memes so far, so the pool stays balanced."""
    have = {t["id"]: 0 for t in templates}
    for meme in existing:
        if meme["template_id"] in have:
            have[meme["template_id"]] += 1
    order = sorted(templates, key=lambda t: (have[t["id"]], random.random()))
    return [order[i % len(order)] for i in range(count)]


def write_batch(llm, templates: list[dict], existing: list[dict], count: int) -> list[dict]:
    """Ask for one meme per chosen template; return the valid, new ones."""
    chosen = pick_templates(templates, existing, count)
    blocks = []
    for template in {t["id"]: t for t in chosen}.values():
        seen = [m["slots"] for m in existing if m["template_id"] == template["id"]]
        block = f"- {_describe(template)}"
        if seen:
            block += "\n  already in the pool: " + json.dumps(
                seen[-SEEN_PER_TEMPLATE:], ensure_ascii=False)
        blocks.append(block)
    reply = llm.complete(f"{TONE}\n\n{WRITE}", "Templates:\n" + "\n".join(blocks),
                         max_tokens=MAX_TOKENS)
    if reply.refused:
        return []
    taken = {_key(m) for m in existing}
    fresh = []
    for item in _json_list(reply.text):
        try:
            meme = validate(item, templates)
        except MemeError as exc:
            print(f"generator: dropped an invalid meme: {exc}")
            continue
        if _key(meme) in taken:
            print(f"generator: dropped a duplicate on {meme['template_id']}")
            continue
        taken.add(_key(meme))
        fresh.append(meme)
    return fresh


def review(llm, memes: list[dict], templates: list[dict]) -> list[dict]:
    """The memes the reviewer passed. An unreadable verdict passes nothing."""
    if not memes:
        return []
    formats = {t["id"]: t["format"] for t in templates}
    listing = "\n".join(
        f"{n}. template {m['template_id']} ({formats[m['template_id']]})\n"
        f"   {json.dumps(m['slots'], ensure_ascii=False)}"
        for n, m in enumerate(memes, 1)
    )
    reply = llm.complete(f"{TONE}\n\n{REVIEW}", listing, max_tokens=MAX_TOKENS)
    if reply.refused:
        return []
    verdicts = {v.get("n"): v for v in _json_list(reply.text) if isinstance(v, dict)}
    passed = []
    for n, meme in enumerate(memes, 1):
        verdict = verdicts.get(n, {})
        if verdict.get("pass") is True:
            passed.append(meme)
        else:
            print(f"generator: reviewer failed {meme['template_id']}: {verdict.get('reason')}")
    return passed


def run(pool, llm, templates: list[dict], count: int, status: str,
        now=lambda: datetime.now(timezone.utc)) -> list[dict]:
    """Write, review and add a batch to the pool with `status`. Returns what was added."""
    existing = pool.all()
    try:
        memes = review(llm, write_batch(llm, templates, existing, count), templates)
    except Exception as exc:  # noqa: BLE001 — a bad run adds nothing; tomorrow runs again
        print(f"generator: run failed: {exc!r}")
        return []
    stamp = now()
    added = []
    for n, meme in enumerate(memes, 1):
        entry = {"id": f"gen-{stamp:%Y%m%d-%H%M}-{n:02d}", **meme, "status": status,
                 "created": f"{stamp:%Y-%m-%d}"}
        pool.add(entry)
        added.append(entry)
    return added
