from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import SourceNotFoundError
from ffkit.audio import (
    AudioInfo,
    detect_trim_bounds,
    embedded_cover,
    estimate_tempo,
    extract_cover,
    measure_loudness,
    measure_normalization_gain,
    probe,
    render,
    stream,
    waveform,
)

INFO = AudioInfo(duration=1.0, sample_rate=44100, channels=1, codec="pcm_s16le")

calls: list[Callable[[Path, Path], object]] = [
    lambda source, _: probe(source),
    lambda source, _: measure_loudness(source),
    lambda source, _: measure_normalization_gain(source),
    lambda source, _: detect_trim_bounds(source),
    lambda source, _: detect_trim_bounds(source, info=INFO),
    lambda source, _: waveform(source),
    lambda source, _: estimate_tempo(source),
    lambda source, _: embedded_cover(source),
    lambda source, out: extract_cover(source, out / "cover.jpg"),
    lambda source, out: render(source, out / "out.mp3"),
    lambda source, _: stream(source),
]


@pytest.mark.parametrize("call", calls)
def test_missing_source_raises_source_not_found(
    call: Callable[[Path, Path], object],
    tmp_path: Path,
) -> None:
    with pytest.raises(SourceNotFoundError, match="Input file not found"):
        call(tmp_path / "missing.wav", tmp_path)
