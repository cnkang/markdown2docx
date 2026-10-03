"""Command line interface for markdown2docx.

This module provides a comprehensive CLI for converting Markdown files to DOCX
format with support for templates, configuration, and various output options.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Never, Optional

from .config import MarkdownToDocxConfig, TemplateConfig, load_config
from .converter import MarkdownToDocxConverter
from .exceptions import MarkdownToDocxError
from .messages import HELP_ZH, message
from .report import doctor
from .templates import DocxTemplateManager

# Configure CLI logger
logger = logging.getLogger(__name__)


class AgentArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        if "--json" in sys.argv:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": {"code": "INVALID_ARGUMENT", "message": message},
                    }
                )
            )
            raise SystemExit(2)
        super().error(message)


def create_argument_parser(ui_lang: str = "en") -> argparse.ArgumentParser:
    """Create and configure the command line argument parser.

    Returns:
        Configured ArgumentParser instance
    """
    parser = AgentArgumentParser(
        prog="markdown2docx",
        description=message(ui_lang, "description"),
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
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")
    parser.add_argument(
        "--lang", help="Document BCP 47 language; local lang spans may override it"
    )
    parser.add_argument(
        "--direction",
        choices=["auto", "ltr", "rtl"],
        help="Document base direction (default: auto)",
    )
    parser.add_argument(
        "--ui-lang",
        choices=["en", "zh"],
        default="en",
        help="CLI language, independent of document language",
    )
    parser.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Disable font downloads",
    )
    parser.add_argument(
        "--allow-unverified-fonts",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Explicitly allow installed fonts without a verified license record",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit only structured JSON on stdout"
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Inspect dependencies without converting a document",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Render an optional PDF/page preview with LibreOffice",
    )
    parser.add_argument(
        "--preview-dir", type=Path, help="Directory for optional rendered previews"
    )
    if ui_lang == "zh":
        parser.epilog = "示例：markdown2docx input.md --json --lang zh-Hans\n诊断：markdown2docx --doctor --json\n配置：MD2DOCX_ 前缀的环境变量或 YAML/TOML 文件。"
        for action in parser._actions:
            if action.help in HELP_ZH:
                action.help = HELP_ZH[action.help]

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


def handle_template_creation(
    template_path: str, verbose: bool = False, *, config: TemplateConfig | None = None
) -> int:
    """Handle template creation command.

    Args:
        template_path: Path where template should be created
        verbose: Whether to show verbose output
        config: Loaded template layout and fonts

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        output_path = DocxTemplateManager.create_modern_template(
            template_path, config=config, add_sample=True
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


def error_code(error: Exception) -> str:
    from .exceptions import (
        ConfigurationError,
        PandocNotFoundError,
        TemplateError,
        ValidationError,
    )

    if hasattr(error, "code"):
        return str(error.code)
    for kind, code in (
        (ConfigurationError, "INVALID_ARGUMENT"),
        (TemplateError, "TEMPLATE_INVALID"),
        (ValidationError, "VALIDATION_FAILED"),
        (PandocNotFoundError, "PANDOC_UNAVAILABLE"),
        (FileNotFoundError, "INPUT_NOT_FOUND"),
    ):
        if isinstance(error, kind):
            return code
    return "CONVERSION_FAILED"


def emit_error(error: Exception) -> None:
    print(
        json.dumps(
            {
                "status": "error",
                "error": {"code": error_code(error), "message": str(error)},
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    ui_lang = "en"
    for index, value in enumerate(sys.argv[1:], 1):
        if value == "--ui-lang" and index + 1 < len(sys.argv):
            ui_lang = sys.argv[index + 1]
        elif value.startswith("--ui-lang="):
            ui_lang = value.split("=", 1)[1]
    parser = create_argument_parser(ui_lang)
    args = parser.parse_args()

    # Setup logging first
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    # Load configuration
    try:
        config = load_config(args.config if hasattr(args, "config") else None)
    except Exception as e:
        if getattr(args, "json", False) is True:
            emit_error(e)
            sys.exit(1)
        logger.error("Failed to load configuration: %s", e)
        sys.exit(1)

    if getattr(args, "doctor", False) is True:
        result = doctor()
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if args.json
            else message(args.ui_lang, "doctor")
            + "\n"
            + json.dumps(result, ensure_ascii=False, indent=2)
        )
        return

    # Handle template creation
    if args.create_template and (
        getattr(args, "json", False) is True or ui_lang == "zh"
    ):
        try:
            path = DocxTemplateManager.create_modern_template(
                args.create_template, config=config.template, add_sample=False
            )
            print(
                json.dumps(
                    {"status": "success", "output_path": str(path)}, ensure_ascii=False
                )
                if args.json
                else message(ui_lang, "success", path=path)
            )
        except Exception as exc:
            if args.json:
                emit_error(exc)
            else:
                print(
                    message(ui_lang, "failure", code=error_code(exc), message=str(exc)),
                    file=sys.stderr,
                )
            sys.exit(1)
        return
    if args.create_template:
        exit_code = handle_template_creation(
            args.create_template, args.verbose, config=config.template
        )
        if exit_code != 0:
            sys.exit(exit_code)
        return

    # Validate input file requirement
    if not args.input:
        parser.error("Input Markdown file is required (unless using --create-template)")

    enhanced = (
        any(getattr(args, flag, False) is True for flag in ("json", "render"))
        or any(
            isinstance(getattr(args, flag, None), (str, bool, Path))
            for flag in (
                "lang",
                "direction",
                "offline",
                "allow_unverified_fonts",
                "preview_dir",
            )
        )
        or ui_lang == "zh"
    )
    if enhanced:
        try:
            converter = MarkdownToDocxConverter(
                reference_doc=args.template, config=config
            )
            report = converter.convert_with_report(
                args.input,
                args.output,
                toc=args.toc,
                toc_depth=args.toc_depth,
                validate_output=args.validate,
                lang=args.lang,
                direction=args.direction,
                offline=args.offline,
                allow_unverified_fonts=args.allow_unverified_fonts,
                render=args.render,
                preview_dir=args.preview_dir,
            )
            if args.json:
                print(json.dumps(report.to_dict(), ensure_ascii=False))
            elif not args.quiet:
                print(message(args.ui_lang, "success", path=report.output_path))
                if args.render:
                    print(
                        message(
                            args.ui_lang,
                            "preview",
                            status=report.preview.get("status", "unverified"),
                            reason=report.preview.get("reason", ""),
                        )
                    )
                for warning in report.warnings:
                    print(message(args.ui_lang, "warning", **warning), file=sys.stderr)
        except Exception as exc:
            if args.json:
                emit_error(exc)
            else:
                print(
                    message(ui_lang, "failure", code=error_code(exc), message=str(exc)),
                    file=sys.stderr,
                )
            sys.exit(1)
        return

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
