import asyncio
import logging
import sys
from pyrogram import Client
from bot.config import API_ID, API_HASH, BOT_TOKEN, STREAMTAPE_LOGIN, STREAMTAPE_KEY
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


async def run_app():
    """Main async application loop."""
    logger.info("Initializing database...")
    await init_db()

    logger.info("Cleaning leftover temporary files...")
    clean_temp_directories()

    # Create client while event loop is active
    app = create_bot_client()

    async with app:
        logger.info("Bot started successfully on MTProto client.")
        if STREAMTAPE_LOGIN and STREAMTAPE_KEY:
            logger.info(f"Streamtape Official API: ENABLED (User: {STREAMTAPE_LOGIN[:4]}***)")
        else:
            logger.warning("Streamtape Official API: NOT DETECTED (Using fallback scraper)")

        # Start background queue workers
        await queue_manager.start_workers(app)
        logger.info("All queue workers active and waiting for tasks.")
        # Keep bot running
        await asyncio.Event().wait()


def main():
    logger.info("==========================================")
    logger.info("Starting Timepass Leech & Downloader Bot...")
    logger.info("==========================================")

    # Ensure an event loop is set for Python 3.10+ / 3.12+ / 3.13+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(run_app())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested. Goodbye!")
    finally:
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
