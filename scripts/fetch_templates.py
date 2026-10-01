"""Download the template images listed in templates/catalog.yaml.

    python scripts/fetch_templates.py            # fetch missing images
    python scripts/fetch_templates.py --force    # re-download all

Each template's `url` points at the image on imgflip. Reports templates whose image
size differs from the catalog's `size` (the slot boxes may then need re-checking).
"""
import argparse
import struct
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402

IMAGES = ROOT / "templates" / "images"


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a JPEG or PNG, without needing Pillow."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return w, h
            i += 2 + length
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download existing images")
    args = parser.parse_args()

    IMAGES.mkdir(parents=True, exist_ok=True)
    failures = 0
    for t in load_catalog():
        dest = IMAGES / t["image"]
        if dest.exists() and not args.force:
            print(f"  skip  {t['id']} (already present)")
            continue
        if not t.get("url"):
            print(f"  ----  {t['id']}: no url in catalog")
            failures += 1
            continue
        try:
            req = urllib.request.Request(t["url"], headers={"User-Agent": "dharmeme/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001 — report and carry on
            print(f"  FAIL  {t['id']}: {exc}")
            failures += 1
            continue
        dest.write_bytes(data)
        size = image_size(data)
        note = ""
        if size and t.get("size") and list(size) != list(t["size"]):
            note = f"  (size {size[0]}x{size[1]}, catalog says {t['size'][0]}x{t['size'][1]})"
        print(f"  ok    {t['id']} -> {dest.name}{note}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
