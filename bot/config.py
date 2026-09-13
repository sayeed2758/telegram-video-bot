import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")

# Optional TeraBox session credentials. Keep these private.
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "").strip()
TERABOX_NDUS = os.getenv("TERABOX_NDUS", "").strip()

# Public proxy documented by the current terabox-gateway-v3 project.
# It can be overridden without changing code.
TERABOX_PROXY_URL = os.getenv(
    "TERABOX_PROXY_URL",
    "https://tbx-proxy.shakir-ansarii075.workers.dev/",
).strip()
