from pathlib import Path
from html import escape
from time import perf_counter
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import (
    MAX_LINKS_PER_MESSAGE,
    MAX_MESSAGE_LENGTH,
    TERABOX_API_KEY,
    TERABOX_COOKIE,
    TERABOX_NDUS,
)
from bot.cache import cache_key, get_or_resolve
from bot.error_messages import classify_resolver_error
from bot.rate_limiter import count_video_files, get_status, is_admin, reset_limit, set_limit, try_consume
from bot.subscription import (
    build_activation_message,
    build_expiry_message,
    build_subscription_text,
    expire_due_subscriptions,
    get_active_subscription,
    PLANS,
    activate_subscription,
    expire_subscription,
)
from bot.history import clear_history, find_recent_duplicate, get_history, get_history_item, record_success
from bot.keyboards import (
    error_keyboard,
    file_keyboard,
    file_list_keyboard_compact,
    selected_file_keyboard,
    quality_keyboard,
    subscription_keyboard,
    welcome_keyboard,
)
from bot.platforms import TERABOX_HOSTS, extract_url, extract_urls
from bot.profile import build_profile_text
from bot.queue_manager import RESOLVE_QUEUE
from bot.admin_dashboard import get_dashboard_stats, get_users, get_user_admin_info, reset_user_limit, set_user_limit
from bot.analytics import bootstrap_from_history, get_daily_breakdown, get_period_stats, get_quality_breakdown, get_top_users, record_event
from bot.resolver import resolve_link
from bot.users import get_broadcast_users, get_user_record, mark_inactive, register_user, search_users
from bot.security import validate_incoming_text
from bot.system_control import APP_VERSION, format_uptime, is_maintenance, set_maintenance
from bot.cleanup import purge_expired_history

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
    "🚦 <b>Daily limit:</b> 2 videos per day by default. Use <code>/mylimit</code> to check your quota.\n"
    "📜 <b>History:</b> Your recent successfully processed videos are saved automatically.\n"
    "👤 <b>Profile:</b> View your usage, daily quota, and processing statistics.\n"
    "💳 <b>Subscription:</b> Choose a premium plan and contact the owner to purchase it.\n\n"
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
ANALYTICS_HISTORY_DB = Path(__file__).resolve().parent.parent / "data" / "history.sqlite3"
bootstrap_from_history(ANALYTICS_HISTORY_DB)


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
    register_user(update.effective_user)

    context.user_data.pop("last_url", None)
    await _send_welcome(message)


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    register_user(update.effective_user)
    if message is not None:
        await message.reply_text(
            _session_status_text(),
            parse_mode="HTML",
            reply_markup=error_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    register_user(update.effective_user)
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
                        InlineKeyboardButton("📜 History", callback_data="history"),
                    ],
                    [InlineKeyboardButton("👤 Profile", callback_data="profile")],
                    [InlineKeyboardButton("🏠 Start", callback_data="start")],
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
    register_user(update.effective_user)
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
    register_user(user)
    await message.reply_text(
        f"🆔 <b>Your Telegram User ID</b>\n\n<code>{user.id}</code>",
        parse_mode="HTML",
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    register_user(user)
    await message.reply_text(
        build_profile_text(user),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📜 History", callback_data="history"),
                InlineKeyboardButton("🚦 My Limit", callback_data="mylimit"),
            ],
            [InlineKeyboardButton("💳 Subscription", callback_data="subscription")],
            [InlineKeyboardButton("🏠 Start", callback_data="start")],
        ]),
    )


async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    register_user(user)
    await message.reply_text(
        build_subscription_text(user),
        parse_mode="HTML",
        reply_markup=subscription_keyboard(user),
    )


async def admin_setlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    register_user(user)
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


async def admin_setplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None:
        return
    register_user(actor)
    if not is_admin(actor.id):
        await message.reply_text("🚫 Admin access required.")
        return
    if len(context.args) not in {2, 3}:
        await message.reply_text(
            "Usage:\n<code>/setplan USER_ID PLAN</code>\n\n"
            "Plans: <code>pro</code> or <code>unlimited</code>.\n"
            "Optional payment/reference ID can be supplied as a third argument.",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text("⚠️ USER_ID must be a number.")
        return
    plan_id = context.args[1].strip().lower()
    if plan_id not in PLANS:
        await message.reply_text("⚠️ Unknown plan. Use <code>pro</code> or <code>unlimited</code>.", parse_mode="HTML")
        return
    reference = context.args[2].strip() if len(context.args) == 3 else ""
    previous = get_active_subscription(target_id)
    renewed = bool(previous and str(previous.get("plan_id")) == plan_id)
    record = activate_subscription(target_id, plan_id, source="admin_manual", payment_id=reference)

    delivery = ""
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=build_activation_message(record, renewed=renewed),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 My Subscription", callback_data="subscription")],
                [InlineKeyboardButton("👤 Profile", callback_data="profile")],
            ]),
        )
        delivery = "\n📨 Confirmation sent to the user."
    except Forbidden:
        delivery = "\n⚠️ Subscription activated, but Telegram could not deliver the confirmation (user may have blocked the bot)."
    except BadRequest:
        delivery = "\n⚠️ Subscription activated, but the confirmation message could not be delivered."
    except Exception:
        delivery = "\n⚠️ Subscription activated, but the confirmation message could not be delivered."

    plan = PLANS[plan_id]
    await message.reply_text(
        "✅ <b>Subscription activated</b>\n\n"
        f"👤 User: <code>{target_id}</code>\n"
        f"{plan['emoji']} Plan: <b>{escape(str(plan['name']))}</b>\n"
        f"📅 From: <b>{escape(str(record['started_at']).replace('T', ' '))}</b>\n"
        f"⏳ Until: <b>{escape(str(record['expires_at']).replace('T', ' '))}</b>\n"
        f"🎯 Limit: <b>{'♾️ Unlimited' if int(record['daily_limit']) < 0 else str(record['daily_limit']) + ' videos/day'}</b>"
        f"{delivery}",
        parse_mode="HTML",
    )


async def admin_expire_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None:
        return
    register_user(actor)
    if not is_admin(actor.id):
        await message.reply_text("🚫 Admin access required.")
        return
    if len(context.args) != 1:
        await message.reply_text("Usage:\n<code>/expire USER_ID</code>", parse_mode="HTML")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await message.reply_text("⚠️ USER_ID must be a number.")
        return
    record = get_active_subscription(target_id)
    if not record:
        await message.reply_text("ℹ️ This user does not have an active premium subscription.")
        return
    changed = expire_subscription(target_id)
    if not changed:
        await message.reply_text("ℹ️ The subscription was already inactive.")
        return
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=build_expiry_message(record),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Renew Subscription", callback_data="subscription")],
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
            ]),
        )
    except Exception:
        pass
    await message.reply_text(
        f"✅ <b>Subscription expired</b> for <code>{target_id}</code>.",
        parse_mode="HTML",
    )


