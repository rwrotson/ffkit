import array
import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import CancelledError
from ffkit.audio import estimate_tempo

tempo_module = importlib.import_module("ffkit.audio.analysis.tempo")
energy_module = importlib.import_module("ffkit.audio.analysis._energy")


def test_tempo_of_steady_tone_is_empty(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    assert estimate_tempo(source) == ()


def test_tempo_estimates_known_pulse_train() -> None:
    values = array.array("d", [1.0 if i % 5 == 0 else 0.0 for i in range(600)])
    estimates = tempo_module._tempo_estimates(memoryview(values))
    assert estimates
    assert estimates[0][1] == 120


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


def test_tempo_segment_transitions(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    estimates = [(0.0, 120.0, 0.5), (30.0, 60.0, 0.5), (60.0, 140.0, 0.5), (90.0, 140.0, 0.5)]
    monkeypatch.setattr(tempo_module, "_tempo_estimates", lambda energy: estimates)

    assert [(segment.start, segment.bpm) for segment in estimate_tempo(source)] == [
        (0.0, 90.0),
        (60.0, 140.0),
    ]


def test_tempo_respects_cancellation(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    with pytest.raises(CancelledError):
        estimate_tempo(source, cancelled=lambda: True)


def test_tempo_of_source_without_decoded_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(energy_module, "iter_output", lambda *args, **kwargs: iter(()))

    assert estimate_tempo("empty.wav") == ()
