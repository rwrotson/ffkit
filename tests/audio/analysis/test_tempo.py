import importlib
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from ffkit import CancelledError
from ffkit.audio import TempoSegment, estimate_tempo

tempo_module = importlib.import_module("ffkit.audio.analysis.tempo")


def click_track(path: Path, *parts: tuple[float, float]) -> Path:
    """Write decaying 1 kHz clicks for each (bpm, seconds) part."""
    inputs: list[str] = []
    for bpm, seconds in parts:
        click = f"0.8*sin(2*PI*1000*t)*exp(-mod(t,{60 / bpm})*60)"
        inputs += ["-f", "lavfi", "-i", f"aevalsrc='{click}':s=22050:d={seconds}"]
    labels = "".join(f"[{index}:a]" for index in range(len(parts)))
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            *inputs,
            "-filter_complex",
            f"{labels}concat=n={len(parts)}:v=0:a=1",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path


def test_tempo_of_steady_tone_is_empty(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    assert estimate_tempo(source) == ()


def test_tempo_of_click_track(tmp_path: Path) -> None:
    source = click_track(tmp_path / "clicks.wav", (120, 20))

    assert estimate_tempo(source) == (TempoSegment(start=0, bpm=120, confidence=1),)


def test_tempo_segment_transitions(tmp_path: Path) -> None:
    source = click_track(tmp_path / "change.wav", (120, 20), (140, 20))

    segments = estimate_tempo(source)

    assert [segment.bpm for segment in segments] == [120, 140]
    assert segments[0].start == 0
    assert 18 < segments[1].start < 30


def test_tempo_of_silent_audio_is_empty(tmp_path: Path) -> None:
    silent = tmp_path / "silent.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=0.3",
            "-y",
            str(silent),
        ],
        check=True,
    )

    assert estimate_tempo(silent) == ()


def test_tempo_respects_cancellation(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    with pytest.raises(CancelledError):
        estimate_tempo(source, cancelled=lambda: True)


def test_tempo_of_source_without_decoded_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tempo_module, "iter_output", lambda *args, **kwargs: iter(()))
    Path("empty.wav").write_bytes(b"")

    assert estimate_tempo("empty.wav") == ()


def test_onset_strength_is_independent_of_chunk_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(1)
    data = rng.uniform(-1, 1, 5000).astype("<f4").tobytes()

    def onsets(chunk_size: int) -> np.ndarray:
        def chunks(*args: object, **kwargs: object) -> Iterator[bytes]:
            for offset in range(0, len(data), chunk_size):
                yield data[offset : offset + chunk_size]

        monkeypatch.setattr(tempo_module, "iter_output", chunks)
        return tempo_module._onset_strength(  # type: ignore[no-any-return]
            "source.wav",
            cancelled=None,
            runtime=tempo_module.FFmpegRuntime(),
        )

    expected = onsets(len(data))
    np.testing.assert_allclose(onsets(1001), expected)
    assert len(expected) == (5000 - tempo_module.FRAME) // tempo_module.HOP + 1


def test_window_tempo_needs_periodicity() -> None:
    assert tempo_module._window_tempi(np.ones(10)) == []
    assert tempo_module._window_tempi(np.ones(800)) == []
    assert tempo_module._window_tempo(np.ones(1024)) is None
    assert tempo_module._window_tempo(np.tile([1.0, 0.0], 100)) is None

    rng = np.random.default_rng(2)
    assert tempo_module._window_tempo(rng.uniform(0, 1, 1024)) is None
    assert tempo_module._window_tempo(np.tile([1.0, 0.0], 512)) is None


def test_windows_keep_only_support_lags() -> None:
    period = round(tempo_module.ONSET_RATE / 2)
    onsets = (np.arange(4000) % period == 0).astype(float)

    windows = tempo_module._window_tempi(onsets)

    assert windows
    longest_lag = tempo_module._lag(tempo_module.OCTAVE_MIN_BPM)
    for _, _, acf in windows:
        assert longest_lag < len(acf) < tempo_module.WINDOW
        assert acf.base is None


def test_low_confidence_segments_are_empty() -> None:
    acf = np.zeros(tempo_module.WINDOW)
    windows = [(float(index), 61.0 + 11 * index, acf) for index in range(20)]

    assert tempo_module._segments(windows, 100.0) == ()


def test_tempo_helpers() -> None:
    values = np.array([0.0, 1.0, 2.0])
    assert tempo_module._refine(values, 1) == 1.0
    assert tempo_module._refine(np.array([0.0, 1.0, 0.5]), 1) == pytest.approx(1.1666667)

    assert tempo_module._fold(60.0, 120.0) == 120.0
    assert tempo_module._fold(240.0, 120.0) == 120.0
    assert tempo_module._fold(90.0, 120.0) == 90.0

    acf = np.zeros(tempo_module.WINDOW)
    assert tempo_module._octave([(0.0, 250.0, acf)], 250.0) in {125.0, 250.0}
