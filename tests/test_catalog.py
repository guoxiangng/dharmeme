import json
import struct

import pytest
import yaml

from dharmeme.catalog import CatalogError, by_id, load_catalog


def write(tmp_path, data):
    p = tmp_path / "catalog.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def template(**over):
    t = {
        "id": "drake",
        "name": "Drake",
        "image": "drake.jpg",
        "format": "Reject top, prefer bottom.",
        "slots": [
            {"name": "rejected", "box": [0.5, 0, 0.5, 0.5], "max_chars": 60},
            {"name": "preferred", "box": [0.5, 0.5, 0.5, 0.5], "max_chars": 60},
        ],
    }
    t.update(over)
    return t


def test_real_catalog_loads():
    templates = load_catalog()
    assert len(templates) >= 10
    for t in templates:
        for s in t["slots"]:
            assert set(s["style"]) >= {"color", "stroke", "align", "uppercase"}


def test_styles_cascade(tmp_path):
    t = template(style={"color": "black"})
    t["slots"][1]["style"] = {"stroke": "none"}
    data = {"defaults": {"style": {"uppercase": False}}, "templates": [t]}
    rejected, preferred = load_catalog(write(tmp_path, data))[0]["slots"]
    assert rejected["style"] == {
        "color": "black", "stroke": "black", "align": "center", "uppercase": False,
    }
    assert preferred["style"]["stroke"] == "none"
    assert preferred["style"]["color"] == "black"


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "Not Kebab"},
        {"format": ""},
        {"size": [100]},
        {"slots": [{"name": "x", "box": [0.6, 0, 0.5, 0.5], "max_chars": 10}]},  # off image
        {"slots": [{"name": "x", "box": [0, 0, 50, 50], "max_chars": 10}]},  # pixels
        {"slots": [{"name": "x", "box": [0, 0, 0.5, 0.5], "max_chars": 0}]},
        {"slots": [{"name": "Bad-Name", "box": [0, 0, 0.5, 0.5], "max_chars": 10}]},
        {"slots": [{"name": "x", "box": [0, 0, 0.5, 0.5], "max_chars": 10}] * 2},
    ],
)
def test_invalid_templates_rejected(tmp_path, bad):
    with pytest.raises(CatalogError):
        load_catalog(write(tmp_path, {"templates": [template(**bad)]}))


def test_duplicate_ids_rejected(tmp_path):
    with pytest.raises(CatalogError):
        load_catalog(write(tmp_path, {"templates": [template(), template()]}))


def test_by_id():
    assert "drake" in by_id(load_catalog())


def test_site_build_publishes_only_approved_memes(tmp_path, monkeypatch):
    import build_site

    bank = tmp_path / "memes.jsonl"
    rows = [
        {"id": "d1", "template_id": "drake", "slots": {"rejected": "a", "preferred": "b"},
         "status": "approved"},
        {"id": "d2", "template_id": "drake", "slots": {"rejected": "c", "preferred": "d"},
         "status": "pending"},
        {"id": "d3", "template_id": "drake", "slots": {"rejected": "e", "preferred": "f"},
         "status": "rejected"},
    ]
    bank.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    memes = build_site.approved_memes(bank, {"drake"})
    assert [m["id"] for m in memes] == ["d1"]
    assert "status" not in memes[0]


def test_bank_problems(tmp_path):
    import build_site

    templates = load_catalog(write(tmp_path, {"templates": [template()]}))
    good = {"id": "d1", "template_id": "drake", "status": "pending",
            "slots": {"rejected": "a", "preferred": "b"}}
    assert build_site.bank_problems([good], templates) == []

    bad = [
        good,
        dict(good),  # duplicate id
        dict(good, id="d2", slots={"rejected": "a"}),  # missing slot
        dict(good, id="d3", slots={"rejected": " ", "preferred": "x" * 61}),
        dict(good, id="d4", status="maybe"),
    ]
    problems = build_site.bank_problems(bad, templates)
    assert [p.split(":")[0] for p in problems] == ["d1", "d2", "d3", "d3", "d4"]


def test_real_bank_matches_catalog():
    import build_site

    templates = load_catalog()
    entries = build_site.bank_entries(build_site.ROOT / "seed" / "memes.jsonl",
                                      {t["id"] for t in templates})
    assert build_site.bank_problems(entries, templates) == []


def png(width, height):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


def test_image_problems_reports_missing_and_wrong_size(tmp_path):
    import build_site

    templates = [
        template(id="ok", image="ok.png", size=[100, 50]),
        template(id="gone", image="gone.png", size=[100, 50]),
        template(id="resized", image="resized.png", size=[100, 50]),
    ]
    (tmp_path / "ok.png").write_bytes(png(100, 50))
    (tmp_path / "resized.png").write_bytes(png(200, 100))
    problems = build_site.image_problems(templates, tmp_path)
    assert len(problems) == 2
    assert "gone.png is missing" in problems[0]
    assert "200x100" in problems[1]


def test_site_build_rejects_unknown_template(tmp_path):
    import build_site

    bank = tmp_path / "memes.jsonl"
    bank.write_text(json.dumps({"id": "x", "template_id": "nope", "slots": {},
                                "status": "approved"}) + "\n")
    with pytest.raises(SystemExit):
        build_site.approved_memes(bank, {"drake"})
