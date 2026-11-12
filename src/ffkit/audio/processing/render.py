import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ffkit._ffmpeg.args import existing_file, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis.loudness import measure_loudness
from ffkit.audio.analysis.silence import trailing_trim_end
from ffkit.audio.defaults import MP3_ENCODER_ARGS
from ffkit.audio.effects import Effects
from ffkit.audio.filters import audio_filters
from ffkit.errors import (
    CancelledError,
    FFmpegError,
    FFmpegProcessError,
    FFmpegTimeoutError,
    InvalidInputError,
    PeakCeilingError,
)
from ffkit.runtime import FFmpegRuntime

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MIN_CEILING_DB = -20
CEILING_MARGIN_DB = 0.2

type CoverChoice = Literal["source", "none"]


def _command_parts(
    source: Path, tags: Mapping[str, str], cover: Path | CoverChoice, *, ffmpeg: str
) -> tuple[list[str], list[str]]:
    """Return the FFmpeg arguments before and after the audio filter option."""
    inputs = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", media_path(source)]
    if cover == "none":
        inputs.extend(["-vn", "-map", "0:a:0"])
    elif isinstance(cover, Path):
        inputs.extend(
            [
                "-i",
                media_path(cover),
                "-map",
                "0:a:0",
                "-map",
                "1:v:0",
                "-c:v",
                "mjpeg",
                "-disposition:v:0",
                "attached_pic",
            ]
        )
    else:
        inputs.extend(
            ["-map", "0:a:0", "-map", "0:v:0?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        )

    outputs = [*MP3_ENCODER_ARGS, "-map_metadata", "0"]
    for key, value in tags.items():
        outputs.extend(["-metadata", f"{key}={value}"])
    return inputs, outputs


def _check_cancelled(cancelled: Cancelled | None) -> None:
    if cancelled is not None and cancelled():
        raise CancelledError("Operation cancelled")


def _next_ceiling(current: float, ceiling: float, peak: float, attempt: int) -> float:
    """Lower the limiter ceiling by the measured overshoot, or fail when out of attempts."""
    if attempt == MAX_ATTEMPTS - 1:
        raise PeakCeilingError(f"Encoded true peak {peak:.2f} dBTP exceeds {ceiling:.2f} dBTP")
    lowered = max(MIN_CEILING_DB, current - (peak - ceiling) - CEILING_MARGIN_DB)
    if lowered <= MIN_CEILING_DB:
        raise PeakCeilingError("True peak ceiling could not be reached")
    return lowered


def _encode(
    source: Path, command: list[str], cancelled: Cancelled | None, *, timeout: float
) -> None:
    try:
        for _ in iter_output(command, pipe="stderr", timeout=timeout, cancelled=cancelled):
            pass
    except (FFmpegProcessError, FFmpegTimeoutError) as error:
        log.error("audio_render_failed source=%s error=%s", source, error)
        raise


def _check_paths(source: Path, destination: Path, cover: Path | CoverChoice) -> None:
    existing_file(source)
    if isinstance(cover, Path):
        existing_file(cover)
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise InvalidInputError("Output path must differ from source audio")


def render(  # noqa: PLR0913 - Render options plus the keyword-only FFmpeg runtime.
    source: Path,
    destination: Path,
    effects: Effects | None = None,
    *,
    tags: Mapping[str, str] | None = None,
    cover: Path | CoverChoice = "source",
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> None:
    """Apply effects to the original source and render a separate MP3 file.

    Source metadata is copied and ``tags`` override it. ``cover`` keeps the source cover, embeds an
    image file, or writes no cover.
    """
    effects = effects or Effects()
    _check_paths(source, destination, cover)

    ceiling = effects.limiter_ceiling_db
    destination.parent.mkdir(parents=True, exist_ok=True)
    inputs, outputs = _command_parts(source, tags or {}, cover, ffmpeg=runtime.ffmpeg_path)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.mp3")

    try:
        trailing_end = trailing_trim_end(effects, source, cancelled, runtime=runtime)

        effective_ceiling = ceiling
        for attempt in range(MAX_ATTEMPTS):
            attempt_effects = effects.replace(
                limiter_ceiling_db=effective_ceiling,
                trim_end=effects.trim_end if trailing_end is None else trailing_end,
            )
            filters = audio_filters(attempt_effects, streaming=True)
            command = [*inputs, *(["-af", ",".join(filters)] if filters else [])]
            _encode(
                source,
                [*command, *outputs, media_path(temporary)],
                cancelled,
                timeout=runtime.process_timeout,
            )

            if ceiling is None or effective_ceiling is None:
                break
            _check_cancelled(cancelled)
            _, peak = measure_loudness(temporary, runtime=runtime)
            if peak is None:
                raise FFmpegError("Could not measure encoded true peak")
            if peak <= ceiling:
                break
            effective_ceiling = _next_ceiling(effective_ceiling, ceiling, peak, attempt)

        _check_cancelled(cancelled)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
