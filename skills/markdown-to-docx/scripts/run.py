#!/usr/bin/env python3
"""Invoke the pinned execution package without a repository checkout."""

import shutil

# controlled argv, shell=False
import subprocess  # nosec B404
import sys

EXECUTION_REVISION = "8b115d196347ca25be622fa4c2e513ae20501284"
SOURCE = f"git+https://github.com/cnkang/markdown2docx.git@{EXECUTION_REVISION}"


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print(
            "markdown-to-docx requires uv: https://docs.astral.sh/uv/", file=sys.stderr
        )
        return 127
    # tool executable and argv, no shell
    return subprocess.call(  # nosec B603
        [
            uv,
            "tool",
            "run",
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
