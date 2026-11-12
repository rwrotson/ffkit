from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, media_path, source_fingerprint
from ffkit._ffmpeg.process import Cancelled, iter_output
from ffkit.audio._filters import audio_filters
from ffkit.audio.analysis._ebur128 import EBUR128_FILTERS, Report, iter_lines
from ffkit.audio.analysis.silence import resolve_silence_trim
from ffkit.audio.defaults import DEFAULT_PEAK_CEILING_DB, DEFAULT_TARGET_LUFS
from ffkit.audio.effects import Effects
from ffkit.errors import SilentAudioError, SourceChangedError
from ffkit.runtime import FFmpegRuntime


class Loudness(BaseModel):
    """Integrated loudness and true peak; ``None`` when FFmpeg reports no finite value.

    ``fingerprint`` identifies the measured file and is set only for unfiltered measurements, which
    ``measure_normalization_gain(known=...)`` can reuse.
    """

    model_config = ConfigDict(frozen=True)

    lufs: float | None = Field(allow_inf_nan=False)
    true_peak_db: float | None = Field(allow_inf_nan=False)
    fingerprint: tuple[int, int, int] | None = None


def measure_loudness(
    source: StrPath,
    *,
    filters: Sequence[str] = (),
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> Loudness:
    """Measure ITU-R BS.1770 integrated loudness and true peak after applying filters.

    Mono audio is measured as dual-mono, as it plays on two speakers.
    """
    fingerprint = source_fingerprint(source)
    chain = [*filters, *EBUR128_FILTERS]

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        media_path(source),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        ",".join(chain),
        "-f",
        "null",
        "-",
    ]
    report = Report()
    output = iter_output(
        command,
        pipe="stderr",
        timeout=runtime.process_timeout,
        cancelled=cancelled,
    )
    for line in iter_lines(output):
        report.read_line(line)

    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during loudness measurement")

    return Loudness(
        lufs=report.lufs(),
        true_peak_db=report.true_peak_db(),
        fingerprint=None if filters else fingerprint,
    )


def gain_for_target(
    loudness: Loudness,
    *,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
) -> float:
    """Return a fixed gain in 0.1 dB steps that reaches the target within the peak ceiling."""
    lufs, peak = loudness.lufs, loudness.true_peak_db
    if lufs is None:
        raise SilentAudioError("Cannot measure track loudness")
    gain = target_lufs - lufs
    if peak is not None:
        gain = min(gain, peak_ceiling_db - peak)

    rounded = round(gain, 1)
    if peak is not None and rounded > peak_ceiling_db - peak:
        rounded = round(rounded - 0.1, 1)
    return rounded


def measure_normalization_gain(  # noqa: PLR0913 - Gain options, cache, and FFmpeg runtime.
    source: StrPath,
    *,
    effects: Effects | None = None,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: float = DEFAULT_PEAK_CEILING_DB,
    known: Loudness | None = None,
    cancelled: Cancelled | None = None,
    runtime: FFmpegRuntime = FFmpegRuntime(),
) -> float:
    """Measure processed audio and calculate a fixed gain within the true peak ceiling.

    Gain, loudness normalization, and the limiter of ``effects`` are ignored; trims apply.
    ``known`` is used instead of measuring only when no filters apply and its fingerprint matches
    the source file's size, mtime, and ctime.
    """
    measured = (effects or Effects()).replace(
        gain_db=0,
        normalize_lufs=None,
        limiter_ceiling_db=None,
    )

    fingerprint = source_fingerprint(source)
    measured = resolve_silence_trim(measured, source, cancelled, runtime=runtime)
    filters = audio_filters(measured)

    if not filters and known is not None and known.fingerprint == fingerprint:
        loudness = known
    else:
        loudness = measure_loudness(source, filters=filters, cancelled=cancelled, runtime=runtime)

    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during normalization")
    return gain_for_target(loudness, target_lufs=target_lufs, peak_ceiling_db=peak_ceiling_db)
