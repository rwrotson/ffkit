from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    model_config = ConfigDict(validate_assignment=True)

    gain_db: float = 0
    normalize_lufs: float | None = None
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    trim_silence: bool = False
    limiter_ceiling_db: float | None = Field(default=None, ge=-20, le=-0.1)

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

    def effective_limiter_db(self, default: float | None) -> float | None:
        """Return the track limiter ceiling, or the default when the track sets none."""
        return self.limiter_ceiling_db if self.limiter_ceiling_db is not None else default
