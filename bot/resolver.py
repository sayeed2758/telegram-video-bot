import json
import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.playterabox.com/api/proxy"
PUBLIC_WORKER_API = os.getenv(
    "TERABOX_PUBLIC_WORKER_API",
    "",
).strip()
GATEWAY_API = os.getenv("TERABOX_GATEWAY_API", "").strip()

REQUEST_TIMEOUT = float(os.getenv("TERABOX_RESOLVER_TIMEOUT", "15"))
PAGE_TIMEOUT = float(os.getenv("TERABOX_PAGE_TIMEOUT", "12"))

# Current public share/list implementations use these hosts.  Keeping them
# explicit is important: blindly turning a mirror hostname into www.<host>
# produces invalid endpoints for some TeraBox mirrors.
SHARE_LIST_ENDPOINTS = (
    "https://www.terabox.app/share/list",
    "https://www.1024tera.com/share/list",
    "https://www.terabox.com/share/list",
)


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
    candidates: list[dict] = []

    def add(value):
        if isinstance(value, list):
            candidates.extend(x for x in value if isinstance(x, dict))
        elif isinstance(value, dict):
            if any(k in value for k in (
                "name", "filename", "file_name", "server_filename",
                "dlink", "download_url", "download_link", "direct_link",
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


def _shorturl_variants(url_or_code: str) -> list[str]:
    code = _extract_shorturl(url_or_code) or url_or_code.strip()
    if not code:
        return []
    values = [code]
    # TeraBox public share URLs commonly expose /s/1<shortcode>, while the
    # share/list endpoint expects the shortcode without the leading 1.
    if code.startswith("1") and len(code) > 8:
        values.append(code[1:])
    return list(dict.fromkeys(values))


def _mirror_urls(url: str) -> list[str]:
    code = _extract_shorturl(url)
    if not code:
        return [url]
    values = _shorturl_variants(code)
    hosts = [
        "terasharefile.com", "terabox.app", "terabox.com", "1024tera.com",
        "1024terabox.com", "teraboxshare.com", "teraboxlink.com",
        "terafileshare.com", "terasharelink.com",
    ]
    result = [url]
    for host in hosts:
        for variant in values:
            result.append(f"https://{host}/s/{variant}")
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
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _extract_js_token(html: str) -> str:
    patterns = [
        r'window\.jsToken\s*=\s*["\']([^"\']+)["\']',
        r'window\.jsToken[^=]{0,80}=\s*["\']([^"\']+)["\']',
        r'jsToken%22%3A%22([^"%]+)',
        r'fn%28%22([^%]+)%22%29',
        r'fn%28%22([^"%]+)%22%29',
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


def _extract_bdstoken(html: str) -> str:
    patterns = (
        r'bdstoken["\']?\s*[:=]\s*["\']([^"\']+)',
        r'"bdstoken"\s*:\s*"([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return unquote(match.group(1))
    return ""


def _parse_cookie_env() -> dict[str, str]:
    raw = os.getenv("TERABOX_COOKIE", "").strip()
    cookies: dict[str, str] = {}
    if raw:
        for part in raw.split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                if key.strip() and value.strip():
                    cookies[key.strip()] = value.strip()
    ndus = os.getenv("TERABOX_NDUS", "").strip()
    if ndus:
        cookies["ndus"] = ndus
    return cookies


def _api_error(data) -> str:
    if not isinstance(data, dict):
        return "Invalid JSON response."
    errno = data.get("errno")
    errmsg = data.get("errmsg") or data.get("error") or data.get("message")
    if errno not in (None, 0, "0"):
        return str(errmsg or f"TeraBox errno {errno}")
    if errmsg and not data.get("list"):
        return str(errmsg)
    return ""


async def _direct_link(client: httpx.AsyncClient, dlink: str, referer: str) -> str:
    if not dlink:
        return ""
    try:
        response = await client.get(
            dlink,
            headers=_browser_headers(referer),
            follow_redirects=False,
            timeout=httpx.Timeout(8.0, connect=4.0),
        )
        location = response.headers.get("location") or response.headers.get("Location")
        if location:
            return location
    except Exception as exc:
        logger.info("TeraBox dlink redirect lookup failed: %s", type(exc).__name__)
    return ""


async def _native_share_resolve(url: str) -> tuple[list[FileResult], str]:
    """Resolve a public TeraBox share through the current share/list flow.

    This handles public/authorized shares only. It does not solve passwords,
    captchas, or private-account access.
    """
    if not _extract_shorturl(url):
        return [], "Invalid TeraBox share format."

    cookies = _parse_cookie_env()
    client_headers = _browser_headers()
    timeout = httpx.Timeout(PAGE_TIMEOUT, connect=5.0)
    attempts_log: list[str] = []

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=client_headers,
        cookies=cookies,
    ) as client:
        # The user's original share URL is preferred. Mirrors are only a
        # fallback if the original page itself fails.
        candidates = _mirror_urls(url)[:4]
        page_ok = False

        for share_url in candidates:
            try:
                response = await client.get(share_url)
                logger.info(
                    "TeraBox share page: status=%s url=%s final=%s",
                    response.status_code, share_url, response.url,
                )
                if response.status_code != 200:
                    attempts_log.append(f"share page HTTP {response.status_code}")
                    continue

                page_ok = True
                final_url = str(response.url)
                html = response.text
                token = _extract_js_token(html)
                log_id = _extract_log_id(html)
                bdstoken = _extract_bdstoken(html)

                surls = []
                for value in (_extract_shorturl(final_url), _extract_shorturl(share_url), _extract_shorturl(url)):
                    if value:
                        surls.extend(_shorturl_variants(value))
                surls = list(dict.fromkeys(surls))

                logger.info(
                    "TeraBox page metadata: final=%s surls=%s jsToken=%s dpLogId=%s bdstoken=%s",
                    final_url,
                    surls,
                    bool(token),
                    bool(log_id),
                    bool(bdstoken),
                )

                if not token:
                    attempts_log.append("jsToken not found")
                    continue

                # Try the current endpoint order first.  The endpoint contract
                # used by current open-source resolvers is share/list with
                # app_id=250528, jsToken and shorturl. Some pages also expose
                # dp-logid/bdstoken, so include those when available.
                for endpoint in SHARE_LIST_ENDPOINTS:
                    for surl in surls:
                        params = {
                            "app_id": "250528",
                            "web": "1",
                            "channel": "0",
                            "clienttype": "0",
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
                        if bdstoken:
                            params["bdstoken"] = bdstoken

                        try:
                            api_response = await client.get(
                                endpoint,
                                params=params,
                                headers={
                                    **_browser_headers(final_url),
                                    "Accept": "application/json, text/plain, */*",
                                    "X-Requested-With": "XMLHttpRequest",
                                },
                            )
                            logger.info(
                                "TeraBox share/list: status=%s endpoint=%s surl=%s",
                                api_response.status_code, endpoint, surl,
                            )
                            if api_response.status_code != 200:
                                attempts_log.append(f"share/list HTTP {api_response.status_code}")
                                continue

                            try:
                                data = api_response.json()
                            except ValueError:
                                attempts_log.append("share/list returned invalid JSON")
                                continue

                            if isinstance(data, dict):
                                logger.info(
                                    "TeraBox share/list response: errno=%s keys=%s errmsg=%s list_count=%s",
                                    data.get("errno"),
                                    sorted(data.keys())[:20],
                                    data.get("errmsg"),
                                    len(data.get("list", [])) if isinstance(data.get("list"), list) else 0,
                                )

                            api_error = _api_error(data)
                            if api_error:
                                attempts_log.append(api_error)
                                continue

                            raw_files = data.get("list", []) if isinstance(data, dict) else []
                            if not isinstance(raw_files, list):
                                raw_files = []

                            parsed_files: list[FileResult] = []
                            for raw in raw_files:
                                if not isinstance(raw, dict):
                                    continue
                                # Skip folders at the top level. We can still
                                # return them as unresolved rather than falsely
                                # claiming a direct video link exists.
                                if str(raw.get("isdir", "0")) in ("1", "true", "True"):
                                    continue
                                parsed = _parse_file(raw)
                                if not parsed:
                                    continue

                                # The dlink is the canonical share/download
                                # action URL. A redirect lookup gives a more
                                # direct playable URL when TeraBox exposes it.
                                if parsed.download_url and parsed.download_url == raw.get("dlink"):
                                    direct = await _direct_link(client, parsed.download_url, final_url)
                                    if direct:
                                        parsed.playable_url = direct
                                parsed_files.append(parsed)

                            if parsed_files:
                                logger.info(
                                    "Native TeraBox resolver SUCCESS: %s file(s)",
                                    len(parsed_files),
                                )
                                return parsed_files, ""

                            attempts_log.append("share/list returned no usable files")

                        except httpx.TimeoutException:
                            attempts_log.append("share/list timeout")
                        except httpx.HTTPError as exc:
                            attempts_log.append(f"share/list {type(exc).__name__}")

                # A successful page with a token should be enough to stop trying
                # unrelated mirror pages. If this page's API endpoints fail,
                # trying another mirror rarely improves the token/session pair.
                if page_ok:
                    break

            except httpx.TimeoutException:
                attempts_log.append("share page timeout")
            except httpx.HTTPError as exc:
                attempts_log.append(f"share page {type(exc).__name__}")

    # Keep the Telegram message short while retaining useful server-side logs.
    reason = attempts_log[-1] if attempts_log else "Public share could not be resolved."
    logger.warning("Native TeraBox resolver failed: %s", " | ".join(attempts_log[-8:]))
    return [], reason


async def _api_resolve(url: str, api_key: str) -> tuple[list[FileResult], str]:
    if not api_key:
        return [], "TERABOX_API_KEY is not configured."
    try:
        timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(API_URL, params={"secret": api_key, "url": url})
            response.raise_for_status()
            data = response.json()
        files = [_parse_file(x) for x in _normalise_files(data)]
        files = [x for x in files if x]
        return (files, "") if files else ([], "Primary API returned no usable files.")
    except httpx.TimeoutException:
        return [], "Primary API timed out."
    except httpx.HTTPStatusError as exc:
        return [], f"Primary API returned HTTP {exc.response.status_code}."
    except (httpx.HTTPError, ValueError) as exc:
        return [], f"Primary API error: {type(exc).__name__}."


async def _worker_resolve(url: str) -> tuple[list[FileResult], str]:
    if not PUBLIC_WORKER_API:
        return [], "Public worker fallback is disabled."
    try:
        timeout = httpx.Timeout(min(REQUEST_TIMEOUT, 8.0), connect=4.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(PUBLIC_WORKER_API, params={"url": url})
            logger.info("TeraBox worker fallback: HTTP %s", response.status_code)
            if response.status_code != 200:
                return [], f"Public worker HTTP {response.status_code}."
            data = response.json()
        files = [_parse_file(x) for x in _normalise_files(data)]
        files = [x for x in files if x]
        return (files, "") if files else ([], "Public worker returned no usable files.")
    except (httpx.TimeoutException, httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return [], f"Public worker {type(exc).__name__}."


async def _gateway_resolve(url: str) -> tuple[list[FileResult], str]:
    if not GATEWAY_API:
        return [], "Gateway fallback is disabled."
    try:
        timeout = httpx.Timeout(min(REQUEST_TIMEOUT, 8.0), connect=4.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                GATEWAY_API,
                params={"mode": "resolve", "url": url, "raw": "1"},
            )
            logger.info("TeraBox gateway fallback: HTTP %s", response.status_code)
            if response.status_code != 200:
                return [], f"Gateway HTTP {response.status_code}."
            data = response.json()
        if isinstance(data, dict) and isinstance(data.get("upstream"), dict):
            data = data["upstream"]
        files = [_parse_file(x) for x in _normalise_files(data)]
        files = [x for x in files if x]
        return (files, "") if files else ([], "Gateway returned no usable files.")
    except (httpx.TimeoutException, httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return [], f"Gateway {type(exc).__name__}."


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

    attempts: list[str] = []

    try:
        files, error = await _native_share_resolve(url)
        if files:
            return _success(platform, url, files)
        attempts.append(f"native: {error}")
    except Exception as exc:
        logger.exception("Native TeraBox resolver failed")
        attempts.append(f"native: {type(exc).__name__}")

    api_key = os.getenv("TERABOX_API_KEY", "").strip()
    files, error = await _api_resolve(url, api_key)
    if files:
        return _success(platform, url, files)
    attempts.append(f"api: {error}")

    # Optional external fallbacks are intentionally disabled by default. This
    # prevents known-dead public endpoints from wasting webhook time.
    if PUBLIC_WORKER_API:
        files, error = await _worker_resolve(url)
        if files:
            return _success(platform, url, files)
        attempts.append(f"worker: {error}")

    if GATEWAY_API:
        files, error = await _gateway_resolve(url)
        if files:
            return _success(platform, url, files)
        attempts.append(f"gateway: {error}")

    logger.warning("TeraBox resolution failed: %s", " | ".join(attempts))
    return ResolveResult(
        platform=platform,
        original_url=url,
        note=(
            "TeraBox could not return a downloadable file. "
            "Check the Render logs for the exact share/list errno."
        ),
    )
