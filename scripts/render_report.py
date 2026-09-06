#!/usr/bin/env python3
"""Render the Thrace project report chapters (Markdown) to DOCX and PDF."""
import re
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Preformatted, PageBreak,
)

REPORT_DIR = Path(__file__).resolve().parent.parent / "report"
CHAPTERS = [f"0{i}-" for i in range(1, 7)]


# ---------------------------------------------------------------------------
# Markdown parsing (shared)
# ---------------------------------------------------------------------------
def parse_markdown(text):
    """Parse chapter markdown into a list of block dicts."""
    lines = text.split("\n")
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        if line.startswith("```"):
            j = i + 1
            code = []
            while j < n and not lines[j].startswith("```"):
                code.append(lines[j])
                j += 1
            blocks.append({"type": "code", "text": "\n".join(code)})
            i = j + 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            blocks.append({"type": f"h{len(m.group(1))}", "text": m.group(2).strip()})
            i += 1
            continue

        if re.match(r"^\|.*\|$", line) and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            header = [c.strip() for c in line.strip("|").split("|")]
            rows = []
            j = i + 2
            while j < n and re.match(r"^\|.*\|$", lines[j]):
                rows.append([c.strip() for c in lines[j].strip("|").split("|")])
                j += 1
            blocks.append({"type": "table", "header": header, "rows": rows})
            i = j
            continue

        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            blocks.append({"type": "ol", "items": items})
            continue

        if line.strip() == "":
            i += 1
            continue

        # paragraph: consume until blank line or special block start
        para = [line]
        i += 1
        while i < n and lines[i].strip() != "" and not (
            lines[i].startswith(("#", "```"))
            or re.match(r"^\s*[-*]\s+", lines[i])
            or re.match(r"^\s*\d+\.\s+", lines[i])
            or re.match(r"^\|.*\|$", lines[i])
        ):
            para.append(lines[i])
            i += 1
        blocks.append({"type": "p", "text": " ".join(para)})
    return blocks


