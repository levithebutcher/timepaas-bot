import logging
from bot.extractors.general_ext import extract_from_general_website

logger = logging.getLogger(__name__)


async def extract_with_bs4(url: str) -> dict:
    """
    Backward-compatible entry point routing to the Universal General Website Extractor.
    """
    return await extract_from_general_website(url)
