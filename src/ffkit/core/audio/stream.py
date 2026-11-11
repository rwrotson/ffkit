import logging
import os
import selectors
import subprocess
from collections.abc import Generator

from ffkit.core.audio._ffmpeg import MP3_ENCODER_ARGS, ffmpeg_number, media_path
from ffkit.core.audio._process import stop
from ffkit.core.audio.filters import audio_filters
from ffkit.core.audio.models import Effects, Track
from ffkit.core.audio.runtime import FFmpegRuntime

log = logging.getLogger(__name__)


def _seeked_track(track: Track, start: float) -> tuple[Track, float] | None:
    snapshot = track.model_copy(deep=True)
    source_offset = start + snapshot.effects.trim_start
    trim_end = snapshot.effects.trim_end
    if trim_end is not None and source_offset >= trim_end:
        return None
    # Replace both bounds at once; assigning them separately can fail interval validation.
    snapshot.effects = Effects.model_validate(
        {
            **snapshot.effects.model_dump(),
            "trim_start": 0,
            "trim_end": None if trim_end is None else trim_end - source_offset,
            # Leading silence removal after a seek would drop a pause at the seek position.
            "trim_silence": snapshot.effects.trim_silence and start == 0,
        }
    )
    return snapshot, source_offset


def stream_mp3(
    track: Track,
    gain: float = 0,
    start: float = 0,
    limiter_db: float | None = None,
    *,
    runtime: FFmpegRuntime | None = None,
) -> Generator[bytes]:
    """Stream original source audio from a position after its trim start."""
    if start < 0:
        raise ValueError("Stream start must not be negative")
    runtime = runtime or FFmpegRuntime()
    return _stream(
        track,
        gain,
        start,
        limiter_db,
        ffmpeg=runtime.ffmpeg_path,
        idle_timeout=runtime.stream_idle_timeout,
    )


def _stream(  # noqa: PLR0913 - Receives only the runtime fields it uses.
    track: Track,
    gain: float,
    start: float,
    limiter_db: float | None,
    *,
    ffmpeg: str,
    idle_timeout: float,
) -> Generator[bytes]:
    seeked = _seeked_track(track, start)
    if seeked is None:
        return
    snapshot, source_offset = seeked
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        ffmpeg_number(source_offset),
        "-i",
        media_path(snapshot.path),
        "-vn",
        "-map",
        "0:a:0",
    ]
    filters = audio_filters(snapshot, gain, streaming=True, limiter_db=limiter_db)
    if filters:
        command += ["-af", ",".join(filters)]
    command += [*MP3_ENCODER_ARGS, "-f", "mp3", "pipe:1"]
    process = subprocess.Popen(  # noqa: S603 - Fixed FFmpeg command with separate path arguments.
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        stdout = process.stdout
        if stdout is None:
            raise RuntimeError("FFmpeg stdout is unavailable")
        with selectors.DefaultSelector() as selector:
            selector.register(stdout, selectors.EVENT_READ)
            while selector.select(idle_timeout):
                chunk = os.read(stdout.fileno(), 8192)
                if not chunk:
                    break
                yield chunk
            else:
                raise TimeoutError("Audio stream stopped responding")
        if process.wait(timeout=5):
            raise RuntimeError(f"Audio encoder exited with status {process.returncode}")
    except Exception:
        log.exception("audio_stream_failed track=%s", track.id)
        raise
    finally:
        stop(process, grace=2)
