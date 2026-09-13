# Advance Tera Video Bot — Phase 9

Phase 9 keeps the Render webhook foundation and adds a **no-cookie public-gateway fallback** for TeraBox public shares.

## Resolver order

1. Owner-configured `TERABOX_GATEWAY_URL` (if set)
2. Owner-configured `TERABOX_PROXY_URL` (if set)
3. Native TeraBox resolver
4. Public no-cookie gateway fallbacks
5. If all fail, the bot reports the actual resolver failure instead of inventing a download link

The public gateway fallback does **not** receive `TERABOX_NDUS` or `TERABOX_COOKIE`.

## Render Environment Variables

Keep your existing working values:

- `BOT_TOKEN`
- `RENDER_EXTERNAL_URL`

Optional private session values:

- `TERABOX_NDUS`
- `TERABOX_COOKIE`

Optional owner-controlled resolver values:

- `TERABOX_GATEWAY_URL`
- `TERABOX_PROXY_URL`

Optional custom public gateway list (comma-separated):

- `TERABOX_PUBLIC_GATEWAYS`

If `TERABOX_PUBLIC_GATEWAYS` is empty, the bot uses the Phase 9 public gateway fallback URLs built into the resolver. These services are third-party and may become unavailable or change behavior, so this is a fallback rather than a guarantee.

## Important

- Never put cookies/tokens in GitHub or Telegram.
- Do not use fake `TERABOX_NDUS` values.
- A TeraBox share may still require password/captcha/session verification; the bot does not bypass those protections.
- No direct URL is fabricated. A Play/Download button appears only when the resolver actually returns a direct URL.
