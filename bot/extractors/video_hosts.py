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
    "mixdrop.ch", "mixdrop.ag", "mixdrop.vc", "mixdrop.club",
    "mixdrop.pe", "mixdrop.is", "mxdrop.click", "mxdrop.to"
}

ARCHIVEBATE_DOMAINS = {
    "archivebate.com", "www.archivebate.com"
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

VIDARA_DOMAINS = {
    "vidara.to", "vidara.so", "vidara.net", "vidara.org",
    "gasobni.com"
}

FILEMOON_DOMAINS = {
    "filemoon.sx", "filemoon.to", "filemoon.in", "moonplayer.top",
    "filemoon.top", "filemoon.wf", "filemoon.nl"
}

VOE_DOMAINS = {
    "voe.sx", "roe.sx", "voe-unblock.com", "turing.voe.sx", "repacki.org",
    "audaciousdefectiveluncheon.com"
}

MP4UPLOAD_DOMAINS = {
    "mp4upload.com", "www.mp4upload.com"
}

VIDGUARD_DOMAINS = {
    "vidguard.to", "vgembed.com", "vembed.net", "listeamed.net", "v6embed.xyz"
}

GOFILE_DOMAINS = {
    "gofile.io", "www.gofile.io"
}

KRAKENFILES_DOMAINS = {
    "krakenfiles.com", "www.krakenfiles.com"
}

PIXELDRAIN_DOMAINS = {
    "pixeldrain.com", "www.pixeldrain.com"
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
    """Extracts direct video URL from Mixdrop (including Dean Edwards packed JS)."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://mixdrop.co/"}
    try:
        clean_url = url.replace("/f/", "/e/")
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        unpacked = unpack_dean_edwards(html) or html

        # Find MDCore.wurl, MDCore.vurl or direct stream assignment
        match = re.search(r'(?:MDCore\.wurl|MDCore\.vurl|wurl|vurl)\s*=\s*["\']([^"\']+)["\']', unpacked)
        if match:
            stream_url = match.group(1)
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url

            # Extract clean video filename if present in MDCore.vfile or page title
            fn_match = re.search(r'MDCore\.vfile\s*=\s*["\']([^"\']+)["\']', unpacked)
            title = fn_match.group(1) if fn_match else "mixdrop_video.mp4"
            if not title.lower().endswith(".mp4"):
                title += ".mp4"

            return {
                "type": "direct",
                "url": stream_url,
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Mixdrop extraction failed for {url}: {e}")
    return None


async def resolve_archivebate(url: str) -> dict:
    """
    Tier-0 Extractor for Archivebate (https://www.archivebate.com/).
    Extracts underlying media host (e.g. Mixdrop) from the download form and iframes,
    then automatically decrypts and returns the direct video stream.
    """
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://www.archivebate.com/"
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        # Extract title
        title = "archivebate_video.mp4"
        title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        if title_m:
            raw_title = title_m.group(1).split("webcam recordings")[0].strip(" ,-|")
            if not raw_title:
                raw_title = title_m.group(1).split("|")[0].strip()
            if raw_title:
                clean_title = re.sub(r'[^\w\s\.\-]', '', raw_title).strip().replace(" ", "_")
                if clean_title:
                    title = f"{clean_title}.mp4"

        # 1. Search for fid input in download form
        embedded_url = None
        fid_match = re.search(r'name=[\'"]fid[\'"][^>]*value=[\'"]([^\'"]+)[\'"]', html)
        if fid_match:
            embedded_url = fid_match.group(1).strip()

        # 2. Search for iframe src pointing to video hosts
        if not embedded_url:
            ifr_matches = re.findall(r'<iframe[^>]*src=[\'"]([^\'"]+)[\'"]', html)
            for ifr in ifr_matches:
                if any(dh in ifr.lower() for dh in ("mixdrop", "mxdrop", "streamtape", "strtape", "dood", "streamwish", "filelions", "vidara")):
                    embedded_url = ifr.strip()
                    break
            if not embedded_url and ifr_matches:
                embedded_url = ifr_matches[0].strip()

        if embedded_url:
            logger.info(f"Archivebate resolved underlying host: {embedded_url}")
            host_res = await extract_from_video_hosts(embedded_url)
            if host_res and host_res.get("url"):
                if title and title != "archivebate_video.mp4":
                    host_res["title"] = title
                return host_res

    except Exception as e:
        logger.warning(f"Archivebate extraction failed for {url}: {e}")

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


async def resolve_vidara(url: str) -> dict:
    """
    Tier-0 Fast Resolver for Vidara.to / Gasobni video streams.
    Directly queries the internal /api/stream endpoint in ~0.05s, completely bypassing headless browser.
    """
    try:
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        filecode = segments[-1] if segments else ""
        if "." in filecode:
            filecode = filecode.rsplit(".", 1)[0]

        if not filecode:
            return None

        api_url = "https://gasobni.com/api/stream"
        payload = {"filecode": filecode}
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Origin": "https://gasobni.com",
            "Referer": f"https://gasobni.com/e/{filecode}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8.0)) as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    streaming_url = data.get("streaming_url")
                    title = data.get("title") or f"{filecode}.mp4"
                    if not title.lower().endswith((".mp4", ".mkv")):
                        title += ".mp4"

                    if streaming_url:
                        logger.info(f"Vidara stream resolved via direct API: {title}")
                        return {
                            "type": "m3u8" if ".m3u8" in streaming_url else "direct",
                            "url": streaming_url,
                            "title": title,
                            "headers": {
                                "User-Agent": DEFAULT_USER_AGENT,
                                "Referer": "https://gasobni.com/"
                            }
                        }
    except Exception as e:
        logger.debug(f"Vidara fast extraction failed for {url}: {e}")
    return None


async def resolve_filemoon(url: str) -> dict:
    """Extracts direct streaming manifest or mp4 from Filemoon."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        clean_url = url.replace("/d/", "/e/")
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        unpacked = unpack_dean_edwards(html) or html
        m3u8_m = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', unpacked)
        if not m3u8_m:
            m3u8_m = re.findall(r'file:\s*["\']([^"\']+)["\']', unpacked)

        if m3u8_m:
            stream_url = m3u8_m[0]
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = "filemoon_video.mp4"
            if title_m:
                t = title_m.group(1).split("-")[0].strip()
                if t:
                    title = f"{re.sub(r'[^\\w\\s\\.\\-]', '', t).strip().replace(' ', '_')}.mp4"
            return {
                "type": "m3u8" if ".m3u8" in stream_url else "direct",
                "url": stream_url,
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Filemoon extraction failed for {url}: {e}")
    return None


async def resolve_voe(url: str) -> dict:
    """Extracts direct HLS manifest from Voe / Roe."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        clean_url = url.replace("/e/", "/").replace("/d/", "/")
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        m3u8_m = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
        if not m3u8_m:
            b64_matches = re.findall(r"window\\.location\\.href\\s*=\\s*['\"](https?://[^'\"]+)['\"]", html)
            if b64_matches:
                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                    async with session.get(b64_matches[0], allow_redirects=True) as resp2:
                        html2 = await resp2.text()
                        m3u8_m = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html2)

        if m3u8_m:
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = "voe_video.mp4"
            if title_m:
                t = title_m.group(1).split("|")[0].strip()
                if t:
                    title = f"{re.sub(r'[^\\w\\s\\.\\-]', '', t).strip().replace(' ', '_')}.mp4"
            return {
                "type": "m3u8",
                "url": m3u8_m[0],
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Voe extraction failed for {url}: {e}")
    return None


async def resolve_mp4upload(url: str) -> dict:
    """Extracts direct MP4 stream from Mp4Upload."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        mp4_m = re.findall(r'player\\.src\\(\\{\\s*type:\\s*["\']video/mp4["\'],\\s*src:\\s*["\']([^"\']+)["\']', html)
        if not mp4_m:
            mp4_m = re.findall(r'["\'](https?://[^\\s"\'<>]+\\.mp4[^\\s"\'<>]*)["\']', html)

        if mp4_m:
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = "mp4upload_video.mp4"
            if title_m:
                t = title_m.group(1).split("-")[0].strip()
                if t:
                    title = f"{re.sub(r'[^\\w\\s\\.\\-]', '', t).strip().replace(' ', '_')}.mp4"
            return {
                "type": "direct",
                "url": mp4_m[0],
                "title": title,
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Mp4Upload extraction failed for {url}: {e}")
    return None


async def resolve_vidguard(url: str) -> dict:
    """Extracts stream from Vidguard / Vgembed."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        clean_url = url.replace("/d/", "/e/")
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(clean_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        unpacked = unpack_dean_edwards(html) or html
        stream_m = re.findall(r'["\'](https?://[^"\']+\\.(?:m3u8|mp4)[^"\']*)["\']', unpacked)
        if stream_m:
            s_url = stream_m[0]
            return {
                "type": "m3u8" if ".m3u8" in s_url else "direct",
                "url": s_url,
                "title": "vidguard_video.mp4",
                "headers": headers
            }
    except Exception as e:
        logger.debug(f"Vidguard extraction failed for {url}: {e}")
    return None


async def resolve_gofile(url: str) -> dict:
    """Extracts direct download link from Gofile."""
    try:
        content_id = url.strip("/").split("/")[-1]
        api_url = f"https://api.gofile.io/contents/{content_id}?wt=4fd6sg89d7s6"
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    if status == "ok":
                        children = data.get("data", {}).get("children", {})
                        for child in children.values():
                            link = child.get("link")
                            name = child.get("name") or "gofile_video.mp4"
                            if link:
                                return {
                                    "type": "direct",
                                    "url": link,
                                    "title": name,
                                    "headers": {"Cookie": f"accountToken={data.get('data', {}).get('token', '')}"}
                                }
    except Exception as e:
        logger.debug(f"Gofile extraction failed for {url}: {e}")
    return None


async def resolve_krakenfiles(url: str) -> dict:
    """Extracts direct video download from Krakenfiles."""
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

        src_m = re.findall(r'<source[^>]*src=[\'"]([^\'"]+)[\'"]', html)
        if src_m:
            stream_url = src_m[0]
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            return {
                "type": "direct",
                "url": stream_url,
                "title": "krakenfiles_video.mp4",
                "headers": headers
            }

        post_url_m = re.search(r'data-url=[\'"]([^\'"]+)[\'"]', html)
        token_m = re.search(r'id=[\'"]token[\'"][^>]*value=[\'"]([^\'"]+)[\'"]', html)
        if post_url_m and token_m:
            dl_post = "https:" + post_url_m.group(1) if post_url_m.group(1).startswith("//") else post_url_m.group(1)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                async with session.post(dl_post, data={"token": token_m.group(1)}) as p_resp:
                    if p_resp.status == 200:
                        p_data = await p_resp.json()
                        dl_url = p_data.get("url")
                        if dl_url:
                            return {
                                "type": "direct",
                                "url": dl_url,
                                "title": "krakenfiles_video.mp4",
                                "headers": headers
                            }
    except Exception as e:
        logger.debug(f"Krakenfiles extraction failed for {url}: {e}")
    return None


async def resolve_pixeldrain(url: str) -> dict:
    """Extracts direct file stream from Pixeldrain."""
    try:
        file_id = url.strip("/").split("/")[-1]
        direct_url = f"https://pixeldrain.com/api/file/{file_id}"
        return {
            "type": "direct",
            "url": direct_url,
            "title": f"pixeldrain_{file_id}.mp4",
            "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://pixeldrain.com/"}
        }
    except Exception as e:
        logger.debug(f"Pixeldrain extraction failed for {url}: {e}")
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

    if is_matching_host(netloc, VIDARA_DOMAINS):
        logger.info(f"Target recognized as Vidara/Gasobni: {url}")
        return await resolve_vidara(url)

    if is_matching_host(netloc, ARCHIVEBATE_DOMAINS):
        logger.info(f"Target recognized as Archivebate: {url}")
        return await resolve_archivebate(url)

    if is_matching_host(netloc, FILEMOON_DOMAINS):
        logger.info(f"Target recognized as Filemoon: {url}")
        return await resolve_filemoon(url)

    if is_matching_host(netloc, VOE_DOMAINS):
        logger.info(f"Target recognized as Voe/Roe: {url}")
        return await resolve_voe(url)

    if is_matching_host(netloc, MP4UPLOAD_DOMAINS):
        logger.info(f"Target recognized as Mp4Upload: {url}")
        return await resolve_mp4upload(url)

    if is_matching_host(netloc, VIDGUARD_DOMAINS):
        logger.info(f"Target recognized as VidGuard: {url}")
        return await resolve_vidguard(url)

    if is_matching_host(netloc, GOFILE_DOMAINS):
        logger.info(f"Target recognized as Gofile: {url}")
        return await resolve_gofile(url)

    if is_matching_host(netloc, KRAKENFILES_DOMAINS):
        logger.info(f"Target recognized as Krakenfiles: {url}")
        return await resolve_krakenfiles(url)

    if is_matching_host(netloc, PIXELDRAIN_DOMAINS):
        logger.info(f"Target recognized as Pixeldrain: {url}")
        return await resolve_pixeldrain(url)

    return None
