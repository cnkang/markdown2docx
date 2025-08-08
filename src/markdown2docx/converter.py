"""Markdown to DOCX converter implementation."""

import pypandoc
from pathlib import Path
from typing import Optional


class MarkdownToDocxConverter:
    """Convert Markdown files to DOCX format using pypandoc."""
    
    def convert(self, input_path: str | Path, output_path: Optional[str | Path] = None) -> Path:
        """Convert markdown file to DOCX.
        
        Args:
            input_path: Path to input markdown file
            output_path: Path to output DOCX file (optional)
            
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
            
        pypandoc.convert_file(
            str(input_path),
            'docx',
            outputfile=str(output_path),
            extra_args=['--reference-doc=']
        )
        
        return output_path