import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import FFmpegProcessError, NoAudioError, SourceNotFoundError
from ffkit.audio import detect_trim_bounds, estimate_tempo, measure_loudness, probe, render, stream

STREAM = {"codec_type": "audio", "codec_name": "pcm_s16le", "sample_rate": "44100", "channels": 1}


def test_probe_reads_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    info = probe(source)

    assert 1.9 < info.duration < 2.1
    assert info.sample_rate == 44100
    assert info.channels == 1
    assert info.codec == "pcm_s16le"
    assert info.bit_rate == 705600
    assert not info.has_cover


def test_probe_reads_audio_stream_tags(tmp_path: Path) -> None:
    source = tmp_path / "stream-tags.mka"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:a",
            "flac",
            "-metadata:s:a:0",
            "title=Stream title",
            "-y",
            str(source),
        ],
        check=True,
    )

    assert probe(source).tags["title"] == "Stream title"


def test_probe_tag_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    report = {
        "streams": [{**STREAM, "tags": {"TITLE": "Stream", "ARTIST": "Singer"}}],
        "format": {"duration": "1", "tags": {"title": "Container", "album": "Album"}},
    }
    result = json.dumps(report).encode()
    monkeypatch.setattr("ffkit.audio.analysis.probe.run", lambda *args, **kwargs: result)

    tags = probe(source).tags
    assert tags == {"title": "Stream", "artist": "Singer", "album": "Album"}


def test_probe_missing_and_bad_audio(tmp_path: Path) -> None:
    with pytest.raises(SourceNotFoundError):
        probe(tmp_path / "missing.wav")

    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"invalid")
    with pytest.raises(FFmpegProcessError):
        probe(broken)
    with pytest.raises(FFmpegProcessError):
        detect_trim_bounds(broken)


def test_probe_rejects_missing_audio_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"x")
    result = json.dumps({"streams": [{"codec_type": "video"}], "format": {}}).encode()
    monkeypatch.setattr("ffkit.audio.analysis.probe.run", lambda *args, **kwargs: result)

    with pytest.raises(NoAudioError, match="no decodable audio"):
        probe(source)


def test_probe_rejects_zero_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "zero.wav"
    source.write_bytes(b"x")
    result = json.dumps({"streams": [STREAM], "format": {"duration": "0"}}).encode()
    monkeypatch.setattr("ffkit.audio.analysis.probe.run", lambda *args, **kwargs: result)

    with pytest.raises(NoAudioError, match="measurable audio duration"):
        probe(source)


def test_probe_reports_embedded_cover(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    image = tmp_path / "cover.png"
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
    target = tmp_path / "with-cover.mp3"
    render(source, target, cover=image)

    info = probe(target)

    assert info.has_cover
    assert info.codec == "mp3"
    assert info.bit_rate == 320000


@pytest.mark.parametrize(
    "stream",
    [
        {"codec_type": "audio", "channels": 1},
        {"codec_type": "audio", "sample_rate": "0", "channels": 1},
        {"codec_type": "audio", "sample_rate": "unknown", "channels": 1},
    ],
)
def test_probe_rejects_stream_without_sample_rate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stream: dict[str, object],
) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    report = {"streams": [stream], "format": {"duration": "1"}}
    monkeypatch.setattr(
        "ffkit.audio.analysis.probe.run",
        lambda *args, **kwargs: json.dumps(report).encode(),
    )

    with pytest.raises(NoAudioError, match="no decodable audio"):
        probe(source)


def _image(path: Path) -> Path:
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
            str(path),
        ],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda source, tmp: measure_loudness(source), id="measure_loudness"),
        pytest.param(lambda source, tmp: estimate_tempo(source), id="estimate_tempo"),
        pytest.param(lambda source, tmp: render(source, tmp / "out.mp3"), id="render"),
        pytest.param(lambda source, tmp: b"".join(stream(source)), id="stream"),
    ],
)
def test_source_without_audio_raises_no_audio_error(
    operation: Callable[[Path, Path], object],
    tmp_path: Path,
) -> None:
    source = _image(tmp_path / "image.png")

    with pytest.raises(NoAudioError):
        operation(source, tmp_path)


def test_unreadable_source_keeps_ffmpeg_error(tmp_path: Path) -> None:
    source = tmp_path / "broken.mp3"
    source.write_bytes(b"not audio")

    with pytest.raises(FFmpegProcessError) as error:
        measure_loudness(source)
    assert not isinstance(error.value, NoAudioError)
