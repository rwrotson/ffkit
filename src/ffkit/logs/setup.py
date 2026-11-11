import logging
import logging.handlers
import sys
from typing import TextIO

import structlog

from ffkit.logs.settings import LogSettings


class _AppFileHandler(logging.handlers.RotatingFileHandler):
    """Mark file handlers for replacement when logging is reconfigured."""


class _AppConsoleHandler(logging.StreamHandler[TextIO]):
    """Mark console handlers for replacement when logging is reconfigured."""


class _AppNullHandler(logging.NullHandler):
    """Prevent fallback stderr output when application console logging is disabled."""


def _prepare_handlers(
    config: LogSettings,
    console: bool,
    console_formatter: logging.Formatter,
    shared_processors: list[structlog.types.Processor],
) -> list[logging.Handler]:
    prepared: list[logging.Handler] = []
    try:
        if console:
            sh = _AppConsoleHandler(sys.stderr)
            sh.setLevel(config.console_level)
            sh.setFormatter(console_formatter)
            prepared.append(sh)
        else:
            prepared.append(_AppNullHandler())

        if config.dir is not None:
            logs_dir_path = config.dir.resolve()
            logs_dir_path.mkdir(parents=True, exist_ok=True)
            fh = _AppFileHandler(
                filename=logs_dir_path / config.file_name,
                maxBytes=config.file_max_bytes,
                backupCount=config.file_backup_count,
            )
            fh.setLevel(config.file_level)
            fh.setFormatter(
                structlog.stdlib.ProcessorFormatter(
                    processors=[
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.processors.JSONRenderer(),
                    ],
                    foreign_pre_chain=shared_processors,
                )
            )
            prepared.append(fh)
    except Exception:
        for handler in prepared:
            handler.close()
        raise
    return prepared


def setup_logging(config: LogSettings | None = None, *, console: bool = True) -> None:
    """Configure structlog and stdlib handlers for an application that uses the library."""
    if config is None:
        config = LogSettings()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    console_renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if config.format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    prepared = _prepare_handlers(config, console, console_formatter, shared_processors)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        if isinstance(handler, (_AppFileHandler, _AppConsoleHandler, _AppNullHandler)):
            root_logger.removeHandler(handler)
            handler.close()
    for handler in prepared:
        root_logger.addHandler(handler)
    root_logger.setLevel(config.level)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
