# Advance Tera Video Bot — Phase 2

Phase 2 adds safe TeraBox link detection.

## Added

- TeraBox domain detection
- TeraBox mirror-domain detection
- Unsupported-link response
- `/start` welcome flow from Phase 1
- Render webhook configuration from Phase 1

## Not added yet

There is deliberately **no TeraBox resolver/API/download logic** in this phase.

## Render

Build:
```text
pip install -r requirements.txt
```

Start:
```text
python main.py
```

Required:
```text
BOT_TOKEN=your_telegram_bot_token
RENDER_EXTERNAL_URL=https://your-service.onrender.com
```

Optional:
```text
WEBHOOK_PATH=telegram-webhook
```

`PORT` is provided by Render.
