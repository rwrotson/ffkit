import importlib
import subprocess
from pathlib import Path

import pytest

from ffkit import (
    Track,
    calculate_normalization_gain,
    extract_cover,
    measure_loudness,
    probe,
    render,
    stream_mp3,
)

normalization_module = importlib.import_module("ffkit.core.audio.normalization")


def tone(path: Path) -> None:
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-y",
            str(path),
        ],
        check=True,
    )


def pcm(data: bytes) -> bytes:
    return subprocess.run(
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "mp3",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "pipe:1",
        ],
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def test_stream_renders_and_seeks(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    tone(source)
    track = Track(path=str(source))
    track.effects.trim_start = 0.2
    track.effects.trim_end = 1.5
    track.effects.gain_db = 2
    rendered = tmp_path / "rendered.mp3"
    render(track, rendered)
    streamed = b"".join(stream_mp3(track))
    assert streamed.startswith(b"ID3")
    assert abs(len(pcm(streamed)) - len(pcm(rendered.read_bytes()))) < 12000
    seeked = b"".join(stream_mp3(track, start=0.7))
    assert seeked.startswith(b"ID3")
    assert len(pcm(seeked)) < len(pcm(rendered.read_bytes()))
    assert track.effects.trim_start == 0.2
    assert track.effects.trim_end == 1.5


def test_extract_cover_custom_missing_and_removed(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    tone(source)
    target = tmp_path / "covers" / "embedded.jpg"
    track = Track(path=str(source))
    assert extract_cover(track, target) is None
    assert not target.exists()
    custom = tmp_path / "custom.jpg"
    custom.write_bytes(b"custom")
    track.cover_path = str(custom)
    assert extract_cover(track, target) == custom
    track.cover_path = str(tmp_path / "missing.jpg")
    assert extract_cover(track, target) is None
    track.cover_removed = True
    assert extract_cover(track, target) is None


def test_extract_embedded_cover(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    tone(source)
    image = tmp_path / "cover.jpg"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32:d=0.1",
            "-frames:v",
            "1",
            "-y",
            str(image),
        ],
        check=True,
    )
    track = Track(path=str(source), cover_path=str(image))
    encoded = tmp_path / "with-cover.mp3"
    render(track, encoded)
    embedded = Track(path=str(encoded))
    target = tmp_path / "embedded.jpg"
    assert extract_cover(embedded, target) == target
    assert target.is_file()
    assert extract_cover(embedded, target) == target


def test_calculate_normalization_gain_uses_processed_audio(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    tone(source)
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


def test_calculate_normalization_gain_rejects_changed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    tone(source)
    track = Track(path=str(source))

    def change_source(path: Path, filters: list[str]) -> tuple[float, float]:
        path.touch()
        return -18, -5

    monkeypatch.setattr(normalization_module, "measure_loudness", change_source)
    with pytest.raises(ValueError, match="Source audio changed"):
        calculate_normalization_gain(track)


def test_stream_reports_failed_encoder_and_closes_early(tmp_path: Path) -> None:
    missing = Track(path=str(tmp_path / "missing.wav"))
    with pytest.raises(RuntimeError, match="Audio encoder exited"):
        b"".join(stream_mp3(missing))
    source = tmp_path / "source.wav"
    tone(source)
    stream = stream_mp3(Track(path=str(source)))
    assert next(stream)
    stream.close()
