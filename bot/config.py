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

# Optional comma-separated public gateway URLs. If empty, Phase 9 uses
# two public gateway formats documented by their respective projects.
# These are fallbacks only; the bot does not send cookies to them.
TERABOX_PUBLIC_GATEWAYS = tuple(
    item.strip().rstrip("/")
    for item in os.getenv("TERABOX_PUBLIC_GATEWAYS", "").split(",")
    if item.strip()
)
