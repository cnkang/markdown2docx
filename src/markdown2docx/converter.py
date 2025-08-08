"""Markdown → DOCX converter (Pandoc) with sane defaults & validation hook."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

import pypandoc

try:
    # Used for robust version comparison (optional)
    from packaging.version import Version
except ImportError:
    Version = None  # Converter still works without packaging; only strict compare is skipped

log = logging.getLogger(__name__)


class MarkdownToDocxConverter:
    """
    Convert Markdown to DOCX via Pandoc with an emphasis on:
    - Using a reference DOCX to control styles (Headings, Code, Table, etc.)
    - Predictable Markdown reader extensions (GFM-based)
    - Optional post-conversion validation hook (OOXML/OPC)
    """

    # Recommended Markdown reader: GitHub Flavored Markdown + compatible extensions
    _DEFAULT_MD_READER = (
        "gfm"
        "+footnotes"
        "+tex_math_dollars"
        "+fenced_divs"
        "+bracketed_spans"
    )

    def __init__(self, reference_doc: Optional[str | Path] = None, min_pandoc: str = "2.19"):
        """
        Args:
            reference_doc: Optional path to a reference DOCX used to control styles.
            min_pandoc: Minimum recommended Pandoc version string.
        """
        self.reference_doc = Path(reference_doc) if reference_doc else None
        self.min_pandoc = min_pandoc
        self._ensure_pandoc(min_pandoc)

    def _ensure_pandoc(self, min_version: str) -> None:
        """Log a warning if local Pandoc is older than the recommended version."""
        try:
            ver = str(pypandoc.get_pandoc_version())
            if Version is None:
                log.info("Pandoc %s detected (skip strict compare; install 'packaging' for version checks).", ver)
            elif Version(ver) < Version(min_version):
                log.warning("Pandoc %s detected; recommend >= %s for robust DOCX output.", ver, min_version)
        except Exception as e:
            log.warning("Unable to determine Pandoc version: %s", e)

    def convert(
        self,
        input_path: str | Path,
        output_path: Optional[str | Path] = None,
        *,
        toc: bool = False,
        toc_depth: int = 3,
        extra_args: Optional[Sequence[str]] = None,
        run_validator: bool = False,
    ) -> Path:
        """
        Convert a Markdown file to DOCX.

        Args:
            input_path: Path to the Markdown file.
            output_path: Optional path to the DOCX result; defaults to input basename with .docx.
            toc: Whether to include a table of contents.
            toc_depth: Depth of the table of contents (if toc=True).
            extra_args: Additional Pandoc arguments to append.
            run_validator: Run a post-conversion validation hook.

        Returns:
            Path to the generated DOCX file.

        Raises:
            FileNotFoundError: If the input file (or reference doc) does not exist.
            RuntimeError: If Pandoc is missing or conversion/validation fails.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(input_path)

        output_path = Path(output_path) if output_path else input_path.with_suffix(".docx")

        args = self._build_args(toc=toc, toc_depth=toc_depth, extra_args=extra_args)

        try:
            pypandoc.convert_file(
                str(input_path),
                to="docx",
                outputfile=str(output_path),
                extra_args=args,
            )
        except OSError as e:
            # Common pypandoc case: Pandoc not installed on the system
            raise RuntimeError(
                "Pandoc not found. Install Pandoc or call pypandoc.download_pandoc() before converting."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Conversion failed: {e}") from e

        if run_validator:
            self._validate_docx(output_path)

        return output_path

    def _build_args(
        self, *, toc: bool, toc_depth: int, extra_args: Optional[Sequence[str]]
    ) -> list[str]:
        """Build a predictable set of Pandoc arguments for DOCX output."""
        args: list[str] = ["-f", self._DEFAULT_MD_READER]

        # Use a reference DOCX to control styles (headings, captions, code, etc.)
        if self.reference_doc:
            if not self.reference_doc.exists():
                raise FileNotFoundError(f"Reference DOCX not found: {self.reference_doc}")
            args.extend(["--reference-doc", str(self.reference_doc)])

        # Optional ToC
        if toc:
            args.append("--toc")
            args.extend(["--toc-depth", str(toc_depth)])

        # Intentionally avoid flags that are irrelevant or noisy for DOCX:
        # - wrap/columns/highlight/email-obfuscation/etc.
        # If you need code highlighting, prefer styling it via the reference DOCX.

        # Allow callers to extend behavior
        if extra_args:
            args.extend(extra_args)

        return args

    def _validate_docx(self, path: Path) -> None:
        """
        Optional validation hook.
        Integrate your validator here (e.g., Open XML SDK Validator via subprocess).
        Keep it simple and fail-fast in CI if validation errors are found.
        """
        try:
            # Example placeholder:
            # subprocess.run(["ooxml-validator", str(path)], check=True)
            pass
        except Exception as e:
            raise RuntimeError(f"Validation failed: {e}") from e
