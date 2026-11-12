import os
from pathlib import Path
from uuid import uuid4

from ffkit.core.audio.analysis.cover import embedded_cover
from ffkit.core.audio.models import Track
from ffkit.core.runtime import FFmpegRuntime


def extract_cover(
    track: Track, destination: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()
) -> Path | None:
    """Return a custom cover or atomically extract the first embedded image as JPEG."""
    if track.cover_removed:
        return None
    if track.cover_path:
        cover = Path(track.cover_path)
        return cover if cover.is_file() else None

    source = Path(track.path)
    if source.resolve() == destination.resolve() or (
        source.exists() and destination.exists() and source.samefile(destination)
    ):
        raise ValueError("Output path must differ from source audio")

    image = embedded_cover(track, runtime=runtime)
    if image is None:
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.jpg")
    try:
        temporary.write_bytes(image)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
