import os
import re
import json
import uuid
import asyncio
import logging
from pathlib import Path
try:
    from pyrogram.types import InputMediaPhoto, InputMediaVideo
except ImportError:
    class InputMediaPhoto:
        def __init__(self, media=None, caption=None):
            self.media = media
            self.caption = caption
    class InputMediaVideo:
        def __init__(
            self,
            media=None,
            thumb=None,
            caption=None,
            duration=0,
            width=0,
            height=0,
            supports_streaming=True
        ):
            self.media = media
            self.thumb = thumb
            self.caption = caption
            self.duration = duration
            self.width = width
            self.height = height
            self.supports_streaming = supports_streaming

from bot.config import TEMP_DIR
from bot.core.cleaner import remove_path

logger = logging.getLogger(__name__)

# Concurrency semaphore to avoid overloading Telegram MTProto DC5 media socket with too many simultaneous uploads
_UPLOAD_SEMAPHORE = asyncio.Semaphore(2)


async def get_video_metadata(file_path: Path) -> tuple[int, int, int, bool]:
    """
    Returns (duration_seconds, width, height, has_audio) using ffprobe.
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
    dur = 0.0
    width, height = 0, 0
    has_audio = False

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

            for s in data.get("streams", []):
                ctype = s.get("codec_type")
                if ctype == "video" and width == 0:
                    width = int(s.get("width") or 0)
                    height = int(s.get("height") or 0)
                    if dur <= 0 and s.get("duration"):
                        try:
                            dur = float(s["duration"])
                        except (ValueError, TypeError):
                            pass
                elif ctype == "audio":
                    has_audio = True

    except Exception as e:
        logger.debug(f"ffprobe metadata extraction failed for {file_path.name}: {e}")

    # Fallback duration parser from ffmpeg output if still <= 0
    if dur <= 0:
        try:
            f_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", str(file_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, f_stderr = await f_proc.communicate()
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", f_stderr.decode("utf-8", errors="ignore"))
            if m:
                h, mins, s = m.groups()
                dur = int(h) * 3600 + int(mins) * 60 + float(s)
        except Exception:
            pass

    final_duration = max(1, int(round(dur)))
    return final_duration, width, height, has_audio


async def ensure_video_has_audio(file_path: Path) -> Path:
    """
    If a video lacks an audio track, Telegram automatically treats it as a GIF/animation.
    Injects a silent AAC audio track without re-encoding video (-c:v copy),
    which takes < 0.5s and forces Telegram to display a full video player with scrubber.
    """
    temp_fixed = file_path.with_name(f"fixed_{file_path.name}")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(file_path),
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        str(temp_fixed)
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        if proc.returncode == 0 and temp_fixed.exists() and temp_fixed.stat().st_size > 0:
            file_path.unlink(missing_ok=True)
            temp_fixed.rename(file_path)
            logger.info(f"Injected silent audio track into {file_path.name} to prevent GIF rendering.")
            return file_path
    except Exception as e:
        logger.debug(f"Failed to inject silent audio track: {e}")
    finally:
        if temp_fixed.exists():
            temp_fixed.unlink(missing_ok=True)
    return file_path


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
    Uses unique thumbnail names per task and verifies file existence to prevent concurrency race conditions.
    """
    async with _UPLOAD_SEMAPHORE:
        thumb_to_use = None
        generated_thumb = None

        if custom_thumb and Path(custom_thumb).exists():
            thumb_to_use = custom_thumb

        try:
            if not as_document and file_path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
                duration, width, height, has_audio = await get_video_metadata(file_path)
                if not has_audio:
                    file_path = await ensure_video_has_audio(file_path)
                    duration, width, height, has_audio = await get_video_metadata(file_path)

                if not thumb_to_use:
                    # Isolated unique thumbnail per task/file to prevent race condition across workers
                    generated_thumb = file_path.parent / f"thumb_{uuid.uuid4().hex[:8]}_{file_path.stem}.jpg"
                    thumb_to_use = await generate_thumbnail(file_path, generated_thumb, duration)

                actual_thumb = str(thumb_to_use) if (thumb_to_use and Path(thumb_to_use).exists() and Path(thumb_to_use).stat().st_size > 0) else None

                try:
                    sent = await client.send_video(
                        chat_id=chat_id,
                        video=str(file_path),
                        caption=caption,
                        duration=duration,
                        width=width,
                        height=height,
                        thumb=actual_thumb,
                        supports_streaming=True,
                        progress=progress_callback
                    )
                    return sent
                except Exception as e:
                    logger.warning(f"send_video failed ({e}); falling back to send_document for {file_path.name}")

            # Fallback to document upload
            actual_thumb = str(thumb_to_use) if (thumb_to_use and Path(thumb_to_use).exists() and Path(thumb_to_use).stat().st_size > 0) else None
            sent = await client.send_document(
                chat_id=chat_id,
                document=str(file_path),
                caption=caption,
                thumb=actual_thumb,
                progress=progress_callback
            )
            return sent

        finally:
            if generated_thumb and generated_thumb.exists():
                remove_path(generated_thumb)


