import builtins
import json
import subprocess
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

import ffkit.cli.app as cli_app
from ffkit.cli.app import app
from ffkit.core.audio import Track
from ffkit.main import main

runner = CliRunner()


def test_help_and_version() -> None:
    assert runner.invoke(app, ["audio", "--help"]).exit_code == 0
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"ffkit {version('ffkit')}" in result.stdout


def test_no_command_shows_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "audio" in result.stdout
    assert "Usage" in result.stdout


def test_missing_input_reports_json_error() -> None:
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", "missing.mp3"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["type"] == "FileNotFoundError"


def test_json_processing_failure_has_one_error_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "broken.wav"
    source.write_bytes(b"invalid audio")
    monkeypatch.setenv("FFKIT_LOG__DIR", str(tmp_path / "logs"))
    result = runner.invoke(
        app, ["--output-format", "json", "audio", "render", str(source), str(tmp_path / "out.mp3")]
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["type"] == "CalledProcessError"
    assert "audio_render_failed" in (tmp_path / "logs" / "ffkit.log").read_text()


def test_existing_output_requires_force(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "output.mp3"
    source.write_bytes(b"input")
    destination.write_bytes(b"original")
    result = runner.invoke(app, ["audio", "render", str(source), str(destination)])
    assert result.exit_code == 2
    assert destination.read_bytes() == b"original"


def test_filesystem_errors_use_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    occupied = tmp_path / "occupied"
    occupied.write_text("file")
    result = runner.invoke(
        app, ["--output-format", "json", "audio", "render", str(source), str(occupied / "out.mp3")]
    )
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["type"] == "FileExistsError"

    monkeypatch.setenv("FFKIT_LOG__DIR", str(occupied))
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", str(source)])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["type"] == "FileExistsError"


def test_probe_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"input")

    def fake_probe(track: Track) -> Track:
        track.duration = 12.5
        track.tags = {"title": "Example"}
        return track

    monkeypatch.setattr(cli_app, "probe", fake_probe)
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", str(source)])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "path": str(source),
        "duration": 12.5,
        "tags": {"title": "Example"},
    }


def test_probe_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()

    def fake_probe(track: Track) -> Track:
        track.duration = 5
        track.tags = {"title": "[red]Example[/red]"}
        return track

    monkeypatch.setattr(cli_app, "probe", fake_probe)
    result = runner.invoke(app, ["audio", "probe", str(source)])
    assert result.exit_code == 0
    assert "[red]Example[/red]" in result.stdout


def test_loudness_and_trim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    monkeypatch.setattr(cli_app, "measure_loudness", lambda path: (-14.2, -1.1))
    monkeypatch.setattr(cli_app, "detect_trim_bounds", lambda path, **kwargs: (1.0, 9.0))
    loudness = runner.invoke(app, ["--output-format", "json", "audio", "loudness", str(source)])
    bounds = runner.invoke(app, ["audio", "trim-bounds", str(source)])
    assert json.loads(loudness.stdout) == {"loudness_lufs": -14.2, "true_peak_db": -1.1}
    assert "Start: 1.0 s" in bounds.stdout
    for option, value in [
        ("--min-duration", "0"),
        ("--min-duration", "11"),
        ("--threshold-db", "1"),
    ]:
        invalid = runner.invoke(app, ["audio", "trim-bounds", str(source), option, value])
        assert invalid.exit_code == 2
        assert option in invalid.output


def test_render_force_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "output.mp3"
    source.touch()
    destination.write_bytes(b"original")

    def fake_render(track: Track, path: Path) -> None:
        assert track.effects.gain_db == 3
        path.write_bytes(b"rendered")

    monkeypatch.setattr(cli_app, "render", fake_render)
    result = runner.invoke(
        app, ["audio", "render", str(source), str(destination), "--force", "--gain-db", "3"]
    )
    assert result.exit_code == 0
    assert destination.read_bytes() == b"rendered"

    def fail_render(track: Track, path: Path) -> None:
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    monkeypatch.setattr(cli_app, "render", fail_render)
    failed = runner.invoke(app, ["audio", "render", str(source), str(destination), "--force"])
    assert failed.exit_code == 1
    assert destination.read_bytes() == b"rendered"


def test_cover_force_is_atomic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "cover.jpg"
    source.touch()
    destination.write_bytes(b"original")

    def fake_cover(track: Track, path: Path) -> Path:
        path.write_bytes(b"cover")
        return path

    monkeypatch.setattr(cli_app, "extract_cover", fake_cover)
    result = runner.invoke(
        app, ["audio", "extract-cover", str(source), str(destination), "--force"]
    )
    assert result.exit_code == 0
    assert destination.read_bytes() == b"cover"
    monkeypatch.setattr(cli_app, "extract_cover", lambda track, path: None)
    failed = runner.invoke(
        app, ["audio", "extract-cover", str(source), str(destination), "--force"]
    )
    assert failed.exit_code == 1
    assert destination.read_bytes() == b"cover"


def test_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_app() -> None:
        raise SystemExit(7)

    monkeypatch.setattr(cli_app, "app", fake_app)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 7


def test_entrypoint_without_cli_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original_import = builtins.__import__

    def missing_typer(
        name: str,
        globals: Mapping[str, object] | None = None,  # noqa: A002 - Match __import__.
        locals: Mapping[str, object] | None = None,  # noqa: A002 - Match __import__.
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "ffkit.cli.app":
            raise ModuleNotFoundError("No module named 'typer'", name="typer")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_typer)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "ffkit[cli]" in capsys.readouterr().err


def test_invalid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFKIT_LOG__LEVEL", "INVALID")
    result = runner.invoke(app, ["audio", "probe", "missing.mp3"])
    assert result.exit_code == 2
    assert "Invalid configuration" in result.stderr
    json_result = runner.invoke(app, ["--output-format", "json", "audio", "probe", "missing.mp3"])
    assert json_result.exit_code == 2
    assert json.loads(json_result.stderr)["error"]["type"] == "ValidationError"


def test_missing_ffmpeg_is_processing_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp3"
    source.touch()

    def missing_tool(path: Path) -> tuple[float | None, float | None]:
        raise FileNotFoundError(2, "No such file or directory", "ffmpeg")

    monkeypatch.setattr(cli_app, "measure_loudness", missing_tool)
    result = runner.invoke(app, ["audio", "loudness", str(source)])
    assert result.exit_code == 1


def test_cover_source_matches_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    result = runner.invoke(app, ["audio", "extract-cover", str(source), str(source), "--force"])
    assert result.exit_code == 2
