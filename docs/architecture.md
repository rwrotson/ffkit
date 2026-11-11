# Architecture

The core does the library's work and knows nothing about settings, logging setup, or the CLI.
Each outer layer adds one application concern on top of the layers below it.

## Layers

Layers are listed from top to bottom. A layer may import any layer below it and never one above it.

| Layer | Location | Responsibility | Third-party packages | Install |
| --- | --- | --- | --- | --- |
| Entry point | `ffkit/main.py` | `ffkit` console script; reports a missing `cli` extra | — | base |
| CLI | `ffkit/cli/` | Composition root: loads `FFKIT_*` settings, sets up logging, passes values to the core, maps errors to exit codes | Pydantic Settings, Typer, Rich | `ffkit[cli]` |
| Logging setup | `ffkit/logs/` | `LogSettings` and `setup_logging()` for applications | structlog | `ffkit[logs]` |
| Core | `ffkit/core/` | Audio models and helpers, defaults, and the `FFKitError` hierarchy | Pydantic | base |

`ffkit/__init__.py` is the public API: it re-exports the core with `__all__` and attaches a
`NullHandler` to the `ffkit` logger. A base install provides only the core; `ffkit.logs` raises
`ModuleNotFoundError` that names the `logs` extra when structlog is missing.

### Rules

- Layers outside the core import core names only from `ffkit`, never from `ffkit.core` or its modules.
- A module whose name starts with `_` is imported only by modules in the same package.
- The library never reads the environment or `.env`. Only the CLI does, in `ffkit.cli.settings`;
  an application composes its own settings from `LogSettings` and `FFmpegRuntime`.
- Library layers receive settings as arguments, such as `runtime=`, `target_lufs=`, or
  `setup_logging(LogSettings(...))`. A model lives in the layer that uses it.
- A new third-party dependency belongs to the lowest layer that needs it, and to that layer's extra.

### Inside the core

`core.audio` imports `core.errors`; `core.errors` imports nothing from `ffkit`. Future media
domains, such as `core.video`, are sibling packages that do not import each other.

Modules in `core.audio` are layered from top to bottom. Modules joined by `:` may import each other;
modules joined by `|` may not:

| Layer | Modules |
| --- | --- |
| Operations | `render : stream : normalization : cover` |
| Measurement | `analysis` |
| Primitives | `silence : filters : formats` |
| Models | `models : runtime` |
| Constants | `defaults \| _ffmpeg \| _process` |

Every module in `core.audio` must belong to one of these layers.

### Enforcement

import-linter checks the package layers, the core and audio layers, access to the core through
`ffkit`, and the third-party packages of each layer (`uv run poe lint-imports`). The contracts are
in `pyproject.toml`. Rules that the contracts do not cover are checked in review.

## Public API

Everything listed in `ffkit.__all__` is public and follows semantic versioning. Other modules can be imported but are not covered by compatibility guarantees, except `ffkit.logs`, which applications use for setup. A removal or incompatible change to the public API is a breaking change (`feat!:` or a `BREAKING CHANGE:` footer).

Audio effects are non-destructive: `Track.path` remains the original source, and each render or
stream applies the current effects to that source. Changing an effect must never use a previous
render as input. Effect trim positions are relative to the original file.

## Import-time behaviour

`import ffkit` does not read the environment or `.env`, configure logging or structlog, add handlers outside the `ffkit` logger, or perform I/O. `tests/test_package.py` checks this in a fresh interpreter.

## Logging

Library modules log through `logging.getLogger(__name__)`. The `NullHandler` on `ffkit` keeps records silent until the application configures logging, and records then follow the application's levels and handlers.

`ffkit.logs.setup_logging()` is a helper for applications that do not have their own setup:

1. Without arguments it uses the `LogSettings()` defaults; it never reads the environment.
2. It replaces the handlers it created before only after new handlers are ready and keeps all others.
3. It adds a stderr handler (console or JSON) unless `console=False`, and, when a log directory is set, a rotating JSON file handler.
4. It configures structlog to render through the same stdlib handlers, so structlog and stdlib records share one format.

## Errors

| Error | Base classes | Raised when |
| --- | --- | --- |
| `FFKitError` | `Exception` | Base for every expected library failure |
| `InvalidInputError` | `FFKitError`, `ValueError` | The input cannot be processed |
| `CancelledError` | `FFKitError`, `RuntimeError` | A `cancelled` callback stopped rendering or silence scanning |

Ported Mixtable audio helpers retain their original built-in and subprocess exceptions, except cancellation, which raises `CancelledError`. New APIs may use `FFKitError` subclasses for expected failures. Unexpected exceptions are not wrapped.

## Adding functionality

- Put the code in `core/`, place a new module in one of the audio layers, and raise a `FFKitError`
  subclass for expected failures.
- Accept values as arguments; do not read the environment.
- Public functions that run FFmpeg or FFprobe take a keyword-only `runtime: FFmpegRuntime | None`.
  Internal helpers receive only the fields they use, such as `ffmpeg` or `timeout`.
- Export public names from the package `__init__.py` files up to `ffkit/__init__.py`, and add them to `__all__`.
- Put default values that callers may need in `core/audio/defaults.py`.
- Test the behaviour in `tests/core/`.

`core/audio/` groups the audio models and helpers. Future media domains can use sibling packages under `core/`.
