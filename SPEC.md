# dharmeme — spec (v1)

The contracts every part builds against. Change this file first, then the code.

## 1. Features

| Feature | Input | Output | LLM at request time |
|---|---|---|---|
| **Random** | none | an approved meme from the bank, rendered | No |
| **Prompt** | a topic, 1–200 chars | a meme whose template and text the LLM chose for the topic | Yes, one call |

Tone: affectionate humour about the practitioner's struggle (attachment, impermanence, the
middle way, monkey mind, karma, suffering, letting go). Never ridicule the Buddha, the Sangha,
sacred objects, or other religions; never target a group of people.

## 2. Template catalog — `templates/catalog.yaml`

Popular meme templates (imgflip and similar), stored in `templates/images/`. No AI-generated
images.

```yaml
defaults:
  style: {color: white, stroke: black, align: center, uppercase: true}

templates:
  - id: drake                      # unique, kebab-case
    name: Drake Hotline Bling
    image: drake.jpg               # file in templates/images/
    url: https://i.imgflip.com/30b1gx.jpg   # where fetch_templates.py downloads it from
    size: [1200, 1200]             # expected pixel size (fetch warns on mismatch)
    verified: false                # true once the boxes were checked on the real image
    format: >-                     # the joke format, written for the LLM
      Two panels. Top: something rejected with disgust. Bottom: the thing preferred instead.
    tags: [preference, choice]
    style: {color: black, stroke: none, uppercase: false}   # overrides defaults
    slots:
      - name: rejected             # snake_case
        box: [0.52, 0.02, 0.46, 0.46]   # x, y, width, height as FRACTIONS of the image
        max_chars: 70
        # style: {...}             # optional per-slot override
      - name: preferred
        box: [0.52, 0.52, 0.46, 0.46]
        max_chars: 70
```

Styles cascade defaults → template → slot; `src/dharmeme/catalog.py` validates the file and
resolves every slot to a complete style. Boxes are fractions so they survive image resizing.
The preview page (`?debug`) outlines each box for tuning.

## 3. Renderer — browser canvas, `web/render.js`

`renderMeme(canvas, template, slots, image)` draws the template image, then each slot's text.

- Font: Anton (SIL OFL, bundled in `web/fonts/`; Impact is not free to redistribute).
- Fitting is a pure function, `fitText(measure, text, box, style) -> {fontSize, lines}`, so it
  can be tested without a browser: wrap to the box width; if it still overflows, shrink the
  font down to a minimum size; at the minimum, truncate with "…". Text never leaves its box.
  A word is kept whole (the font shrinks instead) and only split at the minimum size.
- Throws for an unknown template or slot names that don't match the template.
- The page offers the result as a PNG download (`canvas.toBlob`).

The backend never renders. A Python renderer is only needed later, for Telegram.

## 4. Meme bank — `bank/memes.jsonl`

One JSON object per line, generated offline per template and hand-reviewed.

```json
{"id": "drake-0007", "template_id": "drake",
 "slots": {"rejected": "Reaching nirvana", "preferred": "Reaching inbox zero"},
 "status": "approved", "created": "2026-10-01"}
```

- `status`: `pending` (fresh from the generator), `approved`, `rejected`.
- Random serves only `approved` entries, uniformly at random, entirely in the browser.
- `scripts/generate_bank.py --template drake --count 20` appends `pending` entries
  (offline, LLM via §6).
