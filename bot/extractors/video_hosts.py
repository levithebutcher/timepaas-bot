import re
import json
import base64
import time
import asyncio
import random
import string
import logging
from urllib.parse import urlparse
import aiohttp
from bot.config import DEFAULT_USER_AGENT, STREAMTAPE_LOGIN, STREAMTAPE_KEY, LPLAYGO_KEY, STREAMFILE_KEY

logger = logging.getLogger(__name__)

# Known domain patterns for video hosting providers
STREAMTAPE_DOMAINS = {
    # Official & Primary Mirrors
    "streamtape.com", "streamtape.to", "streamtape.net", "streamtape.xyz",
    "streamtape.site", "streamtape.cc", "streamta.pe", "streamta.com", "streamta.xyz",
    # Shorthand Strtape / Strcloud
    "strtape.tech", "strtape.com", "strtape.xyz", "strtape.site", "strtape.net", "strtape.link",
    "strcloud.link", "strcloud.in", "strcloud.club", "strcloud.xyz",
    # Taped / Tape mirrors (e.g. tapedstream)
    "tapedstream.com", "tapedstream.xyz", "tapedstream.net", "tapestream.net", "tapecontent.net",
    "stape.fun", "stape.site", "stape.net",
    # Anti-Ad & Proxy mirrors
    "strtapeadblocker.xyz", "streamadblocker.xyz", "streamnoads.com",
    "adblockstreamtape.com", "adblockeronstape.com", "watchadsontape.com",
    "tapeadvertisement.com", "tapeblocker.com", "tapenoads.com", "tapewithadblock.org"
}

DOOD_DOMAINS = {
    "doodstream.com", "dood.to", "dood.so", "dood.la", "dood.ws",
    "doods.pro", "ds2play.com", "dood.video"
}

MIXDROP_DOMAINS = {
    "mixdrop.co", "mixdrop.to", "mixdrop.sx", "mixdrop.bz",
    "mixdrop.ch", "mixdrop.ag", "mixdrop.vc", "mixdrop.club",
    "mixdrop.pe", "mixdrop.is", "mxdrop.click", "mxdrop.to",
    "mdzsmutpcvykb.net", "mxcontent.net"
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
    # LuluVideo & LuluVdo mirrors
    "luluvdo.com", "luluvideo.com", "luluvideo.net", "luluvideo.org",
    "luluvid.com", "luluvid.net", "luluvids.com", "luluvids.net",
    "luluvd.com", "luluvd.net", "luluvdoo.com", "luluvido.com",
    "luluvido.net", "luluvido.org", "luluvdo.net", "luluvdo.org",
    # LuluStream & mirrors
    "lulustream.com", "lulustream.net", "lulustream.org", "lulustream.to",
    "lulu.to", "lulu.st", "lulusp.com", "pondr.org", "lulupdo.com",
    "streamhihi.com", "cdn1.site",
    # Lplaygo mirrors
    "lplaygo.com", "lplaygo.net", "lplaygo.org"
}

STREAMFILES_DOMAINS = {
    "streamfiles.net", "streamfile.net", "streamfiles.org", "streamfiles.site"
}

