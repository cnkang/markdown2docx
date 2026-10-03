"""Markdown → DOCX converter with modern standards support and robust error handling.

This module provides the main MarkdownToDocxConverter class for converting
Markdown files to DOCX format using Pandoc with enhanced error handling,
type safety, and configuration management.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional, Sequence, Union

import pypandoc

try:
    from packaging.version import Version

    VERSION_AVAILABLE = True
except ImportError:
    Version = None  # type: ignore[assignment,misc]
    VERSION_AVAILABLE = False

from .config import DEFAULT_CONFIG, MarkdownToDocxConfig
from .exceptions import (
    ConversionError,
    PandocError,
    PandocNotFoundError,
    ValidationError,
)
from .fonts import FontResolver
from .multilingual import MultilingualDocument, text_of
from .output import staged_docx_output
from .report import ConversionReport, render_preview
from .templates import DocxTemplateManager

# Configure logger
logger = logging.getLogger(__name__)


class MarkdownToDocxConverter:
    """Convert Markdown files to modern DOCX format using Pandoc.

    This converter provides robust Markdown to DOCX conversion with:
    - Modern DOCX standards support (Office 2019+)
    - Configurable styling via reference documents
    - Comprehensive error handling and validation
    - Support for advanced Markdown features (tables, code blocks, footnotes)
    - Optional post-conversion validation

    Example:
        Basic usage:
        >>> converter = MarkdownToDocxConverter()
        >>> output_path = converter.convert("input.md", "output.docx")

        With custom template:
        >>> converter = MarkdownToDocxConverter(reference_doc="template.docx")
        >>> output_path = converter.convert("input.md", "output.docx", toc=True)
    """

    def __init__(
        self,
        reference_doc: Optional[Union[str, Path]] = None,
        config: Optional[MarkdownToDocxConfig] = None,
    ) -> None:
        """Initialize the converter with optional reference document and configuration.

        Args:
            reference_doc: Optional path to a reference DOCX file for styling.
                          If provided, the output will use styles from this template.
            config: Optional configuration object. If None, uses default configuration.

        Raises:
            PandocNotFoundError: If Pandoc is not installed or not found.
            PandocError: If Pandoc version check fails.
        """
        self.config = config or DEFAULT_CONFIG
        self.reference_doc = Path(reference_doc) if reference_doc else None

        # Validate Pandoc installation and version
        self._validate_pandoc()

        # Configure logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging based on configuration settings."""
        log_level = getattr(logging, self.config.logging.level.upper(), logging.INFO)
        logger.setLevel(log_level)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(self.config.logging.format)
            handler.setFormatter(formatter)
            logger.addHandler(handler)

    def _validate_pandoc(self) -> None:
        """Validate Pandoc installation and version.

        Raises:
            PandocNotFoundError: If Pandoc is not installed.
            PandocError: If version check fails or version is too old.
        """
        try:
            version_str = str(pypandoc.get_pandoc_version())
            logger.info("Pandoc version %s detected", version_str)

            if VERSION_AVAILABLE and Version is not None:
                current_version = Version(version_str)
                min_version = Version(self.config.pandoc.min_version)

                if current_version < min_version:
                    logger.warning(
                        "Pandoc %s detected; recommend >= %s for optimal DOCX output",
                        version_str,
                        self.config.pandoc.min_version,
                    )
            else:
                logger.info(
                    "Version comparison skipped (install 'packaging' for strict version checks)"
                )

        except OSError as e:
            raise PandocNotFoundError() from e
        except Exception as e:
            raise PandocError(
                f"Failed to validate Pandoc installation: {e}", pandoc_version=None
            ) from e

    def convert(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> Path:
        """Convert with the multilingual pipeline; preserve the Path return value."""
        report = self.convert_with_report(input_path, output_path, **kwargs)
        for warning in report.warnings:
            logger.warning("%s: %s", warning["code"], warning["message"])
        return Path(report.output_path)

    def convert_with_report(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        *,
        toc: Optional[bool] = None,
        toc_depth: Optional[int] = None,
        extra_args: Optional[Sequence[str]] = None,
        validate_output: Optional[bool] = None,
        lang: str | None = None,
        direction: str | None = None,
        offline: bool | None = None,
        allow_unverified_fonts: bool | None = None,
        render: bool = False,
        preview_dir: str | Path | None = None,
    ) -> ConversionReport:
        """Convert atomically, returning separate integrity and rendering evidence.

        Explicit document settings override Markdown metadata and configuration.
        Fonts are referenced, never embedded or installed into the operating system.
        Structural and text-integrity checks always run; validate_output is retained
        for API compatibility and cannot disable the required publication checks.
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        if not input_path.is_file():
            raise ConversionError(
                str(input_path), "Input path must be a file, not a directory"
            )
        output_path = (
            Path(output_path) if output_path else input_path.with_suffix(".docx")
        )
        self._validate_output_path(output_path, str(input_path))
        toc = self.config.conversion.default_toc if toc is None else toc
        toc_depth = (
            self.config.conversion.default_toc_depth if toc_depth is None else toc_depth
        )
        if not 1 <= toc_depth <= 6:
            raise ConversionError(
                str(input_path),
                f"Table of contents depth must be between 1 and 6, got {toc_depth}",
            )
        args = self._build_pandoc_args(
            toc=toc, toc_depth=toc_depth, extra_args=extra_args
        )
        if self.reference_doc:
            from docx import Document

            from .exceptions import TemplateError

            try:
                Document(str(self.reference_doc))
            except Exception as exc:
                raise TemplateError(
                    str(self.reference_doc), f"Invalid DOCX template: {exc}"
                ) from exc
        try:
            parsed = subprocess.run(
                [
                    pypandoc.get_pandoc_path(),
                    "-f",
                    self.config.pandoc.reader_format,
                    "-t",
                    "json",
                    str(input_path.absolute()),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=self.config.pandoc.timeout_seconds,
            )
            ast = json.loads(parsed.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise ConversionError(
                str(input_path), f"Unable to parse Markdown: {exc}", exc
            ) from exc
        metadata = ast.get("meta", {})

        def meta_string(key: str) -> str | None:
            value = metadata.get(key)
            if not value:
                return None
            if value["t"] == "MetaString":
                return str(value["c"])
            return text_of(value) or None

        options = self.config.international
        document_lang = (
            lang if lang is not None else (meta_string("lang") or options.lang)
        )
        document_dir = (
            direction
            if direction is not None
            else (meta_string("dir") or options.direction)
        )
        resolver = FontResolver(
            offline=options.offline if offline is None else offline,
            cache=Path(options.font_cache) if options.font_cache else None,
        )
        allow = (
            options.allow_unverified_fonts
            if allow_unverified_fonts is None
            else allow_unverified_fonts
        )
        for family in {
            self.config.template.body_font,
            self.config.template.heading_font,
            self.config.template.code_font,
        }:
            # Default code fonts are acquired only when needed by content.
            if family != "Noto Sans Mono":
                resolver.audit_family(family, allow_unverified=allow)
        for role, family, default in (
            ("sans", self.config.template.body_font, "Noto Sans"),
            ("heading", self.config.template.heading_font, "Noto Sans"),
            ("mono", self.config.template.code_font, "Noto Sans Mono"),
        ):
            if family != default:
                resolver.aliases[role] = resolver.audit_family(
                    family, allow_unverified=allow
                )
        document = MultilingualDocument(
            ast, resolver, lang=document_lang, base_direction=document_dir
        )
        document.code_size_pt = self.config.template.code_size_pt
        annotated = document.annotate(toc=toc)
        with tempfile.TemporaryDirectory(prefix="md2docx-convert-") as temporary:
            root = Path(temporary)
            ast_path = root / "input.json"
            ast_path.write_text(
                json.dumps(annotated, ensure_ascii=False), encoding="utf-8"
            )
            # JSON input is the annotated AST, not a second Markdown parse.
            args[args.index("-f") + 1] = "json"
            args.extend(
                [
                    "--resource-path",
                    str(input_path.absolute().parent) + os.pathsep + str(Path.cwd()),
                ]
            )
            if self.reference_doc is None:
                reference = DocxTemplateManager.create_reference(
                    root / "reference.docx", self.config.template
                )
                args.extend(["--reference-doc", str(reference)])
            try:
                with staged_docx_output(
                    output_path, overwrite=self.config.conversion.overwrite_existing
                ) as stage:
                    try:
                        pypandoc.convert_file(
                            str(ast_path),
                            to="docx",
                            format="json",
                            outputfile=str(stage),
                            extra_args=args,
                        )
                    except OSError as exc:
                        raise PandocNotFoundError() from exc
                    except Exception as exc:
                        raise ConversionError(
                            str(input_path), f"Pandoc conversion failed: {exc}", exc
                        ) from exc
                    try:
                        self._validate_docx_output(stage)
                        if self.reference_doc:
                            self._audit_template(stage, resolver, allow)
                        checks = document.apply(stage)
                        self._validate_docx_output(stage)
                    except ValidationError as exc:
                        raise ValidationError(
                            str(output_path), exc.validation_errors
                        ) from exc
                    checks["structure"] = "passed"
                    preview = (
                        render_preview(
                            stage,
                            (
                                Path(preview_dir)
                                if preview_dir
                                else output_path.with_suffix(".preview")
                            ),
                            resolver,
                        )
                        if render
                        else {
                            "status": "unverified",
                            "reason": "Rendering not requested",
                        }
                    )
                    checks["rendering"] = preview["status"]
            except OSError as exc:
                raise ConversionError(
                    str(input_path), f"Unable to publish DOCX output: {exc}", exc
                ) from exc
        warnings = list(document.warnings)
        if any(font.source == "cache" for font in resolver.selected.values()):
            warnings.append(
                {
                    "code": "FONT_INSTALLATION_REQUIRED",
                    "message": "Cached fonts are not installed or embedded. Install the reported fonts on viewing machines.",
                }
            )
        if any(not font.verified for font in resolver.selected.values()):
            warnings.append(
                {
                    "code": "FONT_LICENSE_UNVERIFIED",
                    "message": "Unverified fonts were explicitly allowed",
                }
            )
        return ConversionReport(
            str(output_path),
            document.lang,
            sorted(document.languages),
            sorted(document.scripts),
            [font.report() for font in resolver.selected.values()],
            warnings,
            checks,
            preview,
        )

    @staticmethod
    def _audit_template(path: Path, resolver: FontResolver, allow: bool) -> None:
        from lxml import etree

        from .exceptions import TemplateError
        from .multilingual import NS, W

        try:
            with zipfile.ZipFile(path) as archive:
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                root = etree.fromstring(archive.read("word/styles.xml"), parser)
                active = {"Normal"}
                for name in archive.namelist():
                    if (
                        name.startswith("word/")
                        and name.endswith(".xml")
                        and name != "word/styles.xml"
                    ):
                        part = etree.fromstring(archive.read(name), parser)
                        active.update(
                            part.xpath(
                                "//w:pStyle/@w:val | //w:rStyle/@w:val", namespaces=NS
                            )
                        )
                styles = {
                    element.get(W + "styleId"): element
                    for element in root.findall(W + "style")
                }
                pending = list(active)
                while pending:
                    element = styles.get(pending.pop())
                    if element is not None:
                        base = element.find(W + "basedOn")
                        if base is not None and base.get(W + "val") not in active:
                            active.add(base.get(W + "val"))
                            pending.append(base.get(W + "val"))
                families = {
                    value
                    for style in root.findall(W + "style")
                    if style.get(W + "styleId") in active
                    for element in style.iter(W + "rFonts")
                    for key, value in element.attrib.items()
                    if key
                    in {W + slot for slot in ("ascii", "hAnsi", "eastAsia", "cs")}
                }
                for family in families:
                    resolver.audit_family(family, allow_unverified=allow)
        except (OSError, zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
            raise TemplateError(str(path), f"Invalid DOCX template: {exc}") from exc

    def _validate_output_path(self, output_path: Path, input_file: str) -> None:
        """Validate output path safety constraints before writing files."""
        if output_path.suffix.lower() != ".docx":
            raise ConversionError(
                input_file,
                f"Output file must use .docx extension: {output_path}",
            )

        if output_path.exists() and output_path.is_symlink():
            raise ConversionError(
                input_file,
                f"Refusing to write through symlink output path: {output_path}",
            )

    def _build_pandoc_args(
        self, *, toc: bool, toc_depth: int, extra_args: Optional[Sequence[str]]
    ) -> list[str]:
        """Build Pandoc command line arguments for DOCX conversion.

        Args:
            toc: Whether to include table of contents
            toc_depth: Depth of table of contents
            extra_args: Additional arguments to append

        Returns:
            List of Pandoc command line arguments
        """
        # Start with base arguments from configuration
        args = self.config.get_pandoc_args(toc=toc, toc_depth=toc_depth)

        # Add reference document if specified and exists
        if self.reference_doc:
            if self.reference_doc.exists():
                args.extend(["--reference-doc", str(self.reference_doc)])
                logger.debug("Using reference document: %s", self.reference_doc)
            else:
                from .exceptions import TemplateError

                raise TemplateError(
                    str(self.reference_doc),
                    f"Reference document not found: {self.reference_doc}",
                )

        # Add any extra arguments provided by caller
        if extra_args:
            reserved = {
                "-f",
                "--from",
                "--read",
                "-t",
                "--to",
                "--write",
                "-o",
                "--output",
                "--reference-doc",
            }
            if any(argument.split("=", 1)[0] in reserved for argument in extra_args):
                raise ConversionError(
                    "",
                    "Use the converter options instead of overriding the input/output format or template via extra_args",
                )
            args.extend(extra_args)
            logger.debug("Added extra arguments: %s", extra_args)

        return args

    def convert_with_template(
        self,
        input_path: Union[str, Path],
        template_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> Path:
        """Convert Markdown to DOCX using a specific template.

        This is a convenience method that creates a temporary converter instance
        with the specified template and performs the conversion.

        Args:
            input_path: Path to the input Markdown file
            template_path: Path to the DOCX template file
            output_path: Optional path for output file
            **kwargs: Additional arguments passed to convert()

        Returns:
            Path to the generated DOCX file

        Raises:
            FileNotFoundError: If template file doesn't exist
            ConversionError: If conversion fails

        Example:
            >>> converter = MarkdownToDocxConverter()
            >>> output = converter.convert_with_template(
            ...     "document.md",
            ...     "template.docx",
            ...     toc=True
            ... )
        """
        template_path = Path(template_path)
        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        # Create temporary converter with the specified template
        temp_converter = MarkdownToDocxConverter(
            reference_doc=template_path, config=self.config
        )

        return temp_converter.convert(input_path, output_path, **kwargs)

    def _validate_docx_output(self, output_path: Path) -> None:
        """Validate the generated DOCX file for correctness.

        This method performs basic validation of the DOCX file to ensure
        it was generated correctly and is not corrupted.

        Args:
            output_path: Path to the DOCX file to validate

        Raises:
            ValidationError: If validation fails
        """
        validation_errors = []

        try:
            # Basic file existence and size check
            if not output_path.exists():
                validation_errors.append("Output file was not created")
            elif output_path.stat().st_size == 0:
                validation_errors.append("Output file is empty")

            try:
                with zipfile.ZipFile(output_path, "r") as docx_zip:
                    # Check for required DOCX structure
                    required_files = [
                        "[Content_Types].xml",
                        "_rels/.rels",
                        "word/document.xml",
                    ]

                    zip_files = docx_zip.namelist()
                    for required_file in required_files:
                        if required_file not in zip_files:
                            validation_errors.append(
                                f"Missing required file: {required_file}"
                            )

                    # Test that we can read the main document
                    try:
                        docx_zip.read("word/document.xml")
                    except Exception as e:
                        validation_errors.append(f"Cannot read document.xml: {e}")

            except zipfile.BadZipFile:
                validation_errors.append("File is not a valid ZIP/DOCX archive")

            # Additional validation using python-docx if available
            try:
                from docx import Document

                doc = Document(str(output_path))
                # Basic structure check - document should be readable
                _ = len(doc.paragraphs)
            except Exception as e:
                validation_errors.append(f"Document structure validation failed: {e}")

        except Exception as e:
            validation_errors.append(f"Validation process failed: {e}")

        if validation_errors:
            raise ValidationError(str(output_path), validation_errors)

        logger.debug("DOCX validation passed for %s", output_path)

    def get_pandoc_version(self) -> str:
        """Get the version of Pandoc being used.

        Returns:
            Pandoc version string

        Raises:
            PandocError: If unable to determine version
        """
        try:
            return str(pypandoc.get_pandoc_version())
        except Exception as e:
            raise PandocError(f"Unable to determine Pandoc version: {e}") from e
