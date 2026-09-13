from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.platforms import extract_url
from bot.resolver import resolve_link

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


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    url = extract_url(message.text)

    if url:
        status = await message.reply_text(
            "🔗 <b>TeraBox link detected.</b>\n\n"
            "⏳ Processing your link...",
            parse_mode="HTML",
        )

        result = await resolve_link(url)

        if result.ok:
            lines = ["✅ <b>Link processed successfully.</b>", ""]
            for index, item in enumerate(result.files, start=1):
                lines.append(f"📄 <b>{index}. {item.name}</b>")
                lines.append(f"💾 Size: {item.size}")
                lines.append("")
            lines.append("ℹ️ Direct download is not enabled in this phase.")
            text = "\n".join(lines)
        else:
            text = (
                "❌ <b>Could not process this TeraBox link.</b>\n\n"
                f"Reason: {result.message}"
            )

        try:
            await status.edit_text(text, parse_mode="HTML")
        except Exception:
            await message.reply_text(text, parse_mode="HTML")
        return

    await message.reply_text(
        "⚠️ <b>Unsupported link.</b>\n\n"
        "Please send a valid TeraBox share link.",
        parse_mode="HTML",
    )


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
