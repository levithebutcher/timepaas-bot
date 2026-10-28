import re
import asyncio
import logging
from urllib.parse import urlparse
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

MEDIA_KEYWORDS = [
    ".m3u8", ".mp4", ".webm", ".mkv", ".zip", ".rar",
    "/get_video", "tapecontent.net", "pass_md5", "delivery",
    "/download", "/dl/", "attachment"
]


async def extract_with_playwright(url: str, timeout_seconds: int = 25) -> dict:
    """
    Spawns headless Chromium to intercept network media streams, direct download buttons,
    countdown triggers, and native browser download events.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed in the current environment.")
        return None

    intercepted_url = None
    intercepted_filename = None
    intercepted_headers = {}
    stream_type = "direct"
    page_title = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1280, "height": 720},
                accept_downloads=True
            )
            page = await context.new_page()

            # 1. Native browser download trigger listener
            async def handle_download(download):
                nonlocal intercepted_url, intercepted_filename, stream_type, intercepted_headers
                try:
                    dl_url = download.url
                    fn = download.suggested_filename
                    if dl_url:
                        intercepted_url = dl_url
                        intercepted_filename = fn
                        stream_type = "direct"
                        intercepted_headers = {
                            "User-Agent": DEFAULT_USER_AGENT,
                            "Referer": url
                        }
                        logger.info(f"Playwright caught native browser download event: {fn} -> {dl_url[:60]}...")
                except Exception as e:
                    logger.debug(f"Error handling download event: {e}")

            page.on("download", handle_download)

            # 2. Network traffic stream sniffer
            async def handle_response(response):
                nonlocal intercepted_url, intercepted_headers, stream_type
                if intercepted_url:
                    return

                resp_url = response.url
                clean_url = resp_url.split("?")[0].lower()
                content_type = response.headers.get("content-type", "").lower()
                content_disp = response.headers.get("content-disposition", "").lower()

                for kw in MEDIA_KEYWORDS:
                    if (
                        kw in clean_url
                        or "video/" in content_type
                        or "application/x-mpegurl" in content_type
                        or "attachment" in content_disp
                        or "application/force-download" in content_type
                    ):
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

            # Grab page title for clean filename
            try:
                raw_t = await page.title()
                if raw_t:
                    page_title = re.sub(r"[^\w\s\.\-]", "", raw_t).strip()
                    if not any(page_title.lower().endswith(ext) for ext in (".mp4", ".mkv", ".zip")):
                        page_title += ".mp4"
            except Exception:
                page_title = None

            # Check if page has an active countdown timer (e.g. "Please wait 5s...")
            try:
                has_countdown = await page.evaluate("""() => {
                    const text = document.body ? document.body.innerText.toLowerCase() : '';
                    return /wait\\s*\\d+\\s*(?:seconds?|s)/i.test(text) || /countdown/i.test(text);
                }""")
                if has_countdown:
                    logger.info("Countdown timer detected on page, waiting 4s for download button to activate...")
                    await asyncio.sleep(4)
            except Exception:
                pass

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
                    "button:has-text('Direct Download')",
                    "a:has-text('Direct Download')",
                    "button:has-text('Fast Download')",
                    "a:has-text('Fast Download')",
                    "button:has-text('Generate Link')",
                    "a:has-text('Generate Link')",
                    "a[download]",
                    ".btn-download",
                    "#download",
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
            wait_intervals = 5
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
                final_title = intercepted_filename or page_title or intercepted_url.split("/")[-1].split("?")[0] or "browser_media.mp4"
                return {
                    "type": stream_type,
                    "url": intercepted_url,
                    "title": final_title,
                    "headers": intercepted_headers
                }

    except Exception as e:
        logger.debug(f"Playwright sniffer error for {url}: {e}")

    return None
