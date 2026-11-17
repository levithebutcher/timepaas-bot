import re
import math
import logging
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)


def natural_sort_urls(urls: list[str]) -> list[str]:
    """
    Naturally sorts URLs based on numerical sequences in the filename or URL path.
    Example: 'ep1', 'ep2', 'ep10' are sorted in numerical order rather than lexicographical.

    Fallback / Alternative:
    If no numerical sequence is detected across the URLs, or if URLs do not contain
    comparable sequences, the original submission order is 100% preserved.
    """
    if not urls or len(urls) <= 1:
        return list(urls)

    try:
        def extract_sequence_info(url: str):
            parsed = urlparse(url)
            path = unquote(parsed.path)
            segments = [s for s in path.split("/") if s]

            # 1. Check filename or last path segment - ignore file extension digits (.mp4, .m4v, .7z)
            raw_target = segments[-1] if segments else ""
            if "." in raw_target:
                stem = raw_target.rsplit(".", 1)[0]
                ext = "." + raw_target.rsplit(".", 1)[1]
            else:
                stem = raw_target
                ext = ""

            digits = re.findall(r"\d+", stem)
            target = stem

            # 2. If the last segment was completely empty or a generic web route, check preceding segment
            if not digits and (not stem or stem.lower() in ("play", "view", "watch", "download", "index", "file")) and len(segments) > 1:
                for seg in reversed(segments[:-1]):
                    seg_digits = re.findall(r"\d+", seg)
                    if seg_digits:
                        target = seg
                        digits = seg_digits
                        break

            # 3. If still no digits and query string exists (e.g. ?ep=1 or ?part=2)
            if not digits and parsed.query:
                query_digits = re.findall(r"\d+", parsed.query)
                if query_digits:
                    target = parsed.query
                    digits = query_digits

            if not digits:
                return None, raw_target

            # Tagged tokens to prevent TypeError('<' not supported between 'int' and 'str'):
            # (0, int_val) for numbers, (1, str_val) for text
            tokens = []
            for part in re.split(r"(\d+)", target):
                if part.isdigit():
                    tokens.append((0, int(part)))
                elif part:
                    tokens.append((1, part.lower()))
            return tokens, raw_target

        # Check if ANY url in the list actually contains sequence information
        has_sequence = False
        for u in urls:
            tokens, _ = extract_sequence_info(u)
            if tokens is not None:
                has_sequence = True
                break

        # Alternative / Fallback: If no sorting sequence is found in the links at all,
        # preserve original user submission order
        if not has_sequence:
            return list(urls)

        indexed = list(enumerate(urls))

        def sort_key(item):
            idx, u = item
            tokens, target = extract_sequence_info(u)
            if tokens is not None:
                # Group 0: Sequenced items -> sorted by tagged natural tokens, then original idx
                return (0, tokens, idx)
            else:
                # Group 1: Non-sequenced items -> preserve original relative order
                return (1, [(1, target.lower())], idx)

        indexed.sort(key=sort_key)
        return [u for _, u in indexed]

    except Exception as e:
        logger.warning(f"natural_sort_urls safely falling back to original submission order: {e}")
        return list(urls)


def split_into_album_chunks(items: list, max_size: int = 10, min_size: int = 2) -> list[list]:
    """
    Splits items into balanced album packs (between min_size and max_size).
    Guarantees no orphan single items remain when total items >= 2.
    Example:
      11 items -> [6, 5] (instead of 10 + 1)
      21 items -> [7, 7, 7] (instead of 10 + 10 + 1)
    """
    if not items:
        return []

    n = len(items)
    if n <= max_size:
        return [items]

    num_chunks = math.ceil(n / max_size)
    base_size = n // num_chunks
    rem = n % num_chunks
    chunks = []
    start = 0
    for i in range(num_chunks):
        sz = base_size + (1 if i < rem else 0)
        chunks.append(items[start:start + sz])
        start += sz
    return chunks
