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

from bot.config import TERABOX_API_KEY, TERABOX_COOKIE, TERABOX_NDUS
from bot.keyboards import error_keyboard, file_keyboard, welcome_keyboard
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

SESSION_TEXT = (
    "🔐 <b>TeraBox Session Status</b>\n\n"
    "This check only shows whether a private TeraBox session is configured. "
    "It never displays your cookie/token."
)


def _session_status_text() -> str:
    session_line = (
        "✅ Private session configured."
        if (TERABOX_COOKIE or TERABOX_NDUS)
        else "❌ No private TeraBox session configured."
    )
    api_line = (
        "✅ PlayTeraBox API configured (GET /api/proxy)."
        if TERABOX_API_KEY
        else "❌ PlayTeraBox API key not configured."
    )
    return (
        f"{SESSION_TEXT}\n\n"
        f"{session_line}\n"
        f"{api_line}\n\n"
        "🔎 Send a share link to test the active resolver."
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


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            _session_status_text(),
            parse_mode="HTML",
            reply_markup=error_keyboard(),
        )


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
    password: str | None = None,
) -> None:
    context.user_data["last_url"] = url
    if password is None:
        context.user_data.pop("last_password", None)
    else:
        context.user_data["last_password"] = password

    status = await message.reply_text(
        "🔗 <b>TeraBox link detected.</b>\n\n"
        "⏳ Checking the TeraBox share...",
        parse_mode="HTML",
    )

    result = await resolve_link(url, password=password)

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

        # Phase 7 exposes a direct URL only when the resolver actually
        # returned one. No guessed or fabricated links are created.
        first_file = result.files[0] if result.files else None
        first_direct_url = first_file.direct_url if first_file else None
        first_stream_url = first_file.stream_url if first_file else None

        if first_direct_url or first_stream_url:
            lines.append("🎬 <b>Your file is ready.</b>")
            lines.append("Use the buttons below to open or download it.")
        else:
            lines.append(
                "ℹ️ File metadata was found, but no direct file URL was returned yet."
            )

        text = "\n".join(lines)

        await status.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=file_keyboard(first_direct_url, first_stream_url),
        )
        return

    reason = result.message

    lowered = reason.lower()

    if "password required" in lowered:
        context.user_data["awaiting_password"] = True
        text = (
            "🔐 <b>Password required.</b>\n\n"
            "This TeraBox share is asking for an extraction/password code.\n\n"
            "✍️ Send the share password here and I will retry the same link."
        )
    elif "verification required" in lowered or "need verify" in lowered:
        text = (
            "🛡️ <b>TeraBox verification required.</b>\n\n"
            "TeraBox is asking the bot for a verified session for this share.\n\n"
            "🔐 A valid TeraBox session may be required.\n\n"
            "⚡ I stopped the check early instead of waiting on multiple third-party resolvers.\n\n"
            "⚠️ Never send your cookie/token in Telegram or GitHub."
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

    # Phase 11: accept a share password only after the bot explicitly asks for it.
    if context.user_data.get("awaiting_password"):
        password = message.text.strip()
        if not password or len(password) > 64:
            await message.reply_text(
                "⚠️ <b>Invalid password input.</b>\n\nPlease send the TeraBox share password again.",
                parse_mode="HTML",
            )
            return

        context.user_data.pop("awaiting_password", None)
        last_url = context.user_data.get("last_url")
        if not last_url:
            await message.reply_text(
                "ℹ️ I no longer have the previous link. Please send the TeraBox link again.",
                reply_markup=welcome_keyboard(),
            )
            return

        await process_url(message, context, last_url, password=password)
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
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔐 Session Status", callback_data="session")],
                    [
                        InlineKeyboardButton("📖 Help", callback_data="help"),
                        InlineKeyboardButton("🏠 Start", callback_data="start"),
                    ],
                ]
            ),
        )
        return

    if query.data == "session":
        await query.message.reply_text(
            _session_status_text(),
            parse_mode="HTML",
            reply_markup=error_keyboard(),
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

        await process_url(query.message, context, last_url, password=context.user_data.get("last_password"))


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("session", session_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
