#!/usr/bin/env python3
"""Build the supplemental disclosure with native editable Word equations.

Run: uv run --with python-docx --with latex2mathml --with mathml2omml python <this file>
The original imported disclosure is never overwritten.
"""

from pathlib import Path
import re

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from latex2mathml.converter import convert as to_mathml
from mathml2omml import convert as to_omml

HERE = Path(__file__).resolve().parent


def plain(text):
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text).replace("**", "").replace("`", "")


def main():
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(.7)
    section.left_margin = section.right_margin = Inches(.8)
    for name in ("Normal", "Body Text"):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(10.5)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "SimSun")
        style.paragraph_format.space_after = Pt(5)
    lines = (HERE / "ALGORITHMS_2_3_REVISION.md").read_text().splitlines()
    i = 0
    equations = 0
    while i < len(lines):
        line = lines[i]
        if line == r"\[":
            formula = []
            i += 1
            while lines[i] != r"\]":
                formula.append(lines[i])
                i += 1
            xml = to_omml(to_mathml("\n".join(formula)))
            xml = xml.replace("<m:oMath>", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1)
            document.add_paragraph()._p.append(parse_xml(xml))
            equations += 1
        elif line.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                p = document.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(lines[i]); run.font.name = "Consolas"; run.font.size = Pt(8)
                i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [plain(c.strip()) for c in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", c) for c in cells):
                    rows.append(cells)
                i += 1
            table = document.add_table(rows=0, cols=len(rows[0])); table.style = "Table Grid"
            for row in rows:
                for cell, text in zip(table.add_row().cells, row, strict=True):
                    cell.text = text
            i -= 1
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            document.add_heading(line[level:].strip(), min(level - 1, 3))
        elif line.strip():
            document.add_paragraph(plain(line))
        i += 1
    output = HERE / "AegisKV-算法2-3修订技术交底-v3.docx"
    document.save(output)
    print(f"{output.name}: {equations} native equations; original disclosure preserved")


if __name__ == "__main__":
    main()
