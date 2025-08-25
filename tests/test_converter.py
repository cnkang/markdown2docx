"""Comprehensive tests for MarkdownToDocxConverter.

包含基本转换功能测试和扩展功能测试。
"""

import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from markdown2docx.config import MarkdownToDocxConfig
from markdown2docx.converter import MarkdownToDocxConverter
from markdown2docx.exceptions import (
    ConversionError,
    PandocError,
    PandocNotFoundError,
    ValidationError,
)
from markdown2docx.templates import DocxTemplateManager


@pytest.fixture
def sample_markdown():
    """Sample markdown content with modern features (包含现代功能的示例Markdown内容)."""
    return """# Test Document 测试文档

This is a **test** document with modern markdown features:
这是一个包含现代Markdown功能的**测试**文档：

## Text Formatting 文本格式

- **Bold text** (**粗体文本**)
- *Italic text* (*斜体文本*)
- ~~Strikethrough text~~ (~~删除线文本~~)
- `Inline code` (`行内代码`)
- H~2~O (subscript 下标)
- E=mc^2^ (superscript 上标)

## Code Blocks 代码块

```python
def hello_world():
    # Hello world function (你好世界函数)
    print("Hello, World!")
    return True
```

## Tables 表格

| Feature | Status | Notes |
|---------|--------|-------|
| Headers | ✅ | Working (正常工作) |
| Lists | ✅ | All types (所有类型) |
| Code | ✅ | Syntax highlighting (语法高亮) |

## Task Lists 任务列表

- [x] Completed task (已完成任务)
- [ ] Pending task (待完成任务)
- [ ] Another pending task (另一个待完成任务)

## Links and References 链接和引用

Visit [GitHub](https://github.com) for more information.
访问 [GitHub](https://github.com) 获取更多信息。

## Footnotes 脚注

This has a footnote[^1]. 这里有一个脚注[^1]。

[^1]: This is the footnote content. 这是脚注内容。
"""


@pytest.fixture
def converter():
    """Converter instance (转换器实例)."""
    return MarkdownToDocxConverter()


# ============================================================================
# Basic Conversion Tests
# ============================================================================

def test_convert_basic(converter, sample_markdown):
    """Test basic conversion functionality (测试基本转换功能)."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        input_path.write_text(sample_markdown)

        output_path = converter.convert(input_path)

        assert output_path.exists()
        assert output_path.suffix == ".docx"


def test_convert_with_custom_output(converter, sample_markdown):
    """Test conversion with custom output path (测试自定义输出路径的转换)."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        output_path = Path(tmpdir) / "custom.docx"
        input_path.write_text(sample_markdown)

        result = converter.convert(input_path, output_path)

        assert result == output_path
        assert output_path.exists()


def test_convert_with_options(converter, sample_markdown):
    """Test conversion with pandoc options (测试带Pandoc选项的转换)."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        input_path.write_text(sample_markdown)

        output_path = converter.convert(
            input_path,
            toc=True,
            toc_depth=2,
        )

        assert output_path.exists()


def test_convert_with_template(converter, sample_markdown):
    """Test conversion with template (测试使用模板的转换)."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        template_path = Path(tmpdir) / "template.docx"
        input_path.write_text(sample_markdown)

        # Create a template first (首先创建模板)
        DocxTemplateManager.create_modern_template(template_path)

        output_path = converter.convert_with_template(input_path, template_path)

        assert output_path.exists()


def test_convert_nonexistent_file(converter):
    """Test conversion with nonexistent input file (测试不存在输入文件的转换)."""
    with pytest.raises(FileNotFoundError):
        converter.convert("nonexistent.md")


def test_template_creation():
    """Test modern template creation (测试现代模板创建)."""
    with TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "modern_template.docx"

        result = DocxTemplateManager.create_modern_template(template_path)

        assert result == template_path
        assert template_path.exists()


def test_converter_with_reference_doc(sample_markdown):
    """Test converter initialization with reference document (测试使用参考文档初始化转换器)."""
    with TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "template.docx"
        DocxTemplateManager.create_modern_template(template_path)

        converter = MarkdownToDocxConverter(reference_doc=template_path)
        assert converter.reference_doc == template_path


