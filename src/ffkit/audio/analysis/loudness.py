import json
import math
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ffkit._ffmpeg.args import media_path, source_fingerprint
from ffkit._ffmpeg.process import run
from ffkit.audio.analysis.silence import trailing_trim_end
from ffkit.audio.defaults import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    LOUDNORM_RANGE,
    LOUDNORM_TRUE_PEAK_DB,
)
from ffkit.audio.effects import Effects
from ffkit.audio.filters import audio_filters
from ffkit.errors import SilentAudioError, SourceChangedError
from ffkit.runtime import FFmpegRuntime


class SourceLoudness(BaseModel):
    """Source loudness, true peak, and the fingerprint of the measured file."""

    model_config = ConfigDict(frozen=True)

    lufs: float | None
    true_peak_db: float | None
    fingerprint: tuple[int, int, int]


def measure_loudness(
    path: Path,
    *,
    filters: Sequence[str] = (),
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float | None, float | None]:
    """Measure integrated LUFS and true peak after applying filters before loudnorm."""
    chain = [
        *filters,
        f"loudnorm=I={DEFAULT_TARGET_LUFS}:TP={LOUDNORM_TRUE_PEAK_DB}"
        f":LRA={LOUDNORM_RANGE}:print_format=json",
    ]

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-i",
        media_path(path),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        ",".join(chain),
        "-f",
        "null",
        "-",
    ]
    stderr = run(command, pipe="stderr", timeout=runtime.process_timeout).decode(errors="replace")

    marker = stderr.rfind('"input_i"')
    if marker < 0:
        return None, None
    left = stderr.rfind("{", 0, marker)
    right = stderr.find("}", marker)
    data = json.loads(stderr[left : right + 1])

    def finite(value: object) -> float | None:
        try:
            number = float(str(value))
            return number if math.isfinite(number) else None
        except ValueError:
            return None

    return finite(data.get("input_i")), finite(data.get("input_tp"))


def analyze_loudness(source: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> SourceLoudness:
    """Measure source loudness and record the file fingerprint for normalization reuse."""
    fingerprint = source_fingerprint(source)
    lufs, peak = measure_loudness(source, runtime=runtime)
    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during loudness analysis")
    return SourceLoudness(lufs=lufs, true_peak_db=peak, fingerprint=fingerprint)


def normalization_gain(
    lufs: float | None,
    peak: float | None,
    target: float = DEFAULT_TARGET_LUFS,
    ceiling: float = DEFAULT_PEAK_CEILING_DB,
) -> float:
    """Return a fixed gain, keeping the measured true peak below the ceiling."""
    if lufs is None or not math.isfinite(lufs):
        raise SilentAudioError("Cannot measure track loudness")
    gain = target - lufs
    if peak is not None:
        if not math.isfinite(peak):
            raise SilentAudioError("Cannot measure track true peak")
        gain = min(gain, ceiling - peak)

    rounded = round(gain, 1)
    if peak is not None and rounded > ceiling - peak:
        rounded = round(rounded - 0.1, 1)
    return rounded


def calculate_normalization_gain(  # noqa: PLR0913 - Gain options, cache, and FFmpeg runtime.
    source: Path,
    effects: Effects | None = None,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
    *,
    known: SourceLoudness | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> float:
    """Measure processed audio and calculate a fixed gain within the true peak ceiling.

    Gain, loudness normalization, and the limiter of ``effects`` are ignored; trims apply.
    ``known`` is used instead of measuring only when no filters apply and its fingerprint matches
    the source file's size, mtime, and ctime.
    """
    measured = (effects or Effects()).model_copy()
    measured.gain_db = 0
    measured.normalize_lufs = None
    measured.limiter_ceiling_db = None

    fingerprint = source_fingerprint(source)
    trailing_end = trailing_trim_end(measured, source, runtime=runtime)
    if trailing_end is not None:
        measured.trim_end = trailing_end
    filters = audio_filters(measured, streaming=True, limiter_db=None)

    lufs: float | None
    peak: float | None
    if not filters and known is not None and known.fingerprint == fingerprint:
        lufs, peak = known.lufs, known.true_peak_db
    else:
        lufs, peak = measure_loudness(source, filters=filters, runtime=runtime)

    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during normalization")
    return normalization_gain(lufs, peak, target_lufs, peak_ceiling_db)
