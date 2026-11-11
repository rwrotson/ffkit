import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import (
    Track,
    detect_trim_bounds,
    probe,
)


def test_probe_reads_real_audio(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    track = probe(Track(path=str(source), tags={"title": "Custom"}))
    assert track.duration is not None
    assert 1.9 < track.duration < 2.1
    assert track.tags["title"] == "Custom"
    assert track.error is None


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
    assert probe(Track(path=str(source))).tags["title"] == "Stream title"


def test_probe_tag_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    report = {
        "streams": [{"codec_type": "audio", "tags": {"TITLE": "Stream", "ARTIST": "Singer"}}],
        "format": {"duration": "1", "tags": {"title": "Container", "album": "Album"}},
    }
    result = subprocess.CompletedProcess([], 0, stdout=json.dumps(report))
    monkeypatch.setattr(
        "ffkit.core.audio.analysis.probe.subprocess.run", lambda *args, **kwargs: result
    )
    tags = probe(Track(path=str(source), tags={"artist": "Custom"})).tags
    assert tags == {"title": "Stream", "artist": "Custom", "album": "Album"}


def test_reprobe_refreshes_source_tags_and_keeps_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    reports = iter(
        [
            {"title": "Old", "artist": "Artist", "album": "Old album"},
            {"title": "New", "artist": "New artist", "genre": "Rock"},
            {"title": "Latest", "artist": "Final artist"},
        ]
    )

    def fake_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        report = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "1", "tags": next(reports)},
        }
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(report))

    monkeypatch.setattr("ffkit.core.audio.analysis.probe.subprocess.run", fake_probe)
    track = Track(path=str(source), tags={"artist": "Artist"})
    probe(track)
    assert track.tags == {"title": "Old", "artist": "Artist", "album": "Old album"}
    track.tags["genre"] = "Custom genre"
    probe(track)
    assert track.tags == {"title": "New", "artist": "Artist", "genre": "Custom genre"}
    del track.tags["artist"]
    track.tags["title"] = "Edited title"
    probe(track)
    assert track.tags == {
        "title": "Edited title",
        "artist": "Final artist",
        "genre": "Custom genre",
    }


def test_reprobe_after_json_round_trip_refreshes_source_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    titles = iter(("Old", "New"))

    def fake_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        report = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "1", "tags": {"title": next(titles), "artist": "Source"}},
        }
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(report))

    monkeypatch.setattr("ffkit.core.audio.analysis.probe.subprocess.run", fake_probe)
    original = probe(Track(path=str(source), tags={"artist": "Custom"}))
    restored = Track.model_validate_json(original.model_dump_json())
    probe(restored)
    assert restored.tags == {"title": "New", "artist": "Custom"}


def test_probe_missing_and_bad_audio(tmp_path: Path) -> None:
    missing = probe(Track(path=str(tmp_path / "missing.wav")))
    assert missing.error == "Source file is missing"
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"invalid")
    with pytest.raises(subprocess.CalledProcessError):
        probe(Track(path=str(broken)))
    with pytest.raises(ValueError, match="duration"):
        detect_trim_bounds(broken, duration=0)


def test_probe_rejects_missing_audio_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"x")
    result = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps({"streams": [{"codec_type": "video"}], "format": {}})
    )
    monkeypatch.setattr(
        "ffkit.core.audio.analysis.probe.subprocess.run", lambda *args, **kwargs: result
    )
    with pytest.raises(ValueError, match="no decodable audio"):
        probe(Track(path=str(source)))


def test_probe_rejects_zero_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "zero.wav"
    source.write_bytes(b"x")
    result = subprocess.CompletedProcess(
        [],
        0,
        stdout=json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "0"}}),
    )
    monkeypatch.setattr(
        "ffkit.core.audio.analysis.probe.subprocess.run", lambda *args, **kwargs: result
    )
    with pytest.raises(ValueError, match="measurable audio duration"):
        probe(Track(path=str(source)))
