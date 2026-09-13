# Advance Tera Video Bot — Phase 4

Phase 4 makes the resolver verification-aware.

## Added

- Current unified TeraBox proxy resolver
- `refresh=1` resolution
- Native TeraBox fallback
- Optional verified session support through environment variables
- `jsToken`, `dp-logid`, and `bdstoken` handling
- Better verification/error messages

## Environment

Existing variables:

```text
BOT_TOKEN=...
RENDER_EXTERNAL_URL=...
```

Optional:

```text
TERABOX_PROXY_URL=https://tbx-proxy.shakir-ansarii075.workers.dev/
TERABOX_COOKIE=...
TERABOX_NDUS=...
```

`TERABOX_COOKIE` and `TERABOX_NDUS` are private credentials. Never put them in GitHub code or screenshots.

## Important

TeraBox can require a verified browser session for some shares. A public share URL can therefore open normally in a browser while the API returns `need verify`. This phase does not bypass CAPTCHA or other verification; it supports using a legitimate verified session when needed.

## Render

Build:
```text
pip install -r requirements.txt
```

Start:
```text
python main.py
```
