import array
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import (
    Track,
    analyze_peak_waveform,
    analyze_waveform_tempo,
    probe,
    tempo_estimates,
)


def test_waveform_and_tempo_on_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    track = probe(Track(path=str(source)))
    assert len(analyze_peak_waveform(track)) == 400
    analyzed = analyze_waveform_tempo(track)
    assert analyzed is track
    assert analyzed.waveform
    assert len(analyzed.waveform_peak) == 400
    assert analyzed.waveform_peak[0] > 0


def test_peak_waveform_probes_missing_duration(tmp_path: Path) -> None:
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

    peaks = analyze_peak_waveform(Track(path=str(source)))
    assert len(peaks) == 400
    assert 100 < next(index for index, peak in enumerate(peaks) if peak > 0) < 150


def test_tempo_estimates_known_pulse_train() -> None:
    values = array.array("d", [1.0 if i % 5 == 0 else 0.0 for i in range(600)])
    estimates = tempo_estimates(memoryview(values))
    assert estimates
    assert estimates[0][1] == 120


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

    assert analyze_waveform_tempo(probe(Track(path=str(short)))).waveform

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

    analyzed = analyze_waveform_tempo(probe(Track(path=str(silent))))
    assert analyzed.waveform
    assert max(analyzed.waveform) == 0


def test_tempo_segment_transitions(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    estimates = [(0.0, 120.0, 0.5), (30.0, 60.0, 0.5), (60.0, 140.0, 0.5), (90.0, 140.0, 0.5)]
    monkeypatch.setattr(
        "ffkit.core.audio.analysis.waveform.tempo_estimates", lambda energy: estimates
    )

    track = analyze_waveform_tempo(probe(Track(path=str(source))))
    assert [(segment.start, segment.bpm) for segment in track.tempo] == [
        (0.0, 90.0),
        (60.0, 140.0),
    ]
