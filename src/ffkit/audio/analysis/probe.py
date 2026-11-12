import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import existing_file, media_path
from ffkit._ffmpeg.process import run
from ffkit.errors import NoAudioError
from ffkit.runtime import FFmpegRuntime


class AudioInfo(BaseModel):
    """Properties and tags of the first audio stream of a file."""

    model_config = ConfigDict(frozen=True)

    duration: float = Field(gt=0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    codec: str
    bit_rate: int | None = Field(default=None, gt=0, description="Bits per second, if known")
    has_cover: bool = Field(default=False, description="Whether an attached picture is embedded")
    tags: dict[str, str] = Field(default_factory=dict)


def _int(value: object) -> int | None:
    try:
        number = int(str(value))
    except ValueError:
        return None
    return number if number > 0 else None


def probe(source: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> AudioInfo:
    """Read the first audio stream; its tags override container tags."""
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
    streams = report.get("streams", [])
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    sample_rate = _int(audio_stream.get("sample_rate")) if audio_stream else None
    channels = _int(audio_stream.get("channels")) if audio_stream else None
    if audio_stream is None or sample_rate is None or channels is None:
        raise NoAudioError("File has no decodable audio stream")

    info = report["format"]
    duration = float(info.get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise NoAudioError("File has no measurable audio duration")

    format_tags = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    stream_tags = {
        str(key).lower(): str(value) for key, value in audio_stream.get("tags", {}).items()
    }
    return AudioInfo(
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        codec=str(audio_stream.get("codec_name", "")),
        bit_rate=_int(audio_stream.get("bit_rate")) or _int(info.get("bit_rate")),
        has_cover=any(stream.get("disposition", {}).get("attached_pic") == 1 for stream in streams),
        tags={**format_tags, **stream_tags},
    )
