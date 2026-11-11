import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ffkit import (
    Effects,
    Group,
    TempoSegment,
    Track,
    audio_files,
    audio_filters,
    normalization_gain,
    safe_name,
)
from ffkit.core.errors import FFKitError, InvalidInputError


def test_audio_models_preserve_mixtable_defaults_and_validation() -> None:
    track = Track(path="song.flac")
    group = Group(name="Mix", tracks=[track])
    assert track.effects == Effects()
    assert group.effective_gain_db == 0
    assert group.limiter_for(track) == -1
    group.limiter_enabled = False
    assert group.limiter_for(track) is None
    track.effects.limiter_ceiling_db = -3
    assert group.limiter_for(track) == -3
    group.normalization_gain_db = 2
    group.gain_db = 3
    assert group.effective_gain_db == 5
    assert issubclass(InvalidInputError, FFKitError)
    assert issubclass(InvalidInputError, ValueError)
    with pytest.raises(ValidationError):
        Track(path="song.flac", effects=Effects(trim_start=2, trim_end=1))
    with pytest.raises(ValidationError):
        Track(
            path="song.flac", tempo=[TempoSegment(start=2, bpm=100), TempoSegment(start=1, bpm=120)]
        )


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


def test_filters_use_fixed_notation_for_small_values() -> None:
    track = Track(path="song.flac", effects=Effects(trim_start=1e-5, gain_db=1e-5))
    assert audio_filters(track) == [
        "atrim=start=0.00001",
        "asetpts=PTS-STARTPTS",
        "volume=0.00001dB",
    ]


def test_filters_keep_mixtable_order_and_stream_rule() -> None:
    track = Track(path="song.flac")
    assert audio_filters(track) == []
    track.effects = Effects(
        trim_start=1, trim_end=4, trim_silence=True, gain_db=2, normalize_lufs=-14
    )
    expected = [
        "atrim=start=1.0:end=4.0",
        "asetpts=PTS-STARTPTS",
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-50dB",
        "areverse",
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-50dB",
        "areverse",
        "volume=5.0dB",
        "loudnorm=I=-14.0:TP=-1:LRA=11",
        "alimiter=limit=0.89125094:level=false:latency=true",
    ]
    assert audio_filters(track, 3, limiter_db=-1) == expected
    assert audio_filters(track, 3, streaming=True, limiter_db=-1) == [*expected[:3], *expected[6:]]
    track.effects.limiter_ceiling_db = -3
    assert (
        audio_filters(track, limiter_db=-1)[-1]
        == "alimiter=limit=0.70794578:level=false:latency=true"
    )
    track.effects = Effects(trim_end=4)
    assert audio_filters(track)[:2] == ["atrim=start=0.0:end=4.0", "asetpts=PTS-STARTPTS"]


def test_normalization_gain_limits_peak() -> None:
    assert normalization_gain(-20, -5) == 4.0
    assert normalization_gain(-18, None) == 4.0
    assert normalization_gain(-18, -10, target=-16, ceiling=-3) == 2.0
    assert normalization_gain(-14, -0.96) == -0.1
    assert normalization_gain(-18, -5.04) == 4.0
    assert normalization_gain(-18, -4.96) == 3.9
    with pytest.raises(ValueError, match="Cannot measure"):
        normalization_gain(None, None)
    with pytest.raises(ValueError, match="Cannot measure"):
        normalization_gain(float("nan"), None)
    with pytest.raises(ValueError, match="true peak"):
        normalization_gain(-14, float("inf"))


def test_safe_name_uses_tags_and_utf8_limit() -> None:
    track = Track(path="song.flac", tags={"artist": "A/B", "title": "T:Q"})
    assert safe_name(track, 0, 2) == "01. A_B - T_Q.mp3"
    assert safe_name(Track(path="song.flac"), 1, 2) == "02. song.mp3"
    assert safe_name(Track(path="x.flac", tags={"title": "."}), 0, 1) == "1. Untitled.mp3"
    assert len(safe_name(Track(path="x.flac", tags={"title": "é" * 200}), 0, 1).encode()) <= 255


def test_audio_files_resolves_deduplicates_and_sorts(tmp_path: Path) -> None:
    folder = tmp_path / "music"
    folder.mkdir()
    one = folder / "one.FLAC"
    two = folder / "two.mp3"
    ignored = folder / "note.txt"
    for path in (one, two, ignored):
        path.write_bytes(b"x")
    found = audio_files([folder, one, tmp_path / "missing.mp3", ignored])
    assert found == [one, two]


def test_audio_files_skip_hidden_files(tmp_path: Path) -> None:
    visible = tmp_path / "song.mp3"
    hidden = [tmp_path / "._song.mp3", tmp_path / ".song.0123.tmp.mp3"]
    for path in (visible, *hidden):
        path.write_bytes(b"x")
    assert audio_files([tmp_path, *hidden]) == [visible]
