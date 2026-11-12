import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from ffkit import (
    CancelledError,
    FFmpegProcessError,
    FFmpegRuntime,
    InvalidInputError,
    SilentAudioError,
)
from ffkit.audio import AudioInfo, Effects, TrimBounds, detect_trim_bounds, probe

silence_module = importlib.import_module("ffkit.audio.analysis.silence")

RUNTIME = FFmpegRuntime()


def make_audio(path: Path, *sources: str) -> Path:
    inputs = [arg for source in sources for arg in ("-f", "lavfi", "-i", source)]
    labels = "".join(f"[{index}:a]" for index in range(len(sources)))
    graph = f"{labels}concat=n={len(sources)}:v=0:a=1"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            *inputs,
            "-filter_complex",
            graph,
            "-y",
            str(path),
        ],
        check=True,
    )
    return path


SILENCE = "anullsrc=r=44100:cl=mono:d=1"
TONE = "sine=frequency=440:sample_rate=44100:duration=1"


def test_trim_bounds_of_full_tone(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    assert detect_trim_bounds(source) == TrimBounds(start=0.0)


def test_trim_bounds_keep_internal_pause_and_pad_edges(tmp_path: Path) -> None:
    source = make_audio(tmp_path / "edges.flac", SILENCE, TONE, SILENCE, TONE, SILENCE)

    exact = detect_trim_bounds(source, padding=0)
    assert 0.98 <= exact.start <= 1.0
    assert exact.end is not None
    assert 4.0 <= exact.end <= 4.02

    padded = detect_trim_bounds(source, info=probe(source))
    assert padded.start == pytest.approx(exact.start - 0.05)
    assert padded.end == pytest.approx(exact.end + 0.05)


def test_trim_bounds_clamp_padding_and_keep_short_edges(tmp_path: Path) -> None:
    source = make_audio(
        tmp_path / "short-edges.wav",
        "anullsrc=r=44100:cl=mono:d=0.05",
        TONE,
        SILENCE,
    )
    bounds = detect_trim_bounds(source)
    assert bounds.start == 0.0
    assert bounds.end == pytest.approx(1.11, abs=0.02)
    assert detect_trim_bounds(source, padding=1).end is None


def test_trim_bounds_preserve_short_audible_tail(tmp_path: Path) -> None:
    source = make_audio(tmp_path / "tail.wav", TONE, SILENCE, "aevalsrc=0.1:s=44100:d=0.05")
    assert detect_trim_bounds(source) == TrimBounds(start=0.0)


def test_trim_bounds_ignore_isolated_peak(tmp_path: Path) -> None:
    # One sample at -30 dBFS ends silence for a sample-peak detector, not for a 20 ms RMS window.
    click = "aevalsrc='if(eq(n,22050),0.0316,0)':s=44100:d=1"
    source = make_audio(tmp_path / "click.wav", click, TONE)
    assert 0.98 <= detect_trim_bounds(source, padding=0).start <= 1.0


def test_trim_bounds_hear_any_channel(tmp_path: Path) -> None:
    source = tmp_path / "left.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-filter_complex",
            "[1:a]pan=stereo|c0=c0[left];[0:a][left]concat=n=2:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )
    assert 0.98 <= detect_trim_bounds(source, padding=0).start <= 1.0


def test_trim_bounds_relative_to_peak(tmp_path: Path) -> None:
    source = make_audio(
        tmp_path / "quiet.wav",
        "anoisesrc=r=44100:a=0.0001:d=1:seed=1",
        "sine=frequency=440:sample_rate=44100:duration=1,volume=-34dB",
    )
    with pytest.raises(SilentAudioError):
        detect_trim_bounds(source)

    bounds = detect_trim_bounds(source, threshold_reference="peak", threshold_db=-20, padding=0)
    assert 0.98 <= bounds.start <= 1.0


def test_trim_rejects_all_silence(tmp_path: Path) -> None:
    source = make_audio(tmp_path / "silent.wav", SILENCE)
    with pytest.raises(SilentAudioError, match="no audible audio"):
        detect_trim_bounds(source)
    with pytest.raises(SilentAudioError):
        detect_trim_bounds(source, threshold_reference="peak")


def test_trim_bounds_reject_invalid_options(tmp_path: Path) -> None:
    for options in [{"threshold_db": 1.0}, {"threshold_db": float("nan")}, {"padding": -1.0}]:
        with pytest.raises(InvalidInputError):
            detect_trim_bounds(tmp_path / "source.wav", **options)  # type: ignore[arg-type]


def test_trim_bounds_respect_cancellation_and_failures(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    with pytest.raises(CancelledError):
        detect_trim_bounds(source, cancelled=lambda: True)

    info = AudioInfo(duration=1, sample_rate=44100, channels=1, codec="pcm_s16le")
    with pytest.raises(FFmpegProcessError):
        detect_trim_bounds(tmp_path / "missing.wav", info=info)


def test_level_meter_is_independent_of_chunk_boundaries() -> None:
    rng = np.random.default_rng(1)
    samples = rng.uniform(-1, 1, size=(1234, 2)).astype("<f4")
    data = samples.tobytes()

    whole = silence_module._LevelMeter(1000, 2)
    whole.feed(data)
    expected = whole.finish()

    chunked = silence_module._LevelMeter(1000, 2)
    for offset in range(0, len(data), 7):
        chunked.feed(data[offset : offset + 7])
    np.testing.assert_allclose(chunked.finish(), expected)

    # 1234 frames are 123 full 10-frame blocks and a partial one, so 123 windows.
    assert len(expected) == 123
    assert whole.frames == chunked.frames == 1234
    blocks = np.square(samples[:20].astype(np.float64)).sum(axis=0)
    assert expected[0] == pytest.approx(blocks.max() / 20)


def test_level_meter_handles_short_and_empty_input() -> None:
    meter = silence_module._LevelMeter(1000, 1)
    assert len(meter.finish()) == 0

    meter.feed(np.full(4, 0.5, dtype="<f4").tobytes())
    levels = meter.finish()
    assert meter.frames == 4
    assert levels.tolist() == [pytest.approx(4 * 0.25 / 10)]
    span = silence_module._audible_span(
        levels,
        threshold_db=-50,
        reference="full_scale",
        block_seconds=0.01,
    )
    assert span == (0.0, 0.01)


def test_resolve_silence_trim_uses_trimmed_range(tmp_path: Path) -> None:
    source = make_audio(tmp_path / "edges.wav", SILENCE, TONE, SILENCE, TONE, SILENCE)

    plain = Effects(trim_start=0.5)
    assert silence_module.resolve_silence_trim(plain, source, runtime=RUNTIME) is plain

    effects = Effects(trim_start=0.5, trim_end=4.5, trim_silence=True, silence_padding=0)
    resolved = silence_module.resolve_silence_trim(effects, source, runtime=RUNTIME)
    assert not resolved.trim_silence
    assert 0.98 <= resolved.trim_start <= 1.0
    assert resolved.trim_end is not None
    assert 4.0 <= resolved.trim_end <= 4.02

    tail = Effects(trim_start=3.5, trim_silence=True, silence_padding=0)
    assert silence_module.resolve_silence_trim(tail, source, runtime=RUNTIME).trim_end == (
        pytest.approx(4.0, abs=0.02)
    )

    with pytest.raises(SilentAudioError):
        silence_module.resolve_silence_trim(
            Effects(trim_start=2.1, trim_end=2.9, trim_silence=True),
            source,
            runtime=RUNTIME,
        )
