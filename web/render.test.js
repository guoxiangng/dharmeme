// Run with: node --test web/
import { test } from "node:test";
import assert from "node:assert/strict";

import { checkSlots, fitText, fontFor, hasCjk, slotRect, tokens, wrap } from "./render.js";

// Monospace stand-in for canvas measureText: every character is half the font size wide.
const measure = (text, size) => text.length * size * 0.5;

const fitsInside = (fit, width, height) =>
  fit.lines.every((l) => measure(l, fit.fontSize) <= width) &&
  fit.lines.length * fit.lineHeight <= height;

test("short text gets a large font and stays inside the box", () => {
  const fit = fitText(measure, "Letting go", 400, 200);
  assert.ok(fit.fontSize > 40);
  assert.ok(fitsInside(fit, 400, 200));
  assert.equal(fit.truncated, false);
});

test("a 60-char slot fits its box without truncation", () => {
  const text = "When you finally let go of attachment but the WiFi drops ok";
  const fit = fitText(measure, text, 400, 300, { minSize: 12 });
  assert.equal(fit.truncated, false);
  assert.ok(fitsInside(fit, 400, 300));
  assert.equal(fit.lines.join(" "), text);
});

test("a 500-char text shrinks to the minimum and is truncated with an ellipsis", () => {
  const text = "suffering ".repeat(50).trim();
  const fit = fitText(measure, text, 200, 60, { minSize: 12 });
  assert.equal(fit.fontSize, 12);
  assert.equal(fit.truncated, true);
  assert.ok(fit.lines.at(-1).endsWith("…"));
  assert.ok(fitsInside(fit, 200, 60));
});

test("the font shrinks to keep a long word whole instead of splitting it", () => {
  // At the size the height allows (80), "attachment" is 400 wide; it must shrink to fit 200.
  const fit = fitText(measure, "Letting go of attachment", 200, 400, { minSize: 12 });
  assert.ok(fit.lines.includes("attachment"));
  assert.equal(fit.fontSize, 40);
  assert.ok(fitsInside(fit, 200, 400));
});

// Chinese: every character one font-size wide, like a square glyph.
const square = (text, size) => text.length * size;

test("Chinese breaks between characters and Latin words stay whole", () => {
  assert.deepEqual(tokens("放下執著").map((t) => t.text), ["放", "下", "執", "著"]);
  assert.deepEqual(tokens("Me 說 OK"), [
    { text: "Me", space: false }, { text: "說", space: true }, { text: "OK", space: true }]);
  assert.deepEqual(wrap(square, "今天一定專心念佛", 10, 40), ["今天一定", "專心念佛"]);
});

test("no line starts with closing punctuation", () => {
  assert.deepEqual(wrap(square, "念佛，打坐。", 10, 30), ["念佛，", "打坐。"]);
  assert.deepEqual(wrap(square, "念佛，打坐。", 10, 20), ["念", "佛，", "打", "坐。"]);
});

test("Chinese shrinks to fit without being cut", () => {
  const fit = fitText(square, "嘴上說放下了轉頭又撿回來", 60, 60);
  assert.equal(fit.truncated, false);
  assert.equal(fit.lines.join(""), "嘴上說放下了轉頭又撿回來");
});

test("text with Chinese gets a Chinese font for its script, Latin text gets Anton", () => {
  assert.equal(hasCjk("放下"), true);
  assert.equal(hasCjk("Letting go"), false);
  assert.match(fontFor("Letting go", 40), /^40px Anton/);
  assert.match(fontFor("放下", 40, "sc"), /^900 40px "Noto Sans SC"/);
  assert.match(fontFor("放下", 40, "tc"), /^900 40px "Noto Sans TC"/);
});

test("a word wider than the box is split instead of overflowing", () => {
  const lines = wrap(measure, "Mahāparinibbānasuttaaaaaaaaaaaaaaaa", 20, 100);
  assert.ok(lines.length > 1);
  assert.ok(lines.every((l) => measure(l, 20) <= 100));
});

test("wrap terminates when one character is wider than the box", () => {
  const lines = wrap(measure, "OM", 100, 10);
  assert.deepEqual(lines, ["O", "M"]);
});

test("explicit newlines are kept", () => {
  assert.deepEqual(wrap(measure, "a\nb", 10, 1000), ["a", "b"]);
});

const drake = {
  id: "drake",
  slots: [{ name: "rejected" }, { name: "preferred" }],
};

test("checkSlots accepts exactly the template's slot names", () => {
  checkSlots(drake, { rejected: "a", preferred: "b" });
});

test("checkSlots throws for wrong, missing or extra slots", () => {
  assert.throws(() => checkSlots(drake, { wrong: "x" }));
  assert.throws(() => checkSlots(drake, { rejected: "a" }));
  assert.throws(() => checkSlots(drake, { rejected: "a", preferred: "b", extra: "c" }));
  assert.throws(() => checkSlots(drake, { rejected: "a", preferred: 3 }));
});

test("slotRect converts fractions to padded pixels inside the box", () => {
  const r = slotRect({ box: [0.5, 0, 0.5, 0.5] }, 1000, 800);
  assert.ok(r.x > 500 && r.y > 0);
  assert.ok(r.x + r.w < 1000 && r.y + r.h < 400);
});
