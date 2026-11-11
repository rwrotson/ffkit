import json
import math
import subprocess
from pathlib import Path

from ffkit.core.audio._ffmpeg import media_path
from ffkit.core.audio.models import Track
from ffkit.core.audio.runtime import FFmpegRuntime


def probe(track: Track, *, runtime: FFmpegRuntime | None = None) -> Track:
    """Read duration and tags from the first audio stream."""
    runtime = runtime or FFmpegRuntime()
    source = Path(track.path)
    if not source.is_file():
        track.error = "Source file is missing"
        return track
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
    track.duration = float(info.get("duration", 0))
    if not math.isfinite(track.duration) or track.duration <= 0:
        raise ValueError("File has no measurable audio duration")
    format_tags = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    stream_tags = {
        str(key).lower(): str(value) for key, value in audio_stream.get("tags", {}).items()
    }
    track.merge_probed_tags({**format_tags, **stream_tags})
    track.error = None
    return track
