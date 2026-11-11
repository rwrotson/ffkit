import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from ffkit.core._ffmpeg import media_path
from ffkit.core._process import error_tail, stop
from ffkit.core.audio._constants import MP3_ENCODER_ARGS
from ffkit.core.audio.analysis.loudness import measure_loudness
from ffkit.core.audio.analysis.silence import trailing_trim_end
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Track
from ffkit.core.errors import CancelledError
from ffkit.core.runtime import FFmpegRuntime

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MIN_CEILING_DB = -20
CEILING_MARGIN_DB = 0.2
CANCEL_POLL_INTERVAL = 0.1
RENDERED_TAGS = frozenset({"title", "artist", "album", "date", "genre", "track"})


def _command_parts(track: Track, source: Path, *, ffmpeg: str) -> tuple[list[str], list[str]]:
    """Return the FFmpeg arguments before and after the audio filter option."""
    inputs = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", media_path(source)]
    cover = Path(track.cover_path) if track.cover_path else None
    if track.cover_removed:
        inputs.extend(["-vn", "-map", "0:a:0"])
    elif cover and cover.is_file():
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
    # Unprobed tracks hold only explicit tags; probed ones record explicit tags as overrides.
    explicit = track.tags if track.probed_source_tags is None else track.tag_overrides
    for key, value in track.tags.items():
        if key in RENDERED_TAGS or key in explicit:
            outputs.extend(["-metadata", f"{key}={value}"])
    return inputs, outputs


def _run_encoder(
    command: list[str], cancelled: Callable[[], bool] | None, *, timeout: float
) -> None:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate path arguments.
            command, stdout=subprocess.DEVNULL, stderr=errors
        )
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                if cancelled is not None and cancelled():
                    process.terminate()
                    process.wait()
                    raise CancelledError("Export cancelled")
                wait = remaining if cancelled is None else min(CANCEL_POLL_INTERVAL, remaining)
                try:
                    process.wait(timeout=wait)
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode, command, stderr=error_tail(errors)
                )
        finally:
            stop(process)


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise CancelledError("Export cancelled")


def _next_ceiling(current: float, ceiling: float, peak: float, attempt: int) -> float:
    """Lower the limiter ceiling by the measured overshoot, or fail when out of attempts."""
    if attempt == MAX_ATTEMPTS - 1:
        raise RuntimeError(f"Encoded true peak {peak:.2f} dBTP exceeds {ceiling:.2f} dBTP")
    lowered = max(MIN_CEILING_DB, current - (peak - ceiling) - CEILING_MARGIN_DB)
    if lowered <= MIN_CEILING_DB:
        raise RuntimeError("True peak ceiling could not be reached")
    return lowered


def _encode(
    track: Track, command: list[str], cancelled: Callable[[], bool] | None, *, timeout: float
) -> None:
    try:
        _run_encoder(command, cancelled, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        detail = error.stderr or "FFmpeg timed out"
        log.error("audio_render_failed track=%s error=%s", track.id, detail)
        raise


def render(  # noqa: PLR0913 - Render options plus the keyword-only FFmpeg runtime.
    track: Track,
    destination: Path,
    group_gain_db: float = 0,
    *,
    limiter_db: float | None = None,
    cancelled: Callable[[], bool] | None = None,
    runtime: FFmpegRuntime | None = None,
) -> None:
    """Apply effects to the original source and render a separate MP3 file."""
    runtime = runtime or FFmpegRuntime()
    source = Path(track.path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise ValueError("Output path must differ from source audio")
    ceiling = track.effects.effective_limiter_db(limiter_db)
    destination.parent.mkdir(parents=True, exist_ok=True)
    inputs, outputs = _command_parts(track, source, ffmpeg=runtime.ffmpeg_path)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.mp3")
    try:
        trailing_end = trailing_trim_end(track.effects, source, cancelled, runtime=runtime)
        effective_ceiling = ceiling
        for attempt in range(MAX_ATTEMPTS):
            attempt_track = track.model_copy(deep=True)
            attempt_track.effects.limiter_ceiling_db = effective_ceiling
            if trailing_end is not None:
                attempt_track.effects.trim_end = trailing_end
            filters = audio_filters(attempt_track, group_gain_db, streaming=True)
            command = [*inputs, *(["-af", ",".join(filters)] if filters else [])]
            _encode(
                track,
                [*command, *outputs, media_path(temporary)],
                cancelled,
                timeout=runtime.process_timeout,
            )
            if ceiling is None or effective_ceiling is None:
                break
            _check_cancelled(cancelled)
            _, peak = measure_loudness(temporary, runtime=runtime)
            if peak is None:
                raise RuntimeError("Could not measure encoded true peak")
            if peak <= ceiling:
                break
            effective_ceiling = _next_ceiling(effective_ceiling, ceiling, peak, attempt)
        _check_cancelled(cancelled)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
