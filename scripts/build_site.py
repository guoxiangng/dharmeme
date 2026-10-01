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
from fetch_templates import image_size  # noqa: E402

WEB_FILES = ["index.html", "app.js", "render.js", "style.css"]
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


def approved_memes(bank: Path, template_ids: set[str]) -> list[dict]:
    if not bank.exists():
        return []
    memes = []
    for n, line in enumerate(bank.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("status") != "approved":
            continue
        if entry["template_id"] not in template_ids:
            raise SystemExit(f"{bank}:{n}: unknown template {entry['template_id']!r}")
        memes.append({k: entry[k] for k in ("id", "template_id", "slots")})
    return memes


def build(out: Path = ROOT / "_site", strict: bool = False) -> Path:
    templates = load_catalog()
    problems = image_problems(templates, ROOT / "templates" / "images")
    if problems and strict:
        raise SystemExit("Template images do not match the catalog:\n  " + "\n  ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in WEB_FILES:
        shutil.copy2(ROOT / "web" / name, out / name)
    shutil.copytree(ROOT / "web" / "fonts", out / "fonts")
    shutil.copytree(
        ROOT / "templates" / "images", out / "images", ignore=shutil.ignore_patterns(".*")
    )

    catalog = [{k: t[k] for k in CATALOG_FIELDS if k in t} for t in templates]
    (out / "catalog.json").write_text(json.dumps(catalog, indent=1), encoding="utf-8")

    memes = approved_memes(ROOT / "bank" / "memes.jsonl", {t["id"] for t in templates})
    (out / "memes.json").write_text(json.dumps(memes, ensure_ascii=False), encoding="utf-8")

    print(f"Built {out}: {len(templates)} templates, {len(memes)} approved memes.")
    if problems:
        print(f"Image problems ({len(problems)}), see scripts/fetch_templates.py:")
        for p in problems:
            print(f"  {p}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="fail if a template image is missing or the wrong size")
    build(strict=parser.parse_args().strict)
