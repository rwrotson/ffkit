from __future__ import annotations

import math
from pathlib import Path

from ffkit.core.audio.models import Track


def audio_filters(
    track: Track,
    group_gain_db: float = 0,
    *,
    streaming: bool = False,
    limiter_db: float | None = None,
) -> list[str]:
    """Build the Mixtable FFmpeg audio filter chain."""
    effects = track.effects
    filters: list[str] = []
    if effects.trim_start or effects.trim_end is not None:
        trim = f"atrim=start={effects.trim_start}"
        if effects.trim_end is not None:
            trim += f":end={effects.trim_end}"
        filters.extend([trim, "asetpts=PTS-STARTPTS"])
    if effects.trim_silence:
        edge_trim = "silenceremove=start_periods=1:start_duration=0:start_threshold=-50dB"
        filters.append(edge_trim)
        if not streaming:
            filters.extend(["areverse", edge_trim, "areverse"])
    total_gain = effects.gain_db + group_gain_db
    if total_gain:
        filters.append(f"volume={total_gain}dB")
    if effects.normalize_lufs is not None:
        filters.append(f"loudnorm=I={effects.normalize_lufs}:TP=-1:LRA=11")
    ceiling = effects.limiter_ceiling_db if effects.limiter_ceiling_db is not None else limiter_db
    if ceiling is not None:
        filters.append(f"alimiter=limit={10 ** (ceiling / 20):.8f}:level=false:latency=true")
    return filters


def safe_name(track: Track, index: int, width: int) -> str:
    """Build a numbered MP3 filename from track metadata."""
    artist = track.tags.get("artist", "")
    title = track.tags.get("title") or Path(track.path).stem
    name = f"{artist} - {title}" if artist else title
    name = "".join(character if character not in "/\\:\x00" else "_" for character in name).strip()
    prefix = f"{index + 1:0{width}d}. "
    suffix = ".mp3"
    # APFS limits a single UTF-8 filename to 255 bytes.
    remaining = 255 - len(prefix.encode()) - len(suffix.encode())
    name = name.encode("utf-8")[:remaining].decode("utf-8", errors="ignore").rstrip(" .")
    return f"{prefix}{name or 'Untitled'}.mp3"


def normalization_gain(
    lufs: float | None, peak: float | None, target: float = -14, ceiling: float = -1
) -> float:
    """Return a fixed gain, keeping the measured true peak below the ceiling."""
    if lufs is None or not math.isfinite(lufs):
        raise ValueError("Cannot measure track loudness")
    gain = target - lufs
    if peak is not None:
        gain = min(gain, ceiling - peak)
    return round(gain, 1)
