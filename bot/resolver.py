import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx


@dataclass
class FileResult:
    """One file returned by a TeraBox resolver."""

    title: str = "TeraBox file"
    playable_url: str | None = None
    download_url: str | None = None
    size_formatted: str = ""
    duration: str = ""
    quality: str = ""
    thumbnail: str = ""
    quality_urls: dict[str, str] = field(default_factory=dict)
    # Smart Download Center compatibility.
    file_type: str = "video"


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


TERABOX_FALLBACK_API = os.getenv(
    "TERABOX_FALLBACK_API",
    "https://tera-core.vercel.app/api",
).strip()

TERABOX_LEGACY_FALLBACK_API = os.getenv(
    "TERABOX_LEGACY_FALLBACK_API",
    "https://tbx-proxy.shakir-ansarii075.workers.dev/",
).strip()

# Optional authenticated cookie. Public shares are attempted first without it.
TERABOX_NDUS = os.getenv("TERABOX_NDUS", "").strip()

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

TERABOX_NATIVE_HOSTS = (
    "https://www.terabox.com",
    "https://www.1024tera.com",
    "https://www.1024terabox.com",
    "https://www.terabox.app",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)



def _valid_url(value) -> str | None:
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
    playable_url = _first_url(
        file_data,
        (
            "stream_url",
            "streaming_url",
            "playable_url",
            "play_url",
            "m3u8",
            "direct_link",
        ),
    )
    quality_urls: dict[str, str] = {}

    for field_name in ("fast_stream_url", "stream_urls", "quality_urls", "streams"):
        value = file_data.get(field_name)
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
            "fast_download_link",
            "download_link",
            "download_url",
            "direct_download_url",
            "direct_url",
            "original_download_url",
            "dlink",
            "download",
            "file_url",
            "url",
            "link",
            "direct_link",
        ),
    )

    return playable_url, download_url, quality_urls



def _file_title(file_data: dict) -> str:
    for key in (
        "name",
        "filename",
        "file_name",
        "server_filename",
        "title",
    ):
        value = file_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "TeraBox file"



def _guess_file_type(title: str, file_data: dict | None = None) -> str:
    data = file_data or {}
    raw_type = str(data.get("file_type") or data.get("mime_type") or "").lower()
    name = title.lower()

    if "pdf" in raw_type or name.endswith(".pdf"):
        return "document"
    if raw_type.startswith("audio/") or name.endswith((".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg")):
        return "audio"
    if raw_type.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
        return "image"
    return "video"



def _parse_file(file_data: dict) -> FileResult | None:
    if not isinstance(file_data, dict):
        return None

    title = _file_title(file_data)
    playable_url, download_url, quality_urls = _extract_urls(file_data)

    size_value = file_data.get("size_formatted") or file_data.get("size") or ""
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

    # Native TeraBox share/list responses expose dlink. It is usable as a
    # direct/download candidate even when there is no separate stream URL.
    if not playable_url and download_url and str(download_url).startswith(("http://", "https://")):
        playable_url = download_url

    return FileResult(
        title=title,
        playable_url=playable_url,
        download_url=download_url,
        size_formatted=str(size_value),
        duration=duration,
        quality=quality,
        thumbnail=thumbnail,
        quality_urls=quality_urls,
        file_type=_guess_file_type(title, file_data),
    )



def _normalise_api_files(data: dict) -> list[dict]:
    """Accept common wrappers: list/files/data/result/file/items/results."""
    candidates: list[dict] = []

    def add(value):
        if isinstance(value, list):
            candidates.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            if any(
                k in value
                for k in (
                    "name",
                    "filename",
                    "file_name",
                    "server_filename",
                    "dlink",
                    "download_url",
                    "download_link",
                    "direct_link",
                )
            ):
                candidates.append(value)
            for key in ("list", "files", "items", "results"):
                if isinstance(value.get(key), list):
                    candidates.extend(x for x in value[key] if isinstance(x, dict))
            for key in ("file", "item"):
                if isinstance(value.get(key), dict):
                    add(value[key])

    if isinstance(data, dict):
        for key in ("list", "files", "items", "results", "data", "result"):
            add(data.get(key))

    unique: list[dict] = []
    seen = set()
    for item in candidates:
        marker = (
            _file_title(item),
            str(
                item.get("dlink")
                or item.get("download_url")
                or item.get("download_link")
                or item.get("direct_link")
                or ""
            ),
        )
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique



