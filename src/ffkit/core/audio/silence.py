import os
import re
import selectors
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from ffkit.core.audio._ffmpeg import (
    SILENCE_THRESHOLD_DB,
    ffmpeg_number,
    media_path,
)
from ffkit.core.audio.models import Effects
from ffkit.core.errors import CancelledError

ERROR_TAIL_LIMIT = 1000
END_TOLERANCE = 0.001
MIN_TRAILING_SILENCE = 0.01
_EVENT = re.compile(rb"silence_(start|end): ([-\d.]+)")
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
            raise RuntimeError("FFmpeg did not report decoded duration")
        if self.last_end is not None and self.last_end >= self.decoded_end - END_TOLERANCE:
            return self.last_start
        return None


def _consume_scan_chunk(scan: SilenceScan, pending: bytes, chunk: bytes) -> bytes:
    pending += chunk
    while b"\n" in pending:
        line, pending = pending.split(b"\n", 1)
        scan.read_line(line)
    return pending[-8192:]


def _read_scan_stream(
    process: subprocess.Popen[bytes],
    command: list[str],
    cancelled: Callable[[], bool] | None,
    *,
    timeout: float,
) -> tuple[SilenceScan, bytes]:
    scan = SilenceScan()
    pending = b""
    tail = b""
    if process.stderr is None:
        raise RuntimeError("FFmpeg stderr is unavailable")
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            if cancelled and cancelled():
                raise CancelledError("Export cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            for key, _ in selector.select(min(0.1, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                tail = (tail + chunk)[-ERROR_TAIL_LIMIT:]
                pending = _consume_scan_chunk(scan, pending, chunk)
    if pending:
        scan.read_line(pending)
    return scan, tail


def scan_silence(
    command: list[str], cancelled: Callable[[], bool] | None, *, timeout: float
) -> SilenceScan:
    """Run an FFmpeg silencedetect command and parse its stderr with bounded memory."""
    process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate arguments.
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + timeout
        scan, tail = _read_scan_stream(process, command, cancelled, timeout=timeout)
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


def trailing_silence_end(  # noqa: PLR0913 - Receives only the FFmpeg path and timeout it uses.
    effects: Effects,
    source: Path,
    duration: float | None,
    cancelled: Callable[[], bool] | None = None,
    *,
    ffmpeg: str,
    timeout: float,
) -> float | None:
    """Return the source position where trailing silence in the trimmed range starts."""
    if duration is None:
        raise ValueError("Track duration is unavailable")
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
        f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={MIN_TRAILING_SILENCE}",
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
        raise RuntimeError("FFmpeg did not report decoded duration")
    if scan.decoded_end - trailing >= MIN_TRAILING_SILENCE:
        return round(start + trailing, 6)
    return None
