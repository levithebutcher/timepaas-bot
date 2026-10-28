import logging
from urllib.parse import urlparse
from bot.extractors.video_hosts import extract_from_video_hosts
from bot.extractors.ytdlp_ext import extract_with_ytdlp
from bot.extractors.bs4_ext import extract_with_bs4
from bot.extractors.browser_ext import extract_with_playwright

logger = logging.getLogger(__name__)

DIRECT_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m3u8",
    ".zip", ".rar", ".7z", ".tar", ".gz"
}


async def extract_media_link(url: str) -> dict:
    """
    Sequentially resolves target video/archive from a page URL:
    0. Specialized Video Hosts (Streamtape, Doodstream, Mixdrop, Streamwish, FileLions)
    1. Direct file link check (verifying it's not a web player page)
    2. yt-dlp native extraction
    3. BeautifulSoup4 HTML tag search
    4. Playwright headless network sniffer
    """
    clean_path = urlparse(url).path.lower()

    # 0. Specialized Video Hosts Resolver (Streamtape, Doodstream, Mixdrop, etc.) - PRIORITY 1
    logger.info(f"[Tier 0] Checking specialized video host extractors for {url}")
    host_res = await extract_from_video_hosts(url)
    if host_res and host_res.get("url"):
        logger.info(f"[Tier 0] Video host resolver extracted stream: {host_res.get('title')}")
        return host_res

    # 1. Direct media link check (ensure it is NOT a webpage route like /v/, /e/, /watch/)
    is_web_player_route = any(p in clean_path for p in ("/v/", "/e/", "/watch/", "/embed/", "/view/", "/play/", "/file/", "/f/", "/d/"))
    if not is_web_player_route:
        for ext in DIRECT_EXTENSIONS:
            if clean_path.endswith(ext):
                is_m3u8 = clean_path.endswith(".m3u8")
                title = url.split("/")[-1].split("?")[0]
                logger.info(f"Direct media link recognized: {title}")
                return {
                    "type": "m3u8" if is_m3u8 else "direct",
                    "url": url,
                    "title": title,
                    "headers": {}
                }

    # 2. Try yt-dlp
    logger.info(f"[Tier 1] Attempting yt-dlp extraction for {url}")
    result = await extract_with_ytdlp(url)
    if result and result.get("url"):
        logger.info(f"[Tier 1] yt-dlp successfully resolved stream: {result.get('title')}")
        return result

    # 3. Try BeautifulSoup
    logger.info(f"[Tier 2] Falling back to BeautifulSoup4 for {url}")
    result = await extract_with_bs4(url)
    if result and result.get("url"):
        logger.info(f"[Tier 2] BeautifulSoup4 extracted stream: {result.get('title')}")
        return result

    # 4. Try Playwright
    logger.info(f"[Tier 3] Falling back to Playwright headless browser for {url}")
    result = await extract_with_playwright(url)
    if result and result.get("url"):
        logger.info(f"[Tier 3] Playwright intercepted media: {result.get('title')}")
        return result

    logger.warning(f"All extraction tiers failed to find media for {url}")
    return None
