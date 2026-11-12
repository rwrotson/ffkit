import importlib
import math
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from ffkit import CancelledError, InvalidInputError, SourceChangedError, SourceNotFoundError
from ffkit.audio import AudioInfo, ChannelPeaks, Loudness, Waveform, measure_loudness, waveform

waveform_module = importlib.import_module("ffkit.audio.analysis.waveform")

STEREO_INFO = AudioInfo(duration=1.0, sample_rate=48000, channels=2, codec="pcm_s16le")


def _render(path: Path, source: str) -> None:
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-y",
            str(path),
        ],
        check=True,
    )


def _stderr(lines: list[str]) -> Iterator[bytes]:
    data = b"".join(f"[Parsed_ametadata_1 @ 0x1] {line}\n".encode() for line in lines)
    return iter([data[pos : pos + 7] for pos in range(0, len(data), 7)])


def test_waveform_matches_loudness_measurement(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source, duration=3)

    result = waveform(source)
    loudness = measure_loudness(source)

    assert result.loudness == loudness
    assert loudness.lufs is not None
    assert loudness.true_peak_db is not None
    peak = max(max(channel.maximum) for channel in result.channels)
    assert 20 * math.log10(peak) == pytest.approx(loudness.true_peak_db, abs=0.1)
    momentary = [value for value in result.momentary_lufs if value is not None]
    mean_power = sum(10 ** (value / 10) for value in momentary) / len(momentary)
    assert 10 * math.log10(mean_power) == pytest.approx(loudness.lufs, abs=0.5)


@pytest.mark.parametrize("bins", [1, 7, 400, 2000])
def test_waveform_returns_requested_bins(
    make_tone: Callable[..., None],
    tmp_path: Path,
    bins: int,
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)

    result = waveform(source, bins=bins)

    assert len(result.momentary_lufs) == bins
    assert result.bin_duration == pytest.approx(2 / bins)
    assert [len(peaks) for peaks in (result.channels[0].minimum, result.channels[0].maximum)] == [
        bins,
        bins,
    ]
    assert all(value is not None for value in result.momentary_lufs)


def test_waveform_places_a_delayed_stereo_onset(tmp_path: Path) -> None:
    source = tmp_path / "step.wav"
    _render(
        source,
        "aevalsrc=if(lt(t\\,1)\\,0\\,0.5*sin(2*PI*997*t))"
        "|if(lt(t\\,1)\\,0\\,-0.25*sin(2*PI*997*t)):s=48000:d=3",
    )

    result = waveform(source, bins=30)
    left, right = result.channels

    assert result.momentary_lufs[:9] == (None,) * 9
    assert all(value is not None for value in result.momentary_lufs[11:])
    assert max(left.maximum[:9]) == 0
    assert left.maximum[15] == pytest.approx(0.5, abs=0.01)
    assert left.minimum[15] == pytest.approx(-0.5, abs=0.01)
    assert right.maximum[15] == pytest.approx(0.25, abs=0.01)
    assert right.minimum[15] == pytest.approx(-0.25, abs=0.01)
    assert result.peak_levels()[15] == pytest.approx(0.5, abs=0.01)


def test_waveform_of_short_and_silent_audio(tmp_path: Path) -> None:
    short = tmp_path / "short.wav"
    silent = tmp_path / "silent.wav"
    _render(short, "sine=duration=0.13")
    _render(silent, "anullsrc=r=44100:cl=mono:d=0.6")

    short_result = waveform(short, bins=50)
    silent_result = waveform(silent)

    assert len(short_result.momentary_lufs) == 50
    assert max(short_result.channels[0].maximum) > 0
    assert silent_result.momentary_lufs == (None,) * 400
    assert silent_result.loudness.lufs is None
    assert silent_result.peak_levels() == (0.0,) * 400


