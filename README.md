# python-lib-template

A Python library template with a typed public API, optional structlog logging setup, and environment-based settings.

## What Is Included

- A `core/` layer with an example function and a `MyLibError` hierarchy, re-exported from `my_lib` with `__all__`; `py.typed` for type checkers
- Library-safe logging: stdlib loggers with a `NullHandler`, and no environment reads or logging configuration at import time
- An opt-in `setup_logging()` for applications: structlog to stderr (console or JSON) and an optional rotating JSON log file with UTC timestamps
- One Pydantic `Settings` with a nested `MY_LIB_LOG__*` section, a test that keeps `.env.example` in sync, and a generated configuration page
- import-linter contracts that keep the core API independent of configuration and logging setup
- Strict MyPy with the Pydantic plugin, Ruff, pytest in parallel and random order with a 95% branch coverage gate, poethepoet tasks, pre-commit hooks, Commitizen
- CI on Ubuntu and macOS with a lowest-dependency test job, package and strict docs builds, pip-audit, and trivy; actions pinned to commit SHAs; PyPI Trusted Publishing and ProperDocs on GitHub Pages after CI passes on a release tag

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
- uv

## Getting Started

```bash
uv sync --all-groups --locked

uv run pre-commit install
```

## Usage

```python
from my_lib import InvalidInputError, greet

greet("Ada")  # "Hello, Ada!"

try:
    greet("")
except InvalidInputError as error:
    ...
```

The library logs through stdlib loggers under `my_lib` and stays silent until the application configures logging. An application can use the bundled helper:

```python
from my_lib.config import LogSettings
from my_lib.utils.log import setup_logging

setup_logging(LogSettings(level="DEBUG", format="json"))
setup_logging()  # or read MY_LIB_LOG__* variables and .env
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

This template uses [Conventional Commits](https://www.conventionalcommits.org/) enforced by a `commit-msg` pre-commit hook.

```bash
uv run cz bump

uv run cz changelog --dry-run
```

Bump type is inferred automatically: `fix:` → patch, `feat:` → minor, `feat!:` / `BREAKING CHANGE` → major (minor while the version is `0.x`).

## Configuration

`my_lib.config.Settings` defines defaults in code. `load_settings()` and `setup_logging()` without arguments read `MY_LIB_*` environment variables and `.env`; the process environment wins. Sections are nested with `__`:

| Prefix | Controls |
|--------|----------|
| `MY_LIB_LOG__*` | Log levels, console renderer, optional log directory, file rotation |

```env
MY_LIB_LOG__LEVEL=DEBUG
MY_LIB_LOG__FORMAT=json
MY_LIB_LOG__DIR=./logs
```

See `.env.example` and the generated configuration page in the documentation site.

## Project Structure

```
src/
└── my_lib/
    ├── __init__.py          # public API (__all__), NullHandler
    ├── py.typed             # PEP 561 marker
    ├── core/
    │   ├── errors.py        # MyLibError, InvalidInputError
    │   └── example.py       # greet() example
    ├── config/
    │   └── settings.py      # Settings with the log section
    └── utils/
        ├── log.py           # opt-in setup_logging() for applications
        └── misc.py          # find_project_root()
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
| `publish` | publishes to PyPI with Trusted Publishing (tags only; skipped in the template repository) |
| `docs` | builds the docs with ProperDocs and deploys it to GitHub Pages via GitHub Actions |

In a project created from this template, configure a trusted publisher on PyPI with workflow `release.yml` and environment `pypi`. Set Pages Source to **GitHub Actions** and allow `v*` tags in the `github-pages` environment.

## Using This Template

The distribution, import package, and environment prefix have separate names. Follow the [renaming checklist](https://rwrotson.github.io/python-lib-template/notes/#renaming-the-template) when copying this template into a new project.

### Remove the Example

The example function is meant to be copied, then deleted. When your first real API exists, remove:

- `src/my_lib/core/example.py` and `tests/core/test_example.py`
- `greet` from `src/my_lib/core/__init__.py` and `src/my_lib/__init__.py`
- the `my_lib.core.example` row in `docs/reference/index.md` and the example in this README

Then run `uv run poe check` and `uv run --group docs properdocs build --strict`.

## Author

Igor Lashkov — rwrotson@yandex.ru
