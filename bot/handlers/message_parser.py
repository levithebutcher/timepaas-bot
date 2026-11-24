import re
import uuid
import asyncio
import logging
import html
from urllib.parse import urlparse
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    class _MockFilter:
        def __and__(self, other): return self
        def __or__(self, other): return self
        def __invert__(self): return self
    class _MockClient:
        @staticmethod
        def on_message(*args, **kwargs):
            return lambda f: f
    Client = _MockClient
    filters = type("filters", (), {
        "text": _MockFilter(),
        "caption": _MockFilter(),
        "private": _MockFilter(),
        "command": lambda *args: _MockFilter(),
        "regex": lambda *args: _MockFilter(),
    })
    Message = object
    InlineKeyboardMarkup = None
    InlineKeyboardButton = None
from bot.config import MAX_USER_TASKS
from bot.handlers.commands import is_authorized
from bot.core.queue_manager import queue_manager, DownloadTask
from bot.core.sorter import natural_sort_urls

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)", re.IGNORECASE)


def get_canonical_url_key(url: str) -> str:
    """Computes a normalized key for video URLs to deduplicate identical videos/truncated links."""
    u_clean = url.strip()
    parsed = urlparse(u_clean)
    netloc = parsed.netloc.lower().split(":")[0]
    path = parsed.path
    # Streamtape (e.g. /v/file_id/...)
    if "streamtape" in netloc or "strtape" in netloc or "watchadsontape" in netloc:
        m = re.search(r"/v/([a-zA-Z0-9]+)", path)
        if m:
            return f"streamtape:{m.group(1)}"
    # Uqload (e.g. /embed-file_id.html or /file_id.html)
    if "uqload" in netloc:
        m = re.search(r"(?:embed-)?([a-zA-Z0-9]+)", path)
        if m:
            return f"uqload:{m.group(1)}"
    # Abstream (e.g. /embed-file_id.html or /file_id.html)
    if "abstream" in netloc:
        m = re.search(r"(?:embed-)?([a-zA-Z0-9]+)", path)
        if m:
            return f"abstream:{m.group(1)}"
    # Vidara / Gasobni (e.g. /file_id)
    if "vidara" in netloc or "gasobni" in netloc:
        parts = [p for p in path.split("/") if p and p not in ("v", "e", "embed", "download")]
        if parts:
            return f"vidara:{parts[0]}"
    # Mixdrop (e.g. /e/file_id or /f/file_id)
    if any(k in netloc for k in ("mixdrop", "mdzsmutpcvykb", "mxcontent")):
        m = re.search(r"/(?:e|f)/([a-zA-Z0-9]+)", path)
        if m:
            return f"mixdrop:{m.group(1)}"
    # Streamcash (e.g. /embed/file_id)
    if "streamcash" in netloc:
        m = re.search(r"/(?:embed/)?([a-zA-Z0-9\-]+)", path)
        if m:
            return f"streamcash:{m.group(1)}"
    # Livecamrips (e.g. /video/video_id)
    if "livecamrips" in netloc:
        m = re.search(r"/video/([a-zA-Z0-9]+)", path)
        if m:
            return f"livecamrips:{m.group(1)}"
    # LuluStream / LuluVid (e.g. /file_id or /e/file_id)
    if any(k in netloc for k in ("luluvdo", "luluvideo", "lulustream", "luluvid", "lplaygo")):
        parts = [p for p in path.split("/") if p and p not in ("v", "e", "embed", "d")]
        if parts:
            file_id = parts[0].rsplit(".", 1)[0]
            return f"lulustream:{file_id}"
    # Thotplay (e.g. /e/file_id or /file_id)
    if "thotplay" in netloc:
        parts = [p for p in path.split("/") if p and p not in ("e", "v", "d", "embed")]
        if parts:
            return f"thotplay:{parts[0]}"
    return u_clean


