#!/usr/bin/env python3
"""Check preserved sources and export actual Evaluation pages for visual review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[5]
STUDY = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
PAPER = ROOT / "benchmark/AegisKV/paper"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = json.loads((STUDY / "PRESERVED_MANUSCRIPT.json").read_text())
    preservation = {}
    for relative, expected in before["files"].items():
        path = ROOT / relative
        data = path.read_bytes()
        if path == PAPER / "main.tex":
            text = data.decode()
            assert text.count("\\input{evaluation}\n") == 1
            text = text.replace("\\input{evaluation}\n", "")
            text = text.replace(
                "\\bibliography{references,evaluation-references}", "\\bibliography{references}"
            )
            assert hashlib.sha256(text.encode()).hexdigest() == expected
            preservation[relative] = "only Evaluation input and bibliography inclusion changed"
        else:
            assert sha(path) == expected, f"preceding manuscript drifted: {relative}"
            preservation[relative] = "unchanged"
    out = STUDY / "paper-preview"
    out.mkdir(exist_ok=True)
    pdf = PAPER / "main.pdf"
    document = pymupdf.open(pdf)
    start = next(i for i, p in enumerate(document) if "Evaluation" in p.get_text().splitlines())
    reference_page = next(
        i for i in range(start, len(document))
        if "References" in document[i].get_text().splitlines()
    )
    before_references = document[reference_page].get_text().split("References\n", 1)[0].strip()
    end = reference_page if before_references else reference_page - 1
    pages = []
    for i in range(start, len(document)):
        page = document[i]
        for gray in (False, True):
            filename = f"page-{i + 1}-{'gray' if gray else 'color'}.png"
            page.get_pixmap(
                matrix=pymupdf.Matrix(1.5, 1.5),
                alpha=False,
                colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB,
            ).save(out / filename)
        pages.append(i + 1)
    figures = []
    for path in sorted((PAPER / "figures").glob("eval-*.pdf")):
        figure = pymupdf.open(path)
        spans = [
            s
            for p in figure
            for b in p.get_text("dict")["blocks"]
            for line in b.get("lines", [])
            for s in line["spans"]
            if s["text"].strip()
        ]
        figures.append(
            dict(
                path=str(path.relative_to(ROOT)),
                sha256=sha(path),
                width_mm=figure[0].rect.width * 25.4 / 72,
                height_mm=figure[0].rect.height * 25.4 / 72,
                min_source_font_pt=min(s["size"] for s in spans),
                source_fonts=sorted({s["font"] for s in spans}),
            )
        )
    record = dict(
        manuscript_sha256=sha(pdf),
        page_count=len(document),
        evaluation_page_range=[start + 1, end + 1],
        references_start_page=reference_page + 1,
        rendered_pages=pages,
        source_preservation=preservation,
        evaluation_figures=figures,
        tex_sha256=sha(PAPER / "evaluation.tex"),
        check="source hashes and export metadata; actual render inspection is separate",
    )
    (out / "EXPORT_REVIEW.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("page_count", "evaluation_page_range")}))


if __name__ == "__main__":
    main()
