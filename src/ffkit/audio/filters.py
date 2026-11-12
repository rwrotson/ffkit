from ffkit._ffmpeg.args import ffmpeg_number
from ffkit.audio.defaults import (
    DEFAULT_SILENCE_THRESHOLD_DB,
    LOUDNORM_RANGE,
    LOUDNORM_TRUE_PEAK_DB,
)
from ffkit.audio.effects import Effects


def audio_filters(
    effects: Effects,
    group_gain_db: float = 0,
    *,
    streaming: bool = False,
    limiter_db: float | None = None,
) -> list[str]:
    """Build the FFmpeg audio filter chain for effects."""
    filters: list[str] = []

    if effects.trim_start or effects.trim_end is not None:
        trim = f"atrim=start={ffmpeg_number(effects.trim_start)}"
        if effects.trim_end is not None:
            trim += f":end={ffmpeg_number(effects.trim_end)}"
        filters.extend([trim, "asetpts=PTS-STARTPTS"])

    if effects.trim_silence:
        edge_trim = (
            "silenceremove=start_periods=1:start_duration=0:"
            f"start_threshold={DEFAULT_SILENCE_THRESHOLD_DB}dB"
        )
        filters.append(edge_trim)
        if not streaming:
            filters.extend(["areverse", edge_trim, "areverse"])

    total_gain = effects.gain_db + group_gain_db
    if total_gain:
        filters.append(f"volume={ffmpeg_number(total_gain)}dB")

    if effects.normalize_lufs is not None:
        filters.append(
            f"loudnorm=I={ffmpeg_number(effects.normalize_lufs)}"
            f":TP={LOUDNORM_TRUE_PEAK_DB}:LRA={LOUDNORM_RANGE}"
        )

    ceiling = effects.effective_limiter_db(limiter_db)
    if ceiling is not None:
        filters.append(f"alimiter=limit={10 ** (ceiling / 20):.8f}:level=false:latency=true")

    return filters
