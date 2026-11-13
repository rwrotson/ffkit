import math

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, existing_file, ffmpeg_number, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis.probe import AudioInfo, probe
from ffkit.audio.defaults import (
    DEFAULT_SILENCE_PADDING,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TRIM_MIN_DURATION,
    MAX_SILENCE_PADDING,
    MIN_SILENCE_THRESHOLD_DB,
)
from ffkit.audio.effects import Effects, SilenceReference
from ffkit.errors import InvalidInputError, SilentAudioError
from ffkit.runtime import FFmpegRuntime

# Levels are 20 ms RMS windows made of two 10 ms blocks, so windows advance by 10 ms.
BLOCKS_PER_SECOND = 100
WINDOW_BLOCKS = 2

type Levels = npt.NDArray[np.float64]


class TrimBounds(BaseModel):
    """Audible start and end of a source; ``end`` is ``None`` when audio lasts until the end."""

    model_config = ConfigDict(frozen=True)

    start: float = Field(ge=0)
    end: float | None = Field(default=None, gt=0)


class _LevelMeter:
    """Mean-square level per window, as the loudest channel, from interleaved float32 PCM."""

    def __init__(self, sample_rate: int, channels: int) -> None:
        self.block_frames = max(1, round(sample_rate / BLOCKS_PER_SECOND))
        self.block_seconds = self.block_frames / sample_rate
        self.channels = channels
        self.frames = 0
        self._block_bytes = self.block_frames * channels * 4
        self._pending = b""
        self._windows: list[npt.NDArray[np.float64]] = []

        # Per-channel sum of squares of the last block, paired with the next block's first window.
        self._previous: npt.NDArray[np.float64] | None = None

    def feed(self, data: bytes) -> None:
        """Add PCM bytes; a partial block waits for the next call."""
        data = self._pending + data
        complete = len(data) // self._block_bytes * self._block_bytes
        self._pending = data[complete:]
        if complete:
            self._add(np.frombuffer(data[:complete], dtype="<f4"))

    def finish(self) -> Levels:
        """Return window levels; a trailing partial block is divided by the full block size."""
        frame_bytes = self.channels * 4
        complete = len(self._pending) // frame_bytes * frame_bytes
        if complete:
            samples = np.frombuffer(self._pending[:complete], dtype="<f4")
            padding = self.block_frames * self.channels - len(samples)
            self._add(np.concatenate([samples, np.zeros(padding, dtype="<f4")]))
            self.frames -= padding // self.channels
        self._pending = b""

        if not self._windows:
            if self._previous is None:
                return np.zeros(0)
            # A source shorter than one window has a single, one-block window.
            return np.asarray([self._previous.max() / self.block_frames])
        return np.concatenate(self._windows)

    def _add(self, samples: npt.NDArray[np.float32]) -> None:
        blocks = samples.astype(np.float64).reshape(-1, self.block_frames, self.channels)
        self.frames += blocks.shape[0] * self.block_frames
        sums = np.square(blocks).sum(axis=1)
        if self._previous is not None:
            sums = np.concatenate([self._previous[np.newaxis], sums])
        if len(sums) >= WINDOW_BLOCKS:
            windows = sums[:-1] + sums[1:]
            self._windows.append(windows.max(axis=1) / (WINDOW_BLOCKS * self.block_frames))
        self._previous = sums[-1]


def _audible_span(
    levels: Levels,
    *,
    threshold_db: float,
    reference: SilenceReference,
    block_seconds: float,
) -> tuple[float, float] | None:
    """Return the start of the first and the end of the last window above the threshold."""
    peak = float(levels.max()) if len(levels) else 0.0
    if peak == 0:
        return None

    base = peak if reference == "peak" else 1.0
    audible = np.flatnonzero(levels > base * 10 ** (threshold_db / 10))
    if not len(audible):
        return None
    window_blocks = WINDOW_BLOCKS if len(levels) > 1 else 1
    return (
        float(audible[0]) * block_seconds,
        float(audible[-1] + window_blocks) * block_seconds,
    )


def _edges(
    span: tuple[float, float],
    decoded: float,
    *,
    min_duration: float,
    padding: float,
) -> tuple[float, float | None]:
    """Turn an audible span into trim positions, keeping short edge silence and padding."""
    start, end = span
    start = 0.0 if start < min_duration else max(0.0, start - padding)
    trimmed_end: float | None = None
    if decoded - end >= min_duration and end + padding < decoded:
        trimmed_end = end + padding
    return start, trimmed_end


