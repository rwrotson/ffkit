import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.runtime import FFmpegRuntime

type FloatArray = NDArray[np.float64]

SAMPLE_RATE = 22050
FRAME = 1024
HOP = 128
ONSET_RATE = SAMPLE_RATE / HOP
LOWPASS_TAPS = 15
LOWPASS_CUTOFF = 7.0
WINDOW = 2048
WINDOW_HOP = 128
MIN_WINDOW = 4 * ONSET_RATE
MIN_BPM = 50.0
MAX_BPM = 210.0
OCTAVE_MIN_BPM = 30.0
OCTAVE_MAX_BPM = 300.0
PRIOR_BPM = 120.0
PRIOR_OCTAVES = 1.0
ACF_EXPONENT = 0.5
CANDIDATES = 10
MIN_PERIODICITY = 0.1
HISTOGRAM_WIDTH = 1.0
AGREEMENT = 0.03
OCTAVE_TOLERANCE = 0.04
SMOOTHING = 5
TEMPO_MIN_CHANGE = 6
TEMPO_MIN_HOLD = 10
TEMPO_MIN_CONFIDENCE = 0.1

# Lag-0 autocorrelation at or below this means a window has no variation to analyse.
MIN_ACF_ENERGY = 1e-9


class TempoSegment(BaseModel):
    """A timed BPM estimate."""

    model_config = ConfigDict(frozen=True)

    start: float = Field(default=0, ge=0)
    bpm: float = Field(gt=0, le=400)
    confidence: float | None = Field(default=None, ge=0, le=1)


def estimate_tempo(
    source: StrPath,
    *,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[TempoSegment, ...]:
    """Estimate tempo segments with increasing start times; empty when no beat is found.

    Uses spectral flux, generalized autocorrelation, and pulse-train scoring after Percival and
    Tzanetakis (2014), with a log-normal tempo prior for the octave decision.
    """
    onsets = _onset_strength(source, cancelled=cancelled, runtime=runtime)
    windows = _window_tempi(onsets)
    if not windows:
        return ()
    return _segments(windows, _global_tempo(windows))


def _onset_strength(
    source: StrPath,
    *,
    cancelled: Cancelled | None,
    runtime: FFmpegRuntime,
) -> FloatArray:
    """Return the low-pass filtered log-magnitude spectral flux at ``ONSET_RATE``."""
    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "-",
    ]
    window = np.hanning(FRAME)
    pending = b""
    samples = np.zeros(0)
    previous: FloatArray | None = None
    flux: list[FloatArray] = []

    for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
        data = pending + chunk
        usable = len(data) // 4 * 4
        pending = data[usable:]
        samples = np.concatenate((samples, np.frombuffer(data[:usable], dtype="<f4")))
        if len(samples) < FRAME:
            continue

        count = (len(samples) - FRAME) // HOP + 1
        frames = sliding_window_view(samples, FRAME)[::HOP][:count]
        spectrum = np.log1p(1000 * np.abs(np.fft.rfft(frames * window, axis=1)))
        if previous is None:
            previous = spectrum[0]
        steps = np.diff(spectrum, axis=0, prepend=previous[np.newaxis])
        flux.append(np.maximum(steps, 0).sum(axis=1))
        previous = spectrum[-1]
        samples = samples[count * HOP :]

    if not flux:
        return np.zeros(0)
    return np.convolve(np.concatenate(flux), _lowpass(), mode="same")


def _lowpass() -> FloatArray:
    cutoff = LOWPASS_CUTOFF / ONSET_RATE
    taps = np.arange(LOWPASS_TAPS) - (LOWPASS_TAPS - 1) / 2
    kernel: FloatArray = 2 * cutoff * np.sinc(2 * cutoff * taps) * np.hamming(LOWPASS_TAPS)
    return kernel / kernel.sum()


def _window_tempi(onsets: FloatArray) -> list[tuple[float, float, FloatArray]]:
    """Return the center time, tempo, and normalized autocorrelation of each periodic window."""
    size = min(WINDOW, len(onsets))
    if size < MIN_WINDOW:
        return []

    windows: list[tuple[float, float, FloatArray]] = []
    for start in range(0, len(onsets) - size + 1, WINDOW_HOP):
        section = onsets[start : start + size]
        result = _window_tempo(section)
        if result is not None:
            bpm, acf = result
            windows.append(((start + size / 2) / ONSET_RATE, bpm, acf))
    return windows


