from telegram import Update
from telegram.helpers import escape
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
    home_keyboard,
    platform_keyboard,
    result_keyboard,
)
from .platforms import (
    detect_platform,
    is_url,
    normalize_url,
)
from .resolver import resolve_link


PLATFORM_LABELS = {
    "terabox": "TeraBox",
    "diskwala": "DiskWala",
    "flezen": "Flezen",
}


async def _touch_user(update: Update) -> None:
    user = update.effective_user

    if user:
        await upsert_user(
            user.id,
            user.username,
            user.first_name,
        )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    await _touch_user(update)

    context.user_data["selected_platform"] = "all"

    await update.message.reply_text(
        "👋 <b>Welcome to Tera Video Bot</b>\n\n"
        "🔗 Send a supported public link and "
        "I'll process it for you.\n\n"
        "Supported: <b>TeraBox</b> • "
        "<b>DiskWala</b> • <b>Flezen</b>\n\n"
        "🎯 You can select a platform first.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    await _touch_user(update)

    await update.message.reply_text(
        "📖 <b>How to use</b>\n\n"
        "1️⃣ Select a platform or choose All.\n"
        "2️⃣ Send a public/authorized link.\n"
        "3️⃣ The bot detects the platform.\n"
        "4️⃣ Available information and links "
        "will be shown.\n\n"
        "ℹ️ Resolver integrations use configured "
        "API services.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    await _touch_user(update)

    if (
        not ADMIN_ID
        or update.effective_user.id != ADMIN_ID
    ):
        await update.message.reply_text(
            "⛔ Admin only."
        )
        return

    await update.message.reply_text(
        f"📊 <b>Total users:</b> "
        f"{await count_users()}",
        parse_mode=ParseMode.HTML,
    )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

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
            "🔗 <b>Invalid link</b>\n\n"
            "Please send a valid http/https link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    url = normalize_url(text)

    detected = detect_platform(url)

    selected = context.user_data.get(
        "selected_platform",
        "all",
    )

    if not detected:
        await update.message.reply_text(
            "⚠️ <b>Unsupported platform</b>\n\n"
            "I currently recognize "
            "<b>TeraBox</b>, <b>DiskWala</b> "
            "and <b>Flezen</b> links.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if (
        selected != "all"
        and selected != detected
    ):
        await update.message.reply_text(
            f"⚠️ You selected "
            f"<b>{PLATFORM_LABELS[selected]}</b>, "
            f"but this link is from "
            f"<b>{PLATFORM_LABELS[detected]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    processing = await update.message.reply_text(
        f"🔎 <b>{PLATFORM_LABELS[detected]}</b> "
        "link detected.\n\n"
        "⏳ Processing your link...",
        parse_mode=ParseMode.HTML,
    )

    try:
        result = await resolve_link(
            url,
            detected,
        )

    except Exception:
        await processing.edit_text(
            "❌ <b>Processing failed</b>\n\n"
            "Please try another public/authorized link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if result.playable_url:

        safe_title = escape(result.title or "TeraBox file")

        details = (
            "🎬 <b>TeraBox Result</b>\n\n"
            f"📄 <b>Name:</b> "
            f"{safe_title}\n"
        )

        if result.size_formatted:
            details += (
                f"📦 <b>Size:</b> "
                f"{result.size_formatted}\n"
            )

        if result.duration:
            details += (
                f"⏱ <b>Duration:</b> "
                f"{result.duration}\n"
            )

        if result.quality:
            details += (
                f"🎞 <b>Quality:</b> "
                f"{result.quality}\n"
            )

        details += (
            "\n✅ <b>Ready to play</b>\n"
            "Choose an option below:"
        )

        keyboard = result_keyboard(
            result.playable_url,
            result.download_url,
            result.original_url,
        )

        # Phase 4A-1: show the API thumbnail when available.
        # If Telegram cannot fetch it, keep the existing text-result fallback.
        if result.thumbnail:
            try:
                await update.message.reply_photo(
                    photo=result.thumbnail,
                    caption=details,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                await processing.delete()
            except Exception:
                await processing.edit_text(
                    details,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
        else:
            await processing.edit_text(
                details,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    else:

        error_note = result.note or (
            "No playable link was returned."
        )

        await processing.edit_text(
    "⚠️ <b>Unable to process this link</b>\n\n"
    f"{error_note}\n\n"
    "Please try another public/authorized link.",
    parse_mode=ParseMode.HTML,
)

await update.message.reply_text(
    "🏠 Choose an option:",
    reply_markup=home_keyboard(),
)


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    query = update.callback_query

    await query.answer()

    if query.data == "home":

        context.user_data[
            "selected_platform"
        ] = "all"

        await query.message.reply_text(
            "🏠 <b>Home</b>",
            parse_mode=ParseMode.HTML,
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
            "Use the Copy button shown with the link.",
            show_alert=True,
        )

        return

    if query.data.startswith("platform:"):

        platform = query.data.split(
            ":",
            1,
        )[1]

        context.user_data[
            "selected_platform"
        ] = platform

        if platform == "all":

            message = (
                "✅ <b>All platforms selected.</b>\n\n"
                "Send a supported public link."
            )

        else:

            message = (
                f"✅ <b>{PLATFORM_LABELS[platform]}</b> "
                "selected.\n\n"
                "Send its public link."
            )

        await query.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )


def register_handlers(
    app: Application,
) -> None:

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    app.add_handler(
        CommandHandler("stats", stats)
    )

    app.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )
