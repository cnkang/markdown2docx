"""Template management for modern DOCX output."""

from pathlib import Path
from typing import Optional
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH


class DocxTemplateManager:
    """Manage DOCX templates for consistent modern formatting."""
    
    @staticmethod
    def create_modern_template(output_path: str | Path) -> Path:
        """Create a modern DOCX template with current standards.
        
        Args:
            output_path: Path where to save the template
            
        Returns:
            Path to the created template
        """
        output_path = Path(output_path)
        doc = Document()
        
        # Configure document margins (modern standard: 1 inch all around)
        sections = doc.sections
        for section in sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)
        
        # Create modern heading styles
        DocxTemplateManager._create_heading_styles(doc)
        
        # Create modern paragraph styles
        DocxTemplateManager._create_paragraph_styles(doc)
        
        # Create code block style
        DocxTemplateManager._create_code_styles(doc)
        
        # Create table styles
        DocxTemplateManager._create_table_styles(doc)
        
        # Add a sample paragraph to establish the template
        doc.add_paragraph("This is a template document. Delete this content when using.")
        
        doc.save(output_path)
        return output_path
    
    @staticmethod
    def _create_heading_styles(doc: Document) -> None:
        """Create modern heading styles."""
        styles = doc.styles
        
        # Heading 1 - Modern, clean style
        if 'Heading 1' in styles:
            h1_style = styles['Heading 1']
        else:
            h1_style = styles.add_style('Heading 1', WD_STYLE_TYPE.PARAGRAPH)
        
        h1_font = h1_style.font
        h1_font.name = 'Calibri'
        h1_font.size = Pt(18)
        h1_font.bold = True
        h1_font.color.rgb = None  # Use theme color
        
        h1_paragraph = h1_style.paragraph_format
        h1_paragraph.space_before = Pt(12)
        h1_paragraph.space_after = Pt(6)
        
        # Heading 2
        if 'Heading 2' in styles:
            h2_style = styles['Heading 2']
        else:
            h2_style = styles.add_style('Heading 2', WD_STYLE_TYPE.PARAGRAPH)
            
        h2_font = h2_style.font
        h2_font.name = 'Calibri'
        h2_font.size = Pt(14)
        h2_font.bold = True
        
        h2_paragraph = h2_style.paragraph_format
        h2_paragraph.space_before = Pt(10)
        h2_paragraph.space_after = Pt(4)
    
    @staticmethod
    def _create_paragraph_styles(doc: Document) -> None:
        """Create modern paragraph styles."""
        styles = doc.styles
        
        # Normal paragraph style
        normal_style = styles['Normal']
        normal_font = normal_style.font
        normal_font.name = 'Calibri'
        normal_font.size = Pt(11)
        
        normal_paragraph = normal_style.paragraph_format
        normal_paragraph.space_after = Pt(6)
        normal_paragraph.line_spacing = 1.15
    
    @staticmethod
    def _create_code_styles(doc: Document) -> None:
        """Create code block styles."""
        styles = doc.styles
        
        # Code block style
        try:
            code_style = styles.add_style('Code Block', WD_STYLE_TYPE.PARAGRAPH)
            code_font = code_style.font
            code_font.name = 'Consolas'
            code_font.size = Pt(9)
            
            code_paragraph = code_style.paragraph_format
            code_paragraph.left_indent = Inches(0.5)
            code_paragraph.space_before = Pt(6)
            code_paragraph.space_after = Pt(6)
        except ValueError:
            # Style already exists
            pass
    
    @staticmethod
    def _create_table_styles(doc: Document) -> None:
        """Create modern table styles."""
        # Table styles are typically built-in in modern Word
        # This method can be extended for custom table formatting
        pass