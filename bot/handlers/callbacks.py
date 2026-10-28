import logging
try:
    from pyrogram import Client
    from pyrogram.types import CallbackQuery
except ImportError:
    class _MockClient:
        @staticmethod
        def on_callback_query(*args, **kwargs):
            return lambda f: f
    Client = _MockClient
    CallbackQuery = object
from bot.core.queue_manager import queue_manager
from bot.handlers.commands import is_authorized

logger = logging.getLogger(__name__)


@Client.on_callback_query()
async def callback_handler(client: Client, callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if not is_authorized(user_id):
        await callback.answer("⛔ Access denied.", show_alert=True)
        return

    if data.startswith("cancel:"):
        task_id = data.split(":", 1)[1]
        success = queue_manager.cancel_task(task_id)
        if success:
            await callback.answer("🛑 Task cancelled.", show_alert=False)
            try:
                await callback.message.edit_text(
                    f"🚫 **Task Cancelled by user.**\nTask ID: `{task_id[:8]}`"
                )
            except Exception:
                pass
        else:
            await callback.answer("Task is already finished or cannot be cancelled.", show_alert=True)
        return

    if data.startswith("cancel_batch:"):
        batch_id = data.split(":", 1)[1]
        success = queue_manager.cancel_batch(batch_id)
        if success:
            await callback.answer("🛑 Album batch cancelled.", show_alert=False)
            try:
                await callback.message.edit_text(
                    f"🚫 **Album Batch Cancelled by user.**\nBatch ID: `{batch_id[:8]}`"
                )
            except Exception:
                pass
        else:
            await callback.answer("Album batch is already finished or cannot be cancelled.", show_alert=True)
        return

    if data.startswith("zipchoice:"):
        parts = data.split(":")
        if len(parts) == 3:
            task_id = parts[1]
            choice = parts[2]
            fut = queue_manager.decision_futures.get(task_id)
            if fut and not fut.done():
                fut.set_result(choice)
                choice_labels = {
                    "images": "🖼️ Only Images (Chat me)",
                    "zip": "📦 Only ZIP File",
                    "both": "✨ Both (ZIP + Images)"
                }
                label = choice_labels.get(choice, choice)
                await callback.answer(f"Option selected: {label}")
                try:
                    await callback.message.edit_text(
                        f"✅ **Aapne select kiya:** {label}\nUploading shuru ho rahi hai..."
                    )
                except Exception:
                    pass
            else:
                await callback.answer("Option expire ho gaya ya pehle hi process ho chuka hai.", show_alert=True)
        return
