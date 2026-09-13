# Telegram Video Link Bot — Render Ready

Render settings:
- Language: Python 3
- Branch: main
- Root Directory: blank
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Compute: Free (if available)

Environment variables in Render:
- `BOT_TOKEN` = BotFather token
- `WEBHOOK_PATH` = optional custom path

Render automatically provides `PORT` and `RENDER_EXTERNAL_URL`.

Do not commit `.env` or bot tokens.
The resolver layer does not bypass access controls or private APIs; it is reserved for official/licensed/authorized integrations.
