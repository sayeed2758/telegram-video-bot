from telegram import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def home_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 Select Platform")],
            [KeyboardButton("ℹ️ Help")],
        ],
        resize_keyboard=True,
    )


def platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "All",
                    callback_data="platform:all",
                ),
                InlineKeyboardButton(
                    "✅ TeraBox",
                    callback_data="platform:terabox",
                ),
            ],
            [
                InlineKeyboardButton(
                    "DiskWala",
                    callback_data="platform:diskwala",
                ),
                InlineKeyboardButton(
                    "Flezen",
                    callback_data="platform:flezen",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home",
                )
            ],
        ]
    )


def result_keyboard(
    playable_url: str | None,
    download_url: str | None = None,
    original_url: str | None = None,
    quality_options: tuple[str, ...] = (),
) -> InlineKeyboardMarkup:
    buttons = []

    if playable_url:
        buttons.append(
            [
                InlineKeyboardButton(
                    "▶️  Play Online",
                    url=playable_url,
                )
            ]
        )

    if download_url:
        buttons.append(
            [
                InlineKeyboardButton(
                    "⬇️  Download",
                    url=download_url,
                )
            ]
        )

    if quality_options:
        buttons.append(
            [
                InlineKeyboardButton(
                    "🎞  Change Quality",
                    callback_data="quality:menu",
                )
            ]
        )

    # Copy the original TeraBox share link only.
    if original_url and len(original_url) <= 256:
        buttons.append(
            [
                InlineKeyboardButton(
                    "📋  Copy Link",
                    copy_text=CopyTextButton(text=original_url),
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🎯  Select Platform",
                callback_data="select_platform",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


def quality_keyboard(qualities: tuple[str, ...]) -> InlineKeyboardMarkup:
    """Build a compact quality selector with callback-only buttons."""
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
            InlineKeyboardButton(
                "↩️ Back",
                callback_data="quality:back",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)
