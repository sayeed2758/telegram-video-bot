import logging
import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder

from bot.handlers import register_handlers

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing from environment variables.")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(application)

    logger.info("Advance Tera Video Bot started.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
