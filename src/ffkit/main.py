import sys


def main() -> None:
    """Run the optional command-line interface."""
    try:
        # The console script exists for base installs, so resolve optional imports here.
        from ffkit.cli.app import app  # noqa: PLC0415
    except ModuleNotFoundError as error:
        if error.name not in {"typer", "rich"}:
            raise
        sys.stderr.write("CLI dependencies are missing. Install 'ffkit[cli]'.\n")
        raise SystemExit(1) from error
    app()
