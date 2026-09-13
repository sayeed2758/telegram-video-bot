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


def _extract_urls(file_data: dict) -> tuple[str | None, str | None, dict[str, str]]:
    """Extract playable/download URLs and all supported stream qualities."""
    playable_url = _valid_url(file_data.get("stream_url"))
    quality_urls: dict[str, str] = {}

    fast_stream = file_data.get("fast_stream_url")
    if isinstance(fast_stream, dict):
        for quality, candidate in fast_stream.items():
            candidate_url = _valid_url(candidate)
            if candidate_url:
                quality_name = str(quality).strip()
                if quality_name:
                    quality_urls[quality_name] = candidate_url

    if not playable_url:
        for quality in ("1080p", "720p", "480p", "360p"):
            candidate = quality_urls.get(quality)
            if candidate:
                playable_url = candidate
                break

    download_url = _valid_url(file_data.get("fast_download_link"))
    if not download_url:
        download_url = _valid_url(file_data.get("download_link"))

    # Some document responses use different field names. Accept only valid
    # absolute HTTP/HTTPS URLs so PDFs can be delivered too.
    if not download_url:
        for key in (
            "direct_download_url", "direct_url", "download",
            "file_url", "url", "link", "dlink",
        ):
            candidate = _valid_url(file_data.get(key))
            if candidate:
                download_url = candidate
                break

    return playable_url, download_url, quality_urls


def _parse_file(file_data: dict) -> FileResult | None:
    if not isinstance(file_data, dict):
        return None

    title = file_data.get("name")
    if not isinstance(title, str) or not title.strip():
        title = "TeraBox file"

    playable_url, download_url, quality_urls = _extract_urls(file_data)

    size_formatted = str(file_data.get("size_formatted") or "")
    duration = str(file_data.get("duration") or "")

    quality = file_data.get("quality") or ""
    if isinstance(quality, (list, dict)):
        quality = ""
    quality = str(quality)

    thumbnail = _valid_url(file_data.get("thumbnail")) or ""

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
                timeout=httpx.Timeout(30.0, connect=10.0),
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

    raw_files = data.get("list")
    if not isinstance(raw_files, list) or not raw_files:
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
