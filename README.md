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
