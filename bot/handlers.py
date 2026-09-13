from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.keyboards import error_keyboard, welcome_keyboard
from bot.platforms import TERABOX_HOSTS, extract_url
from bot.resolver import resolve_link

WELCOME_TEXT = (
    "👋 <b>Welcome to Advance Tera Video Bot!</b>\n"
    "Made by <b>Legend Shahid (@Dragonn_Exclusive)</b>\n\n"
    "Send me a supported link to get started."
)

HELP_TEXT = (
    "📖 <b>How to use Advance Tera Video Bot</b>\n\n"
    "1️⃣ Send a public TeraBox share link.\n"
    "2️⃣ I will detect and process the link.\n"
    "3️⃣ If the share can be resolved, its file details will be shown.\n\n"
    "⚠️ Some TeraBox shares may require verification or a valid session.\n\n"
    "🛠️ <b>Any Problem you can Report here :-</b> "
    '<a href="https://t.me/Dragonn_Exclusive">@Dragonn_Exclusive</a>'
)

SUPPORTED_TEXT = (
    "🌐 <b>Supported TeraBox domains</b>\n\n"
    "• terabox.com\n"
    "• terabox.app\n"
    "• 1024tera.com\n"
    "• 1024terabox.com\n"
    "• teraboxshare.com\n"
    "• teraboxlink.com\n"
    "• terafileshare.com\n"
    "• terasharefile.com\n"
    "• terasharelink.com"
)

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "welcome.jpg"


async def _send_welcome(message) -> None:
    if WELCOME_IMAGE.is_file():
        with WELCOME_IMAGE.open("rb") as photo:
            await message.reply_photo(
                photo=photo,
                caption=WELCOME_TEXT,
                parse_mode="HTML",
                reply_markup=welcome_keyboard(),
            )
        return

    await message.reply_text(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=welcome_keyboard(),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    context.user_data.pop("last_url", None)
    await _send_welcome(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            HELP_TEXT,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🛠️ Report a Problem",
                            url="https://t.me/Dragonn_Exclusive",
                        )
                    ],
                    [
                        InlineKeyboardButton("🌐 Supported", callback_data="supported"),
                        InlineKeyboardButton("🏠 Start", callback_data="start"),
                    ],
                ]
            ),
        )


async def process_url(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
) -> None:
    context.user_data["last_url"] = url

    status = await message.reply_text(
        "🔗 <b>TeraBox link detected.</b>\n\n"
        "⏳ Processing your link...",
        parse_mode="HTML",
    )

    result = await resolve_link(url)

    if result.ok:
        lines = [
            "✅ <b>Link processed successfully.</b>",
            "",
            f"📦 Files found: <b>{len(result.files)}</b>",
            "",
        ]

        for index, item in enumerate(result.files, start=1):
            lines.append(f"📄 <b>{index}. {item.name}</b>")
            lines.append(f"💾 Size: {item.size}")
            lines.append("")

        lines.append("ℹ️ Direct download/streaming will be added in a later phase.")
        text = "\n".join(lines)

        await status.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=welcome_keyboard(),
        )
        return

    reason = result.message

    if "verify" in reason.lower():
        text = (
            "🛡️ <b>TeraBox verification required.</b>\n\n"
            "TeraBox is asking for a verified session for this share.\n\n"
            "You can retry after updating the resolver session settings."
        )
    else:
        text = (
            "❌ <b>Could not process this TeraBox link.</b>\n\n"
            f"Reason: {reason}"
        )

    try:
        await status.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=error_keyboard(),
        )
    except Exception:
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=error_keyboard(),
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    url = extract_url(message.text)

    if url:
        await process_url(message, context, url)
        return

    await message.reply_text(
        "⚠️ <b>Unsupported link.</b>\n\n"
        "Please send a valid TeraBox share link.",
        parse_mode="HTML",
        reply_markup=welcome_keyboard(),
    )


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    if query.data == "help":
        await query.message.reply_text(
            HELP_TEXT,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🛠️ Report a Problem",
                            url="https://t.me/Dragonn_Exclusive",
                        )
                    ],
                    [
                        InlineKeyboardButton("🌐 Supported", callback_data="supported"),
                        InlineKeyboardButton("🏠 Start", callback_data="start"),
                    ],
                ]
            ),
        )
        return

    if query.data == "supported":
        await query.message.reply_text(
            SUPPORTED_TEXT,
            parse_mode="HTML",
            reply_markup=welcome_keyboard(),
        )
        return

    if query.data == "start":
        context.user_data.pop("last_url", None)
        await _send_welcome(query.message)
        return

    if query.data == "retry":
        last_url = context.user_data.get("last_url")
        if not last_url:
            await query.message.reply_text(
                "ℹ️ There is no previous link to retry.",
                reply_markup=welcome_keyboard(),
            )
            return

        await process_url(query.message, context, last_url)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
