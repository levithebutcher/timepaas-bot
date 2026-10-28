import math
import asyncio
import logging
from pathlib import Path
from bot.config import MAX_SPLIT_SIZE_BYTES

logger = logging.getLogger(__name__)


async def get_video_duration(file_path: Path) -> float:
    """Uses ffprobe to obtain total video duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return float(stdout.decode().strip())
    except Exception as e:
        logger.warning(f"Failed to get video duration with ffprobe for {file_path}: {e}")
    return 0.0


async def split_video_file(file_path: Path, target_part_size: int = MAX_SPLIT_SIZE_BYTES) -> list[Path]:
    """
    Splits video file into multiple parts under target_part_size without re-encoding (-c copy).
    Returns list of split file Paths. If splitting isn't needed, returns [file_path].
    """
    total_size = file_path.stat().st_size
    if total_size <= target_part_size:
        return [file_path]

    num_parts = math.ceil(total_size / target_part_size)
    duration = await get_video_duration(file_path)

    # If duration could not be determined or is not a video, fallback to binary chunking
    if duration <= 0:
        return split_binary_file(file_path, target_part_size)

    part_duration = duration / num_parts
    output_parts = []
    parent_dir = file_path.parent
    stem = file_path.stem
    ext = file_path.suffix or ".mp4"

    logger.info(f"Splitting {file_path.name} ({total_size} bytes) into {num_parts} parts using ffmpeg.")

    for i in range(num_parts):
        start_time = i * part_duration
        part_name = f"{stem}.part{i+1:03d}{ext}"
        part_path = parent_dir / part_name

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(file_path),
            "-t", str(part_duration),
            "-c", "copy",
            "-map", "0",
            str(part_path)
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        if part_path.exists() and part_path.stat().st_size > 0:
            output_parts.append(part_path)
        else:
            logger.error(f"Failed to create video part {i+1} for {file_path.name}")

    if len(output_parts) == num_parts:
        return output_parts

    # Fallback to binary chunking if ffmpeg segment failed
    return split_binary_file(file_path, target_part_size)


def split_binary_file(file_path: Path, chunk_size: int = MAX_SPLIT_SIZE_BYTES) -> list[Path]:
    """Fallback binary file splitter for archives or non-video files exceeding 1.95 GB."""
    parts = []
    stem = file_path.stem
    ext = file_path.suffix
    parent = file_path.parent
    part_idx = 1

    with open(file_path, "rb") as src:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            part_path = parent / f"{stem}.part{part_idx:03d}{ext}"
            with open(part_path, "wb") as dst:
                dst.write(chunk)
            parts.append(part_path)
            part_idx += 1

    return parts
