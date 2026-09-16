import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

from bot.config import (
    TERABOX_COOKIE,
    TERABOX_GATEWAY_URL,
    TERABOX_NDUS,
    TERABOX_PROXY_URL,
    TERABOX_PUBLIC_GATEWAYS,
    TERABOX_TBX_PROXY_URL,
    TERABOX_API_KEY,
    TERABOX_API_URL,
    TERABOX_LEGACY_API_URL,
)

logger = logging.getLogger(__name__)
# Never print request URLs because the PlayTeraBox API key is carried in the
# documented `secret` query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)

_PLAYTERABOX_RATE_LIMIT_UNTIL = 0.0
_PLAYTERABOX_REQUEST_LOCK = asyncio.Lock()
_PLAYTERABOX_LAST_REQUEST_AT = 0.0
PLAYTERABOX_MIN_INTERVAL = 1.5

async def _wait_for_playterabox_slot() -> None:
    """Keep API request starts gently spaced to avoid burst throttling."""
    global _PLAYTERABOX_LAST_REQUEST_AT
    async with _PLAYTERABOX_REQUEST_LOCK:
        now = time.monotonic()
        delay = PLAYTERABOX_MIN_INTERVAL - (now - _PLAYTERABOX_LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        _PLAYTERABOX_LAST_REQUEST_AT = time.monotonic()

TIMEOUT = httpx.Timeout(12.0, connect=5.0)
PLAYTERABOX_API_ATTEMPTS = 4
PLAYTERABOX_RETRY_DELAYS = (0.75, 1.5, 2.5)

# Temporary API failures are retried internally. The user should not have to
# press Retry just because the first API request timed out.
PLAYTERABOX_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

SHARE_LIST_HOSTS = (
    "www.terabox.app",
    "www.1024tera.com",
    "www.terabox.com",
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.terabox.app/",
}


@dataclass
class ResolvedFile:
    name: str
    size: str
    thumbnail: str | None = None
    file_type: str | None = None
    duration: str | None = None
    quality: str | None = None
    direct_url: str | None = None
    stream_url: str | None = None
    quality_urls: dict[str, str] | None = None


@dataclass
class ResolveResult:
    ok: bool
    files: list[ResolvedFile]
    message: str


def _canonical_api_share_url(url: str) -> str:
    """Normalize supported TeraBox mirror shares for the API provider.

    Some supported share domains are mirrors of a normal TeraBox share.
    The PlayTeraBox API accepts the canonical 1024terabox.com share form,
    so preserve the original /s/<code> and only change the hostname.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url

    host = (parsed.hostname or "").lower()
    mirror_hosts = {
        "teraboxshare.com",
        "www.teraboxshare.com",
        "teraboxlink.com",
        "www.teraboxlink.com",
        "terafileshare.com",
        "www.terafileshare.com",
        "terasharefile.com",
        "www.terasharefile.com",
        "terasharelink.com",
        "www.terasharelink.com",
    }

    if host not in mirror_hosts:
        return url

    match = re.search(r"/s/([^/?#]+)", parsed.path, re.I)
    if not match:
        return url

    code = match.group(1)
    return f"https://1024terabox.com/s/{code}"


def _short_code(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/")
    match = re.search(r"/s/([^/]+)", path, re.I)
    if not match:
        return None
    code = match.group(1)
    return code[1:] if code.startswith("1") else code


def _extract_js_token(html: str) -> str | None:
    patterns = (
        r'jsToken["\']?\s*[:=]\s*["\']([^"\']+)',
        r'jsToken\s*=\s*["\']([^"\']+)',
        r'fn%28%22([^%]+)%22%29',
        r'fn\("([^"]+)"\)',
        r'window\.jsToken\s*=\s*["\']([^"\']+)',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return unquote(match.group(1))
    return None


def _extract_log_id(html: str) -> str | None:
    patterns = (
        r'dp-logid[=\\":]+([0-9]+)',
        r'dp-logid%3D([0-9]+)',
        r'"dp-logid"\s*:\s*"?([0-9]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return None


def _extract_bd_token(html: str) -> str | None:
    match = re.search(r'bdstoken["\\\']\s*[:=]\s*["\\\']([^"\\\']+)', html, re.I)
    return match.group(1) if match else None


def _cookie_header() -> str | None:
    if TERABOX_COOKIE:
        return TERABOX_COOKIE

    if TERABOX_NDUS:
        return f"ndus={TERABOX_NDUS}"

    return None


def _extract_file_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("list", "files", "items", "results", "contents"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    for key in ("data", "result", "upstream"):
        value = payload.get(key)
        if isinstance(value, dict):
            found = _extract_file_list(value)
            if found:
                return found

    return []


def _format_size(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Unknown size"

    if number < 0:
        return "Unknown size"

    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1

    return f"{int(number)} {units[index]}" if index == 0 else f"{number:.2f} {units[index]}"


def _pick_fast_stream_url(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, dict):
        return None

    # Prefer the best documented quality when the API returns a quality map.
    for quality in ("1080p", "720p", "480p", "360p"):
        url = value.get(quality)
        if isinstance(url, str) and url.strip():
            return url.strip()

    for url in value.values():
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _extract_quality_urls(item: dict) -> dict[str, str]:
    """Read the documented PlayTeraBox fast_stream_url quality map."""
    value = item.get("fast_stream_url")
    if not isinstance(value, dict):
        return {}

    quality_urls: dict[str, str] = {}
    for quality, url in value.items():
        if not isinstance(quality, str) or not isinstance(url, str):
            continue
        if not url.strip():
            continue
        label = quality.strip().lower()
        if not label:
            continue
        quality_urls[label] = url.strip()

    return quality_urls


def _file_from_dict(item: dict) -> ResolvedFile | None:
    name = (
        item.get("server_filename")
        or item.get("file_name")
        or item.get("filename")
        or item.get("name")
    )
    if not name:
        return None

    thumbs = item.get("thumbs")
    thumb = thumbs.get("url3") if isinstance(thumbs, dict) else None
    thumb = thumb or item.get("thumbnail") or item.get("thumb")

    # PlayTeraBox /api/proxy fields. Keep older resolver field names too so
    # previous owner-controlled resolvers remain compatible.
    direct = (
        item.get("download_link")
        or item.get("fast_download_link")
        or item.get("dlink")
        or item.get("download_url")
        or item.get("downloadUrl")
        or item.get("direct_link")
    )

    # Some API variants wrap URLs inside a links/urls object. Keep this
    # fallback limited to explicit download-named keys so a stream URL is
    # never accidentally exposed as a download action.
    if not direct:
        for container_key in ("links", "urls", "download"):
            container = item.get(container_key)
            if isinstance(container, dict):
                direct = (
                    container.get("download_link")
                    or container.get("fast_download_link")
                    or container.get("download_url")
                    or container.get("url")
                )
                if isinstance(direct, str) and direct.strip():
                    break
                direct = None

    quality_urls = _extract_quality_urls(item)

    stream = (
        item.get("stream_url")
        or item.get("streamUrl")
        or item.get("m3u8")
        or item.get("hls")
        or _pick_fast_stream_url(item.get("fast_stream_url"))
    )

    return ResolvedFile(
        name=str(name),
        size=_format_size(item.get("size") or item.get("file_size")),
        thumbnail=thumb if isinstance(thumb, str) else None,
        file_type=str(item.get("type")).strip() if item.get("type") is not None else None,
        duration=str(item.get("duration")).strip() if item.get("duration") is not None else None,
        quality=str(item.get("quality")).strip() if item.get("quality") is not None else None,
        direct_url=direct if isinstance(direct, str) else None,
        stream_url=stream if isinstance(stream, str) else None,
        quality_urls=quality_urls or None,
    )


def _parse_files(payload) -> list[ResolvedFile]:
    result = []
    for item in _extract_file_list(payload):
        parsed = _file_from_dict(item)
        if parsed:
            result.append(parsed)
    return result


async def _playterabox_api_resolve(
    client: httpx.AsyncClient,
    share_url: str,
) -> ResolveResult:
    """Resolve a TeraBox share through the current ApiDash TeraBox API.

    Primary endpoint: POST /api/terabox-pro with ApiDash-Key header.
    The older GET /api/proxy route is retained only as a compatibility
    fallback for endpoint-shape errors (404/405).
    """
    if not TERABOX_API_KEY:
        return ResolveResult(False, [], "PlayTeraBox API key is not configured.")

    global _PLAYTERABOX_RATE_LIMIT_UNTIL

    now = time.monotonic()
    if now < _PLAYTERABOX_RATE_LIMIT_UNTIL:
        remaining = max(1, int(_PLAYTERABOX_RATE_LIMIT_UNTIL - now))
        return ResolveResult(
            False,
            [],
            f"PlayTeraBox API is rate-limiting requests. Please wait about {remaining} seconds and try again.",
        )

    api_share_url = _canonical_api_share_url(share_url)

    # Current ApiDash documentation: POST /api/terabox-pro + ApiDash-Key.
    endpoints = [
        (TERABOX_API_URL or "https://api.playterabox.com/api/terabox-pro", "current"),
    ]

    # Keep the legacy playground endpoint as a compatibility fallback only.
    legacy = TERABOX_LEGACY_API_URL or "https://api.playterabox.com/api/proxy"
    if legacy.rstrip("/") != endpoints[0][0].rstrip("/"):
        endpoints.append((legacy, "legacy"))

    for endpoint, endpoint_kind in endpoints:
        response = None
        last_error = "PlayTeraBox API request failed."
        # Two attempts for transient 5xx/transport errors. 429 is handled
        # explicitly and is never hammered with immediate retries.
        attempts = 2

        for attempt in range(1, attempts + 1):
            await _wait_for_playterabox_slot()
            try:
                if endpoint_kind == "current":
                    response = await client.post(
                        endpoint,
                        json={"url": api_share_url},
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "ApiDash-Key": TERABOX_API_KEY,
                        },
                    )
                else:
                    response = await client.get(
                        endpoint,
                        params={"secret": TERABOX_API_KEY, "url": api_share_url},
                        headers={
                            "Accept": "application/json",
                            "secret": TERABOX_API_KEY,
                        },
                    )
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                last_error = f"PlayTeraBox API request timed out ({exc.__class__.__name__})."
                logger.warning(
                    "PlayTeraBox %s API timeout on attempt %s/%s: %s",
                    endpoint_kind, attempt, attempts, exc.__class__.__name__,
                )
                if attempt < attempts:
                    await asyncio.sleep(0.75)
                    continue
                response = None
                break
            except httpx.HTTPError as exc:
                last_error = f"PlayTeraBox API request failed: {exc.__class__.__name__}"
                logger.warning(
                    "PlayTeraBox %s API transport failure on attempt %s/%s: %s",
                    endpoint_kind, attempt, attempts, exc.__class__.__name__,
                )
                if attempt < attempts:
                    await asyncio.sleep(0.75)
                    continue
                response = None
                break

            logger.info(
                "PlayTeraBox %s API -> HTTP %s (attempt %s/%s)",
                endpoint_kind, response.status_code, attempt, attempts,
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    wait_seconds = max(5, int(float(retry_after)))
                except (TypeError, ValueError):
                    wait_seconds = 15
                _PLAYTERABOX_RATE_LIMIT_UNTIL = time.monotonic() + wait_seconds
                logger.warning(
                    "PlayTeraBox %s API rate limited (429); cooldown=%ss.",
                    endpoint_kind, wait_seconds,
                )
                # A 429 from the current endpoint is a provider-side state;
                # do not repeatedly hammer it. Do not automatically switch to
                # the legacy endpoint unless the current route is missing.
                return ResolveResult(
                    False,
                    [],
                    f"PlayTeraBox API is rate-limiting requests. Please wait about {wait_seconds} seconds and try again.",
                )

            if response.status_code >= 500 and attempt < attempts:
                await asyncio.sleep(0.75)
                continue
            break

        if response is None:
            if endpoint_kind == "current":
                # If the current endpoint failed at the transport layer, the
                # legacy compatibility route can still be tried once.
                continue
            return ResolveResult(False, [], last_error)

        # Only endpoint-shape errors trigger compatibility fallback.
        if response.status_code in {404, 405}:
            logger.warning(
                "PlayTeraBox %s endpoint returned HTTP %s; trying compatibility endpoint.",
                endpoint_kind, response.status_code,
            )
            continue

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return ResolveResult(False, [], "PlayTeraBox API returned invalid JSON.")

        if response.status_code == 401:
            return ResolveResult(False, [], "PlayTeraBox API key is invalid or missing.")
        if response.status_code == 402:
            return ResolveResult(False, [], "PlayTeraBox API wallet balance is insufficient.")
        if response.status_code == 403:
            return ResolveResult(False, [], "PlayTeraBox API access is denied or the API is not subscribed.")
        if response.status_code >= 400:
            reason = None
            if isinstance(payload, dict):
                reason = payload.get("message") or payload.get("error") or payload.get("detail")
            return ResolveResult(False, [], str(reason or f"PlayTeraBox API returned HTTP {response.status_code}."))

        files = _parse_files(payload)
        if files:
            return ResolveResult(True, files, "Resolved through PlayTeraBox API.")

        status_value = payload.get("status") if isinstance(payload, dict) else None
        if status_value not in {None, "success", True}:
            return ResolveResult(False, [], f"PlayTeraBox API returned status: {status_value}.")
        return ResolveResult(False, [], "PlayTeraBox API returned no playable files.")

    return ResolveResult(False, [], last_error)

async def _proxy_resolve(client: httpx.AsyncClient, code: str, password: str | None = None) -> ResolveResult:
    if not TERABOX_PROXY_URL:
        return ResolveResult(False, [], "Proxy resolver is not configured.")

    try:
        response = await client.get(
            TERABOX_PROXY_URL,
            params={"mode": "resolve", "surl": code, "refresh": "1", **({"pwd": password} if password else {})},
        )
    except httpx.HTTPError as exc:
        logger.warning("Proxy resolver request failed: %s", exc)
        return ResolveResult(False, [], f"Proxy request failed: {exc.__class__.__name__}")

    logger.info("Proxy resolver -> HTTP %s", response.status_code)

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return ResolveResult(False, [], "Proxy returned invalid JSON.")

    files = _parse_files(payload)
    if files:
        return ResolveResult(True, files, f"Found {len(files)} file(s).")

    error = payload.get("error") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None

    if isinstance(data, dict):
        one = _file_from_dict(data)
        if one:
            return ResolveResult(True, [one], "Found 1 file.")

    return ResolveResult(
        False,
        [],
        str(error or "Proxy did not return usable file metadata."),
    )



# Public gateway fallbacks. These are not treated as authoritative; they are
# simply additional resolution attempts when the direct TeraBox flow asks
# for verification. No private cookies are sent to these endpoints.
DEFAULT_PUBLIC_GATEWAYS = (
    "https://terabox-worker.robinkumarshakya103.workers.dev/api",
    "https://tera.pyann.me/api/tera",
)


DEFAULT_TBX_PROXY_URL = "https://tbx-proxy.shakir-ansarii075.workers.dev/"


async def _tbx_proxy_resolve(
    client: httpx.AsyncClient,
    code: str,
    password: str | None = None,
) -> ResolveResult:
    """Try the documented TBX Cloudflare proxy without forwarding private cookies."""
    proxy = (TERABOX_TBX_PROXY_URL or DEFAULT_TBX_PROXY_URL).rstrip("/") + "/"
    try:
        response = await client.get(
            proxy,
            params={"mode": "resolve", "surl": code, "refresh": "1", "raw": "1", **({"pwd": password} if password else {})},
            headers=BROWSER_HEADERS,
        )
    except httpx.HTTPError as exc:
        logger.warning("TBX proxy request failed: %s", exc)
        return ResolveResult(False, [], f"TBX proxy failed: {exc.__class__.__name__}")

    logger.info("TBX proxy -> HTTP %s", response.status_code)
    if response.status_code != 200:
        return ResolveResult(False, [], f"TBX proxy returned HTTP {response.status_code}.")

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return ResolveResult(False, [], "TBX proxy returned invalid JSON.")

    files = _parse_files(payload)
    if not files and isinstance(payload, dict):
        data = payload.get("data") or payload.get("upstream")
        if isinstance(data, dict):
            files = _parse_files(data)

    if not files:
        reason = payload.get("error") or payload.get("message") if isinstance(payload, dict) else None
        return ResolveResult(False, [], str(reason or "TBX proxy returned no file metadata."))

    # The proxy documents a stream mode that can produce an HLS playlist even
    # when a raw TeraBox dlink would require private cookies.
    stream_url = f"{proxy}?mode=stream&surl={code}"
    for item in files:
        if not item.stream_url:
            item.stream_url = stream_url

    return ResolveResult(True, files, f"Found {len(files)} file(s) through TBX proxy.")


async def _public_gateway_resolve(
    client: httpx.AsyncClient,
    share_url: str,
    password: str | None = None,
) -> ResolveResult:
    gateways = TERABOX_PUBLIC_GATEWAYS or DEFAULT_PUBLIC_GATEWAYS

    for gateway in gateways:
        try:
            response = await client.get(
                gateway,
                params={"url": share_url, **({"pwd": password} if password else {})},
                headers=BROWSER_HEADERS,
            )
        except httpx.HTTPError as exc:
            logger.warning("Public gateway %s failed: %s", gateway, exc.__class__.__name__)
            continue

        logger.info("Public gateway %s -> HTTP %s", gateway, response.status_code)

        if response.status_code != 200:
            continue

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            continue

        files = _parse_files(payload)
        if files:
            return ResolveResult(True, files, f"Found {len(files)} file(s).")

        if isinstance(payload, dict):
            for key in ("data", "result", "response", "upstream"):
                nested = payload.get(key)
                if isinstance(nested, (dict, list)):
                    files = _parse_files(nested)
                    if files:
                        return ResolveResult(True, files, f"Found {len(files)} file(s).")

    return ResolveResult(False, [], "Public gateways did not return usable file metadata.")

async def _gateway_resolve(
    client: httpx.AsyncClient,
    share_url: str,
    password: str | None = None,
) -> ResolveResult:
    """Use only an explicitly configured compatible gateway."""
    if not TERABOX_GATEWAY_URL:
        return ResolveResult(False, [], "No gateway resolver is configured.")

    headers = dict(BROWSER_HEADERS)
    cookie = _cookie_header()
    if cookie:
        headers["Cookie"] = cookie

    try:
        response = await client.get(
            TERABOX_GATEWAY_URL,
            params={"url": share_url, "resolve": "true", **({"pwd": password} if password else {})},
            headers=headers,
        )
    except httpx.HTTPError as exc:
        logger.warning("Configured gateway request failed: %s", exc)
        return ResolveResult(
            False, [], f"Configured gateway failed: {exc.__class__.__name__}"
        )

    logger.info("Configured gateway -> HTTP %s", response.status_code)

    if response.status_code != 200:
        return ResolveResult(
            False, [], f"Configured gateway returned HTTP {response.status_code}."
        )

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return ResolveResult(False, [], "Configured gateway returned invalid JSON.")

    files = _parse_files(payload)
    if files:
        return ResolveResult(True, files, f"Found {len(files)} file(s).")

    if isinstance(payload, dict):
        for key in ("data", "result", "upstream"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                files = _parse_files(nested)
                if files:
                    return ResolveResult(True, files, f"Found {len(files)} file(s).")

        reason = payload.get("errmsg") or payload.get("message") or payload.get("error")
        if reason:
            return ResolveResult(False, [], str(reason))

    return ResolveResult(False, [], "Configured gateway returned no usable files.")


async def _native_resolve(
    client: httpx.AsyncClient,
    url: str,
    code: str,
    password: str | None = None,
) -> ResolveResult:
    headers = dict(BROWSER_HEADERS)
    cookie = _cookie_header()
    if cookie:
        headers["Cookie"] = cookie

    try:
        page = await client.get(url, headers=headers)
        page.raise_for_status()
    except httpx.HTTPError as exc:
        return ResolveResult(False, [], f"TeraBox page request failed: {exc.__class__.__name__}")

    final_code = _short_code(str(page.url)) or code
    js_token = _extract_js_token(page.text)
    log_id = _extract_log_id(page.text)
    bd_token = _extract_bd_token(page.text)

    if not js_token:
        return ResolveResult(False, [], "TeraBox jsToken was not found.")

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
        "shorturl": final_code,
        "root": "1",
    }
    if log_id:
        params["dp-logid"] = log_id

    # Some current API responses use bdstoken as part of the verified session.
    if bd_token:
        params["bdstoken"] = bd_token
    if password:
        params["pwd"] = password

    last_error = "No usable files returned."

    for host in SHARE_LIST_HOSTS:
        try:
            response = await client.get(
                f"https://{host}/share/list",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            last_error = f"{host}: {exc.__class__.__name__}"
            continue

        logger.info("Native share/list %s -> HTTP %s", host, response.status_code)

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            last_error = f"{host}: invalid JSON"
            continue

        logger.info(
            "Native share/list %s errno=%s errmsg=%s",
            host,
            payload.get("errno") if isinstance(payload, dict) else None,
            payload.get("errmsg") if isinstance(payload, dict) else None,
        )

        files = _parse_files(payload)
        if files:
            return ResolveResult(True, files, f"Found {len(files)} file(s).")

        if isinstance(payload, dict):
            last_error = str(
                payload.get("errmsg")
                or payload.get("message")
                or last_error
            )

    return ResolveResult(False, [], last_error)


async def resolve_link(url: str, password: str | None = None, session_only: bool = False) -> ResolveResult:
    """Resolve a TeraBox share without long anonymous fallback chains.

    Phase 13 intentionally keeps the path small and predictable:
    1) PlayTeraBox API Pro when configured
    2) optional owner-controlled gateway/proxy
    3) native TeraBox request
    4) return immediately on provider rate-limit/verification/password errors

    Public third-party fallbacks are disabled here because repeated failing
    external requests were leaving Telegram users stuck on Processing.
    """
    code = _short_code(url)
    if not code:
        return ResolveResult(False, [], "Invalid TeraBox share URL.")

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        # 1. PlayTeraBox API Pro (owner subscription).
        if TERABOX_API_KEY:
            if time.monotonic() < _PLAYTERABOX_RATE_LIMIT_UNTIL:
                remaining = max(1, int(_PLAYTERABOX_RATE_LIMIT_UNTIL - time.monotonic()))
                return ResolveResult(
                    False,
                    [],
                    f"PlayTeraBox API is rate-limiting requests. Please wait about {remaining} seconds and try again.",
                )

            api_result = await _playterabox_api_resolve(client, url)
            if api_result.ok:
                return api_result
            # Never fall through to native TeraBox after a provider 429.
            # Doing so only produces the misleading `need verify` message and
            # encourages users to repeat calls while the paid API is cooling down.
            # When the paid PlayTeraBox API is configured, keep it authoritative.
            # A transient timeout is retried internally above; if the API still
            # fails, do not fall into the native resolver because its `need verify`
            # response is a different failure mode and only confuses the user.
            return api_result

        # 2. Optional owner-controlled gateway.
        if TERABOX_GATEWAY_URL:
            gateway_result = await _gateway_resolve(client, url, password)
            if gateway_result.ok:
                return gateway_result
            if _is_password_error(gateway_result.message):
                return ResolveResult(False, [], "Password required for this TeraBox share.")
            if _is_verification_error(gateway_result.message):
                return ResolveResult(False, [], _session_message())

        # 3. Optional owner-controlled proxy.
        if TERABOX_PROXY_URL:
            proxy_result = await _proxy_resolve(client, code, password)
            if proxy_result.ok:
                return proxy_result
            if _is_password_error(proxy_result.message):
                return ResolveResult(False, [], "Password required for this TeraBox share.")
            if _is_verification_error(proxy_result.message):
                return ResolveResult(False, [], _session_message())

        # 4. Native TeraBox flow. This remains the backup route.
        native_result = await _native_resolve(client, url, code, password)
        if native_result.ok:
            return native_result

        if _is_password_error(native_result.message):
            return ResolveResult(False, [], "Password required for this TeraBox share.")

        if _is_verification_error(native_result.message):
            if session_only and not _cookie_header():
                return ResolveResult(False, [], "No TeraBox session is configured.")
            return ResolveResult(False, [], _session_message())

        if session_only:
            if _cookie_header():
                return ResolveResult(
                    False,
                    [],
                    f"Configured TeraBox session was not accepted: {native_result.message}",
                )
            return ResolveResult(False, [], "No TeraBox session is configured.")

        return ResolveResult(False, [], native_result.message)


def _is_verification_error(message: str) -> bool:
    lowered = str(message).lower()
    return any(token in lowered for token in (
        "need verify",
        "verification required",
        "4000020",
        "verify",
        "session required",
    ))


def _is_password_error(message: str) -> bool:
    lowered = str(message).lower()
    return any(token in lowered for token in (
        "password",
        "need extract code",
        "400141",
        "errno -3",
        "pwd",
    ))


def _session_message() -> str:
    if _cookie_header():
        return (
            "TeraBox verification required. The configured session was not accepted "
            "for this share."
        )
    return (
        "TeraBox verification required. This share needs a valid TeraBox session."
    )

