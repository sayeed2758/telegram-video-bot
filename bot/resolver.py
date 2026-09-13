import asyncio
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx


@dataclass
class FileResult:
    """One file returned by the TeraBox API."""

    title: str = "TeraBox file"
    playable_url: str | None = None
    download_url: str | None = None

    size_formatted: str = ""
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""

    # Available quality -> stream URL mapping.
    quality_urls: dict[str, str] = field(default_factory=dict)


@dataclass
class ResolveResult:
    platform: str
    original_url: str

    # Backward-compatible first-file fields.
    title: str = ""
    playable_url: str | None = None
    download_url: str | None = None
    size_formatted: str = ""
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""
    quality_urls: dict[str, str] = field(default_factory=dict)

    # Phase 4C: all files returned by the API.
    files: list[FileResult] = field(default_factory=list)

    note: str = ""


API_URL = "https://api.playterabox.com/api/proxy"
API_CONCURRENCY = int(os.getenv("TERABOX_API_CONCURRENCY", "4"))
_API_SEMAPHORE = asyncio.Semaphore(max(1, API_CONCURRENCY))


def _valid_url(value) -> str | None:
    """Return a valid HTTP/HTTPS URL."""
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = urlparse(value)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return value
    except Exception:
        pass

    return None


def _first_url(data: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        candidate = _valid_url(data.get(key))
        if candidate:
            return candidate
    return None


def _extract_urls(file_data: dict) -> tuple[str | None, str | None, dict[str, str]]:
    """Extract stream/download URLs from multiple TeraBox API response shapes."""
    playable_url = _first_url(
        file_data,
        ("stream_url", "streaming_url", "playable_url", "play_url", "m3u8"),
    )
    quality_urls: dict[str, str] = {}

    for field in ("fast_stream_url", "stream_urls", "quality_urls", "streams"):
        value = file_data.get(field)
        if isinstance(value, dict):
            for quality, candidate in value.items():
                candidate_url = _valid_url(candidate)
                if candidate_url:
                    quality_name = str(quality).strip()
                    if quality_name:
                        quality_urls[quality_name] = candidate_url

    if not playable_url:
        for quality in ("1080p", "720p", "480p", "360p", "auto"):
            candidate = quality_urls.get(quality)
            if candidate:
                playable_url = candidate
                break

    download_url = _first_url(
        file_data,
        (
            "fast_download_link", "download_link", "download_url",
            "direct_download_url", "direct_url", "original_download_url",
            "dlink", "download", "file_url", "url", "link",
        ),
    )

    return playable_url, download_url, quality_urls


def _file_title(file_data: dict) -> str:
    for key in ("name", "filename", "file_name", "server_filename", "title"):
        value = file_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "TeraBox file"


def _normalise_api_files(data: dict) -> list[dict]:
    """Accept common API wrappers: list/files/data/result."""
    candidates = []

    def add(value):
        if isinstance(value, list):
            candidates.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            # Single-file response.
            if any(k in value for k in ("name", "filename", "file_name", "server_filename", "dlink", "download_url", "download_link")):
                candidates.append(value)
            for key in ("list", "files", "items", "results"):
                if isinstance(value.get(key), list):
                    candidates.extend(x for x in value[key] if isinstance(x, dict))

    add(data.get("list"))
    add(data.get("files"))
    add(data.get("items"))
    add(data.get("results"))
    add(data.get("data"))
    add(data.get("result"))

    # Some APIs return the actual file object inside data.result/file.
    for parent_key in ("data", "result"):
        parent = data.get(parent_key)
        if isinstance(parent, dict):
            for key in ("file", "item"):
                add(parent.get(key))

    # De-duplicate by title + URL while preserving order.
    unique = []
    seen = set()
    for item in candidates:
        marker = (_file_title(item), str(item.get("dlink") or item.get("download_url") or item.get("download_link") or ""))
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def _parse_file(file_data: dict) -> FileResult | None:
    if not isinstance(file_data, dict):
        return None

    title = _file_title(file_data)
    playable_url, download_url, quality_urls = _extract_urls(file_data)

    size_value = file_data.get("size_formatted") or file_data.get("size") or ""
    size_formatted = str(size_value)
    duration = str(file_data.get("duration") or "")

    quality = file_data.get("quality") or ""
    if isinstance(quality, (list, dict)):
        quality = ""
    quality = str(quality)

    thumbnail = (
        _valid_url(file_data.get("thumbnail"))
        or _valid_url(file_data.get("thumb"))
        or _valid_url(file_data.get("thumbnail_url"))
        or ""
    )

    if not playable_url and not download_url:
        return None

    if not playable_url and quality and quality in quality_urls:
        playable_url = quality_urls[quality]

    return FileResult(
        title=title,
        playable_url=playable_url,
        download_url=download_url,
        size_formatted=size_formatted,
        duration=duration,
        quality=quality,
        thumbnail=thumbnail,
        quality_urls=quality_urls,
    )


async def resolve_link(url: str, platform: str) -> ResolveResult:
    # Preserve the existing placeholder behavior for other platforms.
    if platform != "terabox":
        result = ResolveResult(
            platform=platform,
            original_url=url,
            title="User submitted link",
            playable_url=url,
            note="No resolver configured for this platform yet.",
        )
        result.files = [
            FileResult(title=result.title, playable_url=url)
        ]
        return result

    api_key = os.getenv("TERABOX_API_KEY", "").strip()

    if not api_key:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="TERABOX_API_KEY is not configured.",
        )

    try:
        async with _API_SEMAPHORE:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=8.0),
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    API_URL,
                    params={"secret": api_key, "url": url},
                )
                response.raise_for_status()
                data = response.json()

    except httpx.TimeoutException:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="⏱️ TeraBox API took too long to respond. Please try again.",
        )

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401 or status == 403:
            note = "🔐 TeraBox API authentication was rejected. Check the API key."
        elif status == 429:
            note = "🚦 TeraBox API rate limit reached. Please wait and try again."
        elif 500 <= status <= 599:
            note = "🛠️ TeraBox service is temporarily unavailable. Please try again later."
        else:
            note = f"⚠️ TeraBox API returned HTTP {status}."
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note=note,
        )

    except Exception:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="⚠️ Unable to connect to the TeraBox service right now.",
        )

    if not isinstance(data, dict):
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="Invalid API response.",
        )

    raw_files = _normalise_api_files(data)
    if not raw_files:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="No file was returned by the API.",
        )

    files: list[FileResult] = []
    for raw_file in raw_files:
        parsed = _parse_file(raw_file)
        if parsed:
            files.append(parsed)

    if not files:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="No playable/downloadable file was returned by the API.",
        )

    first = files[0]

    return ResolveResult(
        platform=platform,
        original_url=url,
        title=first.title,
        playable_url=first.playable_url,
        download_url=first.download_url,
        size_formatted=first.size_formatted,
        duration=first.duration,
        quality=first.quality,
        thumbnail=first.thumbnail,
        quality_urls=first.quality_urls.copy(),
        files=files,
        note="TeraBox link resolved successfully.",
    )
