# AGENTS.md

This file describes repository conventions for coding agents.

## Project Overview

A typed Python library of FFmpeg audio helpers, with room for future video helpers, optional structlog-based application logging, and an optional CLI configured through Pydantic Settings.

Distribution name: `ffkit` | Python package: `ffkit` | Environment prefix: `FFKIT_`

## Commands

This project uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
# Install dependencies
uv sync --all-groups --locked

# Tasks via poethepoet (uv run poe <name>)
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

# Or run tools directly
uv run ruff check .
uv run ruff format .
uv run mypy
uv run pytest
uv run pytest --cov

# Install pre-commit, commit-msg, and pre-push hooks
uv run pre-commit install

# Run pre-commit on all files
uv run pre-commit run --all-files

# Build the sdist and wheel
uv build

# Versioning
uv run cz bump           # bump version, update CHANGELOG, tag
uv run cz changelog      # update CHANGELOG only

# Build static docs site as CI does
uv run --group docs properdocs build --strict
```

## Dependencies

- Put runtime imports needed by the library in `[project].dependencies` and those of outer layers in their extra (`logs`, `cli`); also list extra packages in the `dev` group so tests can import them. Put development tools in the `dev` group, and documentation tools in the `docs` group.
- Keep runtime dependencies minimal and lower bounds wide enough for library consumers; they share one environment with the application.
- Change dependencies through uv (`uv add`, `uv remove`) so `pyproject.toml` and `uv.lock` change together. Verify the lock with `uv sync --locked --all-groups`.
- Raise a direct dependency's lower bound when code needs a newer API. The locked environment does not check lower bounds; the CI `lowest` job does.
- Do not import packages that are installed only as transitive dependencies.
- Security floors for transitive dependencies go in `[tool.uv] constraint-dependencies`.
- Use the project environment for tools. Do not install packages manually into `.venv`.

## Change Workflow

- Inspect `git status` before editing. Preserve existing uncommitted changes and limit edits to the requested task.
- Run `uv run poe check` after code changes. After documentation, `properdocs.yml`, or public docstring changes, also run `uv run --group docs properdocs build --strict`.
- Do not lower coverage thresholds, disable checks, relax import-linter contracts, or add lint and type suppressions solely to pass CI. Explain necessary suppressions at the affected line.
- Use non-rewriting checks (`poe fmt-check`, `poe lint`) for verification; run formatters or `--fix` only when intentionally editing files. Pre-commit's Ruff hooks rewrite files.
- Report which checks ran, which were skipped, and why. `poe test-fast` is not the full CI suite: it skips coverage, and CI also runs tests on macOS, the lowest-dependency job, package and docs builds, and security scans.
- Treat everything exported from `ffkit/__init__.py` and `ffkit/audio/__init__.py` as public API. Mark removals and incompatible changes with `!` or a `BREAKING CHANGE:` footer so Commitizen bumps the version correctly.
- When changing settings or public API, update `.env.example`, README, and the docs. Do not edit generated pages (configuration, API reference); edit `Settings` field descriptions and source docstrings instead.
- Keep the user's `.env` and secrets untracked.

## CI/CD

`.github/workflows/ci.yml` triggers on push/PR to `main` and `dev` and is reusable via
`workflow_call`. Workflow permissions are `contents: read`; actions are pinned to commit SHAs.
Parallel jobs:

- **`quality`** — `poe fmt-check`, `poe lint`, `poe lint-imports`, `poe typecheck`.
- **`test`** — `poe test` (95% branch coverage) on Ubuntu and macOS.
- **`lowest`** — installs the lowest allowed direct dependencies (`--resolution lowest-direct`)
  and runs pytest; it checks the declared lower bounds, which the lock does not.
- **`build`** — `uv build`, `properdocs build --strict`, `poe audit`, trivy filesystem scan
  (CRITICAL/HIGH).

`.github/workflows/release.yml` triggers on version tags (`v*`) and manual `workflow_dispatch`.
It runs CI first, then:

- **`build`** — `uv build`; uploads `dist/` as an artifact.
- **`docs`** — builds the site with `properdocs build --strict` and deploys it to **GitHub Pages** via
  `actions/upload-pages-artifact` + `actions/deploy-pages` (the `github-pages` environment).

Tagged versions are installed directly from GitHub. The build job and its distribution artifacts
remain available if package registry publishing is added later. Pages Source must be set to
**"GitHub Actions"** (Settings → Pages), and the
`github-pages` environment must allow the `v*` tag. Site:
https://rwrotson.github.io/ffkit/

Dependabot opens weekly grouped PRs for uv dependencies (`uv.lock`), GitHub Actions, and pre-commit
hooks (`.github/dependabot.yml`).

## Architecture

### Package Layout & Build

Source lives in `src/ffkit/` — the standard `src/` layout. The uv build backend is configured in `pyproject.toml`:

```toml
[tool.uv.build-backend]
module-name = "ffkit"
module-root = "src"
```

`src/ffkit/py.typed` marks the package as typed (PEP 561); keep it in the wheel.

Internal imports use the `ffkit.` prefix. Ruff bans relative imports except in package `__init__.py`, which may re-export from sibling modules (`from .module import ...`, never `..`):

```python
from ffkit.errors import InvalidInputError
from ffkit.logs import LogSettings
```

### Layers & Public API

```
src/ffkit/__init__.py  — Public API (FFmpegRuntime, errors, audio) with __all__; NullHandler on the "ffkit" logger
src/ffkit/audio/       — Public audio API (ffkit.audio): analysis/, processing/, and shared audio modules
src/ffkit/runtime.py   — FFmpegRuntime
src/ffkit/_ffmpeg/     — Private FFmpeg argument and process helpers
src/ffkit/errors.py    — FFKitError hierarchy
src/ffkit/logs/        — LogSettings and opt-in setup_logging() for applications (`ffkit[logs]` extra)
src/ffkit/cli/         — Typer CLI, its FFKIT_* settings, and composition root (`ffkit[cli]` extra)
src/ffkit/main.py      — `ffkit` console script; reports a missing `cli` extra
```

Follow the layers in `docs/architecture.md`. From top to bottom they are `main`, `cli`, `logs`, `audio`, `runtime | _ffmpeg`, and `errors`; a layer imports only layers below it. `main`, `cli`, and `logs` import library names only from `ffkit` and `ffkit.audio`. Import `_`-prefixed modules and packages only within their package and its subpackages. The library uses only Pydantic among third-party packages; `logs` adds structlog, and `cli` adds Pydantic Settings, Typer, and Rich. Inside `ffkit.audio`, `processing` (output) may import `analysis` (measurement), both use the shared base modules, and every module belongs to one layer listed in `docs/architecture.md`. import-linter contracts in `pyproject.toml` enforce these rules (`uv run poe lint-imports`).

The `FFKitError` hierarchy is available for future APIs. Existing audio helpers raise built-in and subprocess exceptions.

To add functionality: put measurement code in `src/ffkit/audio/analysis/`, output code in `src/ffkit/audio/processing/`, shared audio helpers in `src/ffkit/audio/`, and media-independent FFmpeg helpers in `src/ffkit/_ffmpeg/`; add the module to the audio layer contracts in `pyproject.toml` and `docs/architecture.md`; export supported names from `ffkit/audio/__init__.py` (subpackage `__init__.py` files stay empty); test it in the mirrored path under `tests/audio/`; and list it in `docs/reference/index.md`.

### Import-Time Behaviour

Importing `ffkit` must not read the environment or `.env`, configure logging or structlog, add handlers outside the `ffkit` logger, or perform I/O. `tests/test_package.py` checks this in a fresh interpreter.

### CLI Configuration via Environment Variables

`src/ffkit/cli/settings.py` defines the command's `Settings` (Pydantic `BaseSettings`, prefix `FFKIT_`, nested delimiter `__`) from library models: `log` is `LogSettings` (`FFKIT_LOG__*`) and `ffmpeg` is `FFmpegRuntime` (`FFKIT_FFMPEG__*`). Only `load_settings()` in the CLI reads the environment and `.env`; empty values use defaults. Library code never reads the environment and takes settings objects as arguments.

Every setting needs a `Field(description=...)` and a line in `.env.example`; tests in `tests/cli/test_settings.py` enforce both. The docs configuration page is generated from `Settings` by `docs/gen_config_page.py`; do not edit it by hand.

### Logging

Library code logs through stdlib `logging.getLogger(__name__)` so records follow the application's configuration; the package logger has a `NullHandler`. Do not call `structlog.configure()` or `logging.basicConfig()` from library code.

`setup_logging()` in `ffkit.logs` is an opt-in helper for applications. It configures structlog bridged through stdlib via `ProcessorFormatter`: a stderr handler (`ConsoleRenderer`, or JSON with `FFKIT_LOG__FORMAT=json`) and, when `FFKIT_LOG__DIR` is set, a rotating JSON file handler. Calling it again replaces only its own handlers.

### Documentation Generation

`docs/gen_ref_pages.py` generates API pages from source modules. `docs/gen_config_page.py` builds the configuration page from `Settings` field types, defaults, and descriptions.

### Testing

`tests/` mirrors the package (`audio/`, `_ffmpeg/`, `logs/`, `cli/`); `tests/test_package.py` covers the public API and import-time behaviour.

Tests run in parallel (pytest-xdist) and in random order (pytest-randomly); warnings are errors and each test has a 30-second timeout. Autouse fixtures in `tests/conftest.py` remove `FFKIT_*` variables, run each test in a temporary working directory (so a local `.env` is not read), and restore logging and structlog configuration. pytest adds its own capture handlers to the root logger, so assert on the library's handlers only. Reproduce an order-dependent failure with `uv run pytest -p randomly --randomly-seed=<seed>`.

### Type Checking

MyPy runs with `strict = true` and the Pydantic plugin over `src/`, `tests/`, and `docs/`. All new code must have complete type annotations. Python 3.14 supports union syntax (`X | Y`), which is preferred over `Optional[X]`.

## Commit Handoff

- Do not create or amend commits on the user's behalf.
- After completing and verifying a meaningful, self-contained part of the work, pause before starting the next part.
- At each pause, send the user a one-line English Conventional Commit message for the completed work. Resume when the user asks you to continue.

## Documentation and Comments

- Write documentation, docstrings, and comments in English. Keep them short and factual. Describe each entity's purpose without editorial commentary or tutorials.
- Do not add module docstrings. Package docstrings in `__init__.py` are optional. Put package behavior and important module details in Markdown documentation such as `README.md` or `docs/`.
- Give public classes, functions, and ordinary methods a docstring. Prefer one line describing their overall purpose; do not repeat names, signatures, or type annotations. Ruff checks these in library code. Test functions, fixtures, and standard `dunder` methods are exempt.
- Add docstrings to protected or private objects only when they explain behavior that is not clear from code.
- Keep inline comments only for non-obvious behavior or decisions. Put a short comment on the relevant line when it fits; otherwise place it immediately above. Retain necessary tool directives such as `# noqa` and `# type: ignore`.
- A comment placed above a group of lines applies only to that group. Separate the group from the next unrelated lines with a blank line so the comment's scope is clear.
- In long functions, methods, and tests, separate logical steps (input validation, setup, command building, execution, result handling; arrange, act, assert) with a single blank line. Do not add comments to label the steps. Keep short functions compact.
- Prefer clearer names and more precise types over comments that restate code.
