import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

from bot.config import TERABOX_COOKIE, TERABOX_NDUS, TERABOX_PROXY_URL

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(12.0, connect=6.0)

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
    direct_url: str | None = None


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

    direct = (
        item.get("dlink")
        or item.get("download_url")
        or item.get("downloadUrl")
        or item.get("direct_link")
    )

    return ResolvedFile(
        name=str(name),
        size=_format_size(item.get("size") or item.get("file_size")),
        thumbnail=thumb,
        direct_url=direct if isinstance(direct, str) else None,
    )


def _parse_files(payload) -> list[ResolvedFile]:
    result = []
    for item in _extract_file_list(payload):
        parsed = _file_from_dict(item)
        if parsed:
            result.append(parsed)
    return result


async def _proxy_resolve(client: httpx.AsyncClient, code: str) -> ResolveResult:
    if not TERABOX_PROXY_URL:
        return ResolveResult(False, [], "Proxy resolver is not configured.")

    try:
        response = await client.get(
            TERABOX_PROXY_URL,
            params={"mode": "resolve", "surl": code, "refresh": "1"},
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


async def _native_resolve(
    client: httpx.AsyncClient,
    url: str,
    code: str,
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


async def resolve_link(url: str) -> ResolveResult:
    code = _short_code(url)
    if not code:
        return ResolveResult(False, [], "Invalid TeraBox share URL.")

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        # First use the current unified proxy. It is designed to handle
        # TeraBox token extraction server-side.
        proxy_result = await _proxy_resolve(client, code)
        if proxy_result.ok:
            return proxy_result

        # Then try the native flow, carrying an optional verified session.
        native_result = await _native_resolve(client, url, code)
        if native_result.ok:
            return native_result

        reason = native_result.message
        if "need verify" in reason.lower() or "verify" in reason.lower():
            if not _cookie_header():
                reason += (
                    " TeraBox is requiring a verified session. "
                    "This bot can use TERABOX_COOKIE or TERABOX_NDUS if you provide one."
                )

        return ResolveResult(False, [], reason)
