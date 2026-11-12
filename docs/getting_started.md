# Getting Started

## Requirements

- Python 3.14+
- Git for installation from the repository
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for development
- `ffmpeg` and `ffprobe` on `PATH`, or paths configured through `FFmpegRuntime`, for audio operations

## Installation

Install a release tag directly from GitHub (replace `vX.Y.Z` with a release tag):

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
git clone https://github.com/rwrotson/ffkit.git
cd ffkit
uv sync --all-groups --locked
uv run pre-commit install
```

`pre-commit install` sets up three Git hooks:

- `pre-commit` — file hygiene checks, `uv lock` check, actionlint, a check that `.gitignore` hides no source files, ruff (with `--fix`), import-linter, mypy
- `commit-msg` — Conventional Commit format (Commitizen)
- `pre-push` — pytest without coverage

Ruff and mypy run from the locked project environment (`uv run --no-sync`), so hook and CI versions match.

## Optional CLI

Install with `pip install "ffkit[cli] @ git+https://github.com/rwrotson/ffkit.git@vX.Y.Z"`, then run `ffkit audio --help`.
The `audio` group includes `probe`, `loudness`, `trim-bounds`, `normalization-gain`, `render`, and
`extract-cover`. `render` accepts `--cover PATH`, `--no-cover`, and repeated `--tag KEY=VALUE`.
Use `--output-format json` before `audio` for machine-readable output. Output files are protected
against replacement unless `--force` is passed.
Library `extract_cover()` replaces its destination only after successful extraction and keeps the
existing file when the source has no embedded image.
Filesystem errors are reported in the selected text or JSON output format.
In JSON mode, command errors are a single JSON object on stderr; library logs do not appear there.

```bash
ffkit audio probe song.flac
ffkit audio render song.flac song.mp3 --trim-start 1.5 --limiter-ceiling-db -1
```

## Using the Library

```python
from ffkit import FFmpegRuntime
from ffkit.audio import Effects, measure_loudness, probe, render

info = probe("song.flac")
loudness = measure_loudness("song.flac")
effects = Effects(gain_db=3, trim_silence=True)
render("song.flac", "song.mp3", effects=effects, tags={"title": "Song"})

runtime = FFmpegRuntime(ffmpeg_path="/opt/ffmpeg/bin/ffmpeg", process_timeout=3600)
render("song.flac", "song-quiet.mp3", effects=effects.replace(gain_db=-3), runtime=runtime)
```

- `ffkit` exports `FFmpegRuntime` and the errors, `ffkit.audio` the audio functions and models, and
  `ffkit.audio.library` file discovery, export names, and tag merging.
- Functions accept `str` or `os.PathLike` paths and keyword-only options, return immutable models,
  and never modify their arguments; the application keeps track state in its own models.
- The source is always the original file. To change processing, build new `Effects` (or call
  `effects.replace(...)`) and render or stream from the original again; trim bounds refer to the
  original file, and `stream(start=...)` seeks from `trim_start`.
- `render()` and `stream()` encode with `encoding=`, by default `Mp3Encoding()` at 320 kbit/s.
  `render()` replaces the destination only on success; its `cover` option is `True` (keep the source
  cover), `False`, or an image path.
- `measure_loudness()` records the file fingerprint for unfiltered measurements, and
  `measure_normalization_gain(known=...)` reuses that result while the file is unchanged.
- `trim_silence` and `detect_trim_bounds()` share one detector: 20 ms RMS windows of the loudest
  channel against a threshold relative to full scale or to the loudest window, with padding kept at
  trimmed edges. Pass bounds from `detect_trim_bounds()` as trims to avoid a scan per `stream()`.
- `detect_trim_bounds()` and `peak_envelope()` accept an earlier `AudioInfo` as `info=` instead of
  probing again.
- FFmpeg runs have a 15-minute deadline by default (`process_timeout`); `stream()` instead fails
  after `stream_idle_timeout` seconds without output. Long-running operations accept a `cancelled`
  callback.
- Expected failures raise `FFKitError` subclasses; see [Architecture](architecture.md#errors).

Configure logging in the application, or use the bundled helper from the `logs` extra:

```python
from ffkit.logs import LogSettings, setup_logging

setup_logging(LogSettings(level="DEBUG"))
```

## Development Commands

Tasks are available via [poethepoet](https://poethepoet.natn.io/) — run with `uv run poe <name>`:

```bash
uv run poe check        # fmt-check, lint, lint-imports, typecheck, test
uv run poe fmt          # ruff format .
uv run poe fmt-check    # ruff format --check .
uv run poe lint         # ruff check .
uv run poe lint-imports # import-linter layer contracts
uv run poe typecheck    # mypy (strict: src, tests, docs)
uv run poe test         # pytest (parallel, 95% branch coverage enforced)
uv run poe test-fast    # pytest without coverage, parallel, random order
uv run poe docs         # properdocs serve
uv run poe audit        # pip-audit over locked dependencies
```

Tests run in parallel and in random order. pytest-randomly prints the seed at the top of the run; reproduce an order-dependent failure with `uv run pytest -p randomly --randomly-seed=<seed>`. `poe test-fast` skips coverage; `poe check` runs the same quality and test steps as the CI `quality` and `test` jobs.

Or run the tools directly:

```bash
uv run pytest                        # full suite without coverage
uv run pytest --cov                  # with the coverage gate
uv run pytest tests/path/to/test.py  # single file
uv build                             # sdist and wheel in dist/
```

## Versioning & Changelog

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) — enforced by the `commit-msg` pre-commit hook.

```bash
uv run cz bump            # bump version, update CHANGELOG, create tag
uv run cz changelog       # update CHANGELOG without bumping
uv run cz changelog --dry-run
```

Bump type is inferred from commits: `fix:` → patch · `feat:` → minor · `feat!:` / `BREAKING CHANGE:` → major (minor while the version is `0.x`). Pushing the tag runs the release workflow, which builds distribution artifacts and deploys the docs. Install the tagged source directly from GitHub.

## Adding Functionality

Add measurement under `ffkit.audio.analysis` and output under `ffkit.audio.processing`, export supported names from `ffkit.audio`, and cover them in the mirrored path under `tests/audio`. Keep the library independent of environment loading and logging setup.

## Configuration

The `ffkit` command reads `FFKIT_*` environment variables or a `.env` file. Sections are nested with `__`:

| Prefix | Controls |
|--------|----------|
| `FFKIT_LOG__*` | Log levels, console renderer, optional log directory, file rotation |
| `FFKIT_FFMPEG__*` | FFmpeg and FFprobe executables and process time limits |

```env
FFKIT_LOG__LEVEL=DEBUG
FFKIT_LOG__FORMAT=json
FFKIT_FFMPEG__PROCESS_TIMEOUT=3600
```

The library does not read environment variables. An application composes its own settings from
`LogSettings` and `FFmpegRuntime` and passes them as `setup_logging(settings.log)` and
`runtime=settings.ffmpeg`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

from ffkit import FFmpegRuntime
from ffkit.logs import LogSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYAPP_", env_nested_delimiter="__")

    log: LogSettings = LogSettings()
    ffmpeg: FFmpegRuntime = FFmpegRuntime()
```

All variables are listed on the [configuration page](configuration.md).
