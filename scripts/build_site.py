"""Build the static site into _site/ (SPEC.md §9).

    python scripts/build_site.py          # then: python -m http.server -d _site 8000
    python scripts/build_site.py --strict # CI: fail on a missing or wrong-sized image

Copies the web page, the template images and the font, and writes:
- catalog.json — the resolved catalog (styles merged per slot)
- memes.json   — approved bank entries only
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402
from dharmeme.themes import THEMES_DIR, load_themes, simplified  # noqa: E402
from fetch_templates import image_size  # noqa: E402

WEB_FILES = ["index.html", "app.js", "config.js", "deck.js", "images.js", "render.js",
             "style.css"]
REVIEW_FILES = ["review.html", "review.js"]  # local only (--review), never deployed
CATALOG_FIELDS = ["id", "name", "image", "size", "format", "tags", "slots"]


def image_problems(templates: list[dict], images: Path) -> list[str]:
    """Templates whose image is missing, or not the size the slot boxes were placed on."""
    problems = []
    for t in templates:
        path = images / t["image"]
        if not path.exists():
            problems.append(f"{t['id']}: {t['image']} is missing")
            continue
        size = image_size(path.read_bytes())
        if size is None:
            problems.append(f"{t['id']}: {t['image']} is not a readable JPEG or PNG")
        elif t.get("size") and list(size) != list(t["size"]):
            problems.append(
                f"{t['id']}: {t['image']} is {size[0]}x{size[1]}, "
                f"catalog says {t['size'][0]}x{t['size'][1]}"
            )
    return problems


def bank_entries(bank: Path, template_ids: set[str]) -> list[dict]:
    """Every entry in the bank, whatever its status."""
    if not bank.exists():
        return []
    entries = []
    for n, line in enumerate(bank.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry["template_id"] not in template_ids:
            raise SystemExit(f"{bank}:{n}: unknown template {entry['template_id']!r}")
        entries.append(entry)
    return entries


def approved_memes(bank: Path, template_ids: set[str]) -> list[dict]:
    return [
        {k: entry[k] for k in ("id", "template_id", "slots")}
        for entry in bank_entries(bank, template_ids)
        if entry.get("status") == "approved"
    ]


def bank_problems(entries: list[dict], templates: list[dict]) -> list[str]:
    """Entries the renderer would reject or truncate: wrong slot names, empty or too-long text."""
    slots = {t["id"]: {s["name"]: s["max_chars"] for s in t["slots"]} for t in templates}
    problems, seen = [], set()
    for e in entries:
        if e["id"] in seen:
            problems.append(f"{e['id']}: duplicate id")
        seen.add(e["id"])
        if e.get("status") not in ("pending", "approved", "rejected"):
            problems.append(f"{e['id']}: status {e.get('status')!r}")
        want = slots[e["template_id"]]
        if sorted(e["slots"]) != sorted(want):
            problems.append(f"{e['id']}: slots must be {sorted(want)}, got {sorted(e['slots'])}")
            continue
        for name, text in e["slots"].items():
            if not text.strip():
                problems.append(f"{e['id']}: {name} is empty")
            elif len(text) > want[name]:
                problems.append(f"{e['id']}: {name} is {len(text)} chars, max {want[name]}")
    return problems


def build(out: Path = ROOT / "_site", strict: bool = False, review: bool = False) -> Path:
    templates = load_catalog()
    problems = image_problems(templates, ROOT / "templates" / "images")
    if problems and strict:
        raise SystemExit("Template images do not match the catalog:\n  " + "\n  ".join(problems))
    entries = bank_entries(ROOT / "seed" / "memes.jsonl", {t["id"] for t in templates})
    bad = bank_problems(entries, templates)
    if bad:
        raise SystemExit("Meme bank does not match the catalog:\n  " + "\n  ".join(bad))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in WEB_FILES + (REVIEW_FILES if review else []):
        shutil.copy2(ROOT / "web" / name, out / name)
    shutil.copytree(ROOT / "web" / "fonts", out / "fonts")
    shutil.copytree(
        ROOT / "templates" / "images", out / "images", ignore=shutil.ignore_patterns(".*")
    )

    catalog = [{k: t[k] for k in CATALOG_FIELDS if k in t} for t in templates]
    (out / "catalog.json").write_text(json.dumps(catalog, indent=1), encoding="utf-8")

    # The page only needs each theme's id and button label; the briefs are for the model.
    chinese = load_themes(THEMES_DIR / "zh.yaml")
    for name, themes in (("themes.json", load_themes()), ("themes_zh.json", chinese),
                         ("themes_zh_hans.json", simplified(chinese))):
        labels = [{"id": t["id"], "label": t["label"]} for t in themes]
        (out / name).write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")

    fields = ("id", "template_id", "slots")
    memes = [{k: e[k] for k in fields} for e in entries if e["status"] == "approved"]
    (out / "memes.json").write_text(json.dumps(memes, ensure_ascii=False), encoding="utf-8")
    if review:  # the whole bank, with statuses, for the review page
        bank = [{k: e[k] for k in (*fields, "status")} for e in entries]
        (out / "bank.json").write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")

    print(f"Built {out}: {len(templates)} templates, {len(memes)} approved memes "
          f"of {len(entries)} in the bank.")
    if problems:
        print(f"Image problems ({len(problems)}), see scripts/fetch_templates.py:")
        for p in problems:
            print(f"  {p}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="fail if a template image is missing or the wrong size")
    parser.add_argument("--out", type=Path, default=ROOT / "_site", help="output directory")
    parser.add_argument("--review", action="store_true",
                        help="also build the review page and the full bank (local use only)")
    args = parser.parse_args()
    build(out=args.out, strict=args.strict, review=args.review)
