import json

import pytest
from pydantic import ValidationError

from ffkit import (
    Effects,
    TempoSegment,
    WaveformAnalysis,
)
from ffkit.core.errors import CancelledError, FFKitError, InvalidInputError


def test_audio_models_preserve_defaults_and_validation() -> None:
    effects = Effects()
    assert effects.effective_limiter_db(-1) == -1
    assert effects.effective_limiter_db(None) is None
    effects.limiter_ceiling_db = -3
    assert effects.effective_limiter_db(-1) == -3

    assert issubclass(InvalidInputError, FFKitError)
    assert issubclass(InvalidInputError, ValueError)
    assert issubclass(CancelledError, FFKitError)
    assert issubclass(CancelledError, RuntimeError)

    with pytest.raises(ValidationError):
        Effects(trim_start=2, trim_end=1)
    with pytest.raises(ValidationError, match="increasing start times"):
        WaveformAnalysis(tempo=(TempoSegment(start=2, bpm=100), TempoSegment(start=1, bpm=120)))
    with pytest.raises(ValidationError, match="frozen"):
        WaveformAnalysis().waveform = (1.0,)  # type: ignore[misc]  # Checks the frozen model at runtime.


def test_effects_reject_invalid_trim_assignment_without_mutation() -> None:
    effects = Effects(trim_end=4)
    with pytest.raises(ValidationError, match="Trim end must be later"):
        effects.trim_start = 5
    assert effects.trim_start == 0
    with pytest.raises(ValidationError, match="Trim end must be later"):
        effects.trim_end = 0
    assert effects.trim_end == 4


@pytest.mark.parametrize(
    "data",
    [{"trim_start": "5", "trim_end": "3"}, {"trim_start": 5, "trim_end": "5.0"}],
)
def test_effects_reject_invalid_trim_from_strings(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="Trim end must be later"):
        Effects.model_validate(data)
    with pytest.raises(ValidationError, match="Trim end must be later"):
        Effects.model_validate_json(json.dumps(data))


def test_effects_report_unconvertible_trim_as_field_error() -> None:
    with pytest.raises(ValidationError, match="trim_end") as error:
        Effects.model_validate({"trim_start": 1, "trim_end": "later"})
    assert "Trim end must be later" not in str(error.value)
