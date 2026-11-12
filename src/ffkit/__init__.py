import logging

from . import audio
from .errors import (
    CancelledError,
    FFKitError,
    FFmpegError,
    FFmpegNotFoundError,
    FFmpegProcessError,
    FFmpegTimeoutError,
    InvalidInputError,
    NoAudioError,
    PeakCeilingError,
    SilentAudioError,
    SourceChangedError,
    SourceNotFoundError,
)
from .runtime import FFmpegRuntime

# Records stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "CancelledError",
    "FFKitError",
    "FFmpegError",
    "FFmpegNotFoundError",
    "FFmpegProcessError",
    "FFmpegRuntime",
    "FFmpegTimeoutError",
    "InvalidInputError",
    "NoAudioError",
    "PeakCeilingError",
    "SilentAudioError",
    "SourceChangedError",
    "SourceNotFoundError",
    "audio",
]
