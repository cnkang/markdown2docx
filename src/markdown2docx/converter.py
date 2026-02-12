"""Markdown → DOCX converter with modern standards support and robust error handling.

This module provides the main MarkdownToDocxConverter class for converting
Markdown files to DOCX format using Pandoc with enhanced error handling,
type safety, and configuration management.
"""

from __future__ import annotations

import logging
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
        *,
        toc: Optional[bool] = None,
        toc_depth: Optional[int] = None,
        extra_args: Optional[Sequence[str]] = None,
        validate_output: Optional[bool] = None,
    ) -> Path:
        """Convert a Markdown file to DOCX format.

        Args:
            input_path: Path to the input Markdown file.
            output_path: Optional path for the output DOCX file.
                        If None, uses input filename with .docx extension.
            toc: Whether to include table of contents.
                If None, uses configuration default.
            toc_depth: Depth of table of contents (1-6).
                      If None, uses configuration default.
            extra_args: Additional Pandoc command line arguments.
            validate_output: Whether to validate the output DOCX file.
                           If None, uses configuration default.

        Returns:
            Path to the generated DOCX file.

        Raises:
            FileNotFoundError: If the input file does not exist.
            ConversionError: If the conversion process fails.
            ValidationError: If output validation fails (when enabled).

        Example:
            >>> converter = MarkdownToDocxConverter()
            >>> output = converter.convert("document.md", toc=True, toc_depth=2)
            >>> print(f"Generated: {output}")
        """
        # Validate and prepare paths
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

        # Use configuration defaults if not specified
        if toc is None:
            toc = self.config.conversion.default_toc
        if toc_depth is None:
            toc_depth = self.config.conversion.default_toc_depth
        if validate_output is None:
            validate_output = self.config.conversion.validate_output

        # Validate toc_depth
        if not 1 <= toc_depth <= 6:
            raise ConversionError(
                str(input_path),
                f"Table of contents depth must be between 1 and 6, got {toc_depth}",
            )

        # Create output directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle existing output file
        if output_path.exists() and not self.config.conversion.overwrite_existing:
            raise ConversionError(
                str(input_path), f"Output file already exists: {output_path}"
            )

        # Build Pandoc arguments
        args = self._build_pandoc_args(
            toc=toc, toc_depth=toc_depth, extra_args=extra_args
        )

        logger.info("Converting %s to %s", input_path, output_path)
        logger.debug("Pandoc arguments: %s", args)

        # Perform conversion
        try:
            pypandoc.convert_file(
                str(input_path),
                to="docx",
                outputfile=str(output_path),
                extra_args=args,
            )
        except OSError as e:
            raise PandocNotFoundError() from e
        except Exception as e:
            raise ConversionError(
                str(input_path), f"Pandoc conversion failed: {e}", original_error=e
            ) from e

        # Validate output if requested
        if validate_output:
            self._validate_docx_output(output_path)

        logger.info("Successfully converted to %s", output_path)
        return output_path

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
                logger.warning(
                    "Reference document not found: %s. Proceeding without template.",
                    self.reference_doc,
                )

        # Add any extra arguments provided by caller
        if extra_args:
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
