try:
    from .settings import LogSettings, Settings, load_settings
except ModuleNotFoundError as error:
    if error.name != "pydantic_settings":
        raise
    raise ModuleNotFoundError(
        "ffkit.config requires the 'app' extra; install 'ffkit[app]'", name=error.name
    ) from error

__all__ = ["LogSettings", "Settings", "load_settings"]
