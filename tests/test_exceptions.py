"""Tests for custom exceptions in markdown2docx package."""

import pytest

from markdown2docx.exceptions import (
    ConfigurationError,
    ConversionError,
    MarkdownToDocxError,
    PandocError,
    PandocNotFoundError,
    TemplateError,
    ValidationError,
)


class TestMarkdownToDocxError:
    """Test the base MarkdownToDocxError class."""

    def test_basic_error(self):
        """Test basic error creation and string representation."""
        error = MarkdownToDocxError("Test error message")
        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.details is None

    def test_error_with_details(self):
        """Test error with additional details."""
        error = MarkdownToDocxError("Test error", "Additional details")
        expected = "Test error\nDetails: Additional details"
        assert str(error) == expected
        assert error.message == "Test error"
        assert error.details == "Additional details"


class TestPandocError:
    """Test PandocError and related exceptions."""

    def test_basic_pandoc_error(self):
        """Test basic PandocError creation."""
        error = PandocError("Pandoc failed")
        assert str(error) == "Pandoc failed"
        assert error.pandoc_version is None
        assert error.command is None

    def test_pandoc_error_with_version(self):
        """Test PandocError with version information."""
        error = PandocError("Pandoc failed", pandoc_version="2.19.2")
        expected = "Pandoc failed\nDetails: Pandoc version: 2.19.2"
        assert str(error) == expected
        assert error.pandoc_version == "2.19.2"

    def test_pandoc_error_with_command(self):
        """Test PandocError with command information."""
        error = PandocError("Pandoc failed", command="pandoc -f markdown -t docx")
        expected = "Pandoc failed\nDetails: Failed command: pandoc -f markdown -t docx"
        assert str(error) == expected
        assert error.command == "pandoc -f markdown -t docx"

    def test_pandoc_error_with_version_and_command(self):
        """Test PandocError with both version and command."""
        error = PandocError(
            "Pandoc failed",
            pandoc_version="2.19.2",
            command="pandoc -f markdown -t docx"
        )
        expected = (
            "Pandoc failed\n"
            "Details: Pandoc version: 2.19.2; Failed command: pandoc -f markdown -t docx"
        )
        assert str(error) == expected
        assert error.pandoc_version == "2.19.2"
        assert error.command == "pandoc -f markdown -t docx"

    def test_pandoc_not_found_error(self):
        """Test PandocNotFoundError."""
        error = PandocNotFoundError()
        expected_message = "Pandoc not found. Please install Pandoc or call pypandoc.download_pandoc()."
        assert error.message == expected_message
        assert "installation instructions" in error.details
        assert str(error).startswith(expected_message)


class TestConversionError:
    """Test ConversionError class."""

    def test_basic_conversion_error(self):
        """Test basic ConversionError creation."""
        error = ConversionError("test.md", "Conversion failed")
        assert error.message == "Conversion failed"
        assert error.input_file == "test.md"
        assert error.original_error is None
        assert "Input file: test.md" in str(error)

    def test_conversion_error_with_original_error(self):
        """Test ConversionError with original exception."""
        original = ValueError("Invalid input")
        error = ConversionError("test.md", "Conversion failed", original)
        
        assert error.message == "Conversion failed"
        assert error.input_file == "test.md"
        assert error.original_error is original
        
        error_str = str(error)
        assert "Input file: test.md" in error_str
        assert "Original error: ValueError: Invalid input" in error_str


class TestTemplateError:
    """Test TemplateError class."""

    def test_template_error_with_path(self):
        """Test TemplateError with template path."""
        error = TemplateError("template.docx", "Template is invalid")
        assert error.message == "Template is invalid"
        assert error.template_path == "template.docx"
        assert "Template path: template.docx" in str(error)

    def test_template_error_without_path(self):
        """Test TemplateError without template path."""
        error = TemplateError(None, "Template is invalid")
        assert error.message == "Template is invalid"
        assert error.template_path is None
        assert str(error) == "Template is invalid"


class TestValidationError:
    """Test ValidationError class."""

    def test_validation_error(self):
        """Test ValidationError creation."""
        validation_errors = ["Missing required style", "Invalid structure"]
        error = ValidationError("output.docx", validation_errors)
        
        assert error.message == "DOCX validation failed for output.docx"
        assert error.output_file == "output.docx"
        assert error.validation_errors == validation_errors
        
        error_str = str(error)
        assert "DOCX validation failed for output.docx" in error_str
        assert "Missing required style" in error_str
        assert "Invalid structure" in error_str

    def test_validation_error_single_error(self):
        """Test ValidationError with single validation error."""
        error = ValidationError("output.docx", ["Single error"])
        assert "Single error" in str(error)


class TestConfigurationError:
    """Test ConfigurationError class."""

    def test_configuration_error_with_key(self):
        """Test ConfigurationError with configuration key."""
        error = ConfigurationError("pandoc.path", "Invalid path specified")
        assert error.message == "Invalid path specified"
        assert error.config_key == "pandoc.path"
        assert "Configuration key: pandoc.path" in str(error)

    def test_configuration_error_without_key(self):
        """Test ConfigurationError without configuration key."""
        error = ConfigurationError(None, "Invalid configuration")
        assert error.message == "Invalid configuration"
        assert error.config_key is None
        assert str(error) == "Invalid configuration"


class TestExceptionInheritance:
    """Test exception inheritance hierarchy."""

    def test_all_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from MarkdownToDocxError."""
        exceptions = [
            PandocError("test"),
            PandocNotFoundError(),
            ConversionError("test.md", "test"),
            TemplateError("test.docx", "test"),
            ValidationError("test.docx", ["test"]),
            ConfigurationError("test", "test"),
        ]
        
        for exc in exceptions:
            assert isinstance(exc, MarkdownToDocxError)
            assert isinstance(exc, Exception)

    def test_pandoc_not_found_inherits_from_pandoc_error(self):
        """Test that PandocNotFoundError inherits from PandocError."""
        error = PandocNotFoundError()
        assert isinstance(error, PandocError)
        assert isinstance(error, MarkdownToDocxError)