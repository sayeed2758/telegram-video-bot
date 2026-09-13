from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

WELCOME_TEXT = (
    "👋 <b>Welcome to Advance Tera Video Bot!</b>\n"
    "Made by <b>Legend Shahid (@Dragonn_Exclusive)</b>\n\n"
    "Send me a supported link to get started."
)

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "welcome.jpg"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    if WELCOME_IMAGE.is_file():
        with WELCOME_IMAGE.open("rb") as photo:
            await message.reply_photo(
                photo=photo,
                caption=WELCOME_TEXT,
                parse_mode="HTML",
            )
        return

    await message.reply_text(WELCOME_TEXT, parse_mode="HTML")


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
