# dharmeme

A Buddhist meme generator. Dharma + meme. All memes are impermanent.

Affectionate humour about attachment, impermanence, wandering minds and lost counts of
recitations, drawn onto well-known meme templates. The joke is always on the person
trying to practise, never on the teaching.

- Web app: https://guoxiangng.github.io/dharmeme/
- Telegram bot: https://t.me/Dhamma_meme_bot
- Write-up: https://guoxiangng.github.io/projects/dharmeme.html

## What it does

- **Random** serves a meme from a pool that a person approved, one by one. No model runs.
- **Themes**: pick a Buddhist theme (impermanence, the bodhisattva vow, Pure Land
  practice…) and a model chooses a template and writes a fresh caption. Visitors pick
  from a list; they never type.
- **Chinese**, in the bot: its own themes and voice for 汉传佛教 and 人间佛教, in Simplified
  and Traditional characters, with its own approved pool.
- **Votes**: 👍, 👎 and Report on pool memes. Votes nudge the order, never the exposure.
- **A daily batch** of new memes, reviewed by a second model call, then held as pending
  until the owner approves each one in a private Telegram chat.

No images are AI-generated. Captions are drawn onto a fixed set of template images.

## How it is built

| Part | Where |
|---|---|
| Website | Static page in `web/`, built by `scripts/build_site.py`, deployed to GitHub Pages by `.github/workflows/pages.yml` |
| API and bot | One Lambda (`src/dharmeme/`, `deploy/lambda/handler.py`) behind a Function URL |
| Pool, votes, limits | One DynamoDB table |
| Model | Claude Haiku on Amazon Bedrock |
| Infrastructure | AWS SAM, `deploy/sam/template.yaml` |

[SPEC.md](SPEC.md) holds the contracts between the parts and is the place to read before
changing behaviour. [CLAUDE.md](CLAUDE.md) holds the working rules and the how-tos.

## Bot commands

| Command | What it does |
|---|---|
| `/random` | A meme from the English pool |
| `/meme` | A list of themes; tap one for a fresh meme |
| `/chineserandom`, `/chineserandom_tw` | A meme from the Chinese pool, 简体 or 繁體 |
| `/chinesememe`, `/chinesememe_tw` | A list of Chinese themes; tap one for a fresh meme |
| `/id` | The chat's id, for setting the owner |

## Run it locally

```
pip install -e ".[dev]"
pytest                                  # Python tests
cd web && node --test && cd ..          # JavaScript tests
python scripts/build_site.py            # builds _site/
python -m http.server -d _site 8000     # http://localhost:8000/?debug outlines the text boxes
```

Served from localhost, the page cannot call the API (it only accepts the live site's
origin), so it shows the memes bundled with the site and themed requests fall back.

## Deploy

The website deploys by itself on every push to `main`.

The API:

```
pip install -e ".[aws]"
python scripts/build_lambda.py          # builds deploy/build/dharmeme.zip
cd deploy/sam && sam deploy             # stack "dharmeme", region ap-southeast-1
```

`deploy/sam/samconfig.toml` is not in the repo. It holds the stack name, region and the
owner's chat id (`parameter_overrides = "OwnerChatId=<id>"`); without it, pass those to
`sam deploy` or the owner is unset and nobody is sent memes to approve.

### Telegram, first time

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Store the token, encrypted, in SSM Parameter Store:

   ```
   aws ssm put-parameter --region ap-southeast-1 --name /dharmeme/telegram-token --type SecureString --value "<token>"
   ```

3. Register the webhook and the command menu (repeat after changing the commands):

   ```
   aws lambda invoke --region ap-southeast-1 --function-name <ApiFunction name> --cli-binary-format raw-in-base64-out --payload "{\"admin\":\"set_telegram_webhook\",\"url\":\"<ApiUrl>\"}" out.json
   ```

4. Send `/id` to the bot and deploy with that number as `OwnerChatId`.

### Admin events

Invoke the Lambda directly (it needs IAM permission; the public URL cannot reach these):

| Payload | Effect |
|---|---|
| `{"admin":"generate"}` | Run the daily batch now; `"langs":["zh"]` for one language |
| `{"admin":"send_pending","limit":20}` | Send the owner pending memes not sent before |
| `{"admin":"set_telegram_webhook","url":"<ApiUrl>"}` | Register the webhook and commands |

## Templates

Each template is an image in `templates/images/` and an entry in `templates/catalog.yaml`
with the joke format in words and its text boxes as fractions of the image. Adding one is
manual on purpose; see CLAUDE.md. `python scripts/check_boxes.py <id>` outlines the boxes
on the image.

Meme templates belong to their respective owners. Fonts: Anton and Noto Sans TC/SC, under
the SIL Open Font License.
