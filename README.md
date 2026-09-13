# Advance Tera Video Bot — Phase 3

Phase 3 adds the first real TeraBox processing layer.

## Added

- Public TeraBox share-page request
- `jsToken` extraction
- `dp-logid` extraction when available
- TeraBox `share/list` metadata request
- Multiple official/mirror API hosts
- File name and size display
- Clear failure reason in the bot

## Deliberately not added

- Direct download
- Streaming
- Password/private-share bypass
- CAPTCHA/verification bypass
- Third-party worker dependency

This phase is intentionally limited to public-share metadata resolution so the
resolver can be tested independently before download functionality is added.

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
