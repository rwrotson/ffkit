import json
import logging
import logging.handlers
from pathlib import Path

import pytest

from ffkit.config import LogSettings
from ffkit.utils.log import _AppConsoleHandler, _AppFileHandler, setup_logging

_EXPECTED_HANDLER_COUNT = 2


def _app_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h, (_AppFileHandler, _AppConsoleHandler))]


def test_setup_logging_without_dir_logs_only_to_console(
    clean_root_logger: logging.Logger,
) -> None:
    setup_logging(LogSettings())
    assert [type(h) for h in _app_handlers(clean_root_logger)] == [_AppConsoleHandler]


def test_setup_logging_reads_settings_when_called_without_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setenv("FFKIT_LOG__DIR", str(tmp_path))
    monkeypatch.setenv("FFKIT_LOG__LEVEL", "ERROR")
    setup_logging()
    assert clean_root_logger.level == logging.ERROR
    assert (tmp_path / "ffkit.log").exists()


def test_setup_logging_creates_log_dir(tmp_path: Path, clean_root_logger: logging.Logger) -> None:
    _ = clean_root_logger
    log_dir = tmp_path / "logs"
    setup_logging(LogSettings(dir=log_dir))
    assert log_dir.exists()


def test_setup_logging_does_not_add_duplicate_handlers(
    tmp_path: Path, clean_root_logger: logging.Logger
) -> None:
    config = LogSettings(dir=tmp_path / "logs")
    setup_logging(config)
    count_after_first = len(_app_handlers(clean_root_logger))
    setup_logging(config)
    assert len(_app_handlers(clean_root_logger)) == count_after_first


def test_setup_logging_preserves_unrelated_handlers(
    tmp_path: Path, clean_root_logger: logging.Logger
) -> None:
    foreign_console = logging.StreamHandler()
    foreign_file = logging.handlers.RotatingFileHandler(tmp_path / "foreign.log")
    clean_root_logger.addHandler(foreign_console)
    clean_root_logger.addHandler(foreign_file)

    config = LogSettings(dir=tmp_path / "app")
    setup_logging(config)
    setup_logging(config)

    assert foreign_console in clean_root_logger.handlers
    assert foreign_file in clean_root_logger.handlers
    assert sum(isinstance(h, _AppFileHandler) for h in clean_root_logger.handlers) == 1
    assert sum(isinstance(h, _AppConsoleHandler) for h in clean_root_logger.handlers) == 1


def test_setup_logging_replaces_own_handlers_on_reconfiguration(
    tmp_path: Path, clean_root_logger: logging.Logger
) -> None:
    setup_logging(LogSettings(dir=tmp_path / "first"))
    previous_file = next(
        handler for handler in clean_root_logger.handlers if isinstance(handler, _AppFileHandler)
    )

    setup_logging(
        LogSettings(
            dir=tmp_path / "second",
            file_name="changed.log",
            file_level="DEBUG",
            console_level="WARNING",
            format="json",
        )
    )

    assert len(_app_handlers(clean_root_logger)) == _EXPECTED_HANDLER_COUNT
    assert previous_file not in clean_root_logger.handlers
    assert previous_file.stream is None
    current_file = next(
        handler for handler in clean_root_logger.handlers if isinstance(handler, _AppFileHandler)
    )
    current_console = next(
        handler for handler in clean_root_logger.handlers if isinstance(handler, _AppConsoleHandler)
    )
    assert Path(current_file.baseFilename) == tmp_path / "second" / "changed.log"
    assert current_file.level == logging.DEBUG
    assert current_console.level == logging.WARNING

    clean_root_logger.warning("reconfigured")
    event = json.loads((tmp_path / "second" / "changed.log").read_text())
    assert event["event"] == "reconfigured"


def test_setup_logging_sets_root_level(tmp_path: Path, clean_root_logger: logging.Logger) -> None:
    setup_logging(LogSettings(dir=tmp_path / "logs", level="WARNING"))
    assert clean_root_logger.level == logging.WARNING


def test_setup_logging_json_formatter(
    tmp_path: Path, clean_root_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    config = LogSettings(dir=tmp_path / "logs", format="json")
    setup_logging(config)
    clean_root_logger.warning("json event")
    event = json.loads((tmp_path / "logs" / config.file_name).read_text())
    assert event["event"] == "json event"
    assert json.loads(capsys.readouterr().err)["event"] == "json event"


def test_library_records_reach_configured_handlers(
    clean_root_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    _ = clean_root_logger
    setup_logging(LogSettings(format="json", level="DEBUG"))
    logging.getLogger("ffkit.core.example").debug("from library")
    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "from library"
    assert event["logger"] == "ffkit.core.example"
