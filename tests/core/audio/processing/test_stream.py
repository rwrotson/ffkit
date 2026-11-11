import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import (
    Track,
    audio_filters,
    render,
    stream_mp3,
)

stream_module = importlib.import_module("ffkit.core.audio.processing.stream")


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


def test_stream_renders_and_seeks(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
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


def test_stream_seeks_within_late_trim_interval(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    track = Track(path=str(source))
    track.effects.trim_end = 1.5
    track.effects.trim_start = 1.0
    assert b"".join(stream_mp3(track)).startswith(b"ID3")
    assert track.effects.trim_start == 1.0
    assert track.effects.trim_end == 1.5


def test_stream_stops_at_trim_end(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    track = Track(path=str(source))
    track.effects.trim_start = 0.2
    track.effects.trim_end = 0.5
    assert b"".join(stream_mp3(track, start=0.3)) == b""
    assert b"".join(stream_mp3(track, start=0.8)) == b""


def test_stream_uses_streaming_filters(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    track = Track(path=str(source))
    track.effects.trim_silence = True
    original = audio_filters

    def check_filters(
        current: Track, gain: float, *, streaming: bool, limiter_db: float | None
    ) -> list[str]:
        assert streaming is True
        filters = original(current, gain, streaming=streaming, limiter_db=limiter_db)
        assert "areverse" not in filters
        return filters

    monkeypatch.setattr(stream_module, "audio_filters", check_filters)
    assert b"".join(stream_mp3(track))


def test_stream_reports_failed_encoder_and_closes_early(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    missing = Track(path=str(tmp_path / "missing.wav"))
    with pytest.raises(RuntimeError, match="Audio encoder exited"):
        b"".join(stream_mp3(missing))

    source = tmp_path / "source.wav"
    make_tone(source)
    stream = stream_mp3(Track(path=str(source)))
    assert next(stream)
    stream.close()


def test_stream_rejects_negative_start_on_call(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        stream_mp3(Track(path=str(tmp_path / "source.wav")), start=-1)


def test_stream_seek_keeps_pause_with_trim_silence(tmp_path: Path) -> None:
    source = tmp_path / "pause.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-filter_complex",
            "[0][1][2]concat=n=3:v=0:a=1",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-y",
            str(source),
        ],
        check=True,
    )

    track = Track(path=str(source))
    track.effects.trim_silence = True
    plain = Track(path=str(source))

    seeked = len(pcm(b"".join(stream_mp3(track, start=1.2))))
    expected = len(pcm(b"".join(stream_mp3(plain, start=1.2))))
    assert abs(seeked - expected) < 12000
