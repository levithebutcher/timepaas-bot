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
    class InlineKeyboardButton:
        def __init__(self, text="", callback_data=""):
            self.text = text
            self.callback_data = callback_data
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []
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


def generate_smooth_bar(
    current: int,
    total: int,
    length: int = 10,
    filled_char: str = "█",
    empty_char: str = "░"
) -> str:
    """
    High-Precision 8-Level Fractional Unicode Progress Bar.
    Renders sub-block characters [░, ▏, ▎, ▍, ▌, ▋, ▊, ▉, █] for ultra-smooth 1% progression.
    e.g. [███████▎░░] 73.2%
    """
    if length < 1:
        length = 10

    if not total or total <= 0:
        return f"{empty_char * length} 0.0%"

    fraction = min(max(current / total, 0.0), 1.0)
    percent = fraction * 100
    if fraction >= 1.0:
        return f"{filled_char * length} 100.0%"

    sub_blocks = [empty_char, "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
    total_sub_units = int(fraction * length * 8)
    full_blocks = total_sub_units // 8
    sub_index = total_sub_units % 8

    bar = filled_char * full_blocks
    if full_blocks < length:
        bar += sub_blocks[sub_index]
        bar += empty_char * (length - full_blocks - 1)
    return f"{bar} {percent:.1f}%"


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

    smooth_bar = generate_smooth_bar(current, total, length=10)
    curr_str = format_size(current)
    total_str = format_size(total) if total > 0 else "Unknown"

    display_name = file_name if len(file_name) <= 35 else file_name[:32] + "..."
    if not display_name:
        display_name = "Media File"

    if is_album:
        text = (
            f"╭─────────────────────────────────────╮\n"
            f"│   🎬  V I D E O   A L B U M   H U D  │\n"
            f"╰─────────────────────────────────────╯\n"
            f"╭─ 📂 ITEM IDENTIFIER\n"
            f"│ 🏷 Name: `{display_name}`\n"
            f"│ 🆔 Task: `{task_id[:8]}` • 🎞 *Album Mode*\n"
            f"╰─────────────────────────────────────\n"
            f"╭─ 📈 REAL-TIME PROGRESSION\n"
            f"│ 📊 `{smooth_bar}`\n"
            f"│ 💾 `{curr_str}` / `{total_str}`\n"
            f"│ ⚡ `{speed_str}`  •  ⏱ ETA: `{eta_str}`\n"
            f"╰─────────────────────────────────────\n"
            f"╭─ ⚙️ ENGINE STATUS\n"
            f"│ {action}\n"
            f"╰─────────────────────────────────────"
        )
    else:
        text = (
            f"╭─────────────────────────────────────╮\n"
            f"│   ⚡  T I M E P A S S   L E E C H   │\n"
            f"╰─────────────────────────────────────╯\n"
            f"╭─ 📂 MEDIA TARGET\n"
            f"│ 🏷 Name: `{display_name}`\n"
            f"│ 🆔 Task: `{task_id[:8]}` • 🎥 *Video Player*\n"
            f"╰─────────────────────────────────────\n"
            f"╭─ 📈 REAL-TIME TRANSMISSION\n"
            f"│ 📊 `{smooth_bar}`\n"
            f"│ 💾 `{curr_str}` / `{total_str}`\n"
            f"│ ⚡ `{speed_str}`  •  ⏱ ETA: `{eta_str}`\n"
            f"╰─────────────────────────────────────\n"
            f"╭─ ⚙️ ACTIVE PROCESS\n"
            f"│ {action}\n"
            f"╰─────────────────────────────────────"
        )

    buttons = []
    # Real-time telemetry badges
    info_row = []
    if speed_str and speed_str != "0 B/s":
        info_row.append(InlineKeyboardButton(f"⚡ {speed_str}", callback_data=f"hud:speed:{task_id}"))
    if eta_str and eta_str != "--:--":
        info_row.append(InlineKeyboardButton(f"⏱ {eta_str}", callback_data=f"hud:eta:{task_id}"))
    if curr_str and curr_str != "0 B":
        info_row.append(InlineKeyboardButton(f"💾 {curr_str}", callback_data=f"hud:size:{task_id}"))
    if info_row:
        buttons.append(info_row)

    buttons.append([InlineKeyboardButton("🛑 Cancel Task", callback_data=f"cancel:{task_id}")])
    reply_markup = InlineKeyboardMarkup(buttons) if InlineKeyboardMarkup and InlineKeyboardButton else None

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
        if isinstance(current_dl, dict) and "active_list" in current_dl:
            active_list = current_dl["active_list"]
            pack_tot = current_dl.get("chunk_total", len(active_list))
            completed_in_pack = current_dl.get("completed_in_pack", 0)
            lines = [f"📥 **DOWNLOADING:** Pack [{completed_in_pack}/{pack_tot} Ready]"]
            if active_list:
                for dl_item in active_list[:2]:
                    fn = dl_item.get("file_name", "Media")
                    if len(fn) > 28:
                        fn = fn[:25] + "..."
                    cb = dl_item.get("current", 0)
                    tb = dl_item.get("total", 0)
                    sp = dl_item.get("speed_str", "--")
                    bar = generate_smooth_bar(cb, tb, length=8)
                    lines.append(f"   ▶ `{fn}`\n     `{bar}` ({format_size(cb)}) • ⚡ `{sp}`")
            else:
                lines.append("   ⏳ <i>Finalizing pack downloads...</i>")
            dl_text = "\n".join(lines)
        else:
            file_name = current_dl.get("file_name", "Media")
            if len(file_name) > 35:
                file_name = file_name[:32] + "..."
            curr_b = current_dl.get("current", 0)
            tot_b = current_dl.get("total", 0)
            speed = current_dl.get("speed_str", "--")
            eta = current_dl.get("eta_str", "--")
            pack_idx = current_dl.get("item_num", 1)
            pack_tot = current_dl.get("chunk_total", 1)
            bar = generate_smooth_bar(curr_b, tot_b, length=10)
            dl_text = (
                f"   ▶ `{file_name}` [Pack {pack_idx}/{pack_tot}]\n"
                f"     `{bar}` ({format_size(curr_b)} / {format_size(tot_b)})\n"
                f"     ⚡ `{speed}`  •  ⏱ ETA: `{eta}`"
            )
    else:
        if completed_files >= total_files and total_files > 0:
            dl_text = "   ✅ <i>All downloads completed!</i>"
        else:
            dl_text = "   ⏳ <i>Preparing next 10-pack chunk...</i>"

    overall_pct = (completed_files / total_files * 100.0) if total_files > 0 else 0.0
    smooth_overall = generate_smooth_bar(completed_files, total_files, length=12)

    text = (
        f"╭─────────────────────────────────────╮\n"
        f"│   🎬  A L B U M   P I P E L I N E   │\n"
        f"╰─────────────────────────────────────╯\n"
        f"╭─ 📤 EGRESS STAGE\n"
        f"{up_text}\n"
        f"╰─────────────────────────────────────\n"
        f"╭─ 📥 INGRESS STAGE\n"
        f"{dl_text}\n"
        f"╰─────────────────────────────────────\n"
        f"╭─ 📊 PIPELINE TELEMETRY\n"
        f"│ 📈 `{smooth_overall}`\n"
        f"│ • Processed: {completed_files}/{total_files} Files ({overall_pct:.1f}%)\n"
        f"│ • Albums: {uploaded_albums}/{total_albums} Delivered to Telegram\n"
        f"│ • Host Disk: {free_gb:.1f} GB Free • Multi-Stream: ACTIVE\n"
        f"╰─────────────────────────────────────"
    )

    alb_buttons = [
        [
            InlineKeyboardButton(f"📊 {overall_pct:.1f}% Ready", callback_data=f"hud:batch_prog:{batch_id}"),
            InlineKeyboardButton(f"💾 {free_gb:.1f} GB Free", callback_data=f"hud:batch_disk:{batch_id}"),
            InlineKeyboardButton(f"🎞 {uploaded_albums}/{total_albums} Albums", callback_data=f"hud:batch_albs:{batch_id}")
        ],
        [InlineKeyboardButton("🛑 Cancel Entire Album", callback_data=f"cancel_batch:{batch_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(alb_buttons) if InlineKeyboardMarkup and InlineKeyboardButton else None

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
