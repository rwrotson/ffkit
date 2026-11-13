import os
from pathlib import Path

from ffkit._ffmpeg.args import StrPath, ensure_distinct, existing_file, temporary_sibling
from ffkit.audio.analysis.cover import embedded_cover
from ffkit.runtime import FFmpegRuntime


def extract_cover(
    source: StrPath,
    destination: StrPath,
    *,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> Path | None:
    """Atomically extract the first embedded image as JPEG; return None when there is none."""
    source, destination = existing_file(source), Path(destination)
    ensure_distinct(source, destination)

    image = embedded_cover(source, runtime=runtime)
    if image is None:
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_sibling(destination, ".jpg")
    try:
        temporary.write_bytes(image)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
