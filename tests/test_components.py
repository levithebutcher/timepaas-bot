"""
Unit test suite verifying component logic:
1. URL parsing and multi-link detection
2. Progress bar and size formatting
3. Archive format recognition
"""

import unittest
from pathlib import Path
from bot.core.progress import format_size, format_time, generate_bar
from bot.core.archive_manager import is_archive_file
from bot.core.downloader import parse_aria2_size, derive_filename, sanitize_headers
from bot.handlers.message_parser import URL_REGEX


class TestComponents(unittest.TestCase):

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(500), "500.00 B")
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1024 * 1024), "1.00 MB")
        self.assertEqual(format_size(1024 * 1024 * 1024), "1.00 GB")

    def test_format_time(self):
        self.assertEqual(format_time(0), "00:00")
        self.assertEqual(format_time(45), "00:45")
        self.assertEqual(format_time(125), "02:05")
        self.assertEqual(format_time(3665), "01:01:05")

    def test_generate_bar(self):
        bar_0 = generate_bar(0, 100)
        self.assertIn("0.0%", bar_0)
        bar_50 = generate_bar(50, 100)
        self.assertIn("50.0%", bar_50)
        bar_100 = generate_bar(100, 100)
        self.assertIn("100.0%", bar_100)

    def test_archive_recognition(self):
        self.assertTrue(is_archive_file(Path("bundle.zip")))
        self.assertTrue(is_archive_file(Path("data.rar")))
        self.assertTrue(is_archive_file(Path("archive.tar.gz")))
        self.assertTrue(is_archive_file(Path("files.7z")))
        self.assertFalse(is_archive_file(Path("movie.mp4")))
        self.assertFalse(is_archive_file(Path("image.png")))

    def test_url_extraction(self):
        raw_text = """
        Check this video: https://example.com/video1.mp4
        And this page: https://mysite.org/watch?v=12345
        www.directlink.com/file.zip
        """
        urls = URL_REGEX.findall(raw_text)
        self.assertEqual(len(urls), 3)

    def test_parse_aria2_size(self):
        self.assertEqual(parse_aria2_size("1024B"), 1024)
        self.assertEqual(parse_aria2_size("1KiB"), 1024)
        self.assertEqual(parse_aria2_size("4.5MiB"), int(4.5 * 1024 * 1024))
        self.assertEqual(parse_aria2_size("1.2GiB"), int(1.2 * 1024 * 1024 * 1024))
        self.assertEqual(parse_aria2_size("invalid"), 0)

    def test_derive_filename(self):
        self.assertEqual(derive_filename("https://example.com/video.mp4"), "video.mp4")
        self.assertEqual(
            derive_filename("https://example.com/download", {"Content-Disposition": 'attachment; filename="clip.mkv"'}),
            "clip.mkv"
        )

    def test_sanitize_headers(self):
        dirty = {
            ":status": "200",
            "Set-Cookie": "session=xyz\r\n",
            "User-Agent": "TestAgent\r\nInjected",
            "Referer": "https://example.com/\n",
            "Content-Length": "12345"
        }
        clean = sanitize_headers(dirty)
        self.assertNotIn(":status", clean)
        self.assertNotIn("Set-Cookie", clean)
        self.assertNotIn("Content-Length", clean)
        self.assertNotIn("\r", clean.get("User-Agent", ""))
        self.assertNotIn("\n", clean.get("User-Agent", ""))
        self.assertNotIn("\n", clean.get("Referer", ""))
        self.assertEqual(clean.get("User-Agent"), "TestAgentInjected")
        self.assertEqual(clean.get("Referer"), "https://example.com/")

    def test_album_batch_registration(self):
        from bot.core.queue_manager import QueueManager
        qm = QueueManager()
        qm.register_batch("batch_123", 111, 222, 5, is_album=True)
        batch = qm.batches["batch_123"]
        self.assertTrue(batch.is_album)
        self.assertEqual(batch.total_count, 5)

    def test_input_media_video_stub(self):
        from bot.core.uploader import InputMediaVideo
        imv = InputMediaVideo(media="video.mp4", duration=10, width=1280, height=720)
        self.assertEqual(imv.media, "video.mp4")
        self.assertEqual(imv.duration, 10)
        self.assertTrue(imv.supports_streaming)


if __name__ == "__main__":
    unittest.main()
