import os
import subprocess
from pathlib import Path
from uuid import uuid4

from ffkit.core.audio.analysis import PROCESS_TIMEOUT
from ffkit.core.audio.models import Track


def extract_cover(track: Track, destination: Path) -> Path | None:
    """Return a custom cover or atomically extract the first embedded image as JPEG."""
    if track.cover_removed:
        return None
    if track.cover_path:
        cover = Path(track.cover_path)
        return cover if cover.is_file() else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.jpg")
    try:
        result = subprocess.run(  # noqa: S603 - Fixed FFmpeg command with separate paths.
            [  # noqa: S607 - FFmpeg is resolved from PATH.
                "ffmpeg",
                "-v",
                "error",
                "-i",
                track.path,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-y",
                str(temporary),
            ],
            capture_output=True,
            check=False,
            timeout=PROCESS_TIMEOUT,
        )
        if result.returncode != 0 or not temporary.is_file():
            return None
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
