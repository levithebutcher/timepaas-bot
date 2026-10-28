import re
import uuid
import logging
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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
    InlineKeyboardMarkup = None
    InlineKeyboardButton = None
from bot.config import MAX_USER_TASKS
from bot.handlers.commands import is_authorized
from bot.core.queue_manager import queue_manager, DownloadTask

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)", re.IGNORECASE)


@Client.on_message(filters.text & filters.private & ~filters.command(["start", "help", "status", "cancelall", "setthumb", "clearthumb", "setcaption"]))
async def message_url_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
        return

    # Extract text from current message or replied message
    target_text = message.text
    if message.reply_to_message and message.reply_to_message.text:
        target_text += "\n" + message.reply_to_message.text

    # Find all valid URLs
    raw_urls = URL_REGEX.findall(target_text)
    clean_urls = []
    seen = set()

    for u in raw_urls:
        if isinstance(u, tuple):
            u = u[0]
        if not u.startswith(("http://", "https://")):
            u = "http://" + u
        if u not in seen:
            seen.add(u)
            clean_urls.append(u)

    if not clean_urls:
        return

    # Check maximum allowed URLs per message (based on MAX_USER_TASKS)
    if len(clean_urls) > MAX_USER_TASKS:
        await message.reply_text(
            f"⚠️ You sent {len(clean_urls)} links. Only the first {MAX_USER_TASKS} will be processed."
        )
        clean_urls = clean_urls[:MAX_USER_TASKS]

    # Check user active + queued limit
    current_active = queue_manager.get_user_active_count(user_id)
    available_slots = MAX_USER_TASKS - current_active

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

    batch_id = str(uuid.uuid4())
    queue_manager.register_batch(
        batch_id=batch_id,
        chat_id=message.chat.id,
        user_id=user_id,
        total_count=len(clean_urls)
    )

    ack_msg = await message.reply_text(
        f"📥 **Accepted {len(clean_urls)} link(s)!**\nInitializing tasks in queue..."
    )

    for url in clean_urls:
        task_id = str(uuid.uuid4())
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✖ Cancel Task", callback_data=f"cancel:{task_id}")]
        ])

        status_msg = await message.reply_text(
            f"⏳ **Task Queued:** `{task_id[:8]}`\n"
            f"🔗 `{url[:50]}...`\n"
            f"State: Waiting for worker slot...",
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
