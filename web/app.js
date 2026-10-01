import { API_BASE } from "./config.js";
import { loadImage } from "./images.js";
import { FONT_FAMILY, renderMeme } from "./render.js";

const $ = (id) => document.getElementById(id);
const canvas = $("meme");
const select = $("template");
const slotsBox = $("slots");
const debugBox = $("debug");

let templates = [];
let memes = []; // approved bank entries
let queue = []; // shuffled memes still to show, so Random doesn't repeat until all are seen
let current = null; // {template, image, name} — name is used for the download file

debugBox.checked = new URLSearchParams(location.search).has("debug");

function slotValues() {
  const values = {};
  for (const ta of slotsBox.querySelectorAll("textarea")) values[ta.name] = ta.value;
  return values;
}

function draw() {
  if (!current) return;
  renderMeme(canvas, current.template, slotValues(), current.image, { debug: debugBox.checked });
}

// `values` fills the slot inputs; without it each slot shows its own name as a placeholder.
function buildSlotInputs(template, values) {
  slotsBox.replaceChildren();
  for (const slot of template.slots) {
    const label = document.createElement("label");
    label.htmlFor = `slot-${slot.name}`;
    label.textContent = slot.name.replaceAll("_", " ");
    const ta = document.createElement("textarea");
    ta.id = `slot-${slot.name}`;
    ta.name = slot.name;
    ta.rows = 2;
    ta.value = values ? values[slot.name] : slot.name.replaceAll("_", " ");
    const counter = document.createElement("div");
    counter.className = "counter";
    const update = () => {
      counter.textContent = `${ta.value.length} / ${slot.max_chars}`;
      counter.classList.toggle("over", ta.value.length > slot.max_chars);
    };
    ta.addEventListener("input", () => {
      update();
      draw();
    });
    update();
    slotsBox.append(label, ta, counter);
  }
}

async function show(template, values, name) {
  select.value = template.id;
  buildSlotInputs(template, values);
  $("format").textContent = template.format;
  current = { template, image: await loadImage(template), name };
  draw();
}

function shuffled(list) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function showRandom() {
  if (!queue.length) queue = shuffled(memes);
  const meme = queue.pop();
  return show(templates.find((t) => t.id === meme.template_id), meme.slots, meme.id);
}

$("random").addEventListener("click", () => {
  $("status").textContent = "";
  showRandom();
});

// Ask the API for a meme on the visitor's topic. Whatever goes wrong (limit reached,
// topic declined, API down), the visitor gets a short message and a random meme.
$("prompt").addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = $("topic").value.trim();
  if (!topic) return;
  const button = $("make");
  button.disabled = true;
  $("status").textContent = "Contemplating…";
  let reply;
  try {
    const response = await fetch(`${API_BASE}meme`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ topic }),
    });
    reply = await response.json();
    if (!response.ok) throw new Error(reply.error || response.status);
  } catch (err) {
    console.error(err);
    reply = { fallback: "error", message: "The mind wandered. Here is another one instead." };
  }
  button.disabled = false;
  if (reply.fallback) {
    $("status").textContent = reply.message;
    if (memes.length) await showRandom();
    return;
  }
  $("status").textContent = "";
  await show(templates.find((t) => t.id === reply.template_id), reply.slots, "custom");
});

// The live pool comes from the API; the copy published with the site is the fallback.
async function loadMemes() {
  try {
    const response = await fetch(`${API_BASE}memes`);
    if (!response.ok) throw new Error(response.status);
    return await response.json();
  } catch (err) {
    console.error("pool unavailable, using the bundled memes", err);
    return (await fetch("memes.json")).json();
  }
}

$("download").addEventListener("click", () => {
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `dharmeme-${current.name}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, "image/png");
});

debugBox.addEventListener("change", draw);
select.addEventListener("change", () => {
  const template = templates.find((t) => t.id === select.value);
  show(template, null, template.id);
});

async function main() {
  await document.fonts.load(`40px ${FONT_FAMILY}`);
  [templates, memes] = await Promise.all([
    fetch("catalog.json").then((response) => response.json()),
    loadMemes(),
  ]);
  for (const t of templates) select.add(new Option(t.name, t.id));
  if (memes.length) {
    await showRandom();
  } else {
    $("random").hidden = true;
    $("editor").open = true;
    $("status").textContent = "The meme pool is empty. Give it a topic, or write your own.";
    await show(templates[0], null, templates[0].id);
  }
}

main().catch((err) => {
  $("status").textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
