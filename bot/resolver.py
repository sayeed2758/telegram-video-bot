import os
from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass
class ResolveResult:
    platform: str
    original_url: str
    title: str = ""
    playable_url: str | None = None
    note: str = ""


API_URL = "https://api.playterabox.com/api/proxy"


async def resolve_link(url: str, platform: str) -> ResolveResult:
    """
    Resolve public/authorized TeraBox links through the configured
    TeraBox API service.

    The API key is read only from the server environment.
    It is never exposed to Telegram users.
    """

    # Keep other platforms working with the existing behavior.
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
            timeout=httpx.Timeout(30.0, connect=10.0),
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

    except Exception as exc:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note=f"API request failed: {type(exc).__name__}",
        )

    files = data.get("list") or []

    if not isinstance(files, list) or not files:
        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            playable_url=None,
            note="No files were returned by the API.",
        )

    # Use the first returned file.
    file_data = files[0] or {}

    title = (
        file_data.get("name")
        or file_data.get("title")
        or "TeraBox file"
    )

    # Prefer streaming URLs, then download URLs.
    playable_url = (
        file_data.get("stream_url")
        or (
            file_data.get("fast_stream_url", {}).get("720p")
            if isinstance(file_data.get("fast_stream_url"), dict)
            else None
        )
        or file_data.get("fast_download_link")
        or file_data.get("download_link")
    )

    return ResolveResult(
        platform=platform,
        original_url=url,
        title=title,
        playable_url=playable_url,
        note="Resolved through TeraBox API.",
    )
