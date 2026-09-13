import asyncio
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse
import re

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




TERABOX_FALLBACK_API = os.getenv(
    "TERABOX_FALLBACK_API",
    "https://tera-core.vercel.app/api",
).strip()

TERABOX_LEGACY_FALLBACK_API = os.getenv(
    "TERABOX_LEGACY_FALLBACK_API",
    "https://tbx-proxy.shakir-ansarii075.workers.dev/",
).strip()

# Public community fallback. It returns proxied download/stream URLs and supports
# TeraBox mirror domains including terasharefile.com. Keep it behind the primary
# API so the existing production flow remains unchanged.
TERABOX_PUBLIC_WORKER_API = os.getenv(
    "TERABOX_PUBLIC_WORKER_API",
    "https://terabox-worker.robinkumarshakya103.workers.dev/api",
).strip()

TERABOX_MIRROR_DOMAINS = {
    "terabox.com",
    "terabox.app",
    "1024tera.com",
    "1024terabox.com",
    "teraboxshare.com",
    "teraboxlink.com",
    "terasharefile.com",
    "terafileshare.com",
    "terasharelink.com",
}


def _extract_shorturl(url: str) -> str:
    """Extract the TeraBox share code from common /s/... and ?surl=... URLs."""
    try:
        parsed = urlparse(url)
        query_values = parsed.query
        if "surl=" in query_values:
            from urllib.parse import parse_qs
            values = parse_qs(query_values).get("surl") or []
            if values:
                return values[0].strip().strip("/")
        path = parsed.path.rstrip("/")
        match = re.search(r"/s/([^/]+)$", path)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ""


def _shorturl_variants(url: str) -> list[str]:
    code = _extract_shorturl(url)
    if not code:
        return []

    variants = [code]
    if code.startswith("1") and len(code) > 1:
        variants.append(code[1:])

    # Keep order and uniqueness.
    out = []
    seen = set()
    for value in variants:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _mirror_url_variants(url: str) -> list[str]:
    """Try the supplied mirror and a canonical 1024terabox URL for the same share."""
    variants = [url]
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in TERABOX_MIRROR_DOMAINS:
            path = parsed.path or ""
            canonical = f"https://1024terabox.com{path}"
            if canonical not in variants:
                variants.append(canonical)
    except Exception:
        pass
    return variants


def _parse_gateway_files(data) -> list[FileResult]:
    """Parse the documented tera-core gateway response into FileResult objects."""
    if not isinstance(data, dict):
        return []

    containers = []
    if isinstance(data.get("files"), list):
        containers.extend(data["files"])
    if isinstance(data.get("data"), dict):
        nested = data["data"]
        if isinstance(nested.get("files"), list):
            containers.extend(nested["files"])
        if isinstance(nested.get("list"), list):
            containers.extend(nested["list"])
    if isinstance(data.get("list"), list):
        containers.extend(data["list"])
    if isinstance(data.get("results"), list):
        containers.extend(data["results"])

    results = []
    for item in containers:
        if not isinstance(item, dict):
            continue
        parsed = _parse_file({
            **item,
            "name": item.get("name") or item.get("filename") or item.get("server_filename") or item.get("file_name"),
            "download_url": item.get("download_url") or item.get("download_link") or item.get("direct_link") or item.get("dlink") or item.get("link"),
            "size": item.get("size") or item.get("size_formatted") or "",
            "thumbnail": item.get("thumbnail") or item.get("thumb") or "",
            "playable_url": item.get("playable_url") or item.get("stream_url") or item.get("m3u8"),
        })
        if parsed:
            results.append(parsed)
    return results


async def _public_worker_resolve(url: str) -> list[FileResult]:
    """Resolve through a public Cloudflare worker as an additional fallback.

    The worker documents a simple GET /api?url=... contract and returns
    files[] with file_name, download_url, streaming_url and/or
    original_download_url. This is intentionally a fallback only.
    """
    if not TERABOX_PUBLIC_WORKER_API:
        return []

    for share_url in _mirror_url_variants(url):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=8.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                },
            ) as client:
                response = await client.get(
                    TERABOX_PUBLIC_WORKER_API,
                    params={"url": share_url},
                )
                response.raise_for_status()
                data = response.json()

            if not isinstance(data, dict):
                continue

            # Public worker contract: {success: true, files: [...]}
            items = data.get("files")
            if not isinstance(items, list):
                items = []

            results: list[FileResult] = []
            for item in items:
                if not isinstance(item, dict):
                    continue

                normalized = dict(item)
                normalized["name"] = (
                    item.get("file_name")
                    or item.get("filename")
                    or item.get("server_filename")
                    or item.get("name")
                    or "TeraBox file"
                )
                normalized["download_url"] = (
                    item.get("download_url")
                    or item.get("direct_download_url")
                    or item.get("original_download_url")
                    or item.get("download_link")
                    or item.get("dlink")
                )
                normalized["playable_url"] = (
                    item.get("streaming_url")
                    or item.get("stream_url")
                    or item.get("playable_url")
                    or item.get("m3u8")
                )
                normalized["thumbnail"] = (
                    item.get("thumbnail")
                    or item.get("thumb")
                    or item.get("thumbnail_url")
                    or ""
                )
                parsed = _parse_file(normalized)
                if parsed:
                    results.append(parsed)

            if results:
                return results
        except Exception:
            continue

    return []


