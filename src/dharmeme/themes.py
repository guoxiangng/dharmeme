"""Themes — the fixed list of subjects a visitor can ask for a meme about (themes/*.yaml).

The public picks a theme; it never types a topic. Loaded from YAML at build time; the
Lambda and the site get the same list as JSON.
"""
import re
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parents[2] / "themes"
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ThemeError(ValueError):
    pass


def load_themes(path: Path | str = THEMES_DIR / "en.yaml") -> list[dict]:
    import yaml  # only needed at build time; the Lambda reads themes.json

    with open(path, encoding="utf-8") as f:
        themes = (yaml.safe_load(f) or {}).get("themes") or []
    seen = set()
    for theme in themes:
        where = f"theme {theme.get('id', '?')!r}"
        if not ID_RE.match(str(theme.get("id", ""))):
            raise ThemeError(f"{where}: id must be kebab-case")
        if theme["id"] in seen:
            raise ThemeError(f"{where}: duplicate id")
        seen.add(theme["id"])
        for key in ("label", "brief"):
            if not str(theme.get(key, "")).strip():
                raise ThemeError(f"{where}: missing {key!r}")
        theme["brief"] = " ".join(theme["brief"].split())
    if not themes:
        raise ThemeError("no themes")
    return themes


def as_topic(theme: dict) -> str:
    """What the model is told when a visitor picks this theme."""
    return f"{theme['label']}. {theme['brief']}"
