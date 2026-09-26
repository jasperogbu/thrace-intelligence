#!/usr/bin/env python3
"""Render the report chapters to .docx and .pdf.

The formatting matches the previously generated report so the deliverable
looks unchanged: US Letter, 1.25in side / 1in top-bottom margins, Times
New Roman 12pt body, 16/14/12pt bold headings, Table Grid tables, and
Courier New for code blocks.

Markdown is rendered, not passed through: headings, paragraphs, bullets,
numbered lists, fenced code, pipe tables and bold spans are all mapped to
real Word paragraphs/tables so the output is editable.

Usage:
    python scripts/render_report.py
"""
from __future__ import annotations

import os
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "report")
CHAPTERS = [
    "01-introduction.md",
    "02-literature-review.md",
    "03-methodology.md",
    "04-implementation-results.md",
    "05-discussion.md",
    "06-conclusion.md",
]
DOCX_OUT = os.path.join(REPORT_DIR, "Thrace_Final_Year_Project.docx")
PDF_OUT = os.path.join(REPORT_DIR, "Thrace_Final_Year_Project.pdf")

BODY_FONT = "Times New Roman"
MONO_FONT = "Courier New"
BODY_SIZE = Pt(12)


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------
INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
INLINE_CODE = re.compile(r"`([^`]+)`")


def _add_runs(paragraph, text: str, base_size=BODY_SIZE, base_font=BODY_FONT):
    """Write `text` into `paragraph`, honouring **bold** and `code` spans."""
    # Split on the two inline markers in one pass so they can be interleaved.
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos : m.start()]).font.size = base_size
        if m.group(1) is not None:
            run = paragraph.add_run(m.group(1))
            run.bold = True
            run.font.size = base_size
        else:
            run = paragraph.add_run(m.group(2))
            run.font.name = MONO_FONT
            run.font.size = Pt(10.5)
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:]).font.size = base_size


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|") and line.strip().endswith("|")


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:\-|]+\|?", line.strip()))


def parse_markdown(text: str) -> list[tuple]:
    """Flatten markdown into ('kind', payload) blocks.

    Kinds: h1 h2 h3 h4 p bullet number code table caption blank
    """
    lines = text.split("\n")
    blocks: list[tuple] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            blocks.append(("blank", ""))
            i += 1
            continue

        # Fenced code
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append(("code", "\n".join(buf)))
            continue

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            blocks.append((f"h{len(m.group(1))}", m.group(2).strip()))
            i += 1
            continue

        # Table: header row followed by a separator row
        if _is_table_row(stripped) and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            header = _table_cells(stripped)
            i += 2
            rows = []
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(_table_cells(lines[i]))
                i += 1
            blocks.append(("table", (header, rows)))
            continue

        # Bullets
        if re.match(r"^[-*]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]).strip())
                i += 1
            blocks.append(("bullet", items))
            continue

        # Numbered list
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip())
                i += 1
            blocks.append(("number", items))
            continue

        # Paragraph (consume until a blank line or the start of another block)
        buf = []
        while i < len(lines):
            cur = lines[i].rstrip()
            s = cur.strip()
            if (
                not s
                or s.startswith("#")
                or s.startswith("```")
                or re.match(r"^\s*[-*]\s+", cur)
                or re.match(r"^\s*\d+\.\s+", cur)
                or _is_table_row(s)
            ):
                break
            buf.append(s)
            i += 1
        if buf:
            blocks.append(("p", " ".join(buf)))
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------------------
# DOCX rendering
# ---------------------------------------------------------------------------
def build_docx(chapters: list[tuple[str, str]]) -> Document:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = Inches(1.25)
    section.right_margin = Inches(1.25)
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)

    styles = doc.styles
    for name, size, bold in (
        ("Normal", 12, False),
        ("Heading 1", 16, True),
        ("Heading 2", 14, True),
        ("Heading 3", 12, True),
        ("Heading 4", 12, True),
    ):
        st = styles[name]
        st.font.name = BODY_FONT
        st.font.size = Pt(size)
        st.font.bold = bold

    doc.add_paragraph().add_run()
    for filename, text in chapters:
        _render_blocks(doc, parse_markdown(text))
    return doc


