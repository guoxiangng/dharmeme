import { API_BASE } from "./config.js";
import { deck } from "./deck.js";
import { loadImage } from "./images.js";
import { FONT_FAMILY, renderMeme } from "./render.js";

const $ = (id) => document.getElementById(id);
const canvas = $("meme");
const select = $("template");
const slotsBox = $("slots");
const debugBox = $("debug");

let templates = [];
let memes = []; // the approved pool, each with its up/down counts
let queue = []; // this pass of the pool: every meme once before any repeats (deck.js)
let current = null; // {template, image, name, memeId} — name is used for the download file

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
      // Edited text is no longer the pool's meme, so it can't be rated.
      current.memeId = null;
      showVoteButtons();
    });
    update();
    slotsBox.append(label, ta, counter);
  }
}

// `memeId` is set only for a meme from the pool; those are the ones visitors can rate.
async function show(template, values, name, memeId = null) {
  select.value = template.id;
  buildSlotInputs(template, values);
  $("format").textContent = template.format;
  current = { template, image: await loadImage(template), name, memeId };
  draw();
  showVoteButtons();
}

function showRandom() {
  if (!queue.length) queue = deck(memes);
  const meme = queue.pop();
  return show(templates.find((t) => t.id === meme.template_id), meme.slots, meme.id, meme.id);
}

// What this browser has already voted on: {memeId: "up" | "down", "memeId:report": true}.
function myVotes() {
  try {
    return JSON.parse(localStorage.getItem("dharmeme-votes")) || {};
  } catch {
    return {};
  }
}

function showVoteButtons() {
  const id = current && current.memeId;
  $("votes").hidden = !id;
  if (!id) return;
  const votes = myVotes();
  $("vote-up").disabled = $("vote-down").disabled = Boolean(votes[id]);
  $("vote-up").classList.toggle("chosen", votes[id] === "up");
  $("vote-down").classList.toggle("chosen", votes[id] === "down");
  $("vote-report").disabled = Boolean(votes[`${id}:report`]);
  $("vote-report").textContent = votes[`${id}:report`] ? "Reported" : "Report";
}

async function vote(kind) {
  const id = current.memeId;
  const votes = myVotes();
  votes[kind === "report" ? `${id}:report` : id] = kind === "report" ? true : kind;
  try {
    localStorage.setItem("dharmeme-votes", JSON.stringify(votes));
  } catch {
    // private browsing: the vote still counts, the button just isn't remembered
  }
  showVoteButtons();
  if (kind === "report") $("status").textContent = "Reported. Thank you.";
  try {
    await fetch(`${API_BASE}vote`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id, vote: kind }),
    });
  } catch (err) {
    console.error("vote not recorded", err);
  }
}

for (const kind of ["up", "down", "report"]) {
  $(`vote-${kind}`).addEventListener("click", () => vote(kind));
}

$("random").addEventListener("click", () => {
  $("status").textContent = "";
  showRandom();
});

// Ask the API for a fresh meme on one of the listed themes. Whatever goes wrong (limit
// reached, API down), the visitor gets a short message and a random meme.
async function makeForTheme(theme) {
  const buttons = $("themes").querySelectorAll("button");
  for (const b of buttons) b.disabled = true;
  $("status").textContent = `${theme.label}: contemplating…`;
  let reply;
  try {
    const response = await fetch(`${API_BASE}meme`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ theme: theme.id }),
    });
    reply = await response.json();
    if (!response.ok) throw new Error(reply.error || response.status);
  } catch (err) {
    console.error(err);
    reply = { fallback: "error", message: "The mind wandered. Here is another one instead." };
  }
  for (const b of buttons) b.disabled = false;
  canvas.scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (reply.fallback) {
    $("status").textContent = reply.message;
    if (memes.length) await showRandom();
    return;
  }
  $("status").textContent = "";
  await show(templates.find((t) => t.id === reply.template_id), reply.slots, theme.id);
}

function buildThemeButtons(themes) {
  for (const theme of themes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = theme.label;
    button.addEventListener("click", () => makeForTheme(theme));
    $("themes").append(button);
  }
}

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
  let themes;
  [templates, themes, memes] = await Promise.all([
    fetch("catalog.json").then((response) => response.json()),
    fetch("themes.json").then((response) => response.json()),
    loadMemes(),
  ]);
  for (const t of templates) select.add(new Option(t.name, t.id));
  buildThemeButtons(themes);
  if (memes.length) {
    await showRandom();
  } else {
    $("random").hidden = true;
    $("editor").open = true;
    $("status").textContent = "The meme pool is empty. Pick a theme, or write your own.";
    await show(templates[0], null, templates[0].id);
  }
}

main().catch((err) => {
  $("status").textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
