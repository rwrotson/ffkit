import math
import re

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, existing_file, media_path, source_fingerprint
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis._ebur128 import (
    ABSOLUTE_GATE_LUFS,
    EBUR128_FILTERS,
    MOMENTARY_STEP,
    MOMENTARY_WINDOW,
    Report,
    finite,
    iter_lines,
)
from ffkit.audio.analysis.loudness import Loudness
from ffkit.audio.analysis.probe import AudioInfo, probe
from ffkit.audio.defaults import DEFAULT_DISPLAY_FLOOR_DB, DEFAULT_WAVEFORM_BINS
from ffkit.errors import InvalidInputError, SourceChangedError
from ffkit.runtime import FFmpegRuntime

# ebur128 upsamples to this rate to measure true peaks.
TRUE_PEAK_RATE = 192000

# Longest astats frame; a bin longer than this is measured from several frames.
MAX_FRAME_SAMPLES = 192000

_ASTATS = re.compile(rb"lavfi\.astats\.(\d+)\.(Min|Max)_level=(\S+)")


class ChannelPeaks(BaseModel):
    """Lowest and highest true-peak sample of one channel per bin, linear full scale."""

    model_config = ConfigDict(frozen=True)

    minimum: tuple[float, ...]
    maximum: tuple[float, ...]


class Waveform(BaseModel):
    """Per-bin momentary loudness and per-channel true peaks from one loudness measurement pass."""

    model_config = ConfigDict(frozen=True)

    bin_duration: float = Field(gt=0, description="Seconds covered by each bin")
    loudness: Loudness = Field(description="Integrated loudness and true peak of the source")
    momentary_lufs: tuple[float | None, ...] = Field(
        description="Power average of 400 ms momentary loudness; None at or below -70 LUFS",
    )
    channels: tuple[ChannelPeaks, ...]

    def peak_levels(self, *, floor_db: float | None = None) -> tuple[float, ...]:
        """Scale the highest absolute peak of each bin to 0..1, linearly or in dB above a floor."""
        levels = np.zeros(len(self.momentary_lufs))
        for channel in self.channels:
            levels = np.maximum(levels, -np.array(channel.minimum))
            levels = np.maximum(levels, np.array(channel.maximum))
        if floor_db is not None:
            levels = _decibel_scale(20 * np.log10(np.maximum(levels, 1e-12)), floor_db)
        return tuple(round(float(level), 3) for level in np.minimum(levels, 1))

    def loudness_levels(self, *, floor_lufs: float = DEFAULT_DISPLAY_FLOOR_DB) -> tuple[float, ...]:
        """Scale momentary loudness from ``floor_lufs``..0 LUFS to 0..1."""
        values = np.array([floor_lufs if value is None else value for value in self.momentary_lufs])
        return tuple(round(float(level), 3) for level in _decibel_scale(values, floor_lufs))


def _decibel_scale(values: npt.NDArray[np.float64], floor: float) -> npt.NDArray[np.float64]:
    if not math.isfinite(floor) or floor >= 0:
        raise InvalidInputError("Display floor must be a finite level below 0 dB")
    return np.clip((values - floor) / -floor, 0, 1)


class _Momentary:
    """Power average of momentary loudness blocks per bin."""

    def __init__(self, bins: int, bin_duration: float) -> None:
        self.bin_duration = bin_duration
        self.power = np.zeros(bins)
        self.blocks = np.zeros(bins, dtype=np.int64)
        self.received = 0

    def add(self, lufs: float | None) -> None:
        block = self.received
        self.received += 1
        # ebur128 reports momentary loudness once a full 400 ms window has been read.
        if block < round(MOMENTARY_WINDOW / MOMENTARY_STEP) - 1:
            return

        # The value printed at frame time t covers t - 0.3 s to t + 0.1 s.
        centre = (block + 1) * MOMENTARY_STEP - MOMENTARY_WINDOW / 2
        index = min(int(centre / self.bin_duration), len(self.power) - 1)
        if lufs is not None and lufs > ABSOLUTE_GATE_LUFS:
            self.power[index] += 10 ** (lufs / 10)
        self.blocks[index] += 1

    def lufs(self) -> tuple[float | None, ...]:
        filled = np.flatnonzero(self.blocks)
        if not len(filled):
            return (None,) * len(self.power)

        # A bin without its own block takes the nearest one, as bins can be shorter than 100 ms.
        indices = np.arange(len(self.power))
        right = np.minimum(np.searchsorted(filled, indices), len(filled) - 1)
        left = np.maximum(right - 1, 0)
        nearest = np.where(indices - filled[left] <= filled[right] - indices, left, right)
        sources = filled[nearest]

        mean = self.power[sources] / self.blocks[sources]
        return tuple(
            round(10 * math.log10(power), 1)
            if power > 0 and 10 * math.log10(power) > ABSOLUTE_GATE_LUFS
            else None
            for power in mean
        )


