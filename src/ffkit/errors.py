from collections.abc import Sequence


class FFKitError(Exception):
    """Base class for expected library failures."""


class InvalidInputError(FFKitError, ValueError):
    """The input cannot be processed."""


class SourceNotFoundError(InvalidInputError, FileNotFoundError):
    """An input file does not exist."""


class NoAudioError(InvalidInputError):
    """The source has no decodable audio stream or no measurable duration."""


class SilentAudioError(InvalidInputError):
    """The source, or its selected range, contains no audible audio."""


class SourceChangedError(FFKitError):
    """The source file changed while it was being processed."""


class PeakCeilingError(FFKitError):
    """The encoded output could not be kept below the true peak ceiling."""


class CancelledError(FFKitError, RuntimeError):
    """The caller cancelled the operation."""


class FFmpegError(FFKitError):
    """FFmpeg or FFprobe failed or produced unusable output."""

    def __init__(self, message: str, *, command: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.command = tuple(command)


class FFmpegNotFoundError(FFmpegError):
    """The FFmpeg or FFprobe executable cannot be started."""

    def __init__(self, executable: str, *, command: Sequence[str] = ()) -> None:
        super().__init__(f"Executable not found: {executable}", command=command)
        self.executable = executable


class FFmpegTimeoutError(FFmpegError, TimeoutError):
    """FFmpeg or FFprobe exceeded its time limit."""


class FFmpegProcessError(FFmpegError):
    """FFmpeg or FFprobe exited with a non-zero status."""

    def __init__(self, returncode: int, stderr: str, *, command: Sequence[str] = ()) -> None:
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "no error output"
        super().__init__(f"Exited with status {returncode}: {detail}", command=command)
        self.returncode = returncode
        self.stderr = stderr
