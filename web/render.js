// dharmeme renderer — draws a template image and its slot text on a canvas (SPEC.md §3).
// fitText is pure (it takes a `measure` function), so it is tested in Node without a browser.

export const FONT_FAMILY = "Anton";
const LINE_HEIGHT = 1.15; // line advance as a multiple of the font size
const PAD = 0.04; // inner padding, as a fraction of the box's smaller side
const ELLIPSIS = "…";
// Chinese, Japanese and Korean characters, including their punctuation and full-width forms.
const CJK = /[⺀-鿿豈-﫿＀-￯]/;
const NO_LINE_START = "，。、！？；：」』）》〉…";
// Anton has no Chinese glyphs, so text with Chinese in it is drawn with the device's own
// heavy Chinese font: Simplified ("sc") or Traditional ("tc") faces first.
const CJK_FONTS = {
  sc: '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Heiti SC", "Source Han Sans SC", sans-serif',
  tc: '"Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Heiti TC", "Source Han Sans TC", sans-serif',
};

export function hasCjk(text) {
  return CJK.test(text);
}

// The CSS font for drawing `text` at `size`.
export function fontFor(text, size, script = "sc") {
  return hasCjk(text)
    ? `900 ${size}px ${CJK_FONTS[script] || CJK_FONTS.sc}`
    : `${size}px ${FONT_FAMILY}, Impact, "Arial Black", sans-serif`;
}

// The units a line may break between, each with whether a space came before it. A Latin
// word is one unit. Chinese has no spaces, so each character is its own unit; closing
// punctuation stays glued to the character before it, so no line starts with it.
// Keep in step with tokens() in src/dharmeme/render.py.
export function tokens(para) {
  const out = [];
  let space = false;
  let latinOpen = false;
  for (const ch of para) {
    if (/\s/.test(ch)) {
      space = true;
      latinOpen = false;
    } else if (CJK.test(ch)) {
      if (NO_LINE_START.includes(ch) && out.length && !space) {
        out[out.length - 1].text += ch;
      } else {
        out.push({ text: ch, space });
      }
      space = false;
      latinOpen = false;
    } else if (latinOpen) {
      out[out.length - 1].text += ch;
    } else {
      out.push({ text: ch, space });
      space = false;
      latinOpen = true;
    }
  }
  return out;
}

// Break text into lines no wider than maxWidth. Words wider than a whole line are split
// by character, so nothing can overflow sideways.
export function wrap(measure, text, size, maxWidth) {
  const lines = [];
  for (const para of String(text).split("\n")) {
    let line = "";
    for (const { text: word, space } of tokens(para)) {
      const candidate = line ? `${line}${space ? " " : ""}${word}` : word;
      if (measure(candidate, size) <= maxWidth) {
        line = candidate;
        continue;
      }
      if (line) lines.push(line);
      line = "";
      let rest = word;
      while (rest.length > 1 && measure(rest, size) > maxWidth) {
        let n = rest.length - 1;
        while (n > 1 && measure(rest.slice(0, n), size) > maxWidth) n--;
        lines.push(rest.slice(0, n));
        rest = rest.slice(n);
      }
      line = rest;
    }
    lines.push(line);
  }
  return lines;
}

// Find the largest font size at which `text` fits in a width x height box with every word
// whole: a word is only split across lines at minSize, when shrinking can't help any more.
// Below minSize it stops shrinking and truncates the last visible line with "…".
// Returns {fontSize, lines, lineHeight, truncated}.
export function fitText(measure, text, width, height, { maxSize, minSize = 12 } = {}) {
  const max = Math.max(minSize, Math.floor(maxSize ?? height / LINE_HEIGHT));
  const words = String(text).split("\n").flatMap((para) => tokens(para).map((t) => t.text));
  for (let size = max; size >= minSize; size--) {
    if (size > minSize && words.some((word) => measure(word, size) > width)) continue;
    const lines = wrap(measure, text, size, width);
    if (lines.length * size * LINE_HEIGHT <= height) {
      return { fontSize: size, lines, lineHeight: size * LINE_HEIGHT, truncated: false };
    }
  }
  const size = minSize;
  const lineHeight = size * LINE_HEIGHT;
  const all = wrap(measure, text, size, width);
  const room = Math.max(1, Math.floor(height / lineHeight));
  const lines = all.slice(0, room);
  if (all.length > room) {
    let last = lines[room - 1];
    while (last && measure(last + ELLIPSIS, size) > width) last = last.slice(0, -1);
    lines[room - 1] = last.trimEnd() + ELLIPSIS;
  }
  return { fontSize: size, lines, lineHeight, truncated: all.length > room };
}

