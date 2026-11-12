import importlib
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pytest

from ffkit import (
    CancelledError,
    Effects,
    FFmpegRuntime,
    Group,
    Track,
    audio_filters,
    measure_loudness,
    probe,
    render,
)
from ffkit.core._process import ERROR_TAIL_LIMIT

render_module = importlib.import_module("ffkit.core.audio.processing.render")


def test_render_protects_source_and_existing_output(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    alias = tmp_path / "alias.wav"
    alias.symlink_to(source)

    with pytest.raises(FileNotFoundError):
        render(Track(path=str(tmp_path / "missing.wav")), tmp_path / "out.mp3")
    for destination in (source, alias):
        with pytest.raises(ValueError, match="Output path must differ"):
            render(Track(path=str(source)), destination)

    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"invalid")
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    with pytest.raises(subprocess.CalledProcessError):
        render(Track(path=str(broken)), target)
    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob("*.tmp.mp3"))


def test_render_mp3_with_trim_tags_and_gain(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    track = Track(path=str(source), tags={"title": "New", "artist": "Me", "ignored": "x"})
    track.effects.trim_start = 0.2
    track.effects.trim_end = 0.8
    track.effects.gain_db = 2

    target = tmp_path / "nested" / "out.mp3"
    render(track, target, group_gain_db=1)

    output = probe(target)
    assert output.duration is not None
    assert 0.5 < output.duration < 0.8
    assert output.tags["title"] == "New"
    assert output.tags["artist"] == "Me"
    assert not list(target.parent.glob("*.tmp.mp3"))


def test_render_relative_colon_path_and_tag_overrides(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("Song: Live.wav")
    make_tone(tmp_path / source, duration=1)
    track = Track(path=str(source), tags={"album_artist": "Band", "comment": "kept"})

    target = Path("Out: Live.mp3")
    render(track, target)

    output = probe(target)
    assert output.duration is not None
    assert output.tags["album_artist"] == "Band"
    assert output.tags["comment"] == "kept"


def test_render_trims_edges_without_reversing_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    track = Track(path=str(source))
    track.effects.trim_start = 0.5
    track.effects.trim_end = 4.5
    track.effects.trim_silence = True

    def checked_filters(current: Effects, gain: float, *, streaming: bool) -> list[str]:
        assert streaming is True
        filters = audio_filters(current, gain, streaming=streaming)
        assert "areverse" not in filters
        return filters

    monkeypatch.setattr(render_module, "audio_filters", checked_filters)

    target = tmp_path / "trimmed.mp3"
    render(track, target)

    duration = probe(target).duration
    assert duration is not None
    assert 2.9 < duration < 3.2


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

    track = Track(path=str(source))
    track.effects.trim_silence = True

    with pytest.raises(ValueError, match="no audible audio"):
        render(track, tmp_path / "out.mp3")


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

    track = Track(path=str(source))
    track.effects.trim_silence = True

    target = tmp_path / "rendered.mp3"
    render(track, target)

    duration = probe(target).duration
    assert duration is not None
    assert 2.0 < duration < 2.15


def test_render_limiter_checks_encoded_peak(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "loud.wav"
    make_tone(source, duration=1, gain=12)
    track = Track(path=str(source))
    track.effects.gain_db = 6
    group = Group(name="Mix", tracks=[track])

    target = tmp_path / "limited.mp3"
    render(track, target, limiter_db=group.limiter_for(track))

    _, peak = measure_loudness(target)
    assert peak is not None
    assert peak <= -0.99


def test_render_retries_from_source(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    measured = iter([(None, 0.0), (None, -2.0)])
    monkeypatch.setattr(render_module, "measure_loudness", lambda path, **kwargs: next(measured))
    original_popen = subprocess.Popen
    commands: list[list[str]] = []

    def record(command: list[str], *, stdout: int, stderr: BinaryIO) -> subprocess.Popen[bytes]:
        commands.append(command)
        return original_popen(command, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "Popen", record)

    render(Track(path=str(source)), target, limiter_db=-1)
    assert len(commands) == 2
    assert all(str(source) in command for command in commands)
    assert target.exists()

    target.write_bytes(b"existing")
    monkeypatch.setattr(render_module, "measure_loudness", lambda path, **kwargs: (None, 0.0))
    with pytest.raises(RuntimeError, match="exceeds"):
        render(Track(path=str(source)), target, limiter_db=-1)
    assert target.read_bytes() == b"existing"


@pytest.mark.parametrize("cancelled", [None, lambda: False])
def test_render_keeps_only_error_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: Callable[[], bool] | None
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    original_popen = subprocess.Popen

    def noisy_process(
        _command: list[str], *, stdout: int, stderr: BinaryIO
    ) -> subprocess.Popen[bytes]:
        return original_popen(
            [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000); sys.exit(7)"],
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(subprocess, "Popen", noisy_process)

    with pytest.raises(subprocess.CalledProcessError) as error:
        render(Track(path=str(source)), tmp_path / "out.mp3", cancelled=cancelled)
    assert error.value.returncode == 7
    assert len(error.value.stderr) == ERROR_TAIL_LIMIT


def test_render_encoder_timeout_kills_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    original_popen = subprocess.Popen

    def slow_process(
        _command: list[str], *, stdout: int, stderr: BinaryIO
    ) -> subprocess.Popen[bytes]:
        return original_popen(
            [sys.executable, "-c", "import time; time.sleep(10)"], stdout=stdout, stderr=stderr
        )

    monkeypatch.setattr(subprocess, "Popen", slow_process)
    with pytest.raises(subprocess.TimeoutExpired):
        render(
            Track(path=str(source)),
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

    track = Track(path=str(source), cover_path=str(cover))
    with_cover = tmp_path / "with-cover.mp3"
    render(track, with_cover)
    assert with_cover.exists()

    track.cover_removed = True
    without_cover = tmp_path / "without-cover.mp3"
    render(track, without_cover)
    assert without_cover.exists()
    assert with_cover.stat().st_size > without_cover.stat().st_size


def test_render_cancellation_preserves_output(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    class PendingProcess:
        returncode = 0
        stdout = None
        stderr = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: PendingProcess())
    with pytest.raises(CancelledError, match="Export cancelled"):
        render(Track(path=str(source)), target, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"


def test_render_rejects_unmeasurable_or_unreachable_peak(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    monkeypatch.setattr(render_module, "measure_loudness", lambda path, **kwargs: (None, None))
    with pytest.raises(RuntimeError, match="Could not measure encoded true peak"):
        render(Track(path=str(source)), target, limiter_db=-1)
    assert target.read_bytes() == b"existing"

    monkeypatch.setattr(render_module, "measure_loudness", lambda path, **kwargs: (None, 30.0))
    with pytest.raises(RuntimeError, match="ceiling could not be reached"):
        render(Track(path=str(source)), target, limiter_db=-1)
    assert target.read_bytes() == b"existing"


def test_render_cancellation_after_encoding(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    class CompletedProcess:
        returncode = 0
        stdout = None
        stderr = None

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: CompletedProcess())
    with pytest.raises(CancelledError, match="Export cancelled"):
        render(Track(path=str(source)), target, limiter_db=-1, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"


def test_render_cancellation_before_replace_without_limiter(
    make_tone: Callable[..., None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source, duration=1)
    target = tmp_path / "out.mp3"
    target.write_bytes(b"existing")

    class CompletedProcess:
        returncode = 0
        stdout = None
        stderr = None

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: CompletedProcess())
    with pytest.raises(CancelledError, match="Export cancelled"):
        render(Track(path=str(source)), target, cancelled=lambda: True)
    assert target.read_bytes() == b"existing"
