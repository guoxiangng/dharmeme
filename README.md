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

- **Template catalog** — each template image has a description of what it shows, the joke
  format, and its text slots.
- **Meme bank** — captions batch-generated offline per template, hand-reviewed, stored as
  complete pairs.
- **Back end** — one AWS Lambda (SAM), Claude Haiku on Amazon Bedrock for the prompt feature.
- **Limits** — per-user daily limit and a global daily cap in DynamoDB; when the cap is hit,
  the prompt feature falls back to a random meme.
- **Front end** — Telegram bot or a single static page (to be decided).

## Status

Just started. Nothing is built yet.
