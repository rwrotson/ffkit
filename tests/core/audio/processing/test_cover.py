import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from ffkit import (
    Track,
    extract_cover,
    render,
)


def test_extract_cover_custom_missing_and_removed(
    make_tone: Callable[..., None], tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
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


def test_extract_cover_timeout_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cover.jpg"

    def time_out(command: list[str], **kwargs: object) -> None:
        timeout = kwargs["timeout"]
        assert isinstance(timeout, (int, float))
        assert timeout > 0
        Path(command[-1]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(command, timeout)

    target.write_bytes(b"previous cover")
    monkeypatch.setattr("ffkit.core.audio.processing.cover.subprocess.run", time_out)

    with pytest.raises(subprocess.TimeoutExpired):
        extract_cover(Track(path="source.mp3"), target)
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

    track = Track(path=str(source), cover_path=str(image))
    encoded = tmp_path / "with-cover.mp3"
    render(track, encoded)

    embedded = Track(path=str(encoded))
    original_mp3 = encoded.read_bytes()
    alias = tmp_path / "alias.mp3"
    alias.symlink_to(encoded)
    for destination in (encoded, alias):
        with pytest.raises(ValueError, match="Output path must differ"):
            extract_cover(embedded, destination)
    assert encoded.read_bytes() == original_mp3

    target = tmp_path / "embedded.jpg"
    assert extract_cover(embedded, target) == target
    assert target.is_file()

    original = target.read_bytes()
    target.write_bytes(b"stale cover")
    assert extract_cover(embedded, target) == target
    assert target.read_bytes() == original

    assert extract_cover(Track(path=str(source)), target) is None
    assert target.read_bytes() == original
