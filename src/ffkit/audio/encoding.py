from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ffkit.audio.defaults import DEFAULT_MP3_BITRATE_KBPS


class Mp3Encoding(BaseModel):
    """MP3 output through LAME at a constant bit rate, or variable when ``vbr_quality`` is set."""

    model_config = ConfigDict(frozen=True)

    format: Literal["mp3"] = "mp3"
    bitrate_kbps: int = Field(
        default=DEFAULT_MP3_BITRATE_KBPS,
        ge=32,
        le=320,
        description="Constant bit rate",
    )
    vbr_quality: int | None = Field(
        default=None,
        ge=0,
        le=9,
        description="LAME VBR quality; 0 is best, replaces the bit rate",
    )

    @property
    def extension(self) -> str:
        """File name suffix for this format."""
        return ".mp3"

    @property
    def muxer(self) -> str:
        """FFmpeg output format name."""
        return "mp3"

    def codec_args(self) -> list[str]:
        """FFmpeg arguments that select and configure the audio encoder."""
        quality = (
            ["-q:a", str(self.vbr_quality)]
            if self.vbr_quality is not None
            else ["-b:a", f"{self.bitrate_kbps}k"]
        )
        return ["-codec:a", "libmp3lame", *quality]


# A union discriminated by ``format`` once more encoders are supported.
type Encoding = Mp3Encoding
