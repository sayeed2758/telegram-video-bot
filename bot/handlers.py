from pathlib import Path
from html import escape

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
from bot.error_messages import classify_resolver_error
from bot.rate_limiter import count_video_files, get_status, is_admin, reset_limit, set_limit, try_consume
from bot.keyboards import (
    error_keyboard,
    file_keyboard,
    file_list_keyboard_compact,
    selected_file_keyboard,
    quality_keyboard,
    welcome_keyboard,
)
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
    "🚦 <b>Daily limit:</b> 2 videos per day by default. Use <code>/mylimit</code> to check your quota.\n\n"
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



def _user_id_from_update(update: Update) -> int | None:
    user = update.effective_user
    return int(user.id) if user is not None else None


def _format_limit_status(status: dict[str, int | str]) -> str:
    limit = int(status["limit"])
    used = int(status["used"])
    if limit < 0:
        limit_text = "♾️ Unlimited"
        remaining_text = "♾️"
    else:
        limit_text = str(limit)
        remaining_text = str(status["remaining"])
    return (
        "🚦 <b>Daily Video Limit</b>\n\n"
        f"📅 Date: <b>{status['date']}</b>\n"
        f"🎬 Used: <b>{used}</b>\n"
        f"🎯 Limit: <b>{limit_text}</b> videos\n"
        f"🟢 Remaining: <b>{remaining_text}</b>"
    )


