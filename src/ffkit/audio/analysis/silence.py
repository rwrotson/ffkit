import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from ffkit._ffmpeg.args import ffmpeg_number, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis.probe import probe
from ffkit.audio.defaults import DEFAULT_SILENCE_THRESHOLD_DB, DEFAULT_TRIM_MIN_DURATION
from ffkit.audio.effects import Effects
from ffkit.errors import FFmpegError, NoAudioError, SilentAudioError
from ffkit.runtime import FFmpegRuntime

END_TOLERANCE = 0.001
MIN_TRAILING_SILENCE = 0.01
_EVENT = re.compile(rb"silence_(start|end): ([-\d.]+)")
TRIM_EDGE_TOLERANCE = 0.1
_DECODED = re.compile(rb"^out_time_us=(\d+)$")


@dataclass
class SilenceScan:
    """Silence events and decoded duration reported by FFmpeg silencedetect and progress."""

    first_start: float | None = None
    first_end: float | None = None
    last_start: float | None = None
    last_end: float | None = None
    last_event: str | None = None
    decoded_end: float | None = None

    @classmethod
    def from_lines(cls, lines: Iterable[bytes]) -> Self:
        """Collect events from complete FFmpeg output lines."""
        scan = cls()
        for line in lines:
            scan.read_line(line)
        return scan

    def read_line(self, line: bytes) -> None:
        """Record one FFmpeg output line."""
        event = _EVENT.search(line)
        if event:
            self.last_event = event.group(1).decode()
            value = float(event.group(2))
            if self.last_event == "start":
                self.last_start = value
                if self.first_start is None:
                    self.first_start = value
            else:
                self.last_end = value
                if self.first_end is None:
                    self.first_end = value

        decoded = _DECODED.match(line.strip())
        if decoded:
            self.decoded_end = int(decoded.group(1)) / 1_000_000

    def trailing_start(self) -> float | None:
        """Return where silence that lasts until the end of decoded audio begins."""
        if self.last_start is None:
            return None
        if self.last_event == "start":
            return self.last_start
        if self.decoded_end is None:
            raise FFmpegError("FFmpeg did not report decoded duration")
        if self.last_end is not None and self.last_end >= self.decoded_end - END_TOLERANCE:
            return self.last_start
        return None


def scan_silence(command: list[str], cancelled: Cancelled | None, *, timeout: float) -> SilenceScan:
    """Run an FFmpeg silencedetect command and parse its stderr with bounded memory."""
    scan = SilenceScan()
    pending = b""
    for chunk in iter_output(command, pipe="stderr", timeout=timeout, cancelled=cancelled):
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            scan.read_line(line)
        # Bound memory when FFmpeg writes a long line without a newline.
        pending = pending[-8192:]
    if pending:
        scan.read_line(pending)
    return scan


def trailing_silence_end(  # noqa: PLR0913 - Receives only the FFmpeg path and timeout it uses.
    effects: Effects,
    source: Path,
    duration: float | None,
    cancelled: Cancelled | None = None,
    *,
    ffmpeg: str,
    timeout: float,
) -> float | None:
    """Return the source position where trailing silence in the trimmed range starts."""
    if duration is None:
        raise NoAudioError("Track duration is unavailable")

    start = effects.trim_start
    end = min(effects.trim_end or duration, duration)
    if end <= start:
        return None

    command = [
        ffmpeg,
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
        f"silencedetect=noise={ffmpeg_number(effects.silence_threshold_db)}dB"
        f":d={MIN_TRAILING_SILENCE}",
        "-progress",
        "pipe:2",
        "-f",
        "null",
        "-",
    ]

    scan = scan_silence(command, cancelled, timeout=timeout)
    trailing = scan.trailing_start()
    if trailing is None:
        return None
    if scan.decoded_end is None:
        raise FFmpegError("FFmpeg did not report decoded duration")
    if scan.decoded_end - trailing >= MIN_TRAILING_SILENCE:
        return round(start + trailing, 6)
    return None


def detect_trim_bounds(  # noqa: PLR0913 - Scan options plus the keyword-only FFmpeg runtime.
    path: Path,
    duration: float | None = None,
    threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    min_duration: float = DEFAULT_TRIM_MIN_DURATION,
    cancelled: Cancelled | None = None,
    *,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float, float | None]:
    """Find audible bounds; retain pauses inside the track."""
    if duration is None:
        duration = probe(path, runtime=runtime).duration
    if not duration or duration <= 0:
        raise NoAudioError("Track duration is unavailable")

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        media_path(path),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        f"silencedetect=noise={ffmpeg_number(threshold_db)}dB:d={ffmpeg_number(min_duration)}",
        "-progress",
        "pipe:2",
        "-f",
        "null",
        "-",
    ]

    scan = scan_silence(command, cancelled, timeout=runtime.process_timeout)
    leading = scan.first_start is not None and scan.first_start <= TRIM_EDGE_TOLERANCE
    start = scan.first_end if leading and scan.first_end is not None else 0.0
    end = scan.trailing_start()
    if end is not None and end <= start:
        raise SilentAudioError("Track contains no audible audio")
    return round(start, 3), round(end, 3) if end is not None else None


def trailing_trim_end(
    effects: Effects,
    source: Path,
    cancelled: Cancelled | None = None,
    *,
    runtime: FFmpegRuntime,
) -> float | None:
    """Return where trailing silence starts when ``trim_silence`` is enabled."""
    if not effects.trim_silence:
        return None

    duration = probe(source, runtime=runtime).duration
    trailing_end = trailing_silence_end(
        effects,
        source,
        duration,
        cancelled,
        ffmpeg=runtime.ffmpeg_path,
        timeout=runtime.process_timeout,
    )

    if trailing_end is not None and trailing_end <= effects.trim_start + MIN_TRAILING_SILENCE:
        raise SilentAudioError("Track contains no audible audio")
    return trailing_end
