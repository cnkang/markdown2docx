"""Extended tests for configuration management."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from markdown2docx.config import (
    ConversionConfig,
    LoggingConfig,
    MarkdownToDocxConfig,
    PandocConfig,
    TemplateConfig,
    _parse_env_value,
    load_config,
)
from markdown2docx.exceptions import ConfigurationError


class TestEnvironmentVariableParsing:
    """Test environment variable parsing functionality."""

    def test_parse_env_value_boolean_true(self):
        """Test parsing boolean true values."""
        true_values = ["true", "True", "TRUE", "yes", "Yes", "YES", "1", "on", "On", "ON"]
        for value in true_values:
            assert _parse_env_value(value) is True

    def test_parse_env_value_boolean_false(self):
        """Test parsing boolean false values."""
        false_values = ["false", "False", "FALSE", "no", "No", "NO", "0", "off", "Off", "OFF"]
        for value in false_values:
            assert _parse_env_value(value) is False

    def test_parse_env_value_integer(self):
        """Test parsing integer values."""
        assert _parse_env_value("42") == 42
        assert _parse_env_value("-10") == -10
        assert _parse_env_value("0") == 0

    def test_parse_env_value_float(self):
        """Test parsing float values."""
        assert _parse_env_value("3.14") == 3.14
        assert _parse_env_value("-2.5") == -2.5
        assert _parse_env_value("0.0") == 0.0

    def test_parse_env_value_string(self):
        """Test parsing string values."""
        assert _parse_env_value("hello") == "hello"
        assert _parse_env_value("path/to/file") == "path/to/file"
        assert _parse_env_value("") == ""


class TestMarkdownToDocxConfigFromEnv:
    """Test configuration creation from environment variables."""

    def test_from_env_empty(self):
        """Test creating config from empty environment."""
        with patch.dict(os.environ, {}, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert isinstance(config, MarkdownToDocxConfig)
            assert isinstance(config.pandoc, PandocConfig)
            assert isinstance(config.template, TemplateConfig)
            assert isinstance(config.conversion, ConversionConfig)
            assert isinstance(config.logging, LoggingConfig)

    def test_from_env_pandoc_settings(self):
        """Test parsing Pandoc-related environment variables."""
        env_vars = {
            "MD2DOCX_PANDOC__MIN_VERSION": "2.19.0",
            "MD2DOCX_PANDOC__TIMEOUT_SECONDS": "300",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert config.pandoc.min_version == "2.19.0"
            assert config.pandoc.timeout_seconds == 300

    def test_from_env_template_settings(self):
        """Test parsing template-related environment variables."""
        env_vars = {
            "MD2DOCX_TEMPLATE__BODY_FONT": "Arial",
            "MD2DOCX_TEMPLATE__BODY_SIZE_PT": "12",
            "MD2DOCX_TEMPLATE__MARGIN_CM": "3.0",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert config.template.body_font == "Arial"
            assert config.template.body_size_pt == 12
            assert config.template.margin_cm == 3.0

    def test_from_env_conversion_settings(self):
        """Test parsing conversion-related environment variables."""
        env_vars = {
            "MD2DOCX_CONVERSION__DEFAULT_TOC_DEPTH": "4",
            "MD2DOCX_CONVERSION__VALIDATE_OUTPUT": "false",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert config.conversion.default_toc_depth == 4
            assert config.conversion.validate_output is False

    def test_from_env_logging_settings(self):
        """Test parsing logging-related environment variables."""
        env_vars = {
            "MD2DOCX_LOGGING__LEVEL": "DEBUG",
            "MD2DOCX_LOGGING__FORMAT": "%(levelname)s: %(message)s",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert config.logging.level == "DEBUG"
            assert config.logging.format == "%(levelname)s: %(message)s"

    def test_from_env_mixed_settings(self):
        """Test parsing mixed environment variables."""
        env_vars = {
            "MD2DOCX_PANDOC__TIMEOUT_SECONDS": "600",
            "MD2DOCX_TEMPLATE__BODY_FONT": "Times",
            "MD2DOCX_CONVERSION__DEFAULT_TOC_DEPTH": "2",
            "MD2DOCX_LOGGING__LEVEL": "WARNING",
            "OTHER_VAR": "should_be_ignored",
            "MD2DOCX_INVALID": "top_level_var",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            assert config.pandoc.timeout_seconds == 600
            assert config.template.body_font == "Times"
            assert config.conversion.default_toc_depth == 2
            assert config.logging.level == "WARNING"


class TestMarkdownToDocxConfigFromDict:
    """Test configuration creation from dictionary."""

    def test_from_dict_empty(self):
        """Test creating config from empty dictionary."""
        config = MarkdownToDocxConfig.from_dict({})
        assert isinstance(config, MarkdownToDocxConfig)

    def test_from_dict_partial(self):
        """Test creating config from partial dictionary."""
        config_dict = {
            "pandoc": {"min_version": "2.20.0"},
            "template": {"body_font": "Arial"},
        }
        config = MarkdownToDocxConfig.from_dict(config_dict)
        assert config.pandoc.min_version == "2.20.0"
        assert config.template.body_font == "Arial"

    def test_from_dict_complete(self):
        """Test creating config from complete dictionary."""
        config_dict = {
            "pandoc": {
                "min_version": "2.19.0",
                "timeout_seconds": 120,
            },
            "template": {
                "body_font": "Arial",
                "body_size_pt": 12,
            },
            "conversion": {
                "default_toc_depth": 5,
                "validate_output": True,
            },
            "logging": {
                "level": "ERROR",
                "format": "%(message)s",
            },
        }
        
        config = MarkdownToDocxConfig.from_dict(config_dict)
        
        # Pandoc config
        assert config.pandoc.min_version == "2.19.0"
        assert config.pandoc.timeout_seconds == 120
        
        # Template config
        assert config.template.body_font == "Arial"
        assert config.template.body_size_pt == 12
        
        # Conversion config
        assert config.conversion.default_toc_depth == 5
        assert config.conversion.validate_output is True
        
        # Logging config
        assert config.logging.level == "ERROR"
        assert config.logging.format == "%(message)s"

    def test_from_dict_invalid_format(self):
        """Test error handling for invalid dictionary format."""
        # This should cause a TypeError when trying to create dataclass
        invalid_dict = {
            "pandoc": "not_a_dict",  # Should be a dict
        }
        
        with pytest.raises(ConfigurationError) as exc_info:
            MarkdownToDocxConfig.from_dict(invalid_dict)
        
        assert "Invalid configuration format" in str(exc_info.value)


class TestGetPandocArgs:
    """Test Pandoc arguments generation."""

    def test_get_pandoc_args_basic(self):
        """Test basic Pandoc arguments generation."""
        config = MarkdownToDocxConfig()
        args = config.get_pandoc_args()
        
        assert isinstance(args, list)
        assert all(isinstance(arg, str) for arg in args)

    def test_get_pandoc_args_with_toc(self):
        """Test Pandoc arguments with table of contents."""
        config = MarkdownToDocxConfig()
        args = config.get_pandoc_args(toc=True)
        
        assert "--toc" in args

    def test_get_pandoc_args_with_toc_depth(self):
        """Test Pandoc arguments with custom TOC depth."""
        config = MarkdownToDocxConfig()
        args = config.get_pandoc_args(toc=True, toc_depth=5)
        
        assert "--toc" in args
        # TOC depth is passed as separate arguments
        toc_depth_idx = args.index("--toc-depth")
        assert args[toc_depth_idx + 1] == "5"

    def test_get_pandoc_args_no_toc_with_depth(self):
        """Test that TOC depth is ignored when TOC is disabled."""
        config = MarkdownToDocxConfig()
        args = config.get_pandoc_args(toc=False, toc_depth=5)
        
        assert "--toc" not in args
        assert "--toc-depth=5" not in args


class TestLoadConfig:
    """Test configuration loading function."""

    def test_load_config_no_file(self):
        """Test loading config without file (from environment)."""
        with patch.dict(os.environ, {"MD2DOCX_PANDOC__TIMEOUT_SECONDS": "180"}, clear=True):
            config = load_config()
            assert config.pandoc.timeout_seconds == 180

    def test_load_config_nonexistent_file(self):
        """Test loading config with nonexistent file path."""
        nonexistent_path = Path("/nonexistent/config.yaml")
        config = load_config(nonexistent_path)
        assert isinstance(config, MarkdownToDocxConfig)

    def test_load_config_existing_file(self):
        """Test loading config with existing file (currently falls back to env)."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            tmp.write(b"# Placeholder config file\n")
            tmp.flush()
            
            config_path = Path(tmp.name)
            
            try:
                with patch.dict(os.environ, {"MD2DOCX_LOGGING__LEVEL": "DEBUG"}, clear=True):
                    config = load_config(config_path)
                    assert config.logging.level == "DEBUG"
            finally:
                config_path.unlink()


