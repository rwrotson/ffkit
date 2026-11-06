class MyLibError(Exception):
    """Base class for errors raised by the library."""


class InvalidInputError(MyLibError, ValueError):
    """The input cannot be processed."""
