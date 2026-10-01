"""Template catalog — load templates/catalog.yaml, validate it, resolve styles.

Styles cascade: catalog `defaults.style` <- template `style` <- slot `style`, so every
slot comes out with a complete style and the renderer never has to merge anything.
"""
import re
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "templates" / "catalog.yaml"

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLOT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REQUIRED = ("id", "name", "image", "format", "slots")
BASE_STYLE = {"color": "white", "stroke": "black", "align": "center", "uppercase": True}
ALIGNS = {"left", "center", "right"}


class CatalogError(ValueError):
    pass


def load_catalog(path: Path | str = CATALOG_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    defaults = {**BASE_STYLE, **(raw.get("defaults") or {}).get("style", {})}
    templates = [_resolve(t, defaults) for t in raw.get("templates") or []]
    _validate(templates)
    return templates


def by_id(templates: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in templates}


def _resolve(t: dict, defaults: dict) -> dict:
    t = dict(t)
    tpl_style = {**defaults, **(t.pop("style", None) or {})}
    t["slots"] = [
        {**s, "style": {**tpl_style, **(s.get("style") or {})}} for s in t.get("slots") or []
    ]
    t.setdefault("tags", [])
    t.setdefault("verified", False)
    return t


def _validate(templates: list[dict]) -> None:
    if not templates:
        raise CatalogError("catalog has no templates")
    seen = set()
    for t in templates:
        where = f"template {t.get('id', '?')!r}"
        for key in REQUIRED:
            if not t.get(key):
                raise CatalogError(f"{where}: missing {key!r}")
        if not ID_RE.match(t["id"]):
            raise CatalogError(f"{where}: id must be kebab-case")
        if t["id"] in seen:
            raise CatalogError(f"{where}: duplicate id")
        seen.add(t["id"])
        size = t.get("size")
        if size is not None and not (
            len(size) == 2 and all(isinstance(n, int) and n > 0 for n in size)
        ):
            raise CatalogError(f"{where}: size must be [width, height] in pixels")

        names = set()
        for s in t["slots"]:
            sw = f"{where} slot {s.get('name', '?')!r}"
            if not SLOT_RE.match(str(s.get("name", ""))):
                raise CatalogError(f"{sw}: name must be snake_case")
            if s["name"] in names:
                raise CatalogError(f"{sw}: duplicate slot name")
            names.add(s["name"])
            box = s.get("box")
            if not (isinstance(box, list) and len(box) == 4):
                raise CatalogError(f"{sw}: box must be [x, y, width, height]")
            x, y, w, h = box
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
                raise CatalogError(f"{sw}: box values must be fractions of the image")
            if x + w > 1.0001 or y + h > 1.0001:
                raise CatalogError(f"{sw}: box runs off the image")
            if not (isinstance(s.get("max_chars"), int) and s["max_chars"] > 0):
                raise CatalogError(f"{sw}: max_chars must be a positive integer")
            if s["style"]["align"] not in ALIGNS:
                raise CatalogError(f"{sw}: align must be one of {sorted(ALIGNS)}")
