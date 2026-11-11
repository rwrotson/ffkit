from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from ffkit.core.audio.runtime import FFmpegRuntime

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogSettings(BaseModel):
    """Console and optional rotating file logging."""

    level: LogLevel = Field(default="INFO", description="Root log level")
    console_level: LogLevel = Field(default="DEBUG", description="Minimum level printed to stderr")
    file_level: LogLevel = Field(default="INFO", description="Minimum level written to the file")
    format: Literal["console", "json"] = Field(
        default="console", description="Console log renderer; file logs are always JSON"
    )
    dir: Path | None = Field(
        default=None, description="Log directory; file logging is disabled if unset"
    )
    file_name: str = Field(
        default="ffkit.log", description="Log file basename without path separators"
    )
    file_max_bytes: int = Field(
        default=4 * 1024 * 1024, ge=0, description="File size that triggers rotation"
    )
    file_backup_count: int = Field(default=5, ge=0, description="Rotated files to keep")

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        """Keep the log file inside the configured directory."""
        if value in {"", ".", ".."} or "/" in value or "\\" in value:
            raise ValueError("Log file name must be a basename")
        return value


class Settings(BaseSettings):
    """Load library settings from FFKIT_* variables and .env."""

    model_config = SettingsConfigDict(
        env_prefix="FFKIT_",
        env_file=".env",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
    )

    log: LogSettings = Field(default_factory=LogSettings)
    ffmpeg: FFmpegRuntime = Field(default_factory=FFmpegRuntime)


def nested_model(field: FieldInfo) -> type[BaseModel] | None:
    """Return the settings model of a nested section, if the field is one."""
    for candidate in getattr(field.annotation, "__args__", (field.annotation,)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def env_fields(
    model: type[BaseModel] = Settings, prefix: str = "FFKIT_"
) -> Iterator[tuple[str, FieldInfo]]:
    """Yield every leaf setting with its environment variable name."""
    for name, field in model.model_fields.items():
        variable = f"{prefix}{name.upper()}"
        section = nested_model(field)
        if section is None:
            yield variable, field
        else:
            yield from env_fields(section, f"{variable}__")


def load_settings() -> Settings:
    """Load settings from the environment and .env."""
    return Settings()
