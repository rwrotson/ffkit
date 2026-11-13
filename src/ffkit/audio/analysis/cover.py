import json

from ffkit._ffmpeg.args import StrPath, existing_file, media_path
from ffkit._ffmpeg.process import run
from ffkit.errors import FFmpegProcessError
from ffkit.runtime import FFmpegRuntime


def attached_picture_index(source: StrPath, *, runtime: FFmpegRuntime) -> int | None:
    """Return the stream index of the first attached picture, or None when there is none.

    Video streams without the ``attached_pic`` disposition, such as a music video, are not covers.
    """
    command = [
        runtime.ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "stream=index:stream_disposition=attached_pic",
        "-of",
        "json",
        media_path(existing_file(source)),
    ]
    try:
        report = json.loads(run(command, timeout=runtime.process_timeout))
    except FFmpegProcessError:
        # FFprobe fails when the source cannot be read; it then has no usable cover either.
        return None

    for stream in report.get("streams", []):
        if stream.get("disposition", {}).get("attached_pic") == 1:
            return int(stream["index"])
    return None


def embedded_cover(source: StrPath, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> bytes | None:
    """Return the first attached picture of the source as JPEG bytes."""
    source = existing_file(source)
    index = attached_picture_index(source, runtime=runtime)
    if index is None:
        return None

    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(source),
        "-map",
        f"0:{index}",
        "-frames:v",
        "1",
        "-c:v",
        "mjpeg",
        "-f",
        "image2pipe",
        "pipe:1",
    ]
    return run(command, timeout=runtime.process_timeout) or None
