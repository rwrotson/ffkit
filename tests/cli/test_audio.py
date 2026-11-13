import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import ffkit.cli.audio as cli_audio
from ffkit import FFmpegProcessError, FFmpegRuntime
from ffkit.audio import (
    AudioInfo,
    ChannelPeaks,
    Effects,
    Loudness,
    Mp3Encoding,
    TempoSegment,
    TrimBounds,
    Waveform,
)
from ffkit.cli.app import app

runner = CliRunner()


def test_existing_output_requires_force(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "output.mp3"
    source.write_bytes(b"input")
    destination.write_bytes(b"original")
    result = runner.invoke(app, ["audio", "render", str(source), str(destination)])
    assert result.exit_code == 2
    assert destination.read_bytes() == b"original"


def test_probe_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"input")

    def fake_probe(path: Path, *, runtime: FFmpegRuntime) -> AudioInfo:
        return AudioInfo(
            duration=12.5,
            sample_rate=44100,
            channels=1,
            codec="pcm_s16le",
            tags={"title": "Example"},
        )

    monkeypatch.setattr(cli_audio, "probe", fake_probe)
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", str(source)])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "path": str(source),
        "duration": 12.5,
        "sample_rate": 44100,
        "channels": 1,
        "codec": "pcm_s16le",
        "bit_rate": None,
        "has_cover": False,
        "tags": {"title": "Example"},
    }


def test_probe_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()

    def fake_probe(path: Path, *, runtime: FFmpegRuntime) -> AudioInfo:
        return AudioInfo(
            duration=5,
            sample_rate=44100,
            channels=1,
            codec="pcm_s16le",
            tags={"title": "[red]Example[/red]"},
        )

    monkeypatch.setattr(cli_audio, "probe", fake_probe)
    result = runner.invoke(app, ["audio", "probe", str(source)])
    assert result.exit_code == 0
    assert "[red]Example[/red]" in result.stdout


def test_text_output_keeps_lines_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / ("long-directory-name-" * 6) / "source.mp3"
    source.parent.mkdir()
    source.touch()
    title = "Fire :fire: " + "word " * 30

    def fake_probe(path: Path, *, runtime: FFmpegRuntime) -> AudioInfo:
        return AudioInfo(
            duration=5,
            sample_rate=44100,
            channels=1,
            codec="pcm_s16le",
            tags={"title": title},
        )

    monkeypatch.setattr(cli_audio, "probe", fake_probe)
    result = runner.invoke(app, ["audio", "probe", str(source)])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert f"Path: {source}" in lines
    assert f"title: {title}" in lines


def test_loudness_and_trim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    monkeypatch.setattr(
        cli_audio,
        "measure_loudness",
        lambda path, *, runtime: Loudness(lufs=-14.2, true_peak_db=-1.1),
    )
    calls: list[dict[str, object]] = []

    def fake_bounds(path: Path, **kwargs: object) -> TrimBounds:
        calls.append(kwargs)
        return TrimBounds(start=1.0, end=9.0)

    monkeypatch.setattr(cli_audio, "detect_trim_bounds", fake_bounds)

    loudness = runner.invoke(app, ["--output-format", "json", "audio", "loudness", str(source)])
    bounds = runner.invoke(
        app,
        ["audio", "trim-bounds", str(source), "--threshold-reference", "peak", "--padding", "0"],
    )
    assert json.loads(loudness.stdout) == {"lufs": -14.2, "true_peak_db": -1.1}
    assert "Start: 1.0 s" in bounds.stdout
    assert calls[0]["threshold_reference"] == "peak"
    assert calls[0]["padding"] == 0

    for option, value in [
        ("--min-duration", "0"),
        ("--min-duration", "11"),
        ("--threshold-db", "1"),
        ("--padding", "-1"),
        ("--threshold-reference", "loudest"),
    ]:
        invalid = runner.invoke(app, ["audio", "trim-bounds", str(source), option, value])
        assert invalid.exit_code == 2
        assert option in invalid.output


def test_render_force_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "output.mp3"
    source.touch()
    destination.write_bytes(b"original")

    def fake_render(source: Path, path: Path, effects: Effects, **kwargs: object) -> None:
        assert effects.gain_db == 3
        path.write_bytes(b"rendered")

    monkeypatch.setattr(cli_audio, "render", fake_render)
    result = runner.invoke(
        app,
        ["audio", "render", str(source), str(destination), "--force", "--gain-db", "3"],
    )
    assert result.exit_code == 0
    assert destination.read_bytes() == b"rendered"

    def fail_render(source: Path, path: Path, effects: Effects, **kwargs: object) -> None:
        raise FFmpegProcessError(1, "failed", command=["ffmpeg"])

    monkeypatch.setattr(cli_audio, "render", fail_render)
    failed = runner.invoke(app, ["audio", "render", str(source), str(destination), "--force"])
    assert failed.exit_code == 1
    assert destination.read_bytes() == b"rendered"


