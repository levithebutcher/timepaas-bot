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
        "╭─────────────────────────────────────╮\n"
        "│  ⚡ TIMEPASS LEECH & DOWNLOADER BOT │\n"
        "╰─────────────────────────────────────╯\n"
        "╭─ 🌟 ULTRA-PREMIUM FEATURES\n"
        "│ • 🚀 Multi-Stream Ingress (Aria2 8-conn)\n"
        "│ • 🎬 Double-Buffered Album Pipelining\n"
        "│ • 🧠 Hybrid Headless + DOM Decryption\n"
        "│ • 📦 Auto-Extract ZIP / RAR Archives\n"
        "│ • ✂️ Auto-Split Videos > 1.95 GB\n"
        "│ • 🎛 Real-time Smooth 8-Level Fractional HUD\n"
        "╰─────────────────────────────────────\n"
        "╭─ 💡 QUICK START\n"
        "│ 🔗 Send video links directly, or\n"
        "│ 🎞 Send `/album <links>` for Video Album mode\n"
        "│ 📖 Send `/help` for all commands\n"
        "╰─────────────────────────────────────"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    text = (
        "╭─────────────────────────────────────╮\n"
        "│    📖  C O M M A N D   G U I D E    │\n"
        "╰─────────────────────────────────────╯\n"
        "╭─ 🎮 CORE COMMANDS\n"
        "│ • `<urls>` - Direct Leech (Individual Players)\n"
        "│ • `/album <urls>` - Pipelined Video Album (10-packs)\n"
        "│ • `/status` - Live Queue & Active Tasks HUD\n"
        "│ • `/cancelall` - Cancel all your active tasks\n"
        "╰─────────────────────────────────────\n"
        "╭─ 🎨 CUSTOMIZATION\n"
        "│ • `/setthumb` - Reply to image to set thumbnail\n"
        "│ • `/clearthumb` - Clear thumbnail (auto-generate)\n"
        "│ • `/setcaption <text>` - Custom video caption\n"
        "╰─────────────────────────────────────\n"
        "╭─ 💡 PRO TIPS\n"
        "│ ⚡ Click HUD badges to view live telemetry toasts!\n"
        "│ 🛑 Use the inline cancel button anytime.\n"
        "╰─────────────────────────────────────"
    )
    await message.reply_text(text)


@Client.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return

    active_tasks = [t for t in queue_manager.tasks.values() if t.status not in ("Done", "Failed", "Cancelled")]
    if not active_tasks:
        await message.reply_text(
            "╭─────────────────────────────────────╮\n"
            "│   📭  N O   A C T I V E   T A S K S │\n"
            "╰─────────────────────────────────────╯\n"
            "All queues are clear. Send links to start downloading!"
        )
        return

    lines = [
        "╭─────────────────────────────────────╮",
        "│     📊  A C T I V E   Q U E U E     │",
        "╰─────────────────────────────────────╯"
    ]
    for idx, t in enumerate(active_tasks[:15], 1):
        lines.append(
            f"╭─ [{idx:02d}] 🆔 `{t.id[:8]}` • State: {t.status}\n"
            f"│ 🔗 `{t.url[:45]}...`\n"
            f"╰─────────────────────────────────────"
        )

    await message.reply_text("\n".join(lines))


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
