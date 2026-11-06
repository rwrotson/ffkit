import logging

from .core import (
    Effects,
    FFKitError,
    Group,
    InvalidInputError,
    TempoSegment,
    Track,
    audio_files,
    audio_filters,
    normalization_gain,
    safe_name,
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
    "audio_files",
    "audio_filters",
    "normalization_gain",
    "safe_name",
]
