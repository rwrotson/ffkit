"""Public library API, independent of configuration and logging setup."""

from .errors import FFKitError, InvalidInputError
from .example import greet

__all__ = ["FFKitError", "InvalidInputError", "greet"]