def _extract_shorturl(url: str) -> str:
    """Extract surl from /s/<key> or ?surl=<key>."""
    try:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get("surl") or parse_qs(parsed.query).get("shorturl") or []
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
    # Many /s/ links are rendered as 1<shorturl>, while share/list expects the
    # key without the leading 1. Trying both avoids an unnecessary false failure.
    if code.startswith("1") and len(code) > 1:
        variants.append(code[1:])

    out: list[str] = []
    seen = set()
    for value in variants:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out



def _mirror_url_variants(url: str) -> list[str]:
    variants = [url]
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in TERABOX_MIRROR_DOMAINS:
            path = parsed.path or ""
            canonical_hosts = (
                "https://www.1024terabox.com",
                "https://www.terabox.com",
                "https://www.terabox.app",
            )
            for base in canonical_hosts:
                candidate = f"{base}{path}"
                if candidate not in variants:
                    variants.append(candidate)
    except Exception:
        pass
    return variants



def _headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
    if TERABOX_NDUS:
        headers["Cookie"] = f"ndus={TERABOX_NDUS}"
    return headers



def _decode_token(value: str) -> str:
    return unquote(unescape(value)).strip().strip('"\'')



def _extract_token(text: str, names: tuple[str, ...]) -> str:
    if not text:
        return ""
    patterns = []
    for name in names:
        patterns.extend(
            [
                rf'"{re.escape(name)}"\s*:\s*"([^"]+)"',
                rf"'{re.escape(name)}'\s*:\s*'([^']+)'",
                rf"{re.escape(name)}\s*[:=]\s*['\"]([^'\"]+)['\"]",
            ]
        )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _decode_token(match.group(1))
    return ""



