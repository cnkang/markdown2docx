"""Tests for markdown2docx converter."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from markdown2docx.converter import MarkdownToDocxConverter


@pytest.fixture
def sample_markdown():
    """Sample markdown content."""
    return """# Test Document

This is a **test** document with:

- List item 1
- List item 2

## Section 2

Some `code` and [link](https://example.com).
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


def test_convert_nonexistent_file(converter):
    """Test conversion with nonexistent input file."""
    with pytest.raises(FileNotFoundError):
        converter.convert("nonexistent.md")