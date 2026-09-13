import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "telegram-webhook").strip("/")

# Keep these private. Do not put them in GitHub or Telegram.
TERABOX_COOKIE = os.getenv("TERABOX_COOKIE", "").strip()
TERABOX_NDUS = os.getenv("TERABOX_NDUS", "").strip()

# Optional: your own trusted TeraBox gateway.
TERABOX_GATEWAY_URL = os.getenv("TERABOX_GATEWAY_URL", "").strip()

# Optional: an explicitly configured unified proxy.
TERABOX_PROXY_URL = os.getenv("TERABOX_PROXY_URL", "").strip()
