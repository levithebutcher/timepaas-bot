import re
import time
import asyncio
import random
import string
import logging
from urllib.parse import urlparse
import aiohttp
from bot.config import DEFAULT_USER_AGENT, STREAMTAPE_LOGIN, STREAMTAPE_KEY

logger = logging.getLogger(__name__)

# Known domain patterns for video hosting providers
STREAMTAPE_DOMAINS = {
    "streamtape.com", "streamtape.to", "streamtape.net", "streamta.pe",
    "strtape.tech", "strtapeadblocker.xyz", "streamadblocker.xyz", "strcloud.link"
}

DOOD_DOMAINS = {
    "doodstream.com", "dood.to", "dood.so", "dood.la", "dood.ws",
    "doods.pro", "ds2play.com", "dood.video"
}

MIXDROP_DOMAINS = {
    "mixdrop.co", "mixdrop.to", "mixdrop.sx", "mixdrop.bz",
    "mixdrop.ch", "mixdrop.ag", "mixdrop.vc"
}

STREAMWISH_DOMAINS = {
    "streamwish.to", "streamwish.com", "strwish.com", "wishembed.pro",
    "swish.to", "awish.pro", "streamwish.online"
}

FILELIONS_DOMAINS = {
    "filelions.com", "filelions.to", "filelions.online", "filelions.site"
}

LULUSTREAM_DOMAINS = {
    "luluvid.com", "lulustream.com", "lulu.to", "luluvids.com",
    "pondr.org", "lulupdo.com"
}

STREAMFILES_DOMAINS = {
    "streamfiles.net", "streamfile.net", "streamfiles.org", "streamfiles.site"
}


def unpack_dean_edwards(payload: str) -> str:
    """
    Unpacks JavaScript obfuscated with Dean Edwards P.A.C.K.E.R.
    e.g. eval(function(p,a,c,k,e,d){...}('...', a, c, '...'.split('|')))
    """
    pattern = r"eval\(function\(p,a,c,k,e,d\)\{.*?return p\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']*)'\.split\('\|'\)"
    for m in re.finditer(pattern, payload, re.DOTALL):
        try:
            p, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split('|')

            def baseN(num, b):
                digits = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                res = ""
                while num > 0:
                    res = digits[num % b] + res
                    num //= b
                return res or "0"

            for idx in range(c - 1, -1, -1):
                key = baseN(idx, a)
                val = k[idx] if idx < len(k) and k[idx] else key
                p = re.sub(r"\b" + re.escape(key) + r"\b", val, p)
            return p
        except Exception:
            continue
    return ""


def is_matching_host(netloc: str, domain_set: set[str]) -> bool:
    """Checks if netloc matches or is a subdomain of domain_set entries."""
    netloc = netloc.lower().split(":")[0]
    for d in domain_set:
        if netloc == d or netloc.endswith("." + d):
            return True
    return False


def sanitize_streamtape_url(raw_url: str) -> str:
    """Neutralizes Streamtape decoy domains (stdreamtape, streamtadpe) and ensures valid HTTPS scheme."""
    if not raw_url:
        return ""
    url = re.sub(r"[\x00-\x1f\x7f-\x9f\r\n\t]", "", str(raw_url)).strip().strip("'\"")
    # Fix duplicate domain prefixes (e.g. streamtape.com/streamtape.com/get_video)
    url = re.sub(r"(?:https?://)?(?:[a-z0-9\-]+\.)*streamt[a-z0-9\-]*\.com/(?:[a-z0-9\-]+\.)*streamt[a-z0-9\-]*\.com/", "https://streamtape.com/", url)
    # Neutralize anti-scraper typo domains (stdreamtape.com, streamtadpe.com, streadmtape.com)
    url = re.sub(r"https?://(?:stdreamtape|streamtadpe|streadmtape|streamtapde)\.com", "https://streamtape.com", url)
    url = url.replace("stdreamtape.com", "streamtape.com").replace("streamtadpe.com", "streamtape.com")
    
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        if "/get_video" in url:
            if not url.startswith("/"):
                url = "/" + url
            url = "https://streamtape.com" + url
        else:
            url = "https://" + url

    return url.replace("\\/", "/").replace("&amp;", "&")


