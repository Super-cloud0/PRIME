# PRIME v1 — Telegram Mini App + Bot launch

## What this version does

- One persistent PRIME account per Telegram user.
- Secure server-side validation of `Telegram.WebApp.initData`.
- PostgreSQL profiles, PRIME Score, ELO and histories.
- Global leaderboard.
- Per-user music upload, playback and deletion.
- Gemini AI advice and face analysis through the backend only.
- A real Telegram bot using a Render webhook.
- The bot sends a button that opens the PRIME Mini App.

## 1. Deploy PRIME

The Render web service runs `server:app` and exposes the HTTPS URL.

After deployment, check:

`https://YOUR-RENDER-DOMAIN/health`

It must return JSON containing `status: ok`.

## 2. Configure secrets in Render

Set these environment variables in the PRIME web service:

- `PRIME_JWT_SECRET` — a long random secret.
- `GEMINI_API_KEY` — your Gemini key (optional until AI is used).
- `TELEGRAM_BOT_TOKEN` — the token from `@BotFather`.
- `TELEGRAM_WEBAPP_URL` — the HTTPS URL of this PRIME web service, for example `https://prime-dmvj.onrender.com`.
- `TELEGRAM_WEBHOOK_SECRET` — a long random secret used only for the Telegram webhook.
- `TELEGRAM_AUTH_MAX_AGE=86400`

Never commit these values to Git.

## 3. Configure the bot in BotFather

Create the bot with `@BotFather` if you have not already done so and copy its token into Render as `TELEGRAM_BOT_TOKEN`.

Set the Mini App URL / Main Mini App to the same value as `TELEGRAM_WEBAPP_URL`.

## 4. Register the webhook

After Render is Live, call Telegram's Bot API once:

`https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://YOUR-RENDER-DOMAIN/api/telegram/webhook&secret_token=<WEBHOOK_SECRET>`

Replace all three placeholders with the exact values from Render. Do not publish the bot token or webhook secret.

Then verify:

`https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo`

The response should contain the webhook URL and no persistent error.

## 5. Test

Open the bot in Telegram and send `/start`.

The bot should reply with an **Open PRIME** button. Opening it should:

1. Authenticate the Telegram account automatically.
2. Create the account on first launch.
3. Keep a separate profile for every Telegram user.
4. Allow PRIME Score / AI analysis.
5. Run ELO matches and save history.
6. Show the global leaderboard.
7. Keep music isolated to the authenticated account.

The backend never trusts a Telegram username or ID sent by the browser alone; it validates the signed `initData` using the bot token.

## Important

The current Render Free instance can sleep when idle. Its local filesystem is not durable across all redeploy/restart scenarios, so production-grade persistent music storage requires a persistent disk/object storage setup. The database should be PostgreSQL for real multi-user data.
