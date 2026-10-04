"""Machine-readable conversion results and optional rendering evidence."""

from __future__ import annotations

import os
import shutil

# controlled argv, shell=False
import subprocess  # nosec B404
import tempfile
import uuid
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
    preview: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "unverified",
            "reason": "Rendering not requested",
        }
    )

    schema_version: str = "1.0"
    conversion_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timings: dict[str, float] = field(default_factory=dict)
    tools: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": "success", **asdict(self)}


def render_preview(
    path: Path, output_dir: Path, resolver: FontResolver, *, max_pages: int = 200
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
        if output_dir.is_symlink():
            raise OSError("Preview directory must not be a symlink")
        # Immutable generation directories isolate concurrent and failed renders.
        with tempfile.TemporaryDirectory(
            prefix=".render-", dir=output_dir
        ) as temporary:
            root = Path(temporary)
            profile = (root / "profile").as_uri()
            # tool executable and argv, no shell
            result = subprocess.run(  # nosec B603
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
            generation = root / "generation"
            generation.mkdir()
            destination = generation / "preview.pdf"
            shutil.copyfile(pdf, destination)
            images: list[str] = []
            raster = shutil.which("pdftoppm")
            if raster:
                # tool executable and argv, no shell
                rasterized = subprocess.run(  # nosec B603
                    [
                        raster,
                        "-png",
                        "-l",
                        str(max_pages + 1),
                        "-r",
                        "100",
                        str(destination),
                        str(generation / "page"),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if rasterized.returncode == 0:
                    images = [
                        str(p.absolute())
                        for p in sorted(
                            generation.glob("page-*.png"),
                            key=lambda p: int(p.stem.split("-")[-1]),
                        )
                    ]
                else:
                    return {
                        "status": "failed",
                        "reason": "PDF page rasterization failed",
                        "pdf_generated": True,
                    }
                if len(images) > max_pages:
                    return {
                        "status": "failed",
                        "reason": f"Preview exceeds {max_pages} pages",
                        "pdf_generated": True,
                    }
            published = output_dir / f"generation-{uuid.uuid4().hex}"
            os.replace(generation, published)
            return {
                "status": "rendered",
                "pdf": str((published / "preview.pdf").absolute()),
                "pages": [str((published / Path(p).name).absolute()) for p in images],
                "rasterization": "passed" if raster else "unavailable",
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
