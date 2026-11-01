import assert from "node:assert/strict";
import test from "node:test";
import { offered, todaySgt } from "./season.js";

const themes = [
  { id: "karma", label: "Karma" },
  { id: "vesak", label: "Vesak", dates: ["2026-05-31", "2027-05-20"] },
];

test("a festival theme shows from two weeks before to three days after, first", () => {
  assert.deepEqual(offered(themes, "2026-05-17").map((t) => t.id), ["vesak", "karma"]);
  assert.deepEqual(offered(themes, "2026-06-03").map((t) => t.id), ["vesak", "karma"]);
  assert.deepEqual(offered(themes, "2026-05-16").map((t) => t.id), ["karma"]);
  assert.deepEqual(offered(themes, "2026-06-04").map((t) => t.id), ["karma"]);
});

test("today is the Singapore date", () => {
  // 20:00 UTC on 31 October is already 1 November in Singapore.
  assert.equal(todaySgt(Date.parse("2026-10-31T20:00:00Z")), "2026-11-01");
});
