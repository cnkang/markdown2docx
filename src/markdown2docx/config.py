"""Configuration management for markdown2docx.

This module provides centralized configuration management with support for
default values, environment variables, and configuration files.
"""

from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import ConfigurationError


@dataclass
class PandocConfig:
    """Configuration for Pandoc-related settings."""

    min_version: str = "2.19"
    """Minimum recommended Pandoc version."""

    reader_format: str = (
        "gfm+footnotes+tex_math_dollars+fenced_divs+bracketed_spans+yaml_metadata_block"
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

    body_font: str = "Noto Sans"
    """Default body text font."""

    body_size_pt: int = 11
    """Default body text size in points."""

    heading_font: str = "Noto Sans"
    """Default heading font."""

    code_font: str = "Noto Sans Mono"
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
class InternationalConfig:
    """Document settings; API options and metadata take precedence."""

    lang: str | None = None
    direction: str = "auto"
    offline: bool = False
    allow_unverified_fonts: bool = False
    font_cache: str | None = None
    resources_offline: bool = False
    restricted: bool = False


@dataclass
class LimitsConfig:
    """Resource budgets; limits fail explicitly without truncating content."""

    input_bytes: int = 64 * 1024 * 1024
    archive_bytes: int = 512 * 1024 * 1024
    archive_entries: int = 10000
    xml_bytes: int = 64 * 1024 * 1024
    preview_pages: int = 200


@dataclass
class MarkdownToDocxConfig:
    """Main configuration class for markdown2docx."""

    pandoc: PandocConfig = field(default_factory=PandocConfig)
    template: TemplateConfig = field(default_factory=TemplateConfig)
    conversion: ConversionConfig = field(default_factory=ConversionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    international: InternationalConfig = field(default_factory=InternationalConfig)

    limits: LimitsConfig = field(default_factory=LimitsConfig)

    def validate(self) -> None:
        """Check configuration at both file and API boundaries."""
        for section_field in fields(self):
            section = getattr(self, section_field.name)
            for setting in fields(section):
                value = getattr(section, setting.name)
                default = getattr(type(section)(), setting.name)
                key = f"{section_field.name}.{setting.name}"
                if default is None:
                    valid = value is None or isinstance(value, str)
                elif isinstance(default, bool):
                    valid = type(value) is bool
                elif isinstance(default, int):
                    valid = type(value) is int and value > 0
                elif isinstance(default, float):
                    valid = (
                        type(value) in (int, float)
                        and math.isfinite(value)
                        and value > 0
                    )
                else:
                    valid = isinstance(value, str) and bool(value.strip())
                if not valid:
                    raise ConfigurationError(key, f"Invalid value: {value!r}")
        if self.template.page_size not in {"A4", "Letter"}:
            raise ConfigurationError("template.page_size", "Expected A4 or Letter")
        if not 1 <= self.conversion.default_toc_depth <= 6:
            raise ConfigurationError(
                "conversion.default_toc_depth", "Expected 1 through 6"
            )
        if self.international.direction not in {"auto", "ltr", "rtl"}:
            raise ConfigurationError(
                "international.direction", "Expected auto, ltr or rtl"
            )
        if self.logging.level.upper() not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ConfigurationError("logging.level", "Unknown logging level")
        if self.conversion.create_backup:
            raise ConfigurationError(
                "conversion.create_backup",
                "Backups are unsupported; preserve copies explicitly",
            )
        from packaging.version import InvalidVersion, Version

        try:
            Version(self.pandoc.min_version)
        except InvalidVersion as exc:
            raise ConfigurationError("pandoc.min_version", "Invalid version") from exc
        if self.international.lang is not None:
            import langcodes

            if not langcodes.tag_is_valid(self.international.lang):
                raise ConfigurationError(
                    "international.lang", "Invalid BCP 47 language"
                )

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
        section_types = {
            "pandoc": PandocConfig,
            "template": TemplateConfig,
            "conversion": ConversionConfig,
            "logging": LoggingConfig,
            "international": InternationalConfig,
            "limits": LimitsConfig,
        }
        for name, values in config_dict.items():
            if name not in section_types:
                raise ConfigurationError(name, "Unknown configuration section")
            if not isinstance(values, dict):
                raise ConfigurationError(name, "Expected a mapping")
            known = {item.name for item in fields(section_types[name])}
            for key in values:
                if key not in known:
                    raise ConfigurationError(
                        f"{name}.{key}", "Unknown configuration field"
                    )
        try:
            result = cls(
                **{
                    name: kind(**config_dict.get(name, {}))
                    for name, kind in section_types.items()
                }
            )
        except TypeError as exc:
            raise ConfigurationError(
                None, f"Invalid configuration format: {exc}"
            ) from exc
        result.validate()
        return result

    @classmethod
    def from_env(cls) -> MarkdownToDocxConfig:
        """Create configuration from environment variables.

        Environment variables should be prefixed with 'MD2DOCX_' and use
        double underscores to separate nested keys (e.g., MD2DOCX_PANDOC__MIN_VERSION).

        Returns:
            MarkdownToDocxConfig instance with values from environment
        """
        return cls.from_dict(_parse_env_config())

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
    if value.lower() in ("false", "no", "0", "off"):
        return False

    # Handle numeric values
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # Return as string
    return value


def _parse_env_config() -> Dict[str, Any]:
    """Parse MD2DOCX_* environment variables into a nested config dictionary."""
    config_dict: Dict[str, Any] = {}

    for key, value in os.environ.items():
        if not key.startswith("MD2DOCX_"):
            continue

        config_key = key[8:].lower()
        if "__" in config_key:
            section, setting = config_key.split("__", 1)
            section_values = config_dict.setdefault(section, {})
            if isinstance(section_values, dict):
                boolean_fields = {
                    "default_toc",
                    "validate_output",
                    "create_backup",
                    "overwrite_existing",
                    "offline",
                    "allow_unverified_fonts",
                    "resources_offline",
                    "restricted",
                }
                numeric_fields = {
                    "timeout_seconds",
                    "default_toc_depth",
                    "body_size_pt",
                    "code_size_pt",
                    "input_bytes",
                    "archive_bytes",
                    "archive_entries",
                    "xml_bytes",
                    "preview_pages",
                }
                if setting in boolean_fields:
                    section_values[setting] = _parse_env_value(value)
                elif setting in numeric_fields:
                    try:
                        section_values[setting] = int(value)
                    except ValueError:
                        section_values[setting] = value
                elif setting == "margin_cm":
                    try:
                        section_values[setting] = float(value)
                    except ValueError:
                        section_values[setting] = value
                else:
                    section_values[setting] = value
        else:
            config_dict[config_key] = _parse_env_value(value)

    return config_dict


def _load_config_file(config_path: Path) -> Dict[str, Any]:
    """Load config data from TOML or YAML file."""
    suffix = config_path.suffix.lower()
    loaded: Any
    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(
            "config_path", f"Unable to read config file: {exc}"
        ) from exc

    if suffix == ".toml":
        try:
            loaded = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(
                "config_path", f"Invalid TOML configuration: {exc}"
            ) from exc
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigurationError(
                "config_path",
                "YAML config requires PyYAML. Install with `uv add pyyaml`.",
            ) from exc
        try:
            loaded = yaml.safe_load(content)
        except Exception as exc:
            raise ConfigurationError(
                "config_path", f"Invalid YAML configuration: {exc}"
            ) from exc
    else:
        raise ConfigurationError(
            "config_path",
            "Unsupported config format. Use .toml, .yaml, or .yml files.",
        )

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError("config_path", "Configuration root must be a mapping.")
    return loaded


def _merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge config dictionaries; values in override take precedence."""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_config(existing, value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Optional[Path] = None) -> MarkdownToDocxConfig:
    """Load configuration from file or environment.

    Args:
        config_path: Optional path to configuration file

    Returns:
        MarkdownToDocxConfig instance

    Raises:
        ConfigurationError: If configuration file is invalid
    """
    file_config: Dict[str, Any] = {}
    if config_path is not None:
        file_config = _load_config_file(config_path)

    env_config = _parse_env_config()
    merged = _merge_config(file_config, env_config)
    return MarkdownToDocxConfig.from_dict(merged)


# Global default configuration instance
DEFAULT_CONFIG = MarkdownToDocxConfig()
