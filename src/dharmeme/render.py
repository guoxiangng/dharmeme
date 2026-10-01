"""Server-side renderer for Telegram — the Python twin of web/render.js (SPEC.md §3).

Same rules as the browser: wrap, shrink to keep every word whole, truncate with "…" only
at the minimum size, so text never leaves its box. Keep the two files in step.
"""
import io
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINE_HEIGHT = 1.15  # line advance as a multiple of the font size
PAD = 0.04  # inner padding, as a fraction of the box's smaller side
ELLIPSIS = "…"
ANCHORS = {"left": "lm", "center": "mm", "right": "rm"}


def wrap(measure, text: str, size: int, max_width: float) -> list[str]:
    """Break text into lines no wider than max_width; an over-wide word is split."""
    lines = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            candidate = f"{line} {word}" if line else word
            if measure(candidate, size) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            rest = word
            while len(rest) > 1 and measure(rest, size) > max_width:
                n = len(rest) - 1
                while n > 1 and measure(rest[:n], size) > max_width:
                    n -= 1
                lines.append(rest[:n])
                rest = rest[n:]
            line = rest
        lines.append(line)
    return lines


def fit_text(measure, text: str, width: float, height: float, min_size: int = 12) -> dict:
    """The largest font size at which `text` fits the box with every word whole."""
    largest = max(min_size, int(height / LINE_HEIGHT))
    words = str(text).split()
    for size in range(largest, min_size - 1, -1):
        if size > min_size and any(measure(word, size) > width for word in words):
            continue
        lines = wrap(measure, text, size, width)
        if len(lines) * size * LINE_HEIGHT <= height:
            return {"font_size": size, "lines": lines, "truncated": False}
    size = min_size
    every = wrap(measure, text, size, width)
    room = max(1, int(height / (size * LINE_HEIGHT)))
    lines = every[:room]
    if len(every) > room:
        last = lines[-1]
        while last and measure(last + ELLIPSIS, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + ELLIPSIS
    return {"font_size": size, "lines": lines, "truncated": len(every) > room}


class Renderer:
    def __init__(self, images: Path, font: Path) -> None:
        self.images = Path(images)
        self.font_path = str(font)
        self.font = cache(lambda size: ImageFont.truetype(self.font_path, size))

    def measure(self, text: str, size: int) -> float:
        return self.font(size).getlength(text)

    def render(self, template: dict, slots: dict) -> bytes:
        """Draw the meme and return it as JPEG bytes."""
        image = Image.open(self.images / template["image"]).convert("RGB")
        draw = ImageDraw.Draw(image)
        w, h = image.size
        min_size = max(12, round(h * 0.03))
        for slot in template["slots"]:
            raw = slots[slot["name"]].strip()
            if not raw:
                continue
            style = slot["style"]
            text = raw.upper() if style["uppercase"] else raw
            x, y, bw, bh = slot["box"]
            pad = PAD * min(bw * w, bh * h)
            left, top = x * w + pad, y * h + pad
            width, height = bw * w - 2 * pad, bh * h - 2 * pad
            fit = fit_text(self.measure, text, width, height, min_size)
            size = fit["font_size"]
            line_height = size * LINE_HEIGHT
            anchor_x = {"left": left, "center": left + width / 2, "right": left + width}
            first = top + (height - len(fit["lines"]) * line_height) / 2 + line_height / 2
            stroke = style["stroke"] not in (None, "none")
            for i, line in enumerate(fit["lines"]):
                draw.text(
                    (anchor_x[style["align"]], first + i * line_height), line,
                    font=self.font(size), fill=style["color"], anchor=ANCHORS[style["align"]],
                    # The canvas strokes a line centred on the outline; Pillow's width is
                    # the outward half only.
                    stroke_width=round(max(2, size / 7) / 2) if stroke else 0,
                    stroke_fill=style["stroke"] if stroke else None,
                )
        out = io.BytesIO()
        image.save(out, "JPEG", quality=90)
        return out.getvalue()
