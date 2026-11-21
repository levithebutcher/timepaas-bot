import re
import asyncio
import logging
from urllib.parse import urlparse
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

AD_TRACKER_PATTERNS = (
    "googlesyndication.com", "doubleclick.net", "googleadservices.com",
    "google-analytics.com", "adservice.google", "pagead2.googlesyndication",
    "adnxs.com", "exoclick.com", "popcash.net", "popads.net",
    "propellerads.com", "juicyads.com", "trafficjunky.net", "trafficstars.com",
    "yandex.ru", "yandex.net", "clarity.ms", "scorecardresearch.com",
    "histats.com", "hotjar.com", "onesignal.com", "adsco.re",
    "/ads/", "/ad/", "/advert/", "/banner/", "adsterra.com", "monetag.com"
)

NON_MEDIA_EXTENSIONS = (
    ".js", ".mjs", ".ts", ".css", ".json", ".html", ".htm",
    ".txt", ".svg", ".xml", ".ico", ".woff", ".woff2", ".ttf",
    ".map", ".php", ".jsp", ".asp", ".aspx"
)

NON_MEDIA_MIMES = (
    "text/", "javascript", "application/javascript", "application/x-javascript",
    "application/json", "application/xml", "image/svg", "image/gif", "image/png",
    "image/jpeg", "image/webp", "image/x-icon", "font/"
)

VALID_MEDIA_EXTENSIONS = (
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".ts"
)

