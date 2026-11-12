from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath
from ffkit._ffmpeg.process import Cancelled
from ffkit.audio.analysis._energy import energy
from ffkit.runtime import FFmpegRuntime

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


def estimate_tempo(
    source: StrPath,
    *,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[TempoSegment, ...]:
    """Estimate rough tempo segments with increasing start times; empty when no beat is found."""
    with energy(source, cancelled=cancelled, runtime=runtime) as hops:
        estimates = _tempo_estimates(hops)
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
