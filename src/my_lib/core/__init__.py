"""Public library API, independent of configuration and logging setup."""

from .errors import InvalidInputError, MyLibError
from .example import greet

__all__ = ["InvalidInputError", "MyLibError", "greet"]
