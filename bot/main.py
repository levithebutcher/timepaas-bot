import asyncio
import logging
import sys
import argparse

# High-speed event loop for Linux / macOS / Colab environments
if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass

from pyrogram import Client, enums
from bot.config import (
    API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, TELEGRAM_DC_ID,
    STREAMTAPE_LOGIN, STREAMTAPE_KEY, ROOT_DIR
)
from bot.core.cleaner import clean_temp_directories
from bot.core.queue_manager import queue_manager
from bot.database import init_db, set_dump_channel, get_dump_channel

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TimepassBot")

# Production Telegram DC IP Addresses
DC_ADDRESSES = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.165"
}


def patch_pyrogram_initial_dc(app: Client, target_dc: int = 5):
    """
    Telegram DC2 currently has an internal server glitch returning [500 RPC_CALL_FAIL]
    when importing bot authorization for bots hosted on DC5 / DC4.
    Patches load_session for fresh sessions to initialize directly on the bot's home DC (default DC5).
    """
    orig_load_session = app.load_session

    async def custom_load_session():
        await app.storage.open()
        session_empty = any(
            [
                await app.storage.test_mode() is None,
                await app.storage.auth_key() is None,
                await app.storage.user_id() is None,
                await app.storage.is_bot() is None,
            ]
        )
        if session_empty:
            dc_ip = DC_ADDRESSES.get(target_dc, "91.108.56.165")
            logger.info(f"Initializing fresh MTProto session directly on DC{target_dc} ({dc_ip})...")
            from pyrogram.session.auth import Auth
            await app.storage.api_id(app.api_id)
            await app.storage.dc_id(target_dc)
            await app.storage.server_address(dc_ip)
            await app.storage.port(443)
            await app.storage.date(0)
            await app.storage.test_mode(False)
            auth_key = await Auth(app, target_dc, dc_ip, 443, False).create()
            await app.storage.auth_key(auth_key)
            await app.storage.user_id(None)
            await app.storage.is_bot(None)
        else:
            await orig_load_session()

    app.load_session = custom_load_session


def create_bot_client() -> Client:
    """Instantiates and registers handlers with Pyrogram Client."""
    if not API_ID or not API_HASH:
        logger.critical("Missing API_ID or API_HASH in .env configuration!")
        sys.exit(1)

    if not SESSION_STRING and not BOT_TOKEN:
        logger.critical("Missing both SESSION_STRING and BOT_TOKEN in .env configuration!")
        sys.exit(1)

    client_kwargs = dict(
        name="timepass_bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        workers=32,
        max_concurrent_transmissions=5,
        parse_mode=enums.ParseMode.HTML,
        plugins=dict(root="bot/handlers")
    )

    if SESSION_STRING:
        logger.info("Starting bot using pre-authenticated SESSION_STRING (bypasses ImportBotAuthorization).")
        client_kwargs["session_string"] = SESSION_STRING
    else:
        root_session = ROOT_DIR / "timepass_bot_session.session"
        bot_session = ROOT_DIR / "bot" / "timepass_bot_session.session"
        if bot_session.exists() and bot_session.stat().st_size > 0 and (not root_session.exists() or root_session.stat().st_size == 0):
            client_kwargs["name"] = str(ROOT_DIR / "bot" / "timepass_bot_session")
        client_kwargs["bot_token"] = BOT_TOKEN

    app = Client(**client_kwargs)
    if not SESSION_STRING:
        patch_pyrogram_initial_dc(app, TELEGRAM_DC_ID)
    return app


async def run_app(dump_cli=None):
    """Main async application loop."""
    logger.info("Initializing database...")
    await init_db()

    if dump_cli:
        logger.info(f"Setting Dump Channel from command line argument: {dump_cli}")
        await set_dump_channel(dump_cli)

    dump_channel = await get_dump_channel()
    if dump_channel:
        logger.info(f"Dump Channel active: {dump_channel} (Option B Relay Enabled)")
    else:
        logger.info("No Dump Channel configured. Direct Local Pipeline active (Option A)")

    logger.info("Cleaning leftover temporary files...")
    clean_temp_directories()

    # Create client while event loop is active
    app = create_bot_client()

    try:
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
    except TimeoutError as te:
        if "ImportBotAuthorization" in str(te):
            logger.critical(
                "Telegram MTProto auth server returned [500 RPC_CALL_FAIL]. "
                "Telegram servers are experiencing temporary glitches on fresh bot token authorizations. "
                "To connect instantly without hitting Telegram auth servers, set SESSION_STRING in your configuration."
            )
        raise


def main():
    parser = argparse.ArgumentParser(description="Timepass Leech & Downloader Bot")
    parser.add_argument(
        "--dump", "--dump-channel", "--channel",
        dest="dump_channel",
        help="Dump Channel or Group ID/Username for Option B Relay",
        default=None
    )
    args, _ = parser.parse_known_args()

    logger.info("==========================================")
    logger.info("Starting Timepass Leech & Downloader Bot...")
    logger.info("==========================================")

    # Ensure an event loop is set for Python 3.10+ / 3.12+ / 3.13+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(run_app(dump_cli=args.dump_channel))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested. Goodbye!")
    finally:
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
