# ffkit

Typed FFmpeg helpers for audio processing, with optional application logging and settings.

## What Is Included

- Audio models and helpers for input discovery, probing, silence detection, waveform and tempo analysis, loudness measurement, normalization, MP3 rendering and streaming, and cover extraction; `py.typed` for type checkers
- Library-safe logging: stdlib loggers with a `NullHandler`, and no environment reads or logging configuration at import time
- An opt-in `ffkit.logs.setup_logging()` for applications (`ffkit[app]` extra): structlog to stderr (console or JSON) and an optional rotating JSON log file with UTC timestamps
- One Pydantic `Settings` with nested `FFKIT_LOG__*` and `FFKIT_FFMPEG__*` sections, a test that keeps `.env.example` in sync, and a generated configuration page
- import-linter contracts that keep the core API independent of configuration and logging setup
- Strict MyPy with the Pydantic plugin, Ruff, pytest in parallel and random order with a 95% branch coverage gate, poethepoet tasks, pre-commit hooks, Commitizen
- CI on Ubuntu and macOS with a lowest-dependency test job, package and strict docs builds, pip-audit, and trivy; actions pinned to commit SHAs; release artifacts and ProperDocs on GitHub Pages after CI passes on a release tag

## Stack

- **[structlog](https://www.structlog.org/)** — structured logging with context binding; dev console output or JSON for aggregators
- **[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** — environment-based configuration
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
| `app` | `ffkit.config` settings and `ffkit.logs.setup_logging()` | Pydantic Settings, structlog |
| `cli` | The `ffkit` command; includes `app` | Typer, Rich |

```bash
pip install "ffkit[app] @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"
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

from ffkit import (
    Effects,
    Track,
    audio_filters,
    calculate_normalization_gain,
    extract_cover,
    probe,
    render,
    stream_mp3,
)

track = probe(Track(path="song.flac", effects=Effects(gain_db=3)))
filters = audio_filters(track)
gain = calculate_normalization_gain(track)
render(track, Path("song.mp3"))
chunks = stream_mp3(track, start=0.5)
cover = extract_cover(track, Path("cover.jpg"))

track.effects.gain_db = 6
render(track, Path("song-updated.mp3"))
```

Keep `Track.path` pointed at the original audio file. Change `Effects` on that track and render or
stream from the original again. Never use a rendered output as the input for another effect change:
that would apply effects a second time to already processed audio. Effect trim bounds are positions
in the original file; `stream_mp3(start=...)` seeks from `trim_start` in that file before applying
the remaining effects. Leading silence removal applies only when streaming from `start=0`.
`audio_files()` skips hidden files, such as macOS `._*` files and in-progress render outputs.

`probe()` combines container tags with tags from the first audio stream. Stream tags take precedence
over container tags, and tags explicitly set on `Track` take precedence over both. Re-probing a track
refreshes source tags while preserving explicit tag overrides, including after a JSON round trip of
`Track`. The model includes `probed_source_tags` and `tag_overrides` to retain that distinction.
Rendering and normalization scan for trailing silence before processing when `trim_silence` is
enabled, so long tracks do not require buffering decoded audio in `areverse`.
Calling `audio_filters(track)` directly with `trim_silence=True` and the default
`streaming=False` still emits `areverse`, which can buffer the full decoded track.
An audible ending is retained even when it follows a pause close to the end of the selected range.
`detect_trim_bounds()` likewise keeps short audible tails after an internal pause.
`extract_cover()` replaces an existing destination only after extracting an image from the current
source; if no image exists, it returns `None` and preserves the destination. The destination must
differ from the source audio file.

`analyze_peak_waveform()` reads the source duration when the track has not been probed.
`Effects` validates trim bounds when they are changed as well as when the model is created.
Functions that run FFmpeg or FFprobe accept a keyword-only `runtime: FFmpegRuntime`, which sets the
executables and time limits. By default, `ffmpeg` and `ffprobe` are resolved from `PATH`, and each run
for probing, analysis, silence scanning, rendering, and cover extraction has a 15-minute
(`process_timeout=900`) deadline. `stream_mp3()` has no total deadline; it raises `TimeoutError`
when the encoder produces no output for `stream_idle_timeout` seconds (30 by default).

```python
from ffkit import FFmpegRuntime, Track, probe

runtime = FFmpegRuntime(ffmpeg_path="/opt/ffmpeg/bin/ffmpeg", process_timeout=3600)
track = probe(Track(path="song.flac"), runtime=runtime)
```
`Group` holds shared settings for an application. The library reads only `gain_db`,
`normalization_gain_db`, `limiter_enabled`, and `limiter_ceiling_db` through `effective_gain_db` and
`limiter_for()`; `view`, `normalization_target`, `normalize_target_lufs`,
`normalize_peak_ceiling_db`, `trim_threshold_db`, and `trim_min_duration` are application state that
callers pass to the corresponding functions themselves.
Normalization gains use 0.1 dB steps and round toward attenuation when a measured true-peak ceiling
would otherwise be exceeded. `calculate_normalization_gain()` reuses `Track.loudness_lufs` and
`Track.true_peak_db` only when no filters apply and `Track.analysis_source_stat` matches the source
file's `(st_size, st_mtime_ns, st_ctime_ns)`. `analyze_loudness()` measures the source and fills
all three fields.

The library logs through stdlib loggers under `ffkit` and stays silent until the application configures logging. An application with the `app` extra can use the bundled helper:

```python
from ffkit.config import LogSettings
from ffkit.logs import setup_logging

setup_logging(LogSettings(level="DEBUG", format="json"))
setup_logging()  # or read FFKIT_LOG__* variables and .env
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

`ffkit.config.Settings` defines defaults in code. `load_settings()` and `setup_logging()` without arguments read `FFKIT_*` environment variables and `.env`; the process environment wins. Sections are nested with `__`:

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
The library does not read `FFKIT_FFMPEG__*`; `load_settings().ffmpeg` is an `FFmpegRuntime` that an
application passes as `runtime=`, as the CLI does.

## Project Structure

```
src/
└── ffkit/
    ├── __init__.py          # public API (__all__), NullHandler
    ├── py.typed             # PEP 561 marker
    ├── core/
    │   ├── errors.py        # FFKitError, InvalidInputError
    │   └── audio/
    │       ├── analysis.py      # probing and audio analysis
    │       ├── cover.py         # embedded cover extraction
    │       ├── defaults.py      # public default values
    │       ├── filters.py       # FFmpeg filters and gain calculations
    │       ├── formats.py       # supported audio input discovery
    │       ├── models.py        # track, effects, and group models
    │       ├── normalization.py # processed-track gain calculation
    │       ├── render.py        # non-destructive MP3 rendering
    │       ├── runtime.py       # FFmpegRuntime: executables and time limits
    │       ├── silence.py       # silence detection parsing
    │       └── stream.py        # MP3 playback stream
    ├── config/
    │   └── settings.py      # Settings with the log and ffmpeg sections (ffkit[app])
    ├── logs/
    │   └── setup.py         # opt-in setup_logging() for applications (ffkit[app])
    ├── cli/
    │   └── app.py           # optional Typer commands (ffkit[cli])
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
