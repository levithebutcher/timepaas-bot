import re
import json
import base64
import logging
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import aiohttp
from bs4 import BeautifulSoup
from bot.config import DEFAULT_USER_AGENT
from bot.extractors.video_hosts import extract_from_video_hosts, unpack_dean_edwards, sanitize_title

logger = logging.getLogger(__name__)

TARGET_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m3u8",
    ".zip", ".rar", ".7z", ".tar", ".gz"
}


def extract_page_title(soup: BeautifulSoup, default_title: str = "general_media.mp4") -> str:
    """Extracts a clean, descriptive video/media title from OpenGraph, Twitter, <title>, or <h1>."""
    # 1. OpenGraph / Twitter meta title
    for prop in ("og:title", "twitter:title"):
        meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content"):
            clean = sanitize_title(meta["content"].strip(), default="")
            if clean:
                return clean

    # 2. <title> tag
    title_tag = soup.find("title")
    if title_tag and title_tag.text:
        raw = title_tag.text.strip()
        raw = re.sub(r"\s*[\-\|\–\:]\s*(Watch|Download|Free|HD|Full).*$", "", raw, flags=re.IGNORECASE).strip()
        clean = sanitize_title(raw, default="")
        if clean:
            return clean

    # 3. <h1> tag
    h1_tag = soup.find("h1")
    if h1_tag and h1_tag.text:
        clean = sanitize_title(h1_tag.text.strip(), default="")
        if clean:
            return clean

    return default_title


def find_base64_stream_urls(text: str) -> list[str]:
    """Finds Base64-encoded video URLs (e.g. atob('...') or raw b64 starting with aHR0c)."""
    urls = []
    seen = set()
    matches = re.findall(r'atob\s*\(\s*["\']([A-Za-z0-9+/=]{16,})["\']\s*\)', text)
    matches += re.findall(r'["\'](aHR0c[A-Za-z0-9+/=]{16,})["\']', text)
    for b64_str in matches:
        if b64_str in seen:
            continue
        seen.add(b64_str)
        try:
            decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
            if decoded.startswith(("http://", "https://")) and any(ext in decoded.lower() for ext in (".m3u8", ".mp4", ".webm", ".mkv", "/get_video")):
                urls.append(decoded)
        except Exception:
            continue
    return urls


