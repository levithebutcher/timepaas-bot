import asyncio

# Ensure an active event loop exists for Pyrogram sync wrappers on Python 3.12+ / 3.14+
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import unittest
from pathlib import Path
from bot.core.sorter import split_into_album_chunks
from bot.database import init_db, set_dump_channel, get_dump_channel
from bot.core.uploader import (
    _METADATA_SEMAPHORE,
    _UPLOAD_SEMAPHORE,
    upload_single_to_dump,
    deliver_dumped_album
)
from bot.handlers.commands import (
    setdump_handler,
    getdump_handler,
    cleardump_handler
)


class TestAlbumRelay(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_split_into_album_chunks_balancing(self):
        """Verify Option A smart mathematically balanced chunks with no orphan items."""
        # 1 item (single video mode)
        c1 = split_into_album_chunks(["u1"], max_size=10, min_size=2)
        self.assertEqual(len(c1), 1)
        self.assertEqual(len(c1[0]), 1)

        # 2 items
        c2 = split_into_album_chunks(["u1", "u2"], max_size=10, min_size=2)
        self.assertEqual(len(c2), 1)
        self.assertEqual(len(c2[0]), 2)

        # 10 items (single full album)
        c10 = split_into_album_chunks(list(range(10)), max_size=10, min_size=2)
        self.assertEqual(len(c10), 1)
        self.assertEqual(len(c10[0]), 10)

        # 11 items -> MUST be [6, 5] (never 10 + 1)
        c11 = split_into_album_chunks(list(range(11)), max_size=10, min_size=2)
        sizes11 = [len(x) for x in c11]
        self.assertEqual(sizes11, [6, 5])

        # 12 items -> [6, 6]
        c12 = split_into_album_chunks(list(range(12)), max_size=10, min_size=2)
        self.assertEqual([len(x) for x in c12], [6, 6])

        # 19 items -> [10, 9]
        c19 = split_into_album_chunks(list(range(19)), max_size=10, min_size=2)
        self.assertEqual([len(x) for x in c19], [10, 9])

        # 20 items -> [10, 10]
        c20 = split_into_album_chunks(list(range(20)), max_size=10, min_size=2)
        self.assertEqual([len(x) for x in c20], [10, 10])

        # 21 items -> [7, 7, 7]
        c21 = split_into_album_chunks(list(range(21)), max_size=10, min_size=2)
        self.assertEqual([len(x) for x in c21], [7, 7, 7])

        # 31 items -> [8, 8, 8, 7]
        c31 = split_into_album_chunks(list(range(31)), max_size=10, min_size=2)
        self.assertEqual([len(x) for x in c31], [8, 8, 8, 7])

        # Verify all sizes for any count from 2 to 60 are between 2 and 10
        for count in range(2, 61):
            chunks = split_into_album_chunks(list(range(count)), max_size=10, min_size=2)
            sizes = [len(c) for c in chunks]
            self.assertEqual(sum(sizes), count)
            self.assertTrue(all(2 <= s <= 10 for s in sizes), f"Invalid size in {sizes} for count {count}")

    def test_database_dump_channel_lifecycle(self):
        """Verify saving, retrieving, and clearing dump channel in database."""
        async def run_db_test():
            await init_db()

            # Set integer channel ID
            test_id = -1009876543210
            await set_dump_channel(test_id)
            retrieved = await get_dump_channel()
            self.assertEqual(retrieved, test_id)

            # Set string username channel
            test_user = "@my_telegram_dump"
            await set_dump_channel(test_user)
            retrieved = await get_dump_channel()
            self.assertEqual(retrieved, test_user)

            # Clear channel
            await set_dump_channel(None)
            retrieved = await get_dump_channel()
            self.assertIsNone(retrieved)

        self.loop.run_until_complete(run_db_test())

    def test_uploader_helpers_and_semaphores(self):
        """Verify Option B uploader helpers and CPU protection semaphore exist."""
        self.assertIsNotNone(_METADATA_SEMAPHORE)
        self.assertIsNotNone(_UPLOAD_SEMAPHORE)
        self.assertTrue(callable(upload_single_to_dump))
        self.assertTrue(callable(deliver_dumped_album))

    def test_command_handlers_registered(self):
        """Verify dump channel command handlers exist and are callable."""
        self.assertTrue(callable(setdump_handler))
        self.assertTrue(callable(getdump_handler))
        self.assertTrue(callable(cleardump_handler))


if __name__ == "__main__":
    unittest.main()
