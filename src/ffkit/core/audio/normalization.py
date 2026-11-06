from pathlib import Path

from ffkit.core.audio.analysis import measure_loudness
from ffkit.core.audio.filters import audio_filters, normalization_gain
from ffkit.core.audio.models import Track


def calculate_normalization_gain(
    track: Track, target_lufs: float = -14, peak_ceiling_db: float = -1
) -> float:
    """Measure processed audio and calculate a fixed gain within the true peak ceiling."""
    measured = track.model_copy(deep=True)
    measured.effects.normalize_lufs = None
    measured.effects.limiter_ceiling_db = None
    measured.effects.gain_db = 0
    filters = audio_filters(measured, limiter_db=None)
    source = Path(measured.path)
    stat = source.stat()
    fingerprint = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
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
    after = source.stat()
    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != fingerprint:
        raise ValueError("Source audio changed during normalization")
    return normalization_gain(lufs, peak, target_lufs, peak_ceiling_db)
