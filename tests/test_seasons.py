"""Festival themes: shown only around their dates, worked out from the lunar calendar."""
from datetime import date

import pytest

from dharmeme.themes import THEMES_DIR, ThemeError, festival_dates, load_themes, offered

VESAK = {"id": "vesak", "label": "Vesak", "brief": "b", "dates": ["2026-05-31"]}
KARMA = {"id": "karma", "label": "Karma", "brief": "b"}


def test_lunar_dates_become_the_known_gregorian_dates():
    # Lunar New Year 2026 is 17 February; Singapore's Vesak Day 2026 is 31 May.
    assert "2026-02-17" in festival_dates(["01-01"], 2026)
    assert "2026-05-31" in festival_dates(["04-15"], 2026)


def test_a_festival_is_offered_two_weeks_before_to_three_days_after_and_first():
    ids = lambda day: [t["id"] for t in offered([KARMA, VESAK], day)]  # noqa: E731
    assert ids(date(2026, 5, 17)) == ["vesak", "karma"]
    assert ids(date(2026, 6, 3)) == ["vesak", "karma"]
    assert ids(date(2026, 5, 16)) == ["karma"]
    assert ids(date(2026, 6, 4)) == ["karma"]


def test_both_theme_files_have_festivals_and_every_one_has_dates_ahead(tmp_path):
    for name in ("en", "zh"):
        festivals = [t for t in load_themes(THEMES_DIR / f"{name}.yaml") if "dates" in t]
        assert len(festivals) >= 6
        assert all(max(t["dates"]) > date.today().isoformat() for t in festivals)


def test_a_bad_lunar_date_is_refused(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("themes:\n  - {id: x, label: X, brief: b, lunar: ['13-01']}\n", encoding="utf-8")
    with pytest.raises(ThemeError):
        load_themes(bad)