async def admin_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None:
        return
    if not is_admin(actor.id):
        await message.reply_text("🚫 Admin access required.")
        return
    lines = [
        "💳 <b>Subscription Management</b>",
        "",
        "⭐ <b>PRO</b> — 50 videos/day • 30 days",
        "💎 <b>UNLIMITED</b> — Unlimited • 30 days",
        "",
        "Use:",
        "<code>/setplan USER_ID pro</code>",
        "<code>/setplan USER_ID unlimited</code>",
        "<code>/expire USER_ID</code>",
        "",
        "After activation the user automatically receives a confirmation with start and expiry time.",
    ]
    await message.reply_text("\n".join(lines), parse_mode="HTML")


def _format_duration_ms(value: int) -> str:
    seconds = max(0, int(value)) / 1000.0
    if seconds < 1:
        return f"{int(value)} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = int(seconds // 60)
    remainder = int(round(seconds % 60))
    return f"{minutes}m {remainder}s"


def _analytics_text() -> str:
    today = get_period_stats("today")
    week = get_period_stats("7d")
    month = get_period_stats("30d")
    daily = get_daily_breakdown(7)
    top_users = get_top_users(5)
    qualities = get_quality_breakdown(30)

    lines = [
        "📈 <b>Analytics Center</b>",
        "",
        "🟢 <b>Today</b>",
        f"• Requests: <b>{today['requests']}</b>",
        f"• Successful requests: <b>{today['successes']}</b>",
        f"• Failed requests: <b>{today['failures']}</b>",
        f"• Videos processed: <b>{today['videos']}</b>",
        f"• Active users: <b>{today['active_users']}</b>",
        f"• Success rate: <b>{today['success_rate']:.1f}%</b>",
        f"• Avg processing time: <b>{_format_duration_ms(today['avg_duration_ms'])}</b>",
        "",
        "📅 <b>Last 7 Days</b>",
        f"• Requests: <b>{week['requests']}</b> • Videos: <b>{week['videos']}</b>",
        f"• Success: <b>{week['successes']}</b> • Failed: <b>{week['failures']}</b>",
        f"• Active users: <b>{week['active_users']}</b> • Rate: <b>{week['success_rate']:.1f}%</b>",
        "",
        "🗓️ <b>Last 30 Days</b>",
        f"• Requests: <b>{month['requests']}</b> • Videos: <b>{month['videos']}</b>",
        f"• Success: <b>{month['successes']}</b> • Failed: <b>{month['failures']}</b>",
        f"• Active users: <b>{month['active_users']}</b> • Rate: <b>{month['success_rate']:.1f}%</b>",
        f"• Avg time: <b>{_format_duration_ms(month['avg_duration_ms'])}</b>",
    ]

    if daily:
        lines.extend(["", "📊 <b>7-Day Daily Breakdown</b>"])
        for item in daily:
            lines.append(
                f"• {item['day']} — 🎬 {item['videos']} | ✅ {item['successes']} | ❌ {item['failures']} | 👥 {item['users']}"
            )

    if top_users:
        lines.extend(["", "🏆 <b>Top Users (30-day analytics)</b>"])
        for index, item in enumerate(top_users, 1):
            lines.append(
                f"{index}. <code>{item['user_id']}</code> — 🎬 {item['videos']} | ✅ {item['successful_requests']} | ❌ {item['failures']}"
            )

    if qualities:
        lines.extend(["", "🎚️ <b>Resolved Quality Breakdown (30 days)</b>"])
        lines.extend(f"• {escape(item['quality'])}: <b>{item['count']}</b>" for item in qualities)

    errors = month.get("errors") or []
    if errors:
        lines.extend(["", "⚠️ <b>Top Error Categories (30 days)</b>"])
        lines.extend(f"• {escape(item['category'])}: <b>{item['count']}</b>" for item in errors)

    return "\n".join(lines)


def _analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")],
        [InlineKeyboardButton("🏠 Start", callback_data="start")],
    ])


async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    register_user(user)
    if not is_admin(user.id):
        await message.reply_text("🚫 <b>Admin access required.</b>", parse_mode="HTML")
        return
    await message.reply_text(_analytics_text(), parse_mode="HTML", reply_markup=_analytics_keyboard())


def _admin_queue_text() -> str:
    snapshot = RESOLVE_QUEUE.snapshot_now()
    active = snapshot["active"]
    waiting = snapshot["waiting"]
    maximum = snapshot["max_concurrent"]
    queue_max = snapshot["max_queue_size"]
    return (
        "⏳ <b>Resolver Queue Status</b>\n\n"
        f"🟢 Active: <b>{active}</b> / <b>{maximum}</b>\n"
        f"🕐 Waiting: <b>{waiting}</b> / <b>{queue_max}</b>\n\n"
        "Each user can have only one active/queued request. "
        "The resolver processes requests in FIFO order."
    )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None or not is_admin(actor.id):
        return
    await message.reply_text(
        _admin_queue_text(),
        parse_mode="HTML",
        reply_markup=_admin_dashboard_keyboard(),
    )


def _admin_status_text() -> str:
    snapshot = RESOLVE_QUEUE.snapshot_now()
    maintenance = "🛑 ON" if is_maintenance() else "🟢 OFF"
    api = "✅ Configured" if TERABOX_API_KEY else "❌ Missing"
    webhook_secret = "✅ Configured" if __import__("bot.config", fromlist=["WEBHOOK_SECRET_TOKEN"]).WEBHOOK_SECRET_TOKEN else "⚠️ Not set"
    return (
        "🩺 <b>System Status</b>\n\n"
        f"🏷️ Version: <b>{APP_VERSION}</b>\n"
        f"⏱️ Uptime: <b>{escape(format_uptime())}</b>\n"
        f"🛠️ Maintenance: <b>{maintenance}</b>\n"
        f"⚡ PlayTeraBox API: <b>{api}</b>\n"
        f"🔐 Webhook secret: <b>{webhook_secret}</b>\n"
        f"🚦 Queue: <b>{snapshot['active']}</b> active / <b>{snapshot['waiting']}</b> waiting\n"
        f"🎯 Concurrency: <b>{snapshot['max_concurrent']}</b>\n"
    )


def _maintenance_text() -> str:
    state = "🛑 <b>Maintenance mode is ON</b>" if is_maintenance() else "🟢 <b>Maintenance mode is OFF</b>"
    if is_maintenance():
        detail = "Normal users are temporarily blocked from processing links. Admin controls remain available."
    else:
        detail = "Users can submit links normally."
    return f"🛠️ <b>Maintenance Control</b>\n\n{state}\n\n{detail}"


