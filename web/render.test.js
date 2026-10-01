// Run with: node --test web/
import { test } from "node:test";
import assert from "node:assert/strict";

import { checkSlots, fitText, slotRect, wrap } from "./render.js";

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
