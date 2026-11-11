import os
import selectors
import subprocess
import time
from collections.abc import Iterator
from typing import IO

ERROR_TAIL_LIMIT = 1000


def error_tail(errors: IO[bytes]) -> str:
    """Return the last ``ERROR_TAIL_LIMIT`` bytes of a captured stderr file."""
    errors.seek(0, os.SEEK_END)
    errors.seek(max(0, errors.tell() - ERROR_TAIL_LIMIT))
    return errors.read().decode(errors="replace")


def stdout_chunks(process: subprocess.Popen[bytes], *, timeout: float) -> Iterator[bytes]:
    """Yield stdout until EOF and fail when reading and exit together exceed the timeout."""
    deadline = time.monotonic() + timeout
    if process.stdout is None:
        raise RuntimeError("FFmpeg stdout is unavailable")

    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise subprocess.TimeoutExpired(process.args, timeout)
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            yield chunk

    remaining = max(0, deadline - time.monotonic())
    if process.wait(timeout=remaining):
        raise subprocess.CalledProcessError(process.returncode, process.args)


def stop(process: subprocess.Popen[bytes], *, grace: float | None = None) -> None:
    """Stop a process that is still running and close its pipes.

    Without ``grace`` the process is killed; with it, the process is terminated and killed only
    when it does not exit within ``grace`` seconds.
    """
    if process.poll() is None:
        if grace is None:
            process.kill()
            process.wait()
        else:
            process.terminate()
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=grace)

    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()