async def _gateway_resolve(url: str) -> list[FileResult]:
    """Resolve a TeraBox mirror URL through the documented tera-core gateway."""
    if not TERABOX_FALLBACK_API:
        return []

    for share_url in _mirror_url_variants(url):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                response = await client.get(
                    TERABOX_FALLBACK_API,
                    params={"url": share_url, "resolve": "true"},
                )
                response.raise_for_status()
                data = response.json()
            files = _parse_gateway_files(data)
            if files:
                return files

            # Some versions expose the lower-level resolve mode. This request
            # must stay inside the same AsyncClient context.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            ) as client2:
                for surl in _shorturl_variants(share_url):
                    response = await client2.get(
                        TERABOX_FALLBACK_API,
                        params={"mode": "resolve", "surl": surl, "raw": "1"},
                    )
                    if response.is_success:
                        files = _parse_gateway_files(response.json())
                        if files:
                            return files
        except Exception:
            continue

    return []


async def _legacy_fallback_resolve(url: str) -> list[FileResult]:
    """Legacy fallback kept as a second chance for older deployments."""
    if not TERABOX_LEGACY_FALLBACK_API:
        return []

    for surl in _shorturl_variants(url):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=8.0),
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    TERABOX_LEGACY_FALLBACK_API,
                    params={"mode": "resolve", "surl": surl, "refresh": "1"},
                )
                response.raise_for_status()
                data = response.json()

            payload = data.get("data") if isinstance(data, dict) else None
            if isinstance(payload, dict):
                parsed = _parse_file(payload)
                if parsed:
                    return [parsed]
                for key in ("list", "files", "items", "results"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        results = []
                        for item in value:
                            parsed = _parse_file(item)
                            if parsed:
                                results.append(parsed)
                        if results:
                            return results

            parsed = _parse_file(data) if isinstance(data, dict) else None
            if parsed:
                return [parsed]
        except Exception:
            continue

    return []


async def _fallback_resolve(url: str) -> list[FileResult]:
    # Order: public worker -> configured gateway -> legacy worker.
    # The public worker specifically documents support for mirror domains and
    # returns user-facing download/stream URLs.
    files = await _public_worker_resolve(url)
    if files:
        return files

    files = await _gateway_resolve(url)
    if files:
        return files

    return await _legacy_fallback_resolve(url)

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


async def _primary_resolve(url: str, api_key: str) -> tuple[list[FileResult], str]:
    """Resolve through the configured PlayTeraBox API.

    Returns (files, failure_reason). A primary timeout/error is deliberately
    returned as a reason instead of aborting the whole resolver, because the
    mirror/public fallbacks may still be able to resolve the same share.
    """
    if not api_key:
        return [], "TERABOX_API_KEY is not configured."

    try:
        async with _API_SEMAPHORE:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(12.0, connect=5.0),
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                response = await client.get(
                    API_URL,
                    params={"secret": api_key, "url": url},
                )
                response.raise_for_status()
                data = response.json()
    except httpx.TimeoutException:
        return [], "Primary TeraBox API timed out."
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401 or status == 403:
            return [], "Primary TeraBox API rejected the API key."
        if status == 429:
            return [], "Primary TeraBox API rate limit reached."
        return [], f"Primary TeraBox API returned HTTP {status}."
    except Exception as exc:
        return [], f"Primary TeraBox API error: {str(exc)[:160]}"

    if not isinstance(data, dict):
        return [], "Primary TeraBox API returned an invalid response."

    files: list[FileResult] = []
    for raw_file in _normalise_api_files(data):
        parsed = _parse_file(raw_file)
        if parsed:
            files.append(parsed)

    if files:
        return files, ""
    return [], "Primary TeraBox API returned no usable files."


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip()
    except Exception:
        return ""


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
    host = _host(url)

    # IMPORTANT: terasharefile.com and other mirror domains are often slower
    # through the primary PlayTeraBox API. Resolve those through the dedicated
    # public/gateway fallbacks FIRST, instead of waiting for the primary API
    # to time out and telling the user that the link failed.
    mirror_first = host in {
        "terasharefile.com",
        "terasharelink.com",
        "terafileshare.com",
        "teraboxshare.com",
        "teraboxlink.com",
    }

    failure_reasons: list[str] = []

    async def try_fallbacks() -> list[FileResult]:
        try:
            return await asyncio.wait_for(
                _fallback_resolve(url),
                timeout=28.0,
            )
        except asyncio.TimeoutError:
            failure_reasons.append("Fallback resolver timed out.")
            return []
        except Exception as exc:
            failure_reasons.append(f"Fallback resolver error: {str(exc)[:160]}")
            return []

    async def try_primary() -> list[FileResult]:
        files, reason = await _primary_resolve(url, api_key)
        if reason:
            failure_reasons.append(reason)
        return files

    # Mirror links: fallback first. Normal TeraBox links keep the old primary
    # API-first behavior, so existing working links are not unnecessarily
    # changed.
    if mirror_first:
        files = await try_fallbacks()
        if not files:
            files = await try_primary()
    else:
        files = await try_primary()
        if not files:
            files = await try_fallbacks()

    if not files:
        # Keep the reason useful without exposing internal stack traces.
        if failure_reasons:
            reason_text = " • ".join(dict.fromkeys(failure_reasons[-3:]))
        else:
            reason_text = "All configured TeraBox resolvers failed."

        return ResolveResult(
            platform=platform,
            original_url=url,
            title="TeraBox link",
            note=(
                "⚠️ Unable to resolve this share right now. "
                + reason_text
            ),
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
