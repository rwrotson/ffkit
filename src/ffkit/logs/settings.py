from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