def _system_control_keyboard() -> InlineKeyboardMarkup:
    if is_maintenance():
        toggle = InlineKeyboardButton("🟢 Turn Maintenance OFF", callback_data="admin_maintenance_off")
    else:
        toggle = InlineKeyboardButton("🛑 Turn Maintenance ON", callback_data="admin_maintenance_on")
    return InlineKeyboardMarkup([
        [toggle],
        [InlineKeyboardButton("🩺 System Status", callback_data="admin_status")],
        [InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")],
        [InlineKeyboardButton("🏠 Start", callback_data="start")],
    ])


def _admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"), InlineKeyboardButton("📈 Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users"), InlineKeyboardButton("🔎 Find User", callback_data="admin_find_user")],
        [InlineKeyboardButton("💳 Subscriptions", callback_data="admin_subscriptions"), InlineKeyboardButton("⏳ Queue", callback_data="admin_queue")],
        [InlineKeyboardButton("🩺 System Status", callback_data="admin_status"), InlineKeyboardButton("🛠️ Maintenance", callback_data="admin_maintenance")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin")],
        [InlineKeyboardButton("🏠 Start", callback_data="start")],
    ])

def _admin_stats_text() -> str:
    s = get_dashboard_stats()
    return (
        "👑 <b>Admin Dashboard</b>\n\n"
        f"📅 Date: <b>{escape(str(s['date']))}</b>\n\n"
        "👥 <b>User Overview</b>\n"
        f"• Known users: <b>{s['users']}</b>\n"
        f"• Active users: <b>{s['active_registry']}</b>\n"
        f"• Inactive users: <b>{s['inactive_registry']}</b>\n"
        f"• Active today: <b>{s['today_active']}</b>\n"
        f"• Custom limits: <b>{s['custom_limits']}</b>\n\n"
        "🎬 <b>Video Statistics</b>\n"
        f"• Successful videos: <b>{s['videos']}</b>\n"
        f"• Videos today: <b>{s['today_videos']}</b>\n"
        f"• History video records: <b>{s['history_videos']}</b>\n"
        f"• History entries: <b>{s['history_entries']}</b>\n\n"
        f"🎯 Default daily limit: <b>{s['default_limit']}</b> videos"
    )

def _admin_users_keyboard(users) -> InlineKeyboardMarkup:
    rows = []
    for u in users[:15]:
        label = str(u.get("username") or u.get("first_name") or u["user_id"])
        if len(label) > 20:
            label = label[:19] + "…"
        rows.append([
            InlineKeyboardButton(
                f"👤 {label} • 🎬 {u['lifetime_videos']}",
                callback_data=f"admin_user:{u['user_id']}",
            )
        ])
    rows += [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"), InlineKeyboardButton("🔄 Refresh", callback_data="admin_users")],
        [InlineKeyboardButton("🔎 Find User", callback_data="admin_find_user")],
        [InlineKeyboardButton("🏠 Start", callback_data="start")],
    ]
    return InlineKeyboardMarkup(rows)

def _admin_user_keyboard(user_id:int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("0️⃣ Block",callback_data=f"admin_set:{user_id}:0"),InlineKeyboardButton("2️⃣ 2/day",callback_data=f"admin_set:{user_id}:2")],[InlineKeyboardButton("5️⃣ 5/day",callback_data=f"admin_set:{user_id}:5"),InlineKeyboardButton("🔟 10/day",callback_data=f"admin_set:{user_id}:10")],[InlineKeyboardButton("♾️ Unlimited",callback_data=f"admin_set:{user_id}:-1"),InlineKeyboardButton("↩️ Default",callback_data=f"admin_reset:{user_id}")],[InlineKeyboardButton("👥 Users",callback_data="admin_users")],[InlineKeyboardButton("🏠 Start",callback_data="start")]])

def _admin_user_text(user_id: int) -> str:
    i = get_user_admin_info(user_id)
    lt = "♾️ Unlimited" if int(i["limit"]) < 0 else str(i["limit"])
    rem = "♾️" if int(i["remaining"]) < 0 else str(i["remaining"])
    username = f"@{i['username']}" if i.get("username") else "Not set"
    name = i.get("first_name") or "Unknown"
    activity = "🟢 Active" if int(i.get("is_active", 0)) else "⚪ Inactive"
    last_seen = i.get("last_seen") or "No activity recorded"
    last_processed = i.get("last_processed_at") or "No successful video yet"
    return (
        "👤 <b>User Administration</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"👤 Name: <b>{escape(str(name))}</b>\n"
        f"🔗 Username: <b>{escape(username)}</b>\n"
        f"📡 Status: <b>{activity}</b>\n"
        f"🕒 Last seen: <b>{escape(str(last_seen))}</b>\n\n"
        "📊 <b>Usage</b>\n"
        f"• 🎬 Successful videos: <b>{i['history_videos']}</b>\n"
        f"• 📜 History entries: <b>{i['history_entries']}</b>\n"
        f"• 📅 Today: <b>{i['used']}</b> used\n"
        f"• 🎯 Daily limit: <b>{escape(lt)}</b>\n"
        f"• 🟢 Remaining today: <b>{escape(rem)}</b>\n"
        f"• 🕘 Last successful processing: <b>{escape(str(last_processed))}</b>\n\n"
        "👇 <b>Select a limit action:</b>"
    )


def _admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"), InlineKeyboardButton("📈 Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users"), InlineKeyboardButton("🔎 Find User", callback_data="admin_find_user")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin")],
        [InlineKeyboardButton("🏠 Start", callback_data="start")],
    ])


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None or not is_admin(actor.id):
        if message is not None:
            await message.reply_text("🚫 Admin access required.")
        return
    users = get_users(15)
    if not users:
        await message.reply_text("👥 <b>Users</b>\n\nNo user records are available yet.", parse_mode="HTML", reply_markup=_admin_dashboard_keyboard())
        return
    lines = ["👥 <b>User Management</b>", "", "Tap a user to inspect identity, activity, usage and limits.", ""]
    for n, item in enumerate(users, 1):
        identity = f"@{item['username']}" if item.get('username') else (item.get('first_name') or 'No username')
        lines.append(f"{n}. <b>{escape(identity)}</b> • <code>{item['user_id']}</code> • 🎬 {item['lifetime_videos']}")
    await message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=_admin_users_keyboard(users))


