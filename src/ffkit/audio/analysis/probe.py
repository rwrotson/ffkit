import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import existing_file, media_path
from ffkit._ffmpeg.process import run
from ffkit.errors import NoAudioError
from ffkit.runtime import FFmpegRuntime


class AudioInfo(BaseModel):
    """Duration and tags of the first audio stream."""

    model_config = ConfigDict(frozen=True)

    duration: float = Field(gt=0)
    tags: dict[str, str] = Field(default_factory=dict)


def probe(source: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> AudioInfo:
    """Read duration and tags from the first audio stream; stream tags override container tags."""
    command = [
        runtime.ffprobe_path,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        media_path(existing_file(source)),
    ]
    report = json.loads(run(command, timeout=runtime.process_timeout))
    audio_stream = next(
        (stream for stream in report.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    if audio_stream is None:
        raise NoAudioError("File has no decodable audio stream")

    info = report["format"]
    duration = float(info.get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise NoAudioError("File has no measurable audio duration")

    format_tags = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    stream_tags = {
        str(key).lower(): str(value) for key, value in audio_stream.get("tags", {}).items()
    }
    return AudioInfo(duration=duration, tags={**format_tags, **stream_tags})
