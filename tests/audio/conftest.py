import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _make_tone(path: Path, *, duration: float = 2, gain: float = 0) -> None:
    gain_filter = ["-filter:a", f"volume={gain}dB"] if gain else []
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            *gain_filter,
            "-y",
            str(path),
        ],
        check=True,
    )


@pytest.fixture
def make_tone() -> Callable[..., None]:
    """Return a writer of a 440 Hz sine tone; ``duration`` and ``gain`` are keyword options."""
    return _make_tone


def _make_video(path: Path, *, duration: float = 1) -> None:
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=64x64",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(path),
        ],
        check=True,
    )


@pytest.fixture
def make_video() -> Callable[..., None]:
    """Return a writer of an MP4 with a video track and a sine tone; ``duration`` is an option."""
    return _make_video
