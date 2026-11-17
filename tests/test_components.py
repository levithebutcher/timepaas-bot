"""
Unit test suite verifying component logic:
1. URL parsing and multi-link detection
2. Progress bar and size formatting
3. Archive format recognition
"""

import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

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

    def test_vidara_domain_matching(self):
        from bot.extractors.video_hosts import is_matching_host, VIDARA_DOMAINS
        self.assertTrue(is_matching_host("vidara.to", VIDARA_DOMAINS))
        self.assertTrue(is_matching_host("gasobni.com", VIDARA_DOMAINS))
        self.assertTrue(is_matching_host("sub.vidara.so", VIDARA_DOMAINS))
        self.assertFalse(is_matching_host("othersite.com", VIDARA_DOMAINS))

    def test_archivebate_and_mixdrop_domain_matching(self):
        from bot.extractors.video_hosts import is_matching_host, ARCHIVEBATE_DOMAINS, MIXDROP_DOMAINS
        self.assertTrue(is_matching_host("archivebate.com", ARCHIVEBATE_DOMAINS))
        self.assertTrue(is_matching_host("www.archivebate.com", ARCHIVEBATE_DOMAINS))
        self.assertTrue(is_matching_host("mixdrop.ag", MIXDROP_DOMAINS))
        self.assertTrue(is_matching_host("mxdrop.click", MIXDROP_DOMAINS))
        self.assertTrue(is_matching_host("mixdrop.co", MIXDROP_DOMAINS))
        self.assertFalse(is_matching_host("randomsite.com", ARCHIVEBATE_DOMAINS))

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

        # 4. Mixed URLs starting with int vs str (e.g. 1_...348.mp4 vs Riding_2.mp4 vs Hardcore.mp4)
        mixed = [
            "https://streamtape.com/v/Magep9PXjdim4mw/1_4940488481018219348.mp4",
            "https://streamtape.com/v/23lJ2Km1mQUWa7/Hardcore.mp4",
            "https://streamtape.com/v/AlgDvjGeeRtBRW/Riding_2.mp4",
            "https://streamtape.com/v/LaAoA64Z60iRqpo/1_4940488481018219350.mp4"
        ]
        sorted_mixed = natural_sort_urls(mixed)
        self.assertEqual(len(sorted_mixed), 4)
        self.assertEqual(sorted_mixed[0], mixed[0])  # 1_...348
        self.assertEqual(sorted_mixed[1], mixed[3])  # 1_...350
        self.assertEqual(sorted_mixed[2], mixed[2])  # Riding_2
        self.assertEqual(sorted_mixed[3], mixed[1])  # Hardcore (no digits fallback)

    def test_batch_summary_pagination_safety(self):
        import asyncio
        from bot.core.queue_manager import QueueManager, BatchInfo

        sent_messages = []

        class MockClient:
            async def send_message(self, chat_id, text, **kwargs):
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

    def test_concurrency_and_aria2_connections(self):
        from bot.config import ARIA2_CONNECTIONS, ALBUM_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_TASKS
        self.assertGreaterEqual(ARIA2_CONNECTIONS, 4)
        self.assertGreaterEqual(ALBUM_CONCURRENT_DOWNLOADS, 2)
        self.assertGreaterEqual(MAX_CONCURRENT_TASKS, 4)

    def test_album_dashboard_multi_download_format(self):
        import asyncio
        from bot.core.progress import update_album_pipeline_dashboard

        edited_texts = []

        class MockClient:
            async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
                edited_texts.append(text)
                return True

        current_dl = {
            "active_list": [
                {
                    "file_name": "Episode_01.mp4",
                    "current": 50 * 1024 * 1024,
                    "total": 100 * 1024 * 1024,
                    "speed_str": "12.50 MB/s",
                    "eta_str": "00:04",
                    "item_num": 1,
                    "chunk_total": 10
                },
                {
                    "file_name": "Episode_02.mp4",
                    "current": 80 * 1024 * 1024,
                    "total": 100 * 1024 * 1024,
                    "speed_str": "15.00 MB/s",
                    "eta_str": "00:02",
                    "item_num": 2,
                    "chunk_total": 10
                }
            ],
            "completed_in_pack": 0,
            "chunk_total": 10
        }

        async def run_dash():
            await update_album_pipeline_dashboard(
                client=MockClient(),
                chat_id=123,
                message_id=456,
                batch_id="dash_test_123",
                total_files=10,
                completed_files=0,
                total_albums=1,
                uploaded_albums=0,
                current_dl=current_dl,
                force=True
            )

        asyncio.run(run_dash())
        self.assertEqual(len(edited_texts), 1)
        self.assertIn("<blockquote>", edited_texts[0])
        self.assertIn("</blockquote>", edited_texts[0])
        self.assertIn("Episode_01.mp4", edited_texts[0])
        self.assertIn("Episode_02.mp4", edited_texts[0])
        self.assertIn("12.50 MB/s", edited_texts[0])
        self.assertIn("15.00 MB/s", edited_texts[0])
        self.assertIn("ALBUM PIPELINE", edited_texts[0])

    def test_generate_smooth_bar(self):
        from bot.core.progress import generate_smooth_bar
        bar_0 = generate_smooth_bar(0, 100, length=10)
        self.assertIn("0.0%", bar_0)
        self.assertEqual(bar_0.count("░"), 10)

        bar_50 = generate_smooth_bar(50, 100, length=10)
        self.assertIn("50.0%", bar_50)
        self.assertIn("█" * 5, bar_50)

        bar_100 = generate_smooth_bar(100, 100, length=10)
        self.assertIn("100.0%", bar_100)
        self.assertEqual(bar_100.count("█"), 10)

        # Fractional 73% should have fractional sub-block character
        bar_73 = generate_smooth_bar(73, 100, length=10)
        self.assertIn("73.0%", bar_73)
        self.assertIn("█" * 7, bar_73)

    def test_update_status_message_blockquote_widget(self):
        import asyncio
        from bot.core.progress import update_status_message

        edited_texts = []
        markups = []

        class MockClient:
            async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
                edited_texts.append(text)
                markups.append(reply_markup)
                return True

        async def run():
            await update_status_message(
                client=MockClient(),
                chat_id=111,
                message_id=222,
                task_id="task_widget_test",
                action="📥 Downloading media stream...",
                current=50 * 1024 * 1024,
                total=100 * 1024 * 1024,
                file_name="TestVideo.mp4",
                is_album=False,
                force=True
            )

        asyncio.run(run())
        self.assertEqual(len(edited_texts), 1)
        self.assertIn("<blockquote>", edited_texts[0])
        self.assertIn("</blockquote>", edited_texts[0])
        self.assertIn("TIMEPASS LEECH", edited_texts[0])
        self.assertIn("TestVideo.mp4", edited_texts[0])
        self.assertIsNotNone(markups[0])

    def test_additional_video_hosts_domain_matching(self):
        from bot.extractors.video_hosts import (
            is_matching_host,
            FILEMOON_DOMAINS,
            VOE_DOMAINS,
            MP4UPLOAD_DOMAINS,
            VIDGUARD_DOMAINS,
            GOFILE_DOMAINS,
            KRAKENFILES_DOMAINS,
            PIXELDRAIN_DOMAINS
        )
        self.assertTrue(is_matching_host("filemoon.sx", FILEMOON_DOMAINS))
        self.assertTrue(is_matching_host("voe.sx", VOE_DOMAINS))
        self.assertTrue(is_matching_host("mp4upload.com", MP4UPLOAD_DOMAINS))
        self.assertTrue(is_matching_host("vidguard.to", VIDGUARD_DOMAINS))
        self.assertTrue(is_matching_host("gofile.io", GOFILE_DOMAINS))
        self.assertTrue(is_matching_host("krakenfiles.com", KRAKENFILES_DOMAINS))
        self.assertTrue(is_matching_host("pixeldrain.com", PIXELDRAIN_DOMAINS))
        self.assertFalse(is_matching_host("unknownrandomhost.xyz", FILEMOON_DOMAINS))

    def test_sanitize_filename(self):
        from bot.core.downloader import sanitize_filename
        self.assertEqual(sanitize_filename("clean_file.mp4"), "clean_file.mp4")
        self.assertEqual(sanitize_filename('invalid:*?"<>|file.mp4'), "invalid_______file.mp4")
        self.assertEqual(sanitize_filename(""), "downloaded_media.mp4")

    def test_resolve_clean_title(self):
        from bot.core.queue_manager import resolve_clean_title
        # Non-generic title
        self.assertEqual(resolve_clean_title({"title": "MyVideo.mp4"}, "https://example.com/v/123"), "MyVideo.mp4")
        # Generic title resolved via URL slug
        generic = {"title": "master.mp4", "url": "https://example.com/stream/master.mp4"}
        resolved = resolve_clean_title(generic, "https://site.com/watch/episode_05")
        self.assertEqual(resolved, "episode_05.mp4")

    def test_cancel_all_for_user_with_batches(self):
        from bot.core.queue_manager import QueueManager, DownloadTask
        qm = QueueManager()
        # Task
        t = DownloadTask(
            id="t_cancel_test",
            user_id=1234,
            chat_id=5678,
            url="https://site.com/v.mp4",
            status_msg_id=1,
            batch_id="b1"
        )
        qm.tasks[t.id] = t
        # Batch
        b = qm.register_batch("b_cancel_test", 5678, 1234, 5, is_album=True)
        count = qm.cancel_all_for_user(1234)
        self.assertEqual(count, 2)
        self.assertTrue(t.cancel_event.is_set())
        self.assertTrue(b.cancel_event.is_set())

    def test_split_into_album_chunks_empty(self):
        from bot.core.sorter import split_into_album_chunks
        self.assertEqual(split_into_album_chunks([]), [])

    def test_split_binary_file(self):
        import tempfile
        from bot.core.splitter import split_binary_file
        with tempfile.TemporaryDirectory() as td:
            dummy_file = Path(td) / "large_archive.zip"
            # Create a 50KB dummy file
            dummy_file.write_bytes(b"A" * 50000)
            # Split with 20KB chunk size
            parts = split_binary_file(dummy_file, chunk_size=20000)
            self.assertEqual(len(parts), 3)
            self.assertEqual(parts[0].stat().st_size, 20000)
            self.assertEqual(parts[1].stat().st_size, 20000)
            self.assertEqual(parts[2].stat().st_size, 10000)
            # Verify reconstructed data
            recombined = b"".join(p.read_bytes() for p in parts)
            self.assertEqual(recombined, b"A" * 50000)

    def test_split_video_file_undersize_no_split(self):
        import tempfile
        from bot.core.splitter import split_video_file
        with tempfile.TemporaryDirectory() as td:
            dummy_file = Path(td) / "small_clip.mp4"
            dummy_file.write_bytes(b"\x00" * 1024)
            # target_part_size is larger than file
            parts = asyncio.run(split_video_file(dummy_file, target_part_size=5000))
            self.assertEqual(parts, [dummy_file])

    def test_resolve_dump_chat_formats(self):
        from unittest.mock import AsyncMock, MagicMock
        from bot.handlers.commands import resolve_dump_chat
        from pyrogram.raw.types import ChatInviteAlready

        client = MagicMock()
        client.get_me = AsyncMock(return_value=MagicMock(is_bot=False))
        client.get_chat = AsyncMock(side_effect=lambda cid: MagicMock(id=cid, title=f"Chat {cid}"))
        client.join_chat = AsyncMock(side_effect=lambda inv: MagicMock(id=-1009999999, title="Invite Chat"))
        client.invoke = AsyncMock(return_value=ChatInviteAlready(chat=MagicMock(id=1234567890)))

        # 1. Private channel message link (t.me/c/<id>/<msg>)
        res = asyncio.run(resolve_dump_chat(client, "https://t.me/c/1234567890/45"))
        self.assertEqual(res.id, -1001234567890)

        # 2. Public channel message link
        res = asyncio.run(resolve_dump_chat(client, "https://t.me/my_dump_ch/99"))
        self.assertEqual(res.id, "@my_dump_ch")

        # 3. Public channel URL
        res = asyncio.run(resolve_dump_chat(client, "https://t.me/my_dump_ch"))
        self.assertEqual(res.id, "@my_dump_ch")

        # 4. Raw digits without -100
        res = asyncio.run(resolve_dump_chat(client, "1234567890"))
        self.assertEqual(res.id, -1001234567890)

        # 5. Full -100 channel ID
        res = asyncio.run(resolve_dump_chat(client, "-1001234567890"))
        self.assertEqual(res.id, -1001234567890)

        # 6. Private invite link (Userbot mode)
        res = asyncio.run(resolve_dump_chat(client, "https://t.me/+AbCdEfGh"))
        self.assertEqual(res.id, -1009999999)

        # 6b. Private invite link (Bot mode with CheckChatInvite)
        client.get_me = AsyncMock(return_value=MagicMock(is_bot=True))
        res_bot = asyncio.run(resolve_dump_chat(client, "https://t.me/+AbCdEfGh"))
        self.assertEqual(res_bot.id, -1001234567890)

        # 7. Forwarded message in reply
        reply_msg = MagicMock()
        reply_msg.forward_from_chat = MagicMock(id=-1005555555)
        res = asyncio.run(resolve_dump_chat(client, "", reply_to=reply_msg))
        self.assertEqual(res.id, -1005555555)

    def test_deliver_dumped_album_cleans_dump(self):
        from unittest.mock import AsyncMock, MagicMock
        from bot.core.uploader import deliver_dumped_album

        client = MagicMock()
        client.send_media_group = AsyncMock()
        client.delete_messages = AsyncMock()

        items = [
            {"file_id": "f1", "caption": "c1", "duration": 10, "width": 1280, "height": 720, "msg_id": 101},
            {"file_id": "f2", "caption": "c2", "duration": 20, "width": 1280, "height": 720, "msg_id": 102}
        ]

        asyncio.run(deliver_dumped_album(client, target_chat_id=1234, dump_chat_id=-100999, dumped_items=items))

        # Check send_media_group was called
        client.send_media_group.assert_called_once()
        # Check that dump messages were auto-deleted from dump channel!
        client.delete_messages.assert_called_once_with(chat_id=-100999, message_ids=[101, 102])

    def test_parse_luluvid_title_extraction(self):
        from bot.extractors.video_hosts import _parse_luluvid_content
        sample_html = '''
        <html>
          <head>
            <title>Loading...</title>
            <script>document.title = "adakabeer white guy 1 \\u002d Lulustream.mp4";</script>
          </head>
          <body>
            <script>var x = "https://cdn.example.com/hls/master.m3u8";</script>
          </body>
        </html>
        '''
        stream_url, stream_type, title = _parse_luluvid_content(sample_html)
        self.assertEqual(stream_url, "https://cdn.example.com/hls/master.m3u8")
        self.assertEqual(stream_type, "m3u8")
        self.assertEqual(title, "adakabeer_white_guy_1.mp4")

    def test_progress_html_parsing_safety(self):
        import asyncio
        from pyrogram.parser.html import HTML
        from bot.core.progress import format_time, generate_bar

        h = HTML(None)
        # Test format_time does not return double-dash
        self.assertNotIn("--", format_time(None))
        self.assertNotIn("--", format_time(-1))

        # Test blockquote with dynamic strings parses without unclosed tags
        sample_text = (
            "<blockquote>"
            "⚡ <b>TIMEPASS LEECH</b> • 🎥 <b>Video Player</b>\n"
            "📁 <code>Test &lt;Video&gt; &amp; File.mp4</code>\n"
            f"📊 <code>{generate_bar(50, 100)}</code>\n"
            "💾 <b>50.00 MB</b> / 100.00 MB • ⚡ <b>5.00 MB/s</b> • ⏱ <b>00:10</b>\n"
            "🔄 📥 Downloading media stream..."
            "</blockquote>"
        )
        parsed = asyncio.run(h.parse(sample_text))
        self.assertIsNotNone(parsed)
        self.assertIn("TIMEPASS LEECH", parsed["message"])


if __name__ == "__main__":
    unittest.main()
