import os
import shutil
import zipfile
import tarfile
import logging
from pathlib import Path
from bot.config import EXTRACT_DIR

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".flv", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".rar", ".7z"}


def is_archive_file(file_path: Path) -> bool:
    """Checks whether the file is a recognized archive format."""
    suffix = file_path.suffix.lower()
    return suffix in ARCHIVE_EXTENSIONS


def is_zip_encrypted(zip_path: Path) -> bool:
    """Checks if a zip archive contains password-protected entries."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                if info.flag_bits & 0x1:
                    return True
    except Exception as e:
        logger.warning(f"Error checking zip encryption for {zip_path}: {e}")
    return False


def extract_archive(archive_path: Path, task_id: str) -> dict:
    """
    Extracts an archive into a task-specific directory and returns categorized media.
    Returns:
        {
            "success": bool,
            "is_encrypted": bool,
            "videos": list[Path],
            "images": list[Path],
            "others": list[Path],
            "extract_path": Path
        }
    """
    target_dir = EXTRACT_DIR / task_id
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = archive_path.suffix.lower()

    result = {
        "success": False,
        "is_encrypted": False,
        "videos": [],
        "images": [],
        "others": [],
        "extract_path": target_dir
    }

    try:
        if suffix == ".zip":
            if is_zip_encrypted(archive_path):
                result["is_encrypted"] = True
                return result
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(target_dir)
            result["success"] = True

        elif suffix in {".tar", ".gz", ".bz2", ".xz", ".tgz"}:
            with tarfile.open(archive_path, 'r:*') as tf:
                tf.extractall(target_dir)
            result["success"] = True

        else:
            # Try shutil unpack for other supported formats
            try:
                shutil.unpack_archive(str(archive_path), str(target_dir))
                result["success"] = True
            except Exception as e:
                logger.warning(f"shutil could not unpack {archive_path.name}: {e}")
                return result

    except Exception as e:
        logger.error(f"Failed to extract {archive_path.name}: {e}")
        return result

    # Scan and classify all extracted files recursively
    for item in target_dir.rglob("*"):
        if item.is_file():
            ext = item.suffix.lower()
            if ext in VIDEO_EXTENSIONS:
                result["videos"].append(item)
            elif ext in IMAGE_EXTENSIONS:
                result["images"].append(item)
            else:
                result["others"].append(item)

    # Sort files naturally
    result["videos"].sort(key=lambda p: p.name)
    result["images"].sort(key=lambda p: p.name)
    return result
