import logging
import os
import re
import selectors
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ffkit.core.audio._ffmpeg import ffmpeg_number, media_path
from ffkit.core.audio.analysis import PROCESS_TIMEOUT, measure_loudness, probe
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Track

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MIN_CEILING_DB = -20
MIN_TRAILING_SILENCE = 0.01
SCAN_ERROR_LIMIT = 1000
SCAN_END_TOLERANCE = 0.001
RENDERED_TAGS = frozenset({"title", "artist", "album", "date", "genre", "track"})


@dataclass
class _SilenceScan:
    last_start: float | None = None
    last_end: float | None = None
    last_event: str | None = None
    decoded_end: float | None = None

    def read_line(self, line: bytes) -> None:
        event = re.search(rb"silence_(start|end): ([-\d.]+)", line)
        if event:
            self.last_event = event.group(1).decode()
            value = float(event.group(2))
            if self.last_event == "start":
                self.last_start = value
            else:
                self.last_end = value
        if line.startswith(b"out_time_us="):
            self.decoded_end = float(line.removeprefix(b"out_time_us=")) / 1_000_000


def _consume_scan_chunk(scan: _SilenceScan, pending: bytes, chunk: bytes) -> bytes:
    pending += chunk
    while b"\n" in pending:
        line, pending = pending.split(b"\n", 1)
        scan.read_line(line)
    return pending[-8192:]


def _read_scan_stream(
    process: subprocess.Popen[bytes], command: list[str], cancelled: Callable[[], bool] | None
) -> tuple[_SilenceScan, bytes]:
    scan = _SilenceScan()
    pending = b""
    tail = b""
    if process.stderr is None:
        raise RuntimeError("FFmpeg stderr is unavailable")
    deadline = time.monotonic() + PROCESS_TIMEOUT
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            if cancelled and cancelled():
                raise RuntimeError("Export cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, PROCESS_TIMEOUT)
            for key, _ in selector.select(min(0.1, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                tail = (tail + chunk)[-SCAN_ERROR_LIMIT:]
                pending = _consume_scan_chunk(scan, pending, chunk)
    if pending:
        scan.read_line(pending)
    return scan, tail


def _scan_silence(command: list[str], cancelled: Callable[[], bool] | None) -> _SilenceScan:
    process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate arguments.
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + PROCESS_TIMEOUT
        scan, tail = _read_scan_stream(process, command, cancelled)
        if process.wait(timeout=max(0, deadline - time.monotonic())):
            raise subprocess.CalledProcessError(
                process.returncode, command, stderr=tail.decode(errors="replace")
            )
        return scan
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stderr is not None:
            process.stderr.close()


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
        ffmpeg_number(start),
        "-i",
        media_path(source),
        "-t",
        ffmpeg_number(end - start),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        "silencedetect=noise=-50dB:d=0.01",
        "-progress",
        "pipe:2",
        "-f",
        "null",
        "-",
    ]
    scan = _scan_silence(command, cancelled)
    if scan.last_start is None:
        return None
    if scan.decoded_end is None:
        raise RuntimeError("FFmpeg did not report decoded duration")
    trailing = scan.last_event == "start" or (
        scan.last_end is not None and scan.last_end >= scan.decoded_end - SCAN_END_TOLERANCE
    )
    if trailing and scan.decoded_end - scan.last_start >= MIN_TRAILING_SILENCE:
        return round(start + scan.last_start, 6)
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
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", media_path(source)]
    cover = Path(track.cover_path) if track.cover_path else None
    if track.cover_removed:
        command.extend(["-vn", "-map", "0:a:0"])
    elif cover and cover.is_file():
        command.extend(
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
        command.extend(
            ["-map", "0:a:0", "-map", "0:v:0?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        )
    filter_position = len(command)
    command.extend(["-codec:a", "libmp3lame", "-b:a", "320k", "-map_metadata", "0"])
    # Unprobed tracks hold only explicit tags; probed ones record explicit tags as overrides.
    explicit = track.tags if track.probed_source_tags is None else track.tag_overrides
    for key, value in track.tags.items():
        if key in RENDERED_TAGS or key in explicit:
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
            current.extend([*command[filter_position:], media_path(temporary)])
            if cancelled is None:
                with tempfile.TemporaryFile() as errors:
                    try:
                        result = subprocess.run(  # noqa: S603 - Fixed FFmpeg command with separate path arguments.
                            current,
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=errors,
                            timeout=PROCESS_TIMEOUT,
                        )
                    except subprocess.TimeoutExpired:
                        log.error("audio_render_failed track=%s error=FFmpeg timed out", track.id)
                        raise
                    if result.returncode:
                        errors.seek(0, os.SEEK_END)
                        errors.seek(max(0, errors.tell() - SCAN_ERROR_LIMIT))
                        detail = errors.read().decode(errors="replace")
                        log.error("audio_render_failed track=%s error=%s", track.id, detail)
                        raise subprocess.CalledProcessError(
                            result.returncode, current, stderr=detail
                        )
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
        if cancelled and cancelled():
            raise RuntimeError("Export cancelled")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
