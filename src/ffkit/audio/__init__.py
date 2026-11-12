"""Audio analysis and processing helpers."""

from . import library
from .analysis.cover import embedded_cover
from .analysis.loudness import (
    Loudness,
    gain_for_target,
    measure_loudness,
    measure_normalization_gain,
)
from .analysis.probe import AudioInfo, probe
from .analysis.silence import TrimBounds, detect_trim_bounds
from .analysis.tempo import TempoSegment, estimate_tempo
from .analysis.waveform import peak_envelope, waveform
from .defaults import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
)
from .effects import Effects
from .encoding import Encoding, Mp3Encoding
from .processing.extract import extract_cover
from .processing.render import render
from .processing.stream import stream

__all__ = [
    "DEFAULT_PEAK_CEILING_DB",
    "DEFAULT_SILENCE_THRESHOLD_DB",
    "DEFAULT_TARGET_LUFS",
    "DEFAULT_TRIM_MIN_DURATION",
    "AudioInfo",
    "Effects",
    "Encoding",
    "Loudness",
    "Mp3Encoding",
    "TempoSegment",
    "TrimBounds",
    "detect_trim_bounds",
    "embedded_cover",
    "estimate_tempo",
    "extract_cover",
    "gain_for_target",
    "library",
    "measure_loudness",
    "measure_normalization_gain",
    "peak_envelope",
    "probe",
    "render",
    "stream",
    "waveform",
]