VIDARA_DOMAINS = {
    "vidara.to", "vidara.so", "vidara.net", "vidara.org",
    "gasobni.com", "vidara.cc", "vidara.click", "vidara.xyz", "vidara.live", "vidara.co"
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

EPORNER_DOMAINS = {
    "eporner.com", "www.eporner.com", "eporner.net", "eporner.org",
    "eporner.tv", "eporner.xxx"
}

STREAMCASH_DOMAINS = {
    "streamcash.to", "streamcash.net", "streamcash.cc", "streamcash.org"
}

LIVECAMRIPS_DOMAINS = {
    "livecamrips.to", "livecamrips.com", "livecamrips.net", "livecamrips.org"
}

UQLOAD_DOMAINS = {
    "uqload.vc", "uqload.to", "uqload.com", "uqload.io", "uqload.co",
    "uqload.net", "uqload.ws", "uqload.cx", "uqload.org"
}

ABSTREAM_DOMAINS = {
    "abstream.to", "abstream.net", "abstream.org", "streambucket.xyz"
}

THOTPLAY_DOMAINS = {
    "thotplay.com", "www.thotplay.com", "thotplay.org", "www.thotplay.org",
    "thotplay.net", "www.thotplay.net"
}


def is_thotplay_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return is_matching_host(netloc, THOTPLAY_DOMAINS) or "thotplay" in netloc


def is_streamcash_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return is_matching_host(netloc, STREAMCASH_DOMAINS) or "streamcash" in netloc


def is_livecamrips_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return is_matching_host(netloc, LIVECAMRIPS_DOMAINS) or "livecamrips" in netloc


def is_uqload_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return is_matching_host(netloc, UQLOAD_DOMAINS) or "uqload" in netloc


def is_abstream_host(netloc: str) -> bool:
    netloc = netloc.lower().split(":")[0]
    return is_matching_host(netloc, ABSTREAM_DOMAINS) or "abstream" in netloc


def unpack_dean_edwards(payload: str) -> str:
    """
    Unpacks JavaScript obfuscated with Dean Edwards P.A.C.K.E.R.
    Handles multiple blocks, single/double quotes, and returns all unpacked code.
    e.g. eval(function(p,a,c,k,e,d){...}('...', a, c, '...'.split('|')))
    """
    pattern = r"eval\(function\(p,a,c,k,e,d\)\{.*?return p\}\((['\"])(.*?)\1,\s*(\d+),\s*(\d+),\s*(['\"])(.*?)\5\.split\(['\"]\|['\"]\)"
    unpacked_blocks = []
    for m in re.finditer(pattern, payload, re.DOTALL):
        try:
            p, a, c, k = m.group(2), int(m.group(3)), int(m.group(4)), m.group(6).split('|')

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
            unpacked_blocks.append(p)
        except Exception:
            continue
    return "\n".join(unpacked_blocks)


def sanitize_title(raw_title: str, default: str = "video.mp4") -> str:
    """Sanitizes raw scraped titles into clean, valid filenames."""
    if not raw_title:
        return default
    clean = re.sub(r"[^\w\s\.\-]", "", raw_title).strip().replace(" ", "_")
    if not clean:
        return default
    if not clean.lower().endswith((".mp4", ".mkv", ".webm")):
        clean += ".mp4"
    return clean


def is_matching_host(netloc: str, domain_set: set[str]) -> bool:
    """Checks if netloc matches or is a subdomain of domain_set entries."""
    netloc = netloc.lower().split(":")[0]
    for d in domain_set:
        if netloc == d or netloc.endswith("." + d):
            return True
    return False


def is_streamtape_host(netloc: str) -> bool:
    """Checks if netloc matches Streamtape domain set or mirror naming patterns."""
    netloc = netloc.lower().split(":")[0]
    if is_matching_host(netloc, STREAMTAPE_DOMAINS):
        return True
    if any(k in netloc for k in ("streamtape", "strtape", "tapedstream", "tapestream", "watchadsontape", "strcloud", "stape.fun")):
        return True
    if "tape" in netloc and ("stream" in netloc or "cloud" in netloc or "ad" in netloc):
        return True
    return False


def is_luluvid_host(netloc: str) -> bool:
    """Checks if netloc matches LuluStream / LuluVideo / Lplaygo domain set or mirror naming patterns."""
    netloc = netloc.lower().split(":")[0]
    if is_matching_host(netloc, LULUSTREAM_DOMAINS):
        return True
    if any(k in netloc for k in ("luluvdo", "luluvideo", "lulustream", "luluvid", "luluvd", "lulupdo", "luluvido", "lplaygo")):
        return True
    return False


def sanitize_streamtape_url(raw_url: str, default_domain: str = "streamtape.com") -> str:
    """Neutralizes Streamtape decoy domains (stdreamtape, streamtadpe) and ensures valid HTTPS scheme."""
    if not raw_url:
        return ""
    url = re.sub(r"[\x00-\x1f\x7f-\x9f\r\n\t]", "", str(raw_url)).strip().strip("'\"")
    # Fix duplicate domain prefixes (e.g. streamtape.com/streamtape.com/get_video)
    url = re.sub(r"(?:https?://)?(?:[a-z0-9\-]+\.)*streamt[a-z0-9\-]*\.com/(?:[a-z0-9\-]+\.)*streamt[a-z0-9\-]*\.com/", f"https://{default_domain}/", url)
    # Neutralize anti-scraper typo domains (stdreamtape.com, streamtadpe.com, streadmtape.com)
    url = re.sub(r"https?://(?:stdreamtape|streamtadpe|streadmtape|streamtapde)\.com", f"https://{default_domain}", url)
    url = url.replace("stdreamtape.com", default_domain).replace("streamtadpe.com", default_domain)
    
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        if "/get_video" in url:
            if not url.startswith("/"):
                url = "/" + url
            url = f"https://{default_domain}" + url
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
    input_domain = parsed.netloc.lower().split(":")[0]
    candidate_domains = [input_domain] if input_domain else []
    known_mirrors = [
        "streamtape.com", "streamtape.to", "strtape.tech", "streamta.pe",
        "tapedstream.com", "strcloud.link", "stape.fun", "streamtape.net", "streamtape.xyz"
    ]
    for d in known_mirrors:
        if d not in candidate_domains:
            candidate_domains.append(d)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"https://{input_domain or 'streamtape.com'}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    elem_ids = [
        "robotlink", "ideoolink", "norobotlink", "videolink",
        "ideoooolink", "cphdlk", "linko", "botlink"
    ]

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for domain in candidate_domains:
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
                            clean_direct = sanitize_streamtape_url(raw_src, default_domain=domain)
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
                        clean_direct = sanitize_streamtape_url(stream_url, default_domain=domain)
                        logger.info(f"Streamtape stream extracted via scraper ({domain}): {original_filename}")
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
        pw_target = f"https://{input_domain}/e/{file_id}" if input_domain else clean_embed_url
        logger.info(f"Triggering Playwright fallback for Streamtape {pw_target}")
        res = await extract_with_playwright(pw_target)
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
        title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        raw_title = ""
        if title_m:
            raw_title = title_m.group(1).split("webcam recordings")[0].strip(" ,-|")
            if not raw_title:
                raw_title = title_m.group(1).split("|")[0].strip()
        title = sanitize_title(raw_title, default="archivebate_video.mp4")

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
            if not embedded_url.startswith(("http://", "https://")):
                from urllib.parse import urljoin
                embedded_url = urljoin("https://www.archivebate.com/", embedded_url)
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