def test_cover_force_is_atomic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "cover.jpg"
    source.touch()
    destination.write_bytes(b"original")

    def fake_cover(source: Path, path: Path, *, runtime: FFmpegRuntime) -> Path:
        path.write_bytes(b"cover")
        return path

    monkeypatch.setattr(cli_audio, "extract_cover", fake_cover)
    result = runner.invoke(
        app,
        ["audio", "extract-cover", str(source), str(destination), "--force"],
    )
    assert result.exit_code == 0
    assert destination.read_bytes() == b"cover"

    monkeypatch.setattr(cli_audio, "extract_cover", lambda source, path, *, runtime: None)
    failed = runner.invoke(
        app,
        ["audio", "extract-cover", str(source), str(destination), "--force"],
    )
    assert failed.exit_code == 1
    assert destination.read_bytes() == b"cover"


def test_cover_source_matches_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    result = runner.invoke(app, ["audio", "extract-cover", str(source), str(source), "--force"])
    assert result.exit_code == 2


def test_render_cover_and_tags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    image = tmp_path / "cover.jpg"
    source.touch()
    image.touch()
    rendered: list[dict[str, object]] = []

    def fake_render(source: Path, path: Path, effects: Effects, **kwargs: object) -> None:
        rendered.append(kwargs)

    monkeypatch.setattr(cli_audio, "render", fake_render)

    base = ["audio", "render", str(source)]
    result = runner.invoke(
        app,
        [
            *base,
            str(tmp_path / "a.mp3"),
            "--cover",
            str(image),
            "--tag",
            "title=A=B",
            "--tag",
            "x=",
        ],
    )
    assert result.exit_code == 0
    assert rendered[-1]["tags"] == {"title": "A=B", "x": ""}

    result = runner.invoke(app, [*base, str(tmp_path / "b.mp3"), "--no-cover"])
    assert result.exit_code == 0

    result = runner.invoke(app, [*base, str(tmp_path / "e.mp3")])
    assert result.exit_code == 0
    assert [call["cover"] for call in rendered] == [image, False, True]

    for options in (["--tag", "title"], ["--tag", "=x"], ["--cover", str(image), "--no-cover"]):
        invalid = runner.invoke(app, [*base, str(tmp_path / "c.mp3"), *options])
        assert invalid.exit_code == 2
    missing = runner.invoke(app, [*base, str(tmp_path / "d.mp3"), "--cover", "missing.jpg"])
    assert missing.exit_code == 2
    assert len(rendered) == 3


def test_normalization_gain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    calls: list[tuple[float, float]] = []

    def fake_gain(
        path: Path,
        *,
        target_lufs: float,
        peak_ceiling_db: float,
        runtime: FFmpegRuntime,
    ) -> float:
        calls.append((target_lufs, peak_ceiling_db))
        return 2.5

    monkeypatch.setattr(cli_audio, "measure_normalization_gain", fake_gain)
    result = runner.invoke(
        app,
        ["-f", "json", "audio", "normalization-gain", str(source), "--target-lufs", "-16"],
    )
    assert json.loads(result.stdout) == {"gain_db": 2.5}
    assert calls == [(-16, -1)]

    text = runner.invoke(app, ["audio", "normalization-gain", str(source)])
    assert "Gain: 2.5 dB" in text.stdout
    invalid = runner.invoke(
        app,
        ["audio", "normalization-gain", str(source), "--peak-ceiling-db", "0"],
    )
    assert invalid.exit_code == 2


