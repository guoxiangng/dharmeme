# dharmeme

A Buddhist meme generator. Dharma + meme.

Affectionate humour about attachment, impermanence, the middle way and the monkey mind,
drawn onto well-known meme templates.

## Features

- **Random** — serves a pre-written, reviewed meme (template + caption pair). No LLM call at
  request time.
- **Prompt** — give it a topic; an LLM picks the best-fitting template from the catalog and
  writes the text for its slots.

No images are AI-generated. Captions are drawn onto a fixed set of template images.

## Planned architecture

The detailed contracts are in [SPEC.md](SPEC.md).

- **Template catalog** — each template image has a description of what it shows, the joke
  format, and its text slots.
- **Meme bank** — captions batch-generated offline per template, hand-reviewed, stored as
  complete pairs.
- **Back end** — one AWS Lambda (SAM) behind a Function URL, Claude Haiku on Amazon Bedrock
  for the prompt feature. Memes are drawn in the browser, so the backend only returns text.
- **Limits** — per-IP daily limit and a global daily cap in DynamoDB; when the cap is hit,
  the prompt feature falls back to a random meme.
- **Front end** — static web page on GitHub Pages (guoxiangng.github.io/dharmeme) for v1;
  Telegram bot later.

## Status

Live at https://guoxiangng.github.io/dharmeme/. The catalog, renderer, deploy pipeline and
the Random page are in; the first meme bank is awaiting review at `/review.html`. The prompt
feature is next. See SPEC.md §12.

## Try it locally

```
pip install -e ".[dev]"
python scripts/fetch_templates.py      # download the template images (once)
python scripts/build_site.py
python -m http.server -d _site 8000    # open http://localhost:8000/?debug
```

Tests: `pytest` and `cd web && node --test`.
