from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


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
                InlineKeyboardButton("All", callback_data="platform:all"),
                InlineKeyboardButton("✅ TeraBox", callback_data="platform:terabox"),
            ],
            [
                InlineKeyboardButton("DiskWala", callback_data="platform:diskwala"),
                InlineKeyboardButton("Flezen", callback_data="platform:flezen"),
            ],
            [
                InlineKeyboardButton("🏠 Home", callback_data="home"),
            ],
        ]
    )


def result_keyboard(
    playable_url: str | None,
    download_url: str | None = None,
    original_url: str | None = None,
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

    # Safe callback button. It does not send the long API URL to Telegram
    # as a CopyTextButton, so it cannot trigger Button_copy_text_invalid.
    if original_url:
        buttons.append(
            [
                InlineKeyboardButton(
                    "📋  Copy Link",
                    callback_data="copy_hint",
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