class TestConfigurationIntegration:
    """Test configuration integration scenarios."""

    def test_config_with_all_env_vars(self):
        """Test configuration with comprehensive environment variables."""
        env_vars = {
            "MD2DOCX_PANDOC__MIN_VERSION": "2.19.2",
            "MD2DOCX_PANDOC__TIMEOUT_SECONDS": "900",
            "MD2DOCX_TEMPLATE__BODY_FONT": "Times New Roman",
            "MD2DOCX_TEMPLATE__BODY_SIZE_PT": "12",
            "MD2DOCX_TEMPLATE__MARGIN_CM": "2.0",
            "MD2DOCX_CONVERSION__DEFAULT_TOC_DEPTH": "6",
            "MD2DOCX_CONVERSION__VALIDATE_OUTPUT": "true",
            "MD2DOCX_LOGGING__LEVEL": "INFO",
            "MD2DOCX_LOGGING__FORMAT": "[%(asctime)s] %(levelname)s: %(message)s",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            
            # Verify all settings are applied correctly
            assert config.pandoc.min_version == "2.19.2"
            assert config.pandoc.timeout_seconds == 900
            
            assert config.template.body_font == "Times New Roman"
            assert config.template.body_size_pt == 12
            assert config.template.margin_cm == 2.0
            
            assert config.conversion.default_toc_depth == 6
            assert config.conversion.validate_output is True
            
            assert config.logging.level == "INFO"
            assert config.logging.format == "[%(asctime)s] %(levelname)s: %(message)s"

    def test_config_precedence_env_over_defaults(self):
        """Test that environment variables override default values."""
        env_vars = {
            "MD2DOCX_PANDOC__TIMEOUT_SECONDS": "1200",  # Override default
            "MD2DOCX_CONVERSION__DEFAULT_TOC_DEPTH": "1",  # Override default
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = MarkdownToDocxConfig.from_env()
            
            # These should be overridden
            assert config.pandoc.timeout_seconds == 1200
            assert config.conversion.default_toc_depth == 1
            
            # These should remain defaults
            assert config.pandoc.min_version == "2.19"  # Default
            assert config.template.body_font == "Calibri"  # Default