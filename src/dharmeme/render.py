"""Server-side renderer for Telegram — the Python twin of web/render.js (SPEC.md §3).

Same rules as the browser: wrap, shrink to keep every word whole, truncate with "…" only
at the minimum size, so text never leaves its box. Keep the two files in step.
"""
import io
import re
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINE_HEIGHT = 1.15  # line advance as a multiple of the font size
PAD = 0.04  # inner padding, as a fraction of the box's smaller side
ELLIPSIS = "…"
ANCHORS = {"left": "lm", "center": "mm", "right": "rm"}
# Chinese, Japanese and Korean characters, including their punctuation and full-width forms.
CJK = re.compile(r"[⺀-鿿豈-﫿＀-￯]")
NO_LINE_START = "，。、！？；：」』）》〉…"
CJK_WEIGHT = 900  # Noto Sans TC/SC are variable fonts; memes want the heaviest weight


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text))


def tokens(para: str) -> list[tuple[str, bool]]:
    """The units a line may break between, each with whether a space came before it.

    A Latin word is one unit. Chinese has no spaces, so each character is its own unit;
    closing punctuation stays glued to the character before it, so no line starts with it.
    """
    out: list[tuple[str, bool]] = []
    space, latin_open = False, False
    for ch in para:
        if ch.isspace():
            space, latin_open = True, False
        elif CJK.match(ch):
            if ch in NO_LINE_START and out and not space:
                out[-1] = (out[-1][0] + ch, out[-1][1])
            else:
                out.append((ch, space))
            space, latin_open = False, False
        elif latin_open:
            out[-1] = (out[-1][0] + ch, out[-1][1])
        else:
            out.append((ch, space))
            space, latin_open = False, True
    return out


def wrap(measure, text: str, size: int, max_width: float) -> list[str]:
    """Break text into lines no wider than max_width; an over-wide word is split."""
    lines = []
    for para in str(text).split("\n"):
        line = ""
        for word, space in tokens(para):
            candidate = f"{line}{' ' if space else ''}{word}" if line else word
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
    words = [word for para in str(text).split("\n") for word, _ in tokens(para)]
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
    def __init__(self, images: Path, font: Path, tc_font: Path | None = None,
                 sc_font: Path | None = None) -> None:
        self.images = Path(images)
        self.font_path = str(font)
        # Traditional and Simplified text each get the font drawn for that script.
        self.cjk_paths = {"tc": tc_font and str(tc_font), "sc": sc_font and str(sc_font)}
        self.font = cache(self._load)

    def _load(self, size: int, script: str | None = None):
        """Anton for Latin text; Noto Sans TC or SC, at its heaviest, for text with
        Chinese in it (Anton has no Chinese characters)."""
        path = self.cjk_paths.get(script) if script else None
        if not path:
            return ImageFont.truetype(self.font_path, size)
        font = ImageFont.truetype(path, size)
        font.set_variation_by_axes([CJK_WEIGHT])
        return font

    def render(self, template: dict, slots: dict, script: str = "tc") -> bytes:
        """Draw the meme and return it as JPEG bytes. `script` picks the Chinese font:
        "tc" (Traditional) or "sc" (Simplified)."""
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
            cjk = script if has_cjk(text) else None
            fit = fit_text(lambda t, s: self.font(s, cjk).getlength(t), text, width, height,
                           min_size)
            size = fit["font_size"]
            line_height = size * LINE_HEIGHT
            anchor_x = {"left": left, "center": left + width / 2, "right": left + width}
            first = top + (height - len(fit["lines"]) * line_height) / 2 + line_height / 2
            stroke = style["stroke"] not in (None, "none")
            for i, line in enumerate(fit["lines"]):
                draw.text(
                    (anchor_x[style["align"]], first + i * line_height), line,
                    font=self.font(size, cjk), fill=style["color"],
                    anchor=ANCHORS[style["align"]],
                    # The canvas strokes a line centred on the outline; Pillow's width is
                    # the outward half only.
                    stroke_width=round(max(2, size / 7) / 2) if stroke else 0,
                    stroke_fill=style["stroke"] if stroke else None,
                )
        out = io.BytesIO()
        image.save(out, "JPEG", quality=90)
        return out.getvalue()