async def find_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None or not is_admin(actor.id):
        if message is not None:
            await message.reply_text("🚫 Admin access required.")
        return
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await _admin_find_user_prompt(message, context)
        return
    matches = search_users(query, 10)
    if not matches:
        await message.reply_text(
            f"🔎 <b>No user found</b>\n\nSearch: <code>{escape(query)}</code>",
            parse_mode="HTML",
            reply_markup=_admin_dashboard_keyboard(),
        )
        return
    rows = []
    for item in matches:
        label = f"@{item['username']}" if item.get('username') else (item.get('first_name') or str(item['user_id']))
        rows.append([InlineKeyboardButton(f"👤 {label} • {item['user_id']}", callback_data=f"admin_user:{item['user_id']}")])
    rows.append([InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")])
    await message.reply_text(
        f"🔎 <b>Search Results</b>\n\nQuery: <code>{escape(query)}</code>\nFound: <b>{len(matches)}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _start_broadcast(message, context, draft: str | None = None, actor=None) -> None:
    actor = actor or getattr(message, "from_user", None)
    if actor is None or not is_admin(actor.id):
        await message.reply_text("🚫 Admin access required.")
        return

    if draft is None:
        context.user_data["awaiting_broadcast"] = True
        await message.reply_text(
            "📢 <b>Broadcast Message</b>\n\n"
            "Send the message you want to broadcast to all active users.\n\n"
            "📝 Text messages only in Phase 28.\n"
            "❌ Use the Cancel button to stop.\n\n"
            "Maximum length: 4096 characters.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_broadcast_cancel")]]),
        )
        return

    draft = draft.strip()
    if not draft:
        await message.reply_text("⚠️ Broadcast message cannot be empty.")
        return
    if len(draft) > 4096:
        await message.reply_text("⚠️ Broadcast message is too long. Telegram allows up to 4096 characters per message.")
        return

    context.user_data["broadcast_draft"] = draft
    recipients = get_broadcast_users()
    await message.reply_text(
        "📢 <b>Broadcast Preview</b>\n\n"
        f"<b>Recipients:</b> {len(recipients)} active user(s)\n\n"
        "<b>Message:</b>\n"
        f"<pre>{escape(draft)}</pre>\n\n"
        "Send this message to all active users?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Send Broadcast", callback_data="admin_broadcast_confirm"), InlineKeyboardButton("❌ Cancel", callback_data="admin_broadcast_cancel")],
            [InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")],
        ]),
    )


async def _send_broadcast(message, context, actor=None) -> None:
    actor = actor or getattr(message, "from_user", None)
    if actor is None or not is_admin(actor.id):
        await message.reply_text("🚫 Admin access required.")
        return

    draft = context.user_data.pop("broadcast_draft", None)
    if not isinstance(draft, str) or not draft.strip():
        await message.reply_text("ℹ️ There is no broadcast draft to send.", reply_markup=_admin_broadcast_keyboard())
        return

    recipients = get_broadcast_users()
    if not recipients:
        await message.reply_text(
            "📢 <b>Broadcast Complete</b>\n\nNo active users are registered yet.",
            parse_mode="HTML",
            reply_markup=_admin_broadcast_keyboard(),
        )
        return

    progress = await message.reply_text(
        "📢 <b>Broadcasting...</b>\n\n"
        f"👥 Recipients: <b>{len(recipients)}</b>\n"
        "⏳ Please wait while the messages are delivered.",
        parse_mode="HTML",
    )

    sent = 0
    failed = 0
    blocked = 0
    for user_id in recipients:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=draft,
                disable_web_page_preview=True,
            )
            sent += 1
            # Stay below the normal Telegram broadcast throughput.
            await __import__("asyncio").sleep(0.06)
        except RetryAfter as exc:
            wait_for = max(1.0, float(exc.retry_after))
            await __import__("asyncio").sleep(wait_for)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=draft,
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception:
                failed += 1
        except (Forbidden, BadRequest):
            blocked += 1
            mark_inactive(user_id)
        except Exception:
            failed += 1

    await progress.edit_text(
        "📢 <b>Broadcast Complete</b>\n\n"
        f"✅ Sent: <b>{sent}</b>\n"
        f"🚫 Inactive/blocked: <b>{blocked}</b>\n"
        f"⚠️ Failed: <b>{failed}</b>\n"
        f"👥 Attempted: <b>{len(recipients)}</b>",
        parse_mode="HTML",
        reply_markup=_admin_broadcast_keyboard(),
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    register_user(user)
    if not is_admin(user.id):
        await message.reply_text("🚫 Admin access required.")
        return
    draft = " ".join(context.args).strip() if context.args else None
    await _start_broadcast(message, context, draft)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None or not is_admin(actor.id):
        if message is not None:
            await message.reply_text("🚫 Admin access required.")
        return
    await message.reply_text(_admin_status_text(), parse_mode="HTML", reply_markup=_system_control_keyboard())


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    actor = update.effective_user
    if message is None or actor is None or not is_admin(actor.id):
        if message is not None:
            await message.reply_text("🚫 Admin access required.")
        return

    arg = (context.args[0].strip().lower() if context.args else "")
    if arg in {"on", "off"}:
        set_maintenance(arg == "on")
    elif arg:
        await message.reply_text("⚠️ Use <code>/maintenance on</code> or <code>/maintenance off</code>.", parse_mode="HTML")
        return

    await message.reply_text(_maintenance_text(), parse_mode="HTML", reply_markup=_system_control_keyboard())


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m=update.effective_message; u=update.effective_user
    if m is None or u is None: return
    register_user(u)
    if not is_admin(u.id):
        await m.reply_text("🚫 <b>Admin access required.</b>",parse_mode="HTML"); return
    await m.reply_text(_admin_stats_text(),parse_mode="HTML",reply_markup=_admin_dashboard_keyboard())

async def _admin_find_user_prompt(message, context):
    context.user_data["awaiting_admin_user_search"] = True
    await message.reply_text(
        "🔎 <b>Find User</b>\n\n"
        "Send a Telegram User ID, <code>@username</code>, or part of the user's name.\n\n"
        "Example: <code>7955228561</code> or <code>@username</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin")]]),
    )

