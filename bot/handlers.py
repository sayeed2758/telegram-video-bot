from html import escape
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from .database import (
    check_and_record_request_limit,
    clear_history,
    count_users,
    log_request,
    recent_requests,
    recent_users,
    recent_history,
    log_history,
    request_stats,
    upsert_user,
)
from .keyboards import (
    file_selection_keyboard,
    home_keyboard,
    platform_keyboard,
    quality_keyboard,
    result_keyboard,
    admin_keyboard,
    history_actions_keyboard,
    history_confirm_keyboard,
)
from .platforms import detect_platform, is_url, normalize_url
from .resolver import FileResult, ResolveResult, resolve_link


PLATFORM_LABELS = {
    "terabox": "TeraBox",
    "diskwala": "DiskWala",
    "flezen": "Flezen",
}


BRAND = "🎬 <b>Tera Video Bot</b>"
BRAND_LINE = "✨ Fast • Clean • Simple"


def _brand_block() -> str:
    return f"{BRAND}\n<i>{BRAND_LINE}</i>"


def _home_message(selected_platform: str = "all") -> str:
    platform_text = "All platforms" if selected_platform == "all" else PLATFORM_LABELS.get(selected_platform, "All platforms")
    return (
        f"{_brand_block()}\n\n"
        "🔗 <b>Send your public link</b> and I'll process it for you.\n\n"
        f"🎯 <b>Selected:</b> {escape(platform_text)}\n"
        "📦 <b>Supported:</b> TeraBox • DiskWala • Flezen"
    )


def _result_details(result: FileResult | ResolveResult) -> str:
    title = escape(getattr(result, "title", "TeraBox file") or "TeraBox file")

    details = (
        f"{BRAND}\n\n"
        "✅ <b>Link processed successfully</b>\n\n"
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

    details += "\n\n🎯 <b>Choose an option below</b>"
    return details


def _is_document_result(result: FileResult) -> bool:
    """Detect common document types so PDFs can be sent as Telegram documents."""
    title = (getattr(result, "title", "") or "").lower().strip()
    document_exts = (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".txt", ".csv",
    )
    return title.endswith(document_exts)


async def _send_file_result(
    message,
    result: FileResult,
    original_url: str,
) -> None:
    """Render videos normally and send PDFs/documents directly when possible."""
    details = _result_details(result)

    # PDF/document support: when the resolver gives us a direct download URL,
    # send the file itself instead of making the user open another button.
    if _is_document_result(result) and result.download_url:
        try:
            await message.reply_document(
                document=result.download_url,
                caption=details,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception:
            # Fall back to the normal result UI if Telegram cannot fetch the URL.
            pass

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
        f"{_home_message() }\n\n"
        "💡 <i>Tip: use 🎯 Select Platform when you want to lock the detector to one service.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)

    await update.message.reply_text(
        f"{BRAND}\n\n"
        "📖 <b>How to use</b>\n\n"
        "1️⃣ Select a platform or keep All selected.\n"
        "2️⃣ Send your public/authorized link.\n"
        "3️⃣ Wait while the link is processed.\n"
        "4️⃣ Use Play, Download, Quality or Copy Link.\n\n"
        "🕘 <b>History:</b> View your recent processed links anytime.\n"
        "ℹ️ <b>Note:</b> Results depend on the configured resolver service.\n\n"
        "💬 <b>Need help?</b> Contact the bot owner directly.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Me", url="https://t.me/Dragonn_Exclusive")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]),
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current user's latest processed links."""
    await _touch_user(update)

    user = update.effective_user
    if not user:
        return

    rows = await recent_history(user.id, 10)

    if not rows:
        await update.message.reply_text(
            "🕘 <b>My History</b>\n\n"
            "No processed links yet.\n\n"
            "Send a supported public link and it will appear here.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    lines = ["🕘 <b>My History</b>", ""]
    buttons = []

    for index, row in enumerate(rows, 1):
        platform = PLATFORM_LABELS.get(
            row["platform"],
            str(row["platform"]).title(),
        )
        status = "✅" if row["status"] == "success" else "❌"
        title = escape(row["title"] or "TeraBox file")
        if len(title) > 70:
            title = title[:67] + "..."
        created = escape(
            row["created_at"].replace("T", " ")[:16]
        )

        lines.append(
            f"{index}. {status} <b>{title}</b>\n"
            f"   {escape(platform)} • {created}"
        )

        if row["status"] == "success" and row["original_url"]:
            buttons.append([
                InlineKeyboardButton(
                    f"🔗 {index}. Open Link",
                    url=row["original_url"],
                )
            ])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            buttons + [
                [InlineKeyboardButton("🗑  Clear History", callback_data="history:clear")],
                [InlineKeyboardButton("🏠 Home", callback_data="home")],
            ]
        ),
    )


async def _is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(ADMIN_ID and user and user.id == ADMIN_ID)


