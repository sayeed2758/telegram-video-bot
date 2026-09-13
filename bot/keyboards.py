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
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]
    )


def result_keyboard(original_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶️ Open / Play Link", url=original_url)],
            [InlineKeyboardButton("🔗 Copy Link", callback_data="copy_hint")],
            [InlineKeyboardButton("🎯 Select Platform", callback_data="select_platform")],
        ]
    )
