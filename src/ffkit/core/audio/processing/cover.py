import os
import subprocess
from pathlib import Path
from uuid import uuid4

from ffkit.core._ffmpeg import media_path
from ffkit.core.audio.models import Track
from ffkit.core.runtime import FFmpegRuntime


def extract_cover(
    track: Track, destination: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()
) -> Path | None:
    """Return a custom cover or atomically extract the first embedded image as JPEG."""
    if track.cover_removed:
        return None
    if track.cover_path:
        cover = Path(track.cover_path)
        return cover if cover.is_file() else None
    source = Path(track.path)
    if source.resolve() == destination.resolve() or (
        source.exists() and destination.exists() and source.samefile(destination)
    ):
        raise ValueError("Output path must differ from source audio")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.jpg")
    try:
        result = subprocess.run(  # noqa: S603 - Fixed FFmpeg command with separate paths.
            [
                runtime.ffmpeg_path,
                "-v",
                "error",
                "-i",
                media_path(track.path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-y",
                media_path(temporary),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=runtime.process_timeout,
        )
        if result.returncode != 0 or not temporary.is_file():
            return None
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
