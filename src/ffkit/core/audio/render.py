from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from ffkit.core.audio.analysis import PROCESS_TIMEOUT, measure_loudness
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Track

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MIN_CEILING_DB = -20


def render(  # noqa: C901, PLR0912, PLR0915 - Preserve Mixtable render and retry logic.
    track: Track,
    destination: Path,
    group_gain_db: float = 0,
    *,
    limiter_db: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Render a track to an MP3 file without replacing its source."""
    source = Path(track.path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise ValueError("Output path must differ from source audio")
    ceiling = (
        track.effects.limiter_ceiling_db
        if track.effects.limiter_ceiling_db is not None
        else limiter_db
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    cover = Path(track.cover_path) if track.cover_path else None
    if track.cover_removed:
        command.extend(["-vn", "-map", "0:a:0"])
    elif cover and cover.is_file():
        command.extend(
            [
                "-i",
                str(cover),
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
        command.extend(
            ["-map", "0:a:0", "-map", "0:v:0?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        )
    filter_position = len(command)
    command.extend(["-codec:a", "libmp3lame", "-b:a", "320k", "-map_metadata", "0"])
    for key, value in track.tags.items():
        if key in {"title", "artist", "album", "date", "genre", "track"}:
            command.extend(["-metadata", f"{key}={value}"])
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.mp3")
    try:
        effective_ceiling = ceiling
        for attempt in range(MAX_ATTEMPTS):
            attempt_track = track.model_copy(deep=True)
            attempt_track.effects.limiter_ceiling_db = effective_ceiling
            filters = audio_filters(attempt_track, group_gain_db)
            current = command[:filter_position]
            if filters:
                current.extend(["-af", ",".join(filters)])
            current.extend([*command[filter_position:], str(temporary)])
            if cancelled is None:
                try:
                    subprocess.run(  # noqa: S603 - Fixed FFmpeg command with separate path arguments.
                        current, check=True, capture_output=True, timeout=PROCESS_TIMEOUT
                    )
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                    stderr = getattr(error, "stderr", None)
                    detail = (
                        stderr[-1000:].decode(errors="replace")
                        if isinstance(stderr, bytes)
                        else str(error)[:1000]
                    )
                    log.error("audio_render_failed track=%s error=%s", track.id, detail)
                    raise
            else:
                with tempfile.TemporaryFile() as errors:
                    process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate path arguments.
                        current, stdout=subprocess.DEVNULL, stderr=errors
                    )
                    try:
                        deadline = time.monotonic() + PROCESS_TIMEOUT
                        while process.poll() is None:
                            if time.monotonic() >= deadline:
                                raise subprocess.TimeoutExpired(current, PROCESS_TIMEOUT)
                            if cancelled():
                                process.terminate()
                                process.wait()
                                raise RuntimeError("Export cancelled")
                            try:
                                process.wait(timeout=0.1)
                            except subprocess.TimeoutExpired:
                                continue
                        if process.returncode:
                            errors.seek(0, os.SEEK_END)
                            errors.seek(max(0, errors.tell() - 1000))
                            detail = errors.read().decode(errors="replace")
                            log.error("audio_render_failed track=%s error=%s", track.id, detail)
                            raise subprocess.CalledProcessError(
                                process.returncode, current, stderr=detail
                            )
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
            if ceiling is None:
                break
            if cancelled and cancelled():
                raise RuntimeError("Export cancelled")
            _, peak = measure_loudness(temporary)
            if peak is None:
                raise RuntimeError("Could not measure encoded true peak")
            if peak <= ceiling:
                break
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"Encoded true peak {peak:.2f} dBTP exceeds {ceiling:.2f} dBTP")
            effective_ceiling = max(
                MIN_CEILING_DB, (effective_ceiling or ceiling) - (peak - ceiling) - 0.2
            )
            if effective_ceiling <= MIN_CEILING_DB:
                raise RuntimeError("True peak ceiling could not be reached")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
