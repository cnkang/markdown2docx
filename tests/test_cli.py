"""Comprehensive tests for CLI functionality.

包含基本CLI功能测试和扩展功能测试。
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pytest

from markdown2docx.cli import (
    create_argument_parser,
    handle_conversion,
    handle_template_creation,
    main,
)
from markdown2docx.config import MarkdownToDocxConfig
from markdown2docx.exceptions import MarkdownToDocxError


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


def run_cli_command(args):
    """Helper function to run CLI commands from repository root."""
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "src.markdown2docx.cli"] + args
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    return result


# ============================================================================
# Basic CLI Integration Tests
# ============================================================================


def test_cli_basic_conversion(sample_markdown_content):
    """Test basic CLI conversion functionality."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        input_file.write_text(sample_markdown_content)

        result = run_cli_command([str(input_file)])

        assert result.returncode == 0
        assert "Successfully converted" in result.stdout

        output_file = input_file.with_suffix(".docx")
        assert output_file.exists()


def test_cli_custom_output(sample_markdown_content):
    """Test CLI with custom output file."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        output_file = tmpdir_path / "custom_output.docx"
        input_file.write_text(sample_markdown_content)

        result = run_cli_command([str(input_file), "-o", str(output_file)])

        assert result.returncode == 0
        assert output_file.exists()


def test_cli_template_creation():
    """Test CLI template creation functionality."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        template_file = tmpdir_path / "test_template.docx"

        result = run_cli_command(["--create-template", str(template_file)])

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
        result = run_cli_command(["--create-template", str(template_file)])
        assert result.returncode == 0

        # Then use template for conversion
        result = run_cli_command([str(input_file), "--template", str(template_file)])

        assert result.returncode == 0
        assert "Successfully converted" in result.stdout


def test_cli_with_toc(sample_markdown_content):
    """Test CLI conversion with table of contents."""
    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_file = tmpdir_path / "test.md"
        input_file.write_text(sample_markdown_content)

        result = run_cli_command([str(input_file), "--toc", "--toc-depth", "2"])

        assert result.returncode == 0
        assert "Successfully converted" in result.stdout


def test_cli_nonexistent_file():
    """Test CLI with nonexistent input file."""
    result = run_cli_command(["nonexistent.md"])

    assert result.returncode == 1
    assert "Input file not found" in result.stderr


def test_cli_help():
    """Test CLI help functionality."""
    result = run_cli_command(["--help"])

    assert result.returncode == 0
    assert (
        "Convert Markdown files to modern DOCX format with advanced features"
        in result.stdout
    )
    assert "Examples:" in result.stdout


def test_cli_no_input():
    """Test CLI without input file."""
    result = run_cli_command([])

    assert result.returncode == 2  # argparse error
    assert "required" in result.stderr.lower()


# ============================================================================
# Argument Parser Tests
# ============================================================================


class TestArgumentParser:
    """Test argument parser functionality."""

    def test_create_argument_parser(self):
        """Test argument parser creation."""
        parser = create_argument_parser()
        assert parser is not None
        assert parser.prog == "markdown2docx"

    def test_parser_help_output(self):
        """Test parser help output contains expected information."""
        parser = create_argument_parser()
        help_text = parser.format_help()

        assert "Convert Markdown files to modern DOCX format" in help_text
        assert "--template" in help_text
        assert "--toc" in help_text
        assert "--verbose" in help_text
        assert "--create-template" in help_text

    def test_parser_basic_args(self):
        """Test parsing basic arguments."""
        parser = create_argument_parser()
        args = parser.parse_args(["input.md"])

        assert args.input == "input.md"
        assert args.output is None
        assert args.template is None
        assert args.toc is None
        assert args.validate is None
        assert args.verbose is False

    def test_parser_all_args(self):
        """Test parsing all available arguments."""
        parser = create_argument_parser()
        args = parser.parse_args(
            [
                "input.md",
                "--output",
                "output.docx",
                "--template",
                "template.docx",
                "--toc",
                "--toc-depth",
                "3",
                "--validate",
                "--verbose",
                "--quiet",
            ]
        )

        assert args.input == "input.md"
        assert args.output == "output.docx"
        assert args.template == "template.docx"
        assert args.toc is True
        assert args.toc_depth == 3
        assert args.validate is True
        assert args.verbose is True
        assert args.quiet is True

    def test_parser_create_template(self):
        """Test parsing create template arguments."""
        parser = create_argument_parser()
        args = parser.parse_args(["--create-template", "new_template.docx"])

        assert args.create_template == "new_template.docx"
        assert args.input is None

    def test_parser_conflicting_args(self):
        """Test parser handles conflicting arguments gracefully."""
        parser = create_argument_parser()
        # Last flag wins when both are provided
        args = parser.parse_args(["input.md", "--validate", "--no-validate"])

        assert args.validate is False