async def process_submitted_urls(client: Client, message: Message, target_text: str, is_album: bool = None):
    """Processes URL extraction, queue limit checking, and enqueuing tasks."""
    user_id = message.from_user.id if getattr(message, "from_user", None) else message.chat.id

    # Find all valid URLs and deduplicate truncated duplicates by canonical file ID
    raw_urls = URL_REGEX.findall(target_text)
    best_urls_by_key = {}
    key_order = []

    for u in raw_urls:
        if isinstance(u, tuple):
            u = u[0]
        if not u.startswith(("http://", "https://")):
            u = "http://" + u
        ck = get_canonical_url_key(u)
        if ck not in best_urls_by_key:
            best_urls_by_key[ck] = u
            key_order.append(ck)
        else:
            # Keep the longer, more complete URL (with filename/extension)
            if len(u) > len(best_urls_by_key[ck]):
                best_urls_by_key[ck] = u

    clean_urls = [best_urls_by_key[k] for k in key_order]

    if not clean_urls:
        return

    # Intelligent natural sort with fallback to original submission order
    clean_urls = natural_sort_urls(clean_urls)

    # Auto-detect album mode: if multiple links sent together, automatically group into video album!
    if is_album is None:
        is_album = len(clean_urls) > 1

    # Check maximum allowed URLs per message (album mode supports larger batches up to 100)
    effective_max_tasks = max(MAX_USER_TASKS, 100) if is_album else MAX_USER_TASKS
    if len(clean_urls) > effective_max_tasks:
        await message.reply_text(
            f"⚠️ You sent {len(clean_urls)} links. Only the first {effective_max_tasks} will be processed."
        )
        clean_urls = clean_urls[:effective_max_tasks]

    # Check user active + queued limit
    current_active = queue_manager.get_user_active_count(user_id)
    available_slots = effective_max_tasks - current_active

    if available_slots <= 0:
        await message.reply_text(
            f"🚫 **Queue Limit Exceeded:** You already have {current_active} active or queued tasks. "
            f"Please wait for them to finish or use `/cancelall`."
        )
        return

    if len(clean_urls) > available_slots:
        await message.reply_text(
            f"⚠️ Queue limit: You can only queue {available_slots} more task(s). "
            f"Processing first {available_slots} links."
        )
        clean_urls = clean_urls[:available_slots]

    # --- SPECIALIZED ALBUM PIPELINE MODE (No chat clutter, 1 persistent dashboard) ---
    if is_album:
        batch_id = str(uuid.uuid4())
        status_text = (
            f"<blockquote>"
            f"🎬 <b>VIDEO ALBUM QUEUE</b>\n"
            f"📦 <b>Accepted:</b> {len(clean_urls)} video links\n"
            f"⏳ <i>Starting download & upload pipeline...</i>"
            f"</blockquote>"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Cancel Entire Album", callback_data=f"cancel_batch:{batch_id}")]
        ]) if InlineKeyboardMarkup and InlineKeyboardButton else None

        status_msg = await message.reply_text(status_text, reply_markup=reply_markup)

        batch = queue_manager.register_batch(
            batch_id=batch_id,
            chat_id=message.chat.id,
            user_id=user_id,
            total_count=len(clean_urls),
            is_album=True,
            status_msg_id=status_msg.id,
            user_msg_id=getattr(message, "id", 0)
        )

        asyncio.create_task(
            queue_manager.process_album_pipeline(
                client=client,
                batch=batch,
                urls=clean_urls,
                status_msg_id=status_msg.id
            )
        )
        return

    # --- DIRECT LEECH MODE (Individual video players with individual statuses) ---
    batch_id = str(uuid.uuid4())
    queue_manager.register_batch(
        batch_id=batch_id,
        chat_id=message.chat.id,
        user_id=user_id,
        total_count=len(clean_urls),
        is_album=False,
        user_msg_id=getattr(message, "id", 0)
    )

    ack_msg = await message.reply_text(
        f"<blockquote>📥 <b>Accepted {len(clean_urls)} link(s)</b>\n⏳ Initializing queue...</blockquote>"
    )

    for url in clean_urls:
        task_id = str(uuid.uuid4())

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Cancel Task", callback_data=f"cancel:{task_id}")]
        ]) if InlineKeyboardMarkup and InlineKeyboardButton else None

        safe_url = html.escape(url[:45])
        status_text = (
            f"<blockquote>"
            f"⚡ <b>TIMEPASS LEECH</b>\n"
            f"🔗 <code>{safe_url}...</code>\n"
            f"⏳ <i>Waiting for worker slot in queue...</i>"
            f"</blockquote>"
        )

        status_msg = await message.reply_text(
            status_text,
            reply_markup=reply_markup
        )

        task = DownloadTask(
            id=task_id,
            user_id=user_id,
            chat_id=message.chat.id,
            url=url,
            status_msg_id=status_msg.id,
            batch_id=batch_id
        )

        await queue_manager.enqueue_task(task)

    try:
        await ack_msg.delete()
    except Exception:
        pass


@Client.on_message(filters.command("album") & filters.private)
async def album_command_handler(client: Client, message: Message):
    user_id = message.from_user.id if getattr(message, "from_user", None) else message.chat.id
    if not is_authorized(user_id):
        await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
        return

    target_text = message.text or message.caption or ""
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if replied_text:
            target_text += "\n" + replied_text

    raw_urls = URL_REGEX.findall(target_text)
    if not raw_urls:
        await message.reply_text(
            "ℹ️ **Album Mode Usage:**\n\n"
            "Send video links along with the command:\n"
            "`/album <url1> <url2> ...`\n\n"
            "Or reply to a message containing links with `/album`.\n\n"
            "All downloaded videos will be uploaded together in an interactive Video Album (up to 10 videos per album)!"
        )
        return

    await process_submitted_urls(client, message, target_text, is_album=True)


@Client.on_message((filters.text | filters.caption) & filters.private & ~filters.regex(r"^/"))
async def message_url_handler(client: Client, message: Message):
    user_id = message.from_user.id if getattr(message, "from_user", None) else message.chat.id
    if not is_authorized(user_id):
        await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
        return

    # Extract text from current message or replied message (handles both plain text & media captions)
    target_text = message.text or message.caption or ""
    if target_text.strip().startswith("/"):
        return

    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if replied_text:
            target_text += "\n" + replied_text

    await process_submitted_urls(client, message, target_text, is_album=None)
