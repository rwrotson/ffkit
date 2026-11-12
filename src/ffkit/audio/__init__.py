"""Audio analysis and processing helpers."""

from .analysis.cover import embedded_cover
from .analysis.loudness import (
    SourceLoudness,
    analyze_loudness,
    calculate_normalization_gain,
    measure_loudness,
    normalization_gain,
)
from .analysis.probe import AudioInfo, probe
from .analysis.silence import detect_trim_bounds
from .analysis.waveform import (
    TempoSegment,
    WaveformAnalysis,
    analyze_peak_waveform,
    analyze_waveform_tempo,
    tempo_estimates,
)
from .defaults import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
)
from .effects import Effects
from .files import audio_files, safe_name
from .filters import audio_filters
from .processing.extract import extract_cover
from .processing.render import render
from .processing.stream import stream_mp3
from .tags import MergedTags, merge_tags

__all__ = [
    "DEFAULT_PEAK_CEILING_DB",
    "DEFAULT_SILENCE_THRESHOLD_DB",
    "DEFAULT_TARGET_LUFS",
    "DEFAULT_TRIM_MIN_DURATION",
    "AudioInfo",
    "Effects",
    "MergedTags",
    "SourceLoudness",
    "TempoSegment",
    "WaveformAnalysis",
    "analyze_loudness",
    "analyze_peak_waveform",
    "analyze_waveform_tempo",
    "audio_files",
    "audio_filters",
    "calculate_normalization_gain",
    "detect_trim_bounds",
    "embedded_cover",
    "extract_cover",
    "measure_loudness",
    "merge_tags",
    "normalization_gain",
    "probe",
    "render",
    "safe_name",
    "stream_mp3",
    "tempo_estimates",
]
