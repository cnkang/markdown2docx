"""Modern Markdown to DOCX converter with latest standards support."""

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

__version__ = "0.2.0"
__all__ = [
    "MarkdownToDocxConverter",
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
