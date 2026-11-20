import os
import re
import shutil
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote
import aiohttp
import aiofiles
from bot.config import DEFAULT_USER_AGENT, ARIA2_CONNECTIONS
from bot.core.cleaner import check_free_disk_space

logger = logging.getLogger(__name__)


def sanitize_filename(name: str, default: str = "downloaded_media.mp4") -> str:
    """Sanitizes filename for cross-platform filesystem safety."""
    if not name:
        return default
    clean = re.sub(r'[\x00-\x1f\x7f-\x9f\\/:*?"<>|]', '_', str(name)).strip('. ')
    if not clean:
        return default
    return clean


def derive_filename(url: str, response_headers: dict = None) -> str:
    """Extracts or derives a clean filename from headers or URL path."""
    if response_headers:
        cd = response_headers.get("Content-Disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"\'; ')
            if filename:
                return sanitize_filename(filename)

    parsed = urlparse(url)
    clean_path = unquote(parsed.path)
    base = Path(clean_path).name
    if base and "." in base:
        return sanitize_filename(base)
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


def sanitize_headers(headers: dict = None) -> dict:
    """
    Sanitizes HTTP request headers to prevent forbidden control characters
    (CRLF, NULL, control chars) and removes server response headers.
    """
    if not headers:
        return {}

    DISALLOWED_HEADERS = {
        "set-cookie", "content-length", "content-type", "content-encoding",
        "transfer-encoding", "connection", "keep-alive", "proxy-authenticate",
        "proxy-authorization", "te", "trailers", "upgrade", "server", "date",
        "alt-svc", "cf-ray", "cf-cache-status", "strict-transport-security"
    }

    clean = {}
    for k, v in headers.items():
        if not k or v is None:
            continue
        k_str = str(k).strip()
        if k_str.startswith(":") or k_str.lower() in DISALLOWED_HEADERS:
            continue
        v_str = str(v)
        # Strip forbidden control characters (ASCII 0x00-0x1F and 0x7F-0x9F)
        # Specifically \r (\x0d) and \n (\x0a) which cause ValueError in aiohttp
        v_clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", v_str).strip()
        k_clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", k_str).strip()
        if k_clean and v_clean:
            clean[k_clean] = v_clean

    return clean


def _validate_downloaded_file(target_path: Path):
    """Validates that a downloaded file is valid media and not an HTML/JS/Ad error page or empty file."""
    if not target_path.exists():
        return
    size = target_path.stat().st_size
    if size == 0:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is empty (0 bytes).")

    if size < 1024 * 1024:  # under 1 MB
        prefix = b""
        try:
            with open(target_path, "rb") as check_f:
                prefix = check_f.read(2048).lower()
        except (IOError, OSError):
            return

        # Check for HTML webpage
        if b"<!doctype html" in prefix or b"<html" in prefix or b"<head" in prefix:
            target_path.unlink(missing_ok=True)
            raise RuntimeError(
                "Downloaded content was an HTML webpage instead of a media stream. "
                "The video link could not be downloaded."
            )
        # Check for JavaScript or Ad text
        if (
            b"adsbygoogle" in prefix
            or b"google_ad" in prefix
            or b"(function(" in prefix
            or b"window." in prefix
            or b"var _" in prefix
            or (b"/*" in prefix and b"*/" in prefix)
            or b"webpack" in prefix
        ):
            target_path.unlink(missing_ok=True)
            raise RuntimeError(
                "Downloaded content was a JavaScript ad script instead of a media stream."
            )


async def _download_via_aria2(
    url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None,
    connections: int = ARIA2_CONNECTIONS
) -> bool:
    """
    Accelerated multi-connection downloader via aria2c (splits download into N parallel streams).
    Returns True if successfully downloaded, False on error/fallback.
    """
    aria2_bin = shutil.which("aria2c")
    if not aria2_bin:
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    url = re.sub(r"[\x00-\x1f\x7f-\x9f\s]", "", str(url).strip())
    clean_headers = sanitize_headers(headers)
    user_agent = clean_headers.get("User-Agent", DEFAULT_USER_AGENT)
    parsed = urlparse(url)
    referer = clean_headers.get("Referer", f"{parsed.scheme}://{parsed.netloc}/")

    split_connections = max(16, min(32, connections * 2))
    server_connections = min(16, connections)

    cmd = [
        aria2_bin,
        "--allow-overwrite=true",
        "--file-allocation=none",
        f"--max-connection-per-server={server_connections}",
        f"--split={split_connections}",
        "--min-split-size=1M",
        "--piece-length=1M",
        "--disk-cache=128M",
        "--optimize-concurrent-downloads=true",
        "--conditional-get=true",
        "--stream-piece-selector=geom",
        "--summary-interval=1",
        "--console-log-level=warn",
        f"--user-agent={user_agent}",
        "-d", str(target_path.parent.resolve()),
        "-o", target_path.name,
    ]
    if referer:
        cmd.append(f"--header=Referer: {referer}")
    for k, v in clean_headers.items():
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

    target_path.parent.mkdir(parents=True, exist_ok=True)
    url = re.sub(r"[\x00-\x1f\x7f-\x9f\s]", "", str(url).strip())
    clean_headers = sanitize_headers(headers)

    # 1. Accelerated parallel download via aria2c (configurable N parallel streams)
    if shutil.which("aria2c"):
        try:
            success = await _download_via_aria2(
                url=url,
                target_path=target_path,
                headers=clean_headers,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                connections=ARIA2_CONNECTIONS
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
    req_headers.update(clean_headers)

    # Determine domain for Referer if not already set
    if "Referer" not in req_headers:
        parsed = urlparse(url)
        req_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=60)
    chunk_size = 4 * 1024 * 1024  # 4 MB turbo buffer chunk for accelerated I/O write rate

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
                read_bufsize=1024 * 1024
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


