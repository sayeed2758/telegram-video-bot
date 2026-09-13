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


def main() -> None:
    load_dotenv()

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")

    port = int(os.getenv("PORT", "10000"))
    public_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    webhook_path = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")

    if not public_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is missing.")

    asyncio.run(init_db())

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(application)

    webhook_url = f"{public_url}/{webhook_path}"
    logger.info("Starting webhook on 0.0.0.0:%s", port)
    logger.info("Webhook URL: %s", webhook_url)

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=webhook_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
