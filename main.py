import logging
import asyncio
import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder

from bot.handlers import register_handlers
from bot.cleanup import cleanup_loop, purge_expired_history
from bot.subscription import expire_due_subscriptions, build_expiry_message

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


async def _post_init(application) -> None:
    purge_expired_history()
    expired = expire_due_subscriptions()
    for record in expired:
        try:
            await application.bot.send_message(
                chat_id=int(record["user_id"]),
                text=build_expiry_message(record),
                parse_mode="HTML",
            )
        except Exception:
            pass
    stop_event = asyncio.Event()
    task = asyncio.create_task(cleanup_loop(stop_event, application.bot))
    application.bot_data["cleanup_stop_event"] = stop_event
    application.bot_data["cleanup_task"] = task
    logger.info("Phase 41 cleanup loop started (history TTL=%ss).", __import__("bot.cleanup", fromlist=["HISTORY_TTL_SECONDS"]).HISTORY_TTL_SECONDS)


async def _post_shutdown(application) -> None:
    stop_event = application.bot_data.pop("cleanup_stop_event", None)
    task = application.bot_data.pop("cleanup_task", None)
    if stop_event is not None:
        stop_event.set()
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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

    application = (ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).post_shutdown(_post_shutdown).build())
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
