"""Public library API, independent of configuration and logging setup."""

from .analysis import (
    analyze_peak_waveform,
    analyze_waveform_tempo,
    detect_trim_bounds,
    measure_loudness,
    probe,
    tempo_estimates,
)
from .audio import audio_filters, normalization_gain, safe_name
from .errors import FFKitError, InvalidInputError
from .formats import audio_files
from .models import Effects, Group, TempoSegment, Track

__all__ = [
    "Effects",
    "FFKitError",
    "Group",
    "InvalidInputError",
    "TempoSegment",
    "Track",
    "analyze_peak_waveform",
    "analyze_waveform_tempo",
    "audio_files",
    "audio_filters",
    "detect_trim_bounds",
    "measure_loudness",
    "normalization_gain",
    "probe",
    "safe_name",
    "tempo_estimates",
]
