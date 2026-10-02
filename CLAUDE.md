# Working on dharmeme

A Buddhist meme generator: a static web page, a Telegram bot, one Lambda, one DynamoDB
table, Claude Haiku on Bedrock. Read `README.md` for what it is and `SPEC.md` for how the
parts fit; SPEC.md is the source of truth for behaviour, so change it with the code.

## Rules the owner has set

These came out of specific decisions. Don't relitigate them; ask before going against one.

- **Nothing reaches the pool unread by the owner.** Generated memes are always `pending`
  and are approved one by one in the owner's Telegram chat. Never mark a meme `approved`
  yourself, and never build a path that publishes without the owner.
- **Don't touch the pool while the owner is vetting.** No batch jobs, no status changes,
  no deletes. A job that re-read "what is approved" mid-vetting once undid their approvals
  and flooded their chat with duplicates. Agree whose turn it is, then act.
- **The public never types.** Visitors pick a theme from a list. Free text as a topic is
  accepted only from the owner's own chat. No open prompt box, on any surface.
- **No approval or admin surface that others can reach.** The review page is local-only;
  owner actions are gated on the owner's chat id.
- **No AI-generated images.** Only existing, well-known meme templates.
- **Tone.** The joke is on the practitioner, never on the teaching. Never ridicule the
  Buddha, bodhisattvas, the Sangha, sacred objects or any religion. For Pure Land themes
  the joke is on the wandering mind, never on Amitabha or the Pure Land.
- **Exposure stays even.** Votes may nudge order, never how often a meme is shown, and
  never by raw count. Nothing is hidden or removed automatically.
- **Chinese is its own context**, not a translation: 汉传佛教 and 人间佛教. The owner reads
  Simplified, so anything shown to them for vetting is in Simplified.
- **Costs have a ceiling.** Anything that calls the model is either rate-limited before
  the call or runs a fixed number of times a day. Random never calls the model.
- **Commits** are authored by the repo owner alone: no AI co-author trailer.

## Things that are easy to get wrong

- **Chinese is stored once, in Traditional** (`lang: "zh"`), and converted to Simplified
  on the way out with OpenCC. Always generate and store Traditional, even for a Simplified
  request; never store Simplified (converting back is ambiguous).
- **The database is the pool; the seed is a bootstrap.** Approved memes now come from the
  daily batch and from visitors' nominations as well, so `seed/memes.jsonl` is not a copy
  of the pool and need not be kept in step. It matters only for an empty table and for the
  site's offline fallback.
- **The portfolio page does not link to this repository**, at the owner's request. Don't
  add a source link there.
- **Deleting a seed meme from the table brings it back.** The seed supplies any meme the
  table has never seen. To remove memes for good: `pool_admin.py write-seed`, commit,
  deploy, and only then `pool_admin.py delete-rejected`.
- **Generated ids carry the time to the second.** Two runs in one minute once overwrote
  each other when ids were per-minute.
- **A meme is sent to the owner once.** `asked` marks it. `send_pending` only picks
  pending memes without it.
- **Text boxes belong to one exact image.** The site build fails if an image is missing or
  not the `size` in the catalog. Changing an image means re-checking its boxes.
- **`web/render.js` and `src/dharmeme/render.py` implement the same fitting rules.** Change
  both. The Python one draws Chinese with the bundled Noto fonts; the website uses the
  device's own Chinese font.
- **The model counts characters badly.** About a third of first replies overrun a slot's
  limit; the retry tells it what was wrong. A one-word free topic used to make it ask a
  question back, which is why the prompt says it is one-shot.
- **The model has favourites.** Offered every template it picked the same one each time,
  so each request offers a random four.
- **Telegram rejects answering a button press that is a few seconds old.** That call is
  best-effort; the action must still happen.
- **Rebuild the Lambda package outside a synced folder.** `build_lambda.py` assembles in a
  temp directory for this reason: building in place under OneDrive produced empty
  dependency folders and a broken deploy.

## How to

**Run the tests.** `pytest` and `cd web && node --test`. Both run in CI on every push,
before the site deploys. They use a stub model and an in-memory store, so they cost
nothing and prove nothing about AWS: after a deploy, check the live system by hand.

**Check a page by eye.** Build with `python scripts/build_site.py --out <dir outside any
synced folder>`, serve it with `python -m http.server`, and screenshot it with a headless
browser. `--review` adds a local page that renders every seed meme.

**Deploy the API.** `python scripts/build_lambda.py`, then `sam deploy` from `deploy/sam/`.
`samconfig.toml` there is gitignored and holds the owner's chat id; if it is missing, ask
the owner for the id (they get it by sending `/id` to the bot) and do not commit it.
Behind a TLS-intercepting proxy, point `AWS_CA_BUNDLE` at a bundle that includes the
proxy's root. After changing bot commands, run the `set_telegram_webhook` admin event.

**Add a template.**
1. On a branch, add a catalog entry with the image `url`, `verified: false` and a
   placeholder slot.
2. Run the `fetch-templates` workflow on that branch (`gh workflow run
   fetch-templates.yml --ref <branch>`); it downloads the image on GitHub and commits it.
3. Pull and **look at the image**. Guessed image addresses have returned the wrong meme
   more than once. On imgflip the address is `i.imgflip.com/<template id in base 36>.jpg`.
4. Write the `format` (the joke, in words, for the model), the slots and their boxes; set
   `size`. `python scripts/check_boxes.py <id>` outlines the boxes.
5. Render real captions on it before trusting it, then set `verified: true`.
6. Add seed captions as `pending`, merge, deploy, and send them to the owner with the
   `send_pending` admin event.

Leave out templates that are politically or racially loaded, depict violence, or have no
room for text.

**Look at or tidy the live pool.** `python scripts/pool_admin.py report | write-seed |
delete-rejected`. A deleted meme can be recovered for 35 days with a DynamoDB
point-in-time restore into a temporary table.

**Try the model.** `python scripts/smoke_llm.py "<topic>"` makes one real call.

## Open items

- **Native Chinese formats** (熊猫头 reaction images) are wanted but unsourced. imgflip
  doesn't carry them: its "panda" templates are ordinary pandas or people in costume. The
  owner would need to supply blank images, or a site with direct image links.
- **Slow first reply.** After a quiet spell the bot takes around 20 seconds, mostly loading
  two large Chinese fonts. One font for both scripts would roughly halve the package.
- **The bot's `/random` can repeat**; the website deals a full pass before repeating.
- **Rotating the bot token** means BotFather `/revoke`, storing the new token in SSM, and
  re-running `set_telegram_webhook` (the webhook secret is derived from the token).
