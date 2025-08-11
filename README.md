# Markdown to DOCX Converter

[中文文档](README_zh.md) | English

A Python tool for converting Markdown files to modern DOCX format Word documents with support for the latest document standards and formatting.

## Key Features

- ✅ **Modern Markdown Syntax** - Support for strikethrough, superscript/subscript, task lists, and more
- ✅ **Latest DOCX Standards** - Compatible with Office 2019+ and latest versions
- ✅ **Template System** - Use custom DOCX templates for consistent styling
- ✅ **Advanced Tables** - Support for complex table layouts and alignment
- ✅ **Code Highlighting** - Multi-language syntax highlighting support
- ✅ **Footnotes & References** - Academic document features
- ✅ **Table of Contents** - Automatic TOC generation
- ✅ **Command Line Interface** - Easy-to-use CLI tool
- ✅ **Programmatic API** - Flexible programming interface

## Installation

Run the setup script to install dependencies and ensure Pandoc is available:

```bash
./scripts/setup-env.sh
```

**Note:** The setup script is designed for Unix-like systems (Linux, macOS). Windows users should install dependencies manually.

To include development dependencies (e.g., for running tests), pass additional `uv sync` options:

```bash
./scripts/setup-env.sh --group dev
```

Or install dependencies manually using uv:

```bash
uv sync
```

Ensure Pandoc 2.19+ is installed for optimal compatibility:

```bash
# macOS
brew install pandoc

# Ubuntu/Debian
sudo apt-get install pandoc

# Or download from: https://pandoc.org/installing.html
```

## Usage

### Command Line Usage

```bash
# Basic conversion
uv run python -m src.markdown2docx.cli input.md

# Specify output file
uv run python -m src.markdown2docx.cli input.md -o output.docx

# Use custom template
uv run python -m src.markdown2docx.cli input.md --template custom.docx

# Include table of contents
uv run python -m src.markdown2docx.cli input.md --toc --toc-depth 3

# Create modern DOCX template
uv run python -m src.markdown2docx.cli --create-template modern_template.docx
```

### Programmatic Usage

```python
from src.markdown2docx import MarkdownToDocxConverter
from src.markdown2docx.templates import DocxTemplateManager

# Basic conversion
converter = MarkdownToDocxConverter()
output_path = converter.convert("input.md", "output.docx")

# Template-based conversion
converter = MarkdownToDocxConverter(reference_doc="template.docx")
output_path = converter.convert("input.md", "output.docx")

# Conversion with options
output_path = converter.convert(
    "input.md",
    "output.docx",
    toc=True,
    toc_depth=3,
)

# Create modern template
template_path = DocxTemplateManager.create_modern_template("modern.docx")

# Template-based conversion
output_path = converter.convert_with_template(
    "input.md", 
    "modern.docx", 
    "output.docx"
)
```

## Supported Markdown Features

### Text Formatting
- **Bold**, *italic*, ~~strikethrough~~
- `Inline code`
- Superscript^2^, subscript~2~
- Block quotes

### Lists
- Unordered and ordered lists
- Nested lists
- Task lists `- [x] Completed task`

### Code Blocks
- Syntax highlighting
- Multiple programming language support

### Tables
- Basic tables
- Column alignment (left, center, right)
- Complex table layouts

### Advanced Features
- Footnotes and references
- Internal links
- Mathematical formulas (with proper Pandoc configuration)
- Definition lists

## Modern DOCX Standards Support

This tool ensures generated DOCX files comply with the latest standards:

- **Office 2019+ Compatibility** - Uses modern XML structure
- **Responsive Layout** - Adapts to different screen sizes
- **Modern Fonts** - Defaults to Calibri and other modern fonts
- **Standard Margins** - 1-inch standard margins
- **Consistent Styling** - Unified heading and paragraph styles
- **Table Styling** - Modern table formatting

## Development

Run tests:

```bash
uv run pytest
```

Run tests with coverage:

```bash
uv run pytest --cov=src
```

Test example conversion:

```bash
uv run python -m src.markdown2docx.cli example.md -o example_output.docx
```

## System Requirements

- Python 3.13+
- Pandoc 2.19+ (recommended)
- pypandoc >= 1.13
- python-docx >= 1.1.2
- lxml >= 5.0.0

## Troubleshooting

### Pandoc Version Issues
If you encounter conversion problems, check your Pandoc version:

```bash
pandoc --version
```

We recommend version 2.19+ for optimal modern DOCX support.

### Template Issues
If custom templates don't work, try using the built-in modern template:

```bash
uv run python -m src.markdown2docx.cli --create-template modern.docx
uv run python -m src.markdown2docx.cli input.md --template modern.docx
```

## License

MIT License