# Architecture

The core API does the library's work and knows nothing about configuration or logging setup. Applications decide how to configure logging; the library only emits records.

| Layer | Location | Responsibility | May import |
| --- | --- | --- | --- |
| Public API | `my_lib/__init__.py` | Re-export supported names with `__all__`; attach a `NullHandler` | Core |
| Core | `my_lib/core/` | Library functionality and the `MyLibError` hierarchy | Core and the standard library |
| Configuration | `my_lib/config/` | `Settings` with defaults in code, loaded from `MY_LIB_*` and `.env` | Pydantic and the standard library |
| Utilities | `my_lib/utils/` | Opt-in logging setup and helpers for applications | Configuration and third-party libraries |

import-linter checks these boundaries with `uv run poe lint-imports`; the contracts are in `pyproject.toml`.

## Public API

Everything listed in `my_lib.__all__` is public and follows semantic versioning. Other modules can be imported but are not covered by compatibility guarantees, except `my_lib.config` and `my_lib.utils.log`, which applications use for setup. A removal or incompatible change to the public API is a breaking change (`feat!:` or a `BREAKING CHANGE:` footer).

## Import-time behaviour

`import my_lib` does not read the environment or `.env`, configure logging or structlog, add handlers outside the `my_lib` logger, or perform I/O. `tests/test_package.py` checks this in a fresh interpreter.

## Logging

Library modules log through `logging.getLogger(__name__)`. The `NullHandler` on `my_lib` keeps records silent until the application configures logging, and records then follow the application's levels and handlers.

`my_lib.utils.log.setup_logging()` is a helper for applications that do not have their own setup:

1. Without arguments it loads `LogSettings` from `MY_LIB_LOG__*` and `.env`.
2. It replaces the handlers it created before and keeps all others.
3. It adds a stderr handler (console or JSON) and, when a log directory is set, a rotating JSON file handler.
4. It configures structlog to render through the same stdlib handlers, so structlog and stdlib records share one format.

## Errors

| Error | Base classes | Raised when |
| --- | --- | --- |
| `MyLibError` | `Exception` | Base for every expected library failure |
| `InvalidInputError` | `MyLibError`, `ValueError` | The input cannot be processed |

Callers can catch `MyLibError` for all library failures or the built-in base for a specific one. Add a subclass for each new kind of expected failure. Unexpected exceptions are not wrapped.

## Adding functionality

- Put the code in `core/` and raise a `MyLibError` subclass for expected failures.
- Accept settings or values as arguments; do not call `load_settings()` from the core.
- Export public names from `core/__init__.py` and `my_lib/__init__.py`, and add them to `__all__`.
- Test the behaviour in `tests/core/`.

`core/example.py` shows this pattern.
