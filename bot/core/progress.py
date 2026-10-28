import time
import asyncio
import logging
try:
    from pyrogram.errors import FloodWait, MessageNotModified
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    class FloodWait(Exception):
        value = 0
    class MessageNotModified(Exception):
        pass
    InlineKeyboardMarkup = None
    InlineKeyboardButton = None
from bot.config import PROGRESS_UPDATE_INTERVAL

logger = logging.getLogger(__name__)

# Track last edit timestamp per task to prevent Telegram FloodWait
_LAST_UPDATE_TIMES = {}


def format_size(bytes_val: int) -> str:
    """Formats bytes into human-readable B, KB, MB, GB."""
    if not bytes_val or bytes_val <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    val = float(bytes_val)
    while val >= 1024 and idx < len(units) - 1:
        val /= 1024
        idx += 1
    return f"{val:.2f} {units[idx]}"


def format_time(seconds: float) -> str:
    """Formats seconds into readable string (HH:MM:SS or MM:SS)."""
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def generate_bar(current: int, total: int, length: int = 10) -> str:
    """Generates a modern visual progress bar like ▰▰▰▰▱▱▱▱▱▱ 40.0%."""
    if not total or total <= 0:
        return f"{'▱' * length} 0.0%"
    fraction = min(max(current / total, 0.0), 1.0)
    filled = int(fraction * length)
    bar = "▰" * filled + "▱" * (length - filled)
    percent = fraction * 100
    return f"{bar} {percent:.1f}%"


async def update_status_message(
    client,
    chat_id: int,
    message_id: int,
    task_id: str,
    action: str,
    current: int = 0,
    total: int = 0,
    start_time: float = None,
    file_name: str = "",
    force: bool = False,
    is_album: bool = False
):
    """
    Safely edits status message in chat, throttled to 5 seconds per task.
    Displays modern, transparent progress layouts tailored for Normal or Album mode.
    Handles Telegram FloodWait exceptions seamlessly.
    """
    now = time.time()
    last_time = _LAST_UPDATE_TIMES.get(task_id, 0)

    if not force and (now - last_time < PROGRESS_UPDATE_INTERVAL):
        return

    _LAST_UPDATE_TIMES[task_id] = now

    # Calculate speed, elapsed & ETA
    speed_str = "0 B/s"
    eta_str = "--:--"
    elapsed_str = "--:--"
    if start_time and current > 0:
        elapsed = now - start_time
        if elapsed > 0:
            elapsed_str = format_time(elapsed)
            speed = current / elapsed
            speed_str = f"{format_size(int(speed))}/s"
            if total > current and speed > 0:
                eta = (total - current) / speed
                eta_str = format_time(eta)

    bar = generate_bar(current, total)
    curr_str = format_size(current)
    total_str = format_size(total) if total > 0 else "Unknown"

    display_name = file_name if len(file_name) <= 35 else file_name[:32] + "..."
    if not display_name:
        display_name = "Media File"

    if is_album:
        text = (
            f"🎬 **VIDEO ALBUM QUEUE** ➔ `[{task_id[:8]}]`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📂 **Item:** `{display_name}`\n"
            f"📊 **Progress:** `{bar}`\n"
            f"💾 **Size:** `{curr_str}` / `{total_str}`\n"
            f"⚡ **Speed:** `{speed_str}`\n"
            f"⏱ **ETA:** `{eta_str}` • **Elapsed:** `{elapsed_str}`\n"
            f"🎞 **Album Stage:** {action}\n"
            f"ℹ️ *Will be grouped and posted as a Video Album.*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
    else:
        text = (
            f"⚡ **DIRECT LEECH** ➔ `[{task_id[:8]}]`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📂 **File:** `{display_name}`\n"
            f"📊 **Progress:** `{bar}`\n"
            f"💾 **Size:** `{curr_str}` / `{total_str}`\n"
            f"⚡ **Speed:** `{speed_str}`\n"
            f"⏱ **ETA:** `{eta_str}` • **Elapsed:** `{elapsed_str}`\n"
            f"🔄 **Status:** {action}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✖ Cancel Task", callback_data=f"cancel:{task_id}")]
    ])

    for attempt in range(3):
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup
            )
            break
        except MessageNotModified:
            break
        except FloodWait as e:
            logger.warning(f"FloodWait received: sleeping for {e.value}s")
            await asyncio.sleep(e.value + 1)
        except Exception as e:
            logger.debug(f"Failed to edit status message for {task_id}: {e}")
            break