def test_convert_with_template_method(converter, sample_markdown):
    """Test the convert_with_template method directly."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        template_path = Path(tmpdir) / "template.docx"
        output_path = Path(tmpdir) / "output.docx"

        input_path.write_text(sample_markdown)
        DocxTemplateManager.create_modern_template(template_path)

        # Test convert_with_template method
        result = converter.convert_with_template(
            input_path, template_path, output_path, toc=True
        )

        assert result == output_path
        assert output_path.exists()


# ============================================================================
# Converter Initialization Tests
# ============================================================================

class TestConverterInitialization:
    """Test converter initialization and validation."""

    def test_init_with_config(self):
        """Test converter initialization with custom config."""
        config = MarkdownToDocxConfig()
        converter = MarkdownToDocxConverter(config=config)
        assert converter.config is config

    def test_init_with_reference_doc(self):
        """Test converter initialization with reference document."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            ref_path = Path(tmp.name)
            try:
                converter = MarkdownToDocxConverter(reference_doc=ref_path)
                assert converter.reference_doc == ref_path
            finally:
                ref_path.unlink()

    def test_init_with_both_config_and_reference(self):
        """Test converter initialization with both config and reference doc."""
        config = MarkdownToDocxConfig()
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            ref_path = Path(tmp.name)
            try:
                converter = MarkdownToDocxConverter(reference_doc=ref_path, config=config)
                assert converter.config is config
                assert converter.reference_doc == ref_path
            finally:
                ref_path.unlink()


# ============================================================================
# Pandoc Validation Tests
# ============================================================================

class TestPandocValidation:
    """Test Pandoc installation validation."""

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    def test_validate_pandoc_success(self, mock_get_version):
        """Test successful Pandoc validation."""
        mock_get_version.return_value = "2.19.2"
        
        converter = MarkdownToDocxConverter()
        # Should not raise any exception
        converter._validate_pandoc()

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    def test_validate_pandoc_not_found(self, mock_get_version):
        """Test Pandoc not found error."""
        mock_get_version.side_effect = OSError("Pandoc not found")
        
        with pytest.raises(PandocNotFoundError):
            MarkdownToDocxConverter()

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    def test_validate_pandoc_other_error(self, mock_get_version):
        """Test other Pandoc validation errors."""
        mock_get_version.side_effect = RuntimeError("Unexpected error")
        
        with pytest.raises(PandocError) as exc_info:
            MarkdownToDocxConverter()
        
        assert "Failed to validate Pandoc installation" in str(exc_info.value)

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    @patch("markdown2docx.converter.VERSION_AVAILABLE", False)
    def test_validate_pandoc_no_packaging(self, mock_get_version):
        """Test Pandoc validation without packaging library."""
        mock_get_version.return_value = "2.19.2"
        
        converter = MarkdownToDocxConverter()
        # Should not raise exception, just log info
        converter._validate_pandoc()

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    def test_validate_pandoc_version_warning(self, mock_get_version):
        """Test Pandoc version warning for older versions."""
        mock_get_version.return_value = "2.18.0"  # Older than minimum
        
        converter = MarkdownToDocxConverter()
        with patch("markdown2docx.converter.logger") as mock_logger:
            converter._validate_pandoc()
            mock_logger.warning.assert_called_once()
            assert "recommend >=" in mock_logger.warning.call_args[0][0]


# ============================================================================
# Pandoc Arguments Tests
# ============================================================================

