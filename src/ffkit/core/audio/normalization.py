from pathlib import Path

from ffkit.core.audio._ffmpeg import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    source_fingerprint,
)
from ffkit.core.audio.analysis import measure_loudness, trailing_trim_end
from ffkit.core.audio.filters import audio_filters, normalization_gain
from ffkit.core.audio.models import Track


def calculate_normalization_gain(
    track: Track,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
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
    trailing_end = trailing_trim_end(measured.effects, source)
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
        lufs, peak = measure_loudness(source, filters)
    if source_fingerprint(source) != fingerprint:
        raise ValueError("Source audio changed during normalization")
    return normalization_gain(lufs, peak, target_lufs, peak_ceiling_db)
