import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import FFmpegProcessError, NoAudioError, SourceNotFoundError
from ffkit.audio import detect_trim_bounds, probe


def test_probe_reads_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    info = probe(source)

    assert 1.9 < info.duration < 2.1


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
        "streams": [{"codec_type": "audio", "tags": {"TITLE": "Stream", "ARTIST": "Singer"}}],
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
    with pytest.raises(NoAudioError, match="duration"):
        detect_trim_bounds(broken, duration=0)


def test_probe_rejects_missing_audio_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    result = json.dumps(
        {"streams": [{"codec_type": "audio"}], "format": {"duration": "0"}}
    ).encode()
    monkeypatch.setattr("ffkit.audio.analysis.probe.run", lambda *args, **kwargs: result)

    with pytest.raises(NoAudioError, match="measurable audio duration"):
        probe(source)
