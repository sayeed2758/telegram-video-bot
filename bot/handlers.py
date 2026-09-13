from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import ADMIN_ID
from .database import count_users, upsert_user
from .keyboards import home_keyboard, platform_keyboard, result_keyboard
from .platforms import detect_platform, is_url, normalize_url
from .resolver import resolve_link


async def _touch_user(update: Update) -> None:
    user = update.effective_user
    if user:
        await upsert_user(
            user.id,
            user.username,
            user.first_name,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    await update.message.reply_text(
        "👋 <b>Welcome!</b>\n\n"
        "Send a supported public link and I will detect its platform.\n\n"
        "Supported: <b>TeraBox</b>, <b>DiskWala</b>, <b>Flezen</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    await update.message.reply_text(
        "📖 <b>How to use</b>\n\n"
        "1. Send a public link.\n"
        "2. I detect the platform.\n"
        "3. In this phase, the original link can be opened directly.\n\n"
        "The resolver layer is prepared for a future official/licensed integration.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)

    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    total = await count_users()
    await update.message.reply_text(f"📊 Users: {total}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    text = (update.message.text or "").strip()

    if text == "🎯 Select Platform":
        await update.message.reply_text(
            "🎯 <b>Select Platform</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_keyboard(),
        )
        return

    if text == "ℹ️ Help":
        await help_command(update, context)
        return

    if not is_url(text):
        await update.message.reply_text(
            "🔗 Please send a valid http/https link.",
            reply_markup=home_keyboard(),
        )
        return

    url = normalize_url(text)
    platform = detect_platform(url) or "unknown"

    if platform == "unknown":
        await update.message.reply_text(
            "⚠️ I couldn't identify this as TeraBox, DiskWala, or Flezen.\n"
            "You can still open the original link below.",
            reply_markup=result_keyboard(url),
        )
        return

    result = await resolve_link(url, platform)

    await update.message.reply_text(
        f"🎬 <b>Platform:</b> {platform.title()}\n\n"
        "✅ Link received successfully.\n"
        "▶️ Use the button below to open the original link.",
        parse_mode=ParseMode.HTML,
        reply_markup=result_keyboard(result.playable_url or result.original_url),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "home":
        await query.message.reply_text(
            "🏠 Home",
            reply_markup=home_keyboard(),
        )
        return

    if query.data == "select_platform":
        await query.message.reply_text(
            "🎯 <b>Select Platform</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_keyboard(),
        )
        return

    if query.data == "copy_hint":
        await query.answer(
            "Telegram bots cannot force-copy arbitrary text to clipboard.",
            show_alert=True,
        )
        return

    if query.data.startswith("platform:"):
        platform = query.data.split(":", 1)[1]
        if platform == "all":
            message = "Send a TeraBox, DiskWala, or Flezen link."
        else:
            message = f"✅ Selected: {platform.title()}\n\nNow send its public link."
        await query.message.reply_text(message, reply_markup=home_keyboard())


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
