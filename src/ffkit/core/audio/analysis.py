import array
import json
import math
import mmap
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from statistics import median

from ffkit.core.audio._ffmpeg import (
    LOUDNORM_RANGE,
    LOUDNORM_TRUE_PEAK_DB,
    ffmpeg_number,
    media_path,
    source_fingerprint,
)
from ffkit.core.audio._process import stdout_chunks, stop
from ffkit.core.audio.defaults import (
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
)
from ffkit.core.audio.models import Effects, TempoSegment, Track
from ffkit.core.audio.runtime import FFmpegRuntime
from ffkit.core.audio.silence import MIN_TRAILING_SILENCE, scan_silence, trailing_silence_end

TRIM_EDGE_TOLERANCE = 0.1
WAVEFORM_BINS = 400
PEAK_OVERSAMPLING = 4
TEMPO_MAX_CHANGE = 8
TEMPO_MIN_CHANGE = 12
TEMPO_WINDOW = 300
TEMPO_MIN_WINDOW = 160
TEMPO_MIN_CONFIDENCE = 0.1


def probe(track: Track, *, runtime: FFmpegRuntime | None = None) -> Track:
    """Read duration and tags from the first audio stream."""
    runtime = runtime or FFmpegRuntime()
    source = Path(track.path)
    if not source.is_file():
        track.error = "Source file is missing"
        return track
    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffprobe_path,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            media_path(source),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=runtime.process_timeout,
    )
    report = json.loads(result.stdout)
    audio_stream = next(
        (stream for stream in report.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    if audio_stream is None:
        raise ValueError("File has no decodable audio stream")
    info = report["format"]
    track.duration = float(info.get("duration", 0))
    if not math.isfinite(track.duration) or track.duration <= 0:
        raise ValueError("File has no measurable audio duration")
    format_tags = {str(key).lower(): str(value) for key, value in info.get("tags", {}).items()}
    stream_tags = {
        str(key).lower(): str(value) for key, value in audio_stream.get("tags", {}).items()
    }
    track._update_probed_tags({**format_tags, **stream_tags})
    track.error = None
    return track


def detect_trim_bounds(  # noqa: PLR0913 - Scan options plus the keyword-only FFmpeg runtime.
    path: Path,
    duration: float | None = None,
    threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    min_duration: float = DEFAULT_TRIM_MIN_DURATION,
    cancelled: Callable[[], bool] | None = None,
    *,
    runtime: FFmpegRuntime | None = None,
) -> tuple[float, float | None]:
    """Find audible bounds; retain pauses inside the track."""
    runtime = runtime or FFmpegRuntime()
    if duration is None:
        duration = probe(Track(path=str(path)), runtime=runtime).duration
    if not duration or duration <= 0:
        raise ValueError("Track duration is unavailable")
    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        media_path(path),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        f"silencedetect=noise={ffmpeg_number(threshold_db)}dB:d={ffmpeg_number(min_duration)}",
        "-progress",
        "pipe:2",
        "-f",
        "null",
        "-",
    ]
    scan = scan_silence(command, cancelled, timeout=runtime.process_timeout)
    leading = scan.first_start is not None and scan.first_start <= TRIM_EDGE_TOLERANCE
    start = scan.first_end if leading and scan.first_end is not None else 0.0
    end = scan.trailing_start()
    if end is not None and end <= start:
        raise ValueError("Track contains no audible audio")
    return round(start, 3), round(end, 3) if end is not None else None


def trailing_trim_end(
    effects: Effects,
    source: Path,
    cancelled: Callable[[], bool] | None = None,
    *,
    runtime: FFmpegRuntime,
) -> float | None:
    """Return where trailing silence starts when ``trim_silence`` is enabled."""
    if not effects.trim_silence:
        return None
    duration = probe(Track(path=str(source)), runtime=runtime).duration
    trailing_end = trailing_silence_end(
        effects,
        source,
        duration,
        cancelled,
        ffmpeg=runtime.ffmpeg_path,
        timeout=runtime.process_timeout,
    )
    if trailing_end is not None and trailing_end <= effects.trim_start + MIN_TRAILING_SILENCE:
        raise ValueError("Track contains no audible audio")
    return trailing_end


def analyze_peak_waveform(track: Track, *, runtime: FFmpegRuntime | None = None) -> list[float]:
    """Measure a full-scale peak envelope from four-times oversampled audio."""
    runtime = runtime or FFmpegRuntime()
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


def analyze_waveform_tempo(  # noqa: C901, PLR0915 - Preserve Mixtable streaming analysis.
    track: Track, *, runtime: FFmpegRuntime | None = None
) -> Track:
    """Build a compact waveform and rough tempo segments from decoded mono audio."""
    runtime = runtime or FFmpegRuntime()
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


def measure_loudness(
    path: Path, filters: list[str] | None = None, *, runtime: FFmpegRuntime | None = None
) -> tuple[float | None, float | None]:
    """Measure integrated LUFS and true peak from ffmpeg's loudnorm report."""
    runtime = runtime or FFmpegRuntime()
    chain = [
        *(filters or []),
        f"loudnorm=I={DEFAULT_TARGET_LUFS}:TP={LOUDNORM_TRUE_PEAK_DB}"
        f":LRA={LOUDNORM_RANGE}:print_format=json",
    ]
    result = subprocess.run(  # noqa: S603 - Fixed executable and argument list; paths stay separate.
        [
            runtime.ffmpeg_path,
            "-hide_banner",
            "-i",
            media_path(path),
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
        timeout=runtime.process_timeout,
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


def analyze_loudness(track: Track, *, runtime: FFmpegRuntime | None = None) -> Track:
    """Measure source loudness and record the file fingerprint for normalization reuse."""
    source = Path(track.path)
    fingerprint = source_fingerprint(source)
    lufs, peak = measure_loudness(source, runtime=runtime)
    if source_fingerprint(source) != fingerprint:
        raise ValueError("Source audio changed during loudness analysis")
    track.loudness_lufs = lufs
    track.true_peak_db = peak
    track.analysis_source_stat = fingerprint
    return track
