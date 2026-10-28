# ⚡ Timepass Multi-Link Video Downloader & Leech Bot

An asynchronous Telegram bot built with **Pyrogram (MTProto)** that extracts direct video links from web pages, downloads them, and uploads them to Telegram (up to 2GB) with full multi-link concurrency, queue management, and ZIP archive extraction.

Designed to run seamlessly on **Google Colab Free Tier**, **Linux/VPS**, and **Windows**.

---

## 🌟 Key Features

- **Multi-Link Ingestion:** Send up to 10 URLs in a single message (one per line) or reply to a message containing links.
- **Smart Queue & Concurrency:** Concurrency controlled via `asyncio.Semaphore(MAX_CONCURRENT_TASKS)` (default: 3). Remaining tasks wait in queue and automatically start when a slot frees up.
- **Sequential Link Extraction:**
  1. `yt-dlp` (fastest & handles thousands of sites)
  2. `BeautifulSoup4` (HTML `<video>`, `<source>`, and direct download anchors)
  3. `Playwright` (headless Chromium network sniffer to intercept dynamic streaming URLs)
  4. Automatic `ffmpeg` remuxing of `.m3u8` manifests into `.mp4` containers.
- **ZIP & Archive Support:** Automatically extracts `.zip`, `.rar`, and `.7z` archives. Uploads enclosed videos as video players and photos as grouped Telegram Media Albums (10 photos per album). If an archive contains **more than 50 images**, the bot presents interactive buttons asking whether you want:
  1. `🖼️ Images Only` (uploaded to chat in albums)
  2. `📦 ZIP File Only` (uploaded as raw document)
  3. `✨ Both (ZIP + Images)` (uploaded both ways)
  Password-protected archives are safely uploaded as raw documents.
- **2GB Uploads with Auto-Split:** Video files under 1.95 GB are uploaded directly with auto-generated thumbnails and duration. Files exceeding 1.95 GB are automatically split into parts via `ffmpeg` without re-encoding quality loss.
- **FloodWait-Safe Live Progress:** Throttled status updates (every 5 seconds) displaying progress bar, speed, ETA, and size, with an inline **Cancel** button per task.
- **Batch Summaries:** Sends a final summary report once all links in a batch finish (`X finished, Y failed, Z cancelled`).

---

## 🤖 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Check bot status and welcome instructions |
| `/help` | Detailed usage guide and supported link formats |
| `/status` | View all currently active and queued downloads |
| `/cancelall` | Cancel all active and queued tasks for your account |
| `/setthumb` | Reply to any image to set your custom video thumbnail |
| `/clearthumb` | Revert to auto-generated video thumbnails |
| `/setcaption <text>` | Set a custom caption template for uploaded files |

---

## 🚀 Running on Google Colab (Free Tier)

A pre-filled notebook `Timepass_Bot_Colab.ipynb` is included in your local setup:
1. Open [Google Colab](https://colab.research.google.com/).
2. Click **Upload** and select `Timepass_Bot_Colab.ipynb`.
3. Run the cells in order:
   - **Cell 1:** Clones/pulls the latest commit from GitHub automatically.
   - **Cell 2:** Installs `ffmpeg`, Python packages, and Playwright Chromium.
   - **Cell 3:** Pre-configured credentials setup.
   - **Cell 4:** Activates the **Dual-Layer Anti-Sleep Suite** (Browser JavaScript keep-alive + Kernel pulse thread).
   - **Cell 5:** Starts the bot with live streaming terminal logs.

---

## 💻 Local Setup (Windows / Linux)

### 1. Prerequisites
- Python 3.10+
- `ffmpeg` and `ffprobe` installed and added to your system `PATH`.

### 2. Installation
```bash
git clone https://github.com/levithebutcher/timepaas-bot.git
cd timepaas-bot
pip install -r requirements.txt
playwright install chromium --with-deps
```

### 3. Configuration
Copy `.env.example` to `.env` and fill in your Telegram API credentials:
```ini
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
ADMIN_IDS=your_telegram_id
MAX_CONCURRENT_TASKS=3
MAX_USER_TASKS=10
```

### 4. Run the Bot
```bash
python -m bot.main
```

---

## 🔒 Security & Privacy

This repository uses automated credential checking and strict `.gitignore` rules. Sensitive files (`.env`, session files, `.ipynb` notebooks containing user keys, and downloaded data) are strictly excluded from git tracking.
