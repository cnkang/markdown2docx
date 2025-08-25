"""Custom exceptions for markdown2docx package.

This module defines specific exception types to provide better error handling
and debugging experience for users of the markdown2docx library.
"""

from __future__ import annotations


class MarkdownToDocxError(Exception):
    """Base exception for all markdown2docx related errors."""

    def __init__(self, message: str, details: str | None = None) -> None:
        """Initialize the exception with message and optional details.

        Args:
            message: The main error message
            details: Optional additional details about the error
        """
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        """Return a formatted error message."""
        if self.details:
            return f"{self.message}\nDetails: {self.details}"
        return self.message


class PandocError(MarkdownToDocxError):
    """Raised when Pandoc-related operations fail."""

    def __init__(
        self,
        message: str,
        pandoc_version: str | None = None,
        command: str | None = None,
    ) -> None:
        """Initialize Pandoc error with version and command info.

        Args:
            message: The main error message
            pandoc_version: Version of Pandoc that caused the error
            command: The Pandoc command that failed
        """
        details = []
        if pandoc_version:
            details.append(f"Pandoc version: {pandoc_version}")
        if command:
            details.append(f"Failed command: {command}")

        super().__init__(message, "; ".join(details) if details else None)
        self.pandoc_version = pandoc_version
        self.command = command


class PandocNotFoundError(PandocError):
    """Raised when Pandoc is not installed or not found in PATH."""

    def __init__(self) -> None:
        message = "Pandoc not found. Please install Pandoc or call pypandoc.download_pandoc()."
        super().__init__(message)
        self.details = (
            "Visit https://pandoc.org/installing.html for installation instructions"
        )


class ConversionError(MarkdownToDocxError):
    """Raised when markdown to DOCX conversion fails."""

    def __init__(
        self, input_file: str, message: str, original_error: Exception | None = None
    ) -> None:
        """Initialize conversion error with file and original error info.

        Args:
            input_file: Path to the input file that failed to convert
            message: Description of the conversion error
            original_error: The original exception that caused this error
        """
        details = f"Input file: {input_file}"
        if original_error:
            details += (
                f"; Original error: {type(original_error).__name__}: {original_error}"
            )

        super().__init__(message, details)
        self.input_file = input_file
        self.original_error = original_error


class TemplateError(MarkdownToDocxError):
    """Raised when template-related operations fail."""

    def __init__(self, template_path: str | None, message: str) -> None:
        """Initialize template error with template path info.

        Args:
            template_path: Path to the template that caused the error
            message: Description of the template error
        """
        details = f"Template path: {template_path}" if template_path else None
        super().__init__(message, details)
        self.template_path = template_path


class ValidationError(MarkdownToDocxError):
    """Raised when DOCX validation fails."""

    def __init__(self, output_file: str, validation_errors: list[str]) -> None:
        """Initialize validation error with file and validation details.

        Args:
            output_file: Path to the output file that failed validation
            validation_errors: List of validation error messages
        """
        message = f"DOCX validation failed for {output_file}"
        details = "Validation errors: " + "; ".join(validation_errors)

        super().__init__(message, details)
        self.output_file = output_file
        self.validation_errors = validation_errors


class ConfigurationError(MarkdownToDocxError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, config_key: str | None, message: str) -> None:
        """Initialize configuration error with key info.

        Args:
            config_key: The configuration key that caused the error
            message: Description of the configuration error
        """
        details = f"Configuration key: {config_key}" if config_key else None
        super().__init__(message, details)
        self.config_key = config_key
