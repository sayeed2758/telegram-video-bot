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
)

logger = logging.getLogger(__name__)
# Never print request URLs because the PlayTeraBox API key is carried in the
# documented `secret` query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)

_PLAYTERABOX_RATE_LIMIT_UNTIL = 0.0

TIMEOUT = httpx.Timeout(5.0, connect=3.0)

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
    """Resolve a share through the active PlayTeraBox /api/proxy endpoint.

    The user's PlayTeraBox dashboard documents:
      GET https://api.playterabox.com/api/proxy
      ?secret=<API key>&url=<TeraBox share URL>

    The key is sent only to PlayTeraBox as the secret query parameter.
    Private TeraBox cookies are never forwarded to this service.
    """
    if not TERABOX_API_KEY:
        return ResolveResult(False, [], "PlayTeraBox API key is not configured.")

    try:
        response = await client.get(
            TERABOX_API_URL,
            params={"secret": TERABOX_API_KEY, "url": share_url},
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.warning("PlayTeraBox API request failed: %s", exc.__class__.__name__)
        return ResolveResult(
            False,
            [],
            f"PlayTeraBox API request failed: {exc.__class__.__name__}",
        )

    logger.info("PlayTeraBox API GET /api/proxy -> HTTP %s", response.status_code)

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "")
        try:
            wait_seconds = max(1, int(float(retry_after)))
        except (TypeError, ValueError):
            wait_seconds = 60
        global _PLAYTERABOX_RATE_LIMIT_UNTIL
        _PLAYTERABOX_RATE_LIMIT_UNTIL = time.monotonic() + wait_seconds
        return ResolveResult(
            False,
            [],
            f"PlayTeraBox API is rate-limiting requests. Please wait about {wait_seconds} seconds and try again.",
        )

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
        return ResolveResult(
            False,
            [],
            str(reason or f"PlayTeraBox API returned HTTP {response.status_code}."),
        )

    if isinstance(payload, dict):
        status = str(payload.get("status", "")).lower().strip()
        if status and status not in {"success", "ok", "true"}:
            reason = payload.get("message") or payload.get("error") or payload.get("detail")
            if reason:
                return ResolveResult(False, [], str(reason))

    files = _parse_files(payload)

    # Exact /api/proxy response shape is {status, total_files, list:[...]}.
    # _parse_files already handles that list, including download_link and
    # stream_url. The extra candidates below keep compatibility with possible
    # wrapper objects returned by the API in the future.
    candidates = []
    if isinstance(payload, dict):
        for key in ("data", "result", "response", "file", "files", "dataList"):
            value = payload.get(key)
            if isinstance(value, (dict, list)):
                candidates.append(value)

    for candidate in candidates:
        if isinstance(candidate, dict):
            one = _file_from_dict(candidate)
            if one:
                files.append(one)
            nested = _parse_files(candidate)
            if nested:
                files.extend(nested)
        elif isinstance(candidate, list):
            files.extend(_parse_files(candidate))

    unique = []
    seen = set()
    for item in files:
        key = (item.name, item.direct_url or "", item.stream_url or "")
        if key not in seen:
            seen.add(key)
            unique.append(item)

    if not unique:
        reason = None
        if isinstance(payload, dict):
            reason = payload.get("message") or payload.get("error") or payload.get("detail")
        return ResolveResult(
            False,
            [],
            str(reason or "PlayTeraBox API returned no usable file data."),
        )

    return ResolveResult(True, unique, f"Found {len(unique)} file(s) via PlayTeraBox API.")


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
            if "rate-limiting requests" in api_result.message.lower():
                return api_result
            # A configured API is the authoritative paid route for this phase.
            if any(token in api_result.message.lower() for token in (
                "api key",
                "wallet balance",
                "not subscribed",
                "access is denied",
            )):
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

