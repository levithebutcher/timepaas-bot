import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from candidate directories (handles Colab /content paths)
ROOT_DIR = Path(__file__).resolve().parent.parent
for env_candidate in [
    ROOT_DIR / ".env",
    Path.cwd() / ".env",
    Path("/content/timepaas-bot/.env"),
    Path("/content/.env")
]:
    if env_candidate.exists():
        load_dotenv(env_candidate, override=True)

# Telegram API & Bot Token
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if API_ID:
    try:
        API_ID = int(API_ID)
    except ValueError:
        API_ID = None

# Admin & Authorized Users (set of ints)
raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set()
for item in raw_admins.replace(";", ",").split(","):
    clean_item = item.strip()
    if clean_item.isdigit():
        ADMIN_IDS.add(int(clean_item))

# Concurrency & Queue Configuration
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
MAX_USER_TASKS = int(os.getenv("MAX_USER_TASKS", "10"))
PROGRESS_UPDATE_INTERVAL = float(os.getenv("PROGRESS_UPDATE_INTERVAL", "5.0"))
MIN_FREE_DISK_GB = float(os.getenv("MIN_FREE_DISK_GB", "3.0"))

# Paths & Directories
DOWNLOAD_DIR = ROOT_DIR / os.getenv("DOWNLOAD_DIR", "downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = ROOT_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

EXTRACT_DIR = ROOT_DIR / "extracted"
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = ROOT_DIR / "bot_database.db"

# 1.95 GiB size limit for Telegram Bot API uploads (safety buffer below 2000 MiB)
MAX_SPLIT_SIZE_BYTES = int(1.95 * 1024 * 1024 * 1024)

# Optional Streamtape API Credentials
STREAMTAPE_LOGIN = os.getenv("STREAMTAPE_LOGIN", "").strip().strip('"\'')
STREAMTAPE_KEY = os.getenv("STREAMTAPE_KEY", "").strip().strip('"\'')

# Headers for browser spoofing
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
