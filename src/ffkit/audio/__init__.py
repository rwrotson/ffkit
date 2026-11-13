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
from .analysis.waveform import ChannelPeaks, Waveform, waveform
from .defaults import (
    DEFAULT_DISPLAY_FLOOR_DB,
    DEFAULT_MP3_BITRATE_KBPS,
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_SILENCE_PADDING,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
    DEFAULT_WAVEFORM_BINS,
)
from .effects import Effects, SilenceReference
from .encoding import Encoding, Mp3Encoding
from .processing.extract import extract_cover
from .processing.render import render
from .processing.stream import stream

__all__ = [
    "DEFAULT_DISPLAY_FLOOR_DB",
    "DEFAULT_MP3_BITRATE_KBPS",
    "DEFAULT_PEAK_CEILING_DB",
    "DEFAULT_SILENCE_PADDING",
    "DEFAULT_SILENCE_THRESHOLD_DB",
    "DEFAULT_TARGET_LUFS",
    "DEFAULT_TRIM_MIN_DURATION",
    "DEFAULT_WAVEFORM_BINS",
    "AudioInfo",
    "ChannelPeaks",
    "Effects",
    "Encoding",
    "Loudness",
    "Mp3Encoding",
    "SilenceReference",
    "TempoSegment",
    "TrimBounds",
    "Waveform",
    "detect_trim_bounds",
    "embedded_cover",
    "estimate_tempo",
    "extract_cover",
    "gain_for_target",
    "library",
    "measure_loudness",
    "measure_normalization_gain",
    "probe",
    "render",
    "stream",
    "waveform",
]
