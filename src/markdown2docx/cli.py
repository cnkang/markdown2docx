"""Command line interface for markdown2docx.

This module provides a comprehensive CLI for converting Markdown files to DOCX
format with support for templates, configuration, and various output options.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import MarkdownToDocxConfig, load_config
from .converter import MarkdownToDocxConverter
from .exceptions import MarkdownToDocxError
from .templates import DocxTemplateManager

# Configure CLI logger
logger = logging.getLogger(__name__)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the command line argument parser.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        prog="markdown2docx",
        description="Convert Markdown files to modern DOCX format with advanced features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.md                           # Basic conversion
  %(prog)s document.md -o report.docx            # Specify output file
  %(prog)s document.md --template style.docx     # Use custom template
  %(prog)s document.md --toc --toc-depth 2       # Include table of contents
  %(prog)s --create-template modern.docx         # Create modern template
  %(prog)s document.md --validate                # Validate output file
  %(prog)s document.md --verbose                 # Enable verbose logging

Configuration:
  Set environment variables with MD2DOCX_ prefix to configure defaults:
    MD2DOCX_CONVERSION__DEFAULT_TOC=true
    MD2DOCX_TEMPLATE__BODY_FONT=Arial
    MD2DOCX_LOGGING__LEVEL=DEBUG
        """,
    )

    # Input/output arguments
    parser.add_argument("input", nargs="?", help="Input Markdown file path")
    parser.add_argument(
        "-o",
        "--output",
        help="Output DOCX file path (default: input file with .docx extension)",
    )

    # Template arguments
    parser.add_argument(
        "--template", "--reference-doc", help="Reference DOCX template file for styling"
    )
    parser.add_argument(
        "--create-template",
        metavar="FILE",
        help="Create a modern DOCX template and exit",
    )

    # Table of contents arguments
    parser.add_argument(
        "--toc",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include table of contents in output (use --no-toc to disable)",
    )
    parser.add_argument(
        "--toc-depth",
        type=int,
        metavar="N",
        help="Table of contents depth (1-6, default from config)",
    )

    # Validation and quality
    parser.add_argument(
        "--validate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Validate output DOCX file after conversion (use --no-validate to skip)",
    )

    # Logging and verbosity
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging output"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress all output except errors"
    )

    # Configuration
    parser.add_argument(
        "--config", type=Path, help="Path to configuration file (YAML/TOML)"
    )

    # Version information
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    return parser


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging based on verbosity settings.

    Args:
        verbose: Enable verbose (DEBUG) logging
        quiet: Enable quiet mode (ERROR only)
    """
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level, format="%(levelname)s: %(message)s", stream=sys.stderr
    )


def handle_template_creation(template_path: str, verbose: bool = False) -> int:
    """Handle template creation command.

    Args:
        template_path: Path where template should be created
        verbose: Whether to show verbose output

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        output_path = DocxTemplateManager.create_modern_template(
            template_path, add_sample=True
        )

        if not verbose:
            print(f"✅ Created modern DOCX template: {output_path}")
        else:
            print("✅ Successfully created modern DOCX template")
            print(f"   📁 Location: {output_path}")
            print("   📄 Template includes sample content for preview")
            print("   🎨 Configured with modern Office 2019+ compatibility")

        return 0

    except MarkdownToDocxError as e:
        logger.error("Template creation failed: %s", e)
        if verbose and e.details:
            logger.error("Details: %s", e.details)
        return 1
    except Exception as e:
        logger.error("Unexpected error during template creation: %s", e)
        return 1


def handle_conversion(
    input_path: str,
    output_path: Optional[str],
    template_path: Optional[str],
    toc: Optional[bool],
    toc_depth: Optional[int],
    validate: Optional[bool],
    config: MarkdownToDocxConfig,
    verbose: bool = False,
) -> int:
    """Handle Markdown to DOCX conversion.

    Args:
        input_path: Path to input Markdown file
        output_path: Optional output path
        template_path: Optional template file path
        toc: Whether to include table of contents
        toc_depth: Table of contents depth
        validate: Whether to validate output
        config: Configuration object
        verbose: Whether to show verbose output

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Initialize converter
        converter = MarkdownToDocxConverter(reference_doc=template_path, config=config)

        # Perform conversion
        result_path = converter.convert(
            input_path,
            output_path,
            toc=toc,
            toc_depth=toc_depth,
            validate_output=validate,
        )

        # Success output
        if not verbose:
            print(f"✅ Successfully converted {input_path} to {result_path}")
        else:
            print("✅ Conversion completed successfully")
            print(f"   📄 Input: {input_path}")
            print(f"   📁 Output: {result_path}")
            if template_path:
                print(f"   🎨 Template: {template_path}")
            effective_toc = toc if toc is not None else config.conversion.default_toc
            if effective_toc:
                depth = toc_depth or config.conversion.default_toc_depth
                print(f"   📑 Table of contents: {depth} levels")

            # Show Pandoc version info
            try:
                pandoc_version = converter.get_pandoc_version()
                print(f"   🔧 Pandoc version: {pandoc_version}")
            except MarkdownToDocxError:
                logger.debug("Pandoc version unavailable for verbose output")

        return 0

    except MarkdownToDocxError as e:
        logger.error("Conversion failed: %s", e)
        if verbose and e.details:
            logger.error("Details: %s", e.details)
        return 1
    except Exception as e:
        logger.error("Unexpected error during conversion: %s", e)
        return 1


def main() -> None:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = create_argument_parser()
    args = parser.parse_args()

    # Setup logging first
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    # Load configuration
    try:
        config = load_config(args.config if hasattr(args, "config") else None)
    except Exception as e:
        logger.error("Failed to load configuration: %s", e)
        sys.exit(1)

    # Handle template creation
    if args.create_template:
        exit_code = handle_template_creation(args.create_template, args.verbose)
        if exit_code != 0:
            sys.exit(exit_code)
        return

    # Validate input file requirement
    if not args.input:
        parser.error("Input Markdown file is required (unless using --create-template)")

    # Handle conversion
    exit_code = handle_conversion(
        input_path=args.input,
        output_path=args.output,
        template_path=args.template,
        toc=args.toc,
        toc_depth=args.toc_depth,
        validate=args.validate,
        config=config,
        verbose=args.verbose,
    )

    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
