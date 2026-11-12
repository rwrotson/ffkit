import array
import mmap
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

from ffkit._ffmpeg.args import StrPath, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.runtime import FFmpegRuntime

ENERGY_SAMPLE_RATE = 2000
ENERGY_HOP = 200


def _hop_energy(data: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(data)
    return sum(abs(sample) for sample in samples) / (ENERGY_HOP * 32768)


@contextmanager
def energy(
    source: StrPath, *, cancelled: Cancelled | None, runtime: FFmpegRuntime
) -> Iterator[memoryview[float]]:
    """Yield mean absolute amplitude per 0.1 s hop, kept in a temporary file for long sources."""
    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(ENERGY_SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    hop_bytes = ENERGY_HOP * 2

    with tempfile.TemporaryFile() as energy_file:
        pending = b""
        for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
            data = pending + chunk
            complete = len(data) // hop_bytes * hop_bytes
            values = [
                _hop_energy(data[pos : pos + hop_bytes]) for pos in range(0, complete, hop_bytes)
            ]
            energy_file.write(array.array("d", values).tobytes())
            pending = data[complete:]
        if pending:
            energy_file.write(array.array("d", [_hop_energy(pending)]).tobytes())

        energy_file.flush()
        if not energy_file.tell():
            yield memoryview(array.array("d"))
            return
        with mmap.mmap(energy_file.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            hops = memoryview(mapped).cast("d")
            try:
                yield hops
            finally:
                hops.release()
