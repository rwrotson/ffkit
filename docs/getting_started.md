# Getting Started

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- `ffmpeg` and `ffprobe` on `PATH` for audio operations

## Installation

```bash
git clone <repo-url>
cd ffkit
uv sync --all-groups --locked
uv run pre-commit install
```

`pre-commit install` sets up three Git hooks:

- `pre-commit` — file hygiene checks, `uv lock` check, actionlint, ruff (with `--fix`), import-linter, mypy
- `commit-msg` — Conventional Commit format (Commitizen)
- `pre-push` — pytest without coverage

Ruff and mypy run from the locked project environment (`uv run --no-sync`), so hook and CI versions match.

## Optional CLI

Install with `pip install 'ffkit[cli]'`, then run `ffkit audio --help`.
The `audio` group includes `probe`, `loudness`, `trim-bounds`, `render`, and `extract-cover`.
Use `--output-format json` before `audio` for machine-readable output. Output files are protected
against replacement unless `--force` is passed.

```bash
ffkit audio probe song.flac
ffkit audio render song.flac song.mp3 --trim-start 1.5 --limiter-ceiling-db -1
```

## Using the Library

```python
from ffkit import Effects, Track, audio_filters

track = Track(path="song.flac", effects=Effects(gain_db=3))
filters = audio_filters(track)
```

`Effects` checks trim bounds on assignment. `analyze_peak_waveform()` also accepts a track whose
duration has not yet been populated by `probe()`.

Configure logging in the application, or use the bundled helper:

```python
from ffkit.config import LogSettings
from ffkit.utils.log import setup_logging

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

Bump type is inferred from commits: `fix:` → patch · `feat:` → minor · `feat!:` / `BREAKING CHANGE:` → major (minor while the version is `0.x`). Pushing the tag runs the release workflow, which publishes to PyPI and deploys the docs.

## Adding Functionality

Add audio operations under `ffkit.core.audio`, export supported names from `ffkit`, and cover them in `tests/core/audio`. Keep the core independent of environment loading and logging setup.

## Configuration

`load_settings()` and `setup_logging()` without arguments read environment variables or a `.env` file. Sections are nested with `__`:

| Prefix | Controls |
|--------|----------|
| `FFKIT_LOG__*` | Log levels, console renderer, optional log directory, file rotation |

```env
FFKIT_LOG__LEVEL=DEBUG
FFKIT_LOG__FORMAT=json
```

All variables are listed on the [configuration page](configuration.md).
