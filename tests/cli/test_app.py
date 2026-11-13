import builtins
import json
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

import ffkit.cli.app as cli_app
import ffkit.cli.audio as cli_audio
from ffkit import FFmpegNotFoundError, FFmpegRuntime
from ffkit.audio import Loudness
from ffkit.cli.app import app
from ffkit.cli.settings import Settings
from ffkit.main import main

LOUDNESS = Loudness(lufs=-14.0, true_peak_db=-1.0)

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
    error = json.loads(result.stderr)["error"]
    assert error["type"] == "SourceNotFoundError"
    assert "Input file not found" in error["message"]
    assert "missing.mp3" in error["message"]


def test_json_processing_failure_has_one_error_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "broken.wav"
    source.write_bytes(b"invalid audio")
    monkeypatch.setenv("FFKIT_LOG__DIR", str(tmp_path / "logs"))

    result = runner.invoke(
        app,
        ["--output-format", "json", "audio", "render", str(source), str(tmp_path / "out.mp3")],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["type"] == "FFmpegProcessError"
    assert "audio_render_failed" in (tmp_path / "logs" / "ffkit.log").read_text()


def test_filesystem_errors_use_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    occupied = tmp_path / "occupied"
    occupied.write_text("file")

    result = runner.invoke(
        app,
        ["--output-format", "json", "audio", "render", str(source), str(occupied / "out.mp3")],
    )
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["type"] == "FileExistsError"

    monkeypatch.setenv("FFKIT_LOG__DIR", str(occupied))
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", str(source)])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["type"] == "FileExistsError"


def test_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_app() -> None:
        raise SystemExit(7)

    monkeypatch.setattr(cli_app, "app", fake_app)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 7


@pytest.mark.parametrize("missing", ["typer", "rich", "pydantic_settings", "structlog"])
def test_entrypoint_without_cli_extra(
    missing: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = builtins.__import__

    def missing_dependency(
        name: str,
        globals: Mapping[str, object] | None = None,  # noqa: A002 - Match __import__.
        locals: Mapping[str, object] | None = None,  # noqa: A002 - Match __import__.
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "ffkit.cli.app":
            raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_dependency)
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.touch()

    def missing_tool(path: Path, *, runtime: FFmpegRuntime) -> Loudness:
        raise FFmpegNotFoundError("ffmpeg")

    monkeypatch.setattr(cli_audio, "measure_loudness", missing_tool)
    result = runner.invoke(app, ["audio", "loudness", str(source)])
    assert result.exit_code == 1


def test_commands_use_configured_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    monkeypatch.setenv("FFKIT_FFMPEG__FFMPEG_PATH", "/opt/ffmpeg/bin/ffmpeg")
    monkeypatch.setenv("FFKIT_FFMPEG__PROCESS_TIMEOUT", "60")
    runtimes: list[FFmpegRuntime] = []

    def fake_loudness(path: Path, *, runtime: FFmpegRuntime) -> Loudness:
        runtimes.append(runtime)
        return Loudness(lufs=-14.0, true_peak_db=-1.0)

    monkeypatch.setattr(cli_audio, "measure_loudness", fake_loudness)
    result = runner.invoke(app, ["audio", "loudness", str(source)])
    assert result.exit_code == 0
    assert runtimes == [FFmpegRuntime(ffmpeg_path="/opt/ffmpeg/bin/ffmpeg", process_timeout=60)]


def test_missing_configured_ffprobe_is_processing_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    missing = tmp_path / "missing-ffprobe"
    monkeypatch.setenv("FFKIT_FFMPEG__FFPROBE_PATH", str(missing))
    result = runner.invoke(app, ["--output-format", "json", "audio", "probe", str(source)])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"]["type"] == "FFmpegNotFoundError"


def test_verbose_raises_log_level_without_changing_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp3"
    source.touch()
    settings = Settings()
    levels: list[str] = []
    monkeypatch.setattr(cli_app, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli_app,
        "setup_logging",
        lambda config, **kwargs: levels.append(config.level),
    )
    monkeypatch.setattr(cli_audio, "measure_loudness", lambda path, *, runtime: LOUDNESS)

    assert runner.invoke(app, ["-V", "audio", "loudness", str(source)]).exit_code == 0
    assert runner.invoke(app, ["audio", "loudness", str(source)]).exit_code == 0
    assert levels == ["DEBUG", "INFO"]
    assert settings.log.level == "INFO"
