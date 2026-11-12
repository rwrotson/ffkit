import importlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import CancelledError
from ffkit._ffmpeg.process import ERROR_TAIL_LIMIT
from ffkit.audio import Effects, detect_trim_bounds, probe
from ffkit.audio.analysis.silence import SilenceScan

silence_module = importlib.import_module("ffkit.audio.analysis.silence")
TOOLS = {"ffmpeg": "ffmpeg", "timeout": 30.0}


def test_trim_bounds_of_full_tone(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    assert detect_trim_bounds(source, 2.0) == (0.0, None)


def test_trim_bounds_keep_internal_pause(tmp_path: Path) -> None:
    source = tmp_path / "edges.flac"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-filter_complex",
            "[0:a][1:a][0:a][1:a][0:a]concat=n=5:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )

    start, end = detect_trim_bounds(source)
    assert 0.9 < start < 1.1
    assert end is not None
    assert 3.9 < end < 4.1

    duration = probe(source).duration
    assert detect_trim_bounds(source, duration) == (start, end)


def test_trim_bounds_preserve_short_audible_tail(tmp_path: Path) -> None:
    source = tmp_path / "short-tail.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.1:s=44100:d=0.05",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )

    duration = probe(source).duration
    assert detect_trim_bounds(source) == (0.0, None)
    assert detect_trim_bounds(source, duration) == (0.0, None)


def test_trim_rejects_all_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    scan = SilenceScan.from_lines([b"silence_start: 0", b"silence_end: 2", b"silence_start: 2"])
    monkeypatch.setattr("ffkit.audio.analysis.silence.scan_silence", lambda *args, **kwargs: scan)
    with pytest.raises(ValueError, match="no audible audio"):
        detect_trim_bounds(Path("silent.wav"), duration=2)


def test_trim_bounds_respect_cancellation(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    with pytest.raises(CancelledError):
        detect_trim_bounds(source, cancelled=lambda: True)


def test_trailing_silence_scan_handles_no_silence_and_empty_trim(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source, duration=1)
    effects = Effects()
    assert silence_module.trailing_silence_end(effects, source, 1.0, **TOOLS) is None
    effects.trim_start = 2
    assert silence_module.trailing_silence_end(effects, source, 1.0, **TOOLS) is None
    with pytest.raises(ValueError, match="duration is unavailable"):
        silence_module.trailing_silence_end(effects, source, None, **TOOLS)


def test_trailing_silence_scan_respects_cancellation(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source, duration=1)
    with pytest.raises(CancelledError, match="Export cancelled"):
        silence_module.trailing_silence_end(Effects(), source, 1.0, lambda: True, **TOOLS)


def test_trailing_silence_scan_handles_ffmpeg_failure_and_timeout() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        silence_module.scan_silence(
            ["ffmpeg", "-v", "error", "-i", "missing.wav", "-f", "null", "-"], None, timeout=30
        )
    with pytest.raises(subprocess.TimeoutExpired):
        silence_module.scan_silence(
            [sys.executable, "-c", "import time; time.sleep(10)"], None, timeout=0.01
        )


def test_trailing_silence_scan_bounds_error_output() -> None:
    command = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000); sys.exit(2)"]
    with pytest.raises(subprocess.CalledProcessError) as error:
        silence_module.scan_silence(command, None, timeout=30)
    assert len(error.value.stderr) == ERROR_TAIL_LIMIT