def _window_tempo(section: FloatArray) -> tuple[float, FloatArray] | None:
    """Return one window's tempo and normalized autocorrelation, or None without periodicity."""
    centered = section - section.mean()
    size = len(centered)
    acf = np.fft.irfft(np.abs(np.fft.rfft(centered, 2 * size)) ** ACF_EXPONENT)[:size]
    if acf[0] <= MIN_ACF_ENERGY:
        return None
    acf /= acf[0]

    lags = np.arange(size)
    enhanced = acf.copy()
    for factor in (2, 4):
        harmonic = lags * factor
        valid = harmonic < size
        enhanced[valid] += acf[harmonic[valid]]

    low = max(2, math.ceil(_lag(MAX_BPM)))
    high = min(math.floor(_lag(MIN_BPM)), (size - 1) // 7)
    if high <= low + 1:
        return None
    region = enhanced[low - 1 : high + 2]
    is_peak = (region[1:-1] > region[:-2]) & (region[1:-1] >= region[2:])
    peaks = np.flatnonzero(is_peak) + low
    if not len(peaks) or acf[peaks].max() < MIN_PERIODICITY:
        return None

    candidates = peaks[np.argsort(enhanced[peaks])[::-1][:CANDIDATES]]
    periods = np.array([_refine(enhanced, int(lag)) for lag in candidates])
    best = periods[np.argmax(_pulse_scores(section, periods))]
    return _bpm(best), acf


def _refine(values: FloatArray, lag: int) -> float:
    """Refine a peak lag with parabolic interpolation."""
    left, center, right = values[lag - 1], values[lag], values[lag + 1]
    curvature = left - 2 * center + right
    if curvature >= 0:
        return float(lag)
    return lag + 0.5 * float(left - right) / float(curvature)


def _pulse_scores(section: FloatArray, periods: FloatArray) -> FloatArray:
    """Score candidate periods by cross-correlation with weighted pulse trains over all phases."""
    beats = np.arange(4)
    maxima = np.zeros(len(periods))
    variances = np.zeros(len(periods))
    for index, period in enumerate(periods):
        offsets = np.concatenate((beats * period, beats * period * 2, beats * period * 1.5))
        weights = np.repeat([1.0, 0.5, 0.5], len(beats))
        phases = np.arange(math.ceil(period))
        positions = np.rint(phases[:, np.newaxis] + offsets).astype(int)
        scores = section[np.minimum(positions, len(section) - 1)] @ weights
        maxima[index] = scores.max()
        variances[index] = scores.var()

    total: FloatArray = maxima / max(maxima.sum(), 1e-12) + variances / max(variances.sum(), 1e-12)
    return total


def _global_tempo(windows: list[tuple[float, float, FloatArray]]) -> float:
    """Pick the histogram peak of window tempi in the octave chosen by ``_octave``."""
    tempi = np.array([bpm for _, bpm, _ in windows])
    grid = np.arange(MIN_BPM, MAX_BPM + 0.05, 0.1)
    histogram = np.exp(-0.5 * ((grid[:, np.newaxis] - tempi) / HISTOGRAM_WIDTH) ** 2).sum(axis=1)
    peak = float(grid[np.argmax(histogram)])
    near = tempi[np.abs(tempi - peak) <= HISTOGRAM_WIDTH * 2]
    return _octave(windows, float(np.median(near)) if len(near) else peak)


def _octave(windows: list[tuple[float, float, FloatArray]], tempo: float) -> float:
    """Choose among half, single, and double ``tempo`` by autocorrelation support and prior."""
    candidates = [
        tempo * factor
        for factor in (0.5, 1.0, 2.0)
        if OCTAVE_MIN_BPM <= tempo * factor <= OCTAVE_MAX_BPM
    ]
    support = [_support(windows, candidate) for candidate in candidates]
    scores = [
        value * math.exp(-0.5 * (math.log2(candidate / PRIOR_BPM) / PRIOR_OCTAVES) ** 2)
        for candidate, value in zip(candidates, support, strict=True)
    ]
    return candidates[scores.index(max(scores))]


def _support(windows: list[tuple[float, float, FloatArray]], bpm: float) -> float:
    """Return the mean autocorrelation of the windows at the period of ``bpm``."""
    lag = _lag(bpm)
    values = [float(np.interp(lag, np.arange(len(acf)), acf, right=0.0)) for _, _, acf in windows]
    return max(0.0, sum(values) / len(values))


def _segments(
    windows: list[tuple[float, float, FloatArray]],
    tempo: float,
) -> tuple[TempoSegment, ...]:
    """Split folded window tempi into segments at sustained tempo changes."""
    times = [time for time, _, _ in windows]
    tempi = [_fold(bpm, tempo) for _, bpm, _ in windows]
    half = SMOOTHING // 2
    smoothed = [float(np.median(tempi[max(0, i - half) : i + half + 1])) for i in range(len(tempi))]

    bounds = [0]
    for index in range(1, len(smoothed)):
        reference = float(np.median(tempi[bounds[-1] : index]))
        hold = smoothed[index : index + TEMPO_MIN_HOLD]
        if (
            abs(smoothed[index] - reference) >= TEMPO_MIN_CHANGE
            and len(hold) == TEMPO_MIN_HOLD
            and max(hold) - min(hold) < TEMPO_MIN_CHANGE
        ):
            bounds.append(index)

    segments: list[TempoSegment] = []
    for number, first in enumerate(bounds):
        last = bounds[number + 1] if number + 1 < len(bounds) else len(tempi)
        part = np.array(tempi[first:last])
        local = tempo if len(bounds) == 1 else float(np.median(part))
        octave = _octave(windows[first:last], local) / local
        part *= octave
        bpm = round(local * octave)
        confidence = float(np.mean(np.abs(part - bpm) <= bpm * AGREEMENT))
        start = 0.0 if number == 0 else round(times[first], 1)
        segments.append(TempoSegment(start=start, bpm=bpm, confidence=round(confidence, 2)))

    if max(segment.confidence or 0 for segment in segments) < TEMPO_MIN_CONFIDENCE:
        return ()
    return tuple(segments)


def _fold(bpm: float, tempo: float) -> float:
    """Move ``bpm`` by an octave when it is about half or twice ``tempo``."""
    for factor in (2.0, 0.5):
        if abs(bpm * factor - tempo) <= tempo * OCTAVE_TOLERANCE:
            return bpm * factor
    return bpm


def _lag(bpm: float) -> float:
    return 60 * ONSET_RATE / bpm


def _bpm(lag: float) -> float:
    return 60 * ONSET_RATE / lag
