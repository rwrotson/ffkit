import errno
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console

from ffkit import FFmpegRuntime, SourceNotFoundError


class OutputFormat(StrEnum):
    """Supported command output formats."""

    text = "text"
    json = "json"


@dataclass(frozen=True)
class CLIState:
    """Options shared by all commands of one invocation."""

    output_format: OutputFormat = OutputFormat.text
    runtime: FFmpegRuntime = field(default_factory=FFmpegRuntime)


def cli_state(ctx: typer.Context) -> CLIState:
    """Return the state stored by the root callback."""
    state = ctx.find_root().obj
    return state if isinstance(state, CLIState) else CLIState()


def emit(ctx: typer.Context, data: dict[str, object], lines: list[str]) -> None:
    """Write a result in the selected format."""
    if cli_state(ctx).output_format == OutputFormat.json:
        typer.echo(json.dumps(data))
    else:
        # Lines are data: wrapping or emoji codes would change paths and tag values.
        console = Console(soft_wrap=True, emoji=False)
        for line in lines:
            console.print(line, markup=False)


def report_error(
    output_format: OutputFormat,
    error_type: str,
    message: str,
    *,
    label: str = "Error",
) -> None:
    """Write an error to stderr in the selected format."""
    if output_format == OutputFormat.json:
        typer.echo(json.dumps({"error": {"type": error_type, "message": message}}), err=True)
    else:
        typer.echo(f"{label}: {message}", err=True)


def input_file(path: Path) -> Path:
    """Resolve and validate an input file."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SourceNotFoundError(errno.ENOENT, "Input file not found", str(path))
    return path


def output_file(path: Path, force: bool) -> Path:
    """Resolve an output path and enforce overwrite protection."""
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise ValueError(f"Output already exists: {path}; use --force")
    return path


def parse_tags(values: list[str]) -> dict[str, str]:
    """Parse repeated KEY=VALUE tag options."""
    tags: dict[str, str] = {}
    for value in values:
        key, separator, text = value.partition("=")
        if not separator or not key.strip():
            raise typer.BadParameter(f"expected KEY=VALUE, got {value!r}", param_hint="'--tag'")
        tags[key.strip()] = text
    return tags