class TestPandocArgsGeneration:
    """Test Pandoc arguments generation."""

    def test_build_pandoc_args_basic(self):
        """Test basic Pandoc arguments building."""
        converter = MarkdownToDocxConverter()
        args = converter._build_pandoc_args(toc=False, toc_depth=3, extra_args=None)
        
        assert isinstance(args, list)
        assert all(isinstance(arg, str) for arg in args)

    def test_build_pandoc_args_with_toc(self):
        """Test Pandoc arguments with table of contents."""
        converter = MarkdownToDocxConverter()
        args = converter._build_pandoc_args(toc=True, toc_depth=3, extra_args=None)
        
        assert "--toc" in args

    def test_build_pandoc_args_with_toc_depth(self):
        """Test Pandoc arguments with TOC depth."""
        converter = MarkdownToDocxConverter()
        args = converter._build_pandoc_args(toc=True, toc_depth=4, extra_args=None)
        
        assert "--toc" in args
        # TOC depth is passed as separate arguments
        toc_depth_idx = args.index("--toc-depth")
        assert args[toc_depth_idx + 1] == "4"

    def test_build_pandoc_args_with_reference_doc(self):
        """Test Pandoc arguments with reference document."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            ref_path = Path(tmp.name)
            try:
                converter = MarkdownToDocxConverter(reference_doc=ref_path)
                args = converter._build_pandoc_args(toc=False, toc_depth=3, extra_args=None)
                
                # Reference doc is passed as separate arguments
                ref_doc_idx = args.index("--reference-doc")
                assert args[ref_doc_idx + 1] == str(ref_path)
            finally:
                ref_path.unlink()

    def test_build_pandoc_args_with_extra_args(self):
        """Test Pandoc arguments with extra arguments."""
        converter = MarkdownToDocxConverter()
        extra_args = ["--highlight-style=tango", "--number-sections"]
        args = converter._build_pandoc_args(toc=False, toc_depth=3, extra_args=extra_args)
        
        for extra_arg in extra_args:
            assert extra_arg in args


# ============================================================================
# DOCX Validation Tests
# ============================================================================

class TestDocxValidation:
    """Test DOCX file validation."""

    def test_validate_docx_success(self):
        """Test successful DOCX validation."""
        # Create a minimal valid DOCX file using python-docx
        try:
            from docx import Document
        except ImportError:
            pytest.skip("python-docx not available for creating test DOCX file")
        
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            output_path = Path(tmp.name)
            
            try:
                # Create a minimal valid DOCX document
                doc = Document()
                doc.add_paragraph("Test content")
                doc.save(str(output_path))
                
                converter = MarkdownToDocxConverter()
                # Should not raise any exception
                converter._validate_docx_output(output_path)
                
            finally:
                output_path.unlink()

    def test_validate_docx_missing_file(self):
        """Test DOCX validation with missing file."""
        nonexistent_path = Path("/nonexistent/file.docx")
        
        converter = MarkdownToDocxConverter()
        with pytest.raises(ValidationError) as exc_info:
            converter._validate_docx_output(nonexistent_path)
        
        assert "Output file was not created" in str(exc_info.value)

    def test_validate_docx_empty_file(self):
        """Test DOCX validation with empty file."""
        with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
            output_path = Path(tmp.name)
            # File is empty by default
            
            converter = MarkdownToDocxConverter()
            with pytest.raises(ValidationError) as exc_info:
                converter._validate_docx_output(output_path)
            
            assert "Output file is empty" in str(exc_info.value)


# ============================================================================
# Conversion Error Tests
# ============================================================================

class TestConversionErrors:
    """Test conversion error handling."""

    @patch("markdown2docx.converter.pypandoc.convert_file")
    def test_convert_pypandoc_error(self, mock_convert):
        """Test handling of pypandoc conversion errors."""
        mock_convert.side_effect = RuntimeError("Pandoc conversion failed")
        
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = Path(tmp.name)
            
            try:
                converter = MarkdownToDocxConverter()
                with pytest.raises(ConversionError) as exc_info:
                    converter.convert(input_path)
                
                assert "Pandoc conversion failed" in str(exc_info.value)
                assert str(input_path) in str(exc_info.value)
            finally:
                input_path.unlink()

    def test_convert_nonexistent_input(self):
        """Test conversion with nonexistent input file."""
        nonexistent_path = Path("/nonexistent/input.md")
        
        converter = MarkdownToDocxConverter()
        with pytest.raises(FileNotFoundError):
            converter.convert(nonexistent_path)

    @patch("markdown2docx.converter.pypandoc.convert_file")
    def test_convert_with_validation_failure(self, mock_convert):
        """Test conversion with validation failure."""
        # Mock successful conversion but create empty output file
        mock_convert.return_value = None
        
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = Path(tmp.name)
            
            try:
                converter = MarkdownToDocxConverter()
                with pytest.raises(ValidationError):
                    converter.convert(input_path, validate_output=True)
            finally:
                input_path.unlink()


# ============================================================================
# Template Conversion Tests
# ============================================================================

class TestConvertWithTemplate:
    """Test template-based conversion."""

    def test_convert_with_template_success(self):
        """Test successful template-based conversion."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as md_tmp:
            md_tmp.write("# Test Document\nThis is a test.")
            md_tmp.flush()
            input_path = Path(md_tmp.name)
            
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as docx_tmp:
                template_path = Path(docx_tmp.name)
                
                try:
                    converter = MarkdownToDocxConverter()
                    with patch("markdown2docx.converter.pypandoc.convert_file") as mock_convert:
                        mock_convert.return_value = None
                        
                        # Create the expected output file since mock won't do it
                        expected_output = input_path.with_suffix(".docx")
                        expected_output.write_text("mock docx content")
                        
                        result = converter.convert_with_template(
                            input_path, 
                            template_path,
                            validate_output=False
                        )
                        
                        assert result.exists()
                        mock_convert.assert_called_once()
                        
                        # Clean up
                        expected_output.unlink()
                finally:
                    input_path.unlink()
                    template_path.unlink()
                    if result and result.exists():
                        result.unlink()

    def test_convert_with_template_nonexistent_template(self):
        """Test template conversion with nonexistent template."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = Path(tmp.name)
            
            nonexistent_template = Path("/nonexistent/template.docx")
            
            try:
                converter = MarkdownToDocxConverter()
                with pytest.raises(FileNotFoundError):
                    converter.convert_with_template(input_path, nonexistent_template)
            finally:
                input_path.unlink()


# ============================================================================
# Integration Tests
# ============================================================================

class TestConverterIntegration:
    """Test converter integration scenarios."""

    def test_converter_with_all_options(self):
        """Test converter with all available options."""
        config = MarkdownToDocxConfig()
        
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as md_tmp:
            md_tmp.write("# Test Document\n\n## Section 1\nContent here.\n\n## Section 2\nMore content.")
            md_tmp.flush()
            input_path = Path(md_tmp.name)
            
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as ref_tmp:
                ref_path = Path(ref_tmp.name)
                
                try:
                    converter = MarkdownToDocxConverter(reference_doc=ref_path, config=config)
                    
                    with patch("markdown2docx.converter.pypandoc.convert_file") as mock_convert:
                        mock_convert.return_value = None
                        
                        # Create the expected output file since mock won't do it
                        expected_output = input_path.with_suffix(".docx")
                        expected_output.write_text("mock docx content")
                        
                        result = converter.convert(
                            input_path,
                            toc=True,
                            toc_depth=2,
                            extra_args=["--number-sections"],
                            validate_output=False
                        )
                        
                        assert result.exists()
                        
                        # Clean up
                        expected_output.unlink()
                        
                        # Verify pandoc was called with correct arguments
                        mock_convert.assert_called_once()
                        call_args = mock_convert.call_args
                        
                        # Check that TOC and reference doc arguments were included
                        pandoc_args = call_args[1]["extra_args"]
                        assert "--toc" in pandoc_args
                        assert "--toc-depth" in pandoc_args and "2" in pandoc_args
                        assert "--reference-doc" in pandoc_args and str(ref_path) in pandoc_args
                        assert "--number-sections" in pandoc_args
                        
                finally:
                    input_path.unlink()
                    ref_path.unlink()
                    if result and result.exists():
                        result.unlink()

    @patch("markdown2docx.converter.pypandoc.get_pandoc_version")
    def test_converter_initialization_with_validation(self, mock_get_version):
        """Test converter initialization triggers Pandoc validation."""
        mock_get_version.return_value = "2.19.2"
        
        # Creating converter should trigger validation
        converter = MarkdownToDocxConverter()
        mock_get_version.assert_called_once()

    def test_output_path_generation(self):
        """Test automatic output path generation."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as tmp:
            tmp.write("# Test\nContent")
            tmp.flush()
            input_path = Path(tmp.name)
            
            try:
                converter = MarkdownToDocxConverter()
                
                with patch("markdown2docx.converter.pypandoc.convert_file") as mock_convert:
                    mock_convert.return_value = None
                    
                    result = converter.convert(input_path, validate_output=False)
                    
                    # Output should be same name with .docx extension
                    expected_output = input_path.with_suffix(".docx")
                    assert result == expected_output
                    
            finally:
                input_path.unlink()
                expected_output = input_path.with_suffix(".docx")
                if expected_output.exists():
                    expected_output.unlink()