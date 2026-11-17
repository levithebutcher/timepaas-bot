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

# Concurrency semaphore to allow multiple simultaneous uploads without hitting Telegram flood limits
_UPLOAD_SEMAPHORE = asyncio.Semaphore(4)
# Concurrency semaphore to prevent multiple ffmpeg/ffprobe tasks from pinning CPU at 100%
_METADATA_SEMAPHORE = asyncio.Semaphore(4)


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
            os.replace(temp_fixed, file_path)
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


async def prepare_video_upload_data(
    file_path: Path,
    custom_thumb: str = None
) -> tuple[Path, int, int, int, Path | None, str | None]:
    """
    Unified helper to prepare a video for Telegram upload:
    1. Ensures audio track exists (so Telegram renders a playable video instead of a GIF).
    2. Probes video duration, width, and height.
    3. Handles custom thumbnail or generates a unique temporary thumbnail frame.
    Returns:
        (prepared_file_path, duration, width, height, generated_thumb_path, actual_thumb_str)
    """
    async with _METADATA_SEMAPHORE:
        duration, width, height, has_audio = await get_video_metadata(file_path)
        if not has_audio:
            file_path = await ensure_video_has_audio(file_path)
            duration, width, height, _ = await get_video_metadata(file_path)

        thumb_to_use = custom_thumb if (custom_thumb and Path(custom_thumb).exists()) else None
        generated_thumb = None

        if not thumb_to_use:
            generated_thumb = file_path.parent / f"thumb_{uuid.uuid4().hex[:8]}_{file_path.stem}.jpg"
            thumb_to_use = await generate_thumbnail(file_path, generated_thumb, duration)
            if not thumb_to_use:
                generated_thumb = None

        actual_thumb = str(thumb_to_use) if (thumb_to_use and Path(thumb_to_use).exists() and Path(thumb_to_use).stat().st_size > 0) else None
        return file_path, duration, width, height, generated_thumb, actual_thumb


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
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise FileNotFoundError(f"File to upload does not exist or is empty: {file_path}")

    async with _UPLOAD_SEMAPHORE:
        generated_thumb = None

        try:
            if not as_document and file_path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
                file_path, duration, width, height, generated_thumb, actual_thumb = await prepare_video_upload_data(
                    file_path, custom_thumb
                )
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
            doc_thumb = str(custom_thumb) if (custom_thumb and Path(custom_thumb).exists() and Path(custom_thumb).stat().st_size > 0) else None
            sent = await client.send_document(
                chat_id=chat_id,
                document=str(file_path),
                caption=caption,
                thumb=doc_thumb,
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
    custom_thumb: str = None,
    chunk_size: int = 10
):
    """
    Uploads a list of video files grouped into Telegram video albums.
    Uses chunk sizes up to 10 videos per album (Telegram's official max media group size).
    Falls back cleanly to individual upload_file if send_media_group encounters any error or timeout.
    """
    if not video_items:
        return

    if len(video_items) == 1:
        v_path, caption = video_items[0]
        await upload_file(client, chat_id, v_path, caption=caption, custom_thumb=custom_thumb)
        return

    for i in range(0, len(video_items), chunk_size):
        chunk = video_items[i:i + chunk_size]
        if len(chunk) == 1:
            v_path, caption = chunk[0]
            await upload_file(client, chat_id, v_path, caption=caption, custom_thumb=custom_thumb)
            continue

        temp_thumbs = []

        async def prepare_media_item(v_path, caption):
            file_path, duration, width, height, gen_thumb, actual_thumb = await prepare_video_upload_data(
                v_path, custom_thumb
            )
            if gen_thumb:
                temp_thumbs.append(gen_thumb)

            return InputMediaVideo(
                media=str(file_path),
                thumb=actual_thumb,
                caption=caption,
                duration=duration,
                width=width,
                height=height,
                supports_streaming=True
            )

        # Parallelize video probing and thumbnail generation across all pack videos (capped by _METADATA_SEMAPHORE)
        media_group = list(await asyncio.gather(*(prepare_media_item(vp, cap) for vp, cap in chunk)))

        async with _UPLOAD_SEMAPHORE:
            timeout_sec = max(300.0, len(chunk) * 60.0)
            try:
                # Dynamic timeout based on batch size to prevent premature socket aborts
                await asyncio.wait_for(
                    client.send_media_group(chat_id=chat_id, media=media_group),
                    timeout=timeout_sec
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


async def upload_single_to_dump(
    client,
    dump_chat_id: int | str,
    file_path: Path,
    caption: str = "",
    custom_thumb: str = None
) -> dict:
    """
    Uploads a single video directly to the designated Dump Channel / Group (Option B).
    Immediately deletes the local video file from disk upon successful upload to prevent
    disk space buildup. Returns media descriptors including Telegram server-side file_id.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise FileNotFoundError(f"File to upload does not exist or is empty: {file_path}")

    file_path, duration, width, height, generated_thumb, actual_thumb = await prepare_video_upload_data(
        file_path, custom_thumb
    )

    async with _UPLOAD_SEMAPHORE:
        try:
            sent = await client.send_video(
                chat_id=dump_chat_id,
                video=str(file_path),
                caption=caption,
                duration=duration,
                width=width,
                height=height,
                thumb=actual_thumb,
                supports_streaming=True
            )
        finally:
            if generated_thumb and generated_thumb.exists():
                remove_path(generated_thumb)
            # Immediately delete local video file to free disk!
            remove_path(file_path)

    file_id = sent.video.file_id if sent.video else (sent.document.file_id if sent.document else None)
    thumb_id = sent.video.thumbs[0].file_id if (sent.video and sent.video.thumbs) else None

    return {
        "file_id": file_id,
        "thumb_id": thumb_id,
        "caption": caption,
        "duration": duration,
        "width": width,
        "height": height,
        "msg_id": sent.id
    }


async def deliver_dumped_album(
    client,
    target_chat_id: int,
    dump_chat_id: int | str,
    dumped_items: list[dict]
):
    """
    Delivers video album to user referencing files already on Telegram servers (Option B).
    Lightning-fast server-to-server delivery with zero local network re-upload.
    Automatically deletes temporary messages from the Dump Channel after delivery.
    """
    if not dumped_items:
        return

    dump_msg_ids = [item["msg_id"] for item in dumped_items if "msg_id" in item]

    try:
        if len(dumped_items) == 1:
            item = dumped_items[0]
            try:
                await client.copy_messages(
                    chat_id=target_chat_id,
                    from_chat_id=dump_chat_id,
                    message_ids=item["msg_id"]
                )
            except Exception:
                await client.send_video(
                    chat_id=target_chat_id,
                    video=item["file_id"],
                    caption=item["caption"],
                    duration=item["duration"],
                    width=item["width"],
                    height=item["height"],
                    supports_streaming=True
                )
            return

        # Group into media group using Telegram file_ids
        media_group = [
            InputMediaVideo(
                media=item["file_id"],
                caption=item["caption"],
                duration=item["duration"],
                width=item["width"],
                height=item["height"],
                supports_streaming=True
            )
            for item in dumped_items
        ]

        try:
            await client.send_media_group(chat_id=target_chat_id, media=media_group)
        except Exception as e:
            logger.warning(f"send_media_group with file_ids failed ({e}); falling back to copy_messages")
            await client.copy_messages(
                chat_id=target_chat_id,
                from_chat_id=dump_chat_id,
                message_ids=dump_msg_ids
            )
    finally:
        # Auto-delete temporary relayed videos from the Dump Channel so it stays 100% clean
        if dump_msg_ids:
            try:
                await client.delete_messages(chat_id=dump_chat_id, message_ids=dump_msg_ids)
                logger.info(f"Auto-deleted {len(dump_msg_ids)} temporary messages from Dump Channel {dump_chat_id}")
            except Exception as del_err:
                logger.debug(f"Failed to auto-delete messages from dump channel: {del_err}")


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
