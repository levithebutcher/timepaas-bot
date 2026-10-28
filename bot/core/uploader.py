import os
import asyncio
import logging
from pathlib import Path
try:
    from pyrogram.types import InputMediaPhoto
except ImportError:
    class InputMediaPhoto:
        def __init__(self, media=None): self.media = media
from bot.config import TEMP_DIR
from bot.core.cleaner import remove_path

logger = logging.getLogger(__name__)


import json


async def get_video_metadata(file_path: Path) -> tuple[int, int, int]:
    """
    Returns (duration_seconds, width, height) using ffprobe.
    Ensures duration is read from container format and streams so Telegram displays
    a full video player with controls rather than an animation/GIF.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(file_path)
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            data = json.loads(stdout.decode())
            fmt = data.get("format", {})
            raw_dur = fmt.get("duration")
            dur = float(raw_dur) if raw_dur else 0.0

            width, height = 0, 0
            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    width = int(s.get("width") or 0)
                    height = int(s.get("height") or 0)
                    if dur <= 0 and s.get("duration"):
                        try:
                            dur = float(s["duration"])
                        except (ValueError, TypeError):
                            pass
                    break

            # If duration is 0, Telegram defaults to GIF animation. Ensure at least 1 second.
            final_duration = max(1, int(round(dur)))
            return final_duration, width, height
    except Exception as e:
        logger.debug(f"ffprobe metadata extraction failed for {file_path.name}: {e}")

    return 1, 0, 0


async def generate_thumbnail(file_path: Path, thumb_path: Path, duration: int = 1) -> Path:
    """Extracts a video frame as a JPG thumbnail (avoiding seeking past end of short videos)."""
    seek_seconds = min(1, max(0, duration // 2))
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(seek_seconds),
        "-i", str(file_path),
        "-vframes", "1",
        "-q:v", "2",
        str(thumb_path)
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            return thumb_path
    except Exception as e:
        logger.debug(f"Failed to generate thumbnail for {file_path.name}: {e}")
    return None


async def upload_file(
    client,
    chat_id: int,
    file_path: Path,
    caption: str = "",
    custom_thumb: str = None,
    progress_callback = None,
    as_document: bool = False
):
    """
    Uploads a file to Telegram.
    Tries send_video with metadata and thumbnail first; falls back to send_document.
    """
    thumb_to_use = None
    generated_thumb = None

    if custom_thumb and Path(custom_thumb).exists():
        thumb_to_use = custom_thumb

    try:
        if not as_document and file_path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            duration, width, height = await get_video_metadata(file_path)
            if not thumb_to_use:
                generated_thumb = TEMP_DIR / f"thumb_{file_path.stem}.jpg"
                thumb_to_use = await generate_thumbnail(file_path, generated_thumb, duration)

            try:
                sent = await client.send_video(
                    chat_id=chat_id,
                    video=str(file_path),
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=str(thumb_to_use) if thumb_to_use else None,
                    supports_streaming=True,
                    progress=progress_callback
                )
                return sent
            except Exception as e:
                logger.warning(f"send_video failed ({e}); falling back to send_document for {file_path.name}")

        # Fallback to document upload
        sent = await client.send_document(
            chat_id=chat_id,
            document=str(file_path),
            caption=caption,
            thumb=str(thumb_to_use) if thumb_to_use else None,
            progress=progress_callback
        )
        return sent

    finally:
        if generated_thumb and generated_thumb.exists():
            remove_path(generated_thumb)


async def upload_photo_albums(client, chat_id: int, image_paths: list[Path]):
    """Uploads a list of images in grouped media albums (max 10 per album)."""
    chunk_size = 10
    for i in range(0, len(image_paths), chunk_size):
        chunk = image_paths[i:i + chunk_size]
        media_group = [InputMediaPhoto(media=str(p)) for p in chunk]
        try:
            await client.send_media_group(chat_id=chat_id, media=media_group)
            await asyncio.sleep(1.5)  # Telegram rate limit buffer
        except Exception as e:
            logger.error(f"Failed to send image media group: {e}")
            # Fallback to single document sends
            for img in chunk:
                await client.send_document(chat_id=chat_id, document=str(img))
