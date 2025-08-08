"""Markdown to DOCX converter implementation."""

import pypandoc
from pathlib import Path
from typing import Optional, Dict, Any
import tempfile
import os


class MarkdownToDocxConverter:
    """Convert Markdown files to DOCX format using pypandoc with modern DOCX standards."""
    
    def __init__(self, reference_doc: Optional[str | Path] = None):
        """Initialize converter with optional reference document.
        
        Args:
            reference_doc: Path to reference DOCX file for styling
        """
        self.reference_doc = Path(reference_doc) if reference_doc else None
        self._ensure_pandoc_version()
    
    def _ensure_pandoc_version(self) -> None:
        """Ensure pandoc version supports modern DOCX features."""
        try:
            version = pypandoc.get_pandoc_version()
            if version < (2, 19):  # Minimum version for modern DOCX support
                print(f"Warning: Pandoc version {version} may not support all modern DOCX features. Consider upgrading to 2.19+")
        except Exception:
            print("Warning: Could not determine pandoc version")
    
    def convert(self, 
                input_path: str | Path, 
                output_path: Optional[str | Path] = None,
                **options) -> Path:
        """Convert markdown file to modern DOCX format.
        
        Args:
            input_path: Path to input markdown file
            output_path: Path to output DOCX file (optional)
            **options: Additional pandoc options
            
        Returns:
            Path to the created DOCX file
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
            
        if output_path is None:
            output_path = input_path.with_suffix('.docx')
        else:
            output_path = Path(output_path)
        
        # Configure pandoc options for modern DOCX output
        pandoc_args = self._get_modern_docx_args(**options)
        
        try:
            pypandoc.convert_file(
                str(input_path),
                'docx',
                outputfile=str(output_path),
                extra_args=pandoc_args
            )
        except Exception as e:
            raise RuntimeError(f"Conversion failed: {e}")
        
        return output_path
    
    def _get_modern_docx_args(self, **options) -> list[str]:
        """Get pandoc arguments for modern DOCX output."""
        args = []
        
        # Use reference document if provided
        if self.reference_doc and self.reference_doc.exists():
            args.extend(['--reference-doc', str(self.reference_doc)])
        
        # Modern DOCX features
        args.extend([
            '--wrap=preserve',  # Preserve line wrapping
            '--columns=72',     # Standard column width
            '--toc-depth=3',    # Table of contents depth
        ])
        
        # Ensure headings are properly styled as Word headings
        # This is crucial for proper heading recognition in Word
        args.extend([
            '--standalone',     # Generate standalone document with proper styles
        ])
        
        # Enable modern markdown extensions (compatible with Pandoc 3.x)
        markdown_extensions = [
            'fenced_code_blocks', 
            'footnotes',
            'definition_lists',
            'strikeout',
            'superscript',
            'subscript',
            'task_lists',
            'pipe_tables',
            'grid_tables',
            'multiline_tables',
            'simple_tables',
            'table_captions',
            'header_attributes',
            'fenced_code_attributes',
            'bracketed_spans',
            'fenced_divs'
        ]
        
        # Add extensions to from format
        from_format = f"markdown+{'+'.join(markdown_extensions)}"
        args.extend(['-f', from_format])
        
        # Ensure proper DOCX output format with heading styles
        # This is crucial for Word to recognize headings properly
        args.extend(['-t', 'docx+styles'])
        
        # Add table of contents if requested
        if options.get('--toc') or options.get('toc'):
            args.append('--toc')
            toc_depth = options.get('--toc-depth', options.get('toc_depth', 3))
            args.extend(['--toc-depth', str(toc_depth)])
        
        # Custom options from user
        for key, value in options.items():
            if key.startswith('--') and key not in ['--toc', '--toc-depth']:
                if value is True:
                    args.append(key)
                elif value is not False:
                    args.extend([key, str(value)])
            elif key in ['toc', 'toc_depth']:  # Skip these as they're handled above
                continue
        
        return args
    
    def convert_with_template(self, 
                            input_path: str | Path,
                            template_path: str | Path,
                            output_path: Optional[str | Path] = None) -> Path:
        """Convert markdown using a DOCX template for consistent styling.
        
        Args:
            input_path: Path to input markdown file
            template_path: Path to DOCX template file
            output_path: Path to output DOCX file (optional)
            
        Returns:
            Path to the created DOCX file
        """
        template_path = Path(template_path)
        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        # Temporarily set reference document
        original_ref = self.reference_doc
        self.reference_doc = template_path
        
        try:
            result = self.convert(input_path, output_path)
        finally:
            self.reference_doc = original_ref
            
        return result