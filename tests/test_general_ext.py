import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import unittest
from bs4 import BeautifulSoup
from bot.extractors.general_ext import (
    extract_page_title,
    find_base64_stream_urls,
    extract_from_query_params
)


class TestGeneralExtractor(unittest.TestCase):

    def test_extract_page_title_og(self):
        html = '<meta property="og:title" content="Awesome Movie 2026">'
        soup = BeautifulSoup(html, "html.parser")
        title = extract_page_title(soup)
        self.assertEqual(title, "Awesome_Movie_2026.mp4")

    def test_extract_page_title_title_tag(self):
        html = '<title>Secret Document Episode 01 - Watch Free Online</title>'
        soup = BeautifulSoup(html, "html.parser")
        title = extract_page_title(soup)
        self.assertEqual(title, "Secret_Document_Episode_01.mp4")

    def test_find_base64_stream_urls(self):
        # Base64 for https://example.com/stream.m3u8 is aHR0cHM6Ly9leGFtcGxlLmNvbS9zdHJlYW0ubTN1OA==
        text = 'var stream = atob("aHR0cHM6Ly9leGFtcGxlLmNvbS9zdHJlYW0ubTN1OA==");'
        urls = find_base64_stream_urls(text)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://example.com/stream.m3u8")

    def test_extract_from_query_params(self):
        url = "https://general-site.com/embed?video=https%3A%2F%2Fcdn.storage.org%2Fclip.mp4&autoplay=1"
        extracted = extract_from_query_params(url)
        self.assertEqual(extracted, "https://cdn.storage.org/clip.mp4")

        no_media = "https://general-site.com/search?q=test"
        self.assertIsNone(extract_from_query_params(no_media))


if __name__ == "__main__":
    unittest.main()
