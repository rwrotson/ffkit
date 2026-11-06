import logging

from .core import (
    Effects,
    FFKitError,
    Group,
    InvalidInputError,
    TempoSegment,
    Track,
    analyze_peak_waveform,
    analyze_waveform_tempo,
    audio_files,
    audio_filters,
    detect_trim_bounds,
    measure_loudness,
    normalization_gain,
    probe,
    safe_name,
    tempo_estimates,
)

# Records stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

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
