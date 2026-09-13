import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass
class ResolveResult:
    platform: str
    original_url: str

    title: str = ""
    playable_url: str | None = None
    download_url: str | None = None

    size_formatted: str = ""
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""

    note: str = ""


API_URL = "https://api.playterabox.com/api/proxy"


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


def _extract_urls(file_data: dict) -> tuple[str | None, str | None]:
    """Extract safe playable and download URLs."""

    playable_url = None
    download_url = None

    # Preferred streaming URL
    playable_url = _valid_url(
        file_data.get("stream_url")
    )

    # Quality-based streaming fallback
    if not playable_url:
        fast_stream = file_data.get("fast_stream_url")

        if isinstance(fast_stream, dict):
            for quality in ("720p", "480p", "360p"):
                candidate = _valid_url(
                    fast_stream.get(quality)
                )

                if candidate:
                    playable_url = candidate
                    break

    # Download URL
    download_url = _valid_url(
        file_data.get("fast_download_link")
    )

    if not download_url:
        download_url = _valid_url(
            file_data.get("download_link")
        )

    return playable_url, download_url


async def resolve_link(
    url: str,
    platform: str
) -> ResolveResult:

    # Keep other platforms working.
    if platform != "terabox":
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="User submitted link",
            playable_url=url,
            note="No resolver configured for this platform yet.",
        )

    api_key = os.getenv("TERABOX_API_KEY", "").strip()

    if not api_key:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="TERABOX_API_KEY is not configured.",
        )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                30.0,
                connect=10.0
            ),
            follow_redirects=True,
        ) as client:

            response = await client.get(
                API_URL,
                params={
                    "secret": api_key,
                    "url": url,
                },
            )

            response.raise_for_status()
            data = response.json()

    except httpx.TimeoutException:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="TeraBox API request timed out.",
        )

    except httpx.HTTPStatusError as exc:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note=(
                "TeraBox API returned "
                f"HTTP {exc.response.status_code}."
            ),
        )

    except Exception:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="Unable to connect to the TeraBox API.",
        )

    if not isinstance(data, dict):
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="Invalid API response.",
        )

    files = data.get("list")

    if not isinstance(files, list) or not files:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="No file was returned by the API.",
        )

    file_data = files[0]

    if not isinstance(file_data, dict):
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note="Invalid file data returned by the API.",
        )

    title = file_data.get("name")

    if not isinstance(title, str) or not title.strip():
        title = "TeraBox file"

    playable_url, download_url = _extract_urls(
        file_data
    )

    size_formatted = file_data.get("size_formatted") or ""

    duration = file_data.get("duration")

    if duration is None:
        duration = ""

    duration = str(duration)

    quality = file_data.get("quality") or ""

    if isinstance(quality, (list, dict)):
        quality = ""

    quality = str(quality)

    thumbnail = _valid_url(
        file_data.get("thumbnail")
    ) or ""

    if not playable_url and not download_url:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title=title,
            size_formatted=str(size_formatted),
            duration=duration,
            quality=quality,
            thumbnail=thumbnail,
            note="No valid playable/download URL was returned.",
        )

    return ResolveResult(
        platform=platform,
        original_url=url,
        title=title,
        playable_url=playable_url,
        download_url=download_url,
        size_formatted=str(size_formatted),
        duration=duration,
        quality=quality,
        thumbnail=thumbnail,
        note="TeraBox link resolved successfully.",
    )
