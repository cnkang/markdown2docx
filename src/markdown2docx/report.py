"""Machine-readable conversion results and optional rendering evidence."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fonts import FontResolver, cache_directory, system_font_directories


@dataclass
class ConversionReport:
    output_path: str
    language: str | None
    languages: list[str]
    scripts: list[str]
    fonts: list[dict[str, Any]]
    warnings: list[dict[str, str]] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)
    preview: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": "success", **asdict(self)}


def render_preview(
    path: Path, output_dir: Path, resolver: FontResolver
) -> dict[str, Any]:
    """Render only when the renderer can use verified system-installed fonts."""
    if any(font.source != "system" for font in resolver.selected.values()):
        return {
            "status": "unverified",
            "reason": "Required fonts are cached, not installed for the renderer",
        }
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return {"status": "unverified", "reason": "LibreOffice is unavailable"}
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="md2docx-render-") as temporary:
            root = Path(temporary)
            profile = (root / "profile").as_uri()
            result = subprocess.run(
                [
                    binary,
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(root),
                    str(path.absolute()),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            pdf = root / path.with_suffix(".pdf").name
            if result.returncode or not pdf.is_file():
                return {"status": "failed", "reason": result.stderr or result.stdout}
            destination = output_dir / "preview.pdf"
            shutil.copyfile(pdf, destination)
            images: list[str] = []
            raster = shutil.which("pdftoppm")
            if raster:
                rasterized = subprocess.run(
                    [
                        raster,
                        "-png",
                        "-r",
                        "100",
                        str(destination),
                        str(output_dir / "page"),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if rasterized.returncode == 0:
                    images = [
                        str(p.absolute()) for p in sorted(output_dir.glob("page-*.png"))
                    ]
            return {
                "status": "rendered",
                "pdf": str(destination.absolute()),
                "pages": images,
                "visual_review": "required",
            }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "reason": str(exc)}


def doctor() -> dict[str, Any]:
    import pypandoc

    try:
        version = str(pypandoc.get_pandoc_version())
    except Exception:
        version = None
    return {
        "pandoc": version,
        "font_directories": [str(p) for p in system_font_directories()],
        "font_cache": str(cache_directory()),
        "libreoffice": shutil.which("soffice") or shutil.which("libreoffice"),
        "pdftoppm": shutil.which("pdftoppm"),
        "font_discovery": "available",
        "font_embedding": False,
    }