async def _download_m3u8_via_curl_cffi(
    m3u8_url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None
) -> bool:
    """
    Downloads an HLS .m3u8 stream using curl_cffi with Chrome TLS impersonation.
    Completely bypasses Cloudflare WAF / CDN anti-bot blocking (which blocks FFmpeg with 403),
    fetches AES-128 keys if encrypted, downloads all .ts segments, and remuxes locally via FFmpeg.
    """
    try:
        from curl_cffi.requests import AsyncSession
        import tempfile
        from urllib.parse import urljoin
    except ImportError:
        return False

    h = {}
    if headers:
        for k, v in headers.items():
            if k.lower() != "origin":
                h[k] = v
    if "User-Agent" not in h:
        h["User-Agent"] = DEFAULT_USER_AGENT
    tmp_dir = Path(tempfile.mkdtemp(prefix="hls_curl_"))

    try:
        async with AsyncSession(impersonate="chrome120") as session:
            # 1. Fetch master playlist
            r = await session.get(m3u8_url, headers=h, timeout=15)
            if r.status_code != 200:
                logger.debug(f"curl_cffi master playlist fetch returned status {r.status_code}")
                return False

            lines = r.text.splitlines()
            sub_urls = []
            for line in lines:
                line_clean = line.strip()
                if line_clean and not line_clean.startswith("#"):
                    sub_urls.append(urljoin(m3u8_url, line_clean))

            playlist_url = m3u8_url
            if sub_urls and (sub_urls[0].endswith(".m3u8") or "index" in sub_urls[0] or "urlset" in sub_urls[0]):
                playlist_url = sub_urls[-1]
                r = await session.get(playlist_url, headers=h, timeout=15)
                if r.status_code != 200:
                    return False
                lines = r.text.splitlines()

            local_lines = []
            segments = []
            key_count = 0

            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("#EXT-X-KEY"):
                    key_match = re.search(r'URI=["\']([^"\']+)["\']', line_str)
                    if key_match:
                        key_url = urljoin(playlist_url, key_match.group(1))
                        key_fn = f"key_{key_count}.bin"
                        key_count += 1
                        r_key = await session.get(key_url, headers=h, timeout=15)
                        if r_key.status_code != 200:
                            return False
                        (tmp_dir / key_fn).write_bytes(r_key.content)
                        new_key_line = line_str.replace(key_match.group(1), key_fn)
                        local_lines.append(new_key_line)
                    else:
                        local_lines.append(line_str)
                elif line_str.startswith("#"):
                    local_lines.append(line_str)
                else:
                    seg_url = urljoin(playlist_url, line_str)
                    seg_idx = len(segments)
                    seg_fn = f"seg_{seg_idx:05d}.ts"
                    segments.append((seg_idx, seg_url, tmp_dir / seg_fn))
                    local_lines.append(seg_fn)

            if not segments:
                return False

            local_lines.append("#EXT-X-ENDLIST")
            local_m3u8 = tmp_dir / "local.m3u8"
            local_m3u8.write_text("\n".join(local_lines), encoding="utf-8")

            # Accelerated parallel chunk downloader (16 concurrent streams)
            sem = asyncio.Semaphore(16)
            downloaded_bytes = 0

            async def dl_segment(idx, seg_u, dest):
                nonlocal downloaded_bytes
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()
                async with sem:
                    for attempt in range(4):
                        if cancel_event and cancel_event.is_set():
                            raise asyncio.CancelledError()
                        try:
                            r_s = await session.get(seg_u, headers=h, timeout=20)
                            if r_s.status_code == 200 and len(r_s.content) > 0:
                                dest.write_bytes(r_s.content)
                                downloaded_bytes += len(r_s.content)
                                if progress_callback:
                                    await progress_callback(downloaded_bytes, 0)
                                return
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            await asyncio.sleep(1)
                    raise RuntimeError(f"Failed to download segment {idx}")

            tasks = [dl_segment(idx, u, dest) for idx, u, dest in segments]
            await asyncio.gather(*tasks)

            # Local remux with FFmpeg (offline, zero network)
            remux_cmd = [
                "ffmpeg", "-y",
                "-allowed_segment_extensions", "ALL",
                "-allowed_extensions", "ALL",
                "-i", str(local_m3u8),
                "-c", "copy",
                "-movflags", "+faststart",
                str(target_path)
            ]
            proc = await asyncio.create_subprocess_exec(
                *remux_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            return target_path.exists() and target_path.stat().st_size > 0

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug(f"curl_cffi HLS download fallback failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _download_m3u8_via_ytdlp(m3u8_url: str, target_path: Path, headers: dict) -> bool:
    """Fallback HLS/M3U8 downloader using yt-dlp when FFmpeg fails."""
    def _sync_dl():
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(target_path),
            "format": "best",
            "nocheckcertificate": True,
            "http_headers": headers or {},
            "extractor_args": {
                "generic": {"impersonate": ["chrome"]}
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([m3u8_url])
        return target_path.exists() and target_path.stat().st_size > 0

    try:
        return await asyncio.to_thread(_sync_dl)
    except Exception as e:
        logger.debug(f"yt-dlp m3u8 fallback failed: {e}")
        return False


async def download_m3u8_stream(
    m3u8_url: str,
    target_path: Path,
    headers: dict = None,
    progress_callback = None,
    cancel_event: asyncio.Event = None
) -> Path:
    """
    Downloads and remuxes an HLS .m3u8 stream into an MP4 file using ffmpeg,
    with automatic header forwarding and resilient yt-dlp fallback.
    """
    if not check_free_disk_space():
        raise RuntimeError("Insufficient disk space on host machine.")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required to download HLS .m3u8 streams but was not found on PATH.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    m3u8_url = re.sub(r"[\x00-\x1f\x7f-\x9f\s]", "", str(m3u8_url).strip())
    clean_headers = sanitize_headers(headers)
    user_agent = clean_headers.get("User-Agent", DEFAULT_USER_AGENT)

    header_lines = [f"User-Agent: {user_agent}"]
    for k, v in clean_headers.items():
        if k.lower() != "user-agent":
            header_lines.append(f"{k}: {v}")
    header_str = "\r\n".join(header_lines) + "\r\n"

    # For CDNs known to enforce browser TLS fingerprints (e.g. *.tnmr.org / Lulu CDN),
    # use curl_cffi with Chrome impersonation directly to bypass 403 blocking without delay.
    if any(cdn in m3u8_url for cdn in ("tnmr.org",)):
        logger.info(f"Target HLS stream uses Cloudflare TLS fingerprinting ({m3u8_url[:50]}...). Using curl_cffi downloader directly.")
        curl_success = await _download_m3u8_via_curl_cffi(
            m3u8_url, target_path, clean_headers, progress_callback, cancel_event
        )
        if curl_success and target_path.exists() and target_path.stat().st_size > 0:
            logger.info(f"HLS stream successfully downloaded via direct curl_cffi: {target_path.name}")
            return target_path

    cmd = [
        "ffmpeg",
        "-y",
        "-allowed_segment_extensions", "ALL",
        "-allowed_extensions", "ALL",
        "-http_persistent", "1",
        "-http_multiple", "1",
        "-timeout", "15000000",
        "-tcp_nodelay", "1",
        "-tcp_keepalive", "1",
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_on_network_error", "1",
        "-reconnect_delay_max", "5",
        "-headers", header_str,
        "-i", m3u8_url,
        "-c", "copy",
        "-movflags", "+faststart",
        str(target_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
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
            stderr_bytes = await proc.stderr.read()
            stderr_out = stderr_bytes.decode("utf-8", errors="ignore")
            logger.warning(f"FFmpeg m3u8 download exited with code {proc.returncode}: {stderr_out[-400:]}")

            # 1. Primary Fallback: curl_cffi with Chrome TLS impersonation (bypasses Cloudflare 403 blocks)
            logger.info("Attempting curl_cffi HLS fallback with Chrome TLS impersonation...")
            curl_success = await _download_m3u8_via_curl_cffi(
                m3u8_url, target_path, clean_headers, progress_callback, cancel_event
            )
            if curl_success and target_path.exists() and target_path.stat().st_size > 0:
                logger.info(f"HLS stream successfully downloaded via curl_cffi fallback: {target_path.name}")
                return target_path

            # 2. Secondary Fallback: yt-dlp HLS downloader
            logger.info("Attempting yt-dlp fallback for m3u8 stream...")
            fallback_success = await _download_m3u8_via_ytdlp(m3u8_url, target_path, clean_headers)
            if fallback_success and target_path.exists() and target_path.stat().st_size > 0:
                logger.info(f"HLS stream successfully downloaded via yt-dlp fallback: {target_path.name}")
                return target_path

            # If all fallbacks failed, report root cause error
            if "522" in stderr_out or "5XX Server Error" in stderr_out:
                raise RuntimeError("Host server connection timed out / server down (HTTP 522). Try again later.")
            if "404" in stderr_out or "not found" in stderr_out.lower():
                raise RuntimeError("Stream not found on host (HTTP 404). File may have been deleted.")
            if "403" in stderr_out or "forbidden" in stderr_out.lower():
                raise RuntimeError("Access forbidden by host CDN (HTTP 403).")

            raise RuntimeError(f"FFmpeg m3u8 download exited with code {proc.returncode}")

    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        raise

    return target_path
