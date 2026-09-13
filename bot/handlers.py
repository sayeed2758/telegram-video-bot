from html import escape

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
from .keyboards import (
    file_selection_keyboard,
    home_keyboard,
    platform_keyboard,
    quality_keyboard,
    result_keyboard,
)
from .platforms import detect_platform, is_url, normalize_url
from .resolver import FileResult, ResolveResult, resolve_link


PLATFORM_LABELS = {
    "terabox": "TeraBox",
    "diskwala": "DiskWala",
    "flezen": "Flezen",
}


def _result_details(result: FileResult | ResolveResult) -> str:
    title = escape(getattr(result, "title", "TeraBox file") or "TeraBox file")

    details = (
        "🎬 <b>TeraBox Result</b>\n\n"
        f"📄 <b>Name:</b> {title}\n"
    )

    size_formatted = getattr(result, "size_formatted", "")
    duration = getattr(result, "duration", "")
    quality = getattr(result, "quality", "")

    if size_formatted:
        details += f"📦 <b>Size:</b> {escape(str(size_formatted))}\n"
    if duration:
        details += f"⏱ <b>Duration:</b> {escape(str(duration))}\n"
    if quality:
        details += f"🎞 <b>Quality:</b> {escape(str(quality))}\n"

    details += "\n✅ <b>Ready to play</b>\nChoose an option below:"
    return details


async def _send_file_result(
    message,
    result: FileResult,
    original_url: str,
) -> None:
    """Render a selected file using the same working Phase 4B UI."""
    details = _result_details(result)
    qualities = tuple(result.quality_urls.keys())

    markup = result_keyboard(
        result.playable_url,
        result.download_url,
        original_url,
        quality_options=qualities,
    )

    thumbnail = result.thumbnail or ""
    if thumbnail:
        try:
            await message.reply_photo(
                photo=thumbnail,
                caption=details,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

    await message.reply_text(
        details,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def _touch_user(update: Update) -> None:
    user = update.effective_user
    if user:
        await upsert_user(user.id, user.username, user.first_name)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    context.user_data["selected_platform"] = "all"

    await update.message.reply_text(
        "👋 <b>Welcome to Tera Video Bot</b>\n\n"
        "🔗 Send a supported public link and I'll process it for you.\n\n"
        "Supported: <b>TeraBox</b> • <b>DiskWala</b> • <b>Flezen</b>\n\n"
        "🎯 You can select a platform first.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)

    await update.message.reply_text(
        "📖 <b>How to use</b>\n\n"
        "1️⃣ Select a platform or choose All.\n"
        "2️⃣ Send a public/authorized link.\n"
        "3️⃣ The bot detects the platform.\n"
        "4️⃣ Available files and links will be shown.\n\n"
        "ℹ️ Resolver integrations use configured API services.",
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
            "I currently recognize <b>TeraBox</b>, <b>DiskWala</b> and <b>Flezen</b> links.",
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
        f"🔎 <b>{PLATFORM_LABELS[detected]}</b> link detected.\n\n"
        "⏳ Processing your link...",
        parse_mode=ParseMode.HTML,
    )

    try:
        resolved = await resolve_link(url, detected)
    except Exception:
        await processing.edit_text(
            "❌ <b>Processing failed</b>\n\nPlease try another public/authorized link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if not resolved.files:
        error_note = resolved.note or "No playable link was returned."
        await processing.edit_text(
            "⚠️ <b>Unable to process this link</b>\n\n"
            f"{escape(error_note)}\n\n"
            "Please try another public/authorized link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    # Keep the whole result set available per user for compact callback data.
    context.user_data["last_resolution"] = resolved
    context.user_data["last_result"] = resolved.files[0]

    if len(resolved.files) > 1:
        count = len(resolved.files)
        message = (
            "📁 <b>Multiple Files Found</b>\n\n"
            f"✅ {count} files are available.\n"
            "Select the file you want to open:"
        )

        await processing.edit_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=file_selection_keyboard(tuple(resolved.files)),
        )
        return

    result = resolved.files[0]
    await processing.delete()
    await _send_file_result(update.effective_message, result, resolved.original_url)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "home":
        context.user_data["selected_platform"] = "all"
        await query.message.reply_text(
            "🏠 <b>Home</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if data == "select_platform":
        await query.message.reply_text(
            "🎯 <b>Select Platform</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_keyboard(),
        )
        return

    if data == "noop":
        await query.answer("Only the first 25 files are shown.")
        return

    if data == "files:back":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("Back")
        return

    if data.startswith("file:"):
        resolved = context.user_data.get("last_resolution")
        if not resolved or not getattr(resolved, "files", None):
            await query.answer(
                "File list expired. Please send the link again.",
                show_alert=True,
            )
            return

        try:
            index = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid file selection.", show_alert=True)
            return

        if index < 0 or index >= len(resolved.files):
            await query.answer("That file is unavailable.", show_alert=True)
            return

        result = resolved.files[index]
        context.user_data["last_result"] = result

        try:
            await query.message.delete()
        except Exception:
            pass

        await _send_file_result(query.message, result, resolved.original_url)
        await query.answer(f"File {index + 1} selected.")
        return

    if data == "quality:menu":
        result = context.user_data.get("last_result")
        if not result or not result.quality_urls:
            await query.answer(
                "Quality options are no longer available. Please send the link again.",
                show_alert=True,
            )
            return

        await query.edit_message_reply_markup(
            reply_markup=quality_keyboard(tuple(result.quality_urls.keys()))
        )
        await query.answer("Select a quality.")
        return

    if data == "quality:back":
        result = context.user_data.get("last_result")
        resolved = context.user_data.get("last_resolution")
        if not result:
            await query.answer(
                "Result expired. Please send the link again.",
                show_alert=True,
            )
            return

        original_url = resolved.original_url if resolved else ""
        await query.edit_message_reply_markup(
            reply_markup=result_keyboard(
                result.playable_url,
                result.download_url,
                original_url,
                quality_options=tuple(result.quality_urls.keys()),
            )
        )
        await query.answer("Back to result options.")
        return

    if data.startswith("quality:"):
        quality = data.split(":", 1)[1]
        result = context.user_data.get("last_result")
        resolved = context.user_data.get("last_resolution")

        if not result:
            await query.answer(
                "Result expired. Please send the link again.",
                show_alert=True,
            )
            return

        selected_url = result.quality_urls.get(quality)
        if not selected_url:
            await query.answer(
                "That quality is not available for this file.",
                show_alert=True,
            )
            return

        result.playable_url = selected_url
        result.quality = quality
        context.user_data["last_result"] = result

        original_url = resolved.original_url if resolved else ""
        await query.edit_message_reply_markup(
            reply_markup=result_keyboard(
                result.playable_url,
                result.download_url,
                original_url,
                quality_options=tuple(result.quality_urls.keys()),
            )
        )
        await query.answer(f"{quality} selected.")
        return

    if data.startswith("platform:"):
        platform = data.split(":", 1)[1]
        context.user_data["selected_platform"] = platform

        if platform == "all":
            message = "✅ <b>All platforms selected.</b>\n\nSend a supported public link."
        else:
            message = (
                f"✅ <b>{PLATFORM_LABELS[platform]}</b> selected.\n\n"
                "Send its public link."
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
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
