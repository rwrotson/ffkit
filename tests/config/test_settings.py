import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from my_lib.config import Settings, load_settings
from my_lib.config.settings import env_fields

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def test_settings_use_code_defaults() -> None:
    settings = load_settings()
    assert settings.log.level == "INFO"
    assert settings.log.format == "console"
    assert settings.log.dir is None


def test_nested_environment_variables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MY_LIB_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("MY_LIB_LOG__DIR", str(tmp_path))

    settings = load_settings()

    assert settings.log.level == "WARNING"
    assert settings.log.dir == tmp_path


def test_process_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("MY_LIB_LOG__LEVEL=ERROR\nMY_LIB_LOG__FORMAT=json\n")
    monkeypatch.setenv("MY_LIB_LOG__LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.log.level == "DEBUG"
    assert settings.log.format == "json"


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_LIB_LOG__DIR", "")
    assert load_settings().log.dir is None


def test_invalid_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_LIB_LOG__LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        load_settings()


def test_env_example_parses_to_defaults() -> None:
    assert Settings(_env_file=ENV_EXAMPLE) == Settings()


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#? ?(MY_LIB_[A-Z_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    settings = {name for name, _ in env_fields()}
    assert settings - documented == set(), "add new settings to .env.example"
    assert documented - settings == set(), "remove stale settings from .env.example"


def test_every_setting_has_a_description() -> None:
    assert [name for name, field in env_fields() if not field.description] == []
