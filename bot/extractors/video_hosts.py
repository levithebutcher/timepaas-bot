import re
import time
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


def is_matching_host(netloc: str, domain_set: set[str]) -> bool:
    """Checks if netloc matches or is a subdomain of domain_set entries."""
    netloc = netloc.lower().split(":")[0]
    for d in domain_set:
        if netloc == d or netloc.endswith("." + d):
            return True
    return False


async def resolve_streamtape(url: str) -> dict:
    """
    Extracts direct video URL from Streamtape.
    Tries official API first if credentials exist, then falls back to direct HTML JS parsing.
    """
    parsed = urlparse(url)
    clean_url = url

    # Normalize /v/ (view) to /e/ (embed)
    if "/v/" in parsed.path:
        clean_url = url.replace("/v/", "/e/")

    # 1. Official API Mode (if credentials provided)
    if STREAMTAPE_LOGIN and STREAMTAPE_KEY:
        try:
            file_id = parsed.path.strip("/").split("/")[1]
            api_ticket_url = f"https://api.strtape.tech/file/dlticket?file={file_id}&login={STREAMTAPE_LOGIN}&key={STREAMTAPE_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(api_ticket_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        ticket = result.get("ticket")
                        wait_time = result.get("wait_time", 5)
                        if ticket:
                            await asyncio.sleep(min(wait_time, 5))
                            api_dl_url = f"https://api.strtape.tech/file/dl?file={file_id}&ticket={ticket}&login={STREAMTAPE_LOGIN}&key={STREAMTAPE_KEY}"
                            async with session.get(api_dl_url) as dl_resp:
                                dl_data = await dl_resp.json()
                                direct_url = dl_data.get("result", {}).get("url")
                                if direct_url:
                                    logger.info("Streamtape stream resolved via official API.")
                                    return {
                                        "type": "direct",
                                        "url": direct_url,
                                        "title": f"streamtape_{file_id}.mp4",
                                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://streamtape.com/"}
                                    }
        except Exception as e:
            logger.debug(f"Streamtape API extraction failed, falling back to scraper: {e}")

    # 2. Zero-Config Web Scraper Mode (No API key needed)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://streamtape.com/"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                html = await response.text()

        # Streamtape stores the video link in document.getElementById('robotlink').innerHTML = ...
        # Or ideoolink, norobotlink
        # Pattern 1: Assignment to robotlink or ideoolink
        patterns = [
            r"document\.getElementById\(['\"](?:robotlink|ideoolink|norobotlink)['\"]\)[\s\.]*innerHTML\s*=\s*['\"]([^'\"]+)['\"]",
            r"getElementById\(['\"](?:robotlink|ideoolink)['\"]\)[\s\.]*inner(?:HTML)?\s*=\s*['\"]([^'\"]+)['\"]",
            r"['\"]((?:https?:)?//[^\s'\"]+streamtape\.com/get_video\?[^'\"]+)['\"]",
            r"['\"]((?:https?:)?//[^\s'\"]+/get_video\?[^'\"]+)['\"]"
        ]

        stream_url = None
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                stream_url = match.group(1)
                break

        # Check for multi-part string concatenation (common in Streamtape obfuscation)
        if not stream_url:
            concat_match = re.search(r"getElementById\(['\"](?:robotlink|ideoolink)['\"]\)[\s\.]*inner(?:HTML)?\s*=\s*(.+?);", html)
            if concat_match:
                raw_expr = concat_match.group(1)
                string_tokens = re.findall(r"['\"]([^'\"]+)['\"]", raw_expr)
                if string_tokens:
                    combined = "".join(string_tokens)
                    if "/get_video" in combined:
                        stream_url = combined

        if stream_url:
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            elif not stream_url.startswith("http"):
                stream_url = "https://streamtape.com" + stream_url

            # Unescape characters
            stream_url = stream_url.replace("\\/", "/").replace("&amp;", "&")

            file_id = parsed.path.strip("/").split("/")[-1]
            return {
                "type": "direct",
                "url": stream_url,
                "title": f"streamtape_{file_id}.mp4",
                "headers": headers
            }

    except Exception as e:
        logger.debug(f"Streamtape scraper failed for {url}: {e}")

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

        # Find m3u8 source URL
        m3u8_match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
        if m3u8_match:
            return {
                "type": "m3u8",
                "url": m3u8_match.group(1),
                "title": "streamwish_video.mp4",
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Streamwish extraction failed for {url}: {e}")
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

    return None