def _history_keyboard(rows) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(rows, start=1):
        names = item.get("file_names") or []
        label = str(names[0]) if names else "Processed TeraBox file"
        label = " ".join(label.split())
        if len(label) > 28:
            label = label[:27].rstrip() + "…"
        buttons.append([
            InlineKeyboardButton(
                f"{index}️⃣ {label}",
                callback_data=f"history_view:{item['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton("🗑️ Clear History", callback_data="history_clear"),
        InlineKeyboardButton("🏠 Start", callback_data="start"),
    ])
    return InlineKeyboardMarkup(buttons)


def _format_history_date(value: str) -> str:
    try:
        parsed = __import__("datetime").datetime.fromisoformat(value)
        return parsed.strftime("%d %b %Y • %I:%M %p")
    except Exception:
        return value


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = _user_id_from_update(update)
    if message is None or user_id is None:
        return
    register_user(update.effective_user)

    rows = get_history(user_id)
    if not rows:
        await message.reply_text(
            "📜 <b>Your History</b>\n\n"
            "No successfully processed videos are in your history yet.\n\n"
            "Send a TeraBox link and it will appear here automatically.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Start", callback_data="start")]
            ]),
        )
        return

    lines = [
        "📜 <b>Recent Video History</b>",
        "",
        "Your latest successfully processed TeraBox videos are saved here.",
        "",
    ]
    for index, item in enumerate(rows, start=1):
        names = item.get("file_names") or []
        first_name = names[0] if names else "Processed file"
        if len(names) > 1:
            name_line = f"{first_name} + {len(names) - 1} more"
        else:
            name_line = first_name
        lines.append(
            f"{index}️⃣ <b>{escape(name_line[:110])}</b>\n"
            f"   📦 {item['file_count']} file(s) • 🎬 {item['video_count']} video(s)\n"
            f"   🕒 {escape(_format_history_date(item['created_at']))}"
        )
        if index < len(rows):
            lines.append("")

    lines.extend(["", "👇 <b>Tap an entry to view it or process it again.</b>"])
    await message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_history_keyboard(rows),
    )


async def clear_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = _user_id_from_update(update)
    if message is None or user_id is None:
        return
    deleted = clear_history(user_id)
    if deleted:
        text = f"🗑️ <b>History cleared.</b>\n\nRemoved <b>{deleted}</b> saved entr{'y' if deleted == 1 else 'ies'}."
    else:
        text = "🗑️ <b>History is already empty.</b>"
    await message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 History", callback_data="history")],
            [InlineKeyboardButton("🏠 Start", callback_data="start")],
        ]),
    )


