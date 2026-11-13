import os
from collections.abc import Mapping
from pathlib import Path

from ffkit._ffmpeg.args import (
    StrPath,
    ensure_distinct,
    existing_file,
    media_path,
    temporary_sibling,
)
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio._filters import audio_filters
from ffkit.audio.analysis.cover import attached_picture_index
from ffkit.audio.analysis.loudness import measure_loudness
from ffkit.audio.analysis.probe import audio_stream_required, probe
from ffkit.audio.analysis.silence import resolve_silence_trim
from ffkit.audio.defaults import MIN_LIMITER_CEILING_DB
from ffkit.audio.effects import Effects
from ffkit.audio.encoding import Encoding, Mp3Encoding
from ffkit.errors import (
    CancelledError,
    FFmpegError,
    PeakCeilingError,
)
from ffkit.runtime import FFmpegRuntime

MAX_ATTEMPTS = 5
CEILING_MARGIN_DB = 0.2


def _command_parts(
    source: Path,
    tags: Mapping[str, str],
    cover: Path | int | None,
    encoding: Encoding,
    *,
    ffmpeg: str,
) -> tuple[list[str], list[str]]:
    """Return the FFmpeg arguments before and after the audio filter option.

    ``cover`` is an image file, the stream index of the source cover, or None for no cover.
    """
    inputs = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", media_path(source)]
    if cover is None:
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
            ],
        )
    else:
        inputs.extend(
            [
                "-map",
                "0:a:0",
                "-map",
                f"0:{cover}",
                "-c:v",
                "copy",
                "-disposition:v:0",
                "attached_pic",
            ],
        )

    # Ogg and Opus keep tags on the audio stream; the first mapping wins on conflicting keys.
    outputs = [
        *encoding.codec_args(),
        "-map_metadata",
        "0:s:a:0",
        "-map_metadata",
        "0",
        "-f",
        encoding.muxer,
    ]
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
    lowered = max(MIN_LIMITER_CEILING_DB, current - (peak - ceiling) - CEILING_MARGIN_DB)
    if lowered <= MIN_LIMITER_CEILING_DB:
        raise PeakCeilingError("True peak ceiling could not be reached")
    return lowered


def _encode(command: list[str], cancelled: Cancelled | None, *, timeout: float) -> None:
    for _ in iter_output(command, pipe="stderr", timeout=timeout, cancelled=cancelled):
        pass


def _check_paths(source: Path, destination: Path, cover: Path | bool) -> None:
    existing_file(source)
    if isinstance(cover, Path):
        existing_file(cover)
    ensure_distinct(source, destination)


def render(  # noqa: PLR0913 - Render options plus the keyword-only FFmpeg runtime.
    source: StrPath,
    destination: StrPath,
    *,
    effects: Effects | None = None,
    tags: Mapping[str, str] | None = None,
    cover: StrPath | bool = True,
    encoding: Encoding = Mp3Encoding(),
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> None:
    """Apply effects to the original source and render a separate encoded file.

    Source metadata is copied and ``tags`` override it. ``cover`` keeps the source cover (``True``),
    writes no cover (``False``), or embeds an image file.
    """
    source, destination = Path(source), Path(destination)
    if not isinstance(cover, bool):
        cover = Path(cover)
    effects = effects or Effects()
    _check_paths(source, destination, cover)

    ceiling = effects.limiter_ceiling_db
    destination.parent.mkdir(parents=True, exist_ok=True)
    cover_input: Path | int | None = None
    if isinstance(cover, Path):
        cover_input = cover
    elif cover:
        cover_input = attached_picture_index(source, runtime=runtime)
    inputs, outputs = _command_parts(
        source,
        tags or {},
        cover_input,
        encoding,
        ffmpeg=runtime.ffmpeg_path,
    )
    temporary = temporary_sibling(destination, encoding.extension)

    try:
        info = (
            probe(source, runtime=runtime)
            if effects.trim_silence or effects.normalize_lufs is not None
            else None
        )
        sample_rate = None if info is None else info.sample_rate
        effects = resolve_silence_trim(effects, source, cancelled, info=info, runtime=runtime)

        effective_ceiling = ceiling
        for attempt in range(MAX_ATTEMPTS):
            attempt_effects = effects.replace(limiter_ceiling_db=effective_ceiling)
            filters = audio_filters(attempt_effects, sample_rate=sample_rate)
            command = [*inputs, *(["-af", ",".join(filters)] if filters else [])]
            with audio_stream_required(source, runtime=runtime):
                _encode(
                    [*command, *outputs, media_path(temporary)],
                    cancelled,
                    timeout=runtime.process_timeout,
                )

            if ceiling is None or effective_ceiling is None:
                break
            _check_cancelled(cancelled)
            peak = measure_loudness(temporary, cancelled=cancelled, runtime=runtime).true_peak_db
            if peak is None:
                raise FFmpegError("Could not measure encoded true peak")
            if peak <= ceiling:
                break
            effective_ceiling = _next_ceiling(effective_ceiling, ceiling, peak, attempt)

        _check_cancelled(cancelled)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
