// Run with: node --test web/
import { test } from "node:test";
import assert from "node:assert/strict";

import { deck, upRate } from "./deck.js";

const pool = [
  { id: "new", up: 0, down: 0 },
  { id: "few", up: 5, down: 0 }, // under 10 votes: still unrated
  { id: "loved", up: 500, down: 0 },
  { id: "liked", up: 10, down: 0 }, // same rate as "loved", far fewer votes
  { id: "disliked", up: 1, down: 19 },
];

test("a meme is unrated until it has ten votes", () => {
  assert.equal(upRate(pool[0]), null);
  assert.equal(upRate(pool[1]), null);
  assert.equal(upRate(pool[2]), 1);
  assert.equal(upRate(pool[4]), 0.05);
});

test("every meme appears exactly once per pass, whatever its votes", () => {
  for (let i = 0; i < 200; i++) {
    const ids = deck(pool).map((m) => m.id).sort();
    assert.deepEqual(ids, ["disliked", "few", "liked", "loved", "new"]);
  }
});

test("a rating only nudges the order, and by rate rather than by count", () => {
  const firstShown = { new: 0, few: 0, loved: 0, liked: 0, disliked: 0 };
  const runs = 20000;
  for (let i = 0; i < runs; i++) firstShown[deck(pool).pop().id]++;
  // 500 thumbs up earns no more than 10 thumbs up at the same rate.
  assert.ok(Math.abs(firstShown.loved - firstShown.liked) < runs * 0.03);
  // Unrated memes are treated alike.
  assert.ok(Math.abs(firstShown.new - firstShown.few) < runs * 0.03);
  // Liked ones tend to come earlier than disliked ones, but nothing is shut out.
  assert.ok(firstShown.loved > firstShown.new && firstShown.new > firstShown.disliked);
  assert.ok(firstShown.disliked > runs * 0.01);
});

test("with no votes at all the deck is a plain shuffle", () => {
  const fresh = [1, 2, 3, 4].map((id) => ({ id }));
  const first = {};
  for (let i = 0; i < 8000; i++) {
    const id = deck(fresh).pop().id;
    first[id] = (first[id] || 0) + 1;
  }
  for (const count of Object.values(first)) assert.ok(Math.abs(count - 2000) < 250);
});
