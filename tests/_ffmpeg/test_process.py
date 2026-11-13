import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

import pytest

from ffkit import (
    CancelledError,
    FFmpegError,
    FFmpegNotFoundError,
    FFmpegProcessError,
    FFmpegTimeoutError,
    SourceNotFoundError,
)
from ffkit._ffmpeg.args import existing_file
from ffkit._ffmpeg.process import ERROR_TAIL_LIMIT, error_tail, iter_output, run, stop


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _sleeping(stdout: int | None = None, stderr: int | None = None) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=stdout,
        stderr=stderr,
    )


def test_error_tail_keeps_last_bytes() -> None:
    with tempfile.TemporaryFile() as errors:
        errors.write(b"a" * 10 + b"b" * ERROR_TAIL_LIMIT)
        assert error_tail(errors) == "b" * ERROR_TAIL_LIMIT


def test_run_returns_selected_pipe() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    assert run(_python(code), timeout=30).strip() == b"out"
    assert run(_python(code), pipe="stderr", timeout=30).strip() == b"err"


def test_run_closes_stdin() -> None:
    assert run(_python("import sys; print(repr(sys.stdin.read()))"), timeout=30).strip() == b"''"


def test_run_logs_command(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="ffkit"):
        run(_python("pass"), timeout=30)
    assert "ffmpeg_command" in caplog.text


@pytest.mark.parametrize("pipe", ["stdout", "stderr"])
def test_failed_run_reports_stderr_tail(pipe: Literal["stdout", "stderr"]) -> None:
    code = "import sys; sys.stderr.write('x' * 5000 + 'boom'); raise SystemExit(3)"
    with pytest.raises(FFmpegProcessError, match=r"status 3: .*boom") as error:
        run(_python(code), pipe=pipe, timeout=30)
    assert error.value.returncode == 3
    assert len(error.value.stderr) == ERROR_TAIL_LIMIT
    assert error.value.command[0] == sys.executable
    assert isinstance(error.value, FFmpegError)


def test_missing_executable(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing")
    with pytest.raises(FFmpegNotFoundError) as error:
        run([missing], timeout=30)
    assert error.value.executable == missing


def test_unrelated_spawn_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "No such directory", "/other")

    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(FileNotFoundError) as error:
        run(["ffmpeg"], timeout=30)
    assert not isinstance(error.value, FFmpegNotFoundError)


def test_total_timeout() -> None:
    with pytest.raises(FFmpegTimeoutError, match="Did not finish"):
        run(_python("import time; time.sleep(10)"), timeout=0.1)


def test_exit_after_output_counts_toward_timeout() -> None:
    code = "import os, time; os.close(1); time.sleep(10)"
    with pytest.raises(FFmpegTimeoutError, match="Did not exit"):
        run(_python(code), timeout=0.5)


def test_idle_timeout_resets_on_output() -> None:
    code = "import time\nfor _ in range(3):\n    print(flush=True); time.sleep(0.05)"
    assert len(b"".join(iter_output(_python(code), idle_timeout=5))) == 3

    with pytest.raises(FFmpegTimeoutError, match="no output"):
        list(iter_output(_python("import time; time.sleep(10)"), idle_timeout=0.1))


def test_idle_timeout_ignores_consumer_pauses() -> None:
    code = "import time\nfor _ in range(3):\n    print(flush=True); time.sleep(0.05)"
    output = iter_output(_python(code), idle_timeout=0.3)

    first = next(output)
    time.sleep(0.6)

    assert len(first + b"".join(output)) == 3


def test_cancellation_stops_process() -> None:
    with pytest.raises(CancelledError):
        run(_python("import time; time.sleep(10)"), timeout=30, cancelled=lambda: True)


def test_closing_generator_stops_process() -> None:
    chunks = iter_output(_python("import time; print(flush=True); time.sleep(10)"))
    assert next(chunks) == b"\n"
    chunks.close()


def test_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.touch()
    assert existing_file(path) == path
    with pytest.raises(SourceNotFoundError) as error:
        existing_file(tmp_path / "missing")
    assert isinstance(error.value, FileNotFoundError)
    assert isinstance(error.value, ValueError)


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
