import asyncio
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs
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

TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "").strip()
TERABOX_NDUS = os.getenv("TERABOX_NDUS", "").strip()
TERABOX_NATIVE_HOSTS = (
    "https://www.terabox.app",
    "https://www.terabox.com",
    "https://1024terabox.com",
    "https://www.1024tera.com",
)


def _extract_js_token(html: str) -> str:
    patterns = (
        r'window\.jsToken[^\n]{0,300}?%22([^%]+?)%22',
        r'window\.jsToken[^\n]{0,300}?[\"\']([^\"\']+)[\"\']',
        r'fn%28%22([^%]+)%22%29',
        r'jsToken[\"\']\s*[:=]\s*[\"\']([^\"\']+)[\"\']',
    )
    for pattern in patterns:
        m = re.search(pattern, html, re.I | re.S)
        if m and m.group(1):
            return m.group(1).strip()
    return ""


def _extract_dp_logid(html: str) -> str:
    patterns = (
        r'dp-logid=([^&\"\']+)',
        r'"dplogid"\s*:\s*"?([^,\"}]+)',
        r'"dp_logid"\s*:\s*"?([^,\"}]+)',
    )
    for pattern in patterns:
        m = re.search(pattern, html, re.I | re.S)
        if m and m.group(1):
            return m.group(1).strip()
    return ""


def _extract_surl_from_final_url(final_url: str) -> str:
    try:
        parsed = urlparse(final_url)
        qs = parse_qs(parsed.query)
        for key in ("surl", "shorturl"):
            if qs.get(key):
                return qs[key][0].strip()
        match = re.search(r"/s/([^/?#]+)", parsed.path)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ""


def _cookie_dict() -> dict[str, str]:
    cookies = {}
    if TERABOX_COOKIE:
        for piece in TERABOX_COOKIE.split(";"):
            if "=" in piece:
                k, v = piece.split("=", 1)
                k = k.strip()
                if k:
                    cookies[k] = v.strip()
    if TERABOX_NDUS:
        cookies.setdefault("ndus", TERABOX_NDUS)
    return cookies


