import asyncio
import logging
from urllib.parse import urlparse
import yt_dlp
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


def _ytdlp_extract_sync(url: str) -> dict:
    """Synchronous yt-dlp extraction to be executed in thread pool."""
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "simulate": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "http_headers": {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": referer,
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None

            # Handle playlists or single entries
            if "entries" in info and info["entries"]:
                info = info["entries"][0]

            title = info.get("title", "Video")
            ext = info.get("ext", "mp4")
            stream_url = info.get("url")
            headers = info.get("http_headers", {})

            # If formats are available and stream_url is not direct or is m3u8
            if not stream_url and "formats" in info:
                formats = [f for f in info["formats"] if f.get("url")]
                if formats:
                    stream_url = formats[-1].get("url")

            if stream_url:
                is_m3u8 = ".m3u8" in stream_url or info.get("protocol") in ("m3u8", "m3u8_native")
                return {
                    "type": "m3u8" if is_m3u8 else "direct",
                    "url": stream_url,
                    "title": f"{title}.{ext}",
                    "headers": headers
                }
    except Exception as e:
        err_msg = str(e)
        logger.debug(f"yt-dlp extraction failed for {url}: {err_msg}")
        if "404" in err_msg or "not found" in err_msg.lower():
            return {"error": "File deleted / Not Found on host (HTTP 404)"}
        if "522" in err_msg or "521" in err_msg or "523" in err_msg:
            return {"error": "Host server is down / connection timed out (HTTP 522)"}

    return None


async def extract_with_ytdlp(url: str) -> dict:
    """Async wrapper for yt-dlp extraction."""
    return await asyncio.to_thread(_ytdlp_extract_sync, url)
