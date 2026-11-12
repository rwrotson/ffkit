import subprocess
import sys
import tempfile

import pytest

from ffkit._ffmpeg.process import ERROR_TAIL_LIMIT, error_tail, stdout_chunks, stop


def _sleeping(stdout: int | None = None, stderr: int | None = None) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], stdout=stdout, stderr=stderr
    )


def test_error_tail_keeps_last_bytes() -> None:
    with tempfile.TemporaryFile() as errors:
        errors.write(b"a" * 10 + b"b" * ERROR_TAIL_LIMIT)
        assert error_tail(errors) == "b" * ERROR_TAIL_LIMIT


def test_stdout_chunks_reads_until_exit() -> None:
    process = subprocess.Popen([sys.executable, "-c", "print('done')"], stdout=subprocess.PIPE)
    try:
        assert b"".join(stdout_chunks(process, timeout=30)).strip() == b"done"
    finally:
        stop(process)


def test_stdout_chunks_reports_failed_exit() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(3)"], stdout=subprocess.PIPE
    )
    try:
        with pytest.raises(subprocess.CalledProcessError):
            list(stdout_chunks(process, timeout=30))
    finally:
        stop(process)


def test_stdout_chunks_timeout_includes_stdout_read() -> None:
    process = _sleeping(subprocess.PIPE)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            list(stdout_chunks(process, timeout=0.01))
    finally:
        stop(process)


def test_stdout_chunks_requires_stdout() -> None:
    process = _sleeping()
    try:
        with pytest.raises(RuntimeError, match="stdout"):
            list(stdout_chunks(process, timeout=30))
    finally:
        stop(process)


def test_stop_kills_running_process_and_closes_pipes() -> None:
    process = _sleeping(subprocess.PIPE, subprocess.PIPE)
    stop(process)
    assert process.returncode is not None
    assert process.stdout is not None
    assert process.stdout.closed
    assert process.stderr is not None
    assert process.stderr.closed


def test_stop_terminates_with_grace() -> None:
    process = _sleeping()
    stop(process, grace=5)
    assert process.returncode == -15


def test_stop_kills_after_grace_expires() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print(flush=True); time.sleep(10)",
        ],
        stdout=subprocess.PIPE,
    )

    assert process.stdout is not None
    process.stdout.readline()  # The handler is installed once the first line is printed.

    stop(process, grace=0.1)
    assert process.returncode == -9


def test_stop_leaves_finished_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    stop(process)
    assert process.returncode == 0
