import math
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

# BS.1770 absolute gate; ebur128 reports it when no block passes the gates.
ABSOLUTE_GATE_LUFS = -70.0

# ebur128 prints linear true peaks with three decimals, which loses precision below this level.
MIN_LINEAR_PEAK = 0.1

# Longest unterminated stderr line kept while waiting for a newline.
LINE_LIMIT = 8192

# ebur128 emits one metadata frame per 100 ms; momentary loudness covers the last 400 ms.
MOMENTARY_STEP = 0.1
MOMENTARY_WINDOW = 0.4

EBUR128_FILTERS = (
    "ebur128=peak=true:dualmono=true:metadata=1:framelog=quiet",
    "ametadata=mode=print",
)

_INTEGRATED = re.compile(rb"lavfi\.r128\.I=(\S+)")
_MOMENTARY = re.compile(rb"lavfi\.r128\.M=(\S+)")
_LINEAR_PEAK = re.compile(rb"lavfi\.r128\.true_peak=(\S+)")
_SUMMARY_PEAK = re.compile(rb"^\s*Peak:\s+(\S+) dBFS")


def iter_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Split output chunks into lines; the last, possibly empty, line has no terminator."""
    pending = b""
    for chunk in chunks:
        lines = (pending + chunk).split(b"\n")

        # Bound memory when FFmpeg writes a long line without a newline.
        pending = lines.pop()[-LINE_LIMIT:]

        yield from lines
    yield pending


@dataclass
class Report:
    """Last ebur128 frame metadata and summary values printed by FFmpeg.

    ``on_momentary`` receives each 100 ms momentary loudness value in order.
    """

    on_momentary: Callable[[float | None], None] | None = None
    integrated: bytes | None = None
    linear_peak: bytes | None = None
    summary_peak: bytes | None = None

    def read_line(self, line: bytes) -> None:
        """Record a value from one stderr line."""
        if match := _MOMENTARY.search(line):
            if self.on_momentary is not None:
                self.on_momentary(finite(match.group(1)))
        elif match := _INTEGRATED.search(line):
            self.integrated = match.group(1)
        elif match := _LINEAR_PEAK.search(line):
            self.linear_peak = match.group(1)
        elif match := _SUMMARY_PEAK.match(line):
            self.summary_peak = match.group(1)

    def lufs(self) -> float | None:
        """Return integrated loudness, or ``None`` at or below the absolute gate."""
        lufs = finite(self.integrated)
        return None if lufs is None or lufs <= ABSOLUTE_GATE_LUFS else lufs

    def true_peak_db(self) -> float | None:
        """Return the true peak from frame metadata, or the summary when it is too quiet."""
        linear = finite(self.linear_peak)
        if linear is not None and linear >= MIN_LINEAR_PEAK:
            return 20 * math.log10(linear)
        return finite(self.summary_peak)


def finite(value: bytes | None) -> float | None:
    """Parse a finite float, or return ``None``."""
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None
