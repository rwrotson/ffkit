import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ffkit import FFmpegNotFoundError, FFmpegRuntime, FFmpegTimeoutError
from ffkit.audio import (
    detect_trim_bounds,
    estimate_tempo,
    extract_cover,
    measure_loudness,
    measure_normalization_gain,
    probe,
    render,
    stream,
    waveform,
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "tone.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "value",
    [
        {"ffmpeg_path": ""},
        {"ffprobe_path": ""},
        {"process_timeout": 0},
        {"stream_idle_timeout": -1},
    ],
)
def test_runtime_rejects_invalid_values(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FFmpegRuntime.model_validate(value)


def test_runtime_is_frozen() -> None:
    runtime = FFmpegRuntime()
    with pytest.raises(ValidationError):
        runtime.ffmpeg_path = "other"  # type: ignore[misc]  # Checks the frozen model at runtime.


ffprobe_calls: list[Callable[[Path, Path, FFmpegRuntime], object]] = [
    lambda source, _, runtime: probe(source, runtime=runtime),
    lambda source, _, runtime: waveform(source, runtime=runtime),
]
ffmpeg_calls: list[Callable[[Path, Path, FFmpegRuntime], object]] = [
    lambda source, _, runtime: measure_loudness(source, runtime=runtime),
    lambda source, _, runtime: waveform(source, runtime=runtime),
    lambda source, _, runtime: estimate_tempo(source, runtime=runtime),
    lambda source, _, runtime: measure_normalization_gain(source, runtime=runtime),
    lambda source, _, runtime: detect_trim_bounds(source, runtime=runtime),
    lambda source, out, runtime: render(source, out / "out.mp3", runtime=runtime),
    lambda source, _, runtime: b"".join(stream(source, runtime=runtime)),
]


@pytest.mark.parametrize("call", ffprobe_calls)
def test_functions_use_configured_ffprobe(
    call: Callable[[Path, Path, FFmpegRuntime], object],
    source: Path,
    tmp_path: Path,
) -> None:
    missing = str(tmp_path / "missing-ffprobe")
    with pytest.raises(FFmpegNotFoundError) as error:
        call(source, tmp_path, FFmpegRuntime(ffprobe_path=missing))
    assert error.value.executable == missing


@pytest.mark.parametrize("call", ffmpeg_calls)
def test_functions_use_configured_ffmpeg(
    call: Callable[[Path, Path, FFmpegRuntime], object],
    source: Path,
    tmp_path: Path,
) -> None:
    missing = str(tmp_path / "missing-ffmpeg")
    with pytest.raises(FFmpegNotFoundError) as error:
        call(source, tmp_path, FFmpegRuntime(ffmpeg_path=missing))
    assert error.value.executable == missing


def test_extract_cover_uses_configured_ffmpeg(source: Path, tmp_path: Path) -> None:
    missing = str(tmp_path / "missing-ffmpeg")
    with pytest.raises(FFmpegNotFoundError) as error:
        extract_cover(
            source,
            tmp_path / "cover.jpg",
            runtime=FFmpegRuntime(ffmpeg_path=missing),
        )
    assert error.value.executable == missing


def test_stream_uses_idle_timeout(source: Path, tmp_path: Path) -> None:
    silent_encoder = tmp_path / "silent-ffmpeg"
    silent_encoder.write_text("#!/bin/sh\nsleep 10\n")
    silent_encoder.chmod(0o755)
    runtime = FFmpegRuntime(ffmpeg_path=str(silent_encoder), stream_idle_timeout=0.1)
    with pytest.raises(FFmpegTimeoutError, match="no output"):
        b"".join(stream(source, runtime=runtime))
