"""Audio input discovery for the HTTP API."""

from pathlib import Path

EXTENSIONS = frozenset({".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".opus"})


def audio_files(paths: list[Path]) -> list[Path]:
    """Find supported audio files under files and directories."""
    files: set[Path] = set()
    for raw in paths:
        path = raw.expanduser().resolve()
        if path.is_dir():
            files.update(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in EXTENSIONS
            )
        elif path.is_file() and path.suffix.lower() in EXTENSIONS:
            files.add(path)
    return sorted(files)