async def mylimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = _user_id_from_update(update)
    if message is None or user_id is None:
        return
    await message.reply_text(
        _format_limit_status(get_status(user_id)) +
        "\n\nℹ️ Your quota resets automatically at midnight (India time).",
        parse_mode="HTML",
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    await message.reply_text(
        f"🆔 <b>Your Telegram User ID</b>\n\n<code>{user.id}</code>",
        parse_mode="HTML",
    )


async def admin_setlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not is_admin(user.id):
        await message.reply_text("🚫 You are not authorized to use this command.")
        return
    if len(context.args) != 2:
        await message.reply_text(
            "Usage:\n<code>/setlimit USER_ID LIMIT</code>\n\n"
            "LIMIT: -1 = unlimited, 0 = blocked, positive number = videos/day.",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(context.args[0])
        limit = int(context.args[1])
    except ValueError:
        await message.reply_text("⚠️ USER_ID and LIMIT must be numbers.")
        return
    if limit < -1:
        await message.reply_text("⚠️ LIMIT must be -1, 0, or a positive integer.")
        return
    set_limit(target_id, limit)
    status = get_status(target_id)
    await message.reply_text(
        "✅ <b>User limit updated.</b>\n\n"
        f"👤 User: <code>{target_id}</code>\n"
        + _format_limit_status(status),
        parse_mode="HTML",
    )


async def admin_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if len(context.args) > 1:
        if not is_admin(user.id):
            await message.reply_text("🚫 You are not authorized to inspect another user's limit.")
            return
        try:
            target_id = int(context.args[0])
        except ValueError:
            await message.reply_text("⚠️ USER_ID must be a number.")
            return
    else:
        target_id = user.id
    if len(context.args) == 1 and not is_admin(user.id):
        await message.reply_text("🚫 You are not authorized to inspect another user's limit.")
        return
    await message.reply_text(_format_limit_status(get_status(target_id)), parse_mode="HTML")


async def admin_resetlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not is_admin(user.id):
        await message.reply_text("🚫 You are not authorized to use this command.")
        return
    if len(context.args) != 1:
        await message.reply_text(
            "Usage:\n<code>/resetlimit USER_ID</code>",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text("⚠️ USER_ID must be a number.")
        return
    reset_limit(target_id)
    await message.reply_text(
        "✅ <b>User limit reset.</b>\n\n"
        f"👤 User: <code>{target_id}</code>\n"
        "The default daily limit is active again.",
        parse_mode="HTML",
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

    user = context._user if hasattr(context, "_user") else None
    # python-telegram-bot contexts do not expose effective_user directly; the
    # handler stores the caller id before entering this function.
    caller_id = context.user_data.get("rate_limit_user_id")
    if caller_id is not None:
        status_info = get_status(int(caller_id))
        limit = int(status_info["limit"])
        remaining = int(status_info["remaining"])
        if limit >= 0 and remaining <= 0:
            await message.reply_text(
                "🚦 <b>Daily Video Limit Reached</b>\n\n"
                "You have used all your allowed videos for today.\n\n"
                f"🎯 Daily limit: <b>{limit}</b>\n"
                "🔄 Your quota resets automatically at midnight (India time).\n\n"
                "Use <code>/mylimit</code> to check your current quota.",
                parse_mode="HTML",
                reply_markup=error_keyboard(),
            )
            return

    status = await message.reply_text(
        "🔗 <b>TeraBox link detected.</b>\n\n"
        "⏳ Processing your video...",
        parse_mode="HTML",
    )

    result = await resolve_link(url, password=password)

    if result.ok:
        video_count = count_video_files(result.files)
        caller_id = context.user_data.get("rate_limit_user_id")
        if caller_id is not None and video_count > 0:
            caller_id_int = int(caller_id)
            if not try_consume(caller_id_int, video_count):
                quota = get_status(caller_id_int)
                remaining = quota["remaining"]
                await status.edit_text(
                    "🚦 <b>Daily Video Limit Reached</b>\n\n"
                    f"This link contains <b>{video_count}</b> video file(s), but your remaining quota is <b>{remaining}</b>.\n\n"
                    "Please try again after your quota resets, or contact the bot owner if you need a higher limit.",
                    parse_mode="HTML",
                    reply_markup=error_keyboard(),
                )
                return

        # Phase 18: keep the single-file UI, but expose every file from a
        # folder/share through an interactive selector. The resolved data is
        # stored only for the current user/session; URLs are never placed in
        # callback_data.
        context.user_data["resolved_files"] = [
            {
                "name": item.name,
                "size": item.size,
                "thumbnail": item.thumbnail,
                "file_type": item.file_type,
                "duration": item.duration,
                "quality": item.quality,
                "direct_url": item.direct_url,
                "stream_url": item.stream_url,
                "quality_urls": item.quality_urls or {},
            }
            for item in result.files
        ]

        if len(result.files) > 1:
            lines = [
                "✅ <b>Ready!</b>",
                "",
                "⚡ <b>Processed via PlayTeraBox</b>",
                "",
                f"📦 <b>{len(result.files)} file(s) found</b>",
                "",
                "👇 <b>Select a file to continue:</b>",
                "",
            ]

            for index, item in enumerate(result.files, start=1):
                lines.append(
                    f"{index}️⃣ <b>{escape(str(item.name))}</b>\n"
                    f"   💾 {escape(str(item.size))}"
                )
                if index < len(result.files):
                    lines.append("")

            await status.edit_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=file_list_keyboard_compact(
                    [item.name for item in result.files]
                ),
            )
            return

        context.user_data["active_file_index"] = 0
        first_file = result.files[0] if result.files else None
        first_direct_url = first_file.direct_url if first_file else None
        first_stream_url = first_file.stream_url if first_file else None

        lines = [
            "✅ <b>Ready!</b>",
            "",
            "⚡ <b>Processed via PlayTeraBox</b>",
            "",
            f"📦 <b>{len(result.files)} file(s) found</b>",
            "",
        ]

        if first_file:
            lines.append(f"🎬 <b>1. {escape(str(first_file.name))}</b>")
            lines.append(f"💾 Size: {escape(str(first_file.size))}")
            if first_file.file_type:
                lines.append(f"📁 Type: {escape(str(first_file.file_type))}")
            if first_file.duration:
                lines.append(f"⏱️ Duration: {escape(str(first_file.duration))}")
            if first_file.quality:
                lines.append(f"📺 Quality: {escape(str(first_file.quality))}")
            if first_file.thumbnail:
                lines.append("🖼️ Thumbnail available")
            if first_file.stream_url or first_file.quality_urls:
                lines.append("▶️ Video playback available")
            if first_file.quality_urls and len(first_file.quality_urls) >= 2:
                qualities = ", ".join(first_file.quality_urls.keys())
                lines.append(f"🎚️ Qualities: {escape(qualities)}")
            if first_file.direct_url:
                lines.append("📥 Direct download available")
            else:
                lines.append("📥 Direct download link unavailable")
            lines.append("")

        if first_direct_url or first_stream_url:
            lines.append("👇 <b>Choose an action below</b>")
            if first_direct_url:
                lines.append("📥 <i>Download opens the original file link directly.</i>")
        else:
            lines.append(
                "ℹ️ <b>File details found.</b>\n"
                "No playable/download URL was returned for this result."
            )

        markup = file_keyboard(
            first_direct_url,
            first_stream_url,
            first_file.quality_urls if first_file else None,
        )

        if first_file and first_file.thumbnail:
            try:
                await status.delete()
            except Exception:
                pass
            try:
                await message.reply_photo(
                    photo=first_file.thumbnail,
                    caption="\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            except Exception:
                await message.reply_text(
                    "\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=markup,
                )
        else:
            await status.edit_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=markup,
            )
        return

    reason = result.message
    lowered = str(reason or "").lower()

    if "password required" in lowered:
        context.user_data["awaiting_password"] = True
        text = (
            "🔐 <b>Password Required</b>\n\n"
            "This TeraBox share is protected by a password.\n\n"
            "✍️ Send the share password here and I will retry the same link."
        )
    else:
        title, friendly = classify_resolver_error(reason)
        text = (
            f"<b>{title}</b>\n\n"
            f"{friendly}\n\n"
            "🔄 <b>Retry</b> to try the same link again.\n"
            "🛠️ <b>Help</b> if the problem continues."
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

        context.user_data["rate_limit_user_id"] = update.effective_user.id if update.effective_user else None
        await process_url(message, context, last_url, password=password)
        return

    url = extract_url(message.text)

    if url:
        context.user_data["rate_limit_user_id"] = update.effective_user.id if update.effective_user else None
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
        context.user_data.pop("active_file_index", None)
        context.user_data.pop("resolved_files", None)
        await _send_welcome(query.message)
        return

    if query.data and query.data.startswith("select_file:"):
        raw_index = query.data.split(":", 1)[1]
        try:
            index = int(raw_index)
        except ValueError:
            await query.answer("Invalid file selection.", show_alert=True)
            return

        files = context.user_data.get("resolved_files") or []
        if index < 0 or index >= len(files):
            await query.answer("This file selection is no longer available.", show_alert=True)
            return

        item = files[index]
        name = escape(str(item.get("name") or "Unknown file"))
        size = escape(str(item.get("size") or "Unknown size"))
        direct_url = item.get("direct_url")
        stream_url = item.get("stream_url")
        quality_urls = item.get("quality_urls") or {}
        context.user_data["active_file_index"] = index

        lines = [
            "📄 <b>Selected File</b>",
            "",
            f"🎬 <b>{index + 1}. {name}</b>",
            f"💾 Size: {size}",
        ]
        if item.get("file_type"):
            lines.append(f"📁 Type: {escape(str(item.get('file_type')))}")
        if item.get("duration"):
            lines.append(f"⏱️ Duration: {escape(str(item.get('duration')))}")
        if item.get("quality"):
            lines.append(f"📺 Quality: {escape(str(item.get('quality')))}")
        if item.get("thumbnail"):
            lines.append("🖼️ Thumbnail available")
        if stream_url or quality_urls:
            lines.append("▶️ Video playback available")
        if isinstance(quality_urls, dict) and len(quality_urls) >= 2:
            qualities = ", ".join(str(key) for key in quality_urls.keys())
            lines.append(f"🎚️ Qualities available: {escape(qualities)}")
        if direct_url:
            lines.append("📥 Direct download available")
        else:
            lines.append("📥 Direct download link unavailable")
        lines.extend(["", "👇 <b>Choose an action below</b>"])

        await query.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=selected_file_keyboard(
                direct_url,
                stream_url,
                quality_urls if isinstance(quality_urls, dict) else None,
            ),
        )
        return

    if query.data == "quality":
        files = context.user_data.get("resolved_files") or []
        raw_index = context.user_data.get("active_file_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            await query.answer("Please select a file first.", show_alert=True)
            return

        if index < 0 or index >= len(files):
            await query.answer("This file is no longer available.", show_alert=True)
            return

        item = files[index]
        quality_urls = item.get("quality_urls") or {}
        if not isinstance(quality_urls, dict) or len(quality_urls) < 2:
            await query.answer("Multiple video qualities are not available.", show_alert=True)
            return

        qualities = ", ".join(str(key) for key in quality_urls.keys())
        await query.message.edit_text(
            "🎚️ <b>Choose Video Quality</b>\n\n"
            f"📺 Available: <b>{escape(qualities)}</b>\n\n"
            "Tap a quality to open the corresponding video stream.",
            parse_mode="HTML",
            reply_markup=quality_keyboard(quality_urls),
        )
        return

    if query.data == "quality_back":
        files = context.user_data.get("resolved_files") or []
        raw_index = context.user_data.get("active_file_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            await query.answer("Please select a file again.", show_alert=True)
            return

        if index < 0 or index >= len(files):
            await query.answer("This file is no longer available.", show_alert=True)
            return

        item = files[index]
        name = escape(str(item.get("name") or "Unknown file"))
        size = escape(str(item.get("size") or "Unknown size"))
        direct_url = item.get("direct_url")
        stream_url = item.get("stream_url")
        quality_urls = item.get("quality_urls") or {}

        lines = [
            "📄 <b>Selected File</b>",
            "",
            f"🎬 <b>{index + 1}. {name}</b>",
            f"💾 Size: {size}",
        ]
        if item.get("file_type"):
            lines.append(f"📁 Type: {escape(str(item.get('file_type')))}")
        if item.get("duration"):
            lines.append(f"⏱️ Duration: {escape(str(item.get('duration')))}")
        if item.get("quality"):
            lines.append(f"📺 Quality: {escape(str(item.get('quality')))}")
        if item.get("thumbnail"):
            lines.append("🖼️ Thumbnail available")
        if stream_url or quality_urls:
            lines.append("▶️ Video playback available")
        if isinstance(quality_urls, dict) and len(quality_urls) >= 2:
            qualities = ", ".join(str(key) for key in quality_urls.keys())
            lines.append(f"🎚️ Qualities available: {escape(qualities)}")
        if direct_url:
            lines.append("📥 Direct download available")
        else:
            lines.append("📥 Direct download link unavailable")
        lines.extend(["", "👇 <b>Choose an action below</b>"])

        await query.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=selected_file_keyboard(
                direct_url,
                stream_url,
                quality_urls if isinstance(quality_urls, dict) else None,
            ),
        )
        return

    if query.data == "all_files":
        files = context.user_data.get("resolved_files") or []
        if not files:
            await query.answer("The file list is no longer available.", show_alert=True)
            return

        lines = [
            "📂 <b>All Files</b>",
            "",
            f"📦 <b>{len(files)} file(s) found</b>",
            "",
            "👇 <b>Select a file to continue:</b>",
            "",
        ]
        for index, item in enumerate(files, start=1):
            lines.append(
                f"{index}️⃣ <b>{escape(str(item.get('name') or 'Unknown file'))}</b>\n"
                f"   💾 {escape(str(item.get('size') or 'Unknown size'))}"
            )
            if index < len(files):
                lines.append("")

        await query.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=file_list_keyboard_compact([str(item.get("name") or "Unknown file") for item in files]),
        )
        return

    if query.data == "retry":
        last_url = context.user_data.get("last_url")
        if not last_url:
            await query.message.reply_text(
                "ℹ️ There is no previous link to retry.",
                reply_markup=welcome_keyboard(),
            )
            return

        context.user_data["rate_limit_user_id"] = update.effective_user.id if update.effective_user else None
        await process_url(query.message, context, last_url, password=context.user_data.get("last_password"))


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("session", session_command))
    application.add_handler(CommandHandler("mylimit", mylimit_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("limit", admin_limit_command))
    application.add_handler(CommandHandler("setlimit", admin_setlimit_command))
    application.add_handler(CommandHandler("resetlimit", admin_resetlimit_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