def extract_from_query_params(url: str) -> str:
    """Sniffs nested media URLs inside query strings (e.g. ?url=https%3A%2F%2F...mp4)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for param in ("url", "src", "file", "video", "stream", "source", "link", "media"):
        for val in qs.get(param, []):
            val = unquote(val).strip()
            if val.startswith(("http://", "https://")):
                clean_path = urlparse(val).path.lower()
                if any(clean_path.endswith(ext) for ext in TARGET_EXTENSIONS):
                    return val
    return None


async def extract_from_general_website(url: str) -> dict:
    """
    Universal Extractor for Arbitrary / General Websites:
    1. Query String inspection & redirect following.
    2. Direct Content-Type / Content-Disposition verification.
    3. OpenGraph & Twitter Card video meta tags.
    4. Schema.org / JSON-LD VideoObject.
    5. Embedded <iframe> and <embed> detection (resolves nested video hosts or players).
    6. HTML5 <video>, <source>, and data-* attributes.
    7. JavaScript engines: JWPlayer, Video.js, Clappr, unpacked Dean Edwards, and Base64 streams.
    8. Interactive Download buttons & form redirection sniffing.
    """
    logger.info(f"[General Extractor] Analyzing universal target: {url}")

    # 1. Check query parameters first for nested media
    nested_media = extract_from_query_params(url)
    if nested_media:
        is_m3u8 = ".m3u8" in nested_media.lower()
        title = nested_media.split("/")[-1].split("?")[0] or "media_stream.mp4"
        logger.info(f"[General Extractor] Found nested media in query string: {title}")
        return {
            "type": "m3u8" if is_m3u8 else "direct",
            "url": nested_media,
            "title": title,
            "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": url}
        }

    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status not in (200, 206):
                    logger.debug(f"[General Extractor] HTTP {response.status} for {url}")
                    return None

                final_url = str(response.url)
                c_type = response.headers.get("Content-Type", "").lower()
                c_disp = response.headers.get("Content-Disposition", "")

                # 2. If the URL itself redirected to a specialized video host
                if final_url != url:
                    host_res = await extract_from_video_hosts(final_url)
                    if host_res and host_res.get("url"):
                        logger.info(f"[General Extractor] Redirected to specialized video host: {final_url}")
                        return host_res

                # 3. Direct streaming response via Content-Type or Content-Disposition
                clean_final_path = urlparse(final_url).path.lower()
                is_direct_stream = (
                    "video/" in c_type
                    or "application/x-mpegurl" in c_type
                    or "application/vnd.apple.mpegurl" in c_type
                    or "attachment" in c_disp.lower()
                    or any(clean_final_path.endswith(ext) for ext in TARGET_EXTENSIONS)
                )
                if is_direct_stream:
                    fn = "media_download.mp4"
                    if "filename=" in c_disp:
                        fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', c_disp)
                        if fn_match:
                            fn = fn_match.group(1).strip()
                    else:
                        slug = final_url.split("/")[-1].split("?")[0]
                        if slug:
                            fn = slug

                    logger.info(f"[General Extractor] Recognized direct stream headers: {fn}")
                    return {
                        "type": "m3u8" if (".m3u8" in clean_final_path or "mpegurl" in c_type) else "direct",
                        "url": final_url,
                        "title": fn,
                        "headers": headers
                    }

                html = await response.text()

        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        default_fn = final_url.split("/")[-1].split("?")[0] or "general_video.mp4"
        if not default_fn.lower().endswith((".mp4", ".mkv", ".webm")):
            default_fn += ".mp4"
        page_title = extract_page_title(soup, default_title=default_fn)

        # 4. OpenGraph & Twitter Card Video Meta Tags
        for prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
            meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if meta and meta.get("content"):
                meta_url = meta["content"].strip()
                if meta_url.startswith(("http://", "https://")):
                    host_res = await extract_from_video_hosts(meta_url)
                    if host_res and host_res.get("url"):
                        logger.info(f"[General Extractor] Found video host in meta {prop}: {meta_url}")
                        return host_res

                    clean_meta_path = urlparse(meta_url).path.lower()
                    if any(clean_meta_path.endswith(ext) for ext in TARGET_EXTENSIONS) or ".m3u8" in meta_url:
                        logger.info(f"[General Extractor] Found stream in meta {prop}: {meta_url}")
                        return {
                            "type": "m3u8" if ".m3u8" in meta_url else "direct",
                            "url": meta_url,
                            "title": page_title,
                            "headers": headers
                        }

        # 5. Schema.org / JSON-LD VideoObject
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                js_content = script.string or script.text or ""
                data = json.loads(js_content)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    nodes = item.get("@graph", [item]) if "@graph" in item else [item]
                    for node in nodes:
                        if not isinstance(node, dict):
                            continue
                        if node.get("@type") == "VideoObject" or "contentUrl" in node or "embedUrl" in node:
                            content_url = node.get("contentUrl")
                            if content_url:
                                logger.info(f"[General Extractor] Found JSON-LD contentUrl: {content_url}")
                                return {
                                    "type": "m3u8" if ".m3u8" in content_url else "direct",
                                    "url": content_url,
                                    "title": node.get("name") or page_title,
                                    "headers": headers
                                }
                            embed_url = node.get("embedUrl")
                            if embed_url:
                                host_res = await extract_from_video_hosts(embed_url)
                                if host_res and host_res.get("url"):
                                    logger.info(f"[General Extractor] Found JSON-LD video host embedUrl: {embed_url}")
                                    return host_res
            except Exception:
                continue

        # 6. Embedded <iframe> and <embed> tags (Detects embedded video players across web)
        for ifr in soup.find_all(["iframe", "embed"]):
            src = ifr.get("src") or ifr.get("data-src") or ifr.get("data-lazy-src") or ifr.get("data-original")
            if not src:
                continue
            src = src.strip()
            if src.startswith("//"):
                src = f"{parsed.scheme}:" + src
            abs_iframe_url = urljoin(final_url, src)

            # Check if iframe is a recognized specialized video host
            host_res = await extract_from_video_hosts(abs_iframe_url)
            if host_res and host_res.get("url"):
                logger.info(f"[General Extractor] Resolved video host from iframe: {abs_iframe_url}")
                if not host_res.get("title") or host_res.get("title") in ("stream_video.mp4", "extracted_media.mp4"):
                    host_res["title"] = page_title
                return host_res

            # Check if iframe is an internal embed route (e.g. /embed/player.php)
            clean_ifr_path = urlparse(abs_iframe_url).path.lower()
            if any(kw in clean_ifr_path for kw in ("/embed", "/player", "/play", "/video", "/v/")):
                try:
                    ifr_headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": final_url}
                    ifr_timeout = aiohttp.ClientTimeout(total=8)
                    async with aiohttp.ClientSession(headers=ifr_headers, timeout=ifr_timeout) as ifr_session:
                        async with ifr_session.get(abs_iframe_url, allow_redirects=True) as ifr_resp:
                            if ifr_resp.status == 200:
                                ifr_html = await ifr_resp.text()
                                sub_soup = BeautifulSoup(ifr_html, "html.parser")
                                for sub_v in sub_soup.find_all(["video", "source"]):
                                    v_src = sub_v.get("src") or sub_v.get("data-src")
                                    if v_src and not v_src.startswith("blob:"):
                                        full_v = urljoin(abs_iframe_url, v_src)
                                        logger.info(f"[General Extractor] Found video in sub-iframe: {full_v}")
                                        return {
                                            "type": "m3u8" if ".m3u8" in full_v else "direct",
                                            "url": full_v,
                                            "title": page_title,
                                            "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": abs_iframe_url}
                                        }

                                # Check m3u8 in sub-iframe
                                clean_sub = ifr_html.replace(r"\/", "/")
                                sub_m3u8 = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', clean_sub)
                                if sub_m3u8:
                                    logger.info(f"[General Extractor] Found m3u8 in sub-iframe: {sub_m3u8[0]}")
                                    return {
                                        "type": "m3u8",
                                        "url": sub_m3u8[0],
                                        "title": page_title,
                                        "headers": {"User-Agent": DEFAULT_USER_AGENT, "Referer": abs_iframe_url}
                                    }
                except Exception as ex:
                    logger.debug(f"[General Extractor] Sub-iframe inspection error: {ex}")

        # 7. HTML5 <video>, <source>, and data-* attributes
        for tag in soup.find_all(["video", "source"]):
            src = tag.get("src") or tag.get("data-src") or tag.get("data-url") or tag.get("data-video")
            if src and not src.startswith("blob:"):
                full_url = urljoin(final_url, src)
                clean_path = urlparse(full_url).path.lower()
                logger.info(f"[General Extractor] Found HTML5 video tag source: {full_url}")
                return {
                    "type": "m3u8" if ".m3u8" in clean_path else "direct",
                    "url": full_url,
                    "title": page_title,
                    "headers": headers
                }

        # Check player container data attributes (<div id="player" data-file="...">)
        for el in soup.find_all(attrs={"data-file": True}) + soup.find_all(attrs={"data-src": True}):
            src = el.get("data-file") or el.get("data-src")
            if src and any(ext in src.lower() for ext in (".mp4", ".m3u8", ".webm")):
                full_url = urljoin(final_url, src)
                logger.info(f"[General Extractor] Found stream in data attribute: {full_url}")
                return {
                    "type": "m3u8" if ".m3u8" in full_url else "direct",
                    "url": full_url,
                    "title": page_title,
                    "headers": headers
                }

        # 8. JavaScript Engine Parsing (JWPlayer, VideoJS, unpacked Dean Edwards, Base64)
        clean_html = html.replace(r"\/", "/")
        unpacked_code = unpack_dean_edwards(html)
        corpus = clean_html + "\n" + (unpacked_code.replace(r"\/", "/") if unpacked_code else "")

        # JWPlayer / VideoJS sources array
        source_matches = re.findall(r'sources\s*:\s*\[\s*\{\s*(?:file|src)\s*:\s*["\']([^"\']+)["\']', corpus)
        if source_matches:
            for sm in source_matches:
                if any(ext in sm.lower() for ext in (".m3u8", ".mp4", ".webm", ".mkv")):
                    full_sm = urljoin(final_url, sm)
                    logger.info(f"[General Extractor] Found stream in JS sources array: {full_sm}")
                    return {
                        "type": "m3u8" if ".m3u8" in full_sm else "direct",
                        "url": full_sm,
                        "title": page_title,
                        "headers": headers
                    }

        # Direct JS variables (e.g. file = "...", streamUrl = "...")
        var_matches = re.findall(r'(?:file|src|stream|video_url|videoUrl|hlsUrl|source)\s*[:=]\s*["\'](https?://[^"\']+\.(?:m3u8|mp4|webm|mkv)[^"\']*)["\']', corpus)
        if var_matches:
            logger.info(f"[General Extractor] Found stream in JS variable: {var_matches[0]}")
            return {
                "type": "m3u8" if ".m3u8" in var_matches[0] else "direct",
                "url": var_matches[0],
                "title": page_title,
                "headers": headers
            }

        # Broad regex for .m3u8 playlist URLs
        m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', corpus)
        if m3u8_matches:
            logger.info(f"[General Extractor] Found m3u8 playlist in corpus: {m3u8_matches[0]}")
            return {
                "type": "m3u8",
                "url": m3u8_matches[0],
                "title": page_title,
                "headers": headers
            }

        # Base64 encoded video streams
        b64_urls = find_base64_stream_urls(corpus)
        if b64_urls:
            logger.info(f"[General Extractor] Found Base64 encoded stream: {b64_urls[0]}")
            return {
                "type": "m3u8" if ".m3u8" in b64_urls[0] else "direct",
                "url": b64_urls[0],
                "title": page_title,
                "headers": headers
            }

        # 9. Direct download anchors & buttons
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            full_a_url = urljoin(final_url, href)
            clean_path = urlparse(full_a_url).path.lower()
            is_page_route = any(p in clean_path for p in ("/v/", "/e/", "/watch/", "/embed/", "/view/", "/play/", "/file/", "/f/", "/d/"))
            if is_page_route or full_a_url == final_url:
                continue

            for ext in TARGET_EXTENSIONS:
                if clean_path.endswith(ext):
                    fn = full_a_url.split("/")[-1].split("?")[0] or page_title
                    logger.info(f"[General Extractor] Found direct download anchor: {fn}")
                    return {
                        "type": "m3u8" if ".m3u8" in clean_path else "direct",
                        "url": full_a_url,
                        "title": fn,
                        "headers": headers
                    }

    except Exception as e:
        logger.debug(f"[General Extractor] Analysis error for {url}: {e}")

    return None