MEDIA_KEYWORDS = [
    ".m3u8", ".mp4", ".webm", ".mkv", ".zip", ".rar",
    "/get_video", "tapecontent.net", "pass_md5", "delivery"
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

            # Route blocker for aggressive ad networks and heavy fonts
            async def intercept_route(route):
                req_u = route.request.url.lower()
                r_type = route.request.resource_type
                if r_type in ("font",) or any(ad in req_u for ad in AD_TRACKER_PATTERNS):
                    try:
                        await route.abort()
                    except Exception:
                        pass
                else:
                    try:
                        await route.continue_()
                    except Exception:
                        pass

            try:
                await page.route("**/*", intercept_route)
            except Exception:
                pass

            # 1. Native browser download trigger listener
            async def handle_download(download):
                nonlocal intercepted_url, intercepted_filename, stream_type, intercepted_headers
                try:
                    fn = download.suggested_filename
                    if fn and any(fn.lower().endswith(ext) for ext in NON_MEDIA_EXTENSIONS):
                        logger.debug(f"Ignoring non-media download event: {fn}")
                        return
                    dl_url = download.url
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
                nonlocal intercepted_url, intercepted_headers, stream_type, intercepted_filename
                if intercepted_url:
                    return

                resp_url = response.url
                clean_url = resp_url.split("?")[0].lower()

                # Immediately drop ad networks, trackers, and analytics
                if any(ad in clean_url or ad in resp_url.lower() for ad in AD_TRACKER_PATTERNS):
                    return

                # Immediately drop non-media file extensions (scripts, styles, html, icons)
                if any(clean_url.endswith(ext) for ext in NON_MEDIA_EXTENSIONS):
                    return

                content_type = response.headers.get("content-type", "").lower()
                # Immediately drop non-media MIME types (javascript, text, html, images, fonts)
                if any(m in content_type for m in NON_MEDIA_MIMES):
                    return

                content_disp = response.headers.get("content-disposition", "").lower()

                # Check for m3u8 playlist
                if ".m3u8" in clean_url or "mpegurl" in content_type:
                    intercepted_url = resp_url
                    stream_type = "m3u8"
                    intercepted_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
                    logger.info(f"Playwright intercepted m3u8 stream: {resp_url[:60]}...")
                    return

                # Check for direct media stream
                is_media = (
                    any(clean_url.endswith(ext) for ext in VALID_MEDIA_EXTENSIONS)
                    or content_type.startswith("video/")
                    or any(k in clean_url for k in ("/get_video", "tapecontent.net", "pass_md5", "delivery"))
                )

                # Check for verified media attachment (never accept script or doc attachments)
                if not is_media and ("attachment" in content_disp or "application/force-download" in content_type or "octet-stream" in content_type):
                    fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', content_disp)
                    if fn_match:
                        cand_fn = fn_match.group(1).lower().strip()
                        if not any(cand_fn.endswith(ext) for ext in NON_MEDIA_EXTENSIONS) and any(cand_fn.endswith(ext) for ext in VALID_MEDIA_EXTENSIONS):
                            is_media = True
                            intercepted_filename = fn_match.group(1).strip()

                if is_media:
                    intercepted_url = resp_url
                    stream_type = "direct"
                    intercepted_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
                    logger.info(f"Playwright intercepted media stream: {resp_url[:60]}...")

            page.on("response", handle_response)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            except Exception as e:
                logger.debug(f"Playwright navigation timeout/error for {url}: {e}")

            # Grab page title for clean filename
            try:
                raw_t = await page.title()
                if raw_t:
                    clean_t = re.sub(r"[^\w\s\.\-]", "", raw_t).strip()
                    if clean_t.lower() not in ("loading...", "loading", "please wait", "just a moment..."):
                        if not any(clean_t.lower().endswith(ext) for ext in (".mp4", ".mkv", ".zip")):
                            clean_t += ".mp4"
                        page_title = clean_t
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

            # Dismiss 18+ age verification or warning overlays if present
            try:
                age_selectors = [
                    "button.age-gate-confirm",
                    ".age-gate-confirm",
                    "#verification button",
                    ".verification button",
                    "#age-gate button",
                    ".age-gate button",
                    "#verification",
                    ".verification",
                    "#age-gate",
                    ".age-gate",
                    "button:has-text('18')",
                    "button:has-text('I am 18')",
                    "button:has-text('Enter')",
                    "button:has-text('Agree')",
                    "button:has-text('Accept')",
                    "button:has-text('Confirm')",
                    "a:has-text('I am 18')",
                    "a:has-text('Enter')",
                ]
                for a_sel in age_selectors:
                    try:
                        elem = await page.query_selector(a_sel)
                        if elem:
                            btn = await elem.query_selector("button, a.btn, .btn") if elem.tag_name not in ("button", "a") else elem
                            if btn:
                                await btn.click(timeout=1500)
                                await asyncio.sleep(1.0)
                                logger.info(f"Playwright dismissed age verification overlay via {a_sel}")
                                break
                    except Exception:
                        pass
            except Exception:
                pass

            # Check for embedded iframes pointing to video hosts
            try:
                # 1. Check all frames in Playwright context
                for frame in page.frames:
                    try:
                        f_url = frame.url
                        if f_url and f_url != "about:blank" and not f_url.startswith("chrome"):
                            from bot.extractors.video_hosts import extract_from_video_hosts
                            f_res = await extract_from_video_hosts(f_url)
                            if f_res and f_res.get("url"):
                                logger.info(f"Playwright detected embedded video host frame: {f_url}")
                                await browser.close()
                                return f_res
                    except Exception:
                        pass

                # 2. Check DOM iframe elements
                iframes = await page.eval_on_selector_all("iframe", "els => els.map(e => e.src || e.getAttribute('data-src'))")
                for ifr_src in iframes:
                    if ifr_src:
                        if ifr_src.startswith("//"):
                            ifr_src = "https:" + ifr_src
                        from bot.extractors.video_hosts import extract_from_video_hosts
                        host_res = await extract_from_video_hosts(ifr_src)
                        if host_res and host_res.get("url"):
                            logger.info(f"Playwright detected embedded video host iframe: {ifr_src}")
                            await browser.close()
                            return host_res
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
                    "#player",
                    ".playerjs-play",
                    ".pjs-play-btn",
                    "div[id*='player']",
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

                # Viewport center click fallback to trigger custom canvas or overlay video players
                if not intercepted_url:
                    try:
                        await page.mouse.click(640, 360)
                        await asyncio.sleep(1.5)
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

            # Final check: Inspect rendered DOM HTML content for m3u8 or Playerjs file configuration
            if not intercepted_url:
                try:
                    rendered_html = await page.content()
                    if rendered_html:
                        m3u8_in_dom = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', rendered_html)
                        if m3u8_in_dom:
                            intercepted_url = m3u8_in_dom[0]
                            stream_type = "m3u8"
                            intercepted_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
                            logger.info(f"Playwright captured m3u8 from rendered DOM content: {intercepted_url[:60]}...")
                        else:
                            pjs_match = re.findall(r'(?:file|src)\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^\s"\'<>]*)["\']', rendered_html)
                            if pjs_match:
                                intercepted_url = pjs_match[0]
                                stream_type = "m3u8" if ".m3u8" in intercepted_url else "direct"
                                intercepted_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
                                logger.info(f"Playwright captured Playerjs file from rendered DOM: {intercepted_url[:60]}...")
                except Exception as e:
                    logger.debug(f"Error checking rendered DOM content: {e}")

            await browser.close()

            if intercepted_url:
                final_title = intercepted_filename or page_title or "browser_media.mp4"
                if not any(final_title.lower().endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".zip", ".rar")):
                    final_title = re.sub(r"\.[a-zA-Z0-9]+$", "", final_title) + ".mp4"
                if any(k in final_title.lower() for k in ("loading", "please wait", "just a moment")):
                    clean_segment = url.split("?")[0].rstrip("/").split("/")[-1]
                    final_title = f"{clean_segment}.mp4" if clean_segment else "browser_media.mp4"

                return {
                    "type": stream_type,
                    "url": intercepted_url,
                    "title": final_title,
                    "headers": intercepted_headers
                }

    except Exception as e:
        logger.debug(f"Playwright sniffer error for {url}: {e}")

    return None
