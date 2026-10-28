import re
import logging
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from bot.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

TARGET_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m3u8",
    ".zip", ".rar", ".7z", ".tar", ".gz"
}


async def extract_with_bs4(url: str) -> dict:
    """
    Parses HTML content for video/source tags and download anchor elements.
    """
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")

        # 1. Search in <video> and <source> tags
        for tag in soup.find_all(["video", "source"]):
            src = tag.get("src")
            if src:
                full_url = urljoin(url, src)
                clean_path = urlparse(full_url).path.lower()
                is_m3u8 = ".m3u8" in clean_path
                return {
                    "type": "m3u8" if is_m3u8 else "direct",
                    "url": full_url,
                    "title": full_url.split("/")[-1].split("?")[0] or "extracted_media.mp4",
                    "headers": headers
                }

        # 2. Search in <a href> matching target file extensions
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            full_url = urljoin(url, href)
            if full_url == url:
                continue

            clean_path = urlparse(full_url).path.lower()
            is_page_route = any(p in clean_path for p in ("/v/", "/e/", "/watch/", "/embed/", "/view/", "/play/", "/file/", "/f/", "/d/"))
            if is_page_route:
                continue

            for ext in TARGET_EXTENSIONS:
                if clean_path.endswith(ext):
                    return {
                        "type": "m3u8" if ".m3u8" in clean_path else "direct",
                        "url": full_url,
                        "title": full_url.split("/")[-1].split("?")[0] or f"download{ext}",
                        "headers": headers
                    }

        # 3. Search in <a href> and <form> with 'download' text or attribute and sniff redirects
        download_candidates = []
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip().lower()
            href = a.get("href", "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue

            full_url = urljoin(url, href)
            clean_path = urlparse(full_url).path.lower()
            is_page_route = any(p in clean_path for p in ("/v/", "/e/", "/watch/", "/embed/", "/view/", "/play/", "/file/", "/f/", "/d/"))
            if is_page_route or full_url == url:
                continue

            # Check direct extension
            for ext in TARGET_EXTENSIONS:
                if clean_path.endswith(ext):
                    return {
                        "type": "direct",
                        "url": full_url,
                        "title": full_url.split("/")[-1].split("?")[0] or "downloaded_file",
                        "headers": headers
                    }

            class_or_id = " ".join((a.get("class") or []) + [a.get("id") or ""]).lower()
            is_dl = (
                a.get("download") is not None
                or any(kw in text for kw in ("download", "direct download", "get file", "download file", "fast download"))
                or any(kw in class_or_id for kw in ("btn-download", "download-btn", "dlink", "downloadbtn"))
            )
            if is_dl:
                download_candidates.append(("GET", full_url, None))

        # Also inspect <form> elements with download action or buttons
        for form in soup.find_all("form"):
            form_text = form.get_text().strip().lower()
            form_action = form.get("action", "").strip()
            if any(kw in form_text or kw in form_action.lower() for kw in ("download", "get file")):
                target_url = urljoin(url, form_action) if form_action else url
                method = form.get("method", "POST").upper()
                form_data = {}
                for inp in form.find_all("input"):
                    name = inp.get("name")
                    if name:
                        form_data[name] = inp.get("value", "")
                download_candidates.append((method, target_url, form_data))

        # Sniff top candidate download buttons (max 3) with fast HTTP request to follow redirects
        for method, cand_url, data in download_candidates[:3]:
            try:
                cand_timeout = aiohttp.ClientTimeout(total=8)
                req_kwargs = {"headers": headers, "allow_redirects": True, "timeout": cand_timeout}
                req_coro = session.post(cand_url, data=data, **req_kwargs) if method == "POST" else session.get(cand_url, **req_kwargs)
                async with req_coro as cand_resp:
                    if cand_resp.status in (200, 206):
                        c_disp = cand_resp.headers.get("Content-Disposition", "")
                        c_type = cand_resp.headers.get("Content-Type", "").lower()
                        c_len = cand_resp.headers.get("Content-Length")
                        final_url = str(cand_resp.url)
                        clean_final_path = urlparse(final_url).path.lower()

                        is_media = (
                            any(clean_final_path.endswith(ext) for ext in TARGET_EXTENSIONS)
                            or "attachment" in c_disp.lower()
                            or "video/" in c_type
                            or ("application/octet-stream" in c_type and c_len and int(c_len) > 500 * 1024)
                        )
                        if is_media:
                            cand_title = None
                            if "filename=" in c_disp:
                                fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', c_disp)
                                if fn_match:
                                    cand_title = fn_match.group(1).strip()
                            if not cand_title:
                                cand_title = final_url.split("/")[-1].split("?")[0] or "downloaded_file.mp4"

                            logger.info(f"BS4 download button successfully sniffed direct stream: {cand_title}")
                            return {
                                "type": "m3u8" if ".m3u8" in clean_final_path else "direct",
                                "url": final_url,
                                "title": cand_title,
                                "headers": headers
                            }
            except Exception as ex:
                logger.debug(f"Candidate check failed for {cand_url}: {ex}")

        # 4. Search for Dean Edwards packed JS or inline .m3u8/.mp4 stream URLs
        unpacked_or_html = html
        if "eval(function(p,a,c,k,e,d)" in html:
            from bot.extractors.video_hosts import unpack_dean_edwards
            unpacked = unpack_dean_edwards(html)
            if unpacked:
                unpacked_or_html = html + "\n" + unpacked

        m3u8_matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', unpacked_or_html)
        if m3u8_matches:
            title_tag = soup.find("title")
            title = "stream_video.mp4"
            if title_tag and title_tag.text:
                title = re.sub(r"[^\w\s\.\-]", "", title_tag.text).strip().replace(" ", "_")
                if not title.lower().endswith(".mp4"):
                    title += ".mp4"
            return {
                "type": "m3u8",
                "url": m3u8_matches[0],
                "title": title,
                "headers": headers
            }

    except Exception as e:
        logger.debug(f"BS4 extraction error for {url}: {e}")

    return None
