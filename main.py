import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder

from bot.config import BOT_TOKEN
from bot.database import init_db
from bot.handlers import register_handlers

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def startup() -> None:
    await init_db()


def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is missing. Copy .env.example to .env and add your BotFather token."
        )

    asyncio.run(startup())

    app = ApplicationBuilder().token(token).build()
    register_handlers(app)

    logger.info("Bot started with long polling.")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
