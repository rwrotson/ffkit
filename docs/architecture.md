# Architecture

The library does the work and knows nothing about settings, logging setup, or the CLI.
Each outer layer adds one application concern on top of the layers below it.

## Layers

Layers are listed from top to bottom. A layer may import any layer below it and never one above it.

| Layer | Location | Responsibility | Third-party packages | Install |
| --- | --- | --- | --- | --- |
| Entry point | `ffkit/main.py` | `ffkit` console script; reports a missing `cli` extra | — | base |
| CLI | `ffkit/cli/` | Composition root: loads `FFKIT_*` settings, sets up logging, passes values to the library, maps errors to exit codes | Pydantic Settings, Typer, Rich | `ffkit[cli]` |
| Logging setup | `ffkit/logs/` | `LogSettings` and `setup_logging()` for applications | structlog | `ffkit[logs]` |
| Media domains | `ffkit/audio/` | Audio models, helpers, and defaults | Pydantic, NumPy | base |
| FFmpeg | `ffkit/runtime.py`, `ffkit/_ffmpeg/` | `FFmpegRuntime`; private argument and process helpers | Pydantic | base |
| Errors | `ffkit/errors.py` | The `FFKitError` hierarchy | — | base |

The public API is `ffkit`, which exports `FFmpegRuntime`, the errors, and the `audio` package, and
`ffkit.audio`, which re-exports the audio functions, models, and defaults with `__all__`, and
`ffkit.audio.library`, which exports helpers for applications that manage audio files.
`ffkit/__init__.py` also attaches a `NullHandler` to the `ffkit` logger. A base install provides only
the library; `ffkit.logs` raises `ModuleNotFoundError` that names the `logs` extra when structlog is
missing.

### Rules

- `main`, `cli`, and `logs` import library names only from `ffkit`, `ffkit.audio`, and
  `ffkit.audio.library`, never from their modules.
- A module or package whose name starts with `_` is imported only by modules in the same package and
  its subpackages.
- The library never reads the environment or `.env`. Only the CLI does, in `ffkit.cli.settings`;
  an application composes its own settings from `LogSettings` and `FFmpegRuntime`.
- Library layers receive settings as arguments, such as `runtime=`, `target_lufs=`, or
  `setup_logging(LogSettings(...))`. A model lives in the module that uses it.
- A new third-party dependency belongs to the lowest layer that needs it, and to that layer's extra.

### Media domains

Media domains, such as `ffkit.audio` and a future `ffkit.video`, are sibling packages that do not
import each other. Code they share, such as `FFmpegRuntime` and the FFmpeg and subprocess helpers,
lives below them; `ffkit.errors` imports nothing from `ffkit`.

`ffkit.audio` has three subpackages on top of a shared base:

- `analysis` measures audio and returns data or immutable result models; it never creates output
  files or modifies its arguments.
- `processing` transforms audio into a new file or stream; it may use `analysis`.
- `library` discovers input files, names exports, and merges tags for applications; it does not run
  FFmpeg.

Layers are listed from top to bottom. Modules joined by `|` may not import each other:

| Package | Layer | Modules |
| --- | --- | --- |
| `ffkit.audio` | Operations | `library \| processing` |
| | Analysis | `analysis` |
| | Filters | `_filters` |
| | Models | `effects \| encoding` |
| | Defaults | `defaults` |
| `ffkit.audio.analysis` | Envelopes | `waveform \| tempo` |
| | Loudness | `loudness` |
| | Loudness metering | `_ebur128` |
| | Silence | `silence` |
| | Probe | `probe \| cover` |
| `ffkit.audio.processing` | Output | `render \| stream \| extract` |
| `ffkit.audio.library` | Helpers | `files \| tags` |
| `ffkit.cli` | Root command | `app` |
| | Command groups | `audio` |
| | Shared | `_shared \| settings` |

Every module in these packages must belong to one of their layers. The `__init__.py` files of
`analysis` and `processing` are empty; `ffkit/audio/__init__.py` re-exports from their modules, and
`ffkit/audio/library/__init__.py` re-exports the library helpers.

### Enforcement

import-linter checks the package layers, the audio layers, access to the library through `ffkit`
and its public packages, and the third-party packages of each layer (`uv run poe lint-imports`). The
contracts are in `pyproject.toml`. Rules that the contracts do not cover are checked in review.

