# Markdown to DOCX Converter

中文文档 | [English](README.md)

一个将Markdown文件转换为现代DOCX格式Word文档的Python工具，支持最新的文档标准和格式。

## 主要特性

- ✅ **现代Markdown语法** - 支持删除线、上下标、任务列表等
- ✅ **最新DOCX标准** - 兼容Office 2019+和最新版本
- ✅ **模板系统** - 使用自定义DOCX模板保持一致样式
- ✅ **高级表格** - 支持复杂表格布局和对齐
- ✅ **代码高亮** - 多语言语法高亮支持
- ✅ **脚注和引用** - 学术文档功能
- ✅ **目录生成** - 自动生成文档目录
- ✅ **命令行界面** - 简单易用的CLI工具
- ✅ **编程API** - 灵活的程序化接口

## 安装

使用uv安装依赖：

```bash
uv sync
```

确保系统已安装Pandoc 2.19+以获得最佳兼容性：

```bash
# macOS
brew install pandoc

# Ubuntu/Debian
sudo apt-get install pandoc

# 或从官网下载: https://pandoc.org/installing.html
```

## 使用方法

### 命令行使用

```bash
# 基础转换
uv run python -m src.markdown2docx.cli input.md

# 指定输出文件
uv run python -m src.markdown2docx.cli input.md -o output.docx

# 使用自定义模板
uv run python -m src.markdown2docx.cli input.md --template custom.docx

# 包含目录
uv run python -m src.markdown2docx.cli input.md --toc --toc-depth 3

# 创建现代DOCX模板
uv run python -m src.markdown2docx.cli --create-template modern_template.docx
```

### 编程使用

```python
from src.markdown2docx import MarkdownToDocxConverter
from src.markdown2docx.templates import DocxTemplateManager

# 基础转换
converter = MarkdownToDocxConverter()
output_path = converter.convert("input.md", "output.docx")

# 使用模板转换
converter = MarkdownToDocxConverter(reference_doc="template.docx")
output_path = converter.convert("input.md", "output.docx")

# 带选项的转换
output_path = converter.convert(
    "input.md", 
    "output.docx",
    **{"--toc": True, "--toc-depth": 3}
)

# 创建现代模板
template_path = DocxTemplateManager.create_modern_template("modern.docx")

# 使用模板转换
output_path = converter.convert_with_template(
    "input.md", 
    "modern.docx", 
    "output.docx"
)
```

## 支持的Markdown功能

### 文本格式
- **粗体**、*斜体*、~~删除线~~
- `行内代码`
- 上标^2^、下标~2~
- 引用块

### 列表
- 无序列表和有序列表
- 嵌套列表
- 任务列表 `- [x] 完成的任务`

### 代码块
- 语法高亮
- 多种编程语言支持

### 表格
- 基础表格
- 列对齐（左对齐、居中、右对齐）
- 复杂表格布局

### 高级功能
- 脚注和引用
- 内部链接
- 数学公式（需要适当的Pandoc配置）
- 定义列表

## 最新DOCX标准支持

本工具确保生成的DOCX文件符合最新标准：

- **Office 2019+兼容性** - 使用现代XML结构
- **响应式布局** - 适配不同屏幕尺寸
- **现代字体** - 默认使用Calibri等现代字体
- **标准边距** - 1英寸标准边距
- **一致样式** - 统一的标题和段落样式
- **表格样式** - 现代表格格式

## 开发

运行测试：

```bash
uv run pytest
```

运行测试并查看覆盖率：

```bash
uv run pytest --cov=src
```

测试示例转换：

```bash
uv run python -m src.markdown2docx.cli examples/example.md -o example_output.docx
```

## 系统要求

- Python 3.13+
- Pandoc 2.19+（推荐）
- pypandoc >= 1.13
- python-docx >= 1.1.2
- lxml >= 5.0.0

## 故障排除

### Pandoc版本问题
如果遇到转换问题，请检查Pandoc版本：

```bash
pandoc --version
```

建议使用2.19+版本以获得最佳的现代DOCX支持。

### 模板问题
如果自定义模板不工作，请尝试使用内置的现代模板：

```bash
uv run python -m src.markdown2docx.cli --create-template modern.docx
uv run python -m src.markdown2docx.cli input.md --template modern.docx
```

## 许可证

MIT License