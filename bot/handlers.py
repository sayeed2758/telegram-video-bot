import asyncio
from html import escape
import logging

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
    count_users,
    log_history,
    log_request,
    recent_history,
    recent_requests,
    recent_users,
    request_stats,
    upsert_user,
)
from .keyboards import (
    admin_keyboard,
    file_selection_keyboard,
    home_keyboard,
    platform_keyboard,
    quality_keyboard,
    result_keyboard,
)
from .platforms import detect_platform, is_url, normalize_url
from .resolver import FileResult, ResolveResult, resolve_link

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {
    "terabox": "TeraBox",
    "diskwala": "DiskWala",
    "flezen": "Flezen",
}


def _result_details(result: FileResult | ResolveResult) -> str:
    title = escape(getattr(result, "title", "TeraBox file") or "TeraBox file")
    details = "🎬 <b>TeraBox Result</b>\n\n"
    details += f"📄 <b>Name:</b> {title}\n"

    size = getattr(result, "size_formatted", "")
    duration = getattr(result, "duration", "")
    quality = getattr(result, "quality", "")
    if size:
        details += f"📦 <b>Size:</b> {escape(str(size))}\n"
    if duration:
        details += f"⏱ <b>Duration:</b> {escape(str(duration))}\n"
    if quality:
        details += f"🎞 <b>Quality:</b> {escape(str(quality))}\n"

    details += "\n✅ <b>Ready</b>\nChoose an option below:"
    return details


async def _send_file_result(message, result: FileResult, original_url: str) -> None:
    markup = result_keyboard(
        result.playable_url,
        result.download_url,
        original_url,
        quality_options=tuple(result.quality_urls.keys()),
    )
    details = _result_details(result)

    if result.thumbnail:
        try:
            await message.reply_photo(
                photo=result.thumbnail,
                caption=details,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        except Exception:
            logger.info("Thumbnail could not be sent; using text result.")

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
        "ℹ️ Only public/authorized shares are supported.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    user = update.effective_user
    if not user:
        return

    rows = await recent_history(user.id, 10)
    if not rows:
        await update.message.reply_text(
            "🕘 <b>My History</b>\n\nNo processed links yet.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
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

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            buttons + [[InlineKeyboardButton("🏠 Home", callback_data="home")]]
        ),
    )


async def _is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(ADMIN_ID and user and user.id == ADMIN_ID)


