"""Themes — the fixed list of subjects a visitor can ask for a meme about (themes/*.yaml).

The public picks a theme; it never types a topic. Loaded from YAML at build time; the
Lambda and the site get the same list as JSON.
"""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parents[2] / "themes"
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LUNAR_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|30)$")

# A seasonal theme (one with `lunar` dates) is offered from two weeks before its festival
# until a few days after, and not the rest of the year.
DAYS_BEFORE, DAYS_AFTER = 14, 3
YEARS_AHEAD = 6  # festival dates are worked out at build time for this many years
SGT = timezone(timedelta(hours=8))


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
        if "lunar" in theme:
            if not theme["lunar"] or not all(LUNAR_RE.match(str(d)) for d in theme["lunar"]):
                raise ThemeError(f"{where}: lunar must be a list of MM-DD lunar dates")
            theme["dates"] = festival_dates(theme.pop("lunar"))
    if not themes:
        raise ThemeError("no themes")
    return themes


def simplified(themes: list[dict]) -> list[dict]:
    """The same themes in Simplified characters: same ids, same content."""
    from .prompt import to_simplified

    return [{**t, "label": to_simplified(t["label"]), "brief": to_simplified(t["brief"])}
            for t in themes]


def as_topic(theme: dict) -> str:
    """What the model is told when a visitor picks this theme."""
    return f"{theme['label']}. {theme['brief']}"


def festival_dates(lunar: list[str], first_year: int | None = None) -> list[str]:
    """The Gregorian dates, as YYYY-MM-DD, of lunar MM-DD dates over the next few years,
    starting with last year so a festival in early January is still found in December."""
    from lunardate import LunarDate  # build time only; the Lambda and site get the dates

    start = (first_year or date.today().year) - 1
    found = []
    for year in range(start, start + YEARS_AHEAD + 1):
        for md in lunar:
            month, day = (int(x) for x in md.split("-"))
            try:
                found.append(LunarDate(year, month, day).to_solar_date().isoformat())
            except ValueError:  # day 30 in a 29-day month
                continue
    return sorted(set(found))


def today_sgt() -> date:
    return datetime.now(SGT).date()


def in_season(theme: dict, today: date) -> bool:
    """Evergreen themes always; a festival theme only near one of its dates."""
    if "dates" not in theme:
        return True
    return any(-DAYS_AFTER <= (date.fromisoformat(d) - today).days <= DAYS_BEFORE
               for d in theme["dates"])


def offered(themes: list[dict], today: date | None = None) -> list[dict]:
    """The themes to offer today: festivals in season first, then the evergreen ones."""
    today = today or today_sgt()
    current = [t for t in themes if in_season(t, today)]
    return [t for t in current if "dates" in t] + [t for t in current if "dates" not in t]
