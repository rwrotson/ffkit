import json
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from typer.core import TyperGroup

from ffkit.config import load_settings
from ffkit.core.audio import (
    Effects,
    FFmpegRuntime,
    Track,
    calculate_normalization_gain,
    extract_cover,
    measure_loudness,
    probe,
    render,
)
from ffkit.core.audio._ffmpeg import (
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
    SILENCE_THRESHOLD_DB,
)
from ffkit.core.audio.analysis import detect_trim_bounds
from ffkit.utils.log import setup_logging


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


class CLIGroup(TyperGroup):
    """Report expected command failures without tracebacks."""

    def invoke(self, ctx: Any) -> Any:  # noqa: ANN401 - Typer uses a vendored Click context.
        """Convert input and processing errors to command exits."""
        try:
            return super().invoke(ctx)
        except typer.Exit:
            raise
        except (
            ValueError,
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            RuntimeError,
        ) as error:
            state = cli_state(ctx)
            missing_tool = isinstance(error, FileNotFoundError) and error.filename in {
                state.runtime.ffmpeg_path,
                state.runtime.ffprobe_path,
            }
            code = (
                2 if isinstance(error, (ValueError, FileNotFoundError)) and not missing_tool else 1
            )
            if state.output_format == OutputFormat.json:
                typer.echo(
                    json.dumps({"error": {"type": type(error).__name__, "message": str(error)}}),
                    err=True,
                )
            else:
                typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code) from error


app = typer.Typer(cls=CLIGroup, help="FFmpeg audio helpers.", invoke_without_command=True)
audio = typer.Typer(help="Inspect and process audio files.")
app.add_typer(audio, name="audio")


