from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ffkit.core.audio._ffmpeg import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    SILENCE_THRESHOLD_DB,
)


class TempoSegment(BaseModel):
    """A timed BPM estimate."""

    start: float = Field(default=0, ge=0)
    bpm: float = Field(gt=0, le=400)
    confidence: float | None = Field(default=None, ge=0, le=1)


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


class Track(BaseModel):
    """Original audio source, metadata, and analysis results."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    path: str
    tags: dict[str, str] = Field(default_factory=dict)
    probed_source_tags: dict[str, str] | None = Field(default=None, repr=False)
    tag_overrides: dict[str, str] = Field(default_factory=dict, repr=False)
    cover_path: str | None = None
    cover_removed: bool = False
    color: str = "#808080"
    duration: float | None = None
    loudness_lufs: float | None = None
    true_peak_db: float | None = None
    analysis_source_stat: tuple[int, int, int] | None = None
    tempo: list[TempoSegment] = Field(default_factory=list)
    waveform: list[float] = Field(default_factory=list)
    waveform_peak: list[float] = Field(default_factory=list)
    effects: Effects = Field(default_factory=Effects)
    error: str | None = None

    def _update_probed_tags(self, source_tags: dict[str, str]) -> None:
        if self.probed_source_tags is None:
            overrides = self.tags.copy()
        else:
            overrides = {
                key: value for key, value in self.tags.items() if key in self.tag_overrides
            }
            overrides.update(
                (key, value)
                for key, value in self.tags.items()
                if key not in self.tag_overrides and self.probed_source_tags.get(key) != value
            )
        self.probed_source_tags = source_tags.copy()
        self.tag_overrides = overrides
        self.tags = {**source_tags, **overrides}

    @model_validator(mode="after")
    def valid_edits(self) -> Self:
        """Check tempo ordering."""
        starts = [segment.start for segment in self.tempo]
        if starts != sorted(set(starts)):
            raise ValueError("Tempo segments must have unique, increasing start times")
        return self


class Group(BaseModel):
    """Shared audio settings for a collection of tracks."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    view: str = "catalog"
    normalization_target: float | None = None
    normalization_gain_db: float = 0
    gain_db: float = Field(default=0, ge=-12, le=12)
    normalize_target_lufs: float = Field(default=DEFAULT_TARGET_LUFS, ge=-30, le=0)
    normalize_peak_ceiling_db: float = Field(default=DEFAULT_PEAK_CEILING_DB, ge=-20, le=-0.1)
    trim_threshold_db: float = Field(default=SILENCE_THRESHOLD_DB, ge=-100, le=0)
    trim_min_duration: float = Field(default=0.1, gt=0, le=10)
    limiter_enabled: bool = True
    limiter_ceiling_db: float = Field(default=DEFAULT_PEAK_CEILING_DB, ge=-20, le=-0.1)
    tracks: list[Track] = Field(default_factory=list)

    @property
    def effective_gain_db(self) -> float:
        """Return combined group gain."""
        return self.normalization_gain_db + self.gain_db

    def limiter_for(self, track: Track) -> float | None:
        """Return the track override or enabled group ceiling."""
        if track.effects.limiter_ceiling_db is not None:
            return track.effects.limiter_ceiling_db
        return self.limiter_ceiling_db if self.limiter_enabled else None
