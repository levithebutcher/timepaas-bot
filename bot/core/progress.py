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


def generate_bar(
    current: int,
    total: int,
    length: int = 10,
    mascot: str = "🏃",
    filled_char: str = "▰",
    empty_char: str = "▱"
) -> str:
    """
    Generates a mascot visual progress bar with a runner emoji (🏃),
    e.g. ▰▰▰▰🏃▱▱▱▱▱ 40.0%.
    """
    if length < 1:
        length = 10

    track_len = max(length - 1, 0)
    if not total or total <= 0:
        bar = mascot + empty_char * track_len
        return f"{bar} 0.0%"

    fraction = min(max(current / total, 0.0), 1.0)
    percent = fraction * 100

    filled = min(int(fraction * length), track_len)
    empty = track_len - filled

    bar = (filled_char * filled) + mascot + (empty_char * empty)
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


async def update_album_pipeline_dashboard(
    client,
    chat_id: int,
    message_id: int,
    batch_id: str,
    total_files: int,
    completed_files: int,
    total_albums: int,
    uploaded_albums: int,
    current_dl: dict = None,
    current_up: dict = None,
    force: bool = False
):
    """
    Safely edits the single persistent Album Pipeline dashboard message in chat.
    Displays dual-track progress (concurrent upload and download), overall stats, and free disk.
    Throttled to prevent Telegram FloodWait.
    """
    from bot.core.cleaner import get_free_disk_gb

    now = time.time()
    batch_key = f"batch_{batch_id}"
    last_time = _LAST_UPDATE_TIMES.get(batch_key, 0)

    if not force and (now - last_time < PROGRESS_UPDATE_INTERVAL):
        return

    _LAST_UPDATE_TIMES[batch_key] = now
    free_gb = get_free_disk_gb()

    # Upload section
    if current_up:
        alb_num = current_up.get("album_num", 1)
        alb_cnt = current_up.get("count", 1)
        alb_status = current_up.get("status", "Transmitting media group to Telegram...")
        up_text = (
            f"📤 **UPLOADING:** Album {alb_num}/{total_albums} ({alb_cnt} videos)\n"
            f"   ⏳ <i>{alb_status}</i>"
        )
    else:
        if uploaded_albums >= total_albums and total_albums > 0:
            up_text = "📤 **UPLOADING:** ✅ <i>All albums uploaded!</i>"
        else:
            up_text = "📤 **UPLOADING:** <i>Waiting for first download pack to complete...</i>"

    # Download section
    if current_dl:
        file_name = current_dl.get("file_name", "Media")
        if len(file_name) > 35:
            file_name = file_name[:32] + "..."
        curr_b = current_dl.get("current", 0)
        tot_b = current_dl.get("total", 0)
        speed = current_dl.get("speed_str", "--")
        eta = current_dl.get("eta_str", "--")
        pack_idx = current_dl.get("item_num", 1)
        pack_tot = current_dl.get("chunk_total", 1)
        bar = generate_bar(curr_b, tot_b)
        dl_text = (
            f"📥 **DOWNLOADING:** Pack [{pack_idx}/{pack_tot}]\n"
            f"   ▶ `{file_name}`\n"
            f"   📊 `{bar}`\n"
            f"   💾 `{format_size(curr_b)}` / `{format_size(tot_b)}` • ⚡ `{speed}` • ⏱ `{eta}`"
        )
    else:
        if completed_files >= total_files and total_files > 0:
            dl_text = "📥 **DOWNLOADING:** ✅ <i>All downloads completed!</i>"
        else:
            dl_text = "📥 **DOWNLOADING:** <i>Preparing next chunk...</i>"

    text = (
        f"🎬 **[ALBUM PIPELINE ACTIVE]** ➔ `[{batch_id[:8]}]`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{up_text}\n\n"
        f"{dl_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Overall Status:** {completed_files}/{total_files} Files Processed • {uploaded_albums}/{total_albums} Albums Uploaded\n"
        f"💾 **Free Disk Space:** {free_gb:.1f} GB\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✖ Cancel Entire Album", callback_data=f"cancel_batch:{batch_id}")]
    ]) if InlineKeyboardMarkup and InlineKeyboardButton else None

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
            logger.warning(f"FloodWait received in album dashboard: sleeping {e.value}s")
            await asyncio.sleep(e.value + 1)
        except Exception as e:
            logger.debug(f"Failed to edit album dashboard for {batch_id}: {e}")
            break
