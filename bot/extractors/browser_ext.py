import asyncio
import logging
from urllib.parse import urlparse
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

MEDIA_KEYWORDS = [
    ".m3u8", ".mp4", ".webm", ".mkv", ".zip", ".rar",
    "/get_video", "tapecontent.net", "pass_md5", "delivery"
]


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
                        intercepted_headers = {
                            "User-Agent": DEFAULT_USER_AGENT,
                            "Referer": url
                        }
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

            # Check if a video element with a source already exists in the DOM
            try:
                dom_video_src = await page.evaluate("""() => {
                    const v = document.querySelector('video#mainvideo') || document.querySelector('video');
                    if (v && v.src && v.src.length > 5 && !v.src.startsWith('blob:')) {
                        return v.src;
                    }
                    const s = document.querySelector('video source');
                    if (s && s.src && s.src.length > 5 && !s.src.startsWith('blob:')) {
                        return s.src;
                    }
                    return null;
                }""")
                if dom_video_src:
                    intercepted_url = dom_video_src
                    logger.info(f"Playwright found direct video src in DOM: {dom_video_src[:60]}...")
            except Exception as e:
                logger.debug(f"Error evaluating DOM video src: {e}")

            # Try clicking play or download elements if not yet intercepted
            if not intercepted_url:
                selectors_to_try = [
                    "button:has-text('Download')",
                    "a:has-text('Download')",
                    "button:has-text('Play')",
                    ".jw-display-icon-container",
                    ".jw-preview",
                    ".jw-video",
                    ".vjs-big-play-button",
                    ".play-wrapper",
                    "#mainvideo",
                    "video",
                    "button.play",
                    "div[class*='play']",
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

            # Wait briefly for any delayed network calls or DOM updates
            wait_intervals = 6
            while not intercepted_url and wait_intervals > 0:
                await asyncio.sleep(1)
                wait_intervals -= 1
                try:
                    dom_src = await page.evaluate("() => document.querySelector('video#mainvideo')?.src || document.querySelector('video')?.src")
                    if dom_src and len(dom_src) > 5 and not dom_src.startswith("blob:"):
                        intercepted_url = dom_src
                        logger.info(f"Playwright captured video src from DOM update: {dom_src[:60]}...")
                        break
                except Exception:
                    pass

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
