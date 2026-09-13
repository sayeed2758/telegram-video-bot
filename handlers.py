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

PLATFORM_LABELS = {
    "terabox": "TeraBox",
    "diskwala": "DiskWala",
    "flezen": "Flezen",
}


async def _touch_user(update: Update) -> None:
    user = update.effective_user
    if user:
        await upsert_user(user.id, user.username, user.first_name)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    context.user_data["selected_platform"] = "all"
    await update.message.reply_text(
        "👋 <b>Welcome to Tera Video Bot</b>\n\n"
        "🔗 Send a supported public link and I’ll detect its platform.\n\n"
        "Supported: <b>TeraBox</b> • <b>DiskWala</b> • <b>Flezen</b>\n\n"
        "🎯 You can also select a platform first.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    await update.message.reply_text(
        "📖 <b>How to use</b>\n\n"
        "1️⃣ Select a platform or leave it on All.\n"
        "2️⃣ Send a public link.\n"
        "3️⃣ The bot detects the supported platform.\n"
        "4️⃣ The current resolver opens the original public link.\n\n"
        "ℹ️ Resolver integrations must use an official/licensed/authorized API.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        f"📊 <b>Total users:</b> {await count_users()}",
        parse_mode=ParseMode.HTML,
    )


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
            "🔗 <b>Invalid link</b>\n\nPlease send a valid http/https link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    url = normalize_url(text)
    detected = detect_platform(url)
    selected = context.user_data.get("selected_platform", "all")

    if not detected:
        await update.message.reply_text(
            "⚠️ <b>Unsupported platform</b>\n\n"
            "I recognize TeraBox, DiskWala and Flezen links.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if selected != "all" and selected != detected:
        await update.message.reply_text(
            f"⚠️ You selected <b>{PLATFORM_LABELS[selected]}</b>, "
            f"but this link is from <b>{PLATFORM_LABELS[detected]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    processing = await update.message.reply_text(
        f"🔎 <b>{PLATFORM_LABELS[detected]}</b> link detected.\n⏳ Processing…",
        parse_mode=ParseMode.HTML,
    )

    try:
        result = await resolve_link(url, detected)
    except Exception:
        await processing.edit_text(
            "❌ Processing failed. Please try another public link."
        )
        return

    if result.playable_url:
        await processing.edit_text(
            f"🎬 <b>{PLATFORM_LABELS[detected]}</b>\n\n"
            "✅ Link processed.\n"
            "▶️ Open it using the button below.",
            parse_mode=ParseMode.HTML,
            reply_markup=result_keyboard(result.playable_url),
        )
    else:
        await processing.edit_text(
            "ℹ️ No playable URL was returned by the current resolver.",
            reply_markup=home_keyboard(),
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "home":
        context.user_data["selected_platform"] = "all"
        await query.message.reply_text("🏠 Home", reply_markup=home_keyboard())
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
            "Telegram cannot force-copy arbitrary text to the clipboard.",
            show_alert=True,
        )
        return

    if query.data.startswith("platform:"):
        platform = query.data.split(":", 1)[1]
        context.user_data["selected_platform"] = platform
        message = (
            "✅ <b>All platforms selected.</b>\n\nSend a supported public link."
            if platform == "all"
            else f"✅ <b>{PLATFORM_LABELS[platform]}</b> selected.\n\nSend its public link."
        )
        await query.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
