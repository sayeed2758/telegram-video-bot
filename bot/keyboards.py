from telegram import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def home_keyboard() -> ReplyKeyboardMarkup:
    """Main persistent navigation keyboard."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 Select Platform")],
            [KeyboardButton("🕘 My History"), KeyboardButton("ℹ️ Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✨ All", callback_data="platform:all"),
                InlineKeyboardButton("✅ TeraBox", callback_data="platform:terabox"),
            ],
            [
                InlineKeyboardButton("DiskWala", callback_data="platform:diskwala"),
                InlineKeyboardButton("Flezen", callback_data="platform:flezen"),
            ],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]
    )


def result_keyboard(
    playable_url: str | None,
    download_url: str | None = None,
    original_url: str | None = None,
    quality_options: tuple[str, ...] = (),
) -> InlineKeyboardMarkup:
    """Premium two-column result actions while keeping existing callback contracts."""
    rows = []

    primary = []
    if playable_url:
        primary.append(InlineKeyboardButton("▶️ Play Online", url=playable_url))
    if download_url:
        primary.append(InlineKeyboardButton("⬇️ Download", url=download_url))
    if primary:
        rows.append(primary)

    secondary = []
    if quality_options:
        secondary.append(
            InlineKeyboardButton("🎞 Change Quality", callback_data="quality:menu")
        )

    if original_url and len(original_url) <= 256:
        secondary.append(
            InlineKeyboardButton(
                "📋 Copy Link",
                copy_text=CopyTextButton(text=original_url),
            )
        )

    if secondary:
        rows.append(secondary)

    rows.append(
        [
            InlineKeyboardButton("🎯 Select Platform", callback_data="select_platform"),
            InlineKeyboardButton("🏠 Home", callback_data="home"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def quality_keyboard(qualities: tuple[str, ...]) -> InlineKeyboardMarkup:
    preferred = ("1080p", "720p", "480p", "360p")
    ordered = [q for q in preferred if q in qualities]
    ordered += [q for q in qualities if q not in ordered]

    rows = []
    current_row = []

    for quality in ordered:
        current_row.append(
            InlineKeyboardButton(
                f"🎞 {quality}",
                callback_data=f"quality:{quality}",
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.append(
        [
            InlineKeyboardButton("↩️ Back to Result", callback_data="quality:back"),
            InlineKeyboardButton("🏠 Home", callback_data="home"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def file_selection_keyboard(
    files: tuple,
    max_files: int = 25,
) -> InlineKeyboardMarkup:
    """Compact callback-only menu for multi-file shares."""
    rows = []

    for index, file_result in enumerate(files[:max_files]):
        name = str(getattr(file_result, "title", "TeraBox file") or "TeraBox file")
        if len(name) > 36:
            name = name[:33] + "..."

        rows.append(
            [
                InlineKeyboardButton(
                    f"{index + 1}. {name}",
                    callback_data=f"file:{index}",
                )
            ]
        )

    if len(files) > max_files:
        rows.append(
            [
                InlineKeyboardButton(
                    f"ℹ️ Showing first {max_files} files",
                    callback_data="noop",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton("↩️ Back", callback_data="files:back"),
            InlineKeyboardButton("🏠 Home", callback_data="home"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Dashboard", callback_data="admin:stats"),
                InlineKeyboardButton("👥 Users", callback_data="admin:users"),
            ],
            [
                InlineKeyboardButton("🧾 Recent Requests", callback_data="admin:requests"),
                InlineKeyboardButton("🔄 Refresh", callback_data="admin:refresh"),
            ],
            [InlineKeyboardButton("❌ Close", callback_data="admin:close")],
        ]
    )


def history_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 Clear History", callback_data="history:clear")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]
    )


def history_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, Clear", callback_data="history:confirm_clear"),
                InlineKeyboardButton("❌ Cancel", callback_data="history:cancel_clear"),
            ]
        ]
    )