# ============================================================================
# Template Creation Handler Tests
# ============================================================================


class TestHandleTemplateCreation:
    """Test template creation handling."""

    @patch("markdown2docx.cli.DocxTemplateManager.create_modern_template")
    def test_handle_template_creation_success(self, mock_create):
        """Test successful template creation."""
        mock_create.return_value = Path("created_template.docx")

        result = handle_template_creation("new_template.docx", verbose=False)

        assert result == 0
        mock_create.assert_called_once_with("new_template.docx", add_sample=True)

    @patch("markdown2docx.cli.DocxTemplateManager.create_modern_template")
    def test_handle_template_creation_verbose(self, mock_create):
        """Test template creation with verbose output."""
        mock_create.return_value = Path("created_template.docx")

        with patch("builtins.print") as mock_print:
            result = handle_template_creation("new_template.docx", verbose=True)

            assert result == 0
            mock_create.assert_called_once()

            # Check verbose output was printed
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            assert any(
                "Successfully created modern DOCX template" in call
                for call in print_calls
            )
            assert any("Location:" in call for call in print_calls)

    @patch("markdown2docx.cli.DocxTemplateManager.create_modern_template")
    def test_handle_template_creation_error(self, mock_create):
        """Test template creation error handling."""
        mock_create.side_effect = MarkdownToDocxError(
            "Template creation failed", "Details here"
        )

        with patch("markdown2docx.cli.logger") as mock_logger:
            result = handle_template_creation("new_template.docx", verbose=True)

            assert result == 1
            mock_logger.error.assert_called()

    @patch("markdown2docx.cli.DocxTemplateManager.create_modern_template")
    def test_handle_template_creation_unexpected_error(self, mock_create):
        """Test template creation unexpected error handling."""
        mock_create.side_effect = RuntimeError("Unexpected error")

        with patch("markdown2docx.cli.logger") as mock_logger:
            result = handle_template_creation("new_template.docx", verbose=False)

            assert result == 1
            mock_logger.error.assert_called()


# ============================================================================
# Conversion Handler Tests
# ============================================================================


