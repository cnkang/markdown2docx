"""Machine-readable conversion results and optional rendering evidence."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat

# controlled argv, shell=False
import subprocess  # nosec B404
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .fonts import FontResolver, cache_directory, system_font_directories
from .output import (
    PinnedDirectory,
    pinned_directory,
    secure_temporary_directory,
)


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


def _entry_names(directory: PinnedDirectory) -> list[str]:
    if os.name == "nt":
        return sorted(entry.name for entry in directory.path.iterdir())
    with os.scandir(directory.descriptor) as entries:
        return sorted(entry.name for entry in entries)


def _copy_regular(source: int, target: int) -> None:
    try:
        details = os.fstat(source)
    except BaseException:
        os.close(source)
        raise
    if not stat.S_ISREG(details.st_mode):
        os.close(source)
        os.close(target)
        raise OSError("Preview source is not a regular file")
    original = os.fdopen(source, "rb")
    try:
        destination = os.fdopen(target, "wb")
    except BaseException:
        original.close()
        os.close(target)
        raise
    with original, destination:
        shutil.copyfileobj(original, destination)


def _copy_generation(source: PinnedDirectory, target: PinnedDirectory) -> None:
    """Copy a completed private generation into destination-filesystem staging."""
    for name in _entry_names(source):
        try:
            child = source.open_directory(name)
        except OSError:
            source_descriptor = source.open_regular(name)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if os.name != "nt":
                flags |= os.O_NOFOLLOW
            try:
                target_descriptor = target.open_file(name, flags)
            except BaseException:
                os.close(source_descriptor)
                raise
            _copy_regular(source_descriptor, target_descriptor)
        else:
            target.make_directory(name)
            target_child = target.open_directory(name)
            try:
                _copy_generation(
                    PinnedDirectory(source.path / name, child),
                    PinnedDirectory(target.path / name, target_child),
                )
            finally:
                os.close(child)
                os.close(target_child)


def _publish_generation(generation: PinnedDirectory, target: PinnedDirectory) -> Path:
    """Atomically expose a generation through the pinned publication directory."""
    staging_name = f".preview-publish-{uuid.uuid4().hex}"
    published_name = f"generation-{uuid.uuid4().hex}"
    target.make_directory(staging_name)
    staging_descriptor = target.open_directory(staging_name)
    staging = PinnedDirectory(target.path / staging_name, staging_descriptor)
    published = False
    staging_closed = False
    try:
        _copy_generation(generation, staging)
        if os.name == "nt":
            os.replace(staging.path, target.path / published_name)
        else:
            os.rename(
                staging_name,
                published_name,
                src_dir_fd=target.descriptor,
                dst_dir_fd=target.descriptor,
            )
        published = True
    finally:
        if not published:
            if os.name == "nt":
                os.close(staging_descriptor)
                staging_closed = True
                shutil.rmtree(staging.path)
            else:
                staging.cleanup()
        if not staging_closed:
            os.close(staging_descriptor)
        if os.name == "nt":
            with contextlib.suppress(FileNotFoundError):
                staging.path.rmdir()
        else:
            with contextlib.suppress(OSError):
                os.rmdir(staging_name, dir_fd=target.descriptor)
    return target.current_path() / published_name


def render_preview(
    path: Path, output_dir: Path, resolver: FontResolver, *, max_pages: int = 200
) -> dict[str, Any]:
    """Render privately, then publish through a fixed destination descriptor."""
    if any(font.source != "system" for font in resolver.selected.values()):
        return {
            "status": "unverified",
            "reason": "Required fonts are cached, not installed for the renderer",
        }
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return {"status": "unverified", "reason": "LibreOffice is unavailable"}
    try:
        with pinned_directory(output_dir) as publication:
            with secure_temporary_directory(
                prefix=".render-", directory=output_dir if os.name == "nt" else None
            ) as rendering:
                root = rendering.path
                profile = (root / "profile").as_uri()
                rendering.assert_pinned()
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
                if result.returncode:
                    return {
                        "status": "failed",
                        "reason": result.stderr or result.stdout,
                    }
                pdf_name = path.with_suffix(".pdf").name
                pdf_descriptor = rendering.open_regular(pdf_name)
                rendering.make_directory("generation")
                generation_descriptor = rendering.open_directory("generation")
                generation = PinnedDirectory(root / "generation", generation_descriptor)
                try:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if os.name != "nt":
                        flags |= os.O_NOFOLLOW
                    try:
                        destination_descriptor = generation.open_file(
                            "preview.pdf", flags
                        )
                    except BaseException:
                        os.close(pdf_descriptor)
                        raise
                    _copy_regular(pdf_descriptor, destination_descriptor)
                    images: list[str] = []
                    raster = shutil.which("pdftoppm")
                    if raster:
                        rendering.assert_pinned()
                        # tool executable and argv, no shell
                        rasterized = subprocess.run(  # nosec B603
                            [
                                raster,
                                "-png",
                                "-l",
                                str(max_pages + 1),
                                "-r",
                                "100",
                                str(generation.path / "preview.pdf"),
                                str(generation.path / "page"),
                            ],
                            capture_output=True,
                            timeout=120,
                        )
                        if rasterized.returncode:
                            return {
                                "status": "failed",
                                "reason": "PDF page rasterization failed",
                                "pdf_generated": True,
                            }
                        images = [
                            name
                            for name in _entry_names(generation)
                            if name.startswith("page-") and name.endswith(".png")
                        ]
                        images.sort(
                            key=lambda name: int(Path(name).stem.split("-")[-1])
                        )
                        if len(images) > max_pages:
                            return {
                                "status": "failed",
                                "reason": f"Preview exceeds {max_pages} pages",
                                "pdf_generated": True,
                            }
                    published = _publish_generation(generation, publication)
                    return {
                        "status": "rendered",
                        "pdf": str(published / "preview.pdf"),
                        "pages": [str(published / name) for name in images],
                        "rasterization": "passed" if raster else "unavailable",
                        "visual_review": "required",
                    }
                finally:
                    os.close(generation_descriptor)

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
