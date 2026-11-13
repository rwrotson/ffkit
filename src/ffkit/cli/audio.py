from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ffkit import FFKitError
from ffkit.audio import (
    DEFAULT_DISPLAY_FLOOR_DB,
    DEFAULT_MP3_BITRATE_KBPS,
    DEFAULT_PEAK_CEILING_DB,
    DEFAULT_SILENCE_PADDING,
    DEFAULT_SILENCE_THRESHOLD_DB,
    DEFAULT_TARGET_LUFS,
    DEFAULT_TRIM_MIN_DURATION,
    DEFAULT_WAVEFORM_BINS,
    Effects,
    Mp3Encoding,
    SilenceReference,
    detect_trim_bounds,
    estimate_tempo,
    extract_cover,
    measure_loudness,
    measure_normalization_gain,
    probe,
    render,
    waveform,
)
from ffkit.cli._shared import cli_state, emit, input_file, output_file, parse_tags


class ThresholdReference(StrEnum):
    """Level that a silence threshold is relative to."""

    full_scale = "full_scale"
    peak = "peak"


SILENCE_REFERENCES: dict[ThresholdReference, SilenceReference] = {
    ThresholdReference.full_scale: "full_scale",
    ThresholdReference.peak: "peak",
}

audio = typer.Typer(help="Inspect and process audio files.")


@audio.command("probe")
def probe_command(ctx: typer.Context, source: Path) -> None:
    """Read audio stream properties and tags."""
    source = input_file(source)
    info = probe(source, runtime=cli_state(ctx).runtime)
    emit(
        ctx,
        {"path": str(source), **info.model_dump()},
        [
            f"Path: {source}",
            f"Duration: {info.duration} s",
            f"Codec: {info.codec}",
            f"Sample rate: {info.sample_rate} Hz",
            f"Channels: {info.channels}",
            f"Bit rate: {info.bit_rate} bit/s",
            f"Cover: {'yes' if info.has_cover else 'no'}",
            *[f"{key}: {value}" for key, value in info.tags.items()],
        ],
    )


@audio.command("loudness")
def loudness_command(ctx: typer.Context, source: Path) -> None:
    """Measure integrated loudness and true peak."""
    loudness = measure_loudness(input_file(source), runtime=cli_state(ctx).runtime)
    emit(
        ctx,
        loudness.model_dump(exclude={"fingerprint"}),
        [f"Loudness: {loudness.lufs} LUFS", f"True peak: {loudness.true_peak_db} dBTP"],
    )


