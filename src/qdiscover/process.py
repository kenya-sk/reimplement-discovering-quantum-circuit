"""Subprocess execution with timeouts that also stop descendant builders/workers."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False


def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> ProcessResult:
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(input_text, timeout=timeout)
            return ProcessResult(process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            return ProcessResult(process.returncode, stdout, stderr, timed_out=True)


def run_streamed_process(
    command: list[str], *, stdout_path: Path, timeout: float, max_stdout_bytes: int
) -> ProcessResult:
    """Bound binary output and logs without buffering candidate output in RAM."""
    if timeout <= 0 or max_stdout_bytes <= 0:
        raise ValueError("Timeout and output limit must be positive")
    limit_hit = threading.Event()
    stderr = bytearray()
    with (
        stdout_path.open("wb") as output,
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process,
    ):
        assert process.stdout is not None and process.stderr is not None

        def copy(stream: IO[bytes], write: Callable[[bytes], object], limit: int) -> None:
            written = 0
            while chunk := stream.read(65536):
                write(chunk[: max(0, limit - written)])
                written += len(chunk)
                if written > limit:
                    limit_hit.set()
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    return

        threads = [
            threading.Thread(
                target=copy, args=(process.stdout, output.write, max_stdout_bytes), daemon=True
            ),
            threading.Thread(
                target=copy, args=(process.stderr, stderr.extend, 4 << 20), daemon=True
            ),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        for thread in threads:
            thread.join()
    return ProcessResult(
        process.returncode,
        "",
        stderr.decode(errors="replace"),
        timed_out=timed_out,
        output_limited=limit_hit.is_set(),
    )
