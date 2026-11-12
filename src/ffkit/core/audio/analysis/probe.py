import json
import math
import subprocess
from pathlib import Path

from ffkit.core._ffmpeg import media_path
from ffkit.core.audio.models import AudioInfo
from ffkit.core.runtime import FFmpegRuntime


def probe(source: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> AudioInfo:
    """Read duration and tags from the first audio stream; stream tags override container tags."""
    if not source.is_file():
        raise FileNotFoundError(source)

    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffprobe_path,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            media_path(source),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=runtime.process_timeout,
    )

    report = json.loads(result.stdout)
    audio_stream = next(
        (stream for stream in report.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    if audio_stream is None:
        raise ValueError("File has no decodable audio stream")

    info = report["format"]
    duration = float(info.get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("File has no measurable audio duration")

    format_tags = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    stream_tags = {
        str(key).lower(): str(value) for key, value in audio_stream.get("tags", {}).items()
    }
    return AudioInfo(duration=duration, tags={**format_tags, **stream_tags})
