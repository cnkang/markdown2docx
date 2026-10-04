#!/usr/bin/env python3
"""Smoke-test an installed wheel from a directory outside the source checkout."""

import argparse
import json

# controlled argv, shell=False
import subprocess  # nosec B404
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    interpreter = str(args.python.absolute())
    with tempfile.TemporaryDirectory(prefix="md2docx-wheel-") as directory:
        root = Path(directory)
        source = root / "input.md"
        source.write_text("# Wheel smoke test\n\nEditable document.", encoding="utf-8")
        # tool executable and argv, no shell
        result = subprocess.run(  # nosec B603
            [
                interpreter,
                "-m",
                "markdown2docx.cli",
                str(source),
                "--offline",
                "--json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        report = json.loads(result.stdout)
        if (
            report["checks"]["text_integrity"] != "passed"
            or not source.with_suffix(".docx").is_file()
        ):
            raise RuntimeError("Installed wheel failed conversion")
        # tool executable and argv, no shell
        subprocess.run(  # nosec B603
            [
                interpreter,
                "-c",
                "from importlib.resources import files; import json; from markdown2docx import __version__; r=files('markdown2docx'); json.loads(r.joinpath('font_manifest.json').read_text()); json.loads(r.joinpath('report_schema.json').read_text()); print(__version__)",
            ],
            cwd=root,
            check=True,
            timeout=30,
        )
        # tool executable and argv, no shell
        subprocess.run(  # nosec B603
            [interpreter, "-m", "markdown2docx.cli", "--version"],
            cwd=root,
            check=True,
            timeout=30,
        )
        # tool executable and argv, no shell
        subprocess.run(  # nosec B603
            [interpreter, "-m", "markdown2docx.cli", "--doctor", "--json"],
            cwd=root,
            check=True,
            timeout=30,
        )
    print("Installed wheel smoke checks passed")


if __name__ == "__main__":
    main()
