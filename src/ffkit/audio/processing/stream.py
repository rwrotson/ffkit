import logging
from collections.abc import Generator
from pathlib import Path

from ffkit._ffmpeg.args import StrPath, ffmpeg_number, media_path
from ffkit._ffmpeg.process import iter_output
from ffkit.audio._filters import audio_filters
from ffkit.audio.analysis.silence import resolve_silence_trim
from ffkit.audio.effects import Effects
from ffkit.audio.encoding import Encoding, Mp3Encoding
from ffkit.errors import InvalidInputError
from ffkit.runtime import FFmpegRuntime

log = logging.getLogger(__name__)


def _seeked_effects(effects: Effects, start: float) -> tuple[Effects, float] | None:
    source_offset = start + effects.trim_start
    trim_end = effects.trim_end
    if trim_end is not None and source_offset >= trim_end:
        return None

    seeked = effects.replace(
        trim_start=0,
        trim_end=None if trim_end is None else trim_end - source_offset,
    )

    return seeked, source_offset


def stream(
    source: StrPath,
    *,
    effects: Effects | None = None,
    start: float = 0,
    encoding: Encoding = Mp3Encoding(),
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> Generator[bytes]:
    """Stream encoded source audio from a position after its trim start.

    With ``trim_silence``, the trimmed range is scanned before the first chunk; callers that seek
    often can pass bounds from ``detect_trim_bounds()`` as trims instead.
    """
    if start < 0:
        raise InvalidInputError("Stream start must not be negative")
    return _stream(
        Path(source),
        effects or Effects(),
        start,
        encoding,
        runtime=runtime,
    )


def _stream(
    source: Path, effects: Effects, start: float, encoding: Encoding, *, runtime: FFmpegRuntime
) -> Generator[bytes]:
    effects = resolve_silence_trim(effects, source, runtime=runtime)
    seeked = _seeked_effects(effects, start)
    if seeked is None:
        return
    seeked_effects, source_offset = seeked

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        ffmpeg_number(source_offset),
        "-i",
        media_path(source),
        "-vn",
        "-map",
        "0:a:0",
    ]

    filters = audio_filters(seeked_effects)
    if filters:
        command += ["-af", ",".join(filters)]
    command += [*encoding.codec_args(), "-f", encoding.muxer, "pipe:1"]

    try:
        yield from iter_output(command, idle_timeout=runtime.stream_idle_timeout)
    except Exception:
        log.exception("audio_stream_failed source=%s", source)
        raise
