"""Template management for modern DOCX output.

Goals:
- Produce a clean, predictable reference DOCX for Pandoc or direct authoring.
- Configure universally sensible defaults (A4/Letter, 1" margins, GDI-safe fonts).
- Use built-in Word styles (Heading 1..6, Normal) so downstream tools recognize them.
- Avoid features python-docx cannot truly control (themes, advanced compatibility) unless done via XML.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Optional, Literal

from docx import Document
from docx.shared import Inches, Pt, Cm
from docx.enum.style import WD_STYLE_TYPE

# Optional: available page presets
PageSize = Literal["A4", "Letter"]


class DocxTemplateManager:
    """Build a modern, consistent DOCX template for downstream use."""

    def __init__(
        self,
        *,
        page_size: PageSize = "A4",
        margin: float = 2.54,  # centimeters (≈1 inch)
        body_font: str = "Calibri",
        body_size_pt: int = 11,
        heading_font: str = "Calibri",
        code_font: str = "Consolas",
    ) -> None:
        self.page_size = page_size
        self.margin_cm = margin
        self.body_font = body_font
        self.body_size_pt = body_size_pt
        self.heading_font = heading_font
        self.code_font = code_font

    def create_modern_template(self, output_path: str | Path, *, add_sample: bool = False) -> Path:
        """Create a modern DOCX template.

        Args:
            output_path: Where to save the template (e.g., reference.docx).
            add_sample: If True, inserts minimal sample content to preview styles.

        Returns:
            Path to the created DOCX file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = Document()

        # Page + margin setup (A4 is typical outside US; Letter for US)
        self._configure_page_layout(doc)
        # Core styles (Normal + Headings + Code)
        self._configure_core_styles(doc)
        # Optional: add minimal content so users see headings etc.
        if add_sample:
            self._add_sample_content(doc)

        # Best-effort: set a modern compatibility mode in settings.xml (not exposed by python-docx)
        self._set_compatibility_mode_xml(doc, mode="16")  # Word 2016/2019+ (best-effort)

        doc.save(output_path)
        return output_path

    # ---------- Layout & styles ----------

    def _configure_page_layout(self, doc: Document) -> None:
        """Configure page size and margins."""
        for section in doc.sections:
            # Margins
            section.top_margin = Cm(self.margin_cm)
            section.bottom_margin = Cm(self.margin_cm)
            section.left_margin = Cm(self.margin_cm)
            section.right_margin = Cm(self.margin_cm)

            # Page size
            if self.page_size == "A4":
                section.page_width = Cm(21.0)
                section.page_height = Cm(29.7)
            else:  # Letter
                section.page_width = Inches(8.5)
                section.page_height = Inches(11.0)

    def _configure_core_styles(self, doc: Document) -> None:
        """Configure Normal, Heading 1..6, and a Code Block paragraph style."""
        styles = doc.styles

        # Normal
        normal = styles["Normal"]
        normal.font.name = self.body_font
        normal.font.size = Pt(self.body_size_pt)
        pf = normal.paragraph_format
        pf.space_after = Pt(6)
        pf.line_spacing = 1.15

        # Headings (use built-in names so TOC and outline work everywhere)
        # Sizes chosen for readability; adjust as desired
        heading_specs = [
            ("Heading 1", 18, True, 12, 6),
            ("Heading 2", 16, True, 10, 4),
            ("Heading 3", 14, True, 8, 3),
            ("Heading 4", 12, True, 6, 3),
            ("Heading 5", 11, False, 6, 3),
            ("Heading 6", 11, False, 6, 3),
        ]
        for name, size_pt, bold, space_before_pt, space_after_pt in heading_specs:
            style = styles[name] if name in styles else styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            style.font.name = self.heading_font
            style.font.size = Pt(size_pt)
            style.font.bold = bold
            p = style.paragraph_format
            p.space_before = Pt(space_before_pt)
            p.space_after = Pt(space_after_pt)
            p.keep_with_next = True  # keep heading with the following paragraph

        # Code Block paragraph style (not built-in; keep the name stable)
        code_name = "Code Block"
        if code_name in styles:
            code_style = styles[code_name]
        else:
            code_style = styles.add_style(code_name, WD_STYLE_TYPE.PARAGRAPH)
        code_style.font.name = self.code_font
        code_style.font.size = Pt(9)
        cp = code_style.paragraph_format
        cp.left_indent = Cm(0.75)
        cp.space_before = Pt(6)
        cp.space_after = Pt(6)

    def _add_sample_content(self, doc: Document) -> None:
        """Insert minimal content for preview/testing the template styles."""
        doc.add_heading("Heading 1", level=1)
        doc.add_paragraph("Body text under Heading 1. Replace or remove this sample content.")
        doc.add_heading("Heading 2", level=2)
        doc.add_paragraph("Body text under Heading 2.")
        doc.add_heading("Heading 3", level=3)
        doc.add_paragraph("Body text under Heading 3.")
        doc.add_paragraph("Sample code paragraph:", style="Normal")
        doc.add_paragraph("for i in range(3): print(i)", style="Code Block")

    # ---------- Low-level XML helpers (best-effort) ----------

    def _set_compatibility_mode_xml(self, doc: Document, *, mode: str = "16") -> None:
        """Set Word compatibility mode via settings.xml (best-effort).

        Notes:
        - python-docx does not expose this directly; we edit the XML tree.
        - Common values: 14 (Word 2010), 15 (Word 2013), 16 (Word 2016/2019+).
        - This hints Word rendering behavior for better modern compatibility.
        """
        with contextlib.suppress(Exception):
            # Find settings part
            settings_part = next(
                (part for part in doc.part._child_parts if 'settings' in str(part.partname)),
                None
            )
            
            if not settings_part:
                return
                
            settings = settings_part._element
            nsmap = settings.nsmap or {}
            w_ns = nsmap.get('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
            w = f"{{{w_ns}}}"

            # Find or create compat element
            compat = settings.find(f"{w}compat")
            if compat is None:
                compat = settings.makeelement(f"{w}compat")
                settings.append(compat)

            # Update or create compatibilityMode setting
            existing = compat.findall(f"{w}compatSetting")
            target = next(
                (el for el in existing if el.get(f"{w}name") == "compatibilityMode"),
                None
            )
                    
            if target is None:
                target = settings.makeelement(f"{w}compatSetting")
                compat.append(target)

            target.set(f"{w}name", "compatibilityMode")
            target.set(f"{w}uri", "http://schemas.microsoft.com/office/word")
            target.set(f"{w}val", mode)

    # ---------- Static method for backward compatibility ----------
    
    @classmethod
    def create_default_template(cls, output_path: str | Path) -> Path:
        """Create a modern DOCX template with default settings (backward compatibility)."""
        manager = cls()
        return manager.create_modern_template(output_path, add_sample=True)