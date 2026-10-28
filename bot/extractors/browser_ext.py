import asyncio
import logging
from urllib.parse import urlparse
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

MEDIA_KEYWORDS = [".m3u8", ".mp4", ".webm", ".mkv", ".zip", ".rar"]


async def extract_with_playwright(url: str, timeout_seconds: int = 25) -> dict:
    """
    Spawns headless Chromium to intercept network media streams and download triggers.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed in the current environment.")
        return None

    intercepted_url = None
    intercepted_headers = {}
    stream_type = "direct"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()

            async def handle_response(response):
                nonlocal intercepted_url, intercepted_headers, stream_type
                if intercepted_url:
                    return

                resp_url = response.url
                clean_url = resp_url.split("?")[0].lower()
                content_type = response.headers.get("content-type", "").lower()

                for kw in MEDIA_KEYWORDS:
                    if kw in clean_url or "video/" in content_type or "application/x-mpegurl" in content_type:
                        intercepted_url = resp_url
                        intercepted_headers = await response.all_headers()
                        if ".m3u8" in clean_url or "mpegurl" in content_type:
                            stream_type = "m3u8"
                        else:
                            stream_type = "direct"
                        break

            page.on("response", handle_response)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            except Exception as e:
                logger.debug(f"Playwright navigation timeout/error for {url}: {e}")

            # Try clicking play or download elements if not yet intercepted
            if not intercepted_url:
                selectors_to_try = [
                    "button:has-text('Download')",
                    "a:has-text('Download')",
                    "button:has-text('Play')",
                    ".vjs-big-play-button",
                    "video",
                    "button.play",
                ]
                for selector in selectors_to_try:
                    try:
                        elem = await page.query_selector(selector)
                        if elem:
                            await elem.click(timeout=2000)
                            await asyncio.sleep(2)
                            if intercepted_url:
                                break
                    except Exception:
                        pass

            # Wait briefly for any delayed network calls
            wait_intervals = 5
            while not intercepted_url and wait_intervals > 0:
                await asyncio.sleep(1)
                wait_intervals -= 1

            await browser.close()

            if intercepted_url:
                return {
                    "type": stream_type,
                    "url": intercepted_url,
                    "title": intercepted_url.split("/")[-1].split("?")[0] or "browser_media.mp4",
                    "headers": intercepted_headers
                }

    except Exception as e:
        logger.debug(f"Playwright sniffer error for {url}: {e}")

    return None
