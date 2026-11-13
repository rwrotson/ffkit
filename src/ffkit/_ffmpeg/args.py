import errno
import os
from pathlib import Path
from uuid import uuid4

from ffkit.errors import InvalidInputError, SourceNotFoundError

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


def ensure_distinct(source: Path, destination: Path) -> None:
    """Raise ``InvalidInputError`` when the destination is the existing source file."""
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise InvalidInputError("Output path must differ from the source")


def temporary_sibling(destination: Path, suffix: str) -> Path:
    """Return a unique hidden path next to the destination for an atomic replace."""
    return destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp{suffix}")