def _render_blocks(doc: Document, blocks: list[tuple]) -> None:
    for kind, payload in blocks:
        if kind == "blank":
            continue

        if kind in ("h1", "h2", "h3", "h4"):
            p = doc.add_heading(level=int(kind[1]))
            _add_runs(p, payload, base_size=Pt(16 if kind == "h1" else 14 if kind == "h2" else 12))
            continue

        if kind == "p":
            p = doc.add_paragraph()
            _add_runs(p, payload)
            continue

        if kind == "bullet":
            for item in payload:
                p = doc.add_paragraph(style="List Bullet")
                _add_runs(p, item)
            continue

        if kind == "number":
            for item in payload:
                p = doc.add_paragraph(style="List Number")
                _add_runs(p, item)
            continue

        if kind == "code":
            for line in payload.split("\n"):
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(line if line else " ")
                run.font.name = MONO_FONT
                run.font.size = Pt(9)
            doc.add_paragraph()
            continue

        if kind == "table":
            header, rows = payload
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for idx, cell_text in enumerate(header):
                cell = table.rows[0].cells[idx]
                cell.text = ""
                para = cell.paragraphs[0]
                run = para.add_run(cell_text)
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.name = BODY_FONT
            for row in rows:
                cells = table.add_row().cells
                for idx, cell_text in enumerate(row[: len(header)]):
                    cells[idx].text = ""
                    para = cells[idx].paragraphs[0]
                    _add_runs(para, cell_text, base_size=Pt(10.5))
            doc.add_paragraph()
            continue


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------
def build_pdf(chapters: list[tuple[str, str]]) -> None:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    sheet = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=sheet["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    h1 = ParagraphStyle("H1", parent=body, fontName="Times-Bold", fontSize=15, spaceBefore=14, spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=body, fontName="Times-Bold", fontSize=13, spaceBefore=12, spaceAfter=6)
    h3 = ParagraphStyle("H3", parent=body, fontName="Times-Bold", fontSize=11.5, spaceBefore=10, spaceAfter=5)
    h4 = ParagraphStyle("H4", parent=body, fontName="Times-Bold", fontSize=11, spaceBefore=8, spaceAfter=4)
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=16, bulletIndent=6, spaceAfter=3)
    code = ParagraphStyle("Code", parent=body, fontName="Courier", fontSize=8, leading=10, spaceAfter=0)
    cell = ParagraphStyle("Cell", parent=body, fontSize=9, leading=11, spaceAfter=0)
    cellb = ParagraphStyle("CellB", parent=cell, fontName="Times-Bold")

    def markup(text: str) -> str:
        """Escape for reportlab and restore bold/code as reportlab tags."""
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = INLINE_CODE.sub(r'<font face="Courier">\1</font>', text)
        text = INLINE_BOLD.sub(r"<b>\1</b>", text)
        return text

    def table_flow(header, rows):
        data = [[Paragraph(markup(c), cellb) for c in header]]
        for row in rows:
            data.append([Paragraph(markup(c), cell) for c in row[: len(header)]])
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, (0.4, 0.4, 0.4)),
                    ("BACKGROUND", (0, 0), (-1, 0), (0.93, 0.93, 0.93)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return tbl

    doc = SimpleDocTemplate(
        PDF_OUT,
        pagesize=LETTER,
        leftMargin=1.25 * inch,
        rightMargin=1.25 * inch,
        topMargin=1.0 * inch,
        bottomMargin=1.0 * inch,
        title="Thrace — Final Year Project Report",
        author="Thrace",
    )

    story = []
    for idx, (_filename, text) in enumerate(chapters):
        if idx:
            story.append(PageBreak())
        for kind, payload in parse_markdown(text):
            if kind == "blank":
                continue
            if kind == "h1":
                story.append(Paragraph(markup(payload), h1))
            elif kind == "h2":
                story.append(Paragraph(markup(payload), h2))
            elif kind in ("h3", "h4"):
                story.append(Paragraph(markup(payload), h3 if kind == "h3" else h4))
            elif kind == "p":
                story.append(Paragraph(markup(payload), body))
            elif kind == "bullet":
                for item in payload:
                    story.append(Paragraph(markup(item), bullet, bulletText="•"))
            elif kind == "number":
                for n, item in enumerate(payload, 1):
                    story.append(Paragraph(markup(item), bullet, bulletText=f"{n}."))
            elif kind == "code":
                for line in payload.split("\n"):
                    story.append(Paragraph(markup(line) or "&nbsp;", code))
                story.append(Spacer(1, 8))
            elif kind == "table":
                header, rows = payload
                story.append(table_flow(header, rows))
                story.append(Spacer(1, 8))

    doc.build(story)


def main() -> int:
    chapters: list[tuple[str, str]] = []
    for name in CHAPTERS:
        path = os.path.join(REPORT_DIR, name)
        if not os.path.isfile(path):
            print(f"missing chapter: {name}", file=sys.stderr)
            return 1
        with open(path, encoding="utf-8") as fh:
            chapters.append((name, fh.read()))

    build_docx(chapters).save(DOCX_OUT)
    build_pdf(chapters)

    for path in (DOCX_OUT, PDF_OUT):
        print(f"  {os.path.basename(path):<40} {os.path.getsize(path) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
