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
        self.assertIn("🏃", bar_0)
        bar_50 = generate_bar(50, 100)
        self.assertIn("50.0%", bar_50)
        self.assertIn("🏃", bar_50)
        bar_100 = generate_bar(100, 100)
        self.assertIn("100.0%", bar_100)
        self.assertIn("🏃", bar_100)

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

    def test_get_user_settings_async(self):
        import asyncio
        from bot.database import init_db, get_user_settings
        async def run_check():
            await init_db()
            settings = await get_user_settings(999999)
            self.assertIsInstance(settings, dict)
            self.assertIn("custom_thumb", settings)
            self.assertIn("custom_caption", settings)
        asyncio.run(run_check())


    def test_natural_sort_urls(self):
        from bot.core.sorter import natural_sort_urls
        # 1. Natural ordering with episodes
        urls = [
            "https://site.com/video/ep10.mp4",
            "https://site.com/video/ep2.mp4",
            "https://site.com/video/ep1.mp4",
        ]
        sorted_urls = natural_sort_urls(urls)
        self.assertEqual(sorted_urls, [
            "https://site.com/video/ep1.mp4",
            "https://site.com/video/ep2.mp4",
            "https://site.com/video/ep10.mp4",
        ])

        # 2. Large timestamps / Streamtape style numerical sequence
        st_urls = [
            "https://streamtape.com/v/LaAoA64Z60iRqpo/1_4940488481018219350.mp4",
            "https://streamtape.com/v/Magep9PXjdim4mw/1_4940488481018219348.mp4",
        ]
        st_sorted = natural_sort_urls(st_urls)
        self.assertEqual(st_sorted[0], st_urls[1])
        self.assertEqual(st_sorted[1], st_urls[0])

        # 3. Fallback / Alternative: No digits in any URL -> Preserves original user order 100%
        no_digits = [
            "https://site.com/alpha.mp4",
            "https://site.com/gamma.mp4",
            "https://site.com/beta.mp4",
        ]
        self.assertEqual(natural_sort_urls(no_digits), no_digits)

    def test_batch_summary_pagination_safety(self):
        import asyncio
        from bot.core.queue_manager import QueueManager, BatchInfo

        sent_messages = []

        class MockClient:
            async def send_message(self, chat_id, text):
                sent_messages.append(text)
                return True

        qm = QueueManager()
        batch = BatchInfo(
            batch_id="test_batch_long",
            chat_id=12345,
            user_id=67890,
            total_count=60,
            is_album=True,
            failed_count=60
        )
        # Create 60 long failure URLs (would be >4500 chars)
        for i in range(60):
            batch.failed_urls.append((
                f"https://streamtape.com/v/example{i}/Long_Video_Title_Part_{i:03d}.mp4",
                "HTTP 500 Internal Server Error from upstream provider"
            ))

        async def run_test():
            await qm._send_batch_summary(MockClient(), batch)

        asyncio.run(run_test())

        # Verify that summary was split into multiple messages and none exceeded 4000 characters
        self.assertGreaterEqual(len(sent_messages), 2)
        for msg in sent_messages:
            self.assertLess(len(msg), 4000)

    def test_cancel_batch(self):
        from bot.core.queue_manager import QueueManager
        qm = QueueManager()
        batch = qm.register_batch("batch_c1", 111, 222, 10, is_album=True)
        self.assertFalse(batch.cancel_event.is_set())
        success = qm.cancel_batch("batch_c1")
        self.assertTrue(success)
        self.assertTrue(batch.cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
