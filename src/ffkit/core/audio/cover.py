import subprocess
from pathlib import Path

from ffkit.core.audio.analysis import PROCESS_TIMEOUT
from ffkit.core.audio.models import Track


def extract_cover(track: Track, destination: Path) -> Path | None:
    """Return a custom cover or extract the first embedded image to a JPEG file."""
    if track.cover_removed:
        return None
    if track.cover_path:
        cover = Path(track.cover_path)
        return cover if cover.is_file() else None
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
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
                    str(destination),
                ],
                capture_output=True,
                check=False,
                timeout=PROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            destination.unlink(missing_ok=True)
            raise
        if result.returncode != 0:
            destination.unlink(missing_ok=True)
    return destination if destination.is_file() else None