def _parse_luluvid_content(html: str) -> tuple:
    """Extracts (stream_url, stream_type, title) from LuluStream / LuluVideo HTML content."""
    if not html:
        return None, "direct", None

    title = None
    raw_title = None

    # A. Check script document.title = "..." assignment (handles dynamically injected titles)
    doc_title_match = re.search(r'document\.title\s*=\s*["\']([^"\']+)["\']', html)
    if doc_title_match:
        cand = doc_title_match.group(1).strip()
        try:
            cand = cand.encode('utf-8').decode('unicode_escape').strip()
        except Exception:
            pass
        if cand and not cand.lower().startswith("loading"):
            raw_title = cand

    # B. Check og:title meta tag
    if not raw_title:
        og_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not og_match:
            og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.IGNORECASE)
        if og_match:
            cand = og_match.group(1).strip()
            if cand and not cand.lower().startswith("loading"):
                raw_title = cand

    # C. Fallback to <title> tag
    if not raw_title:
        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        if title_match:
            cand = title_match.group(1).strip()
            if cand and not cand.lower().startswith("loading"):
                raw_title = cand

    if raw_title:
        clean_title = re.sub(r"\s*-\s*Lulu(stream|video|vid|vdo)(\.mp4)?", "", raw_title, flags=re.IGNORECASE).strip()
        if clean_title and not clean_title.lower().startswith("loading"):
            title = sanitize_title(clean_title, default="luluvideo.mp4")

    clean_html = html.replace(r"\/", "/")

    # 1. Direct m3u8 regex check in HTML
    m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', clean_html)

    # 2. Playerjs or standard JS file configs: file: "https://..." or src: "https://..."
    if not m3u8_matches:
        file_configs = re.findall(r'(?:file|src)\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', clean_html)
        if file_configs:
            m3u8_matches.extend(file_configs)

    # 3. Check sources: [{file: "..."}] in JWPlayer / VideoJS configuration
    if not m3u8_matches:
        source_matches = re.findall(r'sources\s*:\s*\[\s*\{\s*(?:file|src)\s*:\s*["\']([^"\']+)["\']', clean_html)
        for sm in source_matches:
            if ".m3u8" in sm or ".mp4" in sm:
                m3u8_matches.append(sm)
                break

    # 4. Unpack Dean Edwards P.A.C.K.E.R. scripts
    if not m3u8_matches:
        unpacked = unpack_dean_edwards(html)
        if unpacked:
            clean_unpacked = unpacked.replace(r"\/", "/")
            m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', clean_unpacked)
            if not m3u8_matches:
                source_unpacked = re.findall(r'["\'](https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*)["\']', clean_unpacked)
                if source_unpacked:
                    m3u8_matches = source_unpacked
            if not m3u8_matches:
                pjs_unpacked = re.findall(r'(?:file|src)\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', clean_unpacked)
                if pjs_unpacked:
                    m3u8_matches = pjs_unpacked

    # 5. Check direct mp4 matches if no m3u8 found
    if not m3u8_matches:
        mp4_matches = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', clean_html)
        valid_mp4s = [m for m in mp4_matches if not any(x in m.lower() for x in ("thumb", "poster", "preview", "banner", "ad."))]
        if valid_mp4s:
            m3u8_matches = valid_mp4s

    if m3u8_matches:
        stream_url = m3u8_matches[0]
        stream_type = "m3u8" if ".m3u8" in stream_url else "direct"
        return stream_url, stream_type, title

    return None, "direct", title


async def _fetch_stealth_text(url: str, headers: dict, retries: int = 3) -> str:
    """Uses curl_cffi with rotating browser TLS impersonations and backoff to bypass Cloudflare rate-limits."""
    from curl_cffi.requests import AsyncSession
    profiles = ["chrome124", "chrome120", "safari15_5"]
    req_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    if headers:
        req_headers.update(headers)

    for attempt in range(1, retries + 1):
        profile = profiles[(attempt - 1) % len(profiles)]
        try:
            async with AsyncSession(impersonate=profile, timeout=15) as session:
                resp = await session.get(url, headers=req_headers)
                if resp.status_code == 200 and resp.text:
                    return resp.text
                elif resp.status_code in (403, 429, 502, 503, 504, 520, 521, 522):
                    if attempt < retries:
                        wait_sec = 1.5 * attempt
                        logger.warning(
                            f"Host {url} returned HTTP {resp.status_code} on {profile}. Retrying in {wait_sec:.1f}s (attempt {attempt}/{retries})..."
                        )
                        await asyncio.sleep(wait_sec)
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(1.0 * attempt)
            else:
                logger.debug(f"curl_cffi fetch failed for {url} ({profile}): {e}")
    return ""


async def resolve_luluvid(url: str) -> dict:
    """Extracts direct m3u8 or mp4 stream from LuluStream / LuluVid / LuluVideo via static analysis, curl_cffi, & Playwright fallback."""
    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"{base_origin}/"
    }

    # Extract clean file ID and construct candidate embed URLs
    parts = [p for p in parsed.path.split("/") if p and p not in ("e", "d", "v", "embed")]
    candidate_urls = []
    file_id = ""
    if parts:
        raw_file_id = parts[0]
        file_id = raw_file_id.rsplit(".", 1)[0] if "." in raw_file_id else raw_file_id
        # Primary embed format
        candidate_urls.append(f"{base_origin}/e/{file_id}")
        candidate_urls.append(f"{base_origin}/{file_id}")
        candidate_urls.append(f"https://lulustream.com/e/{file_id}")
        candidate_urls.append(f"https://lulustream.com/{file_id}")
    if url not in candidate_urls:
        candidate_urls.append(url)

    # Fast API check for Lplaygo if API key is provided
    if "lplaygo" in parsed.netloc and file_id and LPLAYGO_KEY:
        try:
            api_url = f"https://lplaygo.com/api/file/direct_link?key={LPLAYGO_KEY}&file_code={file_id}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200 and data.get("result", {}).get("url"):
                            direct_u = data["result"]["url"]
                            logger.info(f"Lplaygo direct link resolved via official API: {file_id}")
                            return {
                                "type": "m3u8" if ".m3u8" in direct_u else "direct",
                                "url": direct_u,
                                "title": f"{file_id}.mp4",
                                "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"{base_origin}/"}
                            }
        except Exception as e:
            logger.debug(f"Lplaygo API direct link lookup failed: {e}")

    title = "luluvideo.mp4"

    # 1. Stealth TLS fetch via curl_cffi (Primary: obtains genuine token with Chrome TLS impersonation)
    for target_url in candidate_urls:
        try:
            html = await _fetch_stealth_text(target_url, headers)
            if html:
                stream_url, stream_type, page_title = _parse_luluvid_content(html)
                if page_title:
                    title = page_title
                if stream_url:
                    stream_headers = {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": f"{base_origin}/"
                    }
                    logger.info(f"LuluStream/LuluVideo stream resolved via curl_cffi: {title}")
                    return {
                        "type": stream_type,
                        "url": stream_url,
                        "title": title,
                        "headers": stream_headers
                    }
        except Exception as e:
            logger.debug(f"LuluStream curl_cffi extraction failed for {target_url}: {e}")

    # 2. Fast asynchronous static fetch via aiohttp (Fallback)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for target_url in candidate_urls:
                try:
                    async with session.get(target_url, allow_redirects=True) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text()
                except Exception:
                    continue

                stream_url, stream_type, page_title = _parse_luluvid_content(html)
                if page_title:
                    title = page_title
                if stream_url:
                    stream_headers = {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": f"{base_origin}/"
                    }
                    logger.info(f"LuluStream/LuluVideo stream resolved via aiohttp: {title}")
                    return {
                        "type": stream_type,
                        "url": stream_url,
                        "title": title,
                        "headers": stream_headers
                    }
    except Exception as e:
        logger.debug(f"LuluStream aiohttp extraction failed for {url}: {e}")

    # 3. Playwright Fallback if static regex failed (handles Cloudflare/JS challenge or dynamic token injection)
    try:
        from bot.extractors.browser_ext import extract_with_playwright
        pw_target = candidate_urls[0] if candidate_urls else url
        logger.info(f"Triggering Playwright fallback for LuluStream/LuluVideo: {pw_target}")
        res = await extract_with_playwright(pw_target)
        if res and res.get("url"):
            if not res.get("title") or res.get("title") in ("lulustream_video.mp4", "extracted_media.mp4"):
                res["title"] = title
            return res
    except Exception as e:
        logger.debug(f"Playwright fallback failed for LuluStream/LuluVideo: {e}")

    return None


