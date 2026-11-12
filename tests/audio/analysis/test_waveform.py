import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import CancelledError
from ffkit.audio import peak_envelope, probe, waveform

energy_module = importlib.import_module("ffkit.audio.analysis._energy")


def test_waveform_on_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    peaks = peak_envelope(source, info=probe(source))

    assert waveform(source)
    assert len(peaks) == 400
    assert peaks[0] > 0


def test_peak_envelope_probes_without_info(tmp_path: Path) -> None:
    source = tmp_path / "delayed.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-af",
            "adelay=500|500",
            "-y",
            str(source),
        ],
        check=True,
    )

    peaks = peak_envelope(source)
    assert len(peaks) == 400
    assert 100 < next(index for index, peak in enumerate(peaks) if peak > 0) < 150


def test_short_and_silent_audio_analysis(tmp_path: Path) -> None:
    short = tmp_path / "short.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.13",
            "-y",
            str(short),
        ],
        check=True,
    )

    assert waveform(short)

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

    silent_waveform = waveform(silent)
    assert silent_waveform
    assert max(silent_waveform) == 0


def test_waveform_functions_respect_cancellation_and_string_paths(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    for analyze in (peak_envelope, waveform):
        with pytest.raises(CancelledError):
            analyze(source, cancelled=lambda: True)
    assert peak_envelope(str(source)) == peak_envelope(source)
    assert waveform(str(source)) == waveform(source)


def test_waveform_of_source_without_decoded_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(energy_module, "iter_output", lambda *args, **kwargs: iter(()))

    assert waveform("empty.wav") == ()
