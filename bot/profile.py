"""Per-user profile/dashboard helpers for Phase 26."""

from __future__ import annotations

from html import escape

from telegram import User

from bot.history import get_history
from bot.rate_limiter import get_lifetime_video_count, get_status


def _display_name(user: User) -> str:
    if user.full_name:
        return user.full_name.strip()
    if user.username:
        return f"@{user.username}"
    return "Telegram User"


def build_profile_text(user: User | None) -> str:
    """Build the user's private profile/dashboard text."""
    if user is None:
        return "👤 <b>My Profile</b>\n\nUnable to identify your Telegram account."

    status = get_status(int(user.id))
    history = get_history(int(user.id), limit=10)
    lifetime_videos = get_lifetime_video_count(int(user.id))

    limit = int(status["limit"])
    used_today = int(status["used"])
    remaining = int(status["remaining"])

    limit_text = "♾️ Unlimited" if limit < 0 else f"{limit} video(s)"
    remaining_text = "♾️ Unlimited" if limit < 0 else str(remaining)
    username = f"@{user.username}" if user.username else "Not set"

    return (
        "👤 <b>My Profile</b>\n\n"
        f"🪪 <b>Name:</b> {escape(_display_name(user))}\n"
        f"🔖 <b>Username:</b> {escape(username)}\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
        "📊 <b>Usage Statistics</b>\n"
        f"🎬 <b>Total videos processed:</b> {lifetime_videos}\n"
        f"📜 <b>Saved history entries:</b> {len(history)}\n"
        f"📅 <b>Today's usage:</b> {used_today}\n"
        f"🎯 <b>Daily limit:</b> {limit_text}\n"
        f"🟢 <b>Remaining today:</b> {remaining_text}\n\n"
        "💡 Your daily video quota resets automatically at midnight (India time)."
    )