async def resolve_streamfiles(url: str) -> dict:
    """Extracts direct m3u8 stream from StreamFiles via API, static parsing, stealth curl_cffi, or Playwright fallback."""
    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": f"{base_origin}/"}

    parts = [p for p in parsed.path.split("/") if p and p not in ("e", "d", "v", "embed")]
    raw_id = parts[0] if parts else ""
    file_id = raw_id.rsplit(".", 1)[0] if "." in raw_id else raw_id
    if file_id.startswith("embed-"):
        file_id = file_id[6:]

    # Fast API check for Streamfiles if API key is configured
    if file_id and STREAMFILE_KEY:
        try:
            api_url = f"https://streamfile.net/api/file/direct_link?key={STREAMFILE_KEY}&file_code={file_id}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200 and data.get("result", {}).get("url"):
                            direct_u = data["result"]["url"]
                            logger.info(f"StreamFiles direct link resolved via official API: {file_id}")
                            return {
                                "type": "m3u8" if ".m3u8" in direct_u else "direct",
                                "url": direct_u,
                                "title": f"{file_id}.mp4",
                                "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://streamfile.net/"}
                            }
        except Exception as e:
            logger.debug(f"StreamFiles API direct link lookup failed: {e}")

    # Build candidate URLs prioritizing direct embed formats (which contain the master m3u8 playlist)
    candidate_urls = []
    if file_id:
        candidate_urls.append(f"{base_origin}/embed-{file_id}.html")
        candidate_urls.append(f"https://streamfile.net/embed-{file_id}.html")
        candidate_urls.append(f"https://streamfiles.net/embed-{file_id}.html")
        candidate_urls.append(f"{base_origin}/e/{file_id}")
        candidate_urls.append(f"{base_origin}/{file_id}")
    if url not in candidate_urls:
        candidate_urls.append(url)

    title = "streamfiles_video.mp4"

    def _extract_streamfiles_html(html_text: str):
        if not html_text:
            return None, None
        t_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE)
        t = None
        if t_match:
            raw_t = t_match.group(1).strip()
            clean_t = re.sub(r"^(Watch|Download)\s+", "", raw_t, flags=re.IGNORECASE).strip()
            if not clean_t.lower().endswith(".mp4"):
                clean_t += ".mp4"
            t = clean_t

        matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html_text)
        if not matches:
            unpacked = unpack_dean_edwards(html_text)
            if unpacked:
                matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)
        return (matches[0] if matches else None), t

    # 1. Fast static fetch via aiohttp
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            for target_u in candidate_urls:
                try:
                    async with session.get(target_u, allow_redirects=True) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            m3u8_url, parsed_title = _extract_streamfiles_html(html)
                            if parsed_title:
                                title = parsed_title
                            if m3u8_url:
                                logger.info(f"StreamFiles stream resolved via aiohttp: {title}")
                                return {
                                    "type": "m3u8",
                                    "url": m3u8_url,
                                    "title": title,
                                    "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://streamfile.net/"}
                                }
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"StreamFiles aiohttp extraction failed for {url}: {e}")

    # 2. Stealth TLS fetch via curl_cffi
    for target_u in candidate_urls:
        try:
            html = await _fetch_stealth_text(target_u, headers)
            if html:
                m3u8_url, parsed_title = _extract_streamfiles_html(html)
                if parsed_title:
                    title = parsed_title
                if m3u8_url:
                    logger.info(f"StreamFiles stream resolved via curl_cffi: {title}")
                    return {
                        "type": "m3u8",
                        "url": m3u8_url,
                        "title": title,
                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://streamfile.net/"}
                    }
        except Exception as e:
            logger.debug(f"StreamFiles curl_cffi extraction failed for {target_u}: {e}")

    # 3. Playwright Fallback
    try:
        from bot.extractors.browser_ext import extract_with_playwright
        logger.info(f"Triggering Playwright fallback for StreamFiles: {url}")
        res = await extract_with_playwright(url)
        if res and res.get("url"):
            if not res.get("title") or res.get("title") in ("streamfiles_video.mp4", "extracted_media.mp4"):
                res["title"] = title
            return res
    except Exception as e:
        logger.debug(f"Playwright fallback failed for StreamFiles: {e}")

    return None


