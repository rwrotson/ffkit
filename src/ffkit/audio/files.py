from collections.abc import Iterable, Mapping
from pathlib import Path

from ffkit._ffmpeg.args import StrPath

EXTENSIONS = frozenset({".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".opus"})


def _is_audio(path: Path) -> bool:
    # Hidden names include macOS AppleDouble files and in-progress render outputs.
    return not path.name.startswith(".") and path.suffix.lower() in EXTENSIONS


def audio_files(paths: Iterable[StrPath]) -> list[Path]:
    """Find supported audio files under files and directories."""
    files: set[Path] = set()
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file() and _is_audio(item))
        elif path.is_file() and _is_audio(path):
            files.add(path)
    return sorted(files)


def safe_name(source: StrPath, tags: Mapping[str, str], *, index: int, width: int) -> str:
    """Build a numbered MP3 filename from artist and title tags or the source name."""
    artist = tags.get("artist", "")
    title = tags.get("title") or Path(source).stem
    name = f"{artist} - {title}" if artist else title
    name = "".join(character if character not in "/\\:\x00" else "_" for character in name).strip()

    prefix = f"{index + 1:0{width}d}. "
    suffix = ".mp3"
    # APFS limits a single UTF-8 filename to 255 bytes.
    remaining = 255 - len(prefix.encode()) - len(suffix.encode())
    name = name.encode("utf-8")[:remaining].decode("utf-8", errors="ignore").rstrip(" .")
    return f"{prefix}{name or 'Untitled'}.mp3"
