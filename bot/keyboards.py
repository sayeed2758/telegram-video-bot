from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 Help", callback_data="help"),
                InlineKeyboardButton("🌐 Supported", callback_data="supported"),
            ],
            [
                InlineKeyboardButton("🔄 Retry", callback_data="retry"),
            ],
        ]
    )


def error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Retry", callback_data="retry"),
                InlineKeyboardButton("📖 Help", callback_data="help"),
            ],
            [
                InlineKeyboardButton("🏠 Start", callback_data="start"),
            ],
        ]
    )


def file_keyboard(
    direct_url: str | None,
    stream_url: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # Phase 16: cleaner, action-first result UI.
    if stream_url:
        rows.append(
            [InlineKeyboardButton("▶️ Play Video", url=stream_url)]
        )

    if direct_url:
        rows.append(
            [InlineKeyboardButton("📥 Download", url=direct_url)]
        )

    rows.append(
        [
            InlineKeyboardButton("🔄 Process Again", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )

    return InlineKeyboardMarkup(rows)
