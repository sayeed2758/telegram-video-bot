# Advance Tera Video Bot — Phase 1

Phase 1 contains only the basic professional `/start` welcome flow.

## Structure

```text
telegram-video-bot/
├── assets/
│   └── welcome.jpg
├── bot/
│   ├── __init__.py
│   └── handlers.py
├── main.py
├── requirements.txt
└── README.md
```

## Environment

Create/set:

```text
BOT_TOKEN=your_telegram_bot_token
```

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Welcome image

Put the funny meme image supplied by you at:

```text
assets/welcome.jpg
```

The `/start` command sends the image with the professional welcome caption.

If the image is not present, the bot will still send the welcome text instead of crashing.
