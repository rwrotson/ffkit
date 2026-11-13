# ffkit

Typed FFmpeg helpers for audio processing, with optional application logging and settings.

## What Is Included

- Audio models and helpers for input discovery, probing, silence detection, waveform and tempo analysis, loudness measurement, normalization, rendering and streaming with a configurable encoder, and cover extraction; `py.typed` for type checkers
- Library-safe logging: stdlib loggers with a `NullHandler`, and no environment reads or logging configuration at import time
- An opt-in `ffkit.logs.setup_logging()` for applications (`ffkit[logs]` extra): structlog to stderr (console or JSON) and an optional rotating JSON log file with UTC timestamps
- One Pydantic `Settings` with nested `FFKIT_LOG__*` and `FFKIT_FFMPEG__*` sections, a test that keeps `.env.example` in sync, and a generated configuration page
- import-linter contracts that keep the library API independent of configuration and logging setup
- Strict MyPy with the Pydantic plugin, Ruff, pytest in parallel and random order with a 95% branch coverage gate, poethepoet tasks, pre-commit hooks, Commitizen
- CI on Ubuntu and macOS with a lowest-dependency test job, package and strict docs builds, pip-audit, and trivy; actions pinned to commit SHAs; release artifacts and ProperDocs on GitHub Pages after CI passes on a release tag

## Stack

