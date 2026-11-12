import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import FFmpegProcessError, InvalidInputError
from ffkit.audio import Effects, render, stream
from ffkit.audio._filters import audio_filters

stream_module = importlib.import_module("ffkit.audio.processing.stream")


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
    effects = Effects(trim_start=0.2, trim_end=1.5, gain_db=2)

    rendered = tmp_path / "rendered.mp3"
    render(source, rendered, effects=effects)

    streamed = b"".join(stream(source, effects=effects))
    assert streamed.startswith(b"ID3")
    assert abs(len(pcm(streamed)) - len(pcm(rendered.read_bytes()))) < 12000

    seeked = b"".join(stream(source, effects=effects, start=0.7))
    assert seeked.startswith(b"ID3")
    assert len(pcm(seeked)) < len(pcm(rendered.read_bytes()))


def test_stream_seeks_within_late_trim_interval(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    effects = Effects(trim_start=1.0, trim_end=1.5)
    assert b"".join(stream(source, effects=effects)).startswith(b"ID3")


def test_stream_stops_at_trim_end(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    effects = Effects(trim_start=0.2, trim_end=0.5)
    assert b"".join(stream(source, effects=effects, start=0.3)) == b""
    assert b"".join(stream(source, effects=effects, start=0.8)) == b""


def test_stream_uses_streaming_filters(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    effects = Effects(trim_silence=True)
    original = audio_filters

    def check_filters(current: Effects, *, streaming: bool) -> list[str]:
        assert streaming is True
        filters = original(current, streaming=streaming)
        assert "areverse" not in filters
        return filters

    monkeypatch.setattr(stream_module, "audio_filters", check_filters)
    assert b"".join(stream(source, effects=effects))


def test_stream_reports_failed_encoder_and_closes_early(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    with pytest.raises(FFmpegProcessError):
        b"".join(stream(tmp_path / "missing.wav"))

    source = tmp_path / "source.wav"
    make_tone(source)
    chunks = stream(source)
    assert next(chunks)
    chunks.close()


def test_stream_rejects_negative_start_on_call(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="must not be negative"):
        stream(tmp_path / "source.wav", start=-1)


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

    effects = Effects(trim_silence=True)
    plain_effects = Effects()

    seeked = len(pcm(b"".join(stream(source, effects=effects, start=1.2))))
    expected = len(pcm(b"".join(stream(source, effects=plain_effects, start=1.2))))
    assert abs(seeked - expected) < 12000
