from pathlib import Path


def ffmpeg_number(value: float) -> str:
    """Format a number in fixed notation; FFmpeg rejects exponents in durations."""
    text = f"{value:.6f}".rstrip("0")
    return f"{text}0" if text.endswith(".") else text


def media_path(path: str | Path) -> str:
    """Return an absolute path so FFmpeg never reads a ``name:`` prefix as a protocol."""
    return str(Path(path).absolute())
