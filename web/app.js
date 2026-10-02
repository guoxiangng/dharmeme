import { API_BASE } from "./config.js";
import { deck } from "./deck.js";
import { loadImage } from "./images.js";
import { FONT_FAMILY, renderMeme } from "./render.js";

const $ = (id) => document.getElementById(id);
const canvas = $("meme");
const select = $("template");
const slotsBox = $("slots");
const debugBox = $("debug");

// The Chinese section in its two scripts: same themes, same pool, same context.
const CHINESE = {
  "zh-hans": { script: "sc", random: "随机一张", working: "参究中…", empty: "梗图库还是空的，选个主题现写一张吧。" },
  zh: { script: "tc", random: "隨機一張", working: "參究中…", empty: "梗圖庫還是空的，選個主題現寫一張吧。" },
};

let templates = [];
let themes = {}; // by language: [{id, label}]
const pools = {}; // by language: {memes, queue}; a queue is one pass of the pool (deck.js)
let zhLang = "zh-hans"; // which script the Chinese section is in
// {template, image, name, memeId, fresh, lang}: `name` is for the download file; `memeId`
// is set for a pool meme and for a fresh themed one, which are the ones a visitor can rate.
let current = null;

debugBox.checked = new URLSearchParams(location.search).has("debug");

function slotValues() {
  const values = {};
  for (const ta of slotsBox.querySelectorAll("textarea")) values[ta.name] = ta.value;
  return values;
}

function draw() {
  if (!current) return;
  // Chinese typed into the editor is drawn in the script the Chinese section is set to.
  const script = (CHINESE[current.lang] || CHINESE[zhLang]).script;
  renderMeme(canvas, current.template, slotValues(), current.image,
    { debug: debugBox.checked, script });
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
      // Edited text is no longer the meme that was served, so it can't be rated.
      current.memeId = null;
      showVoteButtons();
    });
    update();
    slotsBox.append(label, ta, counter);
  }
}

async function show(template, values, name, { memeId = null, fresh = false, lang = null } = {}) {
  select.value = template.id;
  buildSlotInputs(template, values);
  $("format").textContent = template.format;
  current = { template, image: await loadImage(template), name, memeId, fresh, lang };
  draw();
  showVoteButtons();
}

// The live pool comes from the API. For English, the copy published with the site is
// the fallback, so Random works with the backend down.
async function loadPool(lang) {
  try {
    const response = await fetch(`${API_BASE}memes${lang === "en" ? "" : `?lang=${lang}`}`);
    if (!response.ok) throw new Error(response.status);
    return await response.json();
  } catch (err) {
    console.error(`pool (${lang}) unavailable`, err);
    return lang === "en" ? (await fetch("memes.json")).json() : [];
  }
}

async function pool(lang) {
  if (!pools[lang]) pools[lang] = { memes: await loadPool(lang), queue: [] };
  return pools[lang];
}

// The next meme of this language's pool; false if that pool is empty.
async function showRandom(lang = "en") {
  const p = await pool(lang);
  if (!p.memes.length) return false;
  if (!p.queue.length) p.queue = deck(p.memes);
  const meme = p.queue.pop();
  await show(templates.find((t) => t.id === meme.template_id), meme.slots, meme.id,
    { memeId: meme.id, lang });
  return true;
}

// What this browser has already voted on: {memeId: "up" | "down", "memeId:report": true}.
function myVotes() {
  try {
    return JSON.parse(localStorage.getItem("dharmeme-votes")) || {};
  } catch {
    return {};
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private browsing: it still works, it just isn't remembered
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
  // A fresh themed meme isn't in the pool, so there is nothing to report yet.
  $("vote-report").hidden = current.fresh;
  $("vote-report").disabled = Boolean(votes[`${id}:report`]);
  $("vote-report").textContent = votes[`${id}:report`] ? "Reported" : "Report";
}

async function vote(kind) {
  const { memeId: id, fresh } = current;
  const votes = myVotes();
  votes[kind === "report" ? `${id}:report` : id] = kind === "report" ? true : kind;
  remember("dharmeme-votes", JSON.stringify(votes));
  showVoteButtons();
  if (kind === "report") $("status").textContent = "Reported. Thank you.";
  if (fresh && kind === "up") {
    // A thumbs up on a meme written for you nominates it; the owner decides.
    $("status").textContent = "Thanks! If the owner approves it, it joins the pool.";
  }
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
// reached, API down), the visitor gets a short message and a meme from the pool.
async function makeForTheme(theme, lang = "en") {
  const buttons = document.querySelectorAll(".chip");
  for (const b of buttons) b.disabled = true;
  $("status").textContent = lang === "en"
    ? `${theme.label}: contemplating…`
    : `${theme.label}：${CHINESE[lang].working}`;
  let reply;
  try {
    const response = await fetch(`${API_BASE}meme`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ theme: theme.id, lang }),
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
    if (!(await showRandom(lang)) && lang !== "en") await showRandom();
    return;
  }
  $("status").textContent = "";
  await show(templates.find((t) => t.id === reply.template_id), reply.slots, theme.id,
    { memeId: reply.id || null, fresh: true, lang });
}

function buildThemeButtons(container, list, lang) {
  container.replaceChildren();
  for (const theme of list) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = theme.label;
    button.addEventListener("click", () => makeForTheme(theme, lang));
    container.append(button);
  }
}

// Draw the Chinese section in the chosen script.
function showChinese(lang) {
  zhLang = lang;
  remember("dharmeme-zh", lang);
  for (const key of Object.keys(CHINESE)) $(`script-${key}`).classList.toggle("chosen", key === lang);
  $("zh-random").textContent = CHINESE[lang].random;
  buildThemeButtons($("themes-zh"), themes[lang], lang);
}

for (const lang of Object.keys(CHINESE)) {
  $(`script-${lang}`).addEventListener("click", () => showChinese(lang));
}

$("zh-random").addEventListener("click", async () => {
  $("status").textContent = "";
  canvas.scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (!(await showRandom(zhLang))) $("status").textContent = CHINESE[zhLang].empty;
});

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
  const json = (url) => fetch(url).then((response) => response.json());
  let english;
  [templates, themes.en, themes.zh, themes["zh-hans"], english] = await Promise.all([
    json("catalog.json"), json("themes.json"), json("themes_zh.json"),
    json("themes_zh_hans.json"), loadPool("en"),
  ]);
  pools.en = { memes: english, queue: [] };
  for (const t of templates) select.add(new Option(t.name, t.id));
  buildThemeButtons($("themes"), themes.en, "en");
  let saved = null;
  try {
    saved = localStorage.getItem("dharmeme-zh");
  } catch {
    // no storage: start in Simplified
  }
  showChinese(saved in CHINESE ? saved : "zh-hans");
  if (!(await showRandom())) {
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
