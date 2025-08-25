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
from .templates import DocxTemplateManager

__version__ = "0.1.0"
__all__ = [
    "MarkdownToDocxConverter",
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
