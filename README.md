# ffkit

Typed FFmpeg helpers for audio processing, with optional application logging and settings.

## What Is Included

- Audio models and helpers for input discovery, probing, silence detection, waveform and tempo analysis, loudness measurement, normalization, MP3 rendering and streaming, and cover extraction; `py.typed` for type checkers
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

## Getting Started

Install a tagged version directly from GitHub (replace `vX.Y.Z` with a release tag):

```bash
pip install "ffkit @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"
```

The base install provides the audio API and depends only on Pydantic. Extras add application layers:

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
ffkit audio trim-bounds song.flac --threshold-db -45
ffkit audio render song.flac song.mp3 --gain-db 3 --target-lufs -14
ffkit audio render song.flac song.mp3 --tag title=Intro --cover cover.jpg
ffkit audio normalization-gain song.flac --target-lufs -14 --peak-ceiling-db -1
ffkit audio extract-cover song.flac cover.jpg
```

`render` and `extract-cover` require `--force` to replace an existing output file.
`render` embeds the source cover unless `--cover PATH` replaces it or `--no-cover` drops it;
`--tag KEY=VALUE` sets a tag and may be repeated. `normalization-gain` prints the fixed gain that
reaches the target loudness without exceeding the true-peak ceiling.
The CLI runs `ffmpeg` and `ffprobe` from `PATH` unless `FFKIT_FFMPEG__FFMPEG_PATH` or
`FFKIT_FFMPEG__FFPROBE_PATH` is set.


```python
from pathlib import Path

from ffkit.audio import (
    Effects,
    extract_cover,
    measure_loudness,
    measure_normalization_gain,
    probe,
    render,
    stream_mp3,
)

source = Path("song.flac")
info = probe(source)
effects = Effects(gain_db=3)
loudness = measure_loudness(source)
gain = measure_normalization_gain(source, effects=effects, known=loudness)
render(source, "song.mp3", effects=effects, tags={"title": "Song"})
chunks = stream_mp3(source, effects=effects, start=0.5)
cover = extract_cover(source, Path("cover.jpg"))

louder = effects.replace(gain_db=6)
render(source, "song-updated.mp3", effects=louder)
```

Functions take source paths, `Effects`, and options, and return immutable results such as
`AudioInfo`, `Loudness`, `TrimBounds`, and `TempoSegment`; they never modify their arguments. The
application keeps track state, such as tags, covers, and analysis results, in its own models.

Always pass the original audio file as the source. To change processing, change `Effects` and render
or stream from the original again. Never use a rendered output as the input for another effect change:
that would apply effects a second time to already processed audio. Effect trim bounds are positions
in the original file; `stream_mp3(start=...)` seeks from `trim_start` in that file before applying
the remaining effects. Leading silence removal applies only when streaming from `start=0`.
`audio_files()` skips hidden files, such as macOS `._*` files and in-progress render outputs.

`probe()` returns the duration, sample rate, channels, codec, bit rate, and whether a cover is
embedded, and combines container tags with tags from the first audio stream; stream tags take
precedence over container tags. It raises `SourceNotFoundError` for a missing source. `merge_tags()` refreshes
source tags after a repeated probe while keeping tags the caller changed: pass the current tags, the
new and previous source tags, and the overrides from the previous `MergedTags`.
`render()` copies source metadata and writes `tags` over it. Its `cover` option keeps the source
cover (`True`, the default), writes no cover (`False`), or embeds an image file (a path).
Paths may be `str` or `os.PathLike`; options after the source and destination are keyword-only, and
long-running analysis and rendering accept a `cancelled` callback that raises `CancelledError`.
Rendering and normalization scan for trailing silence before processing when `trim_silence` is
enabled, so long tracks do not require buffering decoded audio in `areverse`.
An audible ending is retained even when it follows a pause close to the end of the selected range.
`detect_trim_bounds()` likewise keeps short audible tails after an internal pause.
`extract_cover()` replaces an existing destination only after extracting an image from the current
source; if no image exists, it returns `None` and preserves the destination. The destination must
differ from the source audio file. `embedded_cover()` returns the first embedded image as JPEG
bytes without writing a file.

`detect_trim_bounds()` and `peak_envelope()` probe the source unless an `AudioInfo` from an earlier
`probe()` is passed as `info=`. `waveform()` returns up to 400 loudness values scaled to the loudest
point, `peak_envelope()` 400 full-scale peaks from oversampled audio, and `estimate_tempo()` rough
`TempoSegment`s; each decodes the source once. `Effects` is immutable; `effects.replace(...)` returns a validated copy, so trim bounds are
checked together. `silence_threshold_db` sets the level used by `trim_silence`.
Functions that run FFmpeg or FFprobe accept a keyword-only `runtime: FFmpegRuntime`, which sets the
executables and time limits. By default, `ffmpeg` and `ffprobe` are resolved from `PATH`, and each run
for probing, analysis, silence scanning, rendering, and cover extraction has a 15-minute
(`process_timeout=900`) deadline. `stream_mp3()` has no total deadline; it raises `FFmpegTimeoutError`
when the encoder produces no output for `stream_idle_timeout` seconds (30 by default).

```python
from pathlib import Path

from ffkit import FFmpegRuntime
from ffkit.audio import probe

runtime = FFmpegRuntime(ffmpeg_path="/opt/ffmpeg/bin/ffmpeg", process_timeout=3600)
info = probe(Path("song.flac"), runtime=runtime)
```

Normalization gains use 0.1 dB steps and round toward attenuation when a measured true-peak ceiling
would otherwise be exceeded. `measure_loudness()` returns a `Loudness` with integrated loudness and
true peak; for an unfiltered measurement it also records the file's
`(st_size, st_mtime_ns, st_ctime_ns)` fingerprint. `measure_normalization_gain(known=...)` reuses
that result instead of measuring only when no filters apply and the fingerprint still matches.
`gain_for_target()` calculates the same gain from a `Loudness` without running FFmpeg. Measuring a
file that changes during the run raises `SourceChangedError`.

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
    │   ├── _filters.py      # FFmpeg filter chain
    │   ├── files.py         # audio input discovery and export names
    │   ├── tags.py          # tag merging
    │   ├── analysis/        # probe, loudness, silence, waveform, embedded cover
    │   └── processing/      # render, stream, cover extraction
    ├── logs/
    │   ├── settings.py      # LogSettings (ffkit[logs])
    │   └── setup.py         # opt-in setup_logging() for applications (ffkit[logs])
    ├── cli/
    │   ├── app.py           # optional Typer commands (ffkit[cli])
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
| `docs` | builds the docs with ProperDocs and deploys it to GitHub Pages via GitHub Actions |

Release tags are installable directly from GitHub. The build job and distribution artifacts are retained so package registry publishing can be added later. Set Pages Source to **GitHub Actions** and allow `v*` tags in the `github-pages` environment.

## Author

Igor Lashkov — rwrotson@yandex.ru