- `review.html` on the site renders the bank with the same renderer. Tap a meme to reject
  it; the page lists the rejected ids to copy, and the statuses are then updated in
  `bank/memes.jsonl` (a static page can't write the file itself).
- The site build fails if an entry's slots don't match its template or a text is empty or
  over `max_chars`. It publishes `approved` entries as `memes.json`, and the whole bank
  with statuses as `bank.json` for the review page.

## 5. Prompt feature — `POST /meme` → `write_meme(topic) -> {template_id, slots}`

One LLM call in the Lambda. The system prompt contains the tone rules (§1) and the catalog:
each template's `id`, `format`, and `slots` with `max_chars`. The user message is the topic.

Required LLM output (JSON only):

```json
{"template_id": "drake", "slots": {"rejected": "...", "preferred": "..."}}
```

or, for a topic that would break the tone rules:

```json
{"declined": true}
```

API: request `{"topic": "..."}`; response `{"template_id": ..., "slots": {...}}` on success,
or `{"fallback": "<reason>", "message": "..."}` where `reason` is `declined`, `limit` or
`error` — the page then shows the message and a random meme.

Validation: `template_id` exists, slot names exactly match, each text is non-empty and within
`max_chars`.

| Outcome | Behaviour |
|---|---|
| Valid | return it; the page renders it |
| Invalid JSON or failed validation | retry once; then `fallback: error` |
| `declined`, or the model refuses | `fallback: declined` (no fallback model — unlike hakigains, a refusal is not retried on a pricier model) |
| Bedrock error / timeout | `fallback: error` |

The user never sees an error; the worst case is a random meme.

## 6. LLM — same pattern as hakigains

- `src/dharmeme/llm/` with `base.py` (`LLMProvider`, `LLMResponse`), `factory.py`
  (`LLM_PROVIDER` env var, default `bedrock`) and `bedrock.py` (Anthropic SDK
  `AnthropicBedrock` client, global inference profile).
- Model: Claude Haiku 4.5 via its global inference profile, set by `BEDROCK_MODEL_ID`
  (exact ID confirmed at build). `BEDROCK_EFFORT=""` (Haiku rejects the effort parameter).
- `max_tokens` small (~400): the output is a few short strings.

## 7. Limits — DynamoDB table `usage`

Applies to the prompt feature only; random never touches the backend.

| Counter | Key | Default limit |
|---|---|---|
| Per IP per day | `ip#<source_ip>#<YYYY-MM-DD>` | 5 |
| Global per day | `global#<YYYY-MM-DD>` | 200 |

- Source IP from the Function URL request context. Weak (IPs change), so the global cap is
  the real ceiling on cost.
- Dates in SGT. Increment is an atomic `ADD` with a condition `count < limit`, checked before
  the Bedrock call; items carry a TTL of 2 days.
- Over either limit: `fallback: limit` with an on-theme message ("The meme well is empty. All
  things are impermanent — try tomorrow.").
- Lambda reserved concurrency: 5. AWS Budgets alert as the backstop (alerts only; the caps above
  are the real stop). Cloudflare Turnstile if abuse appears.

## 8. Front end — static web page (v1)

Served by GitHub Pages from this (public) repo at `https://guoxiangng.github.io/dharmeme/`,
linked from the portfolio (`guoxiangng.github.io`, plus a `projects/dharmeme.html` write-up).

- **Random** button: picks from `memes.json`, renders. Works with the backend down.
- **Prompt** box (max 200 chars): `POST` to the Function URL, renders the result or shows the
  fallback message with a random meme.
- **Download** button for the PNG.

Telegram is a later second front end over the same Lambda core (needs a Python renderer).

## 9. Deploy

- **Site:** a GitHub Actions workflow builds `_site/` from `web/`, the template images, the
  catalog (YAML → `catalog.json`) and the approved bank (→ `memes.json`), and deploys to Pages.
- **API:** SAM in `deploy/sam/template.yaml`, region ap-southeast-1. One zip Lambda (Python
  3.12, `anthropic[bedrock]` + `PyYAML`; no Pillow, no container), Function URL with
  `AuthType: NONE` and CORS allowing only `https://guoxiangng.github.io`, `POST` only.
  Resources: the function and the `usage` table. No secrets needed for v1.

## 10. Repo layout

```
src/dharmeme/   config.py catalog.py prompt.py limits.py api.py
                llm/{base,factory,bedrock}.py
templates/      catalog.yaml  images/
bank/           memes.jsonl
web/            index.html app.js review.html review.js images.js render.js style.css fonts/
scripts/        fetch_templates.py generate_bank.py build_site.py smoke_llm.py
deploy/         sam/template.yaml  lambda/handler.py
.github/        workflows/pages.yml
tests/          (pytest) + web/render.test.js (node --test)
```

## 11. Acceptance examples (become tests)

1. `fitText` with a 60-char text fits the box; with a 500-char text it returns the minimum
   font size and a truncated last line ending "…"; no line is wider than the box.
2. `renderMeme` with slot names that don't match the template throws.
3. `memes.json` from the site build contains only `approved` entries.
4. Prompt with a stubbed LLM returning valid JSON → that `{template_id, slots}` is returned.
5. Stubbed LLM returning an unknown `template_id` twice → `fallback: error`, exactly 2 LLM calls.
6. Stubbed LLM returning `{"declined": true}` → `fallback: declined`.
7. An IP's 6th prompt of the day → `fallback: limit`, no LLM call.
8. Global counter at 200 → `fallback: limit`, no LLM call.
9. A topic over 200 chars, or a non-POST request → HTTP 400 / 405, no LLM call.

## 12. Build order

1. Catalog (about 10 templates) + browser renderer + a local preview page.
2. Bank generator + review page; first approved batch.
3. Prompt Lambda (stubbed-LLM tests, then a live smoke test) + limits + SAM deploy.
4. Pages workflow, public site, portfolio link.
5. Later: Telegram front end.

## Open questions

- Which ~10 templates to start with.
- Limit numbers (5 per IP, 200 global) — placeholders.
