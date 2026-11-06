import array
import json
import math
import mmap
import os
import re
import selectors
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from statistics import median

from ffkit.core.audio.models import TempoSegment, Track

PROCESS_TIMEOUT = 900
TRIM_EDGE_TOLERANCE = 0.1
TEMPO_MAX_CHANGE = 8
TEMPO_MIN_CHANGE = 12
TEMPO_WINDOW = 300
TEMPO_MIN_WINDOW = 160
TEMPO_MIN_CONFIDENCE = 0.1


def _decoded_chunks(process: subprocess.Popen[bytes]) -> Iterator[bytes]:
    deadline = time.monotonic() + PROCESS_TIMEOUT
    if process.stdout is None:
        raise RuntimeError("FFmpeg stdout is unavailable")
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(process.args, PROCESS_TIMEOUT)
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            yield chunk
    remaining = max(0, deadline - time.monotonic())
    if process.wait(timeout=remaining):
        raise subprocess.CalledProcessError(process.returncode, process.args)


def probe(track: Track) -> Track:
    """Read duration and tags from the first audio stream."""
    source = Path(track.path)
    if not source.is_file():
        track.error = "Source file is missing"
        return track
    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],  # noqa: S607 - FFprobe is resolved on PATH.
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
    )
    report = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "audio" for stream in report.get("streams", [])):
        raise ValueError("File has no decodable audio stream")
    info = report["format"]
    track.duration = float(info.get("duration", 0))
    if not math.isfinite(track.duration) or track.duration <= 0:
        raise ValueError("File has no measurable audio duration")
    detected = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    track.tags = {**detected, **track.tags}
    track.error = None
    return track


def detect_trim_bounds(
    path: Path, duration: float | None = None, threshold_db: float = -50, min_duration: float = 0.1
) -> tuple[float, float | None]:
    """Find audible bounds; retain pauses inside the track."""
    if duration is None:
        duration = probe(Track(path=str(path))).duration
    if not duration or duration <= 0:
        raise ValueError("Track duration is unavailable")
    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [  # noqa: S607 - FFmpeg is resolved from PATH; each argument is separate.
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
    )
    starts = [float(value) for value in re.findall(r"silence_start: ([-\d.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([-\d.]+)", result.stderr)]
    start = ends[0] if starts and starts[0] <= TRIM_EDGE_TOLERANCE and ends else 0.0
    end = (
        starts[-1]
        if starts
        and (len(starts) > len(ends) or (ends and ends[-1] >= duration - TRIM_EDGE_TOLERANCE))
        else None
    )
    if end is not None and end <= start:
        raise ValueError("Track contains no audible audio")
    return round(start, 3), round(end, 3) if end is not None else None


def analyze_peak_waveform(track: Track) -> list[float]:
    """Measure a full-scale peak envelope from four-times oversampled audio."""
    duration = track.duration
    if duration is None:
        duration = probe(Track(path=track.path)).duration
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Track duration is unavailable")
    info = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [  # noqa: S607 - FFprobe is resolved from PATH; each argument is separate.
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            track.path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
    )
    stream = json.loads(info.stdout)["streams"][0]
    channels = int(stream["channels"])
    rate = int(stream["sample_rate"]) * 4
    frames_per_bin = max(1, math.ceil(duration * rate / 400))
    peaks = [0.0] * 400
    process = subprocess.Popen(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [  # noqa: S607 - FFmpeg is resolved from PATH; each argument is separate.
            "ffmpeg",
            "-v",
            "error",
            "-i",
            track.path,
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
        for chunk in _decoded_chunks(process):
            pending += chunk
            while len(pending) >= frame_bytes:
                boundary = frames_per_bin - frame_index % frames_per_bin
                count = min(boundary, len(pending) // frame_bytes)
                size = count * frame_bytes
                values = array.array("f")
                values.frombytes(pending[:size])
                pending = pending[size:]
                bin_index = min(399, frame_index // frames_per_bin)
                peaks[bin_index] = max(peaks[bin_index], *(abs(value) for value in values))
                frame_index += count
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()
    return [round(value, 5) for value in peaks]


def analyze_waveform_tempo(track: Track) -> Track:  # noqa: C901, PLR0912, PLR0915 - Preserve Mixtable streaming analysis.
    """Build a compact waveform and rough tempo segments from decoded mono audio."""
    process = subprocess.Popen(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        ["ffmpeg", "-v", "error", "-i", track.path, "-ac", "1", "-ar", "2000", "-f", "s16le", "-"],  # noqa: S607 - FFmpeg is resolved on PATH.
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
            for chunk in _decoded_chunks(process):
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
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        if not energy_count:
            return track
        energy_file.flush()
        with mmap.mmap(energy_file.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            energy = memoryview(mapped).cast("d")
            try:
                width = max(1, math.ceil(energy_count / 400))
                track.waveform = [
                    round(max(energy[pos : pos + width]) / (peak or 1), 3)
                    for pos in range(0, energy_count, width)
                ]
                estimates = tempo_estimates(energy)
            finally:
                energy.release()
    track.waveform_peak = analyze_peak_waveform(track)
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


def measure_loudness(
    path: Path, filters: list[str] | None = None
) -> tuple[float | None, float | None]:
    """Measure integrated LUFS and true peak from ffmpeg's loudnorm report."""
    chain = [*(filters or []), "loudnorm=I=-14:TP=-1:LRA=11:print_format=json"]
    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [  # noqa: S607 - FFmpeg is resolved from PATH; each argument is separate.
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            ",".join(chain),
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
    )
    marker = result.stderr.rfind('"input_i"')
    if marker < 0:
        return None, None
    left = result.stderr.rfind("{", 0, marker)
    right = result.stderr.find("}", marker)
    data = json.loads(result.stderr[left : right + 1])

    def finite(value: object) -> float | None:
        try:
            number = float(str(value))
            return number if math.isfinite(number) else None
        except ValueError:
            return None

    return finite(data.get("input_i")), finite(data.get("input_tp"))
