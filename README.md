# Advance Tera Video Bot — Phase 11

Phase 11 is a small step forward from Phase 10. It keeps the Render webhook foundation and adds three focused improvements:

1. Password/extraction-code handling for TeraBox shares that explicitly require a password.
2. Clearer classification of password-required vs verification-required failures.
3. A visible `▶️ Play Video` button when a stream URL is returned.

## Password flow

When the resolver reports that a share requires a password, the bot asks the user to send that password in Telegram. The password is used only for the current resolver attempt and is not written to GitHub.

Some TeraBox gateway implementations document `pwd` as the optional parameter for password-protected shares.

## Environment Variables

Keep your working:
- `BOT_TOKEN`
- `RENDER_EXTERNAL_URL`

Optional private session values remain supported:
- `TERABOX_NDUS`
- `TERABOX_COOKIE`

Optional owner-controlled endpoints remain supported:
- `TERABOX_GATEWAY_URL`
- `TERABOX_PROXY_URL`
- `TERABOX_TBX_PROXY_URL`
- `TERABOX_PUBLIC_GATEWAYS`

Do not add fake cookie values. Do not send private cookies/tokens to Telegram or commit them to GitHub.

## Important

Password support does not bypass CAPTCHA or session verification. It only passes a user-provided share password to compatible resolver routes.


## Phase 12 — Session status diagnostics

This phase adds a safe session-status check. The bot can report whether `TERABOX_NDUS` or `TERABOX_COOKIE` exists without ever displaying its value.

Use `/session` in Telegram, or open **🌐 Supported → 🔐 Session Status**.

No new Render environment variable is required. Existing `TERABOX_NDUS` / `TERABOX_COOKIE` remain optional.

The normal resolver still uses the native TeraBox flow first, then the existing anonymous fallbacks.

## Phase 13 note
Phase 13 keeps TeraBox resolution intentionally small and fast. Public third-party fallback chains are disabled by default so a failed share does not leave Telegram stuck on “Processing”. The bot checks only an explicitly configured owner gateway/proxy and the native TeraBox route, then returns quickly when TeraBox requires verification/session or a password.

## Phase 15 — PlayTeraBox API `/api/proxy`

This phase corrects the PlayTeraBox integration to match the endpoint shown in the PlayTeraBox API dashboard.

### API request
- Method: `GET`
- Endpoint: `https://api.playterabox.com/api/proxy`
- Query parameters:
  - `secret` = `TERABOX_API_KEY`
  - `url` = the Telegram TeraBox share URL

### Expected response
The API returns JSON containing a `list` array. Each file may include:
- `name`
- `size`
- `download_link`
- `fast_download_link`
- `stream_url`
- `fast_stream_url`
- `subtitle_url`
- `thumbnail`

The bot uses `download_link`/`fast_download_link` for Download/Play buttons and `stream_url`/`fast_stream_url` for video playback when available.

### Render Environment
Required:
- `BOT_TOKEN`
- `RENDER_EXTERNAL_URL`
- `TERABOX_API_KEY`

Optional:
- `TERABOX_API_URL` = `https://api.playterabox.com/api/proxy`

Keep the API key private. Never paste it into Telegram, GitHub, screenshots, or chat.

The PlayTeraBox API is attempted first. If it succeeds, the bot stops there and does not call the slower native TeraBox resolver.