async def upload_video_albums(
    client,
    chat_id: int,
    video_items: list[tuple[Path, str]],
    custom_thumb: str = None
):
    """
    Uploads a list of video files grouped into Telegram video albums.
    Uses safe chunk sizes (max 3 videos per album) to prevent MTProto broken pipe/timeouts.
    Falls back cleanly to individual upload_file if send_media_group encounters any error or timeout.
    """
    if len(video_items) == 1:
        v_path, caption = video_items[0]
        await upload_file(client, chat_id, v_path, caption=caption, custom_thumb=custom_thumb)
        return

    chunk_size = 3
    for i in range(0, len(video_items), chunk_size):
        chunk = video_items[i:i + chunk_size]
        if len(chunk) == 1:
            v_path, caption = chunk[0]
            await upload_file(client, chat_id, v_path, caption=caption, custom_thumb=custom_thumb)
            continue

        media_group = []
        temp_thumbs = []

        for v_path, caption in chunk:
            duration, width, height, has_audio = await get_video_metadata(v_path)
            if not has_audio:
                v_path = await ensure_video_has_audio(v_path)
                duration, width, height, has_audio = await get_video_metadata(v_path)

            thumb_to_use = custom_thumb if custom_thumb and Path(custom_thumb).exists() else None
            if not thumb_to_use:
                gen_thumb = v_path.parent / f"thumb_{uuid.uuid4().hex[:8]}_{v_path.stem}.jpg"
                thumb_to_use = await generate_thumbnail(v_path, gen_thumb, duration)
                if thumb_to_use:
                    temp_thumbs.append(thumb_to_use)

            actual_thumb = str(thumb_to_use) if (thumb_to_use and Path(thumb_to_use).exists() and Path(thumb_to_use).stat().st_size > 0) else None
            media_group.append(
                InputMediaVideo(
                    media=str(v_path),
                    thumb=actual_thumb,
                    caption=caption,
                    duration=duration,
                    width=width,
                    height=height,
                    supports_streaming=True
                )
            )

        async with _UPLOAD_SEMAPHORE:
            try:
                # Enforce 90-second timeout so Pyrogram doesn't hang in infinite socket retry loop
                await asyncio.wait_for(
                    client.send_media_group(chat_id=chat_id, media=media_group),
                    timeout=90.0
                )
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.warning(f"send_media_group failed or timed out ({e}), falling back to individual uploads")
                for v_path, caption in chunk:
                    try:
                        await upload_file(client, chat_id, v_path, caption=caption, custom_thumb=custom_thumb)
                    except Exception as ex:
                        logger.error(f"Fallback single upload failed for {v_path.name}: {ex}")
            finally:
                for t in temp_thumbs:
                    remove_path(t)


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
