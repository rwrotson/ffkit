import logging
from importlib.metadata import version
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from typer.core import TyperGroup

from ffkit import FFKitError
from ffkit.cli._shared import CLIState, OutputFormat, cli_state, report_error
from ffkit.cli.audio import audio
from ffkit.cli.settings import load_settings
from ffkit.logs import FILE_ONLY, setup_logging

log = logging.getLogger(__name__)


class CLIGroup(TyperGroup):
    """Report expected command failures without tracebacks."""

    def invoke(self, ctx: Any) -> Any:  # noqa: ANN401 - Typer uses a vendored Click context.
        """Convert input and processing errors to command exits."""
        try:
            return super().invoke(ctx)
        except typer.Exit:
            raise
        except (FFKitError, ValueError, OSError) as error:
            # Invalid input is a usage error; FFmpeg and other failures are processing errors.
            code = 2 if isinstance(error, (ValueError, FileNotFoundError)) else 1

            # The error is printed below, so the console handler skips this record.
            log.error(
                "command_failed error_type=%s error=%s",
                type(error).__name__,
                error,
                extra=FILE_ONLY,
            )
            report_error(cli_state(ctx).output_format, type(error).__name__, str(error))
            raise typer.Exit(code) from error


app = typer.Typer(cls=CLIGroup, help="FFmpeg audio helpers.", invoke_without_command=True)
app.add_typer(audio, name="audio")


@app.callback()
def root(
    ctx: typer.Context,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--output-format", "-f"),
    ] = OutputFormat.text,
    verbose: Annotated[bool, typer.Option("--verbose", "-V")] = False,
    show_version: Annotated[bool, typer.Option("--version", "-v", is_eager=True)] = False,
) -> None:
    """Prepare logging and output for one invocation."""
    if show_version:
        typer.echo(f"ffkit {version('ffkit')}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        # A missing command is a usage error, as in Click groups without this callback.
        typer.echo(ctx.get_help())
        raise typer.Exit(2)

    ctx.obj = CLIState(output_format)
    try:
        settings = load_settings()
    except ValidationError as error:
        report_error(output_format, "ValidationError", str(error), label="Invalid configuration")
        raise typer.Exit(2) from error

    log_settings = settings.log.model_copy(update={"level": "DEBUG"}) if verbose else settings.log
    setup_logging(log_settings, console=output_format != OutputFormat.json)
    ctx.obj = CLIState(output_format, settings.ffmpeg)
