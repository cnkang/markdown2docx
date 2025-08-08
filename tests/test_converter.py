"""Tests for markdown2docx converter.

Markdown到DOCX转换器的测试，确保核心转换功能正常工作。
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from markdown2docx.converter import MarkdownToDocxConverter
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


def test_convert_basic(converter, sample_markdown):
    """Test basic conversion functionality (测试基本转换功能)."""
    with TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "test.md"
        input_path.write_text(sample_markdown)
        
        output_path = converter.convert(input_path)
        
        assert output_path.exists()
        assert output_path.suffix == '.docx'


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
            **{'--toc': True, '--toc-depth': 2}
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
        
        output_path = converter.convert_with_template(
            input_path, template_path
        )
        
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