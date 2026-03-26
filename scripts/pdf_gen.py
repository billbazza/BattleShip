"""
Battleship — PDF Guide Generator
==================================
Standalone utility for rendering styled PDF guides using fpdf2.
No state, no API calls. Pure input → output.

Usage:
    from scripts.pdf_gen import generate_guide_pdf

    generate_guide_pdf(
        title="My Guide",
        subtitle="A subtitle",
        author="Will Barratt",
        sections=[{"heading": "Chapter 1", "body": "Content here..."}],
        output_path=Path("output.pdf"),
    )
"""
import re
import textwrap
from pathlib import Path

from fpdf import FPDF

VAULT_ROOT = Path(__file__).parent.parent
FONTS_DIR = VAULT_ROOT / "brand" / "fonts"

# Colours (RGB)
ACCENT    = (42, 157, 78)    # #2a9d4e — brand green
DARK_BG   = (18, 18, 18)     # #121212
WHITE     = (255, 255, 255)
LIGHT_GREY = (180, 180, 180)
MID_GREY  = (120, 120, 120)
BODY_TEXT = (50, 50, 50)


class GuidePDF(FPDF):
    """Custom PDF class with Inter fonts and branded footer."""

    def __init__(self, title: str, author: str):
        super().__init__()
        self._guide_title = title
        self._guide_author = author
        self._setup_fonts()

    def _setup_fonts(self):
        regular = str(FONTS_DIR / "Inter-Regular.ttf")
        bold = str(FONTS_DIR / "Inter-Bold.ttf")
        if Path(regular).exists():
            self.add_font("Inter", "", regular)
            self.add_font("Inter", "B", bold)
        else:
            # Fallback to Helvetica if fonts missing
            self.add_font("Inter", "", fname="")

    def footer(self):
        if self.page_no() == 1:
            return  # No footer on cover page
        self.set_y(-15)
        self.set_font("Inter", "", 8)
        self.set_text_color(*MID_GREY)
        self.cell(0, 10, f"battleshipreset.com  |  {self._guide_author}",
                  new_x="LMARGIN", new_y="TOP", align="L")
        self.cell(0, 10, f"{self.page_no()}", new_x="RIGHT", new_y="TOP", align="R")


def _render_cover(pdf: GuidePDF, title: str, subtitle: str, author: str):
    """Draw the cover page with a dark background and accent bar."""
    pdf.add_page()

    # Dark background
    pdf.set_fill_color(*DARK_BG)
    pdf.rect(0, 0, 210, 297, "F")

    # Accent bar at top
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, 210, 6, "F")

    # Title
    pdf.set_y(80)
    pdf.set_font("Inter", "B", 32)
    pdf.set_text_color(*WHITE)
    pdf.multi_cell(0, 14, title, align="C")

    # Subtitle
    pdf.set_y(pdf.get_y() + 8)
    pdf.set_font("Inter", "", 14)
    pdf.set_text_color(*LIGHT_GREY)
    pdf.multi_cell(0, 8, subtitle, align="C")

    # Author
    pdf.set_y(pdf.get_y() + 20)
    pdf.set_font("Inter", "", 12)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 8, f"by {author}", align="C")

    # Bottom accent bar
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 291, 210, 6, "F")


def _render_toc(pdf: GuidePDF, sections: list[dict]):
    """Render a simple table of contents."""
    pdf.add_page()
    pdf.set_font("Inter", "B", 22)
    pdf.set_text_color(*DARK_BG)
    pdf.cell(0, 14, "Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Accent line
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)

    for i, sec in enumerate(sections, 1):
        heading = sec.get("heading", f"Section {i}")
        pdf.set_font("Inter", "", 12)
        pdf.set_text_color(*BODY_TEXT)
        pdf.cell(8, 8, f"{i}.")
        pdf.cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)


def _parse_markdown_line(text: str) -> list[tuple[str, bool]]:
    """Split a line into segments: (text, is_bold). Handles **bold** markers."""
    parts = []
    chunks = re.split(r"(\*\*.*?\*\*)", text)
    for chunk in chunks:
        if chunk.startswith("**") and chunk.endswith("**"):
            parts.append((chunk[2:-2], True))
        elif chunk:
            parts.append((chunk, False))
    return parts


