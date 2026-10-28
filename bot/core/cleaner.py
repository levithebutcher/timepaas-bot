import os
import shutil
import logging
from pathlib import Path
from bot.config import DOWNLOAD_DIR, TEMP_DIR, EXTRACT_DIR, MIN_FREE_DISK_GB

logger = logging.getLogger(__name__)


def clean_temp_directories():
    """Wipes any leftover temporary files from previous runs on bot startup."""
    for folder in [TEMP_DIR, EXTRACT_DIR]:
        if folder.exists():
            for item in folder.iterdir():
                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to delete {item}: {e}")
    logger.info("Startup temporary directory cleanup complete.")


def check_free_disk_space(required_gb: float = MIN_FREE_DISK_GB) -> bool:
    """Checks whether the system has sufficient free disk space."""
    try:
        usage = shutil.disk_usage(DOWNLOAD_DIR)
        free_gb = usage.free / (1024 ** 3)
        return free_gb >= required_gb
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        return True


def get_free_disk_gb() -> float:
    """Returns the current free disk space in Gigabytes."""
    try:
        usage = shutil.disk_usage(DOWNLOAD_DIR)
        return usage.free / (1024 ** 3)
    except Exception:
        return 0.0


def remove_path(path: Path):
    """Safely removes a file or directory tree."""
    if not path:
        return
    try:
        p = Path(path)
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to remove {path}: {e}")
