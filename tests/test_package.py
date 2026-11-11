import logging
import subprocess
import sys

import pytest

import ffkit


def test_package_logger_has_null_handler() -> None:
    handlers = logging.getLogger("ffkit").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)


def test_public_api_names_exist() -> None:
    assert all(hasattr(ffkit, name) for name in ffkit.__all__)


def test_import_leaves_global_logging_unconfigured() -> None:
    code = (
        "import logging, structlog, ffkit; "
        "print(len(logging.getLogger().handlers), structlog.is_configured())"
    )
    # Run in a fresh interpreter: this process already configured logging in other tests.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["0", "False"]


def test_import_does_not_require_app_extra() -> None:
    code = (
        "import sys, ffkit; print('pydantic_settings' in sys.modules, 'structlog' in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["False", "False"]


@pytest.mark.parametrize(
    ("package", "missing"),
    [
        ("ffkit.config", "pydantic_settings"),
        ("ffkit.logs", "pydantic_settings"),
        ("ffkit.logs", "structlog"),
    ],
)
def test_app_packages_report_missing_extra(package: str, missing: str) -> None:
    # A None entry in sys.modules makes the import fail as if the package were not installed.
    code = (
        f"import sys; sys.modules[{missing!r}] = None\n"
        f"try:\n    import {package}\n"
        "except ModuleNotFoundError as error:\n    print(error.name, error)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.startswith(f"{missing} ")
    assert "ffkit[app]" in result.stdout
