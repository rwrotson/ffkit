import array
import mmap
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np

from ffkit._ffmpeg.args import StrPath, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.runtime import FFmpegRuntime

ENERGY_SAMPLE_RATE = 2000
ENERGY_HOP = 200


def _hop_energy(data: bytes) -> bytes:
    """Return mean absolute amplitudes per hop as native float64 bytes."""
    samples = np.frombuffer(data, dtype="<i2").astype(np.float64)
    complete = len(samples) // ENERGY_HOP * ENERGY_HOP
    sums = np.abs(samples[:complete]).reshape(-1, ENERGY_HOP).sum(axis=1)
    if complete < len(samples):
        sums = np.append(sums, np.abs(samples[complete:]).sum())
    # A trailing partial hop is divided by the full hop size, like complete hops.
    return (sums / (ENERGY_HOP * 32768)).tobytes()


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
            energy_file.write(_hop_energy(data[:complete]))
            pending = data[complete:]
        if pending:
            energy_file.write(_hop_energy(pending))

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
