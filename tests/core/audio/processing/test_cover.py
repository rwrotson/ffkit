import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import extract_cover, render


def test_extract_cover_without_image(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    target = tmp_path / "covers" / "embedded.jpg"

    assert extract_cover(source, target) is None
    assert not target.exists()


def test_extract_cover_timeout_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cover.jpg"

    def time_out(command: list[str], **kwargs: object) -> None:
        timeout = kwargs["timeout"]
        assert isinstance(timeout, (int, float))
        assert timeout > 0
        raise subprocess.TimeoutExpired(command, timeout)

    target.write_bytes(b"previous cover")
    monkeypatch.setattr("ffkit.core.audio.analysis.cover.subprocess.run", time_out)

    with pytest.raises(subprocess.TimeoutExpired):
        extract_cover(Path("source.mp3"), target)
    assert target.read_bytes() == b"previous cover"
    assert not list(tmp_path.glob("*.tmp.jpg"))


def test_extract_cover_write_failure_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cover.jpg"
    target.write_bytes(b"previous cover")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(
        "ffkit.core.audio.processing.cover.embedded_cover", lambda source, runtime: b"image"
    )
    monkeypatch.setattr("ffkit.core.audio.processing.cover.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        extract_cover(Path("source.mp3"), target)
    assert target.read_bytes() == b"previous cover"
    assert not list(tmp_path.glob("*.tmp.jpg"))


def test_extract_embedded_cover(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
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

    embedded = tmp_path / "with-cover.mp3"
    render(source, embedded, cover=image)
    original_mp3 = embedded.read_bytes()
    alias = tmp_path / "alias.mp3"
    alias.symlink_to(embedded)
    for destination in (embedded, alias):
        with pytest.raises(ValueError, match="Output path must differ"):
            extract_cover(embedded, destination)
    assert embedded.read_bytes() == original_mp3

    target = tmp_path / "embedded.jpg"
    assert extract_cover(embedded, target) == target
    assert target.is_file()

    original = target.read_bytes()
    target.write_bytes(b"stale cover")
    assert extract_cover(embedded, target) == target
    assert target.read_bytes() == original

    assert extract_cover(source, target) is None
    assert target.read_bytes() == original
