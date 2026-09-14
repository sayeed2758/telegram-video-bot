from urllib.parse import urlparse

TERABOX_HOSTS = {
    "terabox.com",
    "www.terabox.com",
    "terabox.app",
    "www.terabox.app",
    "1024tera.com",
    "www.1024tera.com",
    "1024terabox.com",
    "www.1024terabox.com",
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


def is_terabox_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    if parsed.scheme.lower() not in {"http", "https"}:
        return False

    return parsed.hostname is not None and parsed.hostname.lower() in TERABOX_HOSTS


def extract_urls(text: str) -> list[str]:
    """Extract every unique supported TeraBox URL from a message, in order."""
    urls: list[str] = []
    seen: set[str] = set()

    for part in text.split():
        candidate = part.strip().strip("<>()[]{}.,!?\"'")
        if not is_terabox_url(candidate):
            continue
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    return urls


def extract_url(text: str) -> str | None:
    """Backward-compatible helper returning the first supported URL."""
    urls = extract_urls(text)
    return urls[0] if urls else None
