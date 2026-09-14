from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 Help", callback_data="help"),
                InlineKeyboardButton("🌐 Supported", callback_data="supported"),
            ],
            [
                InlineKeyboardButton("📜 History", callback_data="history"),
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
                InlineKeyboardButton("📜 History", callback_data="history"),
                InlineKeyboardButton("🏠 Start", callback_data="start"),
            ],
        ]
    )


def _quality_order(quality_urls: dict[str, str]) -> list[str]:
    preferred = ("1080p", "720p", "480p", "360p")
    return [quality for quality in preferred if quality in quality_urls] + [
        quality for quality in quality_urls if quality not in preferred
    ]


def quality_keyboard(quality_urls: dict[str, str]) -> InlineKeyboardMarkup:
    """Create a quality selector from the PlayTeraBox quality map."""
    rows: list[list[InlineKeyboardButton]] = []
    ordered = _quality_order(quality_urls)

    for quality in ordered:
        url = quality_urls.get(quality)
        if isinstance(url, str) and url.strip():
            rows.append([
                InlineKeyboardButton(f"📺 {quality} • Play", url=url.strip())
            ])

    rows.append([InlineKeyboardButton("⬅️ Back to Video", callback_data="quality_back")])
    return InlineKeyboardMarkup(rows)


def _best_quality(quality_urls: dict[str, str] | None) -> tuple[str | None, str | None]:
    """Return the highest-priority available quality and its URL."""
    if not isinstance(quality_urls, dict):
        return None, None

    for quality in ("1080p", "720p", "480p", "360p"):
        url = quality_urls.get(quality)
        if isinstance(url, str) and url.strip():
            return quality, url.strip()

    for quality, url in quality_urls.items():
        if isinstance(quality, str) and isinstance(url, str) and url.strip():
            return quality, url.strip()

    return None, None


def _play_button(stream_url: str | None, quality_urls: dict[str, str] | None) -> InlineKeyboardButton | None:
    """Prefer the API stream URL; otherwise fall back to the best quality URL."""
    if isinstance(stream_url, str) and stream_url.strip():
        return InlineKeyboardButton("▶️ Play Video", url=stream_url.strip())

    quality, url = _best_quality(quality_urls)
    if url:
        return InlineKeyboardButton(f"▶️ Play {quality}", url=url)

    return None


def file_keyboard(
    direct_url: str | None,
    stream_url: str | None = None,
    quality_urls: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    play_button = _play_button(stream_url, quality_urls)
    if play_button:
        rows.append([play_button])

    if quality_urls and len(quality_urls) >= 2:
        rows.append(
            [InlineKeyboardButton("🎚️ Choose Quality", callback_data="quality")]
        )

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
    quality_urls: dict[str, str] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    play_button = _play_button(stream_url, quality_urls)
    if play_button:
        rows.append([play_button])

    if quality_urls and len(quality_urls) >= 2:
        rows.append(
            [InlineKeyboardButton("🎚️ Choose Quality", callback_data="quality")]
        )

    if direct_url:
        rows.append([InlineKeyboardButton("📥 Download File", url=direct_url)])

    rows.append([InlineKeyboardButton("📂 All Files", callback_data="all_files")])
    rows.append(
        [
            InlineKeyboardButton("🔄 Process Again", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )

    return InlineKeyboardMarkup(rows)
