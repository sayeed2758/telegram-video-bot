# Tera Video Bot — Clean Rebuild

## Render
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- Root directory: blank

## Required environment variables
- `BOT_TOKEN` — required
- `RENDER_EXTERNAL_URL` — automatically supplied by Render
- `PORT` — automatically supplied by Render

## Optional environment variables
- `ADMIN_ID`
- `DATABASE_PATH` (default: `bot.db`)
- `WEBHOOK_PATH` (default: `telegram-webhook`)
- `TERABOX_API_KEY` — optional primary resolver API key
- `TERABOX_PUBLIC_WORKER_API` — optional override for public fallback
- `TERABOX_GATEWAY_API` — optional override for gateway fallback

## Resolver behavior
For public TeraBox/TeraBox mirror shares the resolver tries, in order:
1. Native public share page + `share/list`
2. Configured PlayTeraBox API
3. Public worker API
4. Gateway API

Only public/authorized shares are supported. Password-protected/private/captcha-gated shares are not bypassed.

SQLite is kept because it is already part of the project. On Render Free, local SQLite data can be lost when the instance is replaced.


## TeraBox resolver configuration

The bot first uses the native public TeraBox share-page + `share/list` flow. Optional fallbacks are disabled unless explicitly configured.

Optional Render environment variables:

- `TERABOX_API_KEY` — optional PlayTeraBox API key.
- `TERABOX_COOKIE` — optional TeraBox cookie string if a public share requires session cookies.
- `TERABOX_NDUS` — optional `ndus` cookie value; used as a convenience if you do not want to put it in `TERABOX_COOKIE`.
- `TERABOX_RESOLVER_TIMEOUT` — default `15`.
- `TERABOX_PAGE_TIMEOUT` — default `12`.
- `TERABOX_PUBLIC_WORKER_API` — optional external worker fallback; disabled by default.
- `TERABOX_GATEWAY_API` — optional external gateway fallback; disabled by default.

The resolver logs the TeraBox `errno`, response keys, and file count in Render logs. This makes a failed share diagnosable instead of silently falling through several dead endpoints.
