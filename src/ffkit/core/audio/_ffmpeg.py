import os
from pathlib import Path

# Executables are resolved from PATH.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
PROCESS_TIMEOUT = 900
SILENCE_THRESHOLD_DB = -50
DEFAULT_TRIM_MIN_DURATION = 0.1
DEFAULT_TARGET_LUFS = -14
DEFAULT_PEAK_CEILING_DB = -1
LOUDNORM_TRUE_PEAK_DB = -1
LOUDNORM_RANGE = 11
MP3_ENCODER_ARGS = ("-codec:a", "libmp3lame", "-b:a", "320k")


def ffmpeg_number(value: float) -> str:
    """Format a number in fixed notation; FFmpeg rejects exponents in durations."""
    text = f"{value:.6f}".rstrip("0")
    return f"{text}0" if text.endswith(".") else text


def media_path(path: str | Path) -> str:
    """Return an absolute path so FFmpeg never reads a ``name:`` prefix as a protocol."""
    return str(Path(path).absolute())


def source_fingerprint(path: Path) -> tuple[int, int, int]:
    """Return size, mtime, and ctime that identify the current file contents."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
