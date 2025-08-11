"""Command line interface for markdown2docx."""

import argparse
from pathlib import Path
from .converter import MarkdownToDocxConverter
from .templates import DocxTemplateManager


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Markdown to modern DOCX format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.md                          # Basic conversion
  %(prog)s input.md -o output.docx           # Specify output file
  %(prog)s input.md --template custom.docx   # Use custom template
  %(prog)s --create-template modern.docx     # Create modern template
        """
    )
    
    parser.add_argument("input", nargs='?', help="Input markdown file")
    parser.add_argument("-o", "--output", help="Output DOCX file")
    parser.add_argument("--template", "--reference-doc", 
                       help="Reference DOCX template for styling")
    parser.add_argument("--create-template", metavar="FILE",
                       help="Create a modern DOCX template")
    parser.add_argument("--toc", action="store_true",
                       help="Include table of contents")
    parser.add_argument("--toc-depth", type=int, default=3,
                       help="Table of contents depth (default: 3)")
    
    args = parser.parse_args()
    
    # Handle template creation
    if args.create_template:
        template_path = DocxTemplateManager.create_modern_template(args.create_template)
        print(f"Created modern DOCX template: {template_path}")
        return
    
    # Validate input file
    if not args.input:
        parser.error("Input markdown file is required (unless using --create-template)")
    
    # Initialize converter with template if provided
    converter = MarkdownToDocxConverter(reference_doc=args.template)
    
    # Prepare conversion options
    options = {}
    if args.toc:
        options['toc'] = True
        options['toc_depth'] = args.toc_depth
    
    try:
        output_path = converter.convert(args.input, args.output, **options)
        print(f"✅ Successfully converted {args.input} to {output_path}")
        
        if args.template:
            print(f"📄 Used template: {args.template}")
            
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()