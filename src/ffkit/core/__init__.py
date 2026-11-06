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
from .cover import extract_cover
from .errors import FFKitError, InvalidInputError
from .formats import audio_files
from .models import Effects, Group, TempoSegment, Track
from .normalization import calculate_normalization_gain
from .render import render
from .stream import stream_mp3

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
    "calculate_normalization_gain",
    "detect_trim_bounds",
    "extract_cover",
    "measure_loudness",
    "normalization_gain",
    "probe",
    "render",
    "safe_name",
    "stream_mp3",
    "tempo_estimates",
]