def _stats_text(stats: dict[str, int], users: int) -> str:
    rate = round(stats["success"] * 100 / stats["total"], 1) if stats["total"] else 0
    return (
        "📊 <b>Admin Dashboard</b>\n\n"
        f"👥 <b>Users:</b> {users}\n"
        f"🔗 <b>Total requests:</b> {stats['total']}\n"
        f"✅ <b>Successful:</b> {stats['success']}\n"
        f"❌ <b>Failed:</b> {stats['failed']}\n"
        f"📈 <b>Success rate:</b> {rate}%\n\n"
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
    await update.message.reply_text(
        _stats_text(await request_stats(), await count_users()),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def _send_admin_stats_message(message) -> None:
    await message.edit_text(
        _stats_text(await request_stats(), await count_users()),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def _admin_users_text() -> str:
    users = await recent_users(10)
    if not users:
        return "👥 <b>Recent Users</b>\n\nNo users recorded yet."
    lines = ["👥 <b>Recent Users</b>", ""]
    for i, user in enumerate(users, 1):
        name = escape(user["first_name"] or "Unknown")
        username = escape(user["username"]) if user["username"] else "—"
        lines.append(f"{i}. <b>{name}</b>\n   @{username}\n   ID: <code>{user['user_id']}</code>")
    return "\n".join(lines)


async def _admin_requests_text() -> str:
    rows = await recent_requests(10)
    if not rows:
        return "🧾 <b>Recent Requests</b>\n\nNo requests recorded yet."
    lines = ["🧾 <b>Recent Requests</b>", ""]
    for row in rows:
        platform = PLATFORM_LABELS.get(row["platform"], row["platform"].title())
        status = "✅" if row["status"] == "success" else "❌"
        created = row["created_at"].replace("T", " ")[:19]
        lines.append(
            f"{status} <b>{escape(platform)}</b> • "
            f"<code>{row['user_id']}</code> • {escape(created)}"
        )
    return "\n".join(lines)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    if not await _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text(
        _stats_text(await request_stats(), await count_users()),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _touch_user(update)
    message = update.effective_message
    if not message:
        return
    text = (message.text or "").strip()

    if text == "🎯 Select Platform":
        await message.reply_text("🎯 <b>Select Platform</b>", parse_mode=ParseMode.HTML, reply_markup=platform_keyboard())
        return
    if text == "🕘 My History":
        await history(update, context)
        return
    if text == "ℹ️ Help":
        await help_command(update, context)
        return

    if not is_url(text):
        await message.reply_text(
            "🔗 <b>Invalid link</b>\n\nPlease send a valid http/https link.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    url = normalize_url(text)
    detected = detect_platform(url)
    selected = context.user_data.get("selected_platform", "all")

    if not detected:
        await message.reply_text(
            "⚠️ <b>Unsupported platform</b>\n\n"
            "Supported: <b>TeraBox</b>, <b>DiskWala</b>, <b>Flezen</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    if selected != "all" and selected != detected:
        await message.reply_text(
            f"⚠️ You selected <b>{PLATFORM_LABELS[selected]}</b>, "
            f"but this link is from <b>{PLATFORM_LABELS[detected]}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return

    user = update.effective_user
    if user and not await _is_admin(update):
        allowed, retry_after, _ = await check_and_record_request_limit(user.id, 10, 40)
        if not allowed:
            if retry_after:
                await message.reply_text(
                    f"⏳ <b>Please wait {retry_after} seconds.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=home_keyboard(),
                )
            else:
                await message.reply_text(
                    "🚦 <b>Daily request limit reached.</b>\n\nTry again tomorrow.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=home_keyboard(),
                )
            return

    processing = await message.reply_text(
        f"🔎 <b>{PLATFORM_LABELS[detected]}</b> link detected.\n\n"
        "⏳ Processing your link...",
        parse_mode=ParseMode.HTML,
    )

    try:
        resolved = await asyncio.wait_for(resolve_link(url, detected), timeout=45.0)
    except Exception as exc:
        logger.exception("Unhandled resolve error")
        if user:
            await log_request(user.id, detected, "failed")
        try:
            await processing.edit_text(
                "❌ <b>Processing failed</b>\n\n"
                f"{escape(type(exc).__name__)}\n\n"
                "Please try again with a public/authorized link.",
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
        except Exception:
            pass
        return

    if not resolved.files:
        if user:
            await log_request(user.id, detected, "failed")
        note = resolved.note or "No usable file was returned."
        try:
            await processing.edit_text(
                "⚠️ <b>Unable to process this link</b>\n\n"
                f"{escape(note)}\n\n"
                "Please try again with a public/authorized link.",
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
        except Exception:
            pass
        return

    if user:
        await log_request(user.id, detected, "success")
        await log_history(
            user.id, detected,
            resolved.files[0].title or "TeraBox file",
            resolved.original_url or url,
            "success",
        )

    context.user_data["last_resolution"] = resolved
    context.user_data["last_result"] = resolved.files[0]

    if len(resolved.files) > 1:
        await processing.edit_text(
            "📁 <b>Multiple Files Found</b>\n\n"
            f"✅ {len(resolved.files)} files are available.\n"
            "Select the file you want to open:",
            parse_mode=ParseMode.HTML,
            reply_markup=file_selection_keyboard(tuple(resolved.files)),
        )
        return

    try:
        await processing.delete()
    except Exception:
        pass
    try:
        await _send_file_result(message, resolved.files[0], resolved.original_url)
    except Exception as exc:
        logger.exception("Result delivery failed")
        try:
            await message.reply_text(
                "⚠️ <b>Link resolved, but Telegram could not display the result.</b>\n\n"
                f"{escape(type(exc).__name__)}",
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
        except Exception:
            pass


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
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
            await query.edit_message_text(await _admin_users_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
            await query.answer("Recent users")
            return
        if action == "requests":
            await query.edit_message_text(await _admin_requests_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
            await query.answer("Recent requests")
            return
        if action == "close":
            try:
                await query.message.delete()
            except Exception:
                await query.edit_message_reply_markup(reply_markup=None)
            return

    if data == "home":
        context.user_data["selected_platform"] = "all"
        await query.message.reply_text("🏠 <b>Home</b>", parse_mode=ParseMode.HTML, reply_markup=home_keyboard())
        return

    if data == "select_platform":
        await query.message.reply_text("🎯 <b>Select Platform</b>", parse_mode=ParseMode.HTML, reply_markup=platform_keyboard())
        return

    if data == "noop":
        await query.answer("Only the first 25 files are shown.")
        return

    if data == "files:back":
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if data.startswith("file:"):
        resolved = context.user_data.get("last_resolution")
        if not resolved or not resolved.files:
            await query.answer("File list expired. Send the link again.", show_alert=True)
            return
        try:
            index = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid file selection.", show_alert=True)
            return
        if not 0 <= index < len(resolved.files):
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
            await query.answer("Quality options expired. Send the link again.", show_alert=True)
            return
        await query.edit_message_reply_markup(reply_markup=quality_keyboard(tuple(result.quality_urls)))
        await query.answer("Select a quality.")
        return

    if data == "quality:back":
        result = context.user_data.get("last_result")
        resolved = context.user_data.get("last_resolution")
        if not result:
            await query.answer("Result expired. Send the link again.", show_alert=True)
            return
        await query.edit_message_reply_markup(
            reply_markup=result_keyboard(
                result.playable_url, result.download_url,
                resolved.original_url if resolved else "",
                quality_options=tuple(result.quality_urls),
            )
        )
        return

    if data.startswith("quality:"):
        quality = data.split(":", 1)[1]
        result = context.user_data.get("last_result")
        resolved = context.user_data.get("last_resolution")
        if not result:
            await query.answer("Result expired. Send the link again.", show_alert=True)
            return
        selected_url = result.quality_urls.get(quality)
        if not selected_url:
            await query.answer("That quality is unavailable.", show_alert=True)
            return
        result.playable_url = selected_url
        result.quality = quality
        context.user_data["last_result"] = result
        await query.edit_message_reply_markup(
            reply_markup=result_keyboard(
                result.playable_url, result.download_url,
                resolved.original_url if resolved else "",
                quality_options=tuple(result.quality_urls),
            )
        )
        await query.answer(f"{quality} selected.")
        return

    if data.startswith("platform:"):
        platform = data.split(":", 1)[1]
        if platform not in ("all", *PLATFORM_LABELS):
            await query.answer("Invalid platform.", show_alert=True)
            return
        context.user_data["selected_platform"] = platform
        message = (
            "✅ <b>All platforms selected.</b>\n\nSend a supported public link."
            if platform == "all"
            else f"✅ <b>{PLATFORM_LABELS[platform]}</b> selected.\n\nSend its public link."
        )
        await query.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=home_keyboard())


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram application error", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>Something went wrong.</b>\n\nPlease try the link again.",
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
    except Exception:
        pass


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(global_error_handler)
