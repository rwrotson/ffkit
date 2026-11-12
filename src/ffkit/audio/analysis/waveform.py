import array
import math
import mmap
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis.probe import AudioInfo, probe
from ffkit.runtime import FFmpegRuntime

WAVEFORM_BINS = 400
PEAK_OVERSAMPLING = 4
TEMPO_MAX_CHANGE = 8
TEMPO_MIN_CHANGE = 12
TEMPO_WINDOW = 300
TEMPO_MIN_WINDOW = 160
TEMPO_MIN_CONFIDENCE = 0.1


class TempoSegment(BaseModel):
    """A timed BPM estimate."""

    model_config = ConfigDict(frozen=True)

    start: float = Field(default=0, ge=0)
    bpm: float = Field(gt=0, le=400)
    confidence: float | None = Field(default=None, ge=0, le=1)


def peak_envelope(
    source: StrPath,
    *,
    info: AudioInfo | None = None,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float, ...]:
    """Measure a full-scale peak envelope from four-times oversampled audio.

    The source is probed for its duration, sample rate, and channels unless ``info`` is given.
    """
    info = info or probe(source, runtime=runtime)
    channels = info.channels
    rate = info.sample_rate * PEAK_OVERSAMPLING
    frames_per_bin = max(1, math.ceil(info.duration * rate / WAVEFORM_BINS))
    peaks = [0.0] * WAVEFORM_BINS

    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ar",
        str(rate),
        "-ac",
        str(channels),
        "-f",
        "f32le",
        "-",
    ]

    frame_bytes = channels * 4
    frame_index = 0
    pending = b""
    for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
        pending += chunk
        while len(pending) >= frame_bytes:
            boundary = frames_per_bin - frame_index % frames_per_bin
            count = min(boundary, len(pending) // frame_bytes)
            size = count * frame_bytes
            values = array.array("f")
            values.frombytes(pending[:size])
            pending = pending[size:]
            bin_index = min(WAVEFORM_BINS - 1, frame_index // frames_per_bin)
            # Builtin max/min over the array run in C; per-sample abs() in Python is slow.
            loudest, quietest = max(values), min(values)
            peaks[bin_index] = max(peaks[bin_index], loudest, -quietest)
            frame_index += count

    return tuple(round(value, 5) for value in peaks)


ENERGY_SAMPLE_RATE = 2000
ENERGY_HOP = 200


def _hop_energy(data: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(data)
    return sum(abs(sample) for sample in samples) / (ENERGY_HOP * 32768)


@contextmanager
def _energy(
    source: StrPath, *, cancelled: Cancelled | None, runtime: FFmpegRuntime
) -> Iterator[memoryview[float]]:
    """Yield mean absolute amplitude per 0.1 s hop, kept in a temporary file for long sources."""
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
        str(ENERGY_SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    hop_bytes = ENERGY_HOP * 2

    with tempfile.TemporaryFile() as energy_file:
        pending = b""
        for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
            data = pending + chunk
            complete = len(data) // hop_bytes * hop_bytes
            values = [
                _hop_energy(data[pos : pos + hop_bytes]) for pos in range(0, complete, hop_bytes)
            ]
            energy_file.write(array.array("d", values).tobytes())
            pending = data[complete:]
        if pending:
            energy_file.write(array.array("d", [_hop_energy(pending)]).tobytes())

        energy_file.flush()
        if not energy_file.tell():
            yield memoryview(array.array("d"))
            return
        with mmap.mmap(energy_file.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            energy = memoryview(mapped).cast("d")
            try:
                yield energy
            finally:
                energy.release()


def waveform(
    source: StrPath,
    *,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float, ...]:
    """Build a compact loudness envelope of up to 400 values scaled to the loudest point."""
    with _energy(source, cancelled=cancelled, runtime=runtime) as energy:
        if not len(energy):
            return ()
        loudest = max(energy) or 1
        width = max(1, math.ceil(len(energy) / WAVEFORM_BINS))
        return tuple(
            round(max(energy[pos : pos + width]) / loudest, 3)
            for pos in range(0, len(energy), width)
        )


def estimate_tempo(
    source: StrPath,
    *,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[TempoSegment, ...]:
    """Estimate rough tempo segments with increasing start times; empty when no beat is found."""
    with _energy(source, cancelled=cancelled, runtime=runtime) as energy:
        estimates = _tempo_estimates(energy)
    if not estimates:
        return ()

    smoothed = [
        round(median(item[1] for item in estimates[max(0, i - 1) : i + 2]))
        for i in range(len(estimates))
    ]
    segments = [TempoSegment(start=0, bpm=smoothed[0], confidence=estimates[0][2])]
    for index in range(1, len(estimates) - 1):
        bpm = smoothed[index]
        previous = segments[-1].bpm
        if (
            abs(bpm * 2 - previous) <= TEMPO_MAX_CHANGE
            or abs(bpm / 2 - previous) <= TEMPO_MAX_CHANGE
        ):
            continue
        if (
            abs(bpm - previous) >= TEMPO_MIN_CHANGE
            and abs(smoothed[index + 1] - bpm) <= TEMPO_MAX_CHANGE
        ):
            segments.append(
                TempoSegment(start=estimates[index][0], bpm=bpm, confidence=estimates[index][2])
            )
    return tuple(segments)


def _tempo_estimates(energy: memoryview[float]) -> list[tuple[float, float, float]]:
    """Measure tempo from one short onset window at a time."""
    estimates: list[tuple[float, float, float]] = []
    section: list[float] = []

    for pos in range(1, len(energy)):
        section.append(max(0.0, energy[pos] - energy[pos - 1]))
        if len(section) < TEMPO_WINDOW and pos != len(energy) - 1:
            continue
        if len(section) >= TEMPO_MIN_WINDOW:
            candidates = [
                (sum(section[i] * section[i - lag] for i in range(lag, len(section))), lag)
                for lag in range(3, 16)
            ]
            score, lag = max(candidates)
            energy_total = sum(value * value for value in section)
            confidence = min(1.0, score / energy_total) if energy_total else 0.0
            if confidence >= TEMPO_MIN_CONFIDENCE:
                start = pos - len(section)
                estimates.append((start / 10, round(600 / lag), round(confidence, 2)))
        section = []

    return estimates
