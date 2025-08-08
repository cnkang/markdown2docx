"""Command line interface for markdown2docx."""

import argparse
from pathlib import Path
from .converter import MarkdownToDocxConverter


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Convert Markdown to DOCX")
    parser.add_argument("input", help="Input markdown file")
    parser.add_argument("-o", "--output", help="Output DOCX file")
    
    args = parser.parse_args()
    
    converter = MarkdownToDocxConverter()
    output_path = converter.convert(args.input, args.output)
    print(f"Converted {args.input} to {output_path}")


if __name__ == "__main__":
    main()