import importlib
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ffkit import CancelledError, SilentAudioError, SourceChangedError
from ffkit.audio import (
    AudioInfo,
    Effects,
    Loudness,
    gain_for_target,
    measure_loudness,
    measure_normalization_gain,
)

silence_module = importlib.import_module("ffkit.audio.analysis.silence")
loudness_module = importlib.import_module("ffkit.audio.analysis.loudness")
ONE_SECOND = AudioInfo(duration=1.0, sample_rate=44100, channels=1, codec="pcm_s16le")


def test_measure_loudness_on_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    loudness = measure_loudness(source)
    louder = measure_loudness(source, filters=["volume=6dB"])

    assert loudness.lufs is not None
    assert loudness.true_peak_db is not None
    stat = source.stat()
    assert loudness.fingerprint == (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    assert louder.lufs is not None
    assert 5 < louder.lufs - loudness.lufs < 7
    assert louder.fingerprint is None


def test_gain_for_target_limits_peak() -> None:
    def gain(lufs: float | None, peak: float | None, **kwargs: float) -> float:
        return gain_for_target(Loudness(lufs=lufs, true_peak_db=peak), **kwargs)

    assert gain(-20, -5) == 4.0
    assert gain(-18, None) == 4.0
    assert gain(-18, -10, target_lufs=-16, peak_ceiling_db=-3) == 2.0
    assert gain(-14, -0.96) == -0.1
    assert gain(-18, -5.04) == 4.0
    assert gain(-18, -4.96) == 3.9
    with pytest.raises(SilentAudioError, match="Cannot measure"):
        gain(None, None)


def test_loudness_rejects_nonfinite_values() -> None:
    with pytest.raises(ValidationError):
        Loudness(lufs=float("nan"), true_peak_db=None)
    with pytest.raises(ValidationError):
        Loudness(lufs=-14, true_peak_db=float("inf"))


def test_measure_loudness_handles_missing_and_nonfinite_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "song.wav"
    source.touch()
    reports = iter([b"no loudnorm report", b'{"input_i": "inf", "input_tp": "not a number"}'])
    monkeypatch.setattr(loudness_module, "run", lambda *args, **kwargs: next(reports))

    assert measure_loudness(source).lufs is None
    assert measure_loudness(source).true_peak_db is None


def test_measure_loudness_rejects_changed_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "song.wav"
    source.touch()

    def change_source(*args: object, **kwargs: object) -> bytes:
        source.write_bytes(b"changed")
        return b""

    monkeypatch.setattr(loudness_module, "run", change_source)
    with pytest.raises(SourceChangedError, match="changed during loudness measurement"):
        measure_loudness(source)


def test_measure_normalization_gain_uses_processed_audio(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    known = measure_loudness(source)
    effects = Effects()

    expected = measure_normalization_gain(source, effects=effects, known=known)
    effects = effects.replace(gain_db=6)
    assert measure_normalization_gain(source, effects=effects, known=known) == expected
    effects = effects.replace(trim_start=0.2)
    assert isinstance(measure_normalization_gain(source, effects=effects, known=known), float)
    effects = effects.replace(trim_silence=True)
    assert isinstance(measure_normalization_gain(source, effects=effects), float)


def test_measure_normalization_gain_rejects_changed_source(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    def change_source(path: Path, **kwargs: object) -> Loudness:
        path.touch()
        return Loudness(lufs=-18, true_peak_db=-5)

    monkeypatch.setattr(loudness_module, "measure_loudness", change_source)
    with pytest.raises(SourceChangedError, match="Source audio changed"):
        measure_normalization_gain(source)


def test_measure_normalization_gain_rejects_all_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "silent.wav"
    source.touch()

    monkeypatch.setattr(silence_module, "trailing_silence_end", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(silence_module, "probe", lambda path, **kwargs: ONE_SECOND)

    with pytest.raises(SilentAudioError, match="no audible audio"):
        measure_normalization_gain(source, effects=Effects(trim_silence=True))


def test_measure_normalization_gain_reuses_known_loudness(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    known = measure_loudness(source)
    expected = measure_normalization_gain(source)

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("measure_loudness should not run")

    monkeypatch.setattr(loudness_module, "measure_loudness", unexpected)
    assert measure_normalization_gain(source, known=known) == expected


@pytest.mark.parametrize("fingerprint", [(0, 0, 0), None])
def test_measure_normalization_gain_ignores_stale_or_filtered_loudness(
    make_tone: Callable[..., None], tmp_path: Path, fingerprint: tuple[int, int, int] | None
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    stale = Loudness(lufs=-60, true_peak_db=-50, fingerprint=fingerprint)

    assert measure_normalization_gain(source, known=stale) == measure_normalization_gain(source)


def test_loudness_functions_respect_cancellation(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    with pytest.raises(CancelledError):
        measure_loudness(source, cancelled=lambda: True)
    with pytest.raises(CancelledError):
        measure_normalization_gain(source, cancelled=lambda: True)


def test_loudness_functions_accept_string_paths(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    assert measure_loudness(str(source)) == measure_loudness(source)
    assert measure_normalization_gain(str(source)) == measure_normalization_gain(source)
