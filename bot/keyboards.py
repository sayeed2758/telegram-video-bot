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

    if stream_url:
        rows.append([InlineKeyboardButton("▶️ Play Video", url=stream_url)])

    if direct_url:
        rows.append([InlineKeyboardButton("📥 Download File", url=direct_url)])

    rows.append(
        [
            InlineKeyboardButton("🔄 Process Again", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def _short_button_name(name: str, limit: int = 34) -> str:
    clean = " ".join(str(name).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def file_list_keyboard(files_count: int) -> InlineKeyboardMarkup:
    """Create a compact selector for a resolved multi-file share."""
    rows: list[list[InlineKeyboardButton]] = []

    # Buttons use only the numeric index in callback_data so long file names
    # never exceed Telegram's callback-data size limit.
    for index in range(files_count):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index + 1}️⃣ Select File {index + 1}",
                    callback_data=f"select_file:{index}",
                )
            ]
        )

    rows.append([InlineKeyboardButton("🏠 Start", callback_data="start")])
    return InlineKeyboardMarkup(rows)


def file_list_keyboard_compact(file_names: list[str]) -> InlineKeyboardMarkup:
    """Create a compact file selector using each file's display name."""
    rows: list[list[InlineKeyboardButton]] = []

    for index, name in enumerate(file_names):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index + 1}️⃣ {_short_button_name(name)}",
                    callback_data=f"select_file:{index}",
                )
            ]
        )

    rows.append([InlineKeyboardButton("🏠 Start", callback_data="start")])
    return InlineKeyboardMarkup(rows)


def selected_file_keyboard(
    direct_url: str | None,
    stream_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if stream_url:
        rows.append([InlineKeyboardButton("▶️ Play Video", url=stream_url)])

    if direct_url:
        rows.append([InlineKeyboardButton("📥 Download File", url=direct_url)])

    rows.append(
        [InlineKeyboardButton("📂 All Files", callback_data="all_files")]
    )
    rows.append(
        [
            InlineKeyboardButton("🔄 Process Again", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )

    return InlineKeyboardMarkup(rows)