@app.callback()
def root(
    ctx: typer.Context,
    output_format: Annotated[
        OutputFormat, typer.Option("--output-format", "-f")
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
        if output_format == OutputFormat.json:
            typer.echo(
                json.dumps({"error": {"type": "ValidationError", "message": str(error)}}),
                err=True,
            )
        else:
            typer.echo(f"Invalid configuration: {error}", err=True)
        raise typer.Exit(2) from error
    if verbose:
        settings.log.level = "DEBUG"
    setup_logging(settings.log, console=output_format != OutputFormat.json)
    ctx.obj = CLIState(output_format, settings.ffmpeg)


def emit(ctx: typer.Context, data: dict[str, object], lines: list[str]) -> None:
    """Write a result in the selected format."""
    if cli_state(ctx).output_format == OutputFormat.json:
        typer.echo(json.dumps(data))
    else:
        console = Console()
        for line in lines:
            console.print(line, markup=False)


def input_file(path: Path) -> Path:
    """Resolve and validate an input file."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
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


def output_file(path: Path, force: bool) -> Path:
    """Resolve an output path and enforce overwrite protection."""
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise ValueError(f"Output already exists: {path}; use --force")
    return path


@audio.command("probe")
def probe_command(ctx: typer.Context, source: Path) -> None:
    """Read audio duration and tags."""
    track = probe(Track(path=str(input_file(source))), runtime=cli_state(ctx).runtime)
    data: dict[str, object] = {"path": track.path, "duration": track.duration, "tags": track.tags}
    emit(
        ctx,
        data,
        [
            f"Path: {track.path}",
            f"Duration: {track.duration} s",
            *[f"{key}: {value}" for key, value in track.tags.items()],
        ],
    )


@audio.command("loudness")
def loudness_command(ctx: typer.Context, source: Path) -> None:
    """Measure integrated loudness and true peak."""
    lufs, peak = measure_loudness(input_file(source), runtime=cli_state(ctx).runtime)
    emit(
        ctx,
        {"loudness_lufs": lufs, "true_peak_db": peak},
        [f"Loudness: {lufs} LUFS", f"True peak: {peak} dBTP"],
    )


@audio.command("trim-bounds")
def trim_bounds_command(
    ctx: typer.Context,
    source: Path,
    threshold_db: Annotated[
        float, typer.Option("--threshold-db", min=-100, max=0)
    ] = SILENCE_THRESHOLD_DB,
    min_duration: Annotated[
        float, typer.Option("--min-duration", min=0, max=10)
    ] = DEFAULT_TRIM_MIN_DURATION,
) -> None:
    """Find audible start and end positions."""
    if min_duration == 0:
        raise typer.BadParameter("must be greater than 0", param_hint="'--min-duration'")
    start, end = detect_trim_bounds(
        input_file(source),
        threshold_db=threshold_db,
        min_duration=min_duration,
        runtime=cli_state(ctx).runtime,
    )
    emit(ctx, {"start": start, "end": end}, [f"Start: {start} s", f"End: {end} s"])


@audio.command("render")
def render_command(  # noqa: PLR0913, PLR0917 - Typer maps each parameter to a user option.
    ctx: typer.Context,
    source: Path,
    destination: Path,
    gain_db: Annotated[float, typer.Option("--gain-db")] = 0,
    target_lufs: Annotated[float | None, typer.Option("--target-lufs")] = None,
    trim_start: Annotated[float, typer.Option("--trim-start")] = 0,
    trim_end: Annotated[float | None, typer.Option("--trim-end")] = None,
    trim_silence: Annotated[bool, typer.Option("--trim-silence")] = False,
    limiter_ceiling_db: Annotated[float | None, typer.Option("--limiter-ceiling-db")] = None,
    cover: Annotated[
        Path | None, typer.Option("--cover", help="Image to embed instead of the source cover.")
    ] = None,
    no_cover: Annotated[
        bool, typer.Option("--no-cover", help="Do not embed a cover image.")
    ] = False,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Set a KEY=VALUE tag; repeatable.")
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Render audio as an MP3 with optional effects."""
    if cover is not None and no_cover:
        raise typer.BadParameter("cannot be combined with --no-cover", param_hint="'--cover'")
    tags = parse_tags(tag or [])
    source = input_file(source)
    cover_path = None if cover is None else str(input_file(cover))
    destination = output_file(destination, force)
    effects = Effects(
        gain_db=gain_db,
        normalize_lufs=target_lufs,
        trim_start=trim_start,
        trim_end=trim_end,
        trim_silence=trim_silence,
        limiter_ceiling_db=limiter_ceiling_db,
    )
    track = Track(
        path=str(source),
        effects=effects,
        tags=tags,
        cover_path=cover_path,
        cover_removed=no_cover,
    )
    render(track, destination, runtime=cli_state(ctx).runtime)
    emit(ctx, {"path": str(destination)}, [str(destination)])


@audio.command("normalization-gain")
def normalization_gain_command(
    ctx: typer.Context,
    source: Path,
    target_lufs: Annotated[
        float, typer.Option("--target-lufs", min=-30, max=0)
    ] = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: Annotated[
        float, typer.Option("--peak-ceiling-db", min=-20, max=-0.1)
    ] = DEFAULT_PEAK_CEILING_DB,
) -> None:
    """Calculate a fixed gain that reaches the target loudness within the peak ceiling."""
    gain = calculate_normalization_gain(
        Track(path=str(input_file(source))),
        target_lufs,
        peak_ceiling_db,
        runtime=cli_state(ctx).runtime,
    )
    emit(ctx, {"gain_db": gain}, [f"Gain: {gain} dB"])


@audio.command("extract-cover")
def extract_cover_command(
    ctx: typer.Context,
    source: Path,
    destination: Path,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Extract an embedded cover as JPEG."""
    source = input_file(source)
    destination = output_file(destination, force)
    if extract_cover(Track(path=str(source)), destination, runtime=cli_state(ctx).runtime) is None:
        raise RuntimeError("No embedded cover found")
    emit(ctx, {"path": str(destination)}, [str(destination)])
