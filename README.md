# Markdown to DOCX Converter

A Python tool for converting Markdown files to DOCX format Word documents.

## Features

- Supports standard Markdown syntax
- Preserves document formatting and structure
- Command-line interface
- Programmable API

## Installation

Install dependencies using uv:

```bash
uv sync
```

## Usage

### Command Line

```bash
# Basic conversion
uv run python -m src.markdown2docx.cli input.md

# Specify output file
uv run python -m src.markdown2docx.cli input.md -o output.docx
```

### Programmatic Usage

```python
from src.markdown2docx import MarkdownToDocxConverter

converter = MarkdownToDocxConverter()
output_path = converter.convert("input.md", "output.docx")
```

## Development

Run tests:

```bash
uv run pytest
```

Run tests with coverage:

```bash
uv run pytest --cov=src
```

## Dependencies

- Python 3.13+
- pypandoc
- python-docx

## License

MIT License