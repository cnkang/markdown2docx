#!/usr/bin/env python3
"""Convert the acceptance fixture and retain reviewable artifacts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from lxml import etree

from markdown2docx import MarkdownToDocxConverter
from markdown2docx.multilingual import NS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/multilingual")
    )
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "examples/multilingual.md"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = (
        MarkdownToDocxConverter()
        .convert_with_report(
            source,
            args.output_dir / "multilingual.docx",
            toc=True,
            render=args.render,
            preview_dir=args.output_dir / "preview",
            offline=args.offline,
        )
        .to_dict()
    )
    required = {"zh-Hans", "zh-Hant", "ja", "ko", "en", "fr", "es", "ru", "ar"}
    assert required <= set(report["languages"]), "A supported language is missing"
    assert all(
        report["checks"][key] == "passed"
        for key in (
            "structure",
            "text_integrity",
            "font_coverage",
            "language_direction",
        )
    ), report["checks"]
    with zipfile.ZipFile(report["output_path"]) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
        expected = {
            "Noto Sans",
            "Noto Sans Arabic",
            "Noto Sans CJK SC",
            "Noto Sans CJK TC",
            "Noto Sans CJK JP",
            "Noto Sans CJK KR",
        }
        cells = root.xpath("//w:tc", namespaces=NS)
        assert any(
            expected <= set(cell.xpath(".//w:rFonts/@w:ascii", namespaces=NS))
            for cell in cells
        ), "Mixed-language table cell lost its fonts"
        assert root.xpath(
            "//w:pPr/w:bidi[@w:val='1']", namespaces=NS
        ), "RTL paragraph missing"
    if args.render:
        assert report["preview"]["status"] == "rendered", report["preview"]
        assert report["preview"]["pages"], "Page previews are missing"
        binary = shutil.which("pdffonts")
        assert binary, "pdffonts is required for CI rendering checks"
        result = subprocess.run(
            [binary, report["preview"]["pdf"]],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        used = set()
        for line in result.stdout.splitlines()[2:]:
            if not line.strip():
                continue
            name = line.split()[0].split("+")[-1]
            normalized = re.sub(r"[^a-z0-9]", "", name.lower())
            normalized = re.sub(r"(?:regular|bolditalic|bold|italic)$", "", normalized)
            used.add(normalized)
        missing = [
            family
            for family in expected
            if re.sub(r"[^a-z0-9]", "", family.lower()) not in used
        ]
        assert (
            not missing
        ), f"Renderer substituted or omitted expected fonts: {missing}; actual: {sorted(used)}"
        report["checks"]["rendered_fonts"] = "passed"
        report["checks"]["visual_review"] = "required"
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