async def resolve_vidara(url: str) -> dict:
    """
    Tier-0 Fast Resolver for Vidara.to / Gasobni video streams.
    Directly queries internal /api/stream endpoint and falls back to fast embed HTML parsing.
    """
    try:
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        filecode = segments[-1] if segments else ""
        if "." in filecode:
            filecode = filecode.rsplit(".", 1)[0]

        if not filecode:
            return None

        candidate_domains = []
        if parsed.netloc:
            candidate_domains.append(parsed.netloc)
        for d in ("vidara.to", "gasobni.com", "vidara.so", "vidara.net"):
            if d not in candidate_domains:
                candidate_domains.append(d)

        payload = {"filecode": filecode}

        # Step 1: Internal API query (super fast: ~0.1s)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5.0, connect=3.0)) as session:
            for domain in candidate_domains:
                try:
                    api_url = f"https://{domain}/api/stream"
                    headers = {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Origin": f"https://{domain}",
                        "Referer": f"https://{domain}/e/{filecode}",
                        "Content-Type": "application/json"
                    }
                    async with session.post(api_url, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            streaming_url = data.get("streaming_url")
                            title = data.get("title") or f"{filecode}.mp4"
                            if not title.lower().endswith((".mp4", ".mkv")):
                                title += ".mp4"

                            if streaming_url:
                                logger.info(f"Vidara stream resolved via {domain} API: {title}")
                                return {
                                    "type": "m3u8" if ".m3u8" in streaming_url else "direct",
                                    "url": streaming_url,
                                    "title": title,
                                    "headers": {
                                        "User-Agent": DEFAULT_USER_AGENT,
                                        "Referer": f"https://{domain}/"
                                    }
                                }
                except Exception as de:
                    logger.debug(f"Vidara API attempt failed for {domain}: {de}")

            # Step 2: Direct Embed HTML fallback (bypasses headless browser)
            for domain in candidate_domains:
                try:
                    embed_url = f"https://{domain}/e/{filecode}"
                    headers = {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": f"https://{domain}/"
                    }
                    async with session.get(embed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            m3u8_match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
                            if m3u8_match:
                                stream_url = m3u8_match.group(1)
                                logger.info(f"Vidara stream resolved via {domain} embed HTML: {filecode}")
                                return {
                                    "type": "m3u8",
                                    "url": stream_url,
                                    "title": f"{filecode}.mp4",
                                    "headers": {
                                        "User-Agent": DEFAULT_USER_AGENT,
                                        "Referer": f"https://{domain}/"
                                    }
                                }
                except Exception as he:
                    logger.debug(f"Vidara HTML embed fallback failed for {domain}: {he}")

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
            raw_t = title_m.group(1).split("-")[0].strip() if title_m else ""
            title = sanitize_title(raw_t, default="filemoon_video.mp4")
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
            b64_matches = re.findall(r"window\.location\.href\s*=\s*['\"](https?://[^'\"]+)['\"]", html)
            if b64_matches:
                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                    async with session.get(b64_matches[0], allow_redirects=True) as resp2:
                        html2 = await resp2.text()
                        m3u8_m = re.findall(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html2)

        if m3u8_m:
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            raw_t = title_m.group(1).split("|")[0].strip() if title_m else ""
            title = sanitize_title(raw_t, default="voe_video.mp4")
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

        mp4_m = re.findall(r'player\.src\(\{\s*type:\s*["\']video/mp4["\'],\s*src:\s*["\']([^"\']+)["\']', html)
        if not mp4_m:
            mp4_m = re.findall(r'["\'](https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)["\']', html)

        if mp4_m:
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            raw_t = title_m.group(1).split("-")[0].strip() if title_m else ""
            title = sanitize_title(raw_t, default="mp4upload_video.mp4")
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
        stream_m = re.findall(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', unpacked)
        if stream_m:
            s_url = stream_m[0]
            title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            raw_t = title_m.group(1).strip() if title_m else ""
            title = sanitize_title(raw_t, default="vidguard_video.mp4")
            return {
                "type": "m3u8" if ".m3u8" in s_url else "direct",
                "url": s_url,
                "title": title,
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


def encode_base_n(num: int, n: int = 36) -> str:
    """Encodes an integer into base-n alphanumeric string."""
    table = "0123456789abcdefghijklmnopqrstuvwxyz"
    if num == 0:
        return table[0]
    ret = []
    while num > 0:
        ret.append(table[num % n])
        num //= n
    return "".join(reversed(ret))


def calc_eporner_hash(vid_hash: str) -> str:
    """Computes Eporner XHR auth token from 32-hex hash."""
    return "".join(encode_base_n(int(vid_hash[lb:lb + 8], 16), 36) for lb in range(0, 32, 8))


async def resolve_eporner(url: str) -> dict:
    """
    Tier-0 Direct Resolver for Eporner:
    1. Extracts video ID and queries web page.
    2. Computes XHR auth hash and calls official /xhr/video/{video_id} JSON API.
    3. Selects best quality direct MP4 (1080p, 720p, 480p) or HLS master playlist.
    4. Fallback: Extracts HTML5 video tag, download button, or Playwright sniffer.
    """
    m = re.search(r"(?:video-|/video/|/embed/|/hd-porn/|/dload/)([a-zA-Z0-9]+)", url)
    video_id = m.group(1) if m else None

    parsed = urlparse(url)
    domain = parsed.netloc if parsed.netloc else "www.eporner.com"
    target_page_url = f"https://{domain}/video-{video_id}/" if video_id else url

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"https://{domain}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    title = f"eporner_{video_id or 'video'}.mp4"

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(target_page_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.debug(f"Eporner page returned HTTP {resp.status} for {target_page_url}")
                    return None
                html = await resp.text()

            # Extract title
            title_m = re.search(r"<title>(.*?)\s*-\s*EPORNER", html, re.IGNORECASE)
            if not title_m:
                title_m = re.search(r'<meta property="og:title"\s*content="([^"]+)"', html)
            if title_m:
                title = sanitize_title(title_m.group(1), default=f"eporner_{video_id or 'video'}.mp4")

            # 1. Official XHR API resolution using reverse-engineered calc_hash
            hash_m = re.search(r'hash\s*[:=]\s*["\']([\da-f]{32})["\']', html)
            if hash_m and video_id:
                vid_hash = hash_m.group(1)
                calculated_token = calc_eporner_hash(vid_hash)
                xhr_url = f"https://{domain}/xhr/video/{video_id}"
                xhr_params = {
                    "hash": calculated_token,
                    "device": "generic",
                    "domain": domain,
                    "fallback": "false"
                }
                xhr_headers = {
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": target_page_url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01"
                }
                try:
                    async with session.get(xhr_url, params=xhr_params, headers=xhr_headers) as xhr_resp:
                        if xhr_resp.status == 200:
                            data = await xhr_resp.json()
                            if data.get("available") is not False:
                                sources = data.get("sources", {})
                                stream_url = None
                                stream_type = "direct"

                                # Priority: highest quality direct mp4
                                mp4_dict = sources.get("mp4", {})
                                if isinstance(mp4_dict, dict):
                                    for res_key in ("1080p", "720p", "480p", "360p", "240p"):
                                        if res_key in mp4_dict and isinstance(mp4_dict[res_key], dict):
                                            stream_url = mp4_dict[res_key].get("src")
                                            if stream_url:
                                                stream_type = "direct"
                                                logger.info(f"Eporner resolved {res_key} direct stream: {stream_url[:50]}...")
                                                break

                                # Fallback: HLS master playlist
                                if not stream_url:
                                    hls_dict = sources.get("hls", {})
                                    if isinstance(hls_dict, dict):
                                        auto_hls = hls_dict.get("auto", {})
                                        if isinstance(auto_hls, dict):
                                            stream_url = auto_hls.get("src")
                                            stream_type = "m3u8"

                                if stream_url:
                                    if stream_url.startswith("//"):
                                        stream_url = "https:" + stream_url
                                    return {
                                        "type": stream_type,
                                        "url": stream_url,
                                        "title": title,
                                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": target_page_url}
                                    }
                except Exception as e:
                    logger.debug(f"Eporner XHR API failed: {e}")

            # 2. HTML Video tag & download button inspection
            vid_tag_m = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', html)
            if vid_tag_m:
                v_url = vid_tag_m.group(1)
                return {
                    "type": "m3u8" if ".m3u8" in v_url else "direct",
                    "url": v_url,
                    "title": title,
                    "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": target_page_url}
                }

            # 3. Direct download link in page (/dload/...)
            dload_m = re.search(r'href=["\'](/dload/[^"\']+)["\']', html)
            if dload_m:
                full_dload = f"https://{domain}" + dload_m.group(1)
                return {
                    "type": "direct",
                    "url": full_dload,
                    "title": title,
                    "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": target_page_url}
                }

    except Exception as e:
        logger.debug(f"Eporner static resolver failed for {url}: {e}")

    # 4. Playwright Fallback
    try:
        from bot.extractors.browser_ext import extract_with_playwright
        logger.info(f"Triggering Playwright fallback for Eporner: {url}")
        res = await extract_with_playwright(url)
        if res and res.get("url"):
            res["title"] = title
            return res
    except Exception as e:
        logger.debug(f"Playwright fallback failed for Eporner: {e}")

    return None


async def resolve_streamcash(url: str, custom_title: str = None) -> dict:
    """
    Tier-0 Fast Resolver for Streamcash.to video embeds.
    Decodes high-speed m3u8 stream from base64-encoded window.__PCr JSON in < 0.2s.
    """
    parsed = urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://livecamrips.to/"
    }

    html = await _fetch_stealth_text(url, headers)
    if not html:
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        html = await resp.text()
        except Exception:
            pass

    if not html:
        return None

    # Title parsing
    title = custom_title
    if not title:
        t_match = re.search(r"<title>(.*?)</title>", html, re.I)
        if t_match:
            raw_t = t_match.group(1).strip()
            if len(raw_t) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw_t):
                title = "streamcash_video.mp4"
            else:
                title = raw_t if raw_t.lower().endswith(".mp4") else f"{raw_t}.mp4"
        else:
            title = "streamcash_video.mp4"

    # Decode base64 stream configuration (__PCr)
    pcr_match = re.search(r"window\.__PCr\s*=\s*['\"]([^'\"]+)['\"]", html)
    if pcr_match:
        try:
            b64_str = pcr_match.group(1)
            decoded = json.loads(base64.b64decode(b64_str).decode("utf-8"))
            stream_src = decoded.get("src")
            if stream_src:
                logger.info(f"Streamcash stream resolved via __PCr: {title}")
                return {
                    "type": "m3u8" if ".m3u8" in stream_src else "direct",
                    "url": stream_src,
                    "title": title,
                    "headers": {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": f"{base_origin}/",
                        "Origin": base_origin
                    }
                }
        except Exception as e:
            logger.debug(f"Failed to decode __PCr from Streamcash: {e}")

    # Fallback to direct m3u8 search
    m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if m3u8_matches:
        return {
            "type": "m3u8",
            "url": m3u8_matches[0],
            "title": title,
            "headers": {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"{base_origin}/",
                "Origin": base_origin
            }
        }

    return None


async def resolve_uqload(url: str, custom_title: str = None) -> dict:
    """
    Tier-0 Fast Resolver for Uqload video embeds.
    Extracts high-speed m3u8 stream from Dean Edwards packed JavaScript in < 0.2s.
    """
    clean_url = url.replace("/d/", "/embed-").replace("/v/", "/embed-")
    parsed = urlparse(clean_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://livecamrips.to/"
    }

    html = await _fetch_stealth_text(clean_url, headers)
    if not html:
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(clean_url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        html = await resp.text()
        except Exception:
            pass

    if not html:
        return None

    title = custom_title
    if not title:
        t_match = re.search(r"<title>(.*?)</title>", html, re.I)
        if t_match:
            raw_t = t_match.group(1).replace("Watch", "").replace("Uqload", "").strip(" -|")
            title = sanitize_title(raw_t, default="uqload_video.mp4")
        else:
            title = "uqload_video.mp4"

    unpacked = unpack_dean_edwards(html) or html

    m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)
    if not m3u8_matches:
        file_m = re.findall(r'(?:file|sources\s*:\s*\[\s*\{\s*file)\s*:\s*["\']([^"\']+\.m3u8[^\s"\']*)["\']', unpacked)
        if file_m:
            m3u8_matches = file_m

    if m3u8_matches:
        stream_url = m3u8_matches[0]
        logger.info(f"Uqload m3u8 stream resolved: {title}")
        return {
            "type": "m3u8",
            "url": stream_url,
            "title": title,
            "headers": {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"{base_origin}/",
                "Origin": base_origin
            }
        }

    mp4_matches = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', unpacked)
    if mp4_matches:
        stream_url = mp4_matches[0]
        return {
            "type": "direct",
            "url": stream_url,
            "title": title,
            "headers": {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"{base_origin}/"
            }
        }

    return None


async def resolve_abstream(url: str, custom_title: str = None) -> dict:
    """
    Tier-0 Fast Resolver for Abstream video embeds.
    Extracts high-speed m3u8 stream from page sources in < 0.2s.
    """
    clean_url = url
    parsed = urlparse(clean_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://livecamrips.to/"
    }

    html = await _fetch_stealth_text(clean_url, headers)
    if not html:
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(clean_url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        html = await resp.text()
        except Exception:
            pass

    if not html:
        return None

    title = custom_title or "abstream_video.mp4"
    unpacked = unpack_dean_edwards(html) or html

    m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)
    if not m3u8_matches:
        file_m = re.findall(r'(?:file|sources\s*:\s*\[\s*\{\s*file)\s*:\s*["\']([^"\']+\.m3u8[^\s"\']*)["\']', unpacked)
        if file_m:
            m3u8_matches = file_m

    if m3u8_matches:
        stream_url = m3u8_matches[0]
        logger.info(f"Abstream m3u8 stream resolved: {title}")
        return {
            "type": "m3u8",
            "url": stream_url,
            "title": title,
            "headers": {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"{base_origin}/",
                "Origin": base_origin
            }
        }

    return None


async def resolve_livecamrips(url: str) -> dict:
    """
    Tier-0 Fast Resolver for Livecamrips.to.
    Fetches the video page, extracts clean page title, locates embedded player iframe,
    and resolves the underlying video stream directly in < 0.3s.
    """
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://livecamrips.to/"
    }
    html = await _fetch_stealth_text(url, headers)
    if not html:
        try:
            from curl_cffi import requests as cffi_requests
            def _sync_fetch():
                with cffi_requests.Session(impersonate="chrome124") as s:
                    r = s.get(url, headers=headers, timeout=12)
                    return r.text if r.status_code == 200 else ""
            html = await asyncio.to_thread(_sync_fetch)
        except Exception:
            pass

    if not html:
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status == 200:
                        html = await resp.text()
        except Exception:
            pass

    if not html:
        logger.info(f"Livecamrips static fetch empty or blocked; falling back directly to Playwright: {url}")
        try:
            from bot.extractors.browser_ext import extract_with_playwright
            return await extract_with_playwright(url)
        except Exception as e:
            logger.debug(f"Livecamrips Playwright fallback failed: {e}")
            return None

    # Clean title extraction
    t_match = re.search(r"<title>(.*?)</title>", html, re.I)
    title = "livecamrip.mp4"
    if t_match:
        raw_t = t_match.group(1).strip()
        clean_t = re.sub(r"^livecamrips\.(?:to|com|net|org)\s*", "", raw_t, flags=re.I).strip()
        clean_t = re.sub(r"[^\w\s\.\-]", "", clean_t).strip()
        if clean_t:
            title = clean_t if clean_t.lower().endswith(".mp4") else f"{clean_t}.mp4"

    # Search for embedded player iframe
    iframe_match = re.search(r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']', html, re.I)
    if iframe_match:
        iframe_url = iframe_match.group(1).strip()
        if iframe_url.startswith("//"):
            iframe_url = "https:" + iframe_url
        logger.info(f"Livecamrips found embedded player iframe: {iframe_url}")

        parsed_ifr = urlparse(iframe_url)
        ifr_netloc = parsed_ifr.netloc.lower().split(":")[0]

        # 1. Specialized host resolvers
        if is_streamcash_host(ifr_netloc):
            res = await resolve_streamcash(iframe_url, custom_title=title)
            if res:
                return res

        if is_uqload_host(ifr_netloc):
            res = await resolve_uqload(iframe_url, custom_title=title)
            if res:
                return res

        if is_abstream_host(ifr_netloc):
            res = await resolve_abstream(iframe_url, custom_title=title)
            if res:
                return res

        if is_matching_host(ifr_netloc, MIXDROP_DOMAINS) or "mixdrop" in ifr_netloc or "mdzsmutpcvykb" in ifr_netloc or "mxcontent" in ifr_netloc:
            res = await resolve_mixdrop(iframe_url)
            if res:
                res["title"] = title
                return res

        # 2. General video host extraction
        other_host_res = await extract_from_video_hosts(iframe_url)
        if other_host_res:
            if title and not title.startswith("streamcash_video"):
                other_host_res["title"] = title
            return other_host_res

        # 3. Dynamic generic inline iframe probe: fetch iframe HTML, unpack JS, check media
        try:
            ifr_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": "https://livecamrips.to/"}
            ifr_html = await _fetch_stealth_text(iframe_url, ifr_headers)
            if ifr_html:
                unpacked = unpack_dean_edwards(ifr_html) or ifr_html
                # Check MDCore.wurl
                md_match = re.search(r'(?:MDCore\.wurl|MDCore\.vurl|wurl|vurl)\s*=\s*["\']([^"\']+)["\']', unpacked)
                if md_match:
                    st_url = md_match.group(1)
                    if st_url.startswith("//"):
                        st_url = "https:" + st_url
                    return {
                        "type": "direct",
                        "url": st_url,
                        "title": title,
                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": iframe_url}
                    }
                # Check m3u8
                m3u8_m = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked)
                if m3u8_m:
                    return {
                        "type": "m3u8",
                        "url": m3u8_m[0],
                        "title": title,
                        "headers": {
                            "User-Agent": DEFAULT_USER_AGENT,
                            "Referer": f"{parsed_ifr.scheme}://{parsed_ifr.netloc}/",
                            "Origin": f"{parsed_ifr.scheme}://{parsed_ifr.netloc}"
                        }
                    }
                # Check mp4
                mp4_m = re.findall(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', unpacked)
                if mp4_m:
                    return {
                        "type": "direct",
                        "url": mp4_m[0],
                        "title": title,
                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": iframe_url}
                    }
        except Exception as ifr_err:
            logger.debug(f"Generic iframe probe failed: {ifr_err}")

    # Fallback to Playwright
    try:
        from bot.extractors.browser_ext import extract_with_playwright
        logger.info(f"Livecamrips fallback to Playwright: {url}")
        res = await extract_with_playwright(url)
        if res and res.get("url"):
            if not res.get("title") or res.get("title") in ("browser_media.mp4", "extracted_media.mp4"):
                res["title"] = title
            return res
    except Exception as e:
        logger.debug(f"Livecamrips Playwright fallback error: {e}")

    return None


def _decrypt_cryptojs_aes(ciphertext_b64: str, password: str) -> str:
    """Decrypts CryptoJS AES encrypted string using OpenSSL EVP_BytesToKey."""
    import base64
    import hashlib
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = base64.b64decode(ciphertext_b64)
    if not raw.startswith(b"Salted__"):
        raise ValueError("Invalid CryptoJS format (missing Salted__ prefix)")
    salt = raw[8:16]
    ciphertext = raw[16:]

    d = b""
    d_i = b""
    while len(d) < (32 + 16):
        d_i = hashlib.md5(d_i + password.encode("utf-8") + salt).digest()
        d += d_i
    key, iv = d[:32], d[32:48]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError("Invalid padding length")
    return decrypted[:-pad_len].decode("utf-8")


async def resolve_thotplay(url: str, custom_title: str = None) -> dict:
    """
    Direct extractor for Thotplay (thotplay.com/e/<id>).
    Extracts AES-encrypted videoURL and secret key, decrypts to HLS master m3u8 playlist.
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[0] != "e":
        video_id = parts[-1]
        fetch_url = f"{parsed.scheme or 'https'}://{parsed.netloc}/e/{video_id}"
    else:
        fetch_url = url

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"{parsed.scheme or 'https'}://{parsed.netloc}/",
    }

    html = await _fetch_stealth_text(fetch_url, headers)
    if not html:
        logger.warning(f"Failed to fetch Thotplay page: {fetch_url}")
        return None

    # Title extraction
    title = custom_title
    if not title:
        t_match = re.search(r"<title>(.*?)</title>", html, re.I)
        if t_match:
            raw_t = t_match.group(1).strip()
            clean_t = re.sub(r"[\\/:*?\"<>|]", "", raw_t).strip()
            if clean_t:
                title = clean_t if clean_t.lower().endswith(".mp4") else f"{clean_t}.mp4"
    if not title:
        video_id = parts[-1] if parts else "video"
        title = f"thotplay_{video_id}.mp4"

    # Extract encrypted videoURL and decryption key
    v_match = re.search(r'const\s+videoURL\s*=\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]', html)
    k_match = re.search(r'decryptLink\s*\(\s*videoURL\s*,\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]', html)

    if v_match and k_match:
        try:
            m3u8_url = _decrypt_cryptojs_aes(v_match.group(1), k_match.group(1))
            if m3u8_url and (".m3u8" in m3u8_url or "api-embed" in m3u8_url):
                logger.info(f"Thotplay decrypted stream URL: {m3u8_url[:60]}...")
                return {
                    "type": "m3u8",
                    "url": m3u8_url,
                    "title": title,
                    "headers": {
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": f"{parsed.scheme or 'https'}://{parsed.netloc}/",
                        "Origin": f"{parsed.scheme or 'https'}://{parsed.netloc}",
                    }
                }
        except Exception as e:
            logger.warning(f"Thotplay AES decryption failed: {e}")

    # Fallback: search for direct mp4 / m3u8 links in html
    m3u8_m = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if m3u8_m:
        return {
            "type": "m3u8",
            "url": m3u8_m[0],
            "title": title,
            "headers": {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"{parsed.scheme or 'https'}://{parsed.netloc}/",
            }
        }

    return None


async def extract_from_video_hosts(url: str) -> dict:
    """
    Tier-0 Router: Checks if URL belongs to any specialized video hosting provider.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc

    if is_streamtape_host(netloc):
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

    if is_luluvid_host(netloc):
        logger.info(f"Target recognized as LuluStream/LuluVid/LuluVideo: {url}")
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

    if is_matching_host(netloc, EPORNER_DOMAINS) or "eporner" in netloc.lower():
        logger.info(f"Target recognized as Eporner: {url}")
        return await resolve_eporner(url)

    if is_livecamrips_host(netloc):
        logger.info(f"Target recognized as Livecamrips: {url}")
        return await resolve_livecamrips(url)

    if is_streamcash_host(netloc):
        logger.info(f"Target recognized as Streamcash: {url}")
        return await resolve_streamcash(url)

    if is_uqload_host(netloc):
        logger.info(f"Target recognized as Uqload: {url}")
        return await resolve_uqload(url)

    if is_abstream_host(netloc):
        logger.info(f"Target recognized as Abstream: {url}")
        return await resolve_abstream(url)

    if is_thotplay_host(netloc):
        logger.info(f"Target recognized as Thotplay: {url}")
        return await resolve_thotplay(url)

    return None
