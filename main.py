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
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing from environment variables.")

    if not RENDER_EXTERNAL_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL is missing. Set it to your Render service URL."
        )

    try:
        port = int(os.getenv("PORT", "10000").strip())
    except ValueError as exc:
        raise RuntimeError("PORT must be a valid integer.") from exc

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(application)

    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}"

    logger.info("Starting Advance Tera Video Bot.")
    logger.info("Webhook endpoint configured on /%s", WEBHOOK_PATH)
    logger.info("Listening on 0.0.0.0:%s", port)

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET_TOKEN or None,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
