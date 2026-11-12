from pathlib import Path

from ffkit import audio_files, safe_name


def test_safe_name_uses_tags_and_utf8_limit() -> None:
    song = Path("song.flac")
    assert safe_name(song, {"artist": "A/B", "title": "T:Q"}, 0, 2) == "01. A_B - T_Q.mp3"
    assert safe_name(song, {}, 1, 2) == "02. song.mp3"
    assert safe_name(song, {"title": "."}, 0, 1) == "1. Untitled.mp3"
    assert len(safe_name(song, {"title": "é" * 200}, 0, 1).encode()) <= 255


def test_audio_files_resolves_deduplicates_and_sorts(tmp_path: Path) -> None:
    folder = tmp_path / "music"
    folder.mkdir()
    one = folder / "one.FLAC"
    two = folder / "two.mp3"
    ignored = folder / "note.txt"
    for path in (one, two, ignored):
        path.write_bytes(b"x")
    found = audio_files([folder, one, tmp_path / "missing.mp3", ignored])
    assert found == [one, two]


def test_audio_files_skip_hidden_files(tmp_path: Path) -> None:
    visible = tmp_path / "song.mp3"
    hidden = [tmp_path / "._song.mp3", tmp_path / ".song.0123.tmp.mp3"]
    for path in (visible, *hidden):
        path.write_bytes(b"x")
    assert audio_files([tmp_path, *hidden]) == [visible]
