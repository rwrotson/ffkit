from pathlib import Path

import pytest

from ffkit import InvalidInputError, SourceNotFoundError
from ffkit._ffmpeg.args import (
    ensure_distinct,
    existing_file,
    ffmpeg_number,
    media_path,
    temporary_sibling,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "1.0"), (1e-5, "0.00001"), (2.5, "2.5"), (1e7, "10000000.0")],
)
def test_ffmpeg_number_uses_fixed_notation(value: float, expected: str) -> None:
    assert ffmpeg_number(value) == expected


def test_media_path_is_absolute(tmp_path: Path) -> None:
    assert media_path("a:b.wav") == str(tmp_path / "a:b.wav")


def test_existing_file_rejects_missing_paths_and_directories(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.touch()

    assert existing_file(str(source)) == source
    for path in (tmp_path / "missing.wav", tmp_path):
        with pytest.raises(SourceNotFoundError, match="Input file not found"):
            existing_file(path)


def test_ensure_distinct_detects_the_same_file(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    link = tmp_path / "link.wav"
    link.hardlink_to(source)

    ensure_distinct(source, tmp_path / "out.mp3")
    for destination in (source, Path("source.wav"), link):
        with pytest.raises(InvalidInputError, match="Output path must differ"):
            ensure_distinct(source, destination)


def test_temporary_sibling_is_unique_and_hidden(tmp_path: Path) -> None:
    destination = tmp_path / "out.mp3"

    first = temporary_sibling(destination, ".mp3")
    second = temporary_sibling(destination, ".mp3")

    assert first != second
    assert first.parent == tmp_path
    assert first.name.startswith(".out.")
    assert first.name.endswith(".tmp.mp3")
