import os
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote
import aiohttp
import aiofiles
from bot.config import DEFAULT_USER_AGENT
from bot.core.cleaner import check_free_disk_space

logger = logging.getLogger(__name__)


def derive_filename(url: str, response_headers: dict = None) -> str:
    """Extracts or derives a clean filename from headers or URL path."""
    if response_headers:
        cd = response_headers.get("Content-Disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"\'; ')
            if filename:
                return filename

    parsed = urlparse(url)
    clean_path = unquote(parsed.path)
    base = Path(clean_path).name
    if base and "." in base:
        return base
    return "downloaded_media.mp4"


async def download_direct_stream(
    url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None,
    max_retries: int = 3
) -> Path:
    """
    Downloads a direct media file in 1MB chunks with Range resume support and retries.
    """
    if not check_free_disk_space():
        raise RuntimeError("Insufficient disk space on host machine to initiate download.")

    req_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        req_headers.update(headers)

    # Determine domain for Referer if not already set
    if "Referer" not in req_headers:
        parsed = urlparse(url)
        req_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=60)
    chunk_size = 1024 * 1024  # 1 MB

    for attempt in range(1, max_retries + 1):
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task was cancelled by user.")

        existing_size = target_path.stat().st_size if target_path.exists() else 0
        if existing_size > 0:
            req_headers["Range"] = f"bytes={existing_size}-"

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=req_headers) as session:
                async with session.get(url) as response:
                    if response.status not in (200, 206):
                        if response.status == 416:
                            # Range not satisfiable, file might already be complete
                            return target_path
                        response.raise_for_status()

                    # Determine total size
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        total_bytes = existing_size + int(content_length)
                    else:
                        total_bytes = 0

                    mode = "ab" if existing_size > 0 and response.status == 206 else "wb"
                    downloaded = existing_size if mode == "ab" else 0

                    async with aiofiles.open(target_path, mode) as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            if cancel_event and cancel_event.is_set():
                                raise asyncio.CancelledError("Task was cancelled by user.")
                            await f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback:
                                await progress_callback(downloaded, total_bytes)

                    # Post-download validation: ensure file is not an HTML webpage
                    if target_path.exists() and target_path.stat().st_size < 500 * 1024:
                        try:
                            with open(target_path, "rb") as check_f:
                                prefix = check_f.read(512).lower()
                                if b"<!doctype html" in prefix or b"<html" in prefix or b"<head" in prefix:
                                    target_path.unlink(missing_ok=True)
                                    raise RuntimeError(
                                        "Downloaded content was an HTML webpage instead of a media stream. "
                                        "The video link could not be downloaded."
                                    )
                        except (IOError, OSError):
                            pass

                    return target_path

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Download attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 * attempt)

    return target_path


async def download_m3u8_stream(
    m3u8_url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None
) -> Path:
    """
    Downloads and remuxes an HLS .m3u8 stream into an MP4 file using ffmpeg.
    """
    if not check_free_disk_space():
        raise RuntimeError("Insufficient disk space on host machine.")

    user_agent = (headers or {}).get("User-Agent", DEFAULT_USER_AGENT)
    referer = (headers or {}).get("Referer", "")

    header_str = f"User-Agent: {user_agent}\r\n"
    if referer:
        header_str += f"Referer: {referer}\r\n"

    cmd = [
        "ffmpeg",
        "-y",
        "-headers", header_str,
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        str(target_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )

    try:
        while proc.returncode is None:
            if cancel_event and cancel_event.is_set():
                proc.kill()
                raise asyncio.CancelledError("M3U8 download cancelled by user.")
            await asyncio.sleep(2)
            if target_path.exists() and progress_callback:
                current_size = target_path.stat().st_size
                await progress_callback(current_size, 0)
            if proc.returncode is not None:
                break
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg m3u8 download exited with code {proc.returncode}")

    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        raise

    return target_path