def test_render_encoding_and_silence_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli_audio, "render", lambda source, path, **kwargs: calls.append(kwargs))
    base = ["audio", "render", str(source)]

    result = runner.invoke(
        app,
        [
            *base,
            str(tmp_path / "out.mp3"),
            "--vbr-quality",
            "2",
            "--silence-threshold-db",
            "-40",
            "--silence-threshold-reference",
            "peak",
            "--silence-padding",
            "0.2",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["encoding"] == Mp3Encoding(vbr_quality=2)
    effects = calls[0]["effects"]
    assert isinstance(effects, Effects)
    assert effects.silence_threshold_db == -40
    assert effects.silence_threshold_reference == "peak"
    assert effects.silence_padding == 0.2
    for option, value in [("--vbr-quality", "10"), ("--bitrate-kbps", "8")]:
        invalid = runner.invoke(app, [*base, str(tmp_path / "bad.mp3"), option, value])
        assert invalid.exit_code == 2


def test_waveform_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    calls: list[int] = []
    result = Waveform(
        bin_duration=0.5,
        loudness=Loudness(lufs=-14.0, true_peak_db=-1.0, fingerprint=(1, 2, 3)),
        momentary_lufs=(None, -30.0),
        channels=(ChannelPeaks(minimum=(0.0, -0.5), maximum=(0.0, 1.0)),),
    )

    def measure(path: Path, *, bins: int, runtime: FFmpegRuntime) -> Waveform:
        calls.append(bins)
        return result

    monkeypatch.setattr(cli_audio, "waveform", measure)

    data = runner.invoke(app, ["-f", "json", "audio", "waveform", str(source), "--bins", "2"])
    text = runner.invoke(app, ["audio", "waveform", str(source)])
    invalid = runner.invoke(app, ["audio", "waveform", str(source), "--bins", "0"])

    assert calls == [2, 400]
    assert json.loads(data.stdout) == {
        "bin_duration": 0.5,
        "loudness": {"lufs": -14.0, "true_peak_db": -1.0},
        "momentary_lufs": [None, -30.0],
        "channels": [{"minimum": [0.0, -0.5], "maximum": [0.0, 1.0]}],
    }
    assert text.stdout.splitlines() == [
        "Loudness: -14.0 LUFS",
        "True peak: -1.0 dBTP",
        "Peaks: 0.0 1.0",
        "Momentary: 0.0 0.5",
    ]
    assert invalid.exit_code == 2


def test_tempo_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    segments = (TempoSegment(start=0, bpm=120, confidence=0.5),)
    monkeypatch.setattr(cli_audio, "estimate_tempo", lambda path, *, runtime: segments)

    result = runner.invoke(app, ["-f", "json", "audio", "tempo", str(source)])
    text = runner.invoke(app, ["audio", "tempo", str(source)])

    assert json.loads(result.stdout) == {
        "segments": [{"start": 0.0, "bpm": 120.0, "confidence": 0.5}],
    }
    assert "120.0 BPM" in text.stdout
    monkeypatch.setattr(cli_audio, "estimate_tempo", lambda path, *, runtime: ())
    assert "No tempo found" in runner.invoke(app, ["audio", "tempo", str(source)]).stdout


def test_text_output_names_missing_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    monkeypatch.setattr(
        cli_audio,
        "probe",
        lambda path, *, runtime: AudioInfo(
            duration=5,
            sample_rate=44100,
            channels=1,
            codec="pcm_s16le",
        ),
    )
    monkeypatch.setattr(
        cli_audio,
        "measure_loudness",
        lambda path, *, runtime: Loudness(lufs=None, true_peak_db=None),
    )
    monkeypatch.setattr(
        cli_audio,
        "detect_trim_bounds",
        lambda path, **kwargs: TrimBounds(start=0.5),
    )

    probed = runner.invoke(app, ["audio", "probe", str(source)])
    loudness = runner.invoke(app, ["audio", "loudness", str(source)])
    bounds = runner.invoke(app, ["audio", "trim-bounds", str(source)])

    assert "Bit rate: unknown" in probed.stdout
    assert "Loudness: below gate" in loudness.stdout
    assert "True peak: unknown" in loudness.stdout
    assert "End: end of file" in bounds.stdout
    assert "None" not in probed.stdout + loudness.stdout + bounds.stdout


def test_render_silence_min_duration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    received: list[Effects] = []

    def fake_render(source: Path, path: Path, effects: Effects, **kwargs: object) -> None:
        received.append(effects)

    monkeypatch.setattr(cli_audio, "render", fake_render)
    base = ["audio", "render", str(source)]

    result = runner.invoke(
        app,
        [*base, str(tmp_path / "a.mp3"), "--trim-silence", "--silence-min-duration", "0.5"],
    )

    assert result.exit_code == 0
    assert received[0].silence_min_duration == 0.5
    for value in ("0", "11"):
        invalid = runner.invoke(
            app,
            [*base, str(tmp_path / "b.mp3"), "--silence-min-duration", value],
        )
        assert invalid.exit_code == 2
        assert "--silence-min-duration" in invalid.output
