import array
import json
import math
import mmap
import subprocess
import tempfile
from statistics import median

from ffkit.core._ffmpeg import media_path
from ffkit.core._process import stdout_chunks, stop
from ffkit.core.audio.analysis.probe import probe
from ffkit.core.audio.models import TempoSegment, Track
from ffkit.core.runtime import FFmpegRuntime

WAVEFORM_BINS = 400
PEAK_OVERSAMPLING = 4
TEMPO_MAX_CHANGE = 8
TEMPO_MIN_CHANGE = 12
TEMPO_WINDOW = 300
TEMPO_MIN_WINDOW = 160
TEMPO_MIN_CONFIDENCE = 0.1


def analyze_peak_waveform(track: Track, *, runtime: FFmpegRuntime = FFmpegRuntime()) -> list[float]:
    """Measure a full-scale peak envelope from four-times oversampled audio."""
    duration = track.duration
    if duration is None:
        duration = probe(Track(path=track.path), runtime=runtime).duration
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Track duration is unavailable")

    info = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            media_path(track.path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=runtime.process_timeout,
    )

    stream = json.loads(info.stdout)["streams"][0]
    channels = int(stream["channels"])
    rate = int(stream["sample_rate"]) * PEAK_OVERSAMPLING
    frames_per_bin = max(1, math.ceil(duration * rate / WAVEFORM_BINS))
    peaks = [0.0] * WAVEFORM_BINS

    process = subprocess.Popen(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffmpeg_path,
            "-v",
            "error",
            "-i",
            media_path(track.path),
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
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    frame_bytes = channels * 4
    frame_index = 0
    pending = b""
    try:
        for chunk in stdout_chunks(process, timeout=runtime.process_timeout):
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
    finally:
        stop(process)

    return [round(value, 5) for value in peaks]


def analyze_waveform_tempo(  # noqa: C901, PLR0915 - Single-pass streaming analysis.
    track: Track, *, runtime: FFmpegRuntime = FFmpegRuntime()
) -> Track:
    """Build a compact waveform and rough tempo segments from decoded mono audio."""
    process = subprocess.Popen(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffmpeg_path,
            "-v",
            "error",
            "-i",
            media_path(track.path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "2000",
            "-f",
            "s16le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    hop = 200
    with tempfile.TemporaryFile() as energy_file:
        remaining_bytes = b""
        energy_count = 0
        peak = 0.0
        try:
            if process.stdout is None:
                raise RuntimeError("FFmpeg stdout is unavailable")
            for chunk in stdout_chunks(process, timeout=runtime.process_timeout):
                data = remaining_bytes + chunk
                complete = len(data) // (hop * 2) * (hop * 2)
                for offset in range(0, complete, hop * 2):
                    samples = array.array("h")
                    samples.frombytes(data[offset : offset + hop * 2])
                    value = sum(abs(sample) for sample in samples) / (hop * 32768)
                    energy_file.write(array.array("d", [value]).tobytes())
                    energy_count += 1
                    peak = max(peak, value)
                remaining_bytes = data[complete:]

            if remaining_bytes:
                samples = array.array("h")
                samples.frombytes(remaining_bytes)
                value = sum(abs(sample) for sample in samples) / (hop * 32768)
                energy_file.write(array.array("d", [value]).tobytes())
                energy_count += 1
                peak = max(peak, value)
        finally:
            stop(process)

        if not energy_count:
            return track
        energy_file.flush()
        with mmap.mmap(energy_file.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            energy = memoryview(mapped).cast("d")
            try:
                width = max(1, math.ceil(energy_count / WAVEFORM_BINS))
                track.waveform = [
                    round(max(energy[pos : pos + width]) / (peak or 1), 3)
                    for pos in range(0, energy_count, width)
                ]
                estimates = tempo_estimates(energy)
            finally:
                energy.release()

    track.waveform_peak = analyze_peak_waveform(track, runtime=runtime)

    segments: list[TempoSegment] = []
    if estimates:
        smoothed = [
            round(median(item[1] for item in estimates[max(0, i - 1) : i + 2]))
            for i in range(len(estimates))
        ]
        segments.append(TempoSegment(start=0, bpm=smoothed[0], confidence=estimates[0][2]))

        for index in range(1, len(estimates) - 1):
            bpm = smoothed[index]
            previous = segments[-1].bpm
            if (
                abs(bpm * 2 - previous) <= TEMPO_MAX_CHANGE
                or abs(bpm / 2 - previous) <= TEMPO_MAX_CHANGE
            ):
                continue
            if (
                abs(bpm - previous) >= TEMPO_MIN_CHANGE
                and abs(smoothed[index + 1] - bpm) <= TEMPO_MAX_CHANGE
            ):
                segments.append(
                    TempoSegment(start=estimates[index][0], bpm=bpm, confidence=estimates[index][2])
                )

    track.tempo = segments
    return track


def tempo_estimates(energy: memoryview[float]) -> list[tuple[float, float, float]]:
    """Measure tempo from one short onset window at a time."""
    estimates: list[tuple[float, float, float]] = []
    section: list[float] = []

    for pos in range(1, len(energy)):
        section.append(max(0.0, energy[pos] - energy[pos - 1]))
        if len(section) < TEMPO_WINDOW and pos != len(energy) - 1:
            continue
        if len(section) >= TEMPO_MIN_WINDOW:
            candidates = [
                (sum(section[i] * section[i - lag] for i in range(lag, len(section))), lag)
                for lag in range(3, 16)
            ]
            score, lag = max(candidates)
            energy_total = sum(value * value for value in section)
            confidence = min(1.0, score / energy_total) if energy_total else 0.0
            if confidence >= TEMPO_MIN_CONFIDENCE:
                start = pos - len(section)
                estimates.append((start / 10, round(600 / lag), round(confidence, 2)))
        section = []

    return estimates