def md_inline_to_xml(s):
    """Markdown inline -> list of (text, bold, italic) tuples."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    tokens = re.split(r"(\*\*.*?\*\*|\*.*?\*)", s)
    out = []
    for t in tokens:
        if not t:
            continue
        if t.startswith("**") and t.endswith("**"):
            out.append((t[2:-2], True, False))
        elif t.startswith("*") and t.endswith("*"):
            out.append((t[1:-1], False, True))
        else:
            out.append((t, False, False))
    return out


# ---------------------------------------------------------------------------
# DOCX builder
# ---------------------------------------------------------------------------
def build_docx(all_blocks, out_path):
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    style.paragraph_format.line_spacing = 1.5
    style.paragraph_format.space_after = Pt(6)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "Times New Roman")

    for name, size, bold, before, after, align in [
        ("Heading 1", 16, True, 18, 12, WD_ALIGN_PARAGRAPH.CENTER),
        ("Heading 2", 14, True, 16, 10, WD_ALIGN_PARAGRAPH.CENTER),
        ("Heading 3", 12, True, 14, 8, WD_ALIGN_PARAGRAPH.LEFT),
        ("Heading 4", 12, True, 12, 6, WD_ALIGN_PARAGRAPH.LEFT),
    ]:
        h = doc.styles[name]
        h.font.name = "Times New Roman"
        h.font.size = Pt(size)
        h.font.bold = bold
        h.font.color.rgb = RGBColor(0, 0, 0)
        h.paragraph_format.space_before = Pt(before)
        h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.alignment = align

    def add_runs(p, text):
        for txt, bold, italic in md_inline_to_xml(text):
            r = p.add_run(txt)
            r.bold = bold
            r.italic = italic

    for chapter_blocks in all_blocks:
        first_h2 = True
        for b in chapter_blocks:
            t = b["type"]
            if t == "h1":
                p = doc.add_paragraph(style="Heading 1")
                add_runs(p, b["text"])
            elif t == "h2":
                if not first_h2:
                    doc.add_page_break()
                first_h2 = False
                p = doc.add_paragraph(style="Heading 2")
                add_runs(p, b["text"])
            elif t == "h3":
                p = doc.add_paragraph(style="Heading 3")
                add_runs(p, b["text"])
            elif t == "h4":
                p = doc.add_paragraph(style="Heading 4")
                add_runs(p, b["text"])
            elif t == "p":
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                add_runs(p, b["text"])
            elif t == "ul":
                for item in b["items"]:
                    p = doc.add_paragraph(style="List Bullet")
                    add_runs(p, item)
            elif t == "ol":
                for item in b["items"]:
                    p = doc.add_paragraph(style="List Number")
                    add_runs(p, item)
            elif t == "code":
                for code_line in b["text"].split("\n"):
                    p = doc.add_paragraph()
                    r = p.add_run(code_line)
                    r.font.name = "Courier New"
                    r.font.size = Pt(8.5)
                    rpr2 = r._element.get_or_add_rPr()
                    rf2 = OxmlElement("w:rFonts")
                    rf2.set(qn("w:ascii"), "Courier New")
                    rf2.set(qn("w:hAnsi"), "Courier New")
                    rpr2.append(rf2)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.0
            elif t == "table":
                header, rows = b["header"], b["rows"]
                table = doc.add_table(rows=1 + len(rows), cols=len(header))
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for c, htxt in enumerate(header):
                    cell = table.rows[0].cells[c]
                    cell.text = ""
                    p = cell.paragraphs[0]
                    r = p.add_run(re.sub(r"\*\*?", "", htxt))
                    r.bold = True
                    r.font.size = Pt(10)
                for rI, row in enumerate(rows):
                    for c, val in enumerate(row):
                        if c >= len(header):
                            continue
                        cell = table.rows[rI + 1].cells[c]
                        cell.text = ""
                        p = cell.paragraphs[0]
                        add_runs(p, val)
                        for r in p.runs:
                            r.font.size = Pt(10)
                doc.add_paragraph()
    doc.save(out_path)


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------
def build_pdf(all_blocks, out_path):
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=styles["Normal"], fontName="Times-Roman",
        fontSize=11, leading=16.5, alignment=TA_JUSTIFY, spaceAfter=8,
    )
    h1 = ParagraphStyle(
        "H1x", parent=body, fontName="Times-Bold", fontSize=16,
        leading=20, alignment=TA_CENTER, spaceBefore=10, spaceAfter=14,
    )
    h2 = ParagraphStyle(
        "H2x", parent=body, fontName="Times-Bold", fontSize=14,
        leading=18, alignment=TA_CENTER, spaceBefore=8, spaceAfter=12,
    )
    h3 = ParagraphStyle(
        "H3x", parent=body, fontName="Times-Bold", fontSize=12,
        leading=16, spaceBefore=12, spaceAfter=6,
    )
    h4 = ParagraphStyle("H4x", parent=h3, fontSize=11.5)
    li = ParagraphStyle("LIx", parent=body, leftIndent=18, spaceAfter=4)
    code = ParagraphStyle(
        "Codex", fontName="Courier", fontSize=7.6, leading=9.5,
        leftIndent=12, spaceAfter=8,
    )

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def fmt(s):
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", s)
        return s

    def add_footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Times-Roman", 9)
        canvas.drawCentredString(A4[0] / 2, 1.4 * cm, str(canvas.getPageNumber()))
        canvas.restoreState()

    story = []
    for chapter_blocks in all_blocks:
        first_h2 = True
        for b in chapter_blocks:
            t = b["type"]
            if t == "h1":
                story.append(Paragraph(fmt(b["text"]), h1))
            elif t == "h2":
                if not first_h2:
                    story.append(PageBreak())
                first_h2 = False
                story.append(Paragraph(fmt(b["text"]), h2))
            elif t == "h3":
                story.append(Paragraph(fmt(b["text"]), h3))
            elif t == "h4":
                story.append(Paragraph(fmt(b["text"]), h4))
            elif t == "p":
                story.append(Paragraph(fmt(b["text"]), body))
            elif t == "ul":
                for item in b["items"]:
                    story.append(Paragraph("•&nbsp;&nbsp;" + fmt(item), li))
            elif t == "ol":
                for k, item in enumerate(b["items"], 1):
                    story.append(Paragraph(f"{k}.&nbsp;&nbsp;" + fmt(item), li))
            elif t == "code":
                txt = b["text"]
                if txt.strip():
                    story.append(Preformatted(txt, code))
            elif t == "table":
                header, rows = b["header"], b["rows"]
                data = [[Paragraph("<b>" + fmt(h) + "</b>", body) for h in header]]
                for row in rows:
                    data.append([Paragraph(fmt(v), body) for v in row[: len(header)]])
                avail = A4[0] - 3 * cm
                ncols = max(1, len(header))
                widths = [avail / ncols] * ncols
                tbl = Table(data, colWidths=widths, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.92, 0.92, 0.92)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 8))

    docpdf = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=2.54 * cm, rightMargin=2.54 * cm,
        topMargin=2.54 * cm, bottomMargin=2.54 * cm,
        title="Thrace Final Year Project Report",
        author="Thrace",
    )
    docpdf.build(story, onFirstPage=add_footer, onLaterPages=add_footer)


# ---------------------------------------------------------------------------
def main():
    files = sorted(p for p in REPORT_DIR.glob("*.md") if p.name[:3] in CHAPTERS)
    if not files:
        print("no chapter files found", file=sys.stderr)
        sys.exit(1)

    all_blocks = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        all_blocks.append(parse_markdown(text))
        print(f"parsed {f.name}")

    docx_path = REPORT_DIR / "Thrace_Final_Year_Project.docx"
    pdf_path = REPORT_DIR / "Thrace_Final_Year_Project.pdf"
    build_docx(all_blocks, docx_path)
    print(f"wrote {docx_path}")
    build_pdf(all_blocks, pdf_path)
    print(f"wrote {pdf_path}")


if __name__ == "__main__":
    main()