def _render_section(pdf: GuidePDF, index: int, heading: str, body: str):
    """Render a single section with heading and body text."""
    # Check if we need a new page (at least 50mm of space)
    if pdf.get_y() > 240:
        pdf.add_page()

    # Section number + heading
    pdf.set_font("Inter", "B", 18)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 12, f"{index}. {heading}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Accent underline
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 80, pdf.get_y())
    pdf.ln(6)

    # Body text — handle paragraphs and basic markdown
    pdf.set_text_color(*BODY_TEXT)
    paragraphs = body.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Handle bullet points
        if para.startswith("- ") or para.startswith("* "):
            lines = para.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    bullet_text = line[2:].strip()
                    pdf.set_font("Inter", "", 11)
                    pdf.cell(6, 7, chr(8226))  # bullet char
                    # Handle bold within bullet
                    segments = _parse_markdown_line(bullet_text)
                    for seg_text, is_bold in segments:
                        pdf.set_font("Inter", "B" if is_bold else "", 11)
                        pdf.write(7, seg_text)
                    pdf.ln(7)
            pdf.ln(3)
            continue

        # Handle sub-headings (### in markdown)
        if para.startswith("### "):
            if pdf.get_y() > 250:
                pdf.add_page()
            pdf.set_font("Inter", "B", 13)
            pdf.set_text_color(*BODY_TEXT)
            pdf.cell(0, 10, para[4:].strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            continue

        # Regular paragraph — write with inline bold support
        lines = para.replace("\n", " ").strip()
        segments = _parse_markdown_line(lines)
        for seg_text, is_bold in segments:
            pdf.set_font("Inter", "B" if is_bold else "", 11)
            pdf.write(7, seg_text)
        pdf.ln(10)

        # Page break if getting close to bottom
        if pdf.get_y() > 270:
            pdf.add_page()


def _render_back_page(pdf: GuidePDF, author: str, guide_urls: list[dict] | None = None):
    """Render the back page: about the author + other guide promos."""
    pdf.add_page()

    # Dark background
    pdf.set_fill_color(*DARK_BG)
    pdf.rect(0, 0, 210, 297, "F")

    # Accent bar
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, 210, 6, "F")

    # About the author
    pdf.set_y(40)
    pdf.set_font("Inter", "B", 20)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, "About the Author", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font("Inter", "", 11)
    pdf.set_text_color(*LIGHT_GREY)
    about = (
        f"{author} is 47, a former desk jockey who lost 3 stone and dropped his "
        f"fitness age from 55 to 17 — without a gym membership until month 6. "
        f"He built Battleship Reset, a 12-week coaching programme for men 40-60, "
        f"and then built an autonomous AI system to run the entire business. "
        f"Everything in this guide is real — no theory, no hypotheticals. "
        f"Just what actually worked."
    )
    pdf.set_x(20)
    pdf.multi_cell(170, 7, about, align="C")

    # Website CTA
    pdf.ln(12)
    pdf.set_font("Inter", "B", 14)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 10, "battleshipreset.com", align="C", new_x="LMARGIN", new_y="NEXT")

    # Other guides promo
    if guide_urls:
        pdf.ln(20)
        pdf.set_font("Inter", "B", 16)
        pdf.set_text_color(*WHITE)
        pdf.cell(0, 10, "More Guides", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        for g in guide_urls:
            pdf.set_font("Inter", "", 11)
            pdf.set_text_color(*LIGHT_GREY)
            pdf.set_x(30)
            pdf.multi_cell(150, 7, f"{g['title']}  —  {g.get('url', '')}", align="C")
            pdf.ln(3)

    # Bottom accent bar
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 291, 210, 6, "F")


def generate_guide_pdf(
    title: str,
    subtitle: str,
    author: str,
    sections: list[dict],
    output_path: Path,
    guide_urls: list[dict] | None = None,
) -> Path:
    """
    Generate a styled PDF guide.

    sections: [{"heading": "Chapter Title", "body": "Full text..."}]
    guide_urls: [{"title": "Other Guide", "url": "https://..."}] for back page promos

    Returns the output_path on success.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = GuidePDF(title=title, author=author)
    pdf.set_auto_page_break(auto=True, margin=20)

    # Cover
    _render_cover(pdf, title, subtitle, author)

    # Table of contents
    _render_toc(pdf, sections)

    # Content sections
    for i, sec in enumerate(sections, 1):
        pdf.add_page()
        _render_section(pdf, i, sec.get("heading", f"Section {i}"), sec.get("body", ""))

    # Back page
    _render_back_page(pdf, author, guide_urls)

    pdf.output(str(output_path))
    return output_path


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_sections = [
        {"heading": "Getting Started", "body": (
            "This is a test section with some body text. It should render cleanly "
            "with proper paragraph spacing.\n\n"
            "Here is a second paragraph with **bold text** inside it. The bold should "
            "render using Inter Bold.\n\n"
            "### A Sub-heading\n\n"
            "And some text under the sub-heading.\n\n"
            "- Bullet point one\n"
            "- Bullet point two with **bold**\n"
            "- Bullet point three"
        )},
        {"heading": "The Real Story", "body": (
            "This is the second section. It demonstrates a longer body of text "
            "that would typically be generated by Claude.\n\n"
            "The key thing is that this looks professional without any manual "
            "design work. The accent colour, fonts, and spacing do the heavy lifting."
        )},
    ]

    out = generate_guide_pdf(
        title="Test Guide",
        subtitle="A quick test of the PDF generator",
        author="Will Barratt",
        sections=test_sections,
        output_path=VAULT_ROOT / "SOVEREIGN" / "products" / "live" / "test_guide.pdf",
        guide_urls=[
            {"title": "Build Your First AI Agent", "url": "battleshipreset.com"},
            {"title": "The Mac Mini Income Machine", "url": "battleshipreset.com"},
        ],
    )
    print(f"Generated: {out}")
