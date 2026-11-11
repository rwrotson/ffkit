import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import (
    Track,
    analyze_loudness,
    calculate_normalization_gain,
    measure_loudness,
    normalization_gain,
    probe,
)

silence_module = importlib.import_module("ffkit.core.audio.analysis.silence")
loudness_module = importlib.import_module("ffkit.core.audio.analysis.loudness")


def test_measure_loudness_on_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    lufs, peak = measure_loudness(source)
    assert lufs is not None
    assert peak is not None
    louder, _ = measure_loudness(source, ["volume=6dB"])
    assert louder is not None
    assert 5 < louder - lufs < 7


def test_normalization_gain_limits_peak() -> None:
    assert normalization_gain(-20, -5) == 4.0
    assert normalization_gain(-18, None) == 4.0
    assert normalization_gain(-18, -10, target=-16, ceiling=-3) == 2.0
    assert normalization_gain(-14, -0.96) == -0.1
    assert normalization_gain(-18, -5.04) == 4.0
    assert normalization_gain(-18, -4.96) == 3.9

    with pytest.raises(ValueError, match="Cannot measure"):
        normalization_gain(None, None)
    with pytest.raises(ValueError, match="Cannot measure"):
        normalization_gain(float("nan"), None)
    with pytest.raises(ValueError, match="true peak"):
        normalization_gain(-14, float("inf"))


def test_measure_loudness_handles_missing_and_nonfinite_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess([], 0, stderr="no loudnorm report")
    monkeypatch.setattr(
        "ffkit.core.audio.analysis.loudness.subprocess.run", lambda *args, **kwargs: result
    )
    assert measure_loudness(Path("song.wav")) == (None, None)
    result.stderr = '{"input_i": "inf", "input_tp": "not a number"}'
    assert measure_loudness(Path("song.wav")) == (None, None)


def test_calculate_normalization_gain_uses_processed_audio(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    track = probe(Track(path=str(source)))
    raw_lufs, raw_peak = measure_loudness(source)
    assert raw_lufs is not None
    assert raw_peak is not None

    stat = source.stat()
    track.analysis_source_stat = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    track.loudness_lufs = raw_lufs
    track.true_peak_db = raw_peak

    expected = calculate_normalization_gain(track)
    track.effects.gain_db = 6
    assert calculate_normalization_gain(track) == expected
    track.effects.trim_start = 0.2
    assert isinstance(calculate_normalization_gain(track), float)
    track.effects.trim_silence = True
    assert isinstance(calculate_normalization_gain(track), float)


def test_calculate_normalization_gain_rejects_changed_source(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    track = Track(path=str(source))

    def change_source(path: Path, filters: list[str], **kwargs: object) -> tuple[float, float]:
        path.touch()
        return -18, -5

    monkeypatch.setattr(loudness_module, "measure_loudness", change_source)
    with pytest.raises(ValueError, match="Source audio changed"):
        calculate_normalization_gain(track)


def test_calculate_normalization_gain_rejects_all_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "silent.wav"
    source.touch()
    track = Track(path=str(source))
    track.effects.trim_silence = True

    monkeypatch.setattr(silence_module, "trailing_silence_end", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(
        silence_module, "probe", lambda track, **kwargs: Track(path=track.path, duration=1.0)
    )

    with pytest.raises(ValueError, match="no audible audio"):
        calculate_normalization_gain(track)


def test_analyze_loudness_fills_normalization_cache(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    track = analyze_loudness(Track(path=str(source)))
    assert track.loudness_lufs is not None
    assert track.true_peak_db is not None
    stat = source.stat()
    assert track.analysis_source_stat == (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    expected = calculate_normalization_gain(track.model_copy(update={"loudness_lufs": None}))

    def unexpected(*args: object) -> None:
        raise AssertionError("measure_loudness should not run")

    monkeypatch.setattr(loudness_module, "measure_loudness", unexpected)
    assert calculate_normalization_gain(track) == expected


def test_analyze_loudness_rejects_changed_source(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    def change_source(path: Path, **kwargs: object) -> tuple[float, float]:
        source.write_bytes(source.read_bytes() + b"x")
        return -20.0, -3.0

    monkeypatch.setattr(loudness_module, "measure_loudness", change_source)
    with pytest.raises(ValueError, match="changed during loudness analysis"):
        analyze_loudness(Track(path=str(source)))
