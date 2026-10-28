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
