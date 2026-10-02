"""Draw each template's text boxes on its image, to check them by eye.

    python scripts/check_boxes.py                    # every template
    python scripts/check_boxes.py drake bike-fall    # just these
    python scripts/check_boxes.py --out some/folder

Writes contact sheets (four templates each) and prints their paths. Use it after adding
a template: the boxes are placed by hand as fractions of the image, and this is how to
see whether they sit where the text should go. Needs Pillow (`pip install -e ".[dev]"`).
"""
import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dharmeme.catalog import load_catalog  # noqa: E402

CELL = 640
PINK = (255, 0, 170)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="template ids (default: all)")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "dharmeme-boxes")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(ROOT / "templates" / "fonts" / "Anton-Regular.ttf"), 20)

    cells = []
    for t in load_catalog():
        if args.ids and t["id"] not in args.ids:
            continue
        img = Image.open(ROOT / "templates" / "images" / t["image"]).convert("RGB")
        real_size = list(img.size)
        scale = CELL / max(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)))
        draw = ImageDraw.Draw(img)
        for s in t["slots"]:
            x, y, w, h = s["box"]
            rect = [x * img.width, y * img.height, (x + w) * img.width, (y + h) * img.height]
            draw.rectangle(rect, outline=PINK, width=3)
            draw.text((rect[0] + 5, rect[1] + 4), s["name"], fill=PINK, font=font,
                      stroke_width=2, stroke_fill=(255, 255, 255))
        cell = Image.new("RGB", (CELL, CELL + 30), "white")
        cell.paste(img, ((CELL - img.width) // 2, 30 + (CELL - img.height) // 2))
        ImageDraw.Draw(cell).text((6, 4), f"{t['id']}  {real_size}", fill="black", font=font)
        cells.append(cell)

    for n in range(0, len(cells), 4):
        group = cells[n:n + 4]
        sheet = Image.new("RGB", (CELL * 2, (CELL + 30) * ((len(group) + 1) // 2)), "white")
        for i, cell in enumerate(group):
            sheet.paste(cell, ((i % 2) * CELL, (i // 2) * (CELL + 30)))
        path = args.out / f"boxes-{n // 4 + 1}.png"
        sheet.save(path)
        print(path)


if __name__ == "__main__":
    main()
