import aiosqlite
from pathlib import Path
from bot.config import DATABASE_PATH, DUMP_CHANNEL_ID


async def init_db():
    """Initialize database tables for user settings and task tracking."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                custom_thumb TEXT,
                custom_caption TEXT,
                auto_extract_zip INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                task_id TEXT PRIMARY KEY,
                user_id INTEGER,
                url TEXT,
                status TEXT,
                file_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        await db.commit()


async def get_user_settings(user_id: int):
    """Retrieve settings for a user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT custom_thumb, custom_caption, auto_extract_zip FROM user_settings WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "custom_thumb": row[0],
                    "custom_caption": row[1],
                    "auto_extract_zip": bool(row[2])
                }
            return {
                "custom_thumb": None,
                "custom_caption": None,
                "auto_extract_zip": True
            }


async def set_user_thumb(user_id: int, thumb_path: str):
    """Update or insert user custom thumbnail path."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO user_settings (user_id, custom_thumb)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET custom_thumb = excluded.custom_thumb
        """, (user_id, thumb_path))
        await db.commit()


async def clear_user_thumb(user_id: int):
    """Clear custom thumbnail for user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE user_settings SET custom_thumb = NULL WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


async def set_user_caption(user_id: int, caption_template: str):
    """Set custom caption template for user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO user_settings (user_id, custom_caption)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET custom_caption = excluded.custom_caption
        """, (user_id, caption_template))
        await db.commit()


async def get_dump_channel() -> int | str | None:
    """Retrieves dump channel ID from database, falling back to DUMP_CHANNEL_ID config."""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute("SELECT value FROM bot_settings WHERE key = 'dump_channel_id'") as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    val = str(row[0]).strip()
                    try:
                        return int(val)
                    except ValueError:
                        return val
    except Exception:
        pass
    return DUMP_CHANNEL_ID


async def set_dump_channel(channel_id: int | str | None):
    """Updates or clears the dump channel ID in the database."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if channel_id is None:
            await db.execute("DELETE FROM bot_settings WHERE key = 'dump_channel_id'")
        else:
            await db.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('dump_channel_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (str(channel_id).strip(),))
        await db.commit()