async def _native_share_resolve(url: str) -> tuple[list[FileResult], str]:
    """Resolve a public TeraBox share directly from its share page + share/list API."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
            "Chrome/121.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Referer": url,
    }
    cookies = _cookie_dict()
    last_error = "native share resolver returned no files"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=6.0),
        follow_redirects=True,
        headers=headers,
        cookies=cookies or None,
    ) as client:
        try:
            page = await client.get(url)
            page.raise_for_status()
            final_url = str(page.url)
            html = page.text
            surl = _extract_surl_from_final_url(final_url) or (_shorturl_variants(url) or [""])[0]
            js_token = _extract_js_token(html)
            dp_logid = _extract_dp_logid(html)
            if not surl:
                return [], "native resolver could not extract share code"
            if not js_token:
                return [], "native resolver could not extract jsToken"

            # A leading 1 is commonly part of the share-path format, not the API shorturl.
            surls = [surl]
            if surl.startswith("1") and len(surl) > 1:
                surls.append(surl[1:])

            for host in TERABOX_NATIVE_HOSTS:
                for shorturl in surls:
                    params = {
                        "app_id": "250528",
                        "web": "1",
                        "channel": "0",
                        "jsToken": js_token,
                        "page": "1",
                        "num": "20",
                        "by": "name",
                        "order": "asc",
                        "site_referer": "",
                        "shorturl": shorturl,
                        "root": "1",
                    }
                    if dp_logid:
                        params["dp-logid"] = dp_logid
                    try:
                        response = await client.get(f"{host}/share/list", params=params)
                        if response.status_code != 200:
                            last_error = f"native share/list HTTP {response.status_code}"
                            continue
                        data = response.json()
                        errno = data.get("errno") if isinstance(data, dict) else None
                        if str(errno) not in ("0", "None"):
                            last_error = str(data.get("errmsg") or f"share/list errno {errno}")
                            continue
                        rows = data.get("list") if isinstance(data, dict) else None
                        if not isinstance(rows, list):
                            last_error = "native share/list returned no list"
                            continue
                        results=[]
                        for item in rows:
                            if not isinstance(item, dict) or str(item.get("isdir", "0")) == "1":
                                continue
                            # Direct dlink can be used by Telegram/browser; for reliability follow one HEAD redirect.
                            dlink = _valid_url(item.get("dlink"))
                            direct = dlink
                            if dlink:
                                try:
                                    head = await client.head(dlink, follow_redirects=False, timeout=8.0)
                                    direct = _valid_url(head.headers.get("location")) or dlink
                                except Exception:
                                    pass
                            filename = item.get("server_filename") or item.get("filename") or "TeraBox file"
                            is_video = str(filename).lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m3u8"))
                            parsed = _parse_file({
                                "server_filename": filename,
                                "size": item.get("size"),
                                "dlink": direct,
                                "streaming_url": direct if is_video else None,
                                "thumb": (item.get("thumbs") or {}).get("url3") if isinstance(item.get("thumbs"), dict) else item.get("thumb"),
                            })
                            if parsed:
                                results.append(parsed)
                        if results:
                            return results, ""
                    except Exception as exc:
                        last_error = f"native share/list failed: {type(exc).__name__}"
                        continue
        except httpx.TimeoutException:
            return [], "native share page timed out"
        except httpx.HTTPStatusError as exc:
            return [], f"native share page HTTP {exc.response.status_code}"
        except Exception as exc:
            return [], f"native share page failed: {type(exc).__name__}"

    return [], last_error


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
    api = os.getenv(
        "TERABOX_PUBLIC_WORKER_API",
        "https://terabox-worker.robinkumarshakya103.workers.dev/api",
    ).strip()
    if not api:
        return []
    for share_url in _mirror_url_variants(url):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True) as client:
                response = await client.get(api, params={"url": share_url})
                if response.status_code >= 400:
                    continue
                data = response.json()
            if not isinstance(data, dict):
                continue
            rows = data.get("files")
            if not isinstance(rows, list):
                continue
            out=[]
            for item in rows:
                if not isinstance(item, dict):
                    continue
                parsed = _parse_file({
                    "file_name": item.get("file_name") or item.get("filename") or item.get("server_filename") or item.get("name"),
                    "size": item.get("size") or "",
                    "download_url": item.get("download_url") or item.get("original_download_url"),
                    "streaming_url": item.get("streaming_url") or item.get("stream_url") or item.get("playable_url"),
                    "thumbnail": item.get("thumbnail") or item.get("thumb") or "",
                })
                if parsed:
                    out.append(parsed)
            if out:
                return out
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

            # Some versions expose the lower-level resolve mode.
            for surl in _shorturl_variants(share_url):
                response = await client.get(
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


async def _fallback_resolve(url: str) -> tuple[list[FileResult], list[str]]:
    errors = []
    native_files, native_error = await _native_share_resolve(url)
    if native_files:
        return native_files, errors
    if native_error:
        errors.append(native_error)

    files = await _public_worker_resolve(url)
    if files:
        return files, errors
    errors.append("public worker returned no files")

    files = await _gateway_resolve(url)
    if files:
        return files, errors
    errors.append("gateway returned no files")

    files = await _legacy_fallback_resolve(url)
    if files:
        return files, errors
    errors.append("legacy gateway returned no files")
    return [], errors

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
    if platform != "terabox":
        result = ResolveResult(
            platform=platform,
            original_url=url,
            title="User submitted link",
            playable_url=url,
            note="No resolver configured for this platform yet.",
        )
        result.files = [FileResult(title=result.title, playable_url=url)]
        return result

    # terasharefile/other mirrors are better handled by the native share flow first.
    host = (urlparse(url).hostname or "").lower()
    mirror_first = host in {"terasharefile.com", "terafileshare.com", "terasharelink.com"}
    fallback_errors: list[str] = []

    if mirror_first:
        native_files, native_error = await _native_share_resolve(url)
        if native_files:
            files = native_files
            first = files[0]
            return ResolveResult(
                platform=platform, original_url=url, title=first.title,
                playable_url=first.playable_url, download_url=first.download_url,
                size_formatted=first.size_formatted, duration=first.duration,
                quality=first.quality, thumbnail=first.thumbnail,
                quality_urls=first.quality_urls.copy(), files=files,
                note="TeraBox link resolved successfully via native share flow.",
            )
        if native_error:
            fallback_errors.append(native_error)

    api_key = os.getenv("TERABOX_API_KEY", "").strip()
    if api_key:
        try:
            async with _API_SEMAPHORE:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(12.0, connect=6.0),
                    follow_redirects=True,
                ) as client:
                    response = await client.get(API_URL, params={"secret": api_key, "url": url})
                    response.raise_for_status()
                    data = response.json()

            if isinstance(data, dict):
                files = []
                for raw_file in _normalise_api_files(data):
                    parsed = _parse_file(raw_file)
                    if parsed:
                        files.append(parsed)
                if files:
                    first = files[0]
                    return ResolveResult(
                        platform=platform, original_url=url, title=first.title,
                        playable_url=first.playable_url, download_url=first.download_url,
                        size_formatted=first.size_formatted, duration=first.duration,
                        quality=first.quality, thumbnail=first.thumbnail,
                        quality_urls=first.quality_urls.copy(), files=files,
                        note="TeraBox link resolved successfully.",
                    )
                fallback_errors.append("primary API returned no usable files")
            else:
                fallback_errors.append("primary API returned invalid JSON")
        except httpx.TimeoutException:
            fallback_errors.append("primary TeraBox API timed out")
        except httpx.HTTPStatusError as exc:
            fallback_errors.append(f"primary API HTTP {exc.response.status_code}")
        except Exception as exc:
            fallback_errors.append(f"primary API failed: {type(exc).__name__}")
    else:
        fallback_errors.append("TERABOX_API_KEY is not configured")

    # Always continue after primary failure/timeouts instead of returning early.
    fallback_files, fallback_notes = await _fallback_resolve(url)
    if fallback_files:
        first = fallback_files[0]
        return ResolveResult(
            platform=platform, original_url=url, title=first.title,
            playable_url=first.playable_url, download_url=first.download_url,
            size_formatted=first.size_formatted, duration=first.duration,
            quality=first.quality, thumbnail=first.thumbnail,
            quality_urls=first.quality_urls.copy(), files=fallback_files,
            note="TeraBox link resolved successfully via fallback resolver.",
        )

    detail = "; ".join((fallback_errors + fallback_notes)[:4])
    return ResolveResult(
        platform=platform,
        original_url=url,
        title="TeraBox link",
        note=(
            "Unable to resolve this TeraBox share right now. "
            + (f"Resolver details: {detail}." if detail else "All configured resolvers returned no usable file.")
        ),
    )