## Public API

Everything listed in `ffkit.__all__`, `ffkit.audio.__all__`, and `ffkit.audio.library.__all__` is public and follows semantic versioning. Other modules can be imported but are not covered by compatibility guarantees, except `ffkit.logs`, which applications use for setup. A removal or incompatible change to the public API is a breaking change (`feat!:` or a `BREAKING CHANGE:` footer).

Audio effects are non-destructive: the source path is always the original file, and each render or
stream applies the current effects to that source. Changing an effect must never use a previous
render as input. Effect trim positions are relative to the original file.

## Import-time behaviour

`import ffkit` does not read the environment or `.env`, configure logging or structlog, add handlers outside the `ffkit` logger, or perform I/O. `tests/test_package.py` checks this in a fresh interpreter.

## Logging

Library modules log through `logging.getLogger(__name__)` and do not log the errors they raise;
the caller decides how to report them. The `NullHandler` on `ffkit` keeps records silent until the application configures logging, and records then follow the application's levels and handlers.

`ffkit.logs.setup_logging()` is a helper for applications that do not have their own setup:

1. Without arguments it uses the `LogSettings()` defaults; it never reads the environment.
2. It replaces the handlers it created before only after new handlers are ready and keeps all others.
3. It adds a stderr handler (console or JSON) unless `console=False`, and, when a log directory is set, a rotating JSON file handler. Records logged with `extra=FILE_ONLY` skip the stderr handler.
4. It configures structlog to render through the same stdlib handlers, so structlog and stdlib records share one format.

## Errors

| Error | Base classes | Raised when |
| --- | --- | --- |
| `FFKitError` | `Exception` | Base for every expected library failure |
| `InvalidInputError` | `FFKitError`, `ValueError` | The input cannot be processed |
| `SourceNotFoundError` | `InvalidInputError`, `FileNotFoundError` | An input file does not exist |
| `NoAudioError` | `InvalidInputError` | The source has no decodable audio stream or no measurable duration |
| `SilentAudioError` | `InvalidInputError` | The source or its selected range has no audible audio |
| `SourceChangedError` | `FFKitError` | The source file changed during an operation |
| `PeakCeilingError` | `FFKitError` | Rendered output cannot be kept below the true peak ceiling |
| `CancelledError` | `FFKitError`, `RuntimeError` | A `cancelled` callback stopped the operation |
| `FFmpegError` | `FFKitError` | FFmpeg or FFprobe failed or produced unusable output; `command` holds the arguments |
| `FFmpegNotFoundError` | `FFmpegError` | The configured executable cannot be started; `executable` names it |
| `FFmpegTimeoutError` | `FFmpegError`, `TimeoutError` | A run exceeded `process_timeout` or a stream `stream_idle_timeout` |
| `FFmpegProcessError` | `FFmpegError` | The process exited with a non-zero status; `returncode` and the `stderr` tail are kept |

All FFmpeg and FFprobe runs go through `ffkit._ffmpeg.process`, which closes stdin, logs each
command at debug level, enforces time limits and cancellation, and translates process failures to
`FFmpegError` subclasses. Pydantic `ValidationError` from models is not wrapped, nor are unexpected
exceptions. The CLI exits with code 2 for `ValueError` and `FileNotFoundError` and 1 for other
errors.

## Adding functionality

- Put measurement in `ffkit/audio/analysis/`, output in `ffkit/audio/processing/`, shared audio
  helpers in `ffkit/audio/`, and FFmpeg helpers that do not depend on the media type in
  `ffkit/_ffmpeg/`. Place a new module in one of the layers above, and raise a `FFKitError`
  subclass for expected failures.
- Accept values as arguments; do not read the environment.
- Public functions that run FFmpeg or FFprobe take a keyword-only `runtime: FFmpegRuntime` that defaults to `FFmpegRuntime()`
  and pass it on to internal helpers. They check the source with `existing_file()` before running FFmpeg.
- Export public names from `ffkit/audio/__init__.py` and add them to its `__all__`.
- Put default values that callers may need in `ffkit/audio/defaults.py`.
- Test the behaviour in `tests/`, in a file that mirrors the module path.
