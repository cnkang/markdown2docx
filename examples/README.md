# Examples Documentation

This directory contains Markdown example files for testing and demonstrating the converter's functionality.

本目录包含用于测试和演示转换器功能的Markdown示例文件。

## File List 文件列表

- `example.md` - Comprehensive multilingual example showcasing all converter features (完整的多语言示例，展示所有转换器功能)

## Usage 使用方法

### Basic Conversion 基础转换
```bash
# Convert with default settings (使用默认设置转换)
uv run python -m src.markdown2docx.cli examples/example.md

# Convert with custom output (指定输出文件)
uv run python -m src.markdown2docx.cli examples/example.md -o my_output.docx

# Convert with template (使用模板转换)
uv run python -m src.markdown2docx.cli examples/example.md --template modern_template.docx

# Convert with table of contents (包含目录)
uv run python -m src.markdown2docx.cli examples/example.md --toc --toc-depth 3
```

### Create Template First 首先创建模板
```bash
# Create a modern template (创建现代模板)
uv run python -m src.markdown2docx.cli --create-template modern_template.docx

# Then use it for conversion (然后用于转换)
uv run python -m src.markdown2docx.cli examples/example.md --template modern_template.docx
```

## Features Tested 测试的功能

The example file tests all converter capabilities:

示例文件测试所有转换器功能：

- **Text Formatting** - Bold, italic, strikethrough, superscript, subscript (文本格式)
- **Lists** - Ordered, unordered, nested, task lists (列表)
- **Code Blocks** - Syntax highlighting for multiple languages (代码块)
- **Tables** - Complex layouts with alignment (表格)
- **Multilingual Content** - International text, RTL languages (多语言内容)
- **Links & References** - External links, footnotes (链接和引用)
- **Special Characters** - Unicode symbols, mathematical notation (特殊字符)

## Expected Output 预期输出

The converted DOCX file should properly handle:

转换后的DOCX文件应该正确处理：

- ✅ Heading styles mapping (# → Heading 1, ## → Heading 2, etc.) (标题样式映射)
- ✅ Text formatting preservation (bold, italic, strikethrough) (文本格式保持)
- ✅ Table and list rendering (表格和列表渲染)
- ✅ Code syntax highlighting (代码语法高亮)
- ✅ Multilingual character support and RTL text (多语言字符支持和RTL文本)
- ✅ Modern DOCX standards compliance (现代DOCX标准兼容性)