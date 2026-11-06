# Getting Started

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

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

## Using the Library

```python
from ffkit import InvalidInputError, greet

greet("Ada")  # "Hello, Ada!"
```

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

See the [architecture guide](architecture.md) for the layers and error handling.

1. Create the code in `src/ffkit/core/slug.py`:

```python
from ffkit.core.errors import InvalidInputError


def slugify(text: str) -> str:
    """Convert text to a lowercase, hyphen-separated slug."""
    words = text.lower().split()
    if not words:
        raise InvalidInputError("text must not be empty")
    return "-".join(words)
```

2. Export it from `src/ffkit/core/__init__.py` and `src/ffkit/__init__.py`:

```python
from .core import InvalidInputError, FFKitError, greet, slugify

__all__ = ["InvalidInputError", "FFKitError", "greet", "slugify"]
```

3. Test it in `tests/core/test_slug.py` and add a row to `docs/reference/index.md`.

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
