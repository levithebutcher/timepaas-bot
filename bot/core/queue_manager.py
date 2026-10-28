import time
import shutil
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
try:
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    InlineKeyboardMarkup = None
    InlineKeyboardButton = None
from bot.config import (
    MAX_CONCURRENT_TASKS,
    MAX_USER_TASKS,
    DOWNLOAD_DIR,
    TEMP_DIR,
    EXTRACT_DIR,
    MAX_SPLIT_SIZE_BYTES
)
from bot.core.cleaner import remove_path
from bot.core.progress import update_status_message
from bot.core.downloader import download_direct_stream, download_m3u8_stream, derive_filename
from bot.core.splitter import split_video_file
from bot.core.archive_manager import is_archive_file, extract_archive
from bot.core.uploader import upload_file, upload_photo_albums, upload_video_albums
from bot.extractors.manager import extract_media_link
from bot.database import get_user_settings

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    id: str
    user_id: int
    chat_id: int
    url: str
    status_msg_id: int
    batch_id: str
    status: str = "Queued"
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    error_msg: str = ""
    start_time: float = field(default_factory=time.time)


@dataclass
class BatchInfo:
    batch_id: str
    chat_id: int
    user_id: int
    total_count: int
    is_album: bool = False
    task_ids: list[str] = field(default_factory=list)
    done_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    failed_urls: list[tuple[str, str]] = field(default_factory=list)
    album_ready_items: list[tuple[Path, str, int]] = field(default_factory=list)


