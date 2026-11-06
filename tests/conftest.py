import logging
import os
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
import structlog


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's FFKIT_* variables and .env file out of every test."""
    for name in list(os.environ):
        if name.startswith("FFKIT_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """Undo global logging setup performed by a test."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    config = structlog.get_config()
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers, root.level = handlers, level
    structlog.configure(**config)


@pytest.fixture
def clean_root_logger() -> Generator[logging.Logger]:
    root = logging.getLogger()
    original_handlers, original_level = root.handlers[:], root.level
    root.handlers = []
    yield root
    for h in root.handlers:
        h.close()
    root.handlers = original_handlers
    root.setLevel(original_level)
