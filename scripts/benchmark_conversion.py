#!/usr/bin/env python3
"""Measure repeatable segmentation and end-to-end timings without CI time assertions."""

import argparse
import json
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

import pypandoc

from markdown2docx import MarkdownToDocxConverter, __version__
from markdown2docx.multilingual import fragments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmark.json"))
    args = parser.parse_args()
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "package": __version__,
        "pandoc": str(pypandoc.get_pandoc_version()),
        "segmentation_ms": {},
        "conversions": {},
    }
    for size in [2000, 4000, 8000, 16000]:
        times = []
        for _ in range(5):
            start = perf_counter()
            fragments("." * size, None, "." * size)
            times.append((perf_counter() - start) * 1000)
        report["segmentation_ms"][str(size)] = statistics.median(times)
    fixture = Path(__file__).resolve().parents[1] / "examples/multilingual.md"
    with tempfile.TemporaryDirectory(prefix="md2docx-benchmark-") as temporary:
        root = Path(temporary)
        samples = {
            "short": "# Hello\n\nShort document.",
            "long-paragraph": "Text words, " * 5000,
            "neutral": "." * 16000,
            "code": "```python\n" + "print('hello')\n" * 500 + "```",
            "table": "| Name | Value |\n|---|---|\n" + "| sample | 123 |\n" * 500,
            "footnotes": "Footnote[^1].\n\n[^1]: Detail.\n",
        }
        paths = {"multilingual": fixture}
        for name, text in samples.items():
            path = root / f"{name}.md"
            path.write_text(text, encoding="utf-8")
            paths[name] = path
        converter = MarkdownToDocxConverter()
        for name, source in paths.items():
            timings = [
                converter.convert_with_report(
                    source, root / f"{name}.docx", offline=True
                ).timings
                for _ in range(3)
            ]
            report["conversions"][name] = {
                key: statistics.median(item[key] for item in timings)
                for key in timings[0]
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
