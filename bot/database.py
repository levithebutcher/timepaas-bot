import aiosqlite
from pathlib import Path
from bot.config import DATABASE_PATH


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
