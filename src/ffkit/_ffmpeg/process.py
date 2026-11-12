import logging
import os
import selectors
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator, Sequence
from typing import IO, Literal, cast

from ffkit.errors import CancelledError, FFmpegNotFoundError, FFmpegProcessError, FFmpegTimeoutError

log = logging.getLogger(__name__)

type Cancelled = Callable[[], bool]

ERROR_TAIL_LIMIT = 1000
CHUNK_SIZE = 65536
CANCEL_POLL_INTERVAL = 0.1
# Exit wait after EOF when the caller sets no total deadline.
EXIT_GRACE = 5


def error_tail(errors: IO[bytes]) -> str:
    """Return the last ``ERROR_TAIL_LIMIT`` bytes of a captured stderr file."""
    errors.seek(0, os.SEEK_END)
    errors.seek(max(0, errors.tell() - ERROR_TAIL_LIMIT))
    return errors.read().decode(errors="replace")


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


def _spawn(
    command: Sequence[str], *, stdout: int | IO[bytes], stderr: int | IO[bytes]
) -> subprocess.Popen[bytes]:
    log.debug("ffmpeg_command command=%s", command)
    try:
        return subprocess.Popen(  # noqa: S603 - Fixed FFmpeg commands with separate arguments.
            list(command), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr
        )
    except FileNotFoundError as error:
        if error.filename not in {command[0], None}:
            raise
        raise FFmpegNotFoundError(command[0], command=command) from error


def _poll_interval(
    deadline: float | None, idle_timeout: float | None, cancelled: Cancelled | None
) -> float | None:
    limits = [] if cancelled is None else [CANCEL_POLL_INTERVAL]
    if deadline is not None:
        limits.append(deadline - time.monotonic())
    if idle_timeout is not None:
        limits.append(idle_timeout)
    return max(0.0, min(limits)) if limits else None


def iter_output(  # noqa: C901 - One loop handles deadlines, idle time, and cancellation.
    command: Sequence[str],
    *,
    pipe: Literal["stdout", "stderr"] = "stdout",
    timeout: float | None = None,
    idle_timeout: float | None = None,
    cancelled: Cancelled | None = None,
) -> Generator[bytes]:
    """Run a command and yield chunks of one output pipe until it exits successfully.

    ``timeout`` limits the whole run, ``idle_timeout`` the time between chunks. The other pipe is
    discarded, except that stderr is kept for the error of a failed run.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    with tempfile.TemporaryFile() as errors:
        process = _spawn(
            command,
            stdout=subprocess.PIPE if pipe == "stdout" else subprocess.DEVNULL,
            stderr=errors if pipe == "stdout" else subprocess.PIPE,
        )
        try:
            # The selected pipe was opened with PIPE above.
            output = cast(IO[bytes], process.stdout if pipe == "stdout" else process.stderr)
            tail = b""
            idle_since = time.monotonic()

            with selectors.DefaultSelector() as selector:
                selector.register(output, selectors.EVENT_READ)
                while True:
                    if cancelled is not None and cancelled():
                        raise CancelledError("Operation cancelled")
                    now = time.monotonic()
                    if deadline is not None and now >= deadline:
                        raise FFmpegTimeoutError(
                            f"Did not finish within {timeout} s", command=command
                        )
                    if idle_timeout is not None and now - idle_since >= idle_timeout:
                        raise FFmpegTimeoutError(
                            f"Produced no output for {idle_timeout} s", command=command
                        )
                    if not selector.select(_poll_interval(deadline, idle_timeout, cancelled)):
                        continue

                    chunk = os.read(output.fileno(), CHUNK_SIZE)
                    if not chunk:
                        break
                    idle_since = time.monotonic()
                    if pipe == "stderr":
                        tail = (tail + chunk)[-ERROR_TAIL_LIMIT:]
                    yield chunk

            remaining = EXIT_GRACE if deadline is None else max(0, deadline - time.monotonic())
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise FFmpegTimeoutError(
                    f"Did not exit within {remaining:.1f} s", command=command
                ) from error
            if returncode:
                stderr = error_tail(errors) if pipe == "stdout" else tail.decode(errors="replace")
                raise FFmpegProcessError(returncode, stderr, command=command)
        finally:
            stop(process, grace=1)


def run(
    command: Sequence[str],
    *,
    pipe: Literal["stdout", "stderr"] = "stdout",
    timeout: float,
    cancelled: Cancelled | None = None,
) -> bytes:
    """Run a command to completion and return the selected output pipe."""
    return b"".join(iter_output(command, pipe=pipe, timeout=timeout, cancelled=cancelled))
