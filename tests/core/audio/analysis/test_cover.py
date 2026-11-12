import subprocess
from collections.abc import Callable
from pathlib import Path

from ffkit import Track, embedded_cover, render


def test_embedded_cover_without_image(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)

    assert embedded_cover(source) is None
    assert embedded_cover(tmp_path / "missing.mp3") is None


def test_embedded_cover_reads_jpeg_bytes(make_tone: Callable[..., None], tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_tone(source)
    image = tmp_path / "cover.png"
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
    encoded = tmp_path / "with-cover.mp3"
    render(Track(path=str(source), cover_path=str(image)), encoded)

    cover = embedded_cover(encoded)

    assert cover is not None
    assert cover.startswith(b"\xff\xd8")
