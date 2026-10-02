# dharmeme — spec (v1)

The contracts every part builds against. Change this file first, then the code.

## 1. Features

| Feature | Input | Output | LLM at request time |
|---|---|---|---|
| **Random** | none | an approved meme from the bank, rendered | No |
| **Theme** | one of the listed Buddhist themes | a fresh meme whose template and text the LLM chose for the theme | Yes, one call |

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

## 4. Meme pool — DynamoDB, seeded from `seed/memes.jsonl`

The live pool is in the DynamoDB table (items with `pk = "meme"`); that is the source of
truth. `seed/memes.jsonl` is loaded into the table once, when it is empty, and is not the
live list: once the generator and the bot change the pool, the file is not updated.

```json
{"id": "drake-0007", "template_id": "drake",
 "slots": {"rejected": "Reaching nirvana", "preferred": "Reaching inbox zero"},
 "status": "approved", "created": "2026-10-01"}
```

- `status`: `pending`, `approved`, `rejected`.
- `GET /memes` returns the `approved` entries. The page fetches them once on load and
  picks at random in the browser, so Random makes no LLM call. If the API is down the
  page uses `memes.json`, the approved seed entries published with the site.
- The site build fails if a seed entry's slots don't match its template or a text is empty
  or over `max_chars`.
- `review.html` renders the seed for local review (`build_site.py --review`); it is never
  deployed.
- **Daily generator** (`generator.py`, an EventBridge schedule on the same Lambda): two LLM
  calls a day whatever the traffic. The first writes one meme for each of the N templates
  with the fewest memes, shown what the pool already has; the second, a separate reviewer,
  passes or fails each against the tone rules. Only valid, non-duplicate, passed memes are
  added. An unreadable review adds nothing.
- Generated memes are always added as `pending` and are not served. Nothing generated is
  published without the owner: with `OwnerChatId` set, the bot sends each pending meme to
  that one chat with **Approve** and **Reject** buttons, and a press counts only when it
  comes from that chat. The `send_pending` admin invoke re-sends whatever is still pending.

## 4a. Feedback — thumbs up, thumbs down, Report

Under every pool meme, on the page and in the bot (topic memes are not in the pool and
have no buttons). `POST /vote {"id", "vote": "up"|"down"|"report"}`; no LLM call.

- **One thumb and one report per voter per meme** (voter = IP on the web, user id in
  Telegram), remembered for 90 days, plus a daily allowance of 300 votes per voter.
- **Votes never change how often a meme is shown.** Random deals the whole pool once per
  pass (`web/deck.js`), so every meme gets the same exposure. Votes only nudge the order
  within a pass: by up-rate, not by count, and only once a meme has 10 votes. 500 thumbs up
  earn no more than 10 at the same rate, so nothing snowballs while the pool is young. The
  bot's `/random` is a weighted pick with the same bounded weights (0.5 to 1.5).
- **Nothing is hidden automatically.** The first report of a meme, or a meme reaching 20
  votes with an up-rate under 30%, is sent once to the owner's chat with Keep and Remove
  buttons. Until the owner decides, it stays in the pool.

## 5. Theme feature — `POST /meme` → `write_meme(topic) -> {template_id, slots}`

**The public picks a theme; it never types a topic.** `themes/en.yaml` lists the themes
(`id`, button `label`, and a `brief` for the model), spanning the shared early teachings
and Mahayana, Chan and Pure Land practice. The request names a theme id, and the model is
given that theme's label and brief, so nothing a visitor types reaches the model. Free
text as a topic is accepted only from the owner's own Telegram chat.

One LLM call in the Lambda. The system prompt contains the tone rules (§1) and a random
six of the catalog's templates (`id`, `format`, `slots` with `max_chars`), so the model
doesn't use one favourite template every time. The user message is `Topic: <label>.
<brief>`.

Required LLM output (JSON only):

```json
{"template_id": "drake", "slots": {"rejected": "...", "preferred": "..."}}
```

or, for a topic that would break the tone rules:

```json
{"declined": true}
```

API: request `{"theme": "<id>"}` (an unlisted theme is a 400); response `{"template_id": ..., "slots": {...}}` on success,
or `{"fallback": "<reason>", "message": "..."}` where `reason` is `declined`, `limit` or
`error` — the page then shows the message and a random meme.

Validation: `template_id` exists, slot names exactly match, each text is non-empty and within
`max_chars`.

| Outcome | Behaviour |
|---|---|
| Valid | return it; the page renders it |
| Invalid JSON or failed validation | retry once, telling the model what was wrong; then `fallback: error` |
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

## 7. Limits — counters in the same table (`pk = "usage"`)

Applies to the prompt feature only; Random makes no LLM call. A request counts against
the limits even if the LLM call then fails.

| Counter | Sort key | Default limit |
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

- **Random** button: picks from the pool fetched from `GET /memes` on load (§4), renders.
  Works with the backend down, from the bundled `memes.json`.
- The API's address is `API_BASE` in `web/config.js`.
- **Theme** buttons (from `themes.json`): `POST` to the Function URL, renders the result or shows the
  fallback message with a random meme.
- **Download** button for the PNG.

**Telegram** is a second front end on the same Lambda (`POST /telegram`, the bot's webhook):
`/random`, `/meme <topic>`, or a plain message as the topic. Telegram needs a real image, so
`render.py` draws the meme with Pillow, by the same rules as `web/render.js`. Topic memes
count against the §7 limits per chat. Updates are accepted only with the secret Telegram
sends back (derived from the bot token). The token lives in SSM Parameter Store
(`/dharmeme/telegram-token`); the bot is off until it exists.

## 9. Deploy

- **Site:** a GitHub Actions workflow builds `_site/` from `web/`, the template images, the
  catalog (YAML → `catalog.json`) and the approved seed (→ `memes.json`), and deploys to Pages.
- **API:** SAM in `deploy/sam/template.yaml`, stack `dharmeme`, region ap-southeast-1.
  `scripts/build_lambda.py` builds `deploy/build/dharmeme.zip` (the package, the Anthropic
  SDK as Linux wheels, `catalog.json`, the seed), then `sam deploy` from `deploy/sam/`. One
  zip Lambda (Python 3.13; no Pillow, no container), Function URL with `AuthType: NONE` and
  CORS allowing only `https://guoxiangng.github.io`, `GET` and `POST`. Resources: the
  function and one on-demand DynamoDB table (TTL on the counters, point-in-time recovery).
  No secrets needed for v1.

## 10. Repo layout

```
src/dharmeme/   catalog.py prompt.py pool.py limits.py store.py api.py
                llm/{base,factory,bedrock}.py
templates/      catalog.yaml  images/
seed/           memes.jsonl
web/            index.html app.js config.js review.html review.js images.js render.js
                style.css fonts/
scripts/        fetch_templates.py build_site.py build_lambda.py smoke_llm.py
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
9. An unlisted theme, typed text, or a non-POST request → HTTP 400 / 405, no LLM call.

## 12. Build order

1. Catalog (about 10 templates) + browser renderer + a local preview page.
2. Bank generator + review page; first approved batch.
3. Prompt Lambda (stubbed-LLM tests, then a live smoke test) + limits + SAM deploy.
4. Pages workflow, public site, portfolio link.
5. Later: Telegram front end.

## Open questions

- Which ~10 templates to start with.
- Limit numbers (5 per IP, 200 global) — placeholders.
