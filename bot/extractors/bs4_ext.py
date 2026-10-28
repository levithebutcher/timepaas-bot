import logging
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

TARGET_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m3u8",
    ".zip", ".rar", ".7z", ".tar", ".gz"
}


async def extract_with_bs4(url: str) -> dict:
    """
    Parses HTML content for video/source tags and download anchor elements.
    """
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")

        # 1. Search in <video> and <source> tags
        for tag in soup.find_all(["video", "source"]):
            src = tag.get("src")
            if src:
                full_url = urljoin(url, src)
                clean_path = urlparse(full_url).path.lower()
                is_m3u8 = ".m3u8" in clean_path
                return {
                    "type": "m3u8" if is_m3u8 else "direct",
                    "url": full_url,
                    "title": full_url.split("/")[-1].split("?")[0] or "extracted_media.mp4",
                    "headers": headers
                }

        # 2. Search in <a href> matching target file extensions
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            full_url = urljoin(url, href)
            clean_path = urlparse(full_url).path.lower()

            for ext in TARGET_EXTENSIONS:
                if clean_path.endswith(ext) or ext in clean_path:
                    return {
                        "type": "m3u8" if ".m3u8" in clean_path else "direct",
                        "url": full_url,
                        "title": full_url.split("/")[-1].split("?")[0] or f"download{ext}",
                        "headers": headers
                    }

        # 3. Search in <a href> with 'download' text or attribute
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip().lower()
            href = a.get("href", "").strip()
            if "download" in text or a.get("download") is not None:
                full_url = urljoin(url, href)
                # Verify that it's not a generic page reload
                if full_url != url:
                    return {
                        "type": "direct",
                        "url": full_url,
                        "title": "downloaded_file",
                        "headers": headers
                    }

    except Exception as e:
        logger.debug(f"BS4 extraction error for {url}: {e}")

    return None
