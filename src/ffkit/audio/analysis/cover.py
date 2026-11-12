import subprocess
from pathlib import Path

from ffkit._ffmpeg.args import media_path
from ffkit.runtime import FFmpegRuntime


def embedded_cover(source: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> bytes | None:
    """Return the first embedded image of the source as JPEG bytes."""
    result = subprocess.run(  # noqa: S603 - Fixed FFmpeg command with a separate path.
        [
            runtime.ffmpeg_path,
            "-v",
            "error",
            "-i",
            media_path(source),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "mjpeg",
            "-f",
            "image2pipe",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=runtime.process_timeout,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout
