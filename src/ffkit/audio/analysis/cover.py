from ffkit._ffmpeg.args import StrPath, existing_file, media_path
from ffkit._ffmpeg.process import run
from ffkit.errors import FFmpegProcessError
from ffkit.runtime import FFmpegRuntime


def embedded_cover(source: StrPath, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> bytes | None:
    """Return the first embedded image of the source as JPEG bytes."""
    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(existing_file(source)),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-c:v",
        "mjpeg",
        "-f",
        "image2pipe",
        "pipe:1",
    ]
    try:
        image = run(command, timeout=runtime.process_timeout)
    except FFmpegProcessError:
        # FFmpeg fails when the source has no video stream to map.
        return None
    return image or None
