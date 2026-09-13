import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.playterabox.com/api/proxy"
PUBLIC_WORKER_API = os.getenv(
    "TERABOX_PUBLIC_WORKER_API",
    "https://terabox-worker.robinkumarshakya103.workers.dev/api",
).strip()
GATEWAY_API = os.getenv(
    "TERABOX_GATEWAY_API",
    "https://terabox-gateway-production.up.railway.app/api",
).strip()

REQUEST_TIMEOUT = float(os.getenv("TERABOX_RESOLVER_TIMEOUT", "12"))
PAGE_TIMEOUT = float(os.getenv("TERABOX_PAGE_TIMEOUT", "10"))


@dataclass
class FileResult:
    title: str = "TeraBox file"
    playable_url: str | None = None
    download_url: str | None = None
    size_formatted: str = ""
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""
    quality_urls: dict[str, str] = field(default_factory=dict)


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
    quality_urls: dict[str, str] = field(default_factory=dict)
    files: list[FileResult] = field(default_factory=list)
    note: str = ""


def _valid_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        p = urlparse(value)
        if p.scheme in ("http", "https") and p.netloc:
            return value
    except Exception:
        pass
    return None


def _first_url(data: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            # Some APIs JSON-encode a URL.
            try:
                decoded = json.loads(value) if value.startswith('"') else value
            except Exception:
                decoded = value
            url = _valid_url(decoded)
            if url:
                return url
    return None


def _file_title(data: dict) -> str:
    for key in ("name", "filename", "file_name", "server_filename", "title"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "TeraBox file"


def _format_size(value) -> str:
    if value in (None, "", 0, "0"):
        return ""
    try:
        size = float(value)
        units = ("B", "KB", "MB", "GB", "TB")
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.1f} {units[index]}" if index else f"{int(size)} B"
    except (TypeError, ValueError):
        return str(value)


def _extract_urls(data: dict) -> tuple[str | None, str | None, dict[str, str]]:
    quality_urls: dict[str, str] = {}

    for key in ("quality_urls", "stream_urls", "streams"):
        value = data.get(key)
        if isinstance(value, dict):
            for quality, candidate in value.items():
                candidate = _valid_url(candidate)
                if candidate:
                    quality_urls[str(quality)] = candidate

    for quality in ("1080p", "720p", "480p", "360p", "M3U8_AUTO_1080", "M3U8_AUTO_720"):
        candidate = _valid_url(data.get(quality))
        if candidate:
            quality_urls.setdefault(quality, candidate)

    playable = _first_url(
        data, ("stream_url", "streaming_url", "playable_url", "play_url", "m3u8")
    )
    if not playable and quality_urls:
        playable = next(iter(quality_urls.values()))

    download = _first_url(
        data,
        (
            "download_url", "direct_download_url", "original_download_url",
            "download_link", "fast_download_link", "direct_link", "dlink",
            "file_url", "url", "link",
        ),
    )
    return playable, download, quality_urls


def _parse_file(data: dict) -> FileResult | None:
    if not isinstance(data, dict):
        return None
    playable, download, qualities = _extract_urls(data)
    if not playable and not download:
        return None

    quality = data.get("quality") or ""
    if isinstance(quality, (dict, list)):
        quality = ""

    thumbnail = (
        _valid_url(data.get("thumbnail"))
        or _valid_url(data.get("thumbnail_url"))
        or _valid_url(data.get("thumb"))
        or ""
    )
    size = data.get("size_formatted") or _format_size(data.get("size") or data.get("sizebytes"))

    # A direct dlink is a valid action URL even if it is not an HLS stream.
    if not playable:
        playable = download

    return FileResult(
        title=_file_title(data),
        playable_url=playable,
        download_url=download,
        size_formatted=str(size or ""),
        duration=str(data.get("duration") or ""),
        quality=str(quality),
        thumbnail=thumbnail,
        quality_urls=qualities,
    )


def _normalise_files(data) -> list[dict]:
    if not isinstance(data, dict):
        return []

    candidates = []

    def add(value):
        if isinstance(value, list):
            candidates.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            # Single file object.
            if any(k in value for k in (
                "name", "filename", "file_name", "server_filename",
                "dlink", "download_url", "download_link", "direct_link"
            )):
                candidates.append(value)
            for key in ("list", "files", "items", "results", "contents"):
                if isinstance(value.get(key), list):
                    candidates.extend(x for x in value[key] if isinstance(x, dict))

    for key in ("list", "files", "items", "results", "contents", "data", "result"):
        add(data.get(key))

    for parent_key in ("data", "result"):
        parent = data.get(parent_key)
        if isinstance(parent, dict):
            for key in ("file", "item"):
                add(parent.get(key))

    unique, seen = [], set()
    for item in candidates:
        marker = (
            _file_title(item),
            str(item.get("dlink") or item.get("download_url") or item.get("direct_link") or ""),
        )
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def _extract_shorturl(url: str) -> str:
    try:
        p = urlparse(url)
        query = parse_qs(p.query)
        for key in ("surl", "shorturl"):
            if query.get(key):
                return unquote(query[key][0]).strip()
        match = re.search(r"/s/([^/?#]+)", p.path)
        if match:
            return unquote(match.group(1)).strip()
    except Exception:
        pass
    return ""


def _shorturl_variants(url: str) -> list[str]:
    code = _extract_shorturl(url)
    if not code:
        return []
    values = [code]
    if code.startswith("1") and len(code) > 8:
        values.append(code[1:])
    return list(dict.fromkeys(values))


def _mirror_urls(url: str) -> list[str]:
    code = _extract_shorturl(url)
    if not code:
        return [url]
    variants = _shorturl_variants(url)
    hosts = [
        "terasharefile.com", "1024terabox.com", "terabox.com",
        "terabox.app", "teraboxshare.com", "teraboxlink.com",
        "terafileshare.com", "terasharelink.com",
    ]
    result = [url]
    for host in hosts:
        for code_variant in variants:
            result.append(f"https://{host}/s/{code_variant}")
    return list(dict.fromkeys(result))


def _browser_headers(referer: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _extract_js_token(html: str) -> str:
    patterns = [
        r'window\.jsToken\s*=\s*["\']([^"\']+)["\']',
        r'"jsToken"\s*:\s*"([^"]+)"',
        r'jsToken%22%3A%22([^"%]+)',
        r'fn%28%22([^%]+)%22%29',
        r'jsToken\s*[:=]\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return unquote(match.group(1))
    return ""


def _extract_log_id(html: str) -> str:
    for pattern in (
        r'dp-logid=([^&"\']+)',
        r'"dp-logid"\s*:\s*"([^"]+)"',
        r'dplogid["\']?\s*[:=]\s*["\']([^"\']+)',
    ):
        match = re.search(pattern, html, re.I)
        if match:
            return unquote(match.group(1))
    return ""


async def _native_share_resolve(url: str) -> tuple[list[FileResult], str]:
    """Resolve a public share using the share page + share/list flow.

    This is deliberately limited to public share metadata. It does not attempt
    passwords, private shares, captcha solving, or account access.
    """
    shorturls = _shorturl_variants(url)
    if not shorturls:
        return [], "Invalid TeraBox share format."

    headers = _browser_headers()
    timeout = httpx.Timeout(PAGE_TIMEOUT, connect=5.0)

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=headers
    ) as client:
        last_error = ""
        for share_url in _mirror_urls(url)[:12]:
            try:
                response = await client.get(share_url)
                response.raise_for_status()

                final_url = str(response.url)
                html = response.text
                token = _extract_js_token(html)
                log_id = _extract_log_id(html)

                resolved_shorturls = []
                final_surl = _extract_shorturl(final_url)
                if final_surl:
                    resolved_shorturls.append(final_surl)
                resolved_shorturls.extend(shorturls)

                if not token:
                    last_error = "Share page did not expose a jsToken."
                    continue

                # The same API is served on the major TeraBox mirror hosts.
                api_hosts = []
                final_host = (urlparse(final_url).hostname or "").lower()
                if final_host.startswith("www."):
                    final_host = final_host[4:]
                if final_host:
                    api_hosts.append(final_host)
                api_hosts.extend(["terabox.app", "1024tera.com", "terabox.com"])
                api_hosts = list(dict.fromkeys(api_hosts))

                for api_host in api_hosts:
                    for surl in list(dict.fromkeys(resolved_shorturls)):
                        params = {
                            "app_id": "250528",
                            "web": "1",
                            "channel": "0",
                            "jsToken": token,
                            "page": "1",
                            "num": "100",
                            "by": "name",
                            "order": "asc",
                            "site_referer": "",
                            "shorturl": surl,
                            "root": "1",
                        }
                        if log_id:
                            params["dp-logid"] = log_id

                        api_url = f"https://www.{api_host}/share/list"
                        try:
                            api_response = await client.get(
                                api_url,
                                params=params,
                                headers=_browser_headers(final_url),
                            )
                            if api_response.status_code != 200:
                                last_error = f"share/list HTTP {api_response.status_code}"
                                continue

                            data = api_response.json()
                            errno = data.get("errno", 0) if isinstance(data, dict) else -1
                            if str(errno) not in ("0",):
                                message = data.get("errmsg") if isinstance(data, dict) else ""
                                last_error = str(message or f"share/list errno {errno}")
                                continue

                            raw_files = data.get("list", []) if isinstance(data, dict) else []
                            files = []
                            for raw in raw_files:
                                parsed = _parse_file(raw)
                                if parsed:
                                    files.append(parsed)
                            if files:
                                logger.info(
                                    "Native TeraBox resolver succeeded: host=%s files=%s",
                                    api_host, len(files),
                                )
                                return files, ""

                        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
                            last_error = type(exc).__name__
                            continue
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last_error = type(exc).__name__
                continue

    return [], last_error or "Public share could not be resolved."


async def _api_resolve(url: str, api_key: str) -> tuple[list[FileResult], str]:
    if not api_key:
        return [], "TERABOX_API_KEY is not configured."

    try:
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(API_URL, params={"secret": api_key, "url": url})
            response.raise_for_status()
            data = response.json()

        files = []
        for raw in _normalise_files(data):
            parsed = _parse_file(raw)
            if parsed:
                files.append(parsed)
        if files:
            return files, ""

        return [], "Primary API returned no usable files."
    except httpx.TimeoutException:
        return [], "Primary API timed out."
    except httpx.HTTPStatusError as exc:
        return [], f"Primary API returned HTTP {exc.response.status_code}."
    except (httpx.HTTPError, ValueError) as exc:
        return [], f"Primary API error: {type(exc).__name__}."


async def _worker_resolve(url: str) -> tuple[list[FileResult], str]:
    if not PUBLIC_WORKER_API:
        return [], "Public worker is disabled."

    for candidate in _mirror_urls(url)[:8]:
        try:
            timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(PUBLIC_WORKER_API, params={"url": candidate})
                if response.status_code != 200:
                    continue
                data = response.json()
            files = [_parse_file(x) for x in _normalise_files(data)]
            files = [x for x in files if x]
            if files:
                return files, ""
        except (httpx.TimeoutException, httpx.HTTPError, ValueError, json.JSONDecodeError):
            continue
    return [], "Public worker did not return usable files."


async def _gateway_resolve(url: str) -> tuple[list[FileResult], str]:
    if not GATEWAY_API:
        return [], "Gateway is disabled."

    for candidate in _mirror_urls(url)[:8]:
        try:
            timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(
                    GATEWAY_API,
                    params={"url": candidate, "resolve": "true"},
                )
                if response.status_code != 200:
                    continue
                data = response.json()
            files = [_parse_file(x) for x in _normalise_files(data)]
            files = [x for x in files if x]
            if files:
                return files, ""
        except (httpx.TimeoutException, httpx.HTTPError, ValueError, json.JSONDecodeError):
            continue
    return [], "Gateway did not return usable files."


def _success(platform: str, original_url: str, files: list[FileResult]) -> ResolveResult:
    first = files[0]
    return ResolveResult(
        platform=platform,
        original_url=original_url,
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


async def resolve_link(url: str, platform: str) -> ResolveResult:
    if platform != "terabox":
        result = ResolveResult(
            platform=platform,
            original_url=url,
            title="User submitted link",
            playable_url=url,
            note="No dedicated resolver is configured for this platform yet.",
        )
        result.files = [FileResult(title=result.title, playable_url=url)]
        return result

    # Public share resolver is first because it does not depend on the user's
    # API key and is the most direct path for public TeraBox shares.
    attempts = []

    try:
        files, error = await _native_share_resolve(url)
        if files:
            return _success(platform, url, files)
        attempts.append(error)
    except Exception as exc:
        logger.exception("Native TeraBox resolver failed")
        attempts.append(type(exc).__name__)

    api_key = os.getenv("TERABOX_API_KEY", "").strip()
    files, error = await _api_resolve(url, api_key)
    if files:
        return _success(platform, url, files)
    attempts.append(error)

    files, error = await _worker_resolve(url)
    if files:
        return _success(platform, url, files)
    attempts.append(error)

    files, error = await _gateway_resolve(url)
    if files:
        return _success(platform, url, files)
    attempts.append(error)

    # Keep the user-facing error short, but make the Render logs useful.
    clean = []
    for item in attempts:
        if item and item not in clean:
            clean.append(item)
    logger.warning("TeraBox resolution failed: %s", " | ".join(clean))

    primary = next((x for x in clean if x and "Primary API" in x), "")
    if primary:
        note = primary + " Native/public fallback resolvers also returned no usable files."
    else:
        note = clean[0] if clean else "No resolver returned usable files."

    return ResolveResult(
        platform=platform,
        original_url=url,
        title="TeraBox link",
        note=note,
    )
