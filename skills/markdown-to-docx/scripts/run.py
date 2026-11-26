#!/usr/bin/env python3
"""Invoke the pinned execution package without a repository checkout."""

import shutil

# controlled argv, shell=False
import subprocess  # nosec B404
import sys

EXECUTION_REVISION = "1b01b2c46b5fe20329f9487977c1f1be89a8cc40"
SOURCE = f"git+https://github.com/cnkang/markdown2docx.git@{EXECUTION_REVISION}"


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print(
            "markdown-to-docx requires uv: https://docs.astral.sh/uv/", file=sys.stderr
        )
        return 127
    # tool executable and argv, no shell
    uv_arguments = ["--offline"] if "--offline" in sys.argv[1:] else []
    return subprocess.call(  # nosec B603
        [
            uv,
            "tool",
            "run",
            *uv_arguments,
            "--python",
            "3.14",
            "--from",
            SOURCE,
            "markdown2docx",
            *sys.argv[1:],
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