async def process_url(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    password: str | None = None,
    skip_duplicate_check: bool = False,
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

    purge_expired_history()

    # Phase 5: stop accidental re-processing of the same recent link before
    # spending another resolver/API request. Explicit Retry/Process Again
    # actions pass skip_duplicate_check=True so users can intentionally re-run.
    if caller_id is not None and not skip_duplicate_check:
        duplicate = find_recent_duplicate(int(caller_id), url)
        if duplicate is not None:
            age = int(duplicate.get("age_seconds", 0))
            if age < 60:
                age_text = "just now"
            else:
                age_text = f"{age // 60}m ago" if age < 3600 else "recently"
            context.user_data["pending_duplicate_url"] = url
            await message.reply_text(
                "♻️ <b>Duplicate Link Detected</b>\n\n"
                "You already processed this link " + f"<b>{age_text}</b>.\n"
                "I stopped here so I don't waste another resolver/API request.\n\n"
                "Do you want to process it again?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Process Again", callback_data="duplicate_process")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="duplicate_cancel")],
                ]),
            )
            return

    processing_started_at = perf_counter()
    if caller_id is not None:
        record_event(int(caller_id), "processing_started")

    status = await message.reply_text(
        "🔗 <b>TeraBox link detected.</b>\n\n"
        "⏳ <b>Processing your video...</b>\n"
        "[░░░░░░░░░░] 0%\n"
        "🔎 Detecting link",
        parse_mode="HTML",
    )

    # Phase 30: keep the upstream resolver bounded and FIFO so several users
    # can use the bot at once without creating an API request burst. One user
    # may have only one active/queued resolver job at a time.
    queue_ticket, queue_reason = await RESOLVE_QUEUE.acquire(caller_id)
    if queue_ticket is None:
        if queue_reason in {"active", "queued"}:
            text = (
                "⏳ <b>Your previous request is still being processed.</b>\n\n"
                "Please wait for that result before sending another link. This prevents duplicate API requests."
            )
        else:
            text = (
                "🚦 <b>Processing queue is busy.</b>\n\n"
                "Too many requests are waiting right now. Please try again in a little while."
            )
        await status.edit_text(text, parse_mode="HTML", reply_markup=error_keyboard())
        return

    if queue_ticket.queued:
        try:
            await status.edit_text(
                "🔗 <b>TeraBox link detected.</b>\n\n"
                f"⏳ <b>You are in the processing queue.</b>\n"
                f"📍 Position: <b>{queue_ticket.position}</b>\n\n"
                "Please wait — your request will start automatically.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await queue_ticket.wait()
        try:
            await status.edit_text(
                "⚡ <b>Your turn has started.</b>\n\n"
                "⏳ Processing your video...",
                parse_mode="HTML",
            )
        except Exception:
            pass

    cache_hit = False
    progress_stop = asyncio.Event()

    async def _progress_loop() -> None:
        stages = [
            (18, "🔎 Link detected"),
            (38, "⚡ Connecting to PlayTeraBox"),
            (60, "📦 Fetching video information"),
            (78, "🎬 Preparing playback"),
            (92, "✅ Finalizing result"),
        ]
        for percent, label in stages:
            if progress_stop.is_set():
                return
            filled = percent // 10
            bar = "█" * filled + "░" * (10 - filled)
            try:
                await status.edit_text(
                    "⏳ <b>Processing your video...</b>\n"
                    f"[{bar}] {percent}%\n"
                    f"{label}",
                    parse_mode="HTML",
                )
            except (BadRequest, Forbidden):
                return
            try:
                await asyncio.wait_for(progress_stop.wait(), timeout=1.8)
                return
            except asyncio.TimeoutError:
                pass

    progress_task = asyncio.create_task(_progress_loop())
    try:
        result, cache_hit = await get_or_resolve(
            cache_key(url, password),
            lambda: resolve_link(url, password=password),
        )
    finally:
        progress_stop.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass
        await RESOLVE_QUEUE.release(queue_ticket)

    duration_ms = int((perf_counter() - processing_started_at) * 1000)

    if result.ok:
        video_count = count_video_files(result.files)
        caller_id = context.user_data.get("rate_limit_user_id")
        if caller_id is not None and video_count > 0:
            caller_id_int = int(caller_id)
            if not try_consume(caller_id_int, video_count):
                quota = get_status(caller_id_int)
                remaining = quota["remaining"]
                record_event(
                    caller_id_int,
                    "quota_blocked",
                    duration_ms=duration_ms,
                    video_count=video_count,
                    file_count=len(result.files),
                )
                await status.edit_text(
                    "🚦 <b>Daily Video Limit Reached</b>\n\n"
                    f"This link contains <b>{video_count}</b> video file(s), but your remaining quota is <b>{remaining}</b>.\n\n"
                    "Please try again after your quota resets, or contact the bot owner if you need a higher limit.",
                    parse_mode="HTML",
                    reply_markup=error_keyboard(),
                )
                return

        caller_id_for_history = context.user_data.get("rate_limit_user_id")
        if caller_id_for_history is not None and video_count > 0:
            record_success(int(caller_id_for_history), url, result.files, video_count)
            record_event(
                int(caller_id_for_history),
                "processing_success",
                duration_ms=duration_ms,
                video_count=video_count,
                file_count=len(result.files),
            )
            if cache_hit:
                record_event(
                    int(caller_id_for_history),
                    "processing_cache_hit",
                    duration_ms=duration_ms,
                    video_count=video_count,
                    file_count=len(result.files),
                )
            for resolved_file in result.files:
                quality = str(resolved_file.quality or "").strip()
                if quality:
                    record_event(
                        int(caller_id_for_history),
                        "resolved_quality",
                        error_category=quality,
                    )

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
                "🎬 <b>Videos Ready</b>",
                "",
                "⚡ <b>Processed via PlayTeraBox</b>" + (" • ⚡ Cached" if cache_hit else ""),
                "🧹 <i>History details clear automatically after 1 hour.</i>",
                f"📦 <b>{len(result.files)} file(s)</b>",
                "",
                "👇 <b>Select a file to view actions</b>",
                "",
            ]

            for index, item in enumerate(result.files, start=1):
                name = escape(str(item.name))
                size = escape(str(item.size))
                lines.append(f"{index}️⃣ <b>{name}</b>\n   💾 {size}")
                if item.duration:
                    lines.append(f"   ⏱️ {escape(str(item.duration))}")
                if item.quality:
                    lines.append(f"   📺 {escape(str(item.quality))}")
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

        def _compact_name(value: str, limit: int = 85) -> str:
            clean = " ".join(str(value).split())
            if len(clean) <= limit:
                return clean
            return clean[: limit - 1].rstrip() + "…"

        lines = [
            "✅ <b>Video Ready</b>",
            "",
            "⚡ <b>PlayTeraBox</b>" + (" • ⚡ Cached" if cache_hit else ""),
            "🧹 <i>History details are automatically cleared after 1 hour.</i>",
        ]

        if first_file:
            lines.extend([
                "",
                f"🎬 <b>{escape(_compact_name(first_file.name))}</b>",
                "",
                f"💾 <b>Size:</b> {escape(str(first_file.size))}",
                f"📁 <b>Type:</b> {escape(str(first_file.file_type or 'video'))}",
            ])
            if first_file.duration:
                lines.append(f"⏱️ <b>Duration:</b> {escape(str(first_file.duration))}")
            if first_file.quality:
                lines.append(f"📺 <b>Quality:</b> {escape(str(first_file.quality))}")

            playback_available = bool(first_file.stream_url or first_file.quality_urls)
            lines.append(f"▶️ <b>Playback:</b> {'Available' if playback_available else 'Unavailable'}")
            lines.append(f"📥 <b>Download:</b> {'Available' if first_file.direct_url else 'Unavailable'}")
            if first_file.quality_urls and len(first_file.quality_urls) >= 2:
                qualities = ", ".join(first_file.quality_urls.keys())
                lines.append(f"🎚️ <b>Qualities:</b> {escape(qualities)}")
            if first_file.thumbnail:
                lines.append("🖼️ <b>Thumbnail:</b> Available")

            lines.extend(["", "👇 <b>Choose an action</b>"])
        else:
            lines.extend([
                "",
                "ℹ️ <b>No file details were returned.</b>",
                "Please try the link again.",
            ])

        markup = file_keyboard(
            first_direct_url,
            first_stream_url,
            first_file.quality_urls if first_file else None,
            context.user_data.get("last_url"),
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
    if caller_id is not None:
        title_for_analytics, _friendly_for_analytics = classify_resolver_error(reason)
        record_event(
            int(caller_id),
            "processing_failure",
            duration_ms=duration_ms,
            error_category=title_for_analytics.replace("🛡️ ", "").replace("❌ ", "")[:80],
        )

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
    register_user(update.effective_user)

    valid_text, text_or_reason = validate_incoming_text(message.text, MAX_MESSAGE_LENGTH)
    if not valid_text:
        if text_or_reason == "too_long":
            await message.reply_text(
                "⚠️ <b>Message is too long.</b>\n\n"
                f"Please send a message shorter than {MAX_MESSAGE_LENGTH} characters.",
                parse_mode="HTML",
            )
        return

    # Phase 28: admin broadcast draft input. This check must run before normal
    # TeraBox-link handling so the draft is treated as a message, not a URL.
    if context.user_data.get("awaiting_broadcast"):
        actor = update.effective_user
        if actor is None or not is_admin(actor.id):
            context.user_data.pop("awaiting_broadcast", None)
            return
        draft = message.text.strip()
        if not draft:
            await message.reply_text("⚠️ Broadcast message cannot be empty. Please send the message again.")
            return
        if len(draft) > 4096:
            await message.reply_text("⚠️ Broadcast message is too long. Telegram allows up to 4096 characters per message.")
            return
        context.user_data.pop("awaiting_broadcast", None)
        context.user_data["broadcast_draft"] = draft
        await message.reply_text(
            "📢 <b>Broadcast Preview</b>\n\n"
            f"<b>Recipients:</b> {len(get_broadcast_users())} active user(s)\n\n"
            "<b>Message:</b>\n"
            f"<pre>{escape(draft)}</pre>\n\n"
            "Send this message to all active users?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Send Broadcast", callback_data="admin_broadcast_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="admin_broadcast_cancel"),
                ],
                [InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")],
            ]),
        )
        return

    if context.user_data.get("awaiting_admin_user_search"):
        context.user_data.pop("awaiting_admin_user_search", None)
        actor = update.effective_user
        if actor is None or not is_admin(actor.id):
            return
        query = message.text.strip()
        matches = search_users(query, 10)
        if not matches:
            await message.reply_text(
                f"🔎 <b>No user found</b>\n\nSearch: <code>{escape(query)}</code>",
                parse_mode="HTML",
                reply_markup=_admin_dashboard_keyboard(),
            )
            return
        buttons = []
        for item in matches:
            label = f"@{item['username']}" if item.get('username') else (item.get('first_name') or str(item['user_id']))
            buttons.append([InlineKeyboardButton(f"👤 {label} • {item['user_id']}", callback_data=f"admin_user:{item['user_id']}")])
        buttons.append([InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin")])
        await message.reply_text(
            f"🔎 <b>Search Results</b>\n\nQuery: <code>{escape(query)}</code>\nFound: <b>{len(matches)}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # Phase 34: maintenance mode blocks normal processing while keeping admin controls available.
    actor = update.effective_user
    if is_maintenance() and not (actor is not None and is_admin(actor.id)):
        await message.reply_text(
            "🛠️ <b>Bot is temporarily under maintenance.</b>\n\n"
            "Please try again after a short while. Your saved history and profile are safe.",
            parse_mode="HTML",
            reply_markup=welcome_keyboard(),
        )
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

    # Phase 30.1: one Telegram message may contain multiple TeraBox links.
    # Process every unique link instead of silently taking only the first one.
    urls = extract_urls(text_or_reason)

    if urls:
        if len(urls) > MAX_LINKS_PER_MESSAGE:
            await message.reply_text(
                f"⚠️ <b>Too many links in one message.</b>\n\n"
                f"Please send at most {MAX_LINKS_PER_MESSAGE} TeraBox links at a time.",
                parse_mode="HTML",
                reply_markup=welcome_keyboard(),
            )
            return

        context.user_data["rate_limit_user_id"] = update.effective_user.id if update.effective_user else None

        if len(urls) > 1:
            await message.reply_text(
                f"📦 <b>{len(urls)} TeraBox links detected.</b>\n\n"
                "⏳ I will process them one by one. Each link gets its own result.",
                parse_mode="HTML",
            )

        for index, url in enumerate(urls, start=1):
            # Keep the existing single-link processing path untouched.
            # This preserves rate limiting, queue handling, history and analytics.
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
    register_user(update.effective_user)

    if query.data in {"admin","admin_stats","admin_analytics","admin_users","admin_find_user","admin_broadcast","admin_broadcast_confirm","admin_broadcast_cancel","admin_queue","admin_status","admin_maintenance","admin_maintenance_on","admin_maintenance_off","admin_subscriptions"} or (query.data and query.data.startswith("admin_user:")) or (query.data and query.data.startswith("admin_set:")) or (query.data and query.data.startswith("admin_reset:")):
        actor=update.effective_user
        if actor is None or not is_admin(actor.id): return
        if query.data in {"admin","admin_stats"}:
            await query.message.edit_text(_admin_stats_text(),parse_mode="HTML",reply_markup=_admin_dashboard_keyboard()); return
        if query.data == "admin_analytics":
            await query.message.edit_text(_analytics_text(),parse_mode="HTML",reply_markup=_analytics_keyboard()); return
        if query.data == "admin_subscriptions":
            await query.message.edit_text(
                "💳 <b>Subscription Management</b>\n\n"
                "⭐ <b>PRO</b> — 50 videos/day • 30 days\n"
                "💎 <b>UNLIMITED</b> — Unlimited • 30 days\n\n"
                "<b>Activate:</b> <code>/setplan USER_ID pro</code>\n"
                "<code>/setplan USER_ID unlimited</code>\n\n"
                "<b>Manual expire:</b> <code>/expire USER_ID</code>\n\n"
                "The user receives an automatic confirmation with the exact start and expiry time.",
                parse_mode="HTML",
                reply_markup=_admin_dashboard_keyboard(),
            )
            return
        if query.data == "admin_queue":
            await query.message.edit_text(_admin_queue_text(),parse_mode="HTML",reply_markup=_admin_dashboard_keyboard()); return
        if query.data == "admin_status":
            await query.message.edit_text(_admin_status_text(),parse_mode="HTML",reply_markup=_system_control_keyboard()); return
        if query.data == "admin_maintenance":
            await query.message.edit_text(_maintenance_text(),parse_mode="HTML",reply_markup=_system_control_keyboard()); return
        if query.data == "admin_maintenance_on":
            set_maintenance(True)
            await query.message.edit_text(_maintenance_text(),parse_mode="HTML",reply_markup=_system_control_keyboard()); return
        if query.data == "admin_maintenance_off":
            set_maintenance(False)
            await query.message.edit_text(_maintenance_text(),parse_mode="HTML",reply_markup=_system_control_keyboard()); return
        if query.data == "admin_broadcast":
            await _start_broadcast(query.message, context, actor=actor)
            return
        if query.data == "admin_broadcast_confirm":
            await _send_broadcast(query.message, context, actor=actor)
            return
        if query.data == "admin_broadcast_cancel":
            context.user_data.pop("awaiting_broadcast", None)
            context.user_data.pop("broadcast_draft", None)
            await query.message.edit_text(
                "❌ <b>Broadcast Cancelled</b>\n\nNo message was sent.",
                parse_mode="HTML",
                reply_markup=_admin_broadcast_keyboard(),
            )
            return
        if query.data == "admin_users":
            users = get_users(15)
            if not users:
                await query.message.edit_text("👥 <b>Users</b>\n\nNo user statistics are available yet.", parse_mode="HTML", reply_markup=_admin_dashboard_keyboard())
                return
            lines = ["👥 <b>Users</b>", "", "🎬 Lifetime successful-video usage", ""]
            for n, u in enumerate(users, 1):
                identity = f"@{u['username']}" if u.get("username") else (u.get("first_name") or "Unknown")
                lt = "∞" if int(u['limit']) < 0 else str(u['limit'])
                state = "🟢" if int(u.get("is_active", 0)) else "⚪"
                lines.append(f"{n}. {state} <b>{escape(identity)}</b> • <code>{u['user_id']}</code> • 🎬 {u['lifetime_videos']} • 📅 {u['today_videos']} • 🎯 {lt}/day")
            lines += ["", "👇 Tap a user for detailed activity and limit controls."]
            await query.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=_admin_users_keyboard(users))
            return
        if query.data == "admin_find_user":
            await _admin_find_user_prompt(query.message, context)
            return
        if query.data.startswith("admin_user:"):
            try: target=int(query.data.split(":",1)[1])
            except ValueError: await query.answer("Invalid user ID.",show_alert=True); return
            await query.message.edit_text(_admin_user_text(target),parse_mode="HTML",reply_markup=_admin_user_keyboard(target)); return
        if query.data.startswith("admin_set:"):
            try:
                _,uid,lim=query.data.split(":",2); target=int(uid); new=int(lim)
            except ValueError: await query.answer("Invalid limit action.",show_alert=True); return
            if new < -1: await query.answer("Invalid limit.",show_alert=True); return
            set_user_limit(target,new)
            await query.message.edit_text("✅ <b>User limit updated.</b>\n\n"+_admin_user_text(target),parse_mode="HTML",reply_markup=_admin_user_keyboard(target)); return
        if query.data.startswith("admin_reset:"):
            try: target=int(query.data.split(":",1)[1])
            except ValueError: await query.answer("Invalid user ID.",show_alert=True); return
            reset_user_limit(target)
            await query.message.edit_text("↩️ <b>User limit reset to default.</b>\n\n"+_admin_user_text(target),parse_mode="HTML",reply_markup=_admin_user_keyboard(target)); return

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
                        InlineKeyboardButton("📜 History", callback_data="history"),
                    ],
                    [InlineKeyboardButton("🏠 Start", callback_data="start")],
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

    if query.data == "profile":
        user = update.effective_user
        if user is None:
            return
        await query.message.reply_text(
            build_profile_text(user),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📜 History", callback_data="history"),
                    InlineKeyboardButton("🚦 My Limit", callback_data="mylimit"),
                ],
                [InlineKeyboardButton("💳 Subscription", callback_data="subscription")],
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
            ]),
        )
        return

    if query.data == "subscription":
        user = update.effective_user
        if user is None:
            return
        await query.message.edit_text(
            build_subscription_text(user),
            parse_mode="HTML",
            reply_markup=subscription_keyboard(user),
        )
        return

    if query.data == "mylimit":
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        await query.message.reply_text(
            _format_limit_status(get_status(user_id)) +
            "\n\nℹ️ Your quota resets automatically at midnight (India time).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Profile", callback_data="profile")],
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
            ]),
        )
        return

    if query.data == "duplicate_process":
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        url = context.user_data.pop("pending_duplicate_url", None)
        if not url:
            await query.message.reply_text(
                "ℹ️ The duplicate request expired. Please send the link again.",
                reply_markup=welcome_keyboard(),
            )
            return
        context.user_data["rate_limit_user_id"] = user_id
        await process_url(query.message, context, url, skip_duplicate_check=True)
        return

    if query.data == "duplicate_cancel":
        context.user_data.pop("pending_duplicate_url", None)
        await query.message.edit_text(
            "✅ <b>Cancelled.</b>\n\n"
            "No duplicate API request was made.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
                [InlineKeyboardButton("📜 History", callback_data="history")],
            ]),
        )
        return

    if query.data == "history":
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        rows = get_history(user_id)
        if not rows:
            await query.message.edit_text(
                "📜 <b>Your History</b>\n\n"
                "No successfully processed videos are saved yet.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Start", callback_data="start")]
                ]),
            )
            return

        lines = [
            "📜 <b>Recent Video History</b>",
            "",
            "Tap an entry to view its saved link details.",
            "",
        ]
        for index, item in enumerate(rows, start=1):
            names = item.get("file_names") or []
            first_name = names[0] if names else "Processed file"
            name_line = f"{first_name} + {len(names) - 1} more" if len(names) > 1 else first_name
            lines.append(
                f"{index}️⃣ <b>{escape(name_line[:110])}</b>\n"
                f"   🎬 {item['video_count']} video(s) • 🕒 {escape(_format_history_date(item['created_at']))}"
            )
            if index < len(rows):
                lines.append("")
        await query.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_history_keyboard(rows),
        )
        return

    if query.data and query.data.startswith("history_view:"):
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        try:
            history_id = int(query.data.split(":", 1)[1])
        except (TypeError, ValueError):
            await query.answer("Invalid history entry.", show_alert=True)
            return

        item = get_history_item(user_id, history_id)
        if item is None:
            await query.answer("This history entry is no longer available.", show_alert=True)
            return

        names = item.get("file_names") or []
        lines = [
            "📄 <b>History Entry</b>",
            "",
            f"🕒 <b>{escape(_format_history_date(item['created_at']))}</b>",
            f"📦 Files: <b>{item['file_count']}</b>",
            f"🎬 Videos: <b>{item['video_count']}</b>",
            "",
            "📁 <b>Files</b>",
        ]
        for index, name in enumerate(names[:10], start=1):
            lines.append(f"{index}. {escape(str(name))}")
        if len(names) > 10:
            lines.append(f"… and {len(names) - 10} more")
        lines.extend([
            "",
            "🔗 <b>Saved TeraBox link</b>",
            f"<code>{escape(item['share_url'])}</code>",
            "",
            "Reprocessing this entry uses your normal daily video quota.",
        ])
        await query.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Process Again", callback_data=f"history_process:{item['id']}")],
                [InlineKeyboardButton("📜 Back to History", callback_data="history")],
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
            ]),
        )
        return

    if query.data and query.data.startswith("history_process:"):
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        try:
            history_id = int(query.data.split(":", 1)[1])
        except (TypeError, ValueError):
            await query.answer("Invalid history entry.", show_alert=True)
            return

        item = get_history_item(user_id, history_id)
        if item is None:
            await query.answer("This history entry is no longer available.", show_alert=True)
            return

        context.user_data["rate_limit_user_id"] = user_id
        await process_url(query.message, context, item["share_url"], skip_duplicate_check=True)
        return

    if query.data == "history_clear":
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        rows = get_history(user_id)
        if not rows:
            await query.answer("History is already empty.", show_alert=True)
            return
        await query.message.edit_text(
            "🗑️ <b>Clear History?</b>\n\n"
            f"This will remove all <b>{len(rows)}</b> saved history entries.\n"
            "Your TeraBox files and account are not affected.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Clear", callback_data="history_clear_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="history"),
                ]
            ]),
        )
        return

    if query.data == "history_clear_confirm":
        user_id = _user_id_from_update(update)
        if user_id is None:
            return
        deleted = clear_history(user_id)
        await query.message.edit_text(
            "🗑️ <b>History Cleared</b>\n\n"
            f"Removed <b>{deleted}</b> saved entr{'y' if deleted == 1 else 'ies'}.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📜 History", callback_data="history")],
                [InlineKeyboardButton("🏠 Start", callback_data="start")],
            ]),
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
                context.user_data.get("last_url"),
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
                context.user_data.get("last_url"),
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
        await process_url(query.message, context, last_url, password=context.user_data.get("last_password"), skip_duplicate_check=True)


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle expected Telegram API errors quietly and safely."""
    error = context.error
    if isinstance(error, (BadRequest, Forbidden, RetryAfter)):
        return

    import logging
    logging.getLogger(__name__).error(
        "Unhandled Telegram update error: %s",
        error.__class__.__name__ if error else "UnknownError",
    )


def register_handlers(application: Application) -> None:
    application.add_error_handler(telegram_error_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("session", session_command))
    application.add_handler(CommandHandler("mylimit", mylimit_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("subscription", subscription_command))
    application.add_handler(CommandHandler("subscriptions", admin_subscription_command))
    application.add_handler(CommandHandler("setplan", admin_setplan_command))
    application.add_handler(CommandHandler("expire", admin_expire_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("finduser", find_user_command))
    application.add_handler(CommandHandler("limit", admin_limit_command))
    application.add_handler(CommandHandler("setlimit", admin_setlimit_command))
    application.add_handler(CommandHandler("resetlimit", admin_resetlimit_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("analytics", analytics_command))
    application.add_handler(CommandHandler("queue", queue_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("maintenance", maintenance_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("clearhistory", clear_history_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )
