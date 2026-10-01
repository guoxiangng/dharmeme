// Review page for the meme bank (SPEC.md §4). A static page can't write the bank file, so
// it collects the ids you reject into a list to copy; the statuses are then updated in
// seed/memes.jsonl.
import { loadImage } from "./images.js";
import { FONT_FAMILY, renderMeme } from "./render.js";

const $ = (id) => document.getElementById(id);
const grid = $("grid");
const rejected = new Set();

let templates = [];
let bank = [];

function updateList() {
  $("rejected").value = [...rejected].sort().join(", ");
}

async function card(entry) {
  const template = templates.find((t) => t.id === entry.template_id);
  const figure = document.createElement("figure");
  figure.className = "card";
  figure.classList.toggle("rejected", rejected.has(entry.id));
  const canvas = document.createElement("canvas");
  renderMeme(canvas, template, entry.slots, await loadImage(template));
  const caption = document.createElement("figcaption");
  caption.textContent = `${entry.id} · ${entry.status}`;
  figure.append(canvas, caption);
  figure.addEventListener("click", () => {
    if (!rejected.delete(entry.id)) rejected.add(entry.id);
    figure.classList.toggle("rejected", rejected.has(entry.id));
    updateList();
  });
  return figure;
}

async function render() {
  const filter = $("filter").value;
  const shown = bank.filter((e) => filter === "all" || e.status === filter);
  $("count").textContent = `${shown.length} of ${bank.length}`;
  grid.replaceChildren(...(await Promise.all(shown.map(card))));
}

// review.html?show=approved opens on that filter.
$("filter").value = new URLSearchParams(location.search).get("show") || "pending";
$("filter").addEventListener("change", render);
$("copy").addEventListener("click", () => navigator.clipboard.writeText($("rejected").value));

async function main() {
  await document.fonts.load(`40px ${FONT_FAMILY}`);
  [templates, bank] = await Promise.all(
    ["catalog.json", "bank.json"].map(async (url) => (await fetch(url)).json()),
  );
  await render();
}

main().catch((err) => {
  $("count").textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