class TestHandleConversion:
    """Test conversion handling."""

    def test_handle_conversion_success(self):
        """Test successful conversion handling."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test Document\nContent here.")
            tmp.flush()
            input_path = tmp.name

            config = MarkdownToDocxConfig()

            try:
                with patch(
                    "markdown2docx.cli.MarkdownToDocxConverter"
                ) as mock_converter_class:
                    mock_converter = Mock()
                    mock_converter.convert.return_value = Path("output.docx")
                    mock_converter_class.return_value = mock_converter

                    result = handle_conversion(
                        input_path=input_path,
                        output_path=None,
                        template_path=None,
                        toc=False,
                        toc_depth=None,
                        validate=None,
                        config=config,
                        verbose=False,
                    )

                    assert result == 0
                    mock_converter.convert.assert_called_once()
                    call_kwargs = mock_converter.convert.call_args[1]
                    assert call_kwargs["toc"] is False
            finally:
                Path(input_path).unlink()

    def test_handle_conversion_preserves_toc_default(self):
        """Test conversion keeps config default when CLI does not set TOC."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test Document\nContent here.")
            tmp.flush()
            input_path = tmp.name

            config = MarkdownToDocxConfig()

            try:
                with patch(
                    "markdown2docx.cli.MarkdownToDocxConverter"
                ) as mock_converter_class:
                    mock_converter = Mock()
                    mock_converter.convert.return_value = Path("output.docx")
                    mock_converter_class.return_value = mock_converter

                    result = handle_conversion(
                        input_path=input_path,
                        output_path=None,
                        template_path=None,
                        toc=None,
                        toc_depth=None,
                        validate=None,
                        config=config,
                        verbose=False,
                    )

                    assert result == 0
                    call_kwargs = mock_converter.convert.call_args[1]
                    assert call_kwargs["toc"] is None
            finally:
                Path(input_path).unlink()

    def test_handle_conversion_with_all_options(self):
        """Test conversion with all options enabled."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test Document\n## Section 1\nContent here.")
            tmp.flush()
            input_path = tmp.name

            config = MarkdownToDocxConfig()

            try:
                with patch(
                    "markdown2docx.cli.MarkdownToDocxConverter"
                ) as mock_converter_class:
                    mock_converter = Mock()
                    mock_converter.convert.return_value = Path("output.docx")
                    mock_converter_class.return_value = mock_converter

                    result = handle_conversion(
                        input_path=input_path,
                        output_path="custom_output.docx",
                        template_path="template.docx",
                        toc=True,
                        toc_depth=4,
                        validate=True,
                        config=config,
                        verbose=True,
                    )

                    assert result == 0

                    # Verify converter was called with correct arguments
                    mock_converter.convert.assert_called_once()
                    call_kwargs = mock_converter.convert.call_args[1]
                    assert call_kwargs["toc"] is True
                    assert call_kwargs["toc_depth"] == 4
                    assert call_kwargs["validate_output"] is True
            finally:
                Path(input_path).unlink()

    def test_handle_conversion_error(self):
        """Test conversion error handling."""
        config = MarkdownToDocxConfig()

        with patch("markdown2docx.cli.MarkdownToDocxConverter") as mock_converter_class:
            mock_converter = Mock()
            mock_converter.convert.side_effect = MarkdownToDocxError(
                "Conversion failed"
            )
            mock_converter_class.return_value = mock_converter

            with patch("markdown2docx.cli.logger") as mock_logger:
                result = handle_conversion(
                    input_path="nonexistent.md",
                    output_path=None,
                    template_path=None,
                    toc=False,
                    toc_depth=None,
                    validate=None,
                    config=config,
                    verbose=False,
                )

                assert result == 1
                mock_logger.error.assert_called()

    def test_handle_conversion_verbose_output(self):
        """Test conversion with verbose output."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test Document\nContent here.")
            tmp.flush()
            input_path = tmp.name

            config = MarkdownToDocxConfig()

            try:
                with patch(
                    "markdown2docx.cli.MarkdownToDocxConverter"
                ) as mock_converter_class:
                    mock_converter = Mock()
                    mock_converter.convert.return_value = Path("output.docx")
                    mock_converter_class.return_value = mock_converter

                    with patch("builtins.print") as mock_print:
                        result = handle_conversion(
                            input_path=input_path,
                            output_path=None,
                            template_path="template.docx",
                            toc=True,
                            toc_depth=2,
                            validate=None,
                            config=config,
                            verbose=True,
                        )

                        assert result == 0

                        # Check verbose output
                        print_calls = [call[0][0] for call in mock_print.call_args_list]
                        assert any(
                            "Conversion completed successfully" in call
                            for call in print_calls
                        )
                        assert any("Input:" in call for call in print_calls)
                        assert any("Output:" in call for call in print_calls)
                        assert any("Template:" in call for call in print_calls)
                        assert any("Table of contents:" in call for call in print_calls)
            finally:
                Path(input_path).unlink()


# ============================================================================
# Main Function Tests
# ============================================================================