def _stats_text(stats: dict[str, int], users: int) -> str:
    success_rate = round(stats["success"] * 100 / stats["total"], 1) if stats["total"] else 0
    return (
        "📊 <b>Admin Dashboard</b>\n\n"
        f"👥 <b>Users:</b> {users}\n"
        f"🔗 <b>Total requests:</b> {stats['total']}\n"
        f"✅ <b>Successful:</b> {stats['success']}\n"
        f"❌ <b>Failed:</b> {stats['failed']}\n"
        f"📈 <b>Success rate:</b> {success_rate}%\n\n"
        "<b>By platform</b>\n"
        f"• TeraBox: {stats['terabox']}\n"
        f"• DiskWala: {stats['diskwala']}\n"
        f"• Flezen: {stats['flezen']}"
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    if not await _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    stats = await request_stats()
    users = await count_users()
    await update.message.reply_text(
        _stats_text(stats, users),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def _send_admin_stats_message(message) -> None:
    stats = await request_stats()
    users = await count_users()
    await message.edit_text(
        _stats_text(stats, users),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def _admin_users_text() -> str:
    users = await recent_users(10)
    if not users:
        return "👥 <b>Recent Users</b>\n\nNo users recorded yet."
    lines = ["👥 <b>Recent Users</b>", ""]
    for i, user in enumerate(users, 1):
        name = escape(user['first_name'] or "Unknown")
        username = escape(user['username']) if user['username'] else "—"
        lines.append(f"{i}. <b>{name}</b>\n   @{username}\n   ID: <code>{user['user_id']}</code>")
    return "\n".join(lines)


async def _admin_requests_text() -> str:
    rows = await recent_requests(10)
    if not rows:
        return "🧾 <b>Recent Requests</b>\n\nNo requests recorded yet."
    lines = ["🧾 <b>Recent Requests</b>", ""]
    for row in rows:
        platform = PLATFORM_LABELS.get(row['platform'], row['platform'].title())
        status = "✅" if row['status'] == "success" else "❌"
        created = row['created_at'].replace("T", " ")[:19]
        lines.append(f"{status} <b>{escape(platform)}</b> • <code>{row['user_id']}</code> • {escape(created)}")
    return "\n".join(lines)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    if not await _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    stats = await request_stats()
    users = await count_users()
    await update.message.reply_text(
        _stats_text(stats, users),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    text = (update.message.text or "").strip()

    if text == "🎯 Select Platform":
        await update.message.reply_text(
            f"{BRAND}\n\n🎯 <b>Select Platform</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_keyboard(),
        )
        return

    if text == "🕘 My History":
        await history(update, context)
        return

    if text == "ℹ️ Help":
        await help_command(update, context)
        return

    if not is_url(text):
        await update.message.reply_text(
            f"{BRAND}\n\n🔗 <b>Invalid link</b>\n\nPlease send a valid http/https link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    url = normalize_url(text)
    detected = detect_platform(url)
    selected = context.user_data.get("selected_platform", "all")

    if not detected:
        await update.message.reply_text(
            f"{BRAND}\n\n⚠️ <b>Unsupported platform</b>\n\n"
            "I currently recognize <b>TeraBox</b>, <b>DiskWala</b> and <b>Flezen</b> links.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if selected != "all" and selected != detected:
        await update.message.reply_text(
            f"{BRAND}\n\n⚠️ You selected <b>{PLATFORM_LABELS[selected]}</b>, "
            f"but this link is from <b>{PLATFORM_LABELS[detected]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    user = update.effective_user
    if user and not await _is_admin(update):
        allowed, retry_after, remaining_today = await check_and_record_request_limit(
            user.id,
            cooldown_seconds=10,
            daily_limit=40,
        )

        if not allowed:
            if retry_after > 0:
                await update.message.reply_text(
                    "⏳ <b>Please wait a moment.</b>\n\n"
                    f"Try again in <b>{retry_after} seconds</b>.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=home_keyboard(),
                )
            else:
                await update.message.reply_text(
                    "🚦 <b>Daily request limit reached.</b>\n\n"
                    "You have reached today's processing limit. "
                    "Please try again tomorrow.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=home_keyboard(),
                )
            return

    processing = await update.message.reply_text(
        f"{BRAND}\n\n"
        f"🔎 <b>{PLATFORM_LABELS[detected]}</b> link detected.\n"
        "⏳ <b>Processing your link...</b>\n\n"
        "Please wait a moment.",
        parse_mode=ParseMode.HTML,
    )

    await asyncio.sleep(0.35)
    try:
        await processing.edit_text(
            f"{BRAND}\n\n"
            f"🔎 <b>{PLATFORM_LABELS[detected]}</b> detected.\n"
            "⚙️ <b>Fetching available result...</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    try:
        resolved = await resolve_link(url, detected)
    except Exception:
        if update.effective_user:
            await log_request(update.effective_user.id, detected, "failed")
        await processing.edit_text(
            f"{BRAND}\n\n❌ <b>Processing failed</b>\n\nPlease try another public/authorized link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if not resolved.files:
        if update.effective_user:
            await log_request(update.effective_user.id, detected, "failed")
        error_note = resolved.note or "No playable link was returned."
        await processing.edit_text(
            f"{BRAND}\n\n⚠️ <b>Unable to process this link</b>\n\n"
            f"{escape(error_note)}\n\n"
            "Please try another public/authorized link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if update.effective_user:
        await log_request(update.effective_user.id, detected, "success")
        # Store one history entry for the successfully processed share.
        # The original public URL is kept so the user can reopen it later.
        history_title = getattr(resolved.files[0], "title", "TeraBox file") or "TeraBox file"
        await log_history(
            update.effective_user.id,
            detected,
            history_title,
            resolved.original_url or url,
            "success",
        )

    # Keep the whole result set available per user for compact callback data.
    context.user_data["last_resolution"] = resolved
    context.user_data["last_result"] = resolved.files[0]

    if len(resolved.files) > 1:
        count = len(resolved.files)
        message = (
            f"{BRAND}\n\n"
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

    if data.startswith("admin:"):
        if not await _is_admin(update):
            await query.answer("Admin only.", show_alert=True)
            return

        action = data.split(":", 1)[1]
        if action in {"stats", "refresh"}:
            await _send_admin_stats_message(query.message)
            await query.answer("Dashboard refreshed.")
            return
        if action == "users":
            await query.edit_message_text(
                await _admin_users_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=admin_keyboard(),
            )
            await query.answer("Recent users")
            return
        if action == "requests":
            await query.edit_message_text(
                await _admin_requests_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=admin_keyboard(),
            )
            await query.answer("Recent requests")
            return
        if action == "close":
            try:
                await query.message.delete()
            except Exception:
                await query.edit_message_reply_markup(reply_markup=None)
            await query.answer("Admin panel closed.")
            return

    if data == "history:clear":
        await query.edit_message_text(
            "🗑 <b>Clear History</b>\n\n"
            "Are you sure you want to delete your saved history?\n\n"
            "⚠️ This cannot be undone.",
            parse_mode=ParseMode.HTML,
            reply_markup=history_confirm_keyboard(),
        )
        await query.answer("Please confirm.")
        return

    if data == "history:cancel_clear":
        await query.edit_message_text(
            "🕘 <b>History</b>\n\n"
            "Your history was not changed.",
            parse_mode=ParseMode.HTML,
            reply_markup=history_actions_keyboard(),
        )
        await query.answer("Cancelled.")
        return

    if data == "history:confirm_clear":
        user = update.effective_user
        if not user:
            await query.answer("Unable to identify your account.", show_alert=True)
            return

        removed = await clear_history(user.id)
        if removed:
            message = (
                "🗑 <b>History cleared</b>\n\n"
                f"✅ {removed} saved record(s) deleted.\n\n"
                "Your future processed links will appear here again."
            )
        else:
            message = "🕘 <b>History</b>\n\nYour history was already empty."

        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🕘 View History", callback_data="history:view")],
                [InlineKeyboardButton("🏠 Home", callback_data="home")],
            ]),
        )
        await query.answer("Done.")
        return

    if data == "history:view":
        # Callback buttons cannot directly invoke a command handler.
        # Recreate the history text using the same database source.
        user = update.effective_user
        if not user:
            await query.answer("Unable to identify your account.", show_alert=True)
            return

        rows = await recent_history(user.id, 10)
        if not rows:
            await query.edit_message_text(
                "🕘 <b>My History</b>\n\nNo processed links yet.",
                parse_mode=ParseMode.HTML,
                reply_markup=history_actions_keyboard(),
            )
            await query.answer("History is empty.")
            return

        lines = ["🕘 <b>My History</b>", ""]
        buttons = []
        for index, row in enumerate(rows, 1):
            platform = PLATFORM_LABELS.get(row["platform"], str(row["platform"]).title())
            status = "✅" if row["status"] == "success" else "❌"
            title = escape(row["title"] or "TeraBox file")
            if len(title) > 70:
                title = title[:67] + "..."
            created = escape(row["created_at"].replace("T", " ")[:16])
            lines.append(f"{index}. {status} <b>{title}</b>\n   {escape(platform)} • {created}")
            if row["status"] == "success" and row["original_url"]:
                buttons.append([InlineKeyboardButton(f"🔗 {index}. Open Link", url=row["original_url"])])

        buttons.append([InlineKeyboardButton("🗑  Clear History", callback_data="history:clear")])
        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer("History refreshed.")
        return

    if data == "home":
        context.user_data["selected_platform"] = "all"
        try:
            await query.edit_message_text(
                _home_message(),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 Select Platform", callback_data="select_platform")]
                ]),
            )
        except Exception:
            await query.message.reply_text(
                _home_message(),
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
        return

    if data == "select_platform":
        await query.message.reply_text(
            f"{BRAND}\n\n🎯 <b>Select Platform</b>",
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
            message = (
                f"{BRAND}\n\n"
                "✅ <b>All platforms selected.</b>\n\n"
                "Send a supported public link."
            )
        else:
            message = (
                f"{BRAND}\n\n"
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
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
