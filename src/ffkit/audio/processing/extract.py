import os
from pathlib import Path
from uuid import uuid4

from ffkit.audio.analysis.cover import embedded_cover
from ffkit.runtime import FFmpegRuntime


def extract_cover(
    source: Path, destination: Path, *, runtime: FFmpegRuntime = FFmpegRuntime()
) -> Path | None:
    """Atomically extract the first embedded image as JPEG; return None when there is none."""
    if source.resolve() == destination.resolve() or (
        source.exists() and destination.exists() and source.samefile(destination)
    ):
        raise ValueError("Output path must differ from source audio")

    image = embedded_cover(source, runtime=runtime)
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