def test_waveform_respects_cancellation_and_string_paths(
    make_tone: Callable[..., None],
    tmp_path: Path,
) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source, duration=1)

    with pytest.raises(CancelledError):
        waveform(source, cancelled=lambda: True)
    assert waveform(str(source), bins=10) == waveform(source, bins=10)


def test_waveform_rejects_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="at least one bin"):
        waveform(tmp_path / "song.wav", bins=0)
    with pytest.raises(SourceNotFoundError):
        waveform(tmp_path / "missing.wav", info=STEREO_INFO)


def test_waveform_parses_metadata_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "song.wav"
    source.touch()
    momentary = ["-120.691"] * 3 + ["-20", "-inf", "-20"]
    peaks = [
        line
        for frame in range(5)
        for line in (
            f"lavfi.astats.1.Min_level={-0.1 * (frame + 1):.6f}",
            f"lavfi.astats.1.Max_level={0.1 * (frame + 1):.6f}",
            "lavfi.astats.2.Min_level=nan",
            "lavfi.astats.2.Max_level=0.050000",
        )
    ]
    lines = [
        "frame:0    pts:0       pts_time:0",
        *(f"lavfi.r128.M={value}" for value in momentary),
        *peaks,
        "lavfi.r128.I=-21.000",
        "lavfi.r128.true_peak=0.500",
    ]
    monkeypatch.setattr(waveform_module, "iter_output", lambda *args, **kwargs: _stderr(lines))

    result = waveform(source, bins=4, info=STEREO_INFO)

    assert result.bin_duration == 0.25
    assert result.loudness.lufs == -21.0
    assert result.loudness.true_peak_db == pytest.approx(-6.02, abs=0.01)
    assert result.momentary_lufs == (-20.0, -23.0, -23.0, -23.0)
    assert result.channels == (
        ChannelPeaks(minimum=(-0.1, -0.2, -0.3, -0.5), maximum=(0.1, 0.2, 0.3, 0.5)),
        ChannelPeaks(minimum=(0.0,) * 4, maximum=(0.05,) * 4),
    )


def test_waveform_without_decoded_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.touch()
    monkeypatch.setattr(waveform_module, "iter_output", lambda *args, **kwargs: iter(()))

    result = waveform(source, bins=3, info=STEREO_INFO)

    assert result.momentary_lufs == (None, None, None)
    assert result.channels == ()
    assert result.peak_levels(floor_db=-60) == (0.0, 0.0, 0.0)


def test_waveform_rejects_changed_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    source.touch()

    def change_source(*args: object, **kwargs: object) -> Iterator[bytes]:
        source.write_bytes(b"changed")
        return iter(())

    monkeypatch.setattr(waveform_module, "iter_output", change_source)
    with pytest.raises(SourceChangedError, match="changed during waveform"):
        waveform(source, info=STEREO_INFO)


def test_waveform_display_levels() -> None:
    result = Waveform(
        bin_duration=1,
        loudness=Loudness(lufs=-14, true_peak_db=0),
        momentary_lufs=(None, -90.0, -30.0, 3.0),
        channels=(
            ChannelPeaks(minimum=(0.0, -0.031623, -0.5, -1.2), maximum=(0.0, 0.0005, 0.1, 1.0)),
            ChannelPeaks(minimum=(0.0, 0.0, -0.1, 0.0), maximum=(0.0, 0.0, 0.25, 0.5)),
        ),
    )

    assert result.peak_levels() == (0.0, 0.032, 0.5, 1.0)
    assert result.peak_levels(floor_db=-60) == (0.0, 0.5, 0.9, 1.0)
    assert result.loudness_levels() == (0.0, 0.0, 0.5, 1.0)
    assert result.loudness_levels(floor_lufs=-120) == (0.0, 0.25, 0.75, 1.0)
    for floor in (0.0, math.nan):
        with pytest.raises(InvalidInputError, match="Display floor"):
            result.peak_levels(floor_db=floor)
        with pytest.raises(InvalidInputError, match="Display floor"):
            result.loudness_levels(floor_lufs=floor)
