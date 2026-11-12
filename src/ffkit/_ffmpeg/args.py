import errno
import os
from pathlib import Path

from ffkit.errors import SourceNotFoundError

type StrPath = str | os.PathLike[str]


def ffmpeg_number(value: float) -> str:
    """Format a number in fixed notation; FFmpeg rejects exponents in durations."""
    text = f"{value:.6f}".rstrip("0")
    return f"{text}0" if text.endswith(".") else text


def media_path(path: StrPath) -> str:
    """Return an absolute path so FFmpeg never reads a ``name:`` prefix as a protocol."""
    return str(Path(path).absolute())


def source_fingerprint(path: StrPath) -> tuple[int, int, int]:
    """Return size, mtime, and ctime that identify the current file contents."""
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def existing_file(path: StrPath) -> Path:
    """Return the path, or raise ``SourceNotFoundError`` when it is not a file."""
    path = Path(path)
    if not path.is_file():
        raise SourceNotFoundError(errno.ENOENT, "Input file not found", str(path))
    return path