// Throw unless `slots` has exactly the template's slot names, each a string.
export function checkSlots(template, slots) {
  const want = template.slots.map((s) => s.name).sort();
  const got = Object.keys(slots || {}).sort();
  if (want.join(",") !== got.join(",")) {
    throw new Error(
      `slots for ${template.id} must be [${want.join(", ")}], got [${got.join(", ")}]`,
    );
  }
  for (const [name, value] of Object.entries(slots)) {
    if (typeof value !== "string") throw new Error(`slot ${name} must be a string`);
  }
}

// Pixel rectangle (with padding) for a slot whose box is in image fractions.
export function slotRect(slot, imgW, imgH) {
  const [x, y, w, h] = slot.box;
  const pad = PAD * Math.min(w * imgW, h * imgH);
  return {
    x: x * imgW + pad,
    y: y * imgH + pad,
    w: w * imgW - 2 * pad,
    h: h * imgH - 2 * pad,
  };
}

// Draw the meme. `image` is a loaded HTMLImageElement, or null to draw a placeholder
// (used while the real template images are still missing). Sizes the canvas to the image.
// `script` picks the Chinese font family: "sc" (Simplified) or "tc" (Traditional).
export function renderMeme(canvas, template, slots, image, { debug = false, script = "sc" } = {}) {
  checkSlots(template, slots);
  const [w, h] = image
    ? [image.naturalWidth, image.naturalHeight]
    : template.size || [800, 800];
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  if (image) {
    ctx.drawImage(image, 0, 0, w, h);
  } else {
    drawPlaceholder(ctx, template, w, h);
  }

  const minSize = Math.max(12, Math.round(h * 0.03));

  for (const slot of template.slots) {
    const rect = slotRect(slot, w, h);
    if (debug) {
      ctx.save();
      ctx.strokeStyle = "#ff00aa";
      ctx.lineWidth = Math.max(2, w / 300);
      ctx.setLineDash([8, 6]);
      ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
      ctx.restore();
    }
    const style = slot.style;
    const raw = slots[slot.name].trim();
    if (!raw) continue;
    const text = style.uppercase ? raw.toUpperCase() : raw;
    // One font for the whole slot, chosen by whether its text has any Chinese in it.
    const font = (size) => fontFor(text, size, script);
    const measure = (part, size) => {
      ctx.font = font(size);
      return ctx.measureText(part).width;
    };
    const fit = fitText(measure, text, rect.w, rect.h, { minSize });
    drawLines(ctx, fit, rect, style, font(fit.fontSize));
  }
}

function drawLines(ctx, fit, rect, style, font) {
  const { fontSize, lines, lineHeight } = fit;
  ctx.save();
  ctx.font = font;
  ctx.textAlign = style.align;
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  const x =
    style.align === "left" ? rect.x : style.align === "right" ? rect.x + rect.w : rect.x + rect.w / 2;
  const top = rect.y + (rect.h - lines.length * lineHeight) / 2 + lineHeight / 2;
  lines.forEach((line, i) => {
    const y = top + i * lineHeight;
    if (style.stroke && style.stroke !== "none") {
      ctx.strokeStyle = style.stroke;
      ctx.lineWidth = Math.max(2, fontSize / 7);
      ctx.strokeText(line, x, y);
    }
    ctx.fillStyle = style.color;
    ctx.fillText(line, x, y);
  });
  ctx.restore();
}

function drawPlaceholder(ctx, template, w, h) {
  ctx.fillStyle = "#8a8f98";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#c9ccd1";
  for (const slot of template.slots) {
    const [x, y, bw, bh] = slot.box;
    ctx.fillRect(x * w, y * h, bw * w, bh * h);
  }
  const label = `${template.name} (image missing)`;
  ctx.font = "100px sans-serif";
  const size = Math.min(h / 14, (100 * w * 0.9) / ctx.measureText(label).width);
  ctx.fillStyle = "#5b6069";
  ctx.font = `${Math.round(size)}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, w / 2, h / 2);
}
