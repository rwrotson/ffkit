import logging
from collections.abc import Generator
from pathlib import Path

from ffkit._ffmpeg.args import ffmpeg_number, media_path
from ffkit._ffmpeg.process import iter_output
from ffkit.audio.defaults import MP3_ENCODER_ARGS
from ffkit.audio.effects import Effects
from ffkit.audio.filters import audio_filters
from ffkit.errors import InvalidInputError
from ffkit.runtime import FFmpegRuntime

log = logging.getLogger(__name__)


def _seeked_effects(effects: Effects, start: float) -> tuple[Effects, float] | None:
    source_offset = start + effects.trim_start
    trim_end = effects.trim_end
    if trim_end is not None and source_offset >= trim_end:
        return None

    # Replace both bounds at once; assigning them separately can fail interval validation.
    seeked = Effects.model_validate(
        {
            **effects.model_dump(),
            "trim_start": 0,
            "trim_end": None if trim_end is None else trim_end - source_offset,
            # Leading silence removal after a seek would drop a pause at the seek position.
            "trim_silence": effects.trim_silence and start == 0,
        }
    )

    return seeked, source_offset


def stream_mp3(  # noqa: PLR0913 - Stream options plus the keyword-only FFmpeg runtime.
    source: Path,
    effects: Effects | None = None,
    gain: float = 0,
    start: float = 0,
    limiter_db: float | None = None,
    *,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> Generator[bytes]:
    """Stream original source audio from a position after its trim start."""
    if start < 0:
        raise InvalidInputError("Stream start must not be negative")
    return _stream(
        source,
        effects or Effects(),
        gain,
        start,
        limiter_db,
        ffmpeg=runtime.ffmpeg_path,
        idle_timeout=runtime.stream_idle_timeout,
    )


def _stream(  # noqa: PLR0913 - Receives only the runtime fields it uses.
    source: Path,
    effects: Effects,
    gain: float,
    start: float,
    limiter_db: float | None,
    *,
    ffmpeg: str,
    idle_timeout: float,
) -> Generator[bytes]:
    seeked = _seeked_effects(effects, start)
    if seeked is None:
        return
    seeked_effects, source_offset = seeked

    command = [
        ffmpeg,
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

    filters = audio_filters(seeked_effects, gain, streaming=True, limiter_db=limiter_db)
    if filters:
        command += ["-af", ",".join(filters)]
    command += [*MP3_ENCODER_ARGS, "-f", "mp3", "pipe:1"]

    try:
        yield from iter_output(command, idle_timeout=idle_timeout)
    except Exception:
        log.exception("audio_stream_failed source=%s", source)
        raise
