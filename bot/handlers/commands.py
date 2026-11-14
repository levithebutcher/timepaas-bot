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
        await message.reply_text("⛔ <b>Access Denied.</b> You are not authorized to use this bot.")
        return

    text = (
        "<blockquote>"
        "⚡ <b>TIMEPASS LEECH & DOWNLOADER</b>\n\n"
        "Send any video link to download and upload directly to Telegram!\n\n"
        "• <b>Single link:</b> Direct video player upload\n"
        "• <b>Multiple links:</b> Auto-grouped into video albums (up to 10 per album)\n"
        "• <b>Fast Multi-Stream:</b> 32-split Aria2 turbo engine\n"
        "• <b>Auto-Split:</b> Automatically splits videos &gt; 1.95 GB\n\n"
        "📖 <i>Send /help for full command guide</i>"
        "</blockquote>"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    text = (
        "<blockquote>"
        "📖 <b>COMMAND GUIDE</b>\n\n"
        "• <code>&lt;link&gt;</code> — Download & upload single video\n"
        "• <code>&lt;link1&gt; &lt;link2&gt;...</code> — Auto-grouped video album\n"
        "• <code>/album &lt;links&gt;</code> — Force album mode\n"
        "• <code>/status</code> — View active tasks\n"
        "• <code>/cancelall</code> — Cancel all active tasks\n"
        "• <code>/setthumb</code> — Reply to image to set thumbnail\n"
        "• <code>/clearthumb</code> — Reset thumbnail\n"
        "• <code>/setcaption &lt;text&gt;</code> — Set custom caption"
        "</blockquote>"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    active_tasks = [t for t in queue_manager.tasks.values() if t.status not in ("Done", "Failed", "Cancelled")]
    if not active_tasks:
        await message.reply_text(
            "<blockquote>"
            "📭 <b>NO ACTIVE TASKS</b>\n"
            "All queues are clear. Send links to start downloading!"
            "</blockquote>"
        )
        return

    items = []
    for idx, t in enumerate(active_tasks[:10], 1):
        items.append(f"• <b>[{idx:02d}]</b> <code>{t.id[:8]}</code> — <i>{t.status}</i>\n  <code>{t.url[:40]}...</code>")

    text = (
        f"<blockquote>"
        f"📊 <b>ACTIVE QUEUE ({len(active_tasks)} Tasks)</b>\n\n"
        + "\n\n".join(items) +
        f"</blockquote>"
    )
    await message.reply_text(text)


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