class _Peaks:
    """Per-channel minimum and maximum of astats frames, ``frames_per_bin`` frames per bin."""

    def __init__(self, bins: int, frames_per_bin: int = 1) -> None:
        self.bins = bins
        self.frames_per_bin = frames_per_bin
        self.minimum: list[npt.NDArray[np.float64]] = []
        self.maximum: list[npt.NDArray[np.float64]] = []
        self.frames: list[int] = []

    def read_line(self, line: bytes) -> bool:
        match = _ASTATS.search(line)
        if match is None:
            return False

        channel = int(match.group(1)) - 1
        while len(self.frames) <= channel:
            self.minimum.append(np.zeros(self.bins))
            self.maximum.append(np.zeros(self.bins))
            self.frames.append(0)

        value = finite(match.group(3)) or 0.0
        index = min(self.frames[channel] // self.frames_per_bin, self.bins - 1)
        if match.group(2) == b"Min":
            self.minimum[channel][index] = min(self.minimum[channel][index], value)
        else:
            self.maximum[channel][index] = max(self.maximum[channel][index], value)
            self.frames[channel] += 1
        return True

    def channels(self) -> tuple[ChannelPeaks, ...]:
        return tuple(
            ChannelPeaks(
                minimum=tuple(round(float(value), 5) for value in minimum),
                maximum=tuple(round(float(value), 5) for value in maximum),
            )
            for minimum, maximum in zip(self.minimum, self.maximum, strict=True)
        )


def waveform(
    source: StrPath,
    *,
    bins: int = DEFAULT_WAVEFORM_BINS,
    info: AudioInfo | None = None,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> Waveform:
    """Measure loudness, momentary loudness, and true-peak minima and maxima per bin in one pass.

    Loudness matches ``measure_loudness()``. Peaks are read from audio upsampled like ebur128
    true-peak metering. The source is probed for its duration unless ``info`` is given.
    """
    if bins < 1:
        raise InvalidInputError("Waveform needs at least one bin")
    path = existing_file(source)
    info = info or probe(path, runtime=runtime)
    fingerprint = source_fingerprint(path)

    rate = max(TRUE_PEAK_RATE, info.sample_rate)
    samples_per_bin = max(1, math.ceil(info.duration * rate / bins))
    frames_per_bin = math.ceil(samples_per_bin / MAX_FRAME_SAMPLES)
    frame_samples = math.ceil(samples_per_bin / frames_per_bin)
    graph = ";".join(
        [
            "[0:a:0]asplit=2[loudness][peaks]",
            f"[loudness]{','.join(EBUR128_FILTERS)}[loudness_out]",
            f"[peaks]aresample={rate},aformat=sample_fmts=fltp,"
            f"asetnsamples=n={frame_samples}:p=0,"
            "astats=metadata=1:reset=1:measure_overall=none"
            ":measure_perchannel=Min_level+Max_level,"
            "ametadata=mode=print[peaks_out]",
        ],
    )

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        media_path(path),
        "-filter_complex",
        graph,
        "-map",
        "[loudness_out]",
        "-f",
        "null",
        "-",
        "-map",
        "[peaks_out]",
        "-f",
        "null",
        "-",
    ]
    momentary = _Momentary(bins, info.duration / bins)
    report = Report(on_momentary=momentary.add)
    peaks = _Peaks(bins, frames_per_bin)
    output = iter_output(
        command,
        pipe="stderr",
        timeout=runtime.process_timeout,
        cancelled=cancelled,
    )
    for line in iter_lines(output):
        if not peaks.read_line(line):
            report.read_line(line)

    if source_fingerprint(path) != fingerprint:
        raise SourceChangedError("Source audio changed during waveform measurement")

    return Waveform(
        bin_duration=info.duration / bins,
        loudness=Loudness(
            lufs=report.lufs(),
            true_peak_db=report.true_peak_db(),
            fingerprint=fingerprint,
        ),
        momentary_lufs=momentary.lufs(),
        channels=peaks.channels(),
    )
