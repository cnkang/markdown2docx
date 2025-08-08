"""Modern Markdown to DOCX converter with latest standards support."""

from .converter import MarkdownToDocxConverter
from .templates import DocxTemplateManager

__version__ = "0.1.0"
__all__ = ["MarkdownToDocxConverter", "DocxTemplateManager"]