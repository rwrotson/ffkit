import logging
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from ffkit.core.audio.analysis import PROCESS_TIMEOUT, TRIM_EDGE_TOLERANCE, measure_loudness, probe
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Track

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MIN_CEILING_DB = -20
MIN_TRAILING_SILENCE = 0.01


def _scan_silence(command: list[str], cancelled: Callable[[], bool] | None) -> str:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate arguments.
            command, stdout=subprocess.DEVNULL, stderr=errors
        )
        try:
            deadline = time.monotonic() + PROCESS_TIMEOUT
            while process.poll() is None:
                if cancelled and cancelled():
                    raise RuntimeError("Export cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, PROCESS_TIMEOUT)
                try:
                    process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    continue
            errors.seek(0, os.SEEK_END)
            errors.seek(max(0, errors.tell() - 8192))
            tail = errors.read().decode(errors="replace")
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command, stderr=tail)
            return tail
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def _trailing_silence_end(
    track: Track, source: Path, cancelled: Callable[[], bool] | None
) -> float | None:
    duration = probe(Track(path=str(source))).duration
    if duration is None:
        raise ValueError("Track duration is unavailable")
    start = track.effects.trim_start
    end = min(track.effects.trim_end or duration, duration)
    if end <= start:
        return None
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-ss",
        str(start),
        "-i",
        str(source),
        "-t",
        str(end - start),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        "silencedetect=noise=-50dB:d=0",
        "-f",
        "null",
        "-",
    ]
    tail = _scan_silence(command, cancelled)
    events = list(re.finditer(r"silence_(start|end): ([-\d.]+)", tail))
    starts = [event for event in events if event.group(1) == "start"]
    if not starts:
        return None
    last_start = starts[-1]
    last_end = next((event for event in reversed(events) if event.group(1) == "end"), None)
    trailing = (
        last_end is None
        or last_start.start() > last_end.start()
        or (float(last_end.group(2)) >= end - start - TRIM_EDGE_TOLERANCE)
    )
    if trailing and end - start - float(last_start.group(2)) >= MIN_TRAILING_SILENCE:
        return round(start + float(last_start.group(2)), 6)
    return None


def render(  # noqa: C901, PLR0912, PLR0915 - Preserve Mixtable render and retry logic.
    track: Track,
    destination: Path,
    group_gain_db: float = 0,
    *,
    limiter_db: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Apply effects to the original source and render a separate MP3 file."""
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
        trailing_end = (
            _trailing_silence_end(track, source, cancelled) if track.effects.trim_silence else None
        )
        if (
            trailing_end is not None
            and trailing_end <= track.effects.trim_start + MIN_TRAILING_SILENCE
        ):
            raise ValueError("Track contains no audible audio")
        effective_ceiling = ceiling
        for attempt in range(MAX_ATTEMPTS):
            attempt_track = track.model_copy(deep=True)
            attempt_track.effects.limiter_ceiling_db = effective_ceiling
            if trailing_end is not None:
                attempt_track.effects.trim_end = trailing_end
            filters = audio_filters(attempt_track, group_gain_db, streaming=True)
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
