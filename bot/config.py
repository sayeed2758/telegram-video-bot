import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")

# Optional private TeraBox session. Never put these in GitHub or Telegram.
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "").strip()
TERABOX_NDUS = os.getenv("TERABOX_NDUS", "").strip()

# Optional owner-controlled gateway.
TERABOX_GATEWAY_URL = os.getenv("TERABOX_GATEWAY_URL", "").strip()

# Optional owner-controlled proxy.
TERABOX_PROXY_URL = os.getenv("TERABOX_PROXY_URL", "").strip()

# Optional owner-controlled TBX Cloudflare proxy. If empty, the documented
# public proxy is used for no-cookie metadata/stream fallback.
TERABOX_TBX_PROXY_URL = os.getenv("TERABOX_TBX_PROXY_URL", "").strip()

# Optional PlayTeraBox API Pro key. Keep this secret and set it only in Render.
TERABOX_API_KEY = os.getenv("TERABOX_API_KEY", "").strip()
TERABOX_API_URL = os.getenv(
    "TERABOX_API_URL",
    "https://api.playterabox.com/api/proxy",
).strip().rstrip("/")

# PlayTeraBox API anti-burst/cache controls. These reduce duplicate API calls
# and help avoid upstream HTTP 429 responses.
TERABOX_API_MIN_INTERVAL_SECONDS = float(
    os.getenv("TERABOX_API_MIN_INTERVAL_SECONDS", "1.5").strip() or "1.5"
)
TERABOX_API_CACHE_TTL_SECONDS = int(
    os.getenv("TERABOX_API_CACHE_TTL_SECONDS", "90").strip() or "90"
)

# Persistent upstream 429 recovery. The bot respects Retry-After when present;
# otherwise it uses an escalating local cooldown to avoid hammering the API.
TERABOX_API_429_FALLBACK_SECONDS = int(
    os.getenv("TERABOX_API_429_FALLBACK_SECONDS", "120").strip() or "120"
)
TERABOX_API_429_MAX_COOLDOWN_SECONDS = int(
    os.getenv("TERABOX_API_429_MAX_COOLDOWN_SECONDS", "900").strip() or "900"
)

# Optional comma-separated public gateway URLs. If empty, Phase 9 uses
# two public gateway formats documented by their respective projects.
# These are fallbacks only; the bot does not send cookies to them.
DEFAULT_DAILY_VIDEO_LIMIT = int(os.getenv("DEFAULT_DAILY_VIDEO_LIMIT", "2").strip() or "2")
RATE_LIMIT_TIMEZONE = os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"

TERABOX_PUBLIC_GATEWAYS = tuple(
    item.strip().rstrip("/")
    for item in os.getenv("TERABOX_PUBLIC_GATEWAYS", "").split(",")
    if item.strip()
)
