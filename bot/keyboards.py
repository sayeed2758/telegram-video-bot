from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, User

from bot.config import PLAYER_BASE_URL
from bot.subscription import build_purchase_url


def welcome_keyboard() -> InlineKeyboardMarkup:
    """Clean home navigation; retry is kept for actual results/errors only."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 Help", callback_data="help"),
                InlineKeyboardButton("🌐 Supported", callback_data="supported"),
            ],
            [
                InlineKeyboardButton("📜 History", callback_data="history"),
                InlineKeyboardButton("👤 Profile", callback_data="profile"),
            ],
            [
                InlineKeyboardButton("🔐 Session Status", callback_data="session"),
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
                InlineKeyboardButton("👤 Profile", callback_data="profile"),
            ],
            [InlineKeyboardButton("🏠 Start", callback_data="start")],
        ]
    )


def _quality_order(quality_urls: dict[str, str]) -> list[str]:
    preferred = ("1080p", "720p", "480p", "360p")
    return [quality for quality in preferred if quality in quality_urls] + [
        quality for quality in quality_urls if quality not in preferred
    ]


def _player_url(stream_url: str, *, title: str | None = None, quality: str | None = None, poster: str | None = None) -> str:
    """Wrap a resolved stream in the optional premium browser player."""
    if not PLAYER_BASE_URL:
        return stream_url

    params = [f"src={quote(stream_url, safe='')}"]
    if title:
        params.append(f"title={quote(title, safe='')}")
    if quality:
        params.append(f"quality={quote(quality, safe='')}")
    if poster:
        params.append(f"poster={quote(poster, safe='')}")
    return PLAYER_BASE_URL + "?" + "&".join(params)


def quality_keyboard(quality_urls: dict[str, str], title: str | None = None, poster: str | None = None) -> InlineKeyboardMarkup:
    """Create a quality selector using the optional premium player."""
    rows: list[list[InlineKeyboardButton]] = []
    ordered = _quality_order(quality_urls)

    for quality in ordered:
        url = quality_urls.get(quality)
        if isinstance(url, str) and url.strip():
            rows.append([
                InlineKeyboardButton(
                    f"📺 {quality} • Play",
                    url=_player_url(url.strip(), title=title, quality=quality, poster=poster),
                )
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


def _play_button(
    stream_url: str | None,
    quality_urls: dict[str, str] | None,
    *,
    title: str | None = None,
    poster: str | None = None,
) -> InlineKeyboardButton | None:
    """Prefer the API stream URL; otherwise fall back to the best quality URL."""
    if isinstance(stream_url, str) and stream_url.strip():
        return InlineKeyboardButton(
            "🎬 Open Premium Player" if PLAYER_BASE_URL else "▶️ Play Video",
            url=_player_url(stream_url.strip(), title=title, poster=poster),
        )

    quality, url = _best_quality(quality_urls)
    if url:
        return InlineKeyboardButton(
            f"🎬 Open {quality} Player" if PLAYER_BASE_URL else f"▶️ Play {quality}",
            url=_player_url(url, title=title, quality=quality, poster=poster),
        )

    return None


def file_keyboard(
    direct_url: str | None,
    stream_url: str | None = None,
    quality_urls: dict[str, str] | None = None,
    original_url: str | None = None,
    title: str | None = None,
    poster: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    play_button = _play_button(stream_url, quality_urls, title=title, poster=poster)
    if play_button:
        rows.append([play_button])

    if quality_urls and len(quality_urls) >= 2:
        rows.append(
            [InlineKeyboardButton("🎚️ Choose Quality", callback_data="quality")]
        )

    if direct_url:
        rows.append([InlineKeyboardButton("📥 Download File", url=direct_url)])

    if isinstance(original_url, str) and original_url.strip():
        rows.append([InlineKeyboardButton("🔗 Original Link", url=original_url.strip())])

    rows.append(
        [
            InlineKeyboardButton("🔄 Refresh Link", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("📜 History", callback_data="history"),
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
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
    rows.append(
        [
            InlineKeyboardButton("📜 History", callback_data="history"),
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
        ]
    )
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
    original_url: str | None = None,
    title: str | None = None,
    poster: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    play_button = _play_button(stream_url, quality_urls, title=title, poster=poster)
    if play_button:
        rows.append([play_button])

    if quality_urls and len(quality_urls) >= 2:
        rows.append(
            [InlineKeyboardButton("🎚️ Choose Quality", callback_data="quality")]
        )

    if direct_url:
        rows.append([InlineKeyboardButton("📥 Download File", url=direct_url)])

    if isinstance(original_url, str) and original_url.strip():
        rows.append([InlineKeyboardButton("🔗 Original Link", url=original_url.strip())])

    rows.append([InlineKeyboardButton("📂 All Files", callback_data="all_files")])
    rows.append(
        [
            InlineKeyboardButton("🔄 Refresh Link", callback_data="retry"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("📜 History", callback_data="history"),
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
        ]
    )

    return InlineKeyboardMarkup(rows)


def subscription_keyboard(user: User | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Purchase PRO • 50/day", url=build_purchase_url(user, "pro"))],
        [InlineKeyboardButton("💎 Purchase UNLIMITED", url=build_purchase_url(user, "unlimited"))],
        [
            InlineKeyboardButton("👤 Profile", callback_data="profile"),
            InlineKeyboardButton("🏠 Start", callback_data="start"),
        ],
    ])
