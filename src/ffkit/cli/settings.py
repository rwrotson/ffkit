from collections.abc import Iterator

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from ffkit import FFmpegRuntime
from ffkit.logs import LogSettings


class Settings(BaseSettings):
    """Load CLI settings from FFKIT_* variables and .env."""

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
    model: type[BaseModel] = Settings,
    prefix: str = "FFKIT_",
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
