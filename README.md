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
