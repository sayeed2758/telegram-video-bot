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
    note: str = ""


API_URL = "https://api.playterabox.com/api/proxy"


def _valid_url(value) -> str | None:
    """Return a valid HTTP/HTTPS URL as a string."""
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


def _extract_playable_url(file_data: dict) -> str | None:
    """Safely extract a playable/download URL from the API response."""

    # 1. Direct stream URL
    stream_url = _valid_url(file_data.get("stream_url"))

    if stream_url:
        return stream_url

    # 2. Fast stream URLs
    fast_stream = file_data.get("fast_stream_url")

    if isinstance(fast_stream, dict):
        # Prefer HD first
        for quality in ("720p", "480p", "360p"):
            stream = _valid_url(fast_stream.get(quality))

            if stream:
                return stream

    # 3. Fast download URL
    fast_download = _valid_url(
        file_data.get("fast_download_link")
    )

    if fast_download:
        return fast_download

    # 4. Normal download URL
    download_url = _valid_url(
        file_data.get("download_link")
    )

    if download_url:
        return download_url

    return None


async def resolve_link(
    url: str,
    platform: str
) -> ResolveResult:

    # Keep other platforms working exactly as before.
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
            playable_url=None,
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
            playable_url=None,
            note="TeraBox API request timed out.",
        )

    except httpx.HTTPStatusError as exc:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note=f"TeraBox API returned HTTP {exc.response.status_code}.",
        )

    except Exception:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note="Unable to connect to the TeraBox API.",
        )

    # Make sure the API returned an object.
    if not isinstance(data, dict):
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note="Invalid API response.",
        )

    files = data.get("list")

    if not isinstance(files, list) or not files:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note="No file was returned by the API.",
        )

    # Use the first file returned by the API.
    file_data = files[0]

    if not isinstance(file_data, dict):
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note="Invalid file data returned by the API.",
        )

    title = file_data.get("name")

    if not isinstance(title, str) or not title.strip():
        title = "TeraBox file"

    playable_url = _extract_playable_url(file_data)

    if not playable_url:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title=title,
            playable_url=None,
            note="The API did not return a valid playable URL.",
        )

    return ResolveResult(
        platform=platform,
        original_url=url,
        title=title,
        playable_url=playable_url,
        note="TeraBox link resolved successfully.",
    )
