"""Bounded Pandoc execution with process cleanup and stable failure codes."""

from __future__ import annotations

import os
import shutil
import signal

# controlled argv, shell=False
import subprocess  # nosec B404
from pathlib import Path
from typing import Sequence

import pypandoc

from .exceptions import PandocError, PandocNotFoundError


class PandocTimeoutError(PandocError):
    """A Pandoc stage exceeded its configured time budget."""

    code = "PANDOC_TIMEOUT"


def run_pandoc(
    arguments: Sequence[str], *, timeout: int, phase: str
) -> subprocess.CompletedProcess[bytes]:
    """Run one stage; kill its process group on timeout or cancellation."""
    command = [pypandoc.get_pandoc_path(), *arguments]
    try:
        # tool executable and argv, no shell
        process = subprocess.Popen(  # nosec B603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise PandocNotFoundError() from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as exc:
        if os.name == "nt":
            try:
                # tool executable and argv, no shell
                subprocess.run(  # nosec B603
                    [
                        shutil.which("taskkill")
                        or str(
                            Path(os.environ.get("SystemRoot", "C:/Windows"))
                            / "System32/taskkill.exe"
                        ),
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except OSError, subprocess.SubprocessError:
                # Fall back to terminating the parent if taskkill is unavailable.
                if process.poll() is None:
                    process.kill()
            finally:
                if process.poll() is None:
                    process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            process.wait(timeout=10)
        if isinstance(exc, subprocess.TimeoutExpired):
            raise PandocTimeoutError(
                f"Pandoc {phase} exceeded {timeout} seconds"
            ) from exc
        raise
    if process.returncode:
        raise PandocError(
            f"Pandoc {phase} failed: {stderr.decode('utf-8', errors='replace')[-4000:]}"
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def write_docx(
    input_path: str,
    *,
    outputfile: str,
    extra_args: Sequence[str],
    timeout: int,
    to: str = "docx",
    format: str = "json",
) -> None:
    """Write the annotated AST using the same bounded runner as parsing."""
    run_pandoc(
        [*extra_args, str(Path(input_path)), "--output", outputfile],
        timeout=timeout,
        phase="write",
    )