def _extract_js_token(text: str) -> str:
    patterns = (
        r"fn%28%22([^%]+)%22%29",
        r"fn\(%22([^%]+)%22%29",
        r'jsToken\\?"\\?\s*:\s*"([^"]+)"',
        r"jsToken\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"window\.jsToken\s*=\s*['\"]([^'\"]+)['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _decode_token(match.group(1))
    return ""



def _extract_dp_logid(text: str, final_url: str) -> str:
    for source in (final_url, text):
        match = re.search(r"dp-logid[=:\\]+([0-9]+)", source, re.I)
        if match:
            return match.group(1)
    return ""



def _response_file_list(data) -> list[FileResult]:
    if not isinstance(data, dict):
        return []

    # Direct TeraBox API shape: { errno: 0, list: [...] }
    items = data.get("list")
    if isinstance(items, list):
        output = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Preserve TeraBox metadata such as thumbs.url3.
            thumbs = item.get("thumbs")
            thumbnail = ""
            if isinstance(thumbs, dict):
                thumbnail = thumbs.get("url3") or thumbs.get("url2") or thumbs.get("url1") or ""
            normalized = {
                **item,
                "name": item.get("server_filename") or item.get("filename") or item.get("name"),
                "download_url": item.get("dlink") or item.get("download_url") or item.get("download_link"),
                "thumbnail": item.get("thumb") or item.get("thumbnail") or thumbnail,
                "size": item.get("size") or item.get("size_formatted") or "",
                "file_type": item.get("mime_type") or item.get("category") or item.get("file_type") or "",
            }
            parsed = _parse_file(normalized)
            if parsed:
                output.append(parsed)
        if output:
            return output

    results: list[FileResult] = []
    for raw in _normalise_api_files(data):
        parsed = _parse_file(raw)
        if parsed:
            results.append(parsed)
    return results


async def _native_share_resolve(url: str) -> tuple[list[FileResult], str]:
    """Resolve using TeraBox's own share page + share/list flow.

    This is the important recovery path for mirror domains such as
    terasharefile.com when third-party JSON APIs return an empty list.
    """
    last_reason = ""
    timeout = httpx.Timeout(25.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_headers()) as client:
        for share_url in _mirror_url_variants(url):
            try:
                page = await client.get(share_url, headers=_headers(share_url))
                page.raise_for_status()
                final_url = str(page.url)
                html = page.text or ""

                shorturls = _shorturl_variants(final_url) or _shorturl_variants(share_url)
                if not shorturls:
                    last_reason = "Could not extract TeraBox short URL from share page."
                    continue

                js_token = _extract_js_token(html)
                dp_logid = _extract_dp_logid(html, final_url)

                # If the page did not expose jsToken in a direct pattern, try
                # encoded/escaped variants once more.
                if not js_token:
                    js_token = _extract_token(html, ("jsToken", "jstoken", "js_token"))

                parsed_final = urlparse(final_url)
                base = f"{parsed_final.scheme}://{parsed_final.netloc}" if parsed_final.netloc else "https://www.terabox.com"
                list_endpoints = [
                    f"{base}/share/list",
                    "https://www.1024tera.com/share/list",
                    "https://www.terabox.com/share/list",
                    "https://www.terabox.app/share/list",
                ]

                # Keep only unique endpoints.
                seen_endpoints = []
                for endpoint in list_endpoints:
                    if endpoint not in seen_endpoints:
                        seen_endpoints.append(endpoint)

                for shorturl in shorturls:
                    for endpoint in seen_endpoints:
                        params = {
                            "app_id": "250528",
                            "web": "1",
                            "channel": "0",
                            "clienttype": "5",
                            "page": "1",
                            "num": "1000",
                            "by": "name",
                            "order": "asc",
                            "site_referer": "",
                            "shorturl": shorturl,
                            "root": "1",
                        }
                        if js_token:
                            params["jsToken"] = js_token
                        if dp_logid:
                            params["dp-logid"] = dp_logid

                        response = await client.get(
                            endpoint,
                            params=params,
                            headers=_headers(final_url),
                        )
                        if not response.is_success:
                            last_reason = f"share/list HTTP {response.status_code}"
                            continue

                        try:
                            data = response.json()
                        except Exception:
                            last_reason = "TeraBox share/list returned non-JSON data."
                            continue

                        errno = data.get("errno") if isinstance(data, dict) else None
                        if errno not in (None, 0, "0"):
                            errmsg = str(data.get("errmsg") or data.get("message") or "")
                            last_reason = f"TeraBox share/list errno {errno}: {errmsg}".strip()
                            continue

                        files = _response_file_list(data)
                        if files:
                            return files, ""

                        last_reason = "TeraBox share/list returned no usable files."
            except httpx.TimeoutException:
                last_reason = "Native TeraBox share resolution timed out."
            except httpx.HTTPStatusError as exc:
                last_reason = f"Native TeraBox share page HTTP {exc.response.status_code}."
            except Exception as exc:
                last_reason = f"Native TeraBox resolver error: {exc.__class__.__name__}."

    return [], last_reason



def _parse_gateway_files(data) -> list[FileResult]:
    if not isinstance(data, dict):
        return []

    containers = []
    for key in ("files", "list", "results"):
        if isinstance(data.get(key), list):
            containers.extend(data[key])
    for parent_key in ("data", "result"):
        nested = data.get(parent_key)
        if isinstance(nested, dict):
            for key in ("files", "list", "results"):
                if isinstance(nested.get(key), list):
                    containers.extend(nested[key])

    results = []
    for item in containers:
        if not isinstance(item, dict):
            continue
        parsed = _parse_file(item)
        if parsed:
            results.append(parsed)
    return results


async def _gateway_resolve(url: str) -> list[FileResult]:
    if not TERABOX_FALLBACK_API:
        return []

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_headers()) as client:
        for share_url in _mirror_url_variants(url):
            try:
                response = await client.get(
                    TERABOX_FALLBACK_API,
                    params={"url": share_url, "resolve": "true"},
                    headers=_headers(share_url),
                )
                if response.is_success:
                    try:
                        files = _parse_gateway_files(response.json())
                    except Exception:
                        files = []
                    if files:
                        return files

                for surl in _shorturl_variants(share_url):
                    response = await client.get(
                        TERABOX_FALLBACK_API,
                        params={"mode": "resolve", "surl": surl},
                        headers=_headers(share_url),
                    )
                    if response.is_success:
                        try:
                            files = _parse_gateway_files(response.json())
                        except Exception:
                            files = []
                        if files:
                            return files
            except Exception:
                continue
    return []


async def _legacy_fallback_resolve(url: str) -> list[FileResult]:
    if not TERABOX_LEGACY_FALLBACK_API:
        return []

    timeout = httpx.Timeout(25.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_headers()) as client:
        for surl in _shorturl_variants(url):
            try:
                response = await client.get(
                    TERABOX_LEGACY_FALLBACK_API,
                    params={"mode": "resolve", "surl": surl, "refresh": "1"},
                    headers=_headers(url),
                )
                if not response.is_success:
                    continue
                data = response.json()
                files = _response_file_list(data)
                if files:
                    return files
            except Exception:
                continue
    return []


async def _fallback_resolve(url: str) -> tuple[list[FileResult], str]:
    # 1) Native share/list flow. This is the key fix for mirror-domain shares.
    native_files, native_reason = await _native_share_resolve(url)
    if native_files:
        return native_files, ""

    # 2) Public gateway.
    files = await _gateway_resolve(url)
    if files:
        return files, ""

    # 3) Legacy gateway.
    files = await _legacy_fallback_resolve(url)
    if files:
        return files, ""

    return [], native_reason


API_URL = "https://api.playterabox.com/api/proxy"
API_CONCURRENCY = int(os.getenv("TERABOX_API_CONCURRENCY", "4"))
_API_SEMAPHORE = asyncio.Semaphore(max(1, API_CONCURRENCY))


async def resolve_link(url: str, platform: str) -> ResolveResult:
    # Preserve existing placeholder behavior for other platforms.
    if platform != "terabox":
        result = ResolveResult(
            platform=platform,
            original_url=url,
            title="User submitted link",
            playable_url=url,
            note="No resolver configured for this platform yet.",
        )
        result.files = [FileResult(title=result.title, playable_url=url, file_type="video")]
        return result

    api_key = os.getenv("TERABOX_API_KEY", "").strip()

    # First try the existing configured PlayTeraBox endpoint when a key exists.
    if api_key:
        try:
            async with _API_SEMAPHORE:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=8.0),
                    follow_redirects=True,
                    headers=_headers(),
                ) as client:
                    response = await client.get(
                        API_URL,
                        params={"secret": api_key, "url": url},
                    )
                    response.raise_for_status()
                    data = response.json()

            if isinstance(data, dict):
                files: list[FileResult] = []
                for raw_file in _normalise_api_files(data):
                    parsed = _parse_file(raw_file)
                    if parsed:
                        files.append(parsed)
                if files:
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
                        quality_urls=first.quality_urls,
                        files=files,
                    )
            # Empty/unsupported response: do not stop here. Continue into the
            # native resolver and gateway fallbacks.
        except httpx.TimeoutException:
            primary_note = "⏱️ Primary TeraBox API timed out; trying fallback resolver."
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            primary_note = f"⚠️ Primary TeraBox API returned HTTP {status}; trying fallback resolver."
        except Exception:
            primary_note = "⚠️ Primary TeraBox API failed; trying fallback resolver."
    else:
        primary_note = ""

    fallback_files, fallback_reason = await _fallback_resolve(url)
    if fallback_files:
        first = fallback_files[0]
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
            quality_urls=first.quality_urls,
            files=fallback_files,
            note="",
        )

    if not api_key and not TERABOX_NDUS:
        note = "No TeraBox resolver returned a usable file."
    elif fallback_reason:
        note = fallback_reason
    else:
        note = "No playable/downloadable file was returned by the available TeraBox resolvers."

    return ResolveResult(
        platform=platform,
        original_url=url,
        title="TeraBox link",
        note=note,
    )
