#!/usr/bin/env python3
"""Render existing paper PDFs for inline viewing in paper_draft.md."""

import hashlib
import json
import re
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[3]
FIGURES = ROOT / "paper" / "figures"
PREVIEWS = FIGURES / "preview"
REPORT = ROOT / "exports" / "draft-preview" / "manifest.json"


def main():
    PREVIEWS.mkdir(exist_ok=True)
    entries = []
    source_text = "\n".join(path.read_text() for path in (ROOT / "paper").glob("*.tex"))
    paths = sorted(set(re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", source_text)))
    for relative in paths:
        source = ROOT / "paper" / relative
        name = source.stem
        width = 1200 if name in {"policy-ablation", "storage-overview"} else 900
        target = PREVIEWS / f"{name}.png"
        with fitz.open(source) as document:
            if len(document) != 1:
                raise ValueError(f"Expected a single-page figure: {source}")
            page = document[0]
            scale = width / page.rect.width
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(target)
            entries.append({
                "source": str(source.relative_to(ROOT)),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "preview": str(target.relative_to(ROOT)),
                "preview_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "width_px": pixmap.width,
                "height_px": pixmap.height,
                "source_width_pt": page.rect.width,
                "source_height_pt": page.rect.height,
            })
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "method": "PyMuPDF rendering; full source page; uniform scaling; no crop or redraw",
        "pymupdf_version": fitz.VersionBind,
        "figures": entries,
    }, indent=2) + "\n")
    print(f"Rendered {len(entries)} figures for paper_draft.md")


if __name__ == "__main__":
    main()
