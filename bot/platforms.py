from urllib.parse import urlparse


SUPPORTED = {
    "terabox": (
        "terabox.com",
        "terabox.app",
        "1024tera.com",
        "1024terabox.com",
        "teraboxshare.com",
        "teraboxlink.com",
        "terafileshare.com",
        "terasharefile.com",
        "terasharelink.com",
    ),
    "diskwala": ("diskwala.com",),
    "flezen": ("flezen.com",),
}


def normalize_url(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def detect_platform(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        for platform, domains in SUPPORTED.items():
            for domain in domains:
                if host == domain or host.endswith("." + domain):
                    return platform
    except Exception:
        return None
    return None


def is_url(text: str) -> bool:
    try:
        parsed = urlparse((text or "").strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False
