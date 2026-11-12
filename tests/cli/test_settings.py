import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from ffkit import FFmpegRuntime
from ffkit.cli.settings import Settings, env_fields, load_settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def test_settings_use_code_defaults() -> None:
    settings = load_settings()
    assert settings.log.level == "INFO"
    assert settings.log.format == "console"
    assert settings.log.dir is None


def test_nested_environment_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FFKIT_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("FFKIT_LOG__DIR", str(tmp_path))

    settings = load_settings()

    assert settings.log.level == "WARNING"
    assert settings.log.dir == tmp_path


def test_ffmpeg_section_loads_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFKIT_FFMPEG__FFMPEG_PATH", "/opt/ffmpeg/bin/ffmpeg")
    monkeypatch.setenv("FFKIT_FFMPEG__PROCESS_TIMEOUT", "60")

    settings = load_settings()

    assert settings.ffmpeg == FFmpegRuntime(
        ffmpeg_path="/opt/ffmpeg/bin/ffmpeg",
        process_timeout=60,
    )


def test_ffmpeg_section_validates_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFKIT_FFMPEG__STREAM_IDLE_TIMEOUT", "0")
    with pytest.raises(ValidationError):
        load_settings()


def test_process_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("FFKIT_LOG__LEVEL=ERROR\nFFKIT_LOG__FORMAT=json\n")
    monkeypatch.setenv("FFKIT_LOG__LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.log.level == "DEBUG"
    assert settings.log.format == "json"


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFKIT_LOG__DIR", "")
    assert load_settings().log.dir is None


def test_invalid_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFKIT_LOG__LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        load_settings()


def test_env_example_parses_to_defaults() -> None:
    assert Settings(_env_file=ENV_EXAMPLE) == Settings()


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#? ?(FFKIT_[A-Z_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    settings = {name for name, _ in env_fields()}
    assert settings - documented == set(), "add new settings to .env.example"
    assert documented - settings == set(), "remove stale settings from .env.example"


def test_every_setting_has_a_description() -> None:
    assert [name for name, field in env_fields() if not field.description] == []
