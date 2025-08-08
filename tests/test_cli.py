"""Tests for CLI functionality.

CLI集成测试，确保命令行功能正常工作。
"""

import pytest
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


@pytest.fixture
def sample_markdown_content():
    """Sample markdown content for CLI testing."""
    return """# Test Document

This is a **test** document for CLI testing.

## Features

- Basic formatting
- Lists and tables
- Code blocks

```python
def hello():
    print("Hello, World!")
```

| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |
"""


def run_cli_command(args, cwd=None):
    """Helper function to run CLI commands."""
    cmd = [sys.executable, "-m", "src.markdown2docx.cli"] + args
    result = subprocess.run(
        cmd, 
        cwd=cwd,
        capture_output=True, 
        text=True
    )
    return result


def test_cli_basic_conversion(sample_markdown_content):
    """Test basic CLI conversion functionality."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        input_file.write_text(sample_markdown_content)
        
        result = run_cli_command([str(input_file)], cwd=tmpdir_path.parent)
        
        assert result.returncode == 0
        assert "Successfully converted" in result.stdout
        
        output_file = input_file.with_suffix('.docx')
        assert output_file.exists()


def test_cli_custom_output(sample_markdown_content):
    """Test CLI with custom output file."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        output_file = tmpdir_path / "custom_output.docx"
        input_file.write_text(sample_markdown_content)
        
        result = run_cli_command([
            str(input_file), 
            "-o", str(output_file)
        ], cwd=tmpdir_path.parent)
        
        assert result.returncode == 0
        assert output_file.exists()


def test_cli_template_creation():
    """Test CLI template creation functionality."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        template_file = tmpdir_path / "test_template.docx"
        
        result = run_cli_command([
            "--create-template", str(template_file)
        ], cwd=tmpdir_path.parent)
        
        assert result.returncode == 0
        assert "Created modern DOCX template" in result.stdout
        assert template_file.exists()


def test_cli_with_template(sample_markdown_content):
    """Test CLI conversion with template."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        template_file = tmpdir_path / "template.docx"
        input_file.write_text(sample_markdown_content)
        
        # First create template
        result = run_cli_command([
            "--create-template", str(template_file)
        ], cwd=tmpdir_path.parent)
        assert result.returncode == 0
        
        # Then use template for conversion
        result = run_cli_command([
            str(input_file),
            "--template", str(template_file)
        ], cwd=tmpdir_path.parent)
        
        assert result.returncode == 0
        assert "Used template" in result.stdout


def test_cli_with_toc(sample_markdown_content):
    """Test CLI conversion with table of contents."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        input_file.write_text(sample_markdown_content)
        
        result = run_cli_command([
            str(input_file),
            "--toc",
            "--toc-depth", "2"
        ], cwd=tmpdir_path.parent)
        
        assert result.returncode == 0
        assert "Successfully converted" in result.stdout


def test_cli_nonexistent_file():
    """Test CLI with nonexistent input file."""
    result = run_cli_command(["nonexistent.md"])
    
    assert result.returncode == 1
    assert "Conversion failed" in result.stdout


def test_cli_help():
    """Test CLI help functionality."""
    result = run_cli_command(["--help"])
    
    assert result.returncode == 0
    assert "Convert Markdown to modern DOCX format" in result.stdout
    assert "Examples:" in result.stdout


def test_cli_no_input():
    """Test CLI without input file."""
    result = run_cli_command([])
    
    assert result.returncode == 2  # argparse error
    assert "required" in result.stderr.lower()