- **[structlog](https://www.structlog.org/)** — structured logging with context binding; dev console output or JSON for aggregators
- **[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** — environment-based CLI configuration
- **[uv](https://docs.astral.sh/uv/)** — package management and build backend
- **[Ruff](https://docs.astral.sh/ruff/)** — linting and formatting
- **[MyPy](https://mypy.readthedocs.io/)** — strict type checking
- **[pytest](https://docs.pytest.org/)** + **[pytest-xdist](https://github.com/pytest-dev/pytest-xdist)** + **[pytest-randomly](https://github.com/pytest-dev/pytest-randomly)** — parallel tests in random order with coverage enforcement
- **[import-linter](https://import-linter.readthedocs.io/)** — layer boundary contracts
- **[poethepoet](https://poethepoet.natn.io/)** — task runner
- **[commitizen](https://commitizen-tools.github.io/commitizen/)** — Conventional Commits + automated versioning and CHANGELOG
- **[ProperDocs](https://properdocs.org/)** + **[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)** — documentation site

## Requirements

- Python 3.14+
- Git for installation from the repository; uv for development
- `ffmpeg` and `ffprobe` on `PATH`, or paths configured through `FFmpegRuntime`, for audio operations
- Linux or macOS; process pipes are read with `selectors`, which Windows does not support for pipes

## Getting Started

Install a tagged version directly from GitHub (replace `vX.Y.Z` with a release tag):

```bash
pip install "ffkit @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"
```

The base install provides the audio API and depends on Pydantic and NumPy. Extras add application layers:

| Extra | Adds | Packages |
| --- | --- | --- |
| `logs` | `ffkit.logs`: `LogSettings` and `setup_logging()` | structlog |
| `cli` | The `ffkit` command and its `FFKIT_*` settings; includes `logs` | Pydantic Settings, Typer, Rich |

```bash
pip install "ffkit[logs] @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"
```

For development in a clone of the repository:

```bash
uv sync --all-groups --locked

uv run pre-commit install
```

## Usage

Install the optional CLI with `pip install "ffkit[cli] @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"` (or `uv sync --extra cli` in a clone).
Run `ffkit --help` and `ffkit audio --help` to see the commands:

```bash
ffkit audio probe song.flac
ffkit --output-format json audio loudness song.flac
ffkit audio trim-bounds song.flac --threshold-db -60 --threshold-reference peak
ffkit audio render song.flac song.mp3 --gain-db 3 --target-lufs -14
ffkit audio render song.flac song.mp3 --tag title=Intro --cover cover.jpg
ffkit audio normalization-gain song.flac --target-lufs -14 --peak-ceiling-db -1
ffkit audio extract-cover song.flac cover.jpg
ffkit audio render song.flac song.mp3 --trim-silence --silence-threshold-db -45 --vbr-quality 2
ffkit audio waveform song.flac --bins 200
ffkit -f json audio tempo song.flac
```

`render` and `extract-cover` require `--force` to replace an existing output file.
`render` embeds the source cover unless `--cover PATH` replaces it or `--no-cover` drops it;
`--tag KEY=VALUE` sets a tag and may be repeated. `--silence-min-duration` sets the shortest edge
silence that `--trim-silence` removes. `normalization-gain` prints the fixed gain that
reaches the target loudness without exceeding the true-peak ceiling. `render` encodes MP3 at
`--bitrate-kbps` (320 by default) or LAME `--vbr-quality`. `waveform` prints loudness, true peak, and 400 (`--bins`)
peak and momentary loudness levels scaled to 0..1, and `tempo` prints rough tempo segments. JSON output uses the field names of the
library result models, such as `lufs` and `true_peak_db`. Exit code 2 marks invalid input, including a
missing input file, and 1 a processing failure.
The CLI runs `ffmpeg` and `ffprobe` from `PATH` unless `FFKIT_FFMPEG__FFMPEG_PATH` or
`FFKIT_FFMPEG__FFPROBE_PATH` is set.

### Library

The public API is `ffkit` (`FFmpegRuntime` and errors), `ffkit.audio` (audio functions and models),
and `ffkit.audio.library` (file discovery, export names, and tag merging, which do not run FFmpeg).

```python
from pathlib import Path

from ffkit.audio import (
    Effects,
    Mp3Encoding,
    extract_cover,
    measure_loudness,
    measure_normalization_gain,
    probe,
    render,
    stream,
)

source = Path("song.flac")
info = probe(source)
effects = Effects(gain_db=3)
loudness = measure_loudness(source)
gain = measure_normalization_gain(source, effects=effects, known=loudness)
render(source, "song.mp3", effects=effects, tags={"title": "Song"})
chunks = stream(source, effects=effects, start=0.5)
cover = extract_cover(source, "cover.jpg")

louder = effects.replace(gain_db=6)
render(source, "song-updated.mp3", effects=louder, encoding=Mp3Encoding(vbr_quality=2))
```

Paths may be `str` or `os.PathLike`, and options after the source and destination are
keyword-only. Functions return immutable results such as `AudioInfo`, `Loudness`, `TrimBounds`, and
`TempoSegment` and never modify their arguments; the application keeps track state, such as tags,
covers, and analysis results, in its own models.

#### Effects and output

- Always pass the original audio file as the source. To change processing, build new `Effects` and
  render or stream from the original again; a rendered output used as input would receive the
  effects twice.
- `Effects` is immutable; `effects.replace(...)` returns a validated copy, so trim bounds are
  checked together. Trim bounds are positions in the original file.
- `trim_silence` removes leading and trailing silence below `silence_threshold_db`, measured as
  20 ms RMS windows of the loudest channel. The threshold is relative to full scale or, with
  `silence_threshold_reference="peak"`, to the loudest window. Edge silence shorter than
  `silence_min_duration` (0.1 s by default) is kept, `silence_padding` seconds (0.05 by default) are kept at trimmed edges, and pauses inside the
  track stay. Rendering, normalization, and streaming find the bounds with a separate decode of the
  trimmed range, so long tracks are not buffered in memory.
- `stream(start=...)` resolves silence bounds first and then seeks from the audible start;
  `trim_silence` scans the range before the first chunk, so a player that seeks often can pass
  bounds from `detect_trim_bounds()` as `trim_start` and `trim_end` instead.
- `render()` and `stream()` encode with `encoding=`, which defaults to `Mp3Encoding()` (LAME,
  320 kbit/s CBR; set `vbr_quality` for VBR). `normalize_lufs` applies FFmpeg `loudnorm` (-70 to
  -5 LUFS) and keeps the source sample rate.
- `render()` writes to a temporary file and replaces the destination only on success. It copies
  source metadata and writes `tags` over it; `cover` keeps the source cover (`True`, the default),
  writes none (`False`), or embeds an image file. Tags of the first audio stream, where Ogg and Opus
  keep them, override container tags. A `limiter_ceiling_db` effect is verified on the
  encoded file and retried with a lower ceiling when the true peak exceeds it.
- `extract_cover()` likewise replaces the destination only after extracting an image; without an
  embedded image it returns `None`. `embedded_cover()` returns the image as JPEG bytes.
- A cover is a stream with the `attached_pic` disposition, as reported by `probe().has_cover`.
  Other video streams, such as the picture of a music video, are neither kept by `render()` nor
  returned by `embedded_cover()`.

#### Analysis

- `probe()` returns duration, sample rate, channels, codec, bit rate, whether a cover is embedded,
  and tags; tags of the first audio stream override container tags.
- `measure_loudness()` returns a `Loudness`: ITU-R BS.1770 integrated loudness and true peak from
  FFmpeg `ebur128`, with mono measured as dual-mono. For an unfiltered measurement it also records
  the file's `(st_size, st_mtime_ns, st_ctime_ns)` fingerprint, and
  `measure_normalization_gain(known=...)` reuses it only while no filters apply and the fingerprint
  matches. `gain_for_target()` calculates the gain from a `Loudness` without running FFmpeg. Gains
  use 0.1 dB steps and round toward attenuation to stay below the true-peak ceiling.
- `detect_trim_bounds()` returns the audible `TrimBounds` with the same detector, padding, and
  threshold reference options as `trim_silence`, and keeps short tails after an internal pause.
- `waveform()` returns a `Waveform` from one decode: the same `Loudness` as `measure_loudness()`,
  the power average of BS.1770 momentary loudness per bin, and per-channel `ChannelPeaks` minima and
  maxima of audio upsampled to 192 kHz like true-peak metering; `bins=` sets the bin count (400).
  `peak_levels()` and `loudness_levels()` scale them to 0..1 for display. `estimate_tempo()` returns
  rough `TempoSegment`s from one decode.
- `detect_trim_bounds()` and `waveform()` probe the source unless an earlier `AudioInfo` is passed as
  `info=`.

#### Library helpers

`ffkit.audio.library.audio_files()` finds supported audio files and skips hidden files, such as macOS
`._*` files and in-progress render outputs. `safe_name()` builds a numbered export name from tags,
with the `extension` of the chosen encoding. `merge_tags()` refreshes source tags after a repeated
probe while keeping tags the caller changed: pass the current tags, the new and previous source
tags, and the overrides from the previous `MergedTags`.

#### Runtime, cancellation, and errors

Functions that run FFmpeg or FFprobe accept a keyword-only `runtime: FFmpegRuntime` with the
executables and time limits. By default `ffmpeg` and `ffprobe` are resolved from `PATH`, and each
run has a 15-minute deadline (`process_timeout=900`). `stream()` has no total deadline; it raises
`FFmpegTimeoutError` when the encoder produces no output for `stream_idle_timeout` seconds (30 by
default). Long-running analysis, rendering, and streaming accept a `cancelled` callback; when it returns `True`,
FFmpeg is stopped and `CancelledError` is raised.

```python
from ffkit import FFmpegRuntime
from ffkit.audio import probe

runtime = FFmpegRuntime(ffmpeg_path="/opt/ffmpeg/bin/ffmpeg", process_timeout=3600)
info = probe("song.flac", runtime=runtime)
```

Expected failures raise `FFKitError` subclasses: `InvalidInputError` (also a `ValueError`) and its
`SourceNotFoundError`, `NoAudioError`, and `SilentAudioError`; `SourceChangedError`;
`PeakCeilingError`; `CancelledError`; and `FFmpegError` with `FFmpegNotFoundError`,
`FFmpegTimeoutError`, and `FFmpegProcessError`, which keeps the exit status and the end of stderr.
See [Architecture](https://rwrotson.github.io/ffkit/architecture/#errors) for the full table.

### Logging

The library logs through stdlib loggers under `ffkit` and stays silent until the application configures logging. An application with the `logs` extra can use the bundled helper:

```python
from ffkit.logs import LogSettings, setup_logging

setup_logging(LogSettings(level="DEBUG", format="json"))
setup_logging()  # defaults: INFO to stderr, no log file
```

## Development

Run development tasks with [poethepoet](https://poethepoet.natn.io/):

```bash
uv run poe check       # format check, lint, import contracts, type check, tests with coverage
uv run poe fmt
uv run poe test-fast
uv run poe docs
uv run poe audit
```

Or run the tools directly:

```bash
uv run pytest
uv run pytest tests/path/to/test.py
uv build
```

## Docs

```bash
uv run --group docs properdocs serve
uv run --group docs properdocs build
```

Source is in `docs/`. ProperDocs generates the API reference from public docstrings. The release workflow deploys the site to GitHub Pages.

## Versioning & Changelog

The repository uses [Conventional Commits](https://www.conventionalcommits.org/) enforced by a `commit-msg` pre-commit hook.

```bash
uv run cz bump

uv run cz changelog --dry-run
```

Bump type is inferred automatically: `fix:` → patch, `feat:` → minor, `feat!:` / `BREAKING CHANGE` → major (minor while the version is `0.x`).

## Configuration

The `ffkit` command reads `FFKIT_*` environment variables and `.env`; the process environment wins. Defaults live in `ffkit.cli.settings.Settings`. Sections are nested with `__`:

| Prefix | Controls |
|--------|----------|
| `FFKIT_LOG__*` | Log levels, console renderer, optional log directory, file rotation |
| `FFKIT_FFMPEG__*` | FFmpeg and FFprobe executables and process time limits |

```env
FFKIT_LOG__LEVEL=DEBUG
FFKIT_LOG__FORMAT=json
FFKIT_LOG__DIR=./logs
FFKIT_FFMPEG__FFMPEG_PATH=/opt/ffmpeg/bin/ffmpeg
```

See `.env.example` and the generated configuration page in the documentation site.
`FFKIT_LOG__FILE_NAME` must be a filename without directory separators; `FFKIT_LOG__DIR`
selects its directory.
The library does not read environment variables. An application composes its own settings from the
library models and passes them on: `setup_logging(settings.log)` and `runtime=settings.ffmpeg`.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

from ffkit import FFmpegRuntime
from ffkit.logs import LogSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYAPP_", env_nested_delimiter="__")

    log: LogSettings = LogSettings()
    ffmpeg: FFmpegRuntime = FFmpegRuntime()
```

## Project Structure

```
src/
└── ffkit/
    ├── __init__.py          # public API (__all__), NullHandler
    ├── py.typed             # PEP 561 marker
    ├── errors.py            # FFKitError hierarchy
    ├── runtime.py           # FFmpegRuntime: executables and time limits
    ├── _ffmpeg/             # private FFmpeg argument and process helpers
    ├── audio/               # public ffkit.audio API
    │   ├── defaults.py      # default values
    │   ├── effects.py       # Effects model
    │   ├── encoding.py      # output encoders: Mp3Encoding
    │   ├── _filters.py      # FFmpeg filter chain
    │   ├── library/         # ffkit.audio.library: input discovery, export names, tag merging
    │   ├── analysis/        # probe, loudness, silence, waveform, tempo, embedded cover
    │   └── processing/      # render, stream, cover extraction
    ├── logs/
    │   ├── settings.py      # LogSettings (ffkit[logs])
    │   └── setup.py         # opt-in setup_logging() for applications (ffkit[logs])
    ├── cli/
    │   ├── app.py           # optional Typer root command and error exits (ffkit[cli])
    │   ├── audio.py         # audio commands
    │   ├── _shared.py       # output, input, and tag helpers shared by commands
    │   └── settings.py      # FFKIT_* settings of the command
    └── main.py              # ffkit console script entry point
tests/                       # mirrors the package; test_package.py checks import-time behaviour
```

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main` and `dev`. Actions are pinned to commit SHAs.

| Job | What it does |
|-----|-------------|
| `quality` | ruff format check, ruff lint, import-linter contracts, strict mypy |
| `test` | parallel tests in random order on Ubuntu and macOS, 95% branch coverage enforced |
| `lowest` | tests against the lowest allowed direct dependencies |
| `build` | package build, `properdocs build --strict`, pip-audit, trivy filesystem scan (CRITICAL/HIGH) |

Dependabot opens weekly grouped PRs for uv dependencies, GitHub Actions, and pre-commit hooks.

`.github/workflows/release.yml` runs on version tags (`v*`) or via `workflow_dispatch`. It runs CI first, then:

| Job | What it does |
|-----|-------------|
| `build` | builds the sdist and wheel |
| `docs` | on tags only: builds the docs with ProperDocs and deploys them to GitHub Pages via GitHub Actions |

Release tags are installable directly from GitHub. The build job and distribution artifacts are retained so package registry publishing can be added later. Set Pages Source to **GitHub Actions** and allow `v*` tags in the `github-pages` environment.

## Author

Igor Lashkov — rwrotson@yandex.ru
