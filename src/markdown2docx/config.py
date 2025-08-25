"""Configuration management for markdown2docx.

This module provides centralized configuration management with support for
default values, environment variables, and configuration files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import ConfigurationError


@dataclass
class PandocConfig:
    """Configuration for Pandoc-related settings."""

    min_version: str = "2.19"
    """Minimum recommended Pandoc version."""

    reader_format: str = (
        "gfm" "+footnotes" "+tex_math_dollars" "+fenced_divs" "+bracketed_spans"
    )
    """Default Markdown reader format with extensions."""

    writer_format: str = "docx+styles"
    """Default DOCX writer format."""

    timeout_seconds: int = 300
    """Timeout for Pandoc operations in seconds."""


@dataclass
class TemplateConfig:
    """Configuration for DOCX template settings."""

    page_size: str = "A4"
    """Default page size (A4 or Letter)."""

    margin_cm: float = 2.54
    """Default margin in centimeters (≈1 inch)."""

    body_font: str = "Calibri"
    """Default body text font."""

    body_size_pt: int = 11
    """Default body text size in points."""

    heading_font: str = "Calibri"
    """Default heading font."""

    code_font: str = "Consolas"
    """Default code block font."""

    code_size_pt: int = 9
    """Default code block font size in points."""


@dataclass
class ConversionConfig:
    """Configuration for conversion settings."""

    default_toc: bool = False
    """Whether to include table of contents by default."""

    default_toc_depth: int = 3
    """Default table of contents depth."""

    validate_output: bool = False
    """Whether to validate output DOCX files by default."""

    create_backup: bool = False
    """Whether to create backup of existing output files."""

    overwrite_existing: bool = True
    """Whether to overwrite existing output files."""


@dataclass
class LoggingConfig:
    """Configuration for logging settings."""

    level: str = "INFO"
    """Default logging level."""

    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    """Default logging format."""

    file_path: Optional[str] = None
    """Optional log file path."""


@dataclass
class MarkdownToDocxConfig:
    """Main configuration class for markdown2docx."""

    pandoc: PandocConfig = field(default_factory=PandocConfig)
    template: TemplateConfig = field(default_factory=TemplateConfig)
    conversion: ConversionConfig = field(default_factory=ConversionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> MarkdownToDocxConfig:
        """Create configuration from dictionary.

        Args:
            config_dict: Dictionary containing configuration values

        Returns:
            MarkdownToDocxConfig instance

        Raises:
            ConfigurationError: If configuration is invalid
        """
        try:
            pandoc_config = PandocConfig(**config_dict.get("pandoc", {}))
            template_config = TemplateConfig(**config_dict.get("template", {}))
            conversion_config = ConversionConfig(**config_dict.get("conversion", {}))
            logging_config = LoggingConfig(**config_dict.get("logging", {}))

            return cls(
                pandoc=pandoc_config,
                template=template_config,
                conversion=conversion_config,
                logging=logging_config,
            )
        except TypeError as e:
            raise ConfigurationError(None, f"Invalid configuration format: {e}") from e

    @classmethod
    def from_env(cls) -> MarkdownToDocxConfig:
        """Create configuration from environment variables.

        Environment variables should be prefixed with 'MD2DOCX_' and use
        double underscores to separate nested keys (e.g., MD2DOCX_PANDOC__MIN_VERSION).

        Returns:
            MarkdownToDocxConfig instance with values from environment
        """
        config_dict: Dict[str, Any] = {}

        # Parse environment variables
        for key, value in os.environ.items():
            if not key.startswith("MD2DOCX_"):
                continue

            # Remove prefix and convert to lowercase
            config_key = key[8:].lower()

            # Handle nested keys (double underscore separator)
            if "__" in config_key:
                section, setting = config_key.split("__", 1)
                if section not in config_dict:
                    config_dict[section] = {}
                config_dict[section][setting] = _parse_env_value(value)
            else:
                config_dict[config_key] = _parse_env_value(value)

        return cls.from_dict(config_dict)

    def get_pandoc_args(self, *, toc: bool = False, toc_depth: int = 3) -> list[str]:
        """Get Pandoc arguments based on configuration.

        Args:
            toc: Whether to include table of contents
            toc_depth: Depth of table of contents

        Returns:
            List of Pandoc command line arguments
        """
        args = ["-f", self.pandoc.reader_format, "-t", self.pandoc.writer_format]

        if toc:
            args.extend(["--toc", "--toc-depth", str(toc_depth)])

        return args


def _parse_env_value(value: str) -> Any:
    """Parse environment variable value to appropriate Python type.

    Args:
        value: String value from environment variable

    Returns:
        Parsed value (bool, int, float, or str)
    """
    # Handle boolean values
    if value.lower() in ("true", "yes", "1", "on"):
        return True
    elif value.lower() in ("false", "no", "0", "off"):
        return False

    # Handle numeric values
    try:
        if "." in value:
            return float(value)
        else:
            return int(value)
    except ValueError:
        pass

    # Return as string
    return value


def load_config(config_path: Optional[Path] = None) -> MarkdownToDocxConfig:
    """Load configuration from file or environment.

    Args:
        config_path: Optional path to configuration file

    Returns:
        MarkdownToDocxConfig instance

    Raises:
        ConfigurationError: If configuration file is invalid
    """
    if config_path and config_path.exists():
        # TODO: Add support for YAML/TOML config files
        # For now, just use environment variables
        pass

    # Load from environment variables
    return MarkdownToDocxConfig.from_env()


# Global default configuration instance
DEFAULT_CONFIG = MarkdownToDocxConfig()
