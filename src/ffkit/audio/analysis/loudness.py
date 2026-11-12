import json
import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from ffkit._ffmpeg.args import StrPath, media_path, source_fingerprint
from ffkit._ffmpeg.process import Cancelled, run
from ffkit.audio._filters import audio_filters
from ffkit.audio.analysis.silence import trailing_trim_end
from ffkit.audio.defaults import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    LOUDNORM_RANGE,
    LOUDNORM_TRUE_PEAK_DB,
)
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
    """Measure integrated LUFS and true peak after applying filters before loudnorm."""
    fingerprint = source_fingerprint(source)
    chain = [
        *filters,
        f"loudnorm=I={DEFAULT_TARGET_LUFS}:TP={LOUDNORM_TRUE_PEAK_DB}"
        f":LRA={LOUDNORM_RANGE}:print_format=json",
    ]

    command = [
        runtime.ffmpeg_path,
        "-hide_banner",
        "-nostats",
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
    stderr = run(
        command, pipe="stderr", timeout=runtime.process_timeout, cancelled=cancelled
    ).decode(errors="replace")

    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during loudness measurement")

    marker = stderr.rfind('"input_i"')
    data: dict[str, object] = {}
    if marker >= 0:
        left = stderr.rfind("{", 0, marker)
        right = stderr.find("}", marker)
        data = json.loads(stderr[left : right + 1])

    return Loudness(
        lufs=_finite(data.get("input_i")),
        true_peak_db=_finite(data.get("input_tp")),
        fingerprint=None if filters else fingerprint,
    )


def _finite(value: object) -> float | None:
    try:
        number = float(str(value))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


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
        gain_db=0, normalize_lufs=None, limiter_ceiling_db=None
    )

    fingerprint = source_fingerprint(source)
    trailing_end = trailing_trim_end(measured, source, cancelled, runtime=runtime)
    if trailing_end is not None:
        measured = measured.replace(trim_end=trailing_end)
    filters = audio_filters(measured, streaming=True)

    if not filters and known is not None and known.fingerprint == fingerprint:
        loudness = known
    else:
        loudness = measure_loudness(source, filters=filters, cancelled=cancelled, runtime=runtime)

    if source_fingerprint(source) != fingerprint:
        raise SourceChangedError("Source audio changed during normalization")
    return gain_for_target(loudness, target_lufs=target_lufs, peak_ceiling_db=peak_ceiling_db)
