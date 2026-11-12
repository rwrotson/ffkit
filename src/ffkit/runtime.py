from pydantic import BaseModel, ConfigDict, Field


class FFmpegRuntime(BaseModel):
    """FFmpeg executables and process time limits used by audio helpers."""

    model_config = ConfigDict(frozen=True)

    ffmpeg_path: str = Field(
        default="ffmpeg", min_length=1, description="FFmpeg executable; bare names use PATH"
    )
    ffprobe_path: str = Field(
        default="ffprobe", min_length=1, description="FFprobe executable; bare names use PATH"
    )
    process_timeout: float = Field(
        default=900, gt=0, description="Seconds an FFmpeg or FFprobe run may take"
    )
    stream_idle_timeout: float = Field(
        default=30, gt=0, description="Seconds a stream may go without output before failing"
    )
