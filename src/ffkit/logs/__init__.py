try:
    from .settings import LogSettings
    from .setup import FILE_ONLY, setup_logging
except ModuleNotFoundError as error:
    if error.name != "structlog":
        raise
    raise ModuleNotFoundError(
        "ffkit.logs requires the 'logs' extra; install 'ffkit[logs]'",
        name=error.name,
    ) from error

__all__ = ["FILE_ONLY", "LogSettings", "setup_logging"]
