"""Tests for markdown2docx converter."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from markdown2docx.converter import MarkdownToDocxConverter
from markdown2docx.templates import DocxTemplateManager


@pytest.fixture
def sample_markdown():
    """Sample markdown content with modern features."""
    return """# Test Document

This is a **test** document with modern markdown features:

## Text Formatting

- **Bold text**
- *Italic text* 
- ~~Strikethrough text~~
- `Inline code`
- H~2~O (subscript)
- E=mc^2^ (superscript)

## Code Blocks

```python
def hello_world():
    print("Hello, World!")
    return True
```

## Tables

| Feature | Status | Notes |
|---------|--------|-------|
| Headers | ✅ | Working |
| Lists | ✅ | All types |
| Code | ✅ | Syntax highlighting |

## Task Lists

- [x] Completed task
- [ ] Pending task
- [ ] Another pending task

## Links and References

Visit [GitHub](https://github.com) for more information.

## Footnotes

This has a footnote[^1].

[^1]: This is the footnote content.
"""


@pytest.fixture
def converter():
    """Converter instance."""
    return MarkdownToDocxConverter()


def test_convert_basic(converter, sample_markdown):
    """Test basic conversion functionality."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        input_path.write_text(sample_markdown)
        
        output_path = converter.convert(input_path)
        
        assert output_path.exists()
        assert output_path.suffix == '.docx'


def test_convert_with_custom_output(converter, sample_markdown):
    """Test conversion with custom output path."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        output_path = Path(tmpdir) / "custom.docx"
        input_path.write_text(sample_markdown)
        
        result = converter.convert(input_path, output_path)
        
        assert result == output_path
        assert output_path.exists()


def test_convert_with_options(converter, sample_markdown):
    """Test conversion with pandoc options."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        input_path.write_text(sample_markdown)
        
        output_path = converter.convert(
            input_path, 
            **{'--toc': True, '--toc-depth': 2}
        )
        
        assert output_path.exists()


def test_convert_with_template(converter, sample_markdown):
    """Test conversion with template."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        template_path = Path(tmpdir) / "template.docx"
        input_path.write_text(sample_markdown)
        
        # Create a template first
        DocxTemplateManager.create_modern_template(template_path)
        
        output_path = converter.convert_with_template(
            input_path, template_path
        )
        
        assert output_path.exists()


def test_convert_nonexistent_file(converter):
    """Test conversion with nonexistent input file."""
    with pytest.raises(FileNotFoundError):
        converter.convert("nonexistent.md")


def test_template_creation():
    """Test modern template creation."""
    with TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "modern_template.docx"
        
        result = DocxTemplateManager.create_modern_template(template_path)
        
        assert result == template_path
        assert template_path.exists()


def test_converter_with_reference_doc(sample_markdown):
    """Test converter initialization with reference document."""
    with TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "template.docx"
        DocxTemplateManager.create_modern_template(template_path)
        
        converter = MarkdownToDocxConverter(reference_doc=template_path)
        assert converter.reference_doc == template_path