"""Audio analysis and processing helpers."""

from .analysis.cover import embedded_cover
from .analysis.loudness import (
    Loudness,
    gain_for_target,
    measure_loudness,
    measure_normalization_gain,
)
from .analysis.probe import AudioInfo, probe
from .analysis.silence import TrimBounds, detect_trim_bounds
from .analysis.waveform import TempoSegment, estimate_tempo, peak_envelope, waveform
from .defaults import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
)
from .effects import Effects
from .files import audio_files, safe_name
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
    "Loudness",
    "MergedTags",
    "TempoSegment",
    "TrimBounds",
    "audio_files",
    "detect_trim_bounds",
    "embedded_cover",
    "estimate_tempo",
    "extract_cover",
    "gain_for_target",
    "measure_loudness",
    "measure_normalization_gain",
    "merge_tags",
    "peak_envelope",
    "probe",
    "render",
    "safe_name",
    "stream_mp3",
    "waveform",
]
