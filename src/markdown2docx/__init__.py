"""Modern Markdown to DOCX converter with latest standards support."""

from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, MarkdownToDocxConfig
from .converter import MarkdownToDocxConverter
from .exceptions import (
    ConfigurationError,
    ConversionError,
    MarkdownToDocxError,
    PandocError,
    PandocNotFoundError,
    TemplateError,
    ValidationError,
)
from .fonts import FontError
from .report import ConversionReport
from .templates import DocxTemplateManager
from .version import __version__ as __version__


def convert_untrusted(
    input_path: str | Path,
    output_path: str | Path | None = None,
    **kwargs: Any,
) -> Path:
    """Convert untrusted Markdown through the default-safe conversion entry point."""
    return MarkdownToDocxConverter().convert_untrusted(
        input_path, output_path, **kwargs
    )


def convert_untrusted_with_report(
    input_path: str | Path,
    output_path: str | Path | None = None,
    **kwargs: Any,
) -> ConversionReport:
    """Convert untrusted Markdown with restricted resources and offline fonts."""
    return MarkdownToDocxConverter().convert_untrusted_with_report(
        input_path, output_path, **kwargs
    )


__all__ = [
    "MarkdownToDocxConverter",
    "convert_untrusted",
    "convert_untrusted_with_report",
    "ConversionReport",
    "FontError",
    "DocxTemplateManager",
    "MarkdownToDocxConfig",
    "DEFAULT_CONFIG",
    "MarkdownToDocxError",
    "PandocError",
    "PandocNotFoundError",
    "ConversionError",
    "TemplateError",
    "ValidationError",
    "ConfigurationError",
]
