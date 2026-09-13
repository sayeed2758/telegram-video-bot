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


def extract_url(text: str) -> str | None:
    for part in text.split():
        candidate = part.strip().strip("<>()[]{}.,!?\"'")
        if is_terabox_url(candidate):
            return candidate
    return None