def _scan(  # noqa: PLR0913 - Range, level options, and the keyword-only FFmpeg runtime.
    source: StrPath,
    info: AudioInfo,
    *,
    start: float,
    end: float | None,
    cancelled: Cancelled | None,
    runtime: FFmpegRuntime,
) -> tuple[_LevelMeter, Levels]:
    """Decode a source range once and measure its window levels."""
    command = [runtime.ffmpeg_path, "-v", "error"]
    if start:
        command += ["-ss", ffmpeg_number(start)]
    command += ["-i", media_path(source)]
    if end is not None:
        command += ["-t", ffmpeg_number(end - start)]

    # The decoded layout is forced to the probed one so frames split into channels correctly.
    command += [
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        str(info.channels),
        "-ar",
        str(info.sample_rate),
        "-f",
        "f32le",
        "-",
    ]

    meter = _LevelMeter(info.sample_rate, info.channels)
    for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
        meter.feed(chunk)
    return meter, meter.finish()


def _silence_edges(  # noqa: PLR0913 - Scan options plus the keyword-only FFmpeg runtime.
    source: StrPath,
    info: AudioInfo,
    *,
    start: float,
    end: float | None,
    threshold_db: float,
    reference: SilenceReference,
    min_duration: float,
    padding: float,
    cancelled: Cancelled | None,
    runtime: FFmpegRuntime,
) -> tuple[float, float | None]:
    """Return trim positions relative to ``start``; raise when the range has no audible audio."""
    meter, levels = _scan(source, info, start=start, end=end, cancelled=cancelled, runtime=runtime)
    span = _audible_span(
        levels,
        threshold_db=threshold_db,
        reference=reference,
        block_seconds=meter.block_seconds,
    )
    if span is None:
        raise SilentAudioError("Track contains no audible audio")

    decoded = meter.frames / info.sample_rate
    return _edges(span, decoded, min_duration=min_duration, padding=padding)


def detect_trim_bounds(  # noqa: PLR0913 - Scan options plus the keyword-only FFmpeg runtime.
    source: StrPath,
    *,
    info: AudioInfo | None = None,
    threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    threshold_reference: SilenceReference = "full_scale",
    min_duration: float = DEFAULT_TRIM_MIN_DURATION,
    padding: float = DEFAULT_SILENCE_PADDING,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> TrimBounds:
    """Find audible bounds by 20 ms RMS windows; retain pauses inside the track.

    ``threshold_db`` is relative to full scale or, with ``threshold_reference="peak"``, to the
    loudest window. Edge silence shorter than ``min_duration`` is kept, and ``padding`` seconds of
    silence are kept at trimmed edges. The source is probed first unless ``info`` is given.
    """
    if not MIN_SILENCE_THRESHOLD_DB <= threshold_db <= 0:
        raise InvalidInputError(
            f"Silence threshold must be between {MIN_SILENCE_THRESHOLD_DB} and 0 dB",
        )
    if not 0 <= min_duration < math.inf:
        raise InvalidInputError("Minimum duration must be a finite value of at least 0")
    if not 0 <= padding <= MAX_SILENCE_PADDING:
        raise InvalidInputError(f"Padding must be between 0 and {MAX_SILENCE_PADDING} s")

    source = existing_file(source)
    info = info or probe(source, runtime=runtime)
    start, end = _silence_edges(
        source,
        info,
        start=0,
        end=None,
        threshold_db=threshold_db,
        reference=threshold_reference,
        min_duration=min_duration,
        padding=padding,
        cancelled=cancelled,
        runtime=runtime,
    )
    return TrimBounds(start=round(start, 3), end=None if end is None else round(end, 3))


def resolve_silence_trim(
    effects: Effects,
    source: StrPath,
    cancelled: Cancelled | None = None,
    *,
    info: AudioInfo | None = None,
    runtime: FFmpegRuntime,
) -> Effects:
    """Replace ``trim_silence`` with trim bounds found inside the trimmed range."""
    if not effects.trim_silence:
        return effects

    info = info or probe(source, runtime=runtime)
    start, end = _silence_edges(
        source,
        info,
        start=effects.trim_start,
        end=effects.trim_end,
        threshold_db=effects.silence_threshold_db,
        reference=effects.silence_threshold_reference,
        min_duration=effects.silence_min_duration,
        padding=effects.silence_padding,
        cancelled=cancelled,
        runtime=runtime,
    )
    return effects.replace(
        trim_silence=False,
        trim_start=round(effects.trim_start + start, 6),
        trim_end=effects.trim_end if end is None else round(effects.trim_start + end, 6),
    )
