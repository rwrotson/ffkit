class FFKitError(Exception):
    """Base class for errors raised by the library."""


class InvalidInputError(FFKitError, ValueError):
    """The input cannot be processed."""
