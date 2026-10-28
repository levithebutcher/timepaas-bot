import os
import re
import shutil
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


def parse_aria2_size(s: str) -> int:
    """Converts aria2 size string (e.g., 4.5MiB, 80KiB) to integer bytes."""
    units = {
        "b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
        "kb": 1000, "mb": 1000**2, "gb": 1000**3
    }
    match = re.match(r"^([\d\.]+)\s*([a-zA-Z]+)?$", s.strip())
    if not match:
        return 0
    val = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    return int(val * units.get(unit, 1))


def _validate_downloaded_file(target_path: Path):
    """Validates that a downloaded file is valid media and not an HTML error webpage."""
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


async def _download_via_aria2(
    url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None,
    connections: int = 4
) -> bool:
    """
    Accelerated multi-connection downloader via aria2c (splits download into N parallel streams).
    Returns True if successfully downloaded, False on error/fallback.
    """
    aria2_bin = shutil.which("aria2c")
    if not aria2_bin:
        return False

    user_agent = (headers or {}).get("User-Agent", DEFAULT_USER_AGENT)
    parsed = urlparse(url)
    referer = (headers or {}).get("Referer", f"{parsed.scheme}://{parsed.netloc}/")

    cmd = [
        aria2_bin,
        "--allow-overwrite=true",
        "--auto-file-allocation=false",
        "--file-allocation=none",
        f"--max-connection-per-server={connections}",
        f"--split={connections}",
        "--min-split-size=1M",
        "--summary-interval=1",
        "--console-log-level=warn",
        f"--user-agent={user_agent}",
        "-d", str(target_path.parent.resolve()),
        "-o", target_path.name,
    ]
    if referer:
        cmd.append(f"--header=Referer: {referer}")
    if headers:
        for k, v in headers.items():
            if k.lower() not in ("user-agent", "referer"):
                cmd.append(f"--header={k}: {v}")
    cmd.append(url)

    logger.info(f"Starting aria2c accelerated download ({connections} parallel streams) for {target_path.name}")
    aria2_control_file = target_path.with_name(target_path.name + ".aria2")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    summary_pattern = re.compile(r'\[#[0-9a-fA-F]+\s+([\d\.]+[a-zA-Z]+)/([\d\.]+[a-zA-Z]+)')

    async def read_stdout():
        last_progress_time = 0
        while True:
            if cancel_event and cancel_event.is_set():
                break
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="ignore")
            m = summary_pattern.search(decoded)
            if m and progress_callback:
                now = asyncio.get_event_loop().time()
                if now - last_progress_time >= 1.0:
                    last_progress_time = now
                    dl_bytes = parse_aria2_size(m.group(1))
                    tot_bytes = parse_aria2_size(m.group(2))
                    try:
                        await progress_callback(dl_bytes, tot_bytes)
                    except Exception:
                        pass

    reader_task = asyncio.create_task(read_stdout())

    try:
        while proc.returncode is None:
            if cancel_event and cancel_event.is_set():
                proc.kill()
                reader_task.cancel()
                target_path.unlink(missing_ok=True)
                aria2_control_file.unlink(missing_ok=True)
                raise asyncio.CancelledError("Download cancelled by user.")
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

        await reader_task

        if proc.returncode != 0:
            stderr_out = await proc.stderr.read()
            logger.warning(
                f"aria2c exited with code {proc.returncode}: {stderr_out.decode('utf-8', errors='ignore')[:300]}"
            )
            target_path.unlink(missing_ok=True)
            aria2_control_file.unlink(missing_ok=True)
            return False

        if target_path.exists() and target_path.stat().st_size > 0:
            return True
        return False

    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        reader_task.cancel()
        target_path.unlink(missing_ok=True)
        aria2_control_file.unlink(missing_ok=True)
        raise
    except Exception as e:
        logger.warning(f"aria2c execution error: {e}")
        if proc.returncode is None:
            proc.kill()
        reader_task.cancel()
        target_path.unlink(missing_ok=True)
        aria2_control_file.unlink(missing_ok=True)
        return False


async def download_direct_stream(
    url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None,
    max_retries: int = 3
) -> Path:
    """
    Downloads a direct media file.
    Attempts multi-connection acceleration via aria2c first (if installed),
    and safely falls back to chunked aiohttp with Range resume support.
    """
    if not check_free_disk_space():
        raise RuntimeError("Insufficient disk space on host machine to initiate download.")

    # 1. Accelerated parallel download via aria2c (safe 4 connections)
    if shutil.which("aria2c"):
        try:
            success = await _download_via_aria2(
                url=url,
                target_path=target_path,
                headers=headers,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                connections=4
            )
            if success:
                _validate_downloaded_file(target_path)
                return target_path
            else:
                logger.info("aria2c multi-connection download did not complete, falling back to aiohttp.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"aria2c attempt failed: {e}, falling back to aiohttp.")

    # 2. Resilient chunked aiohttp downloader
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
            connector = aiohttp.TCPConnector(limit=0, enable_cleanup_closed=True)
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=req_headers,
                connector=connector,
                read_bufsize=1024 * 512
            ) as session:
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

                    _validate_downloaded_file(target_path)
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
