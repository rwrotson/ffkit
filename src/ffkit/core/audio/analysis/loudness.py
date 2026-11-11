import json
import math
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ffkit.core._ffmpeg import media_path, source_fingerprint
from ffkit.core.audio._constants import LOUDNORM_RANGE, LOUDNORM_TRUE_PEAK_DB
from ffkit.core.audio.analysis.silence import trailing_trim_end
from ffkit.core.audio.defaults import DEFAULT_PEAK_CEILING_DB, DEFAULT_TARGET_LUFS
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Track
from ffkit.core.runtime import FFmpegRuntime


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

    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffmpeg_path,
            "-hide_banner",
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
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=runtime.process_timeout,
    )

    marker = result.stderr.rfind('"input_i"')
    if marker < 0:
        return None, None
    left = result.stderr.rfind("{", 0, marker)
    right = result.stderr.find("}", marker)
    data = json.loads(result.stderr[left : right + 1])

    def finite(value: object) -> float | None:
        try:
            number = float(str(value))
            return number if math.isfinite(number) else None
        except ValueError:
            return None

    return finite(data.get("input_i")), finite(data.get("input_tp"))


def analyze_loudness(track: Track, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> Track:
    """Measure source loudness and record the file fingerprint for normalization reuse."""
    source = Path(track.path)
    fingerprint = source_fingerprint(source)
    lufs, peak = measure_loudness(source, runtime=runtime)
    if source_fingerprint(source) != fingerprint:
        raise ValueError("Source audio changed during loudness analysis")

    track.loudness_lufs = lufs
    track.true_peak_db = peak
    track.analysis_source_stat = fingerprint
    return track


def normalization_gain(
    lufs: float | None,
    peak: float | None,
    target: float = DEFAULT_TARGET_LUFS,
    ceiling: float = DEFAULT_PEAK_CEILING_DB,
) -> float:
    """Return a fixed gain, keeping the measured true peak below the ceiling."""
    if lufs is None or not math.isfinite(lufs):
        raise ValueError("Cannot measure track loudness")
    gain = target - lufs
    if peak is not None:
        if not math.isfinite(peak):
            raise ValueError("Cannot measure track true peak")
        gain = min(gain, ceiling - peak)

    rounded = round(gain, 1)
    if peak is not None and rounded > ceiling - peak:
        rounded = round(rounded - 0.1, 1)
    return rounded


def calculate_normalization_gain(
    track: Track,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
    *,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> float:
    """Measure processed audio and calculate a fixed gain within the true peak ceiling.

    Stored ``loudness_lufs`` and ``true_peak_db`` are reused instead of measuring only when no
    filters apply and ``analysis_source_stat`` matches the source file's size, mtime, and ctime.
    """
    measured = track.model_copy(deep=True)
    measured.effects.normalize_lufs = None
    measured.effects.limiter_ceiling_db = None
    measured.effects.gain_db = 0

    source = Path(measured.path)
    fingerprint = source_fingerprint(source)
    trailing_end = trailing_trim_end(measured.effects, source, runtime=runtime)
    if trailing_end is not None:
        measured.effects.trim_end = trailing_end
    filters = audio_filters(measured, streaming=True, limiter_db=None)

    lufs: float | None
    peak: float | None
    if (
        not filters
        and track.analysis_source_stat == fingerprint
        and track.loudness_lufs is not None
    ):
        lufs, peak = track.loudness_lufs, track.true_peak_db
    else:
        lufs, peak = measure_loudness(source, filters=filters, runtime=runtime)

    if source_fingerprint(source) != fingerprint:
        raise ValueError("Source audio changed during normalization")
    return normalization_gain(lufs, peak, target_lufs, peak_ceiling_db)
