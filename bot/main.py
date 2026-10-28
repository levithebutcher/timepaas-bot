import asyncio
import logging
import sys
from pyrogram import Client
from bot.config import API_ID, API_HASH, BOT_TOKEN
from bot.core.cleaner import clean_temp_directories
from bot.core.queue_manager import queue_manager
from bot.database import init_db

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TimepassBot")


def create_bot_client() -> Client:
    """Instantiates and registers handlers with Pyrogram Client."""
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logger.critical("Missing API_ID, API_HASH, or BOT_TOKEN in .env configuration!")
        sys.exit(1)

    app = Client(
        name="timepass_bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins=dict(root="bot/handlers")
    )
    return app


async def startup():
    """Startup initialization routine."""
    logger.info("Initializing database...")
    await init_db()

    logger.info("Cleaning leftover temporary files...")
    clean_temp_directories()


def main():
    logger.info("==========================================")
    logger.info("Starting Timepass Leech & Downloader Bot...")
    logger.info("==========================================")

    # Run initial async setup
    asyncio.run(startup())

    app = create_bot_client()

    async def run_bot():
        async with app:
            logger.info("Bot started successfully on MTProto client.")
            # Start background queue workers
            await queue_manager.start_workers(app)
            logger.info("All queue workers active and waiting for tasks.")
            # Keep bot running
            await asyncio.Event().wait()

    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested. Goodbye!")


if __name__ == "__main__":
    main()
