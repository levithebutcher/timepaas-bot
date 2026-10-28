import logging
from pathlib import Path
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message
except ImportError:
    class _MockFilter:
        def __and__(self, other): return self
        def __invert__(self): return self
    class _MockClient:
        @staticmethod
        def on_message(*args, **kwargs):
            return lambda f: f
    Client = _MockClient
    filters = type("filters", (), {
        "text": _MockFilter(),
        "private": _MockFilter(),
        "command": lambda *args: _MockFilter()
    })
    Message = object
from bot.config import ADMIN_IDS, DOWNLOAD_DIR
from bot.database import set_user_thumb, clear_user_thumb, set_user_caption, get_user_settings
from bot.core.queue_manager import queue_manager

logger = logging.getLogger(__name__)


def is_authorized(user_id: int) -> bool:
    """Checks if user is in ADMIN_IDS. If ADMIN_IDS is empty, grants access."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
        return

    text = (
        "👋 **Welcome to Timepass Leech & Video Downloader Bot!**\n\n"
        "Send me any webpage URL or video link, and I will extract, download, "
        "and upload it to Telegram (up to 2GB)!\n\n"
        "⚡ **Features:**\n"
        "• **Multi-Link Support:** Send up to 10 links in one message.\n"
        "• **Smart Extractor:** yt-dlp, HTML video tags, and Playwright sniffer.\n"
        "• **ZIP & Archive Support:** Auto-extracts videos & photos from archives.\n"
        "• **High Speed:** Resumable chunk downloads with real-time status bars.\n"
        "• **2GB Uploads:** Video player format with thumbnails & duration.\n\n"
        "Type /help to see all available commands."
    )
    await message.reply_text(text)


@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    text = (
        "📖 **Commands & Usage Guide:**\n\n"
        "• **Send Links:** Paste 1 to 10 URLs (one per line) or reply to a message containing links.\n"
        "• `/status` - Check currently active and queued tasks.\n"
        "• `/cancelall` - Cancel all your pending and active downloads.\n"
        "• `/setthumb` - Reply to an image to set your custom video thumbnail.\n"
        "• `/clearthumb` - Clear custom thumbnail and revert to auto-generated thumbs.\n"
        "• `/setcaption <text>` - Set custom caption template (e.g. `/setcaption Downloaded via Bot`).\n\n"
        "💡 **Tip:** Each download gets its own inline **Cancel** button."
    )
    await message.reply_text(text)


@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    active_tasks = [t for t in queue_manager.tasks.values() if t.status not in ("Done", "Failed", "Cancelled")]
    if not active_tasks:
        await message.reply_text("📭 No active or queued tasks right now.")
        return

    lines = [f"📊 **Active & Queued Tasks ({len(active_tasks)}):**\n"]
    for idx, t in enumerate(active_tasks[:15], 1):
        lines.append(f"{idx}. `[{t.id[:8]}]` **State:** {t.status}\n🔗 `{t.url[:45]}...`")

    await message.reply_text("\n\n".join(lines))


@Client.on_message(filters.command("cancelall") & filters.private)
async def cancelall_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    cancelled = queue_manager.cancel_all_for_user(message.from_user.id)
    if cancelled > 0:
        await message.reply_text(f"🛑 Cancelled {cancelled} task(s).")
    else:
        await message.reply_text("ℹ️ You have no active or pending tasks to cancel.")


@Client.on_message(filters.command("setthumb") & filters.private)
async def setthumb_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    replied = message.reply_to_message
    if not replied or not (replied.photo or (replied.document and replied.document.mime_type.startswith("image/"))):
        await message.reply_text("⚠️ Please **reply to an image** with `/setthumb`.")
        return

    thumb_dir = DOWNLOAD_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"thumb_{message.from_user.id}.jpg"

    msg = await message.reply_text("⏳ Saving custom thumbnail...")
    try:
        await client.download_media(replied, file_name=str(thumb_path))
        await set_user_thumb(message.from_user.id, str(thumb_path))
        await msg.edit_text("✅ **Custom thumbnail saved successfully!**")
    except Exception as e:
        logger.error(f"Failed to save thumbnail: {e}")
        await msg.edit_text(f"❌ Failed to save thumbnail: `{e}`")


@Client.on_message(filters.command("clearthumb") & filters.private)
async def clearthumb_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    await clear_user_thumb(message.from_user.id)
    await message.reply_text("🗑️ Custom thumbnail cleared. Default video thumbnails will be used.")


@Client.on_message(filters.command("setcaption") & filters.private)
async def setcaption_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("⚠️ Usage: `/setcaption Your Custom Caption Here`")
        return

    caption = parts[1].strip()
    await set_user_caption(message.from_user.id, caption)
    await message.reply_text(f"✅ **Custom caption template saved:**\n`{caption}`")
