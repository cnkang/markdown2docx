#!/usr/bin/env python3
"""Invoke the pinned execution package without a repository checkout."""

import shutil
import subprocess
import sys

EXECUTION_REVISION = "f0c33504d83b0dc983f56b7d0d2ab8ea89640687"
SOURCE = f"git+https://github.com/cnkang/markdown2docx.git@{EXECUTION_REVISION}"


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print(
            "markdown-to-docx requires uv: https://docs.astral.sh/uv/", file=sys.stderr
        )
        return 127
    return subprocess.call(
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
