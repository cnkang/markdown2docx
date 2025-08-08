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
        
        # Add sample content to establish the template structure
        doc.add_heading('标题1示例', level=1)
        doc.add_paragraph('这是正文段落示例。')
        doc.add_heading('标题2示例', level=2)
        doc.add_paragraph('这是另一个正文段落示例。')
        doc.add_heading('标题3示例', level=3)
        doc.add_paragraph('删除此模板内容后即可使用。')
        
        doc.save(output_path)
        return output_path
    
    @staticmethod
    def _create_heading_styles(doc: Document) -> None:
        """Create modern heading styles that map to Word's built-in heading styles."""
        styles = doc.styles
        
        # Configure built-in heading styles (这些是Word内置的标题样式)
        heading_configs = [
            ('Heading 1', 18, 12, 6),
            ('Heading 2', 14, 10, 4), 
            ('Heading 3', 12, 8, 3),
            ('Heading 4', 11, 6, 3),
            ('Heading 5', 11, 6, 3),
            ('Heading 6', 11, 6, 3)
        ]
        
        for style_name, font_size, space_before, space_after in heading_configs:
            try:
                # Use existing built-in style or create if not exists
                if style_name in styles:
                    heading_style = styles[style_name]
                else:
                    heading_style = styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
                
                # Configure font
                heading_font = heading_style.font
                heading_font.name = 'Calibri'
                heading_font.size = Pt(font_size)
                heading_font.bold = True
                heading_font.color.rgb = None  # Use theme color
                
                # Configure paragraph formatting
                heading_paragraph = heading_style.paragraph_format
                heading_paragraph.space_before = Pt(space_before)
                heading_paragraph.space_after = Pt(space_after)
                heading_paragraph.keep_with_next = True  # Keep heading with following paragraph
                
            except Exception as e:
                # Skip if style already exists or cannot be modified
                continue
    
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