@audio.command("trim-bounds")
def trim_bounds_command(  # noqa: PLR0913, PLR0917 - Typer maps each parameter to a user option.
    ctx: typer.Context,
    source: Path,
    threshold_db: Annotated[
        float,
        typer.Option("--threshold-db", min=-100, max=0),
    ] = DEFAULT_SILENCE_THRESHOLD_DB,
    min_duration: Annotated[
        float,
        typer.Option("--min-duration", min=0, max=10),
    ] = DEFAULT_TRIM_MIN_DURATION,
    threshold_reference: Annotated[
        ThresholdReference,
        typer.Option("--threshold-reference", help="Full scale or the loudest window."),
    ] = ThresholdReference.full_scale,
    padding: Annotated[
        float,
        typer.Option("--padding", min=0, max=1, help="Silence kept at trimmed edges."),
    ] = DEFAULT_SILENCE_PADDING,
) -> None:
    """Find audible start and end positions."""
    if min_duration == 0:
        raise typer.BadParameter("must be greater than 0", param_hint="'--min-duration'")

    bounds = detect_trim_bounds(
        input_file(source),
        threshold_db=threshold_db,
        threshold_reference=SILENCE_REFERENCES[threshold_reference],
        min_duration=min_duration,
        padding=padding,
        runtime=cli_state(ctx).runtime,
    )
    emit(
        ctx,
        bounds.model_dump(),
        [f"Start: {bounds.start} s", f"End: {bounds.end} s"],
    )


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
    silence_threshold_db: Annotated[
        float,
        typer.Option("--silence-threshold-db", help="Level used by --trim-silence."),
    ] = DEFAULT_SILENCE_THRESHOLD_DB,
    silence_threshold_reference: Annotated[
        ThresholdReference,
        typer.Option("--silence-threshold-reference", help="Reference of --silence-threshold-db."),
    ] = ThresholdReference.full_scale,
    silence_padding: Annotated[
        float,
        typer.Option("--silence-padding", min=0, max=1, help="Silence kept by --trim-silence."),
    ] = DEFAULT_SILENCE_PADDING,
    limiter_ceiling_db: Annotated[float | None, typer.Option("--limiter-ceiling-db")] = None,
    cover: Annotated[
        Path | None,
        typer.Option("--cover", help="Image to embed instead of the source cover."),
    ] = None,
    no_cover: Annotated[
        bool,
        typer.Option("--no-cover", help="Do not embed a cover image."),
    ] = False,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Set a KEY=VALUE tag; repeatable."),
    ] = None,
    bitrate_kbps: Annotated[
        int,
        typer.Option("--bitrate-kbps", help="MP3 constant bit rate."),
    ] = DEFAULT_MP3_BITRATE_KBPS,
    vbr_quality: Annotated[
        int | None,
        typer.Option("--vbr-quality", help="LAME VBR quality 0-9; replaces the bit rate."),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Render audio as an MP3 with optional effects."""
    if cover is not None and no_cover:
        raise typer.BadParameter("cannot be combined with --no-cover", param_hint="'--cover'")

    tags = parse_tags(tag or [])
    source = input_file(source)
    cover_choice: Path | bool = not no_cover
    if cover is not None:
        cover_choice = input_file(cover)
    destination = output_file(destination, force)

    effects = Effects(
        gain_db=gain_db,
        normalize_lufs=target_lufs,
        trim_start=trim_start,
        trim_end=trim_end,
        trim_silence=trim_silence,
        silence_threshold_db=silence_threshold_db,
        silence_threshold_reference=SILENCE_REFERENCES[silence_threshold_reference],
        silence_padding=silence_padding,
        limiter_ceiling_db=limiter_ceiling_db,
    )
    encoding = Mp3Encoding(bitrate_kbps=bitrate_kbps, vbr_quality=vbr_quality)
    render(
        source,
        destination,
        effects=effects,
        tags=tags,
        cover=cover_choice,
        encoding=encoding,
        runtime=cli_state(ctx).runtime,
    )
    emit(ctx, {"path": str(destination)}, [str(destination)])


@audio.command("normalization-gain")
def normalization_gain_command(
    ctx: typer.Context,
    source: Path,
    target_lufs: Annotated[
        float,
        typer.Option("--target-lufs", min=-30, max=0),
    ] = DEFAULT_TARGET_LUFS,
    peak_ceiling_db: Annotated[
        float,
        typer.Option("--peak-ceiling-db", min=-20, max=-0.1),
    ] = DEFAULT_PEAK_CEILING_DB,
) -> None:
    """Calculate a fixed gain that reaches the target loudness within the peak ceiling."""
    gain = measure_normalization_gain(
        input_file(source),
        target_lufs=target_lufs,
        peak_ceiling_db=peak_ceiling_db,
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
    if extract_cover(source, destination, runtime=cli_state(ctx).runtime) is None:
        raise FFKitError("No embedded cover found")
    emit(ctx, {"path": str(destination)}, [str(destination)])


@audio.command("waveform")
def waveform_command(
    ctx: typer.Context,
    source: Path,
    bins: Annotated[
        int,
        typer.Option("--bins", min=1, max=100_000, help="Number of time bins."),
    ] = DEFAULT_WAVEFORM_BINS,
) -> None:
    """Report loudness, momentary loudness, and per-channel true peaks per time bin."""
    result = waveform(input_file(source), bins=bins, runtime=cli_state(ctx).runtime)
    emit(
        ctx,
        result.model_dump(exclude={"loudness": {"fingerprint"}}),
        [
            f"Loudness: {result.loudness.lufs} LUFS",
            f"True peak: {result.loudness.true_peak_db} dBTP",
            "Peaks: "
            + " ".join(
                str(level) for level in result.peak_levels(floor_db=DEFAULT_DISPLAY_FLOOR_DB)
            ),
            "Momentary: " + " ".join(str(level) for level in result.loudness_levels()),
        ],
    )


@audio.command("tempo")
def tempo_command(ctx: typer.Context, source: Path) -> None:
    """Estimate rough tempo segments."""
    segments = estimate_tempo(input_file(source), runtime=cli_state(ctx).runtime)
    emit(
        ctx,
        {"segments": [segment.model_dump() for segment in segments]},
        [
            f"{segment.start} s: {segment.bpm} BPM (confidence {segment.confidence})"
            for segment in segments
        ]
        or ["No tempo found"],
    )
