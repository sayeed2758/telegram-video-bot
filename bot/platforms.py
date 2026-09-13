from urllib.parse import urlparse


SUPPORTED = {
    "terabox": ("terabox.com", "terabox.app", "1024tera.com"),
    "diskwala": ("diskwala.com",),
    "flezen": ("flezen.com",),
}


def normalize_url(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def detect_platform(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None

    host = host.removeprefix("www.")

    for platform, domains in SUPPORTED.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    return None


def is_url(text: str) -> bool:
    try:
        parsed = urlparse(normalize_url(text))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False
