import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

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
    if match:
        return match.group(1)
    return None


def _extract_js_token(html: str) -> str | None:
    patterns = (
        r'jsToken["\']?\s*[:=]\s*["\']([^"\']+)',
        r'jsToken\s*=\s*["\']([^"\']+)',
        r'fn%28%22([^%]+)%22%29',
        r'fn\("([^"]+)"\)',
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


def _extract_file_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("list", "files", "items", "results", "contents"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    for key in ("data", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            found = _extract_file_list(value)
            if found:
                return found

    return []


def _format_size(value) -> str:
    try:
        size = int(float(value))
    except (TypeError, ValueError):
        return "Unknown size"

    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    number = float(size)
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1

    if index == 0:
        return f"{int(number)} {units[index]}"
    return f"{number:.2f} {units[index]}"


def _file_from_dict(item: dict) -> ResolvedFile | None:
    name = (
        item.get("server_filename")
        or item.get("file_name")
        or item.get("filename")
        or item.get("name")
    )
    if not name:
        return None

    direct = (
        item.get("dlink")
        or item.get("download_url")
        or item.get("downloadUrl")
        or item.get("direct_link")
    )

    thumb = (
        item.get("thumbs", {}).get("url3")
        if isinstance(item.get("thumbs"), dict)
        else None
    ) or item.get("thumbnail") or item.get("thumb")

    return ResolvedFile(
        name=str(name),
        size=_format_size(item.get("size") or item.get("file_size")),
        thumbnail=thumb,
        direct_url=direct if isinstance(direct, str) else None,
    )


async def resolve_public_share(url: str) -> ResolveResult:
    """Resolve public share metadata only.

    This phase deliberately stops after obtaining file metadata. It does not
    download files, bypass passwords, or solve CAPTCHA/verification.
    """
    code = _short_code(url)
    if not code:
        return ResolveResult(False, [], "Invalid TeraBox share URL.")

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        try:
            page = await client.get(url)
            page.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("TeraBox share page request failed: %s", exc)
            return ResolveResult(False, [], "Could not open the TeraBox share page.")

        final_url = str(page.url)
        final_code = _short_code(final_url) or code
        js_token = _extract_js_token(page.text)
        log_id = _extract_log_id(page.text)

        if not js_token:
            logger.warning("TeraBox page opened but jsToken was not found.")
            return ResolveResult(
                False,
                [],
                "TeraBox opened, but the public share token was not found.",
            )

        if not log_id:
            logger.info("TeraBox dp-logid was not found; continuing without it.")

        common = {
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
            common["dp-logid"] = log_id

        last_reason = "No usable files returned."

        for host in SHARE_LIST_HOSTS:
            endpoint = f"https://{host}/share/list"
            try:
                response = await client.get(endpoint, params=common)
            except httpx.HTTPError as exc:
                last_reason = f"{host}: {exc.__class__.__name__}"
                logger.warning("share/list failed on %s: %s", host, exc)
                continue

            logger.info(
                "TeraBox share/list %s -> HTTP %s",
                host,
                response.status_code,
            )

            if response.status_code != 200:
                last_reason = f"{host}: HTTP {response.status_code}"
                continue

            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError):
                last_reason = f"{host}: invalid JSON"
                continue

            logger.info(
                "TeraBox share/list %s keys=%s errno=%s",
                host,
                sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                payload.get("errno") if isinstance(payload, dict) else None,
            )

            raw_files = _extract_file_list(payload)
            files = []
            for item in raw_files:
                parsed = _file_from_dict(item)
                if parsed:
                    files.append(parsed)

            if files:
                return ResolveResult(
                    True,
                    files,
                    f"Found {len(files)} file(s).",
                )

            if isinstance(payload, dict):
                last_reason = str(
                    payload.get("errmsg")
                    or payload.get("message")
                    or f"{host}: no files"
                )

        return ResolveResult(False, [], last_reason)


async def resolve_link(url: str) -> ResolveResult:
    return await resolve_public_share(url)
