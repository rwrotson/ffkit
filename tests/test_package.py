import logging
import subprocess
import sys

import my_lib


def test_package_logger_has_null_handler() -> None:
    handlers = logging.getLogger("my_lib").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)


def test_public_api_names_exist() -> None:
    assert all(hasattr(my_lib, name) for name in my_lib.__all__)


def test_import_leaves_global_logging_unconfigured() -> None:
    code = (
        "import logging, structlog, my_lib; "
        "print(len(logging.getLogger().handlers), structlog.is_configured())"
    )
    # Run in a fresh interpreter: this process already configured logging in other tests.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["0", "False"]
