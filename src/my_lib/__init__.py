import logging

from .core import InvalidInputError, MyLibError, greet

# Records stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["InvalidInputError", "MyLibError", "greet"]
