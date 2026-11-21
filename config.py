import os

# Telegram Bot Token (Get it from @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE"))
TOKEN = BOT_TOKEN

# Admin Telegram IDs (List of integer user IDs)
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).split(",") if x.strip().isdigit()
]
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0

# VookMail API Key (Optional: our PoW engine solves it automatically if empty)
VOOK_API_KEY = os.getenv("VOOK_API_KEY", os.getenv("API_KEY", ""))
API_KEY = VOOK_API_KEY

# Base URL for VookMail REST API
VOOK_BASE_URL = "https://www.vookmail.com/api/v1"
BASE_URL = VOOK_BASE_URL

# Database: Supabase PostgreSQL URL (or empty for local SQLite)
# Example: postgresql://postgres.xxxx:your_password@aws-0-region.pooler.supabase.com:6543/postgres
DATABASE_URL = os.getenv("DATABASE_URL", os.getenv("DB_URL", ""))
DB_URL = DATABASE_URL

# Local SQLite fallback filename
DB_PATH = os.path.join(os.path.dirname(__file__), "vookmail_bot.db")

# Default Support Link or Username
DEFAULT_SUPPORT = "@YourSupportUsername"
