# Phase 1 — Private Telegram Archive Channel Connection

This phase only connects and verifies a private Telegram channel. It does **not** change the existing TeraBox resolver or send real videos yet.

## 1. Create the private channel

Create a new Telegram channel and keep it **Private**. Example:

`Sayeed Terabox Archive`

## 2. Add the bot as administrator

Open the channel → Administrators → Add Administrator → select your bot.

For Phase 1, allow at least:

- Post Messages
- Edit Messages (optional)
- Delete Messages (recommended for cleanup of the temporary Phase 1 test)

Do not make the channel public just for this phase.

## 3. Get the private channel ID

The value must normally look like:

`-1001234567890`

A practical mobile method is to forward one message from the private channel to a Telegram ID helper that you trust, and use the channel chat ID it reports. Do not share bot tokens or API keys with any helper service.

## 4. Add the Render environment variable

Render → your service → **Environment** → add:

`ARCHIVE_CHANNEL_ID`

Value:

`-1001234567890`

Use your real channel ID. Never paste it into GitHub code.

## 5. Deploy

Push the Phase 1 files to GitHub. Render will redeploy automatically.

## 6. Test from your admin account

Send:

`/channelstatus`

Expected:

`✅ Connection ready.`

Then send:

`/channeltest`

Expected:

`✅ Phase 1 channel test passed.`

A temporary test message will appear in the private channel and the bot will attempt to remove it automatically.

## Important

This phase deliberately does **not** modify the current TeraBox API/resolver flow, daily limits, queue, cache, history database, or user-facing video result. Existing working behavior is preserved.