class TestMainFunction:
    """Test main function integration."""

    def test_main_help(self):
        """Test main function with help argument."""
        with patch("sys.argv", ["markdown2docx", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_no_args(self):
        """Test main function with no arguments."""
        with patch("sys.argv", ["markdown2docx"]):
            with patch("markdown2docx.cli.create_argument_parser") as mock_parser:
                mock_parser_instance = Mock()
                mock_parser_instance.parse_args.return_value = Mock(
                    input=None, create_template=None
                )
                mock_parser_instance.error = Mock(side_effect=SystemExit(2))
                mock_parser.return_value = mock_parser_instance

                with pytest.raises(SystemExit):
                    main()

    def test_main_create_template(self):
        """Test main function with create template option."""
        with patch("sys.argv", ["markdown2docx", "--create-template", "template.docx"]):
            with patch("markdown2docx.cli.handle_template_creation") as mock_handle:
                mock_handle.return_value = 0

                main()  # Should not raise SystemExit
                mock_handle.assert_called_once_with("template.docx", False)

    def test_main_conversion(self):
        """Test main function with conversion."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = tmp.name

            try:
                with patch("sys.argv", ["markdown2docx", input_path]):
                    with patch("markdown2docx.cli.handle_conversion") as mock_handle:
                        mock_handle.return_value = 0

                        main()  # Should not raise SystemExit
                        mock_handle.assert_called_once()
            finally:
                Path(input_path).unlink()

    def test_main_with_config_loading(self):
        """Test main function loads configuration correctly."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = tmp.name

            try:
                with patch("sys.argv", ["markdown2docx", input_path, "--verbose"]):
                    with patch("markdown2docx.cli.load_config") as mock_load_config:
                        mock_config = MarkdownToDocxConfig()
                        mock_load_config.return_value = mock_config

                        with patch(
                            "markdown2docx.cli.handle_conversion"
                        ) as mock_handle:
                            mock_handle.return_value = 0

                            main()  # Should not raise SystemExit

                            # Verify config was loaded and passed to handle_conversion
                            mock_load_config.assert_called_once()
                            call_kwargs = mock_handle.call_args[1]
                            assert call_kwargs["config"] is mock_config
                            assert call_kwargs["verbose"] is True
            finally:
                Path(input_path).unlink()

    def test_main_validation_options(self):
        """Test main function handles validation options correctly."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = tmp.name

            try:
                # Test --validate option
                with patch("sys.argv", ["markdown2docx", input_path, "--validate"]):
                    with patch("markdown2docx.cli.handle_conversion") as mock_handle:
                        mock_handle.return_value = 0

                        main()

                        call_kwargs = mock_handle.call_args[1]
                        assert call_kwargs["validate"] is True

                # Test --no-validate option
                with patch("sys.argv", ["markdown2docx", input_path, "--no-validate"]):
                    with patch("markdown2docx.cli.handle_conversion") as mock_handle:
                        mock_handle.return_value = 0

                        main()

                        call_kwargs = mock_handle.call_args[1]
                        assert call_kwargs["validate"] is False

                # Test both options (last option wins)
                with patch(
                    "sys.argv",
                    ["markdown2docx", input_path, "--validate", "--no-validate"],
                ):
                    with patch("markdown2docx.cli.handle_conversion") as mock_handle:
                        mock_handle.return_value = 0

                        main()

                        call_kwargs = mock_handle.call_args[1]
                        assert call_kwargs["validate"] is False
            finally:
                Path(input_path).unlink()

    def test_main_quiet_mode(self):
        """Test main function with quiet mode."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = tmp.name

            try:
                with patch("sys.argv", ["markdown2docx", input_path, "--quiet"]):
                    with patch("markdown2docx.cli.logging") as mock_logging:
                        with patch(
                            "markdown2docx.cli.handle_conversion"
                        ) as mock_handle:
                            mock_handle.return_value = 0

                            main()

                            # Verify logging level was set to ERROR for quiet mode
                            mock_logging.basicConfig.assert_called()
                            call_kwargs = mock_logging.basicConfig.call_args[1]
                            assert call_kwargs["level"] == mock_logging.ERROR
            finally:
                Path(input_path).unlink()


# ============================================================================
# Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Test CLI integration scenarios."""

    def test_cli_end_to_end_conversion(self):
        """Test complete CLI conversion workflow."""
        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False
        ) as md_tmp:
            md_tmp.write(
                "# Test Document\n\n## Section 1\nContent here.\n\n## Section 2\nMore content."
            )
            md_tmp.flush()
            input_path = md_tmp.name

            with tempfile.NamedTemporaryFile(
                suffix=".docx", delete=False
            ) as output_tmp:
                output_path = output_tmp.name

                try:
                    argv = [
                        "markdown2docx",
                        input_path,
                        "--output",
                        output_path,
                        "--toc",
                        "--toc-depth",
                        "2",
                        "--verbose",
                    ]

                    with patch("sys.argv", argv):
                        with patch(
                            "markdown2docx.cli.MarkdownToDocxConverter"
                        ) as mock_converter_class:
                            mock_converter = Mock()
                            mock_converter.convert.return_value = Path(output_path)
                            mock_converter_class.return_value = mock_converter

                            result = main()

                            # Should not raise SystemExit
                            mock_converter.convert.assert_called_once()

                            # Verify correct arguments were passed
                            call_args = mock_converter.convert.call_args
                            assert str(call_args[0][0]) == input_path  # input_path
                            assert str(call_args[0][1]) == output_path  # output_path
                            assert call_args[1]["toc"] is True
                            assert call_args[1]["toc_depth"] == 2
                finally:
                    Path(input_path).unlink()
                    Path(output_path).unlink(missing_ok=True)

    def test_cli_template_creation_workflow(self):
        """Test complete CLI template creation workflow."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            template_path = tmp.name

            try:
                argv = [
                    "markdown2docx",
                    "--create-template",
                    template_path,
                    "--verbose",
                ]

                with patch("sys.argv", argv):
                    with patch(
                        "markdown2docx.cli.DocxTemplateManager.create_modern_template"
                    ) as mock_create:
                        mock_create.return_value = Path(template_path)

                        result = main()

                        # main() doesn't return a value, it exits with sys.exit()
                        # If we reach here, it means no exception was raised
                        mock_create.assert_called_once_with(
                            template_path, add_sample=True
                        )
            finally:
                Path(template_path).unlink(missing_ok=True)
