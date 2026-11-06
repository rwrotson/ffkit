import logging

import pytest

from my_lib.core import InvalidInputError, MyLibError, greet


def test_greet_returns_greeting() -> None:
    assert greet("Ada") == "Hello, Ada!"


@pytest.mark.parametrize("name", ["", "   "])
def test_greet_rejects_blank_name(name: str) -> None:
    with pytest.raises(InvalidInputError, match="must not be empty"):
        greet(name)


def test_greet_logs_through_package_logger(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="my_lib"):
        greet("Ada")
    assert [record.name for record in caplog.records] == ["my_lib.core.example"]


def test_invalid_input_error_is_library_and_value_error() -> None:
    assert issubclass(InvalidInputError, MyLibError)
    assert issubclass(InvalidInputError, ValueError)
