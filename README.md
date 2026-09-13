# Telegram Video Link Bot — Phase 1

This starter project creates a live Telegram bot with:
- /start and /help
- Home menu
- Platform selector: All, TeraBox, DiskWala, Flezen
- URL detection
- User registration in SQLite
- Basic admin-only /stats
- "Play Original Link" button for links the user submits

Important:
This phase intentionally does NOT bypass platform protections, scrape private APIs, or convert copyrighted/unauthorized media into downloadable files. The resolver layer is left as a safe adapter point for an official/licensed/public integration.

## 1) Create the bot
Open @BotFather on Telegram:
1. /newbot
2. Choose bot name
3. Choose username ending in "bot"
4. Copy the token
5. Put it in .env

Telegram says the token is effectively a password, so keep it private.

## 2) Install
Python 3.11+ recommended.

Windows:
    py -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

Linux/macOS:
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## 3) Configure
Copy .env.example to .env and set BOT_TOKEN.
Optional: set ADMIN_ID to your numeric Telegram user ID.

## 4) Run
    python main.py

This uses long polling, so no domain/HTTPS setup is required for Phase 1.

## 5) Make it 24/7
Later, deploy this same folder to a VPS/container service and run:
    python main.py

For production, webhook mode can also be used. Telegram documents both polling and webhooks in its Bot API docs.

## Project flow
User -> Telegram -> bot.py -> platform detection -> resolver adapter -> response

The resolver adapter is deliberately isolated so we can add an official/licensed API later without rewriting the whole bot.