def evaluate_streamtape_js(expr: str) -> str:
    """Evaluates Streamtape string concatenation and .substring() offsets."""
    pattern = r"['\"]([^'\"]*)['\"](?:\s*\))?(?:\.substring\((\d+)(?:,\s*(\d+))?\))?"
    result = []
    for m in re.finditer(pattern, expr):
        s = m.group(1)
        sub1 = m.group(2)
        sub2 = m.group(3)
        if sub1 is not None:
            start = int(sub1)
            end = int(sub2) if sub2 is not None else None
            s = s[start:end] if end is not None else s[start:]
        result.append(s)
    return "".join(result)


async def resolve_streamtape(url: str) -> dict:
    """
    Extracts direct video URL from Streamtape.
    Tries official API first if credentials exist, then falls back to direct HTML JS parsing across mirrors,
    and finally to Playwright headless sniffer.
    """
    parsed = urlparse(url)

    # Extract actual clean file_id from /v/ID/filename or /e/ID
    parts = [p for p in parsed.path.split("/") if p and p not in ("v", "e")]
    if not parts:
        return None
    file_id = parts[0]

    # Extract original filename if present (e.g. 02.mp4)
    original_filename = parts[1] if len(parts) > 1 and "." in parts[1] else f"streamtape_{file_id}.mp4"
    clean_embed_url = f"https://streamtape.com/e/{file_id}"

    # 1. Official API Mode (if credentials provided)
    if STREAMTAPE_LOGIN and STREAMTAPE_KEY:
        try:
            api_ticket_url = f"https://api.strtape.tech/file/dlticket?file={file_id}&login={STREAMTAPE_LOGIN}&key={STREAMTAPE_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(api_ticket_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result") or {}
                        ticket = result.get("ticket")
                        wait_time = int(result.get("wait_time", 5))
                        if ticket:
                            # Respect wait_time + 1s buffer for ticket activation
                            await asyncio.sleep(wait_time + 1)
                            api_dl_url = f"https://api.strtape.tech/file/dl?file={file_id}&ticket={ticket}&login={STREAMTAPE_LOGIN}&key={STREAMTAPE_KEY}"
                            async with session.get(api_dl_url) as dl_resp:
                                dl_data = await dl_resp.json()
                                res_obj = dl_data.get("result") or {}
                                direct_url = res_obj.get("url")
                                file_name = res_obj.get("name") or original_filename
                                if direct_url:
                                    logger.info(f"Streamtape stream resolved via official API: {file_name}")
                                    return {
                                        "type": "direct",
                                        "url": direct_url,
                                        "title": file_name,
                                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"https://streamtape.com/v/{file_id}"}
                                    }
        except Exception as e:
            logger.warning(f"Streamtape API extraction error: {e}")

    # 2. Zero-Config Web Scraper across Streamtape domain mirrors
    mirrors = ["streamtape.com", "streamtape.to", "strtape.tech", "streamta.pe"]
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://streamtape.com/"
    }

    elem_ids = [
        "robotlink", "ideoolink", "norobotlink", "videolink",
        "ideoooolink", "cphdlk", "linko", "botlink"
    ]

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for domain in mirrors:
                for target_url in [f"https://{domain}/e/{file_id}", f"https://{domain}/v/{file_id}"]:
                    try:
                        async with session.get(target_url, allow_redirects=True) as response:
                            if response.status != 200:
                                continue
                            html = await response.text()
                    except Exception:
                        continue

                    # A. Check video#mainvideo tag src in HTML
                    vid_tag_match = re.search(r'<video[^>]+id=["\']mainvideo["\'][^>]+src=["\']([^"\']+)["\']', html)
                    if vid_tag_match:
                        raw_src = vid_tag_match.group(1)
                        if "/get_video" in raw_src:
                            clean_direct = sanitize_streamtape_url(raw_src)
                            return {
                                "type": "direct",
                                "url": clean_direct,
                                "title": original_filename,
                                "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"https://{domain}/"}
                            }

                    # B. Check script innerHTML assignments for known element IDs
                    stream_url = None
                    for eid in elem_ids:
                        assign_match = re.search(
                            r"document\.getElementById\(['\"]" + eid + r"['\"]\)\.innerHTML\s*=\s*(.+?);",
                            html
                        )
                        if assign_match:
                            expr = assign_match.group(1)
                            evaluated = evaluate_streamtape_js(expr)
                            if "/get_video" in evaluated:
                                stream_url = evaluated
                                break

                        # Check static div contents <div id="videolink">...</div>
                        tag_match = re.search(r"id=['\"]" + eid + r"['\"][^>]*>([^<]+)</div>", html)
                        if tag_match:
                            text = tag_match.group(1).strip()
                            if "/get_video" in text:
                                stream_url = text
                                break

                    if not stream_url:
                        # C. Broad /get_video regex fallback
                        match = re.search(r"['\"]((?:https?:)?//[^\s'\"]+/get_video\?[^'\"]+)['\"]", html)
                        if match:
                            stream_url = match.group(1)

                    if stream_url:
                        clean_direct = sanitize_streamtape_url(stream_url)
                        logger.info(f"Streamtape stream extracted via scraper: {original_filename}")
                        return {
                            "type": "direct",
                            "url": clean_direct,
                            "title": original_filename,
                            "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"https://{domain}/"}
                        }

    except Exception as e:
        logger.debug(f"Streamtape scraper failed for {url}: {e}")

    # 3. Playwright Fallback if static scraping didn't yield token
    try:
        from bot.extractors.browser_ext import extract_with_playwright
        logger.info(f"Triggering Playwright fallback for Streamtape {clean_embed_url}")
        res = await extract_with_playwright(clean_embed_url)
        if res and res.get("url"):
            res["title"] = original_filename
            return res
    except Exception as e:
        logger.debug(f"Playwright fallback failed for Streamtape: {e}")

    return None


