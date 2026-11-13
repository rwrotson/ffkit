# Silence level used by trim detection and trailing-silence removal.
DEFAULT_SILENCE_THRESHOLD_DB = -50

# Shortest edge silence that is trimmed, in seconds.
DEFAULT_TRIM_MIN_DURATION = 0.1

# Silence kept before the first and after the last audible window, in seconds.
DEFAULT_SILENCE_PADDING = 0.05

DEFAULT_TARGET_LUFS = -14
DEFAULT_PEAK_CEILING_DB = -1

# Lowest limiter ceiling accepted by effects and reached by render retries.
MIN_LIMITER_CEILING_DB = -20

DEFAULT_WAVEFORM_BINS = 400

# Floor of the 0..1 waveform display scales.
DEFAULT_DISPLAY_FLOOR_DB = -60.0

DEFAULT_MP3_BITRATE_KBPS = 320

LOUDNORM_TRUE_PEAK_DB = -1

# Integrated loudness targets accepted by the FFmpeg loudnorm filter.
LOUDNORM_MIN_LUFS = -70
LOUDNORM_MAX_LUFS = -5

LOUDNORM_RANGE = 11
