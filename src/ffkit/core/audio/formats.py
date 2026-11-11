from pathlib import Path

EXTENSIONS = frozenset({".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".opus"})


def _is_audio(path: Path) -> bool:
    # Hidden names include macOS AppleDouble files and in-progress render outputs.
    return not path.name.startswith(".") and path.suffix.lower() in EXTENSIONS


def audio_files(paths: list[Path]) -> list[Path]:
    """Find supported audio files under files and directories."""
    files: set[Path] = set()
    for raw in paths:
        path = raw.expanduser().resolve()
        if path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file() and _is_audio(item))
        elif path.is_file() and _is_audio(path):
            files.add(path)
    return sorted(files)
