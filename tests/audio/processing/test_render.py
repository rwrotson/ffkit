import importlib
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from ffkit import (
    CancelledError,
    FFmpegError,
    FFmpegProcessError,
    FFmpegRuntime,
    FFmpegTimeoutError,
    InvalidInputError,
    PeakCeilingError,
    SilentAudioError,
    SourceNotFoundError,
)
from ffkit._ffmpeg.process import ERROR_TAIL_LIMIT, iter_output
from ffkit.audio import (
    Effects,
    Loudness,
    Mp3Encoding,
    measure_loudness,
    probe,
    render,
    stream,
)
from ffkit.audio._filters import audio_filters

render_module = importlib.import_module("ffkit.audio.processing.render")

LIMITED = Effects(limiter_ceiling_db=-1)


def _replace_command(monkeypatch: pytest.MonkeyPatch, command: list[str]) -> None:
    """Run another command in place of the FFmpeg encoder."""

    def replaced(_command: Sequence[str], **kwargs: Any) -> Iterator[bytes]:  # noqa: ANN401
        return iter_output(command, **kwargs)

    monkeypatch.setattr(render_module, "iter_output", replaced)


def test_render_protects_source_and_existing_output(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    alias = tmp_path / "alias.wav"
    alias.symlink_to(source)

    with pytest.raises(SourceNotFoundError):
        render(tmp_path / "missing.wav", tmp_path / "out.mp3")
    for destination in (source, alias):
        with pytest.raises(InvalidInputError, match="Output path must differ"):
            render(source, destination)

    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"invalid")
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    with pytest.raises(FFmpegProcessError):
        render(broken, target)
    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob("*.tmp.mp3"))


def test_render_mp3_with_trim_tags_and_gain(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    effects = Effects(trim_start=0.2, trim_end=0.8, gain_db=3)

    target = tmp_path / "nested" / "out.mp3"
    render(source, target, effects=effects, tags={"title": "New", "artist": "Me"})

    output = probe(target)
    assert output.duration is not None
    assert 0.5 < output.duration < 0.8
    assert output.tags["title"] == "New"
    assert output.tags["artist"] == "Me"
    assert not list(target.parent.glob("*.tmp.mp3"))


def test_render_relative_colon_path_and_tags(
    make_tone: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("Song: Live.wav")
    make_tone(tmp_path / source, duration=1)
    target = Path("Out: Live.mp3")
    render(source, target, tags={"album_artist": "Band", "comment": "kept"})

    output = probe(target)
    assert output.duration is not None
    assert output.tags["album_artist"] == "Band"
    assert output.tags["comment"] == "kept"


def test_render_trims_edges_without_reversing_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "edges.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-filter_complex",
            "[0:a][1:a][0:a][1:a][0:a]concat=n=5:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )
    effects = Effects(trim_start=0.5, trim_end=4.5, trim_silence=True)

    def checked_filters(current: Effects) -> list[str]:
        assert not current.trim_silence
        return audio_filters(current)

    monkeypatch.setattr(render_module, "audio_filters", checked_filters)

    target = tmp_path / "trimmed.mp3"
    render(source, target, effects=effects)

    duration = probe(target).duration
    assert duration is not None
    # 3 s of audio plus 0.05 s of padding at each edge.
    assert 3.05 < duration < 3.2


def test_render_rejects_all_silence_with_trim(tmp_path: Path) -> None:
    source = tmp_path / "silent.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-y",
            str(source),
        ],
        check=True,
    )

    effects = Effects(trim_silence=True)

    with pytest.raises(SilentAudioError, match="no audible audio"):
        render(source, tmp_path / "out.mp3", effects=effects)


def test_render_keeps_short_audible_tail_after_pause(tmp_path: Path) -> None:
    source = tmp_path / "audible-tail.wav"
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
            "aevalsrc=0.1:s=44100:d=0.05",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )

    effects = Effects(trim_silence=True)

    target = tmp_path / "rendered.mp3"
    render(source, target, effects=effects)

    duration = probe(target).duration
    assert duration is not None
    assert 2.0 < duration < 2.15


