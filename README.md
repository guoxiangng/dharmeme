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

Live at https://guoxiangng.github.io/dharmeme/ with both features: Random, and a meme for
your topic. The API (Lambda + DynamoDB + Claude Haiku on Bedrock) is deployed with SAM.
Next: the Telegram bot, then a scheduled generator that grows the pool. See SPEC.md §12.

## Telegram bot

The same Lambda answers a Telegram bot (`/random`, `/meme <topic>`, or just send a topic).
It is off until a bot token exists. To switch it on:

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Store the token (it goes to SSM Parameter Store, encrypted, and nowhere else):

   ```
   aws ssm put-parameter --region ap-southeast-1 --name /dharmeme/telegram-token --type SecureString --value "<token>"
   ```

3. Point the bot at the API (the URL is the stack's `ApiUrl` output):

   ```
   aws lambda invoke --region ap-southeast-1 --function-name <ApiFunction name> --cli-binary-format raw-in-base64-out --payload "{\"admin\":\"set_telegram_webhook\",\"url\":\"<ApiUrl>\"}" out.json
   ```

Topic memes count against the same daily limits as the website, per chat.

## Daily generator

Every day at 09:00 SGT the Lambda writes a batch of new memes and has a second model call
review them. The ones that pass are stored as pending: nothing generated is shown until
the owner approves it. To get them for approval, send `/id` to the bot and deploy with
that number: `sam deploy --parameter-overrides OwnerChatId=<id>`. Each pending meme then
arrives in that chat, and only that chat, with Approve and Reject buttons. The admin event
`{"admin":"send_pending"}` re-sends the ones still pending.

To run it by hand:

```
aws lambda invoke --region ap-southeast-1 --function-name <ApiFunction name> --cli-binary-format raw-in-base64-out --payload "{\"admin\":\"generate\"}" out.json
```

## Try it locally

```
pip install -e ".[dev]"
python scripts/fetch_templates.py      # download the template images (once)
python scripts/build_site.py
python -m http.server -d _site 8000    # open http://localhost:8000/?debug
```

Tests: `pytest` and `cd web && node --test`.
