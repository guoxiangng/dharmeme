import { FONT_FAMILY, renderMeme } from "./render.js";

const $ = (id) => document.getElementById(id);
const canvas = $("meme");
const select = $("template");
const slotsBox = $("slots");
const debugBox = $("debug");

// Where template images are served from. Relative = next to this page; to move them to a
// CDN, set an absolute URL here (the host must send CORS headers, or PNG export is blocked).
const IMAGE_BASE = "images/";

let templates = [];
let current = null; // {template, image}
const imageCache = new Map();

debugBox.checked = new URLSearchParams(location.search).has("debug");

function loadImage(template) {
  if (!imageCache.has(template.id)) {
    imageCache.set(
      template.id,
      new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null); // not fetched yet: draw a placeholder
        img.crossOrigin = "anonymous";
        img.src = `${IMAGE_BASE}${template.image}`;
      }),
    );
  }
  return imageCache.get(template.id);
}

function slotValues() {
  const values = {};
  for (const ta of slotsBox.querySelectorAll("textarea")) values[ta.name] = ta.value;
  return values;
}

function draw() {
  if (!current) return;
  renderMeme(canvas, current.template, slotValues(), current.image, { debug: debugBox.checked });
  $("status").textContent = current.image
    ? ""
    : "Template image not downloaded yet; showing a placeholder.";
}

function buildSlotInputs(template) {
  slotsBox.replaceChildren();
  for (const slot of template.slots) {
    const label = document.createElement("label");
    label.htmlFor = `slot-${slot.name}`;
    label.textContent = slot.name.replaceAll("_", " ");
    const ta = document.createElement("textarea");
    ta.id = `slot-${slot.name}`;
    ta.name = slot.name;
    ta.rows = 2;
    ta.value = slot.name.replaceAll("_", " ");
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

async function selectTemplate(id) {
  const template = templates.find((t) => t.id === id);
  buildSlotInputs(template);
  $("format").textContent = template.format;
  current = { template, image: await loadImage(template) };
  draw();
}

$("download").addEventListener("click", () => {
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `dharmeme-${current.template.id}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, "image/png");
});

debugBox.addEventListener("change", draw);
select.addEventListener("change", () => selectTemplate(select.value));

async function main() {
  await document.fonts.load(`40px ${FONT_FAMILY}`);
  templates = await (await fetch("catalog.json")).json();
  for (const t of templates) select.add(new Option(t.name, t.id));
  await selectTemplate(templates[0].id);
}

main().catch((err) => {
  $("status").textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