class QueueManager:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        self.queue = asyncio.Queue()
        self.tasks: dict[str, DownloadTask] = {}
        self.batches: dict[str, BatchInfo] = {}
        self.decision_futures: dict[str, asyncio.Future] = {}
        self._user_task_counts: dict[int, int] = {}
        self._workers: list[asyncio.Task] = []

    def get_user_active_count(self, user_id: int) -> int:
        return self._user_task_counts.get(user_id, 0)

    def register_batch(self, batch_id: str, chat_id: int, user_id: int, total_count: int, is_album: bool = False):
        self.batches[batch_id] = BatchInfo(
            batch_id=batch_id,
            chat_id=chat_id,
            user_id=user_id,
            total_count=total_count,
            is_album=is_album
        )

    async def enqueue_task(self, task: DownloadTask):
        self.tasks[task.id] = task
        self._user_task_counts[task.user_id] = self._user_task_counts.get(task.user_id, 0) + 1
        
        batch = self.batches.get(task.batch_id)
        if batch:
            batch.task_ids.append(task.id)

        await self.queue.put(task)
        logger.info(f"Task {task.id} enqueued for user {task.user_id}")

    async def _prompt_zip_choice(self, client, task: DownloadTask, filename: str, count: int) -> str:
        """Prompts user with inline buttons when a ZIP contains > 50 images."""
        fut = asyncio.get_running_loop().create_future()
        self.decision_futures[task.id] = fut

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🖼️ Images Only ({count})", callback_data=f"zipchoice:{task.id}:images"),
                InlineKeyboardButton("📦 ZIP File Only", callback_data=f"zipchoice:{task.id}:zip")
            ],
            [
                InlineKeyboardButton("✨ Send Both (ZIP + Images)", callback_data=f"zipchoice:{task.id}:both")
            ]
        ])

        try:
            prompt_msg = await client.send_message(
                chat_id=task.chat_id,
                text=(
                    f"📦 **Large Image Archive Detected!**\n"
                    f"File: `{filename}` contains **{count} images**.\n\n"
                    f"Kripya option choose karein ki aapko ye images kaise chahiye (60s timer):"
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Failed to send zip choice prompt: {e}")
            self.decision_futures.pop(task.id, None)
            return "both"

        choice = "both"
        try:
            choice = await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            try:
                await prompt_msg.edit_text(
                    f"⏰ **Timeout (60s):** Auto-selected **Both (ZIP + Images)** for `{filename}`."
                )
            except Exception:
                pass
        finally:
            self.decision_futures.pop(task.id, None)

        return choice

    def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task and task.status not in ("Done", "Failed", "Cancelled"):
            task.status = "Cancelled"
            task.cancel_event.set()
            fut = self.decision_futures.pop(task_id, None)
            if fut and not fut.done():
                fut.cancel()
            logger.info(f"Task {task_id} marked as cancelled.")
            return True
        return False

    def cancel_all_for_user(self, user_id: int) -> int:
        cancelled_count = 0
        for task in self.tasks.values():
            if task.user_id == user_id and task.status not in ("Done", "Failed", "Cancelled"):
                task.status = "Cancelled"
                task.cancel_event.set()
                cancelled_count += 1
        return cancelled_count

    async def start_workers(self, client, num_workers: int = MAX_CONCURRENT_TASKS):
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker_loop(client, i + 1))
            self._workers.append(worker)
        logger.info(f"Started {num_workers} background queue workers.")

    async def _worker_loop(self, client, worker_id: int):
        while True:
            task: DownloadTask = await self.queue.get()
            try:
                if task.cancel_event.is_set():
                    task.status = "Cancelled"
                    await self._handle_task_completion(client, task, "Cancelled")
                    continue

                async with self.semaphore:
                    await self._process_task(client, task)

            except Exception as e:
                logger.error(f"Worker {worker_id} unhandled exception on task {task.id}: {e}", exc_info=True)
            finally:
                self.queue.task_done()

    async def _process_task(self, client, task: DownloadTask):
        task_dir = DOWNLOAD_DIR / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        downloaded_file = None
        user_settings = await get_user_settings(task.user_id)

        try:
            # Step 1: Extraction
            task.status = "Extracting"
            await update_status_message(
                client=client,
                chat_id=task.chat_id,
                message_id=task.status_msg_id,
                task_id=task.id,
                action="🔍 Extracting video link...",
                force=True
            )

            media_info = await extract_media_link(task.url)
            if not media_info or not media_info.get("url"):
                raise RuntimeError("No downloadable video or media stream could be extracted from page.")

            if task.cancel_event.is_set():
                raise asyncio.CancelledError()

            stream_url = media_info["url"]
            stream_type = media_info.get("type", "direct")
            title = media_info.get("title") or derive_filename(stream_url)
            headers = media_info.get("headers", {})

            # Step 2: Download
            task.status = "Downloading"
            target_path = task_dir / title
            start_dl_time = time.time()

            async def dl_progress(current, total):
                if task.cancel_event.is_set():
                    raise asyncio.CancelledError()
                await update_status_message(
                    client=client,
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    task_id=task.id,
                    action="📥 Downloading...",
                    current=current,
                    total=total,
                    start_time=start_dl_time,
                    file_name=title
                )

            if stream_type == "m3u8":
                downloaded_file = await download_m3u8_stream(
                    m3u8_url=stream_url,
                    target_path=target_path.with_suffix(".mp4"),
                    headers=headers,
                    progress_callback=dl_progress,
                    cancel_event=task.cancel_event
                )
            else:
                downloaded_file = await download_direct_stream(
                    url=stream_url,
                    target_path=target_path,
                    headers=headers,
                    progress_callback=dl_progress,
                    cancel_event=task.cancel_event
                )

            if task.cancel_event.is_set():
                raise asyncio.CancelledError()

            # Step 3: Handle ZIP / Archive files
            if user_settings.get("auto_extract_zip", True) and is_archive_file(downloaded_file):
                task.status = "Extracting Archive"
                await update_status_message(
                    client=client,
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    task_id=task.id,
                    action="📦 Extracting images & videos from ZIP...",
                    force=True
                )

                archive_result = extract_archive(downloaded_file, task.id)

                if archive_result["is_encrypted"]:
                    # Password protected: send raw zip as document
                    await client.send_message(
                        chat_id=task.chat_id,
                        text=f"⚠️ **Note:** `{downloaded_file.name}` is password-protected. Uploading as raw archive document."
                    )
                elif archive_result["success"] and (archive_result["videos"] or archive_result["images"]):
                    img_count = len(archive_result["images"])
                    choice = "images"  # default for <= 50 images

                    if img_count > 50:
                        choice = await self._prompt_zip_choice(
                            client, task, downloaded_file.name, img_count
                        )

                    task.status = "Uploading Media"

                    # 1. Send raw ZIP file if user chose 'zip' or 'both'
                    if choice in ("zip", "both"):
                        await upload_file(
                            client=client,
                            chat_id=task.chat_id,
                            file_path=downloaded_file,
                            caption=f"📦 `{downloaded_file.name}`",
                            as_document=True
                        )

                    # 2. Send Extracted Images as Albums if user chose 'images' or 'both'
                    if choice in ("images", "both") and archive_result["images"]:
                        await upload_photo_albums(client, task.chat_id, archive_result["images"])

                    # 3. Always send any videos found in archive
                    for vid in archive_result["videos"]:
                        if task.cancel_event.is_set():
                            raise asyncio.CancelledError()
                        await upload_file(
                            client=client,
                            chat_id=task.chat_id,
                            file_path=vid,
                            caption=f"🎥 `{vid.name}`",
                            custom_thumb=user_settings.get("custom_thumb")
                        )

                    remove_path(archive_result["extract_path"])
                    task.status = "Done"
                    await self._handle_task_completion(client, task, "Done")
                    return

            # Step 4: Video Splitting Check (> 1.95 GB)
            parts_to_upload = [downloaded_file]
            if downloaded_file.stat().st_size > MAX_SPLIT_SIZE_BYTES:
                task.status = "Splitting"
                await update_status_message(
                    client=client,
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    task_id=task.id,
                    action="✂ File > 1.95GB. Splitting into parts...",
                    force=True
                )
                parts_to_upload = await split_video_file(downloaded_file, MAX_SPLIT_SIZE_BYTES)

            batch = self.batches.get(task.batch_id)
            if batch and batch.is_album:
                task.status = "Ready for Album"
                caption = user_settings.get("custom_caption") or f"🎬 `{downloaded_file.name}`"
                album_dir = DOWNLOAD_DIR / f"album_{batch.batch_id}"
                album_dir.mkdir(parents=True, exist_ok=True)
                for part in parts_to_upload:
                    dest_path = album_dir / part.name
                    if dest_path.exists():
                        dest_path = album_dir / f"{task.id[:6]}_{part.name}"
                    shutil.move(str(part), str(dest_path))
                    batch.album_ready_items.append((dest_path, caption, task.status_msg_id))
                await update_status_message(
                    client=client,
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    task_id=task.id,
                    action="⏳ Downloaded! Waiting for other album videos...",
                    force=True
                )
                await self._handle_task_completion(client, task, "Done")
                return

            # Step 5: Uploading
            task.status = "Uploading"
            for part in parts_to_upload:
                if task.cancel_event.is_set():
                    raise asyncio.CancelledError()

                part_size = part.stat().st_size
                start_up_time = time.time()

                async def up_progress(current, total):
                    if task.cancel_event.is_set():
                        raise asyncio.CancelledError()
                    await update_status_message(
                        client=client,
                        chat_id=task.chat_id,
                        message_id=task.status_msg_id,
                        task_id=task.id,
                        action="📤 Uploading to Telegram...",
                        current=current,
                        total=total or part_size,
                        start_time=start_up_time,
                        file_name=part.name
                    )

                caption = user_settings.get("custom_caption") or f"🎬 `{part.name}`"
                await upload_file(
                    client=client,
                    chat_id=task.chat_id,
                    file_path=part,
                    caption=caption,
                    custom_thumb=user_settings.get("custom_thumb"),
                    progress_callback=up_progress
                )

            task.status = "Done"
            await self._handle_task_completion(client, task, "Done")

        except asyncio.CancelledError:
            task.status = "Cancelled"
            await self._handle_task_completion(client, task, "Cancelled")

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            task.status = "Failed"
            task.error_msg = str(e)
            await self._handle_task_completion(client, task, "Failed")

        finally:
            remove_path(task_dir)

    async def _handle_task_completion(self, client, task: DownloadTask, outcome: str):
        # Decrement user task count
        curr = self._user_task_counts.get(task.user_id, 1)
        self._user_task_counts[task.user_id] = max(0, curr - 1)

        batch = self.batches.get(task.batch_id)

        # Update individual task status message: Delete upon success so chat stays clean
        try:
            if outcome == "Done":
                if not (batch and batch.is_album):
                    await client.delete_messages(
                        chat_id=task.chat_id,
                        message_ids=task.status_msg_id
                    )
            elif outcome == "Cancelled":
                await client.edit_message_text(
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    text=f"🚫 **Task Cancelled.**\n🔗 `{task.url}`"
                )
            else:
                await client.edit_message_text(
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    text=f"❌ **Task Failed!**\n🔗 `{task.url}`\n**Reason:** `{task.error_msg}`"
                )
        except Exception as e:
            logger.debug(f"Could not update final task status for {task.id}: {e}")

        # Batch progress check
        if not batch:
            return

        if outcome == "Done":
            batch.done_count += 1
        elif outcome == "Cancelled":
            batch.cancelled_count += 1
        else:
            batch.failed_count += 1
            batch.failed_urls.append((task.url, task.error_msg))

        # Check if entire batch is complete
        total_processed = batch.done_count + batch.failed_count + batch.cancelled_count
        if total_processed >= batch.total_count:
            if batch.is_album and batch.album_ready_items:
                user_settings = await get_user_settings(batch.user_id)
                album_videos = [(item[0], item[1]) for item in batch.album_ready_items]
                try:
                    await upload_video_albums(
                        client=client,
                        chat_id=batch.chat_id,
                        video_items=album_videos,
                        custom_thumb=user_settings.get("custom_thumb")
                    )
                except Exception as e:
                    logger.error(f"Failed to upload album batch {batch.batch_id}: {e}")
                finally:
                    # Clean up album status messages and folder
                    for _, _, s_id in batch.album_ready_items:
                        try:
                            await client.delete_messages(chat_id=batch.chat_id, message_ids=s_id)
                        except Exception:
                            pass
                    album_dir = DOWNLOAD_DIR / f"album_{batch.batch_id}"
                    remove_path(album_dir)
                    batch.album_ready_items.clear()

            await self._send_batch_summary(client, batch)

    async def _send_batch_summary(self, client, batch: BatchInfo):
        # If everything finished cleanly with no failures, keep chat clean (no summary spam)
        if batch.failed_count == 0 and batch.cancelled_count == 0:
            self.batches.pop(batch.batch_id, None)
            return

        summary_lines = [
            "🏁 **Batch Processing Report:**",
            f"✅ **Finished:** {batch.done_count}",
            f"❌ **Failed:** {batch.failed_count}",
            f"🚫 **Cancelled:** {batch.cancelled_count}"
        ]

        if batch.failed_urls:
            summary_lines.append("\n**Failed Links:**")
            for url, err in batch.failed_urls:
                summary_lines.append(f"• `{url}` — *{err[:50]}*")

        try:
            await client.send_message(
                chat_id=batch.chat_id,
                text="\n".join(summary_lines)
            )
        except Exception as e:
            logger.error(f"Failed to send batch summary for {batch.batch_id}: {e}")
        finally:
            self.batches.pop(batch.batch_id, None)


# Global singleton instance
queue_manager = QueueManager()
