from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ffkit.audio.defaults import (
    DEFAULT_SILENCE_PADDING,
    DEFAULT_SILENCE_THRESHOLD_DB,
    LOUDNORM_MAX_LUFS,
    LOUDNORM_MIN_LUFS,
    MIN_LIMITER_CEILING_DB,
)

# Level that a silence threshold is relative to: digital full scale or the loudest window.
type SilenceReference = Literal["full_scale", "peak"]


def _as_float(value: object) -> float | None:
    """Coerce like lax field validation; field validators report values that do not convert."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


class Effects(BaseModel):
    """Audio processing options applied to the original source."""

    model_config = ConfigDict(frozen=True)

    gain_db: float = 0
    normalize_lufs: float | None = Field(default=None, ge=LOUDNORM_MIN_LUFS, le=LOUDNORM_MAX_LUFS)
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    trim_silence: bool = False
    silence_threshold_db: float = Field(default=DEFAULT_SILENCE_THRESHOLD_DB, ge=-100, le=0)
    silence_threshold_reference: SilenceReference = "full_scale"
    silence_padding: float = Field(default=DEFAULT_SILENCE_PADDING, ge=0, le=1)
    limiter_ceiling_db: float | None = Field(
        default=None,
        ge=MIN_LIMITER_CEILING_DB,
        le=-0.1,
    )

    @model_validator(mode="before")
    @classmethod
    def valid_trim(cls, values: object) -> object:
        """Reject trim bounds that would produce an empty interval."""
        if isinstance(values, dict):
            start = _as_float(values.get("trim_start", 0))
            end = _as_float(values.get("trim_end"))
            if start is not None and end is not None and end <= start:
                raise ValueError("Trim end must be later than start")
        return values

    def replace(self, **changes: object) -> Self:
        """Return a validated copy with the given fields changed."""
        return self.model_validate({**self.model_dump(), **changes})
