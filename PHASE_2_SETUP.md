# Phase 2 — Telegram-Native Video Delivery

Phase 2 upgrades the working resolver so a resolved video is sent to the configured private Telegram archive channel and then copied into the requesting user's chat.

## What changed
- Added `bot/media_delivery.py`.
- `bot/handlers.py` now calls the delivery layer after a successful resolution.
- The resolver/API connection is preserved.
- The Render filesystem is not used as permanent MP4 storage. Telegram receives the direct media URL.
- The video caption already includes the one-hour deletion notice; actual expiry/deletion tracking is the next phase.

## Important
The standard Telegram Bot API has upload-size constraints. This phase does not pretend to provide unlimited file sizes. Large-file support needs a separate infrastructure phase.

## Replace on GitHub
- `bot/media_delivery.py` — NEW
- `bot/handlers.py` — REPLACE

Keep unchanged
- `bot/resolver.py`
- `bot/archive_channel.py`
- `bot/config.py`
- databases
- queue/cache/rate-limit files
- `main.py`

## Test
1. Deploy.
2. Send one authorized/public TeraBox video share that previously resolved successfully.
3. Confirm the bot posts the actual video in the private archive channel.
4. Confirm the bot copies the actual video into the user's chat.
5. Check Render logs for delivery errors if Telegram rejects the media.
