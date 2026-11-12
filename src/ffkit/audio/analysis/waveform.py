import array
import math

from ffkit._ffmpeg.args import StrPath, media_path
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio.analysis._energy import energy
from ffkit.audio.analysis.probe import AudioInfo, probe
from ffkit.runtime import FFmpegRuntime

WAVEFORM_BINS = 400
PEAK_OVERSAMPLING = 4


def peak_envelope(
    source: StrPath,
    *,
    info: AudioInfo | None = None,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float, ...]:
    """Measure a full-scale peak envelope from four-times oversampled audio.

    The source is probed for its duration, sample rate, and channels unless ``info`` is given.
    """
    info = info or probe(source, runtime=runtime)
    channels = info.channels
    rate = info.sample_rate * PEAK_OVERSAMPLING
    frames_per_bin = max(1, math.ceil(info.duration * rate / WAVEFORM_BINS))
    peaks = [0.0] * WAVEFORM_BINS

    command = [
        runtime.ffmpeg_path,
        "-v",
        "error",
        "-i",
        media_path(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ar",
        str(rate),
        "-ac",
        str(channels),
        "-f",
        "f32le",
        "-",
    ]

    frame_bytes = channels * 4
    frame_index = 0
    pending = b""
    for chunk in iter_output(command, timeout=runtime.process_timeout, cancelled=cancelled):
        pending += chunk
        while len(pending) >= frame_bytes:
            boundary = frames_per_bin - frame_index % frames_per_bin
            count = min(boundary, len(pending) // frame_bytes)
            size = count * frame_bytes
            values = array.array("f")
            values.frombytes(pending[:size])
            pending = pending[size:]
            bin_index = min(WAVEFORM_BINS - 1, frame_index // frames_per_bin)
            # Builtin max/min over the array run in C; per-sample abs() in Python is slow.
            loudest, quietest = max(values), min(values)
            peaks[bin_index] = max(peaks[bin_index], loudest, -quietest)
            frame_index += count

    return tuple(round(value, 5) for value in peaks)


def waveform(
    source: StrPath,
    *,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> tuple[float, ...]:
    """Build a compact loudness envelope of up to 400 values scaled to the loudest point."""
    with energy(source, cancelled=cancelled, runtime=runtime) as hops:
        if not len(hops):
            return ()
        loudest = max(hops) or 1
        width = max(1, math.ceil(len(hops) / WAVEFORM_BINS))
        return tuple(
            round(max(hops[pos : pos + width]) / loudest, 3) for pos in range(0, len(hops), width)
        )
