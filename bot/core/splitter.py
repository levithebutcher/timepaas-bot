import os
import math
import asyncio
import logging
from pathlib import Path
from bot.config import MAX_SPLIT_SIZE_BYTES

logger = logging.getLogger(__name__)

# Safe threshold under Telegram's strict 2000 MB limit (1.90 GB to account for VBR spikes)
SAFE_SPLIT_LIMIT_BYTES = min(MAX_SPLIT_SIZE_BYTES, int(1.90 * 1024 * 1024 * 1024))


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
            val = stdout.decode().strip()
            if val:
                return float(val)
    except Exception as e:
        logger.warning(f"Failed to get video duration with ffprobe for {file_path}: {e}")
    return 0.0


async def split_video_file(file_path: Path, target_part_size: int = SAFE_SPLIT_LIMIT_BYTES) -> list[Path]:
    """
    Splits video file into multiple valid streamable parts under target_part_size without re-encoding (-c copy).
    Uses keyframe-aligned segmenting, proper DTS/PTS timestamp resets, and +faststart moov atom positioning.
    Returns list of split file Paths. If splitting isn't needed, returns [file_path].
    """
    total_size = file_path.stat().st_size
    if total_size <= target_part_size:
        return [file_path]

    duration = await get_video_duration(file_path)

    # If duration could not be determined or is not a video, fallback to binary chunking
    if duration <= 0:
        logger.info(f"Duration unavailable for {file_path.name}; using binary chunking.")
        return split_binary_file(file_path, target_part_size)

    parent_dir = file_path.parent
    stem = file_path.stem
    ext = file_path.suffix or ".mp4"

    # Calculate conservative segment duration to guarantee every part stays <= target_part_size
    bytes_per_sec = total_size / duration
    safe_part_bytes = target_part_size * 0.90  # 10% safety margin for VBR peaks
    calc_segment_duration = max(10, int(safe_part_bytes / max(1.0, bytes_per_sec)))

    logger.info(
        f"Splitting {file_path.name} ({total_size / (1024**3):.2f} GB, {duration:.1f}s) "
        f"using FFmpeg keyframe segmenter (segment_time={calc_segment_duration}s)."
    )

    # 1. Primary Strategy: FFmpeg Segment Muxer (lightning fast ~2000x, keyframe safe, monotonic timestamps)
    out_pattern = parent_dir / f"{stem}.part%03d{ext}"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(file_path),
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_time", str(calc_segment_duration),
        "-reset_timestamps", "1",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(out_pattern)
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        # Collect generated parts matching the pattern
        generated = sorted(parent_dir.glob(f"{stem}.part[0-9][0-9][0-9]{ext}"))
        if generated and len(generated) > 1:
            # Verify all generated parts are non-empty and under target_part_size
            valid = True
            for part in generated:
                p_size = part.stat().st_size
                if p_size == 0 or p_size > target_part_size:
                    valid = False
                    logger.warning(f"Segment part {part.name} size {p_size} violated constraints (target={target_part_size})")
                    break

            if valid:
                logger.info(f"FFmpeg segmented {file_path.name} into {len(generated)} clean parts successfully.")
                return generated
            else:
                # Clean up invalid segments before fallback
                for part in generated:
                    part.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"FFmpeg segment muxer failed for {file_path.name}: {e}")

    # 2. Fallback Strategy: Precise Keyframe Seeking Loop with safe PTS and +faststart
    num_parts = math.ceil(total_size / safe_part_bytes)
    part_duration = duration / num_parts
    output_parts = []

    logger.info(f"Fallback: Seeking cuts for {file_path.name} into {num_parts} parts of ~{part_duration:.1f}s each.")

    for i in range(num_parts):
        start_time = i * part_duration
        part_name = f"{stem}.part{i+1:03d}{ext}"
        part_path = parent_dir / part_name

        cut_cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(file_path),
            "-t", str(part_duration),
            "-c", "copy",
            "-map", "0",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(part_path)
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cut_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if part_path.exists() and 0 < part_path.stat().st_size <= target_part_size:
                output_parts.append(part_path)
            else:
                logger.error(f"Fallback cut part {i+1} invalid for {file_path.name}")
        except Exception as e:
            logger.error(f"Fallback cut failed for part {i+1}: {e}")

    if len(output_parts) == num_parts:
        return output_parts

    # Clean any partial fallback outputs
    for p in output_parts:
        p.unlink(missing_ok=True)

    # 3. Last-resort binary chunking
    logger.warning(f"All video splitting strategies failed for {file_path.name}; falling back to binary split.")
    return split_binary_file(file_path, target_part_size)


def split_binary_file(file_path: Path, chunk_size: int = SAFE_SPLIT_LIMIT_BYTES) -> list[Path]:
    """Fallback binary file splitter for archives or non-video files exceeding 1.90 GB."""
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
