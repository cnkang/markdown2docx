"""Fail unless required cross-platform test evidence is present and non-empty."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REQUIRED_FILES = (
    "artifacts/junit.xml",
    "coverage.xml",
    "artifacts/multilingual/report.json",
    "artifacts/multilingual/multilingual.docx",
)
DISTRIBUTION_PATTERNS = ("*.whl", "*.tar.gz")


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def find_missing_evidence(root: Path) -> list[str]:
    """Return every required file or distribution class that is absent or empty."""
    missing = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not _is_nonempty_file(root / relative_path)
    ]
    dist = root / "artifacts" / "dist"
    for pattern in DISTRIBUTION_PATTERNS:
        if not any(_is_nonempty_file(path) for path in dist.glob(pattern)):
            missing.append(f"artifacts/dist/{pattern}")
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    missing = find_missing_evidence(args.root)
    if missing:
        print("Required test evidence is missing or empty:", file=sys.stderr)
        for relative_path in missing:
            print(f"  {relative_path}", file=sys.stderr)
        return 1

    print("Required test evidence is present and non-empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