async def resolve_doodstream(url: str) -> dict:
    """Extracts direct video URL from Doodstream (dood.to, doodstream.com)."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        # Convert /d/ to /e/
        clean_url = url.replace("/d/", "/e/")
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

            # Find pass_md5 token: '/pass_md5/' + token
            md5_match = re.search(r"/pass_md5/([^'\"]+)", html)
            if not md5_match:
                return None

            token = md5_match.group(1)
            parsed = urlparse(clean_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            pass_md5_url = f"{base_url}/pass_md5/{token}"

            async with session.get(pass_md5_url, headers={"Referer": clean_url}) as pass_resp:
                if pass_resp.status != 200:
                    return None
                direct_base = (await pass_resp.text()).strip()

            # Construct final URL with random string and token
            rand_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
            expiry = int(time.time() * 1000)
            final_url = f"{direct_base}{rand_str}?token={token}&expiry={expiry}"

            return {
                "type": "direct",
                "url": final_url,
                "title": "doodstream_video.mp4",
                "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": base_url}
            }
    except Exception as e:
        logger.debug(f"Doodstream extraction failed for {url}: {e}")
    return None


async def resolve_mixdrop(url: str) -> dict:
    """Extracts direct video URL from Mixdrop."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://mixdrop.co/"}
    try:
        clean_url = url.replace("/f/", "/e/")
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        # Find MDCore.wurl or direct stream assignment
        match = re.search(r'(?:MDCore\.wurl|MDCore\.vurl)\s*=\s*["\']([^"\']+)["\']', html)
        if match:
            stream_url = match.group(1)
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            return {
                "type": "direct",
                "url": stream_url,
                "title": "mixdrop_video.mp4",
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Mixdrop extraction failed for {url}: {e}")
    return None


async def resolve_streamwish(url: str) -> dict:
    """Extracts direct streaming manifest from Streamwish or FileLions."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        clean_url = url.replace("/f/", "/e/")
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        # Find m3u8 source URL in plain HTML or via Dean Edwards unpacker
        m3u8_matches = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
        if not m3u8_matches:
            unpacked = unpack_dean_edwards(html)
            if unpacked:
                m3u8_matches = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', unpacked)

        if m3u8_matches:
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            title = "streamwish_video.mp4"
            if title_match:
                title = title_match.group(1).strip()
                if not title.lower().endswith(".mp4"):
                    title += ".mp4"
            return {
                "type": "m3u8",
                "url": m3u8_matches[0],
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Streamwish extraction failed for {url}: {e}")
    return None


async def resolve_luluvid(url: str) -> dict:
    """Extracts direct m3u8 stream from LuluStream / LuluVid via unpacked JS."""
    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"{base_origin}/"}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        title = "lulustream_video.mp4"
        if title_match:
            raw_title = title_match.group(1).strip()
            clean_title = re.sub(r"\s*-\s*Lulustream(\.mp4)?", "", raw_title, flags=re.IGNORECASE).strip()
            if not clean_title.lower().endswith(".mp4"):
                clean_title += ".mp4"
            title = clean_title

        # Check if m3u8 is already directly present
        m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
        if not m3u8_matches:
            unpacked = unpack_dean_edwards(html)
            if unpacked:
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)

        if m3u8_matches:
            logger.info(f"LuluStream stream resolved: {title}")
            return {
                "type": "m3u8",
                "url": m3u8_matches[0],
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"LuluStream extraction failed for {url}: {e}")
    return None


async def resolve_streamfiles(url: str) -> dict:
    """Extracts direct m3u8 stream from StreamFiles."""
    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"{base_origin}/"}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        title = "streamfiles_video.mp4"
        if title_match:
            raw_title = title_match.group(1).strip()
            clean_title = re.sub(r"^(Watch|Download)\s+", "", raw_title, flags=re.IGNORECASE).strip()
            if not clean_title.lower().endswith(".mp4"):
                clean_title += ".mp4"
            title = clean_title

        m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
        if not m3u8_matches:
            unpacked = unpack_dean_edwards(html)
            if unpacked:
                m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)

        if m3u8_matches:
            logger.info(f"StreamFiles stream resolved: {title}")
            return {
                "type": "m3u8",
                "url": m3u8_matches[0],
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"StreamFiles extraction failed for {url}: {e}")
    return None


async def extract_from_video_hosts(url: str) -> dict:
    """
    Tier-0 Router: Checks if URL belongs to any specialized video hosting provider.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc

    if is_matching_host(netloc, STREAMTAPE_DOMAINS):
        logger.info(f"Target recognized as Streamtape: {url}")
        return await resolve_streamtape(url)

    if is_matching_host(netloc, DOOD_DOMAINS):
        logger.info(f"Target recognized as Doodstream: {url}")
        return await resolve_doodstream(url)

    if is_matching_host(netloc, MIXDROP_DOMAINS):
        logger.info(f"Target recognized as Mixdrop: {url}")
        return await resolve_mixdrop(url)

    if is_matching_host(netloc, STREAMWISH_DOMAINS) or is_matching_host(netloc, FILELIONS_DOMAINS):
        logger.info(f"Target recognized as Streamwish/FileLions: {url}")
        return await resolve_streamwish(url)

    if is_matching_host(netloc, LULUSTREAM_DOMAINS):
        logger.info(f"Target recognized as LuluStream/LuluVid: {url}")
        return await resolve_luluvid(url)

    if is_matching_host(netloc, STREAMFILES_DOMAINS):
        logger.info(f"Target recognized as StreamFiles: {url}")
        return await resolve_streamfiles(url)

    return None
