import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token & Admin Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8929349073"))

# Domain & Platform Configuration
DOMAIN = os.getenv("DOMAIN", "muellfach.de")
MUELLFACH_BASE_URL = os.getenv("MUELLFACH_BASE_URL", f"https://www.{DOMAIN}")
MUELLFACH_AJAX_URL = f"{MUELLFACH_BASE_URL}/ajax.php"
MUELLFACH_API_V1_URL = f"{MUELLFACH_BASE_URL}/api/v1"
MUELLFACH_SYNC_URL = f"{MUELLFACH_AJAX_URL}?action=sync"
MUELLFACH_API_URL = MUELLFACH_AJAX_URL

# Database Path (configurable for persistent volume on Render/Railway)
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "mailfuetch.db"))

# Polling Interval (in seconds - optimized for ultra-fast OTP forwarding)
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.5"))

# Email Retention Days (10 days as requested)
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "10"))