def test_render_limiter_checks_encoded_peak(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "loud.wav"
    make_tone(source, duration=1, gain=12)
    effects = Effects(gain_db=6, limiter_ceiling_db=-1)

    target = tmp_path / "limited.mp3"
    render(source, target, effects=effects)

    peak = measure_loudness(target).true_peak_db
    assert peak is not None
    assert peak <= -0.99


def test_render_retries_from_source(
    make_tone: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    measured = iter([Loudness(lufs=None, true_peak_db=0.0), Loudness(lufs=None, true_peak_db=-2.0)])
    monkeypatch.setattr(render_module, "measure_loudness", lambda path, **kwargs: next(measured))
    commands: list[Sequence[str]] = []

    def record(command: Sequence[str], **kwargs: Any) -> Iterator[bytes]:  # noqa: ANN401
        commands.append(command)
        return iter_output(command, **kwargs)

    monkeypatch.setattr(render_module, "iter_output", record)

    render(source, target, effects=LIMITED)
    assert len(commands) == 2
    assert all(str(source) in command for command in commands)
    assert target.exists()

    target.write_bytes(b"existing")
    monkeypatch.setattr(
        render_module,
        "measure_loudness",
        lambda path, **kwargs: Loudness(lufs=None, true_peak_db=0.0),
    )
    with pytest.raises(PeakCeilingError, match="exceeds"):
        render(source, target, effects=LIMITED)
    assert target.read_bytes() == b"existing"


@pytest.mark.parametrize("cancelled", [None, lambda: False])
def test_render_keeps_only_error_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: Callable[[], bool] | None,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    _replace_command(
        monkeypatch,
        [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000); sys.exit(7)"],
    )

    with pytest.raises(FFmpegProcessError) as error:
        render(source, tmp_path / "out.mp3", cancelled=cancelled)
    assert error.value.returncode == 7
    assert len(error.value.stderr) == ERROR_TAIL_LIMIT


def test_render_encoder_timeout_kills_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    _replace_command(monkeypatch, [sys.executable, "-c", "import time; time.sleep(10)"])
    with pytest.raises(FFmpegTimeoutError):
        render(
            source,
            tmp_path / "out.mp3",
            runtime=FFmpegRuntime(process_timeout=0.2),
        )

    assert not list(tmp_path.glob("*.tmp.mp3"))


def test_render_cover_choices(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source, duration=1)
    cover = tmp_path / "cover.jpg"
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
            str(cover),
        ],
        check=True,
    )

    with_cover = tmp_path / "with-cover.mp3"
    render(source, with_cover, cover=cover)
    assert with_cover.exists()

    kept_cover = tmp_path / "kept-cover.mp3"
    render(with_cover, kept_cover)
    without_cover = tmp_path / "without-cover.mp3"
    render(with_cover, without_cover, cover=False)
    assert kept_cover.stat().st_size > without_cover.stat().st_size

    with pytest.raises(SourceNotFoundError):
        render(source, tmp_path / "missing-cover.mp3", cover=tmp_path / "missing.jpg")


def test_render_cancellation_preserves_output(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    with pytest.raises(CancelledError, match="Operation cancelled"):
        render(source, target, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"


def test_render_rejects_unmeasurable_or_unreachable_peak(
    make_tone: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    monkeypatch.setattr(
        render_module,
        "measure_loudness",
        lambda path, **kwargs: Loudness(lufs=None, true_peak_db=None),
    )
    with pytest.raises(FFmpegError, match="Could not measure encoded true peak"):
        render(source, target, effects=LIMITED)
    assert target.read_bytes() == b"existing"

    monkeypatch.setattr(
        render_module,
        "measure_loudness",
        lambda path, **kwargs: Loudness(lufs=None, true_peak_db=30.0),
    )
    with pytest.raises(PeakCeilingError, match="ceiling could not be reached"):
        render(source, target, effects=LIMITED)
    assert target.read_bytes() == b"existing"


def test_render_cancellation_after_encoding(
    make_tone: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    # Encoding finishes without output; cancellation is noticed afterwards.
    monkeypatch.setattr(render_module, "iter_output", lambda *args, **kwargs: iter(()))

    with pytest.raises(CancelledError, match="Operation cancelled"):
        render(source, target, effects=LIMITED, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"


def test_render_cancellation_before_replace_without_limiter(
    make_tone: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    # Encoding finishes without output; cancellation is noticed afterwards.
    monkeypatch.setattr(render_module, "iter_output", lambda *args, **kwargs: iter(()))

    with pytest.raises(CancelledError, match="Operation cancelled"):
        render(source, target, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"


def test_render_and_stream_accept_string_paths(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"

    render(str(source), str(target), cover=False)

    assert probe(str(target)).codec == "mp3"
    assert b"".join(stream(str(source))).startswith(b"ID3")


def test_render_and_stream_use_encoding(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"

    render(source, target, cover=False, encoding=Mp3Encoding(bitrate_kbps=96))
    streamed = b"".join(stream(source, encoding=Mp3Encoding(bitrate_kbps=96)))

    assert probe(target).bit_rate == 96000
    assert len(streamed) < len(b"".join(stream(source)))
