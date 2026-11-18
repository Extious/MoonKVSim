#!/usr/bin/env python3
"""Export native Draw.io, then remove exporter border rounding for alignment.

The complete native white canvas maps onto its declared physical page. The
vector content, including the branch time scale, is preserved; no redraw or
content crop is used. Editable XML and native exports are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import fitz

from motivation_layout import HEIGHT_IN, WIDTHS_IN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cli = Path.home() / ".codex/skills/drawio/scripts/drawio-cli"
    native = args.output_dir / "workflow.drawio.pdf"
    subprocess.run([str(cli), "-x", "-f", "pdf", "-e", "--crop", "-b", "0",
                    "-o", str(native), str(args.source)], check=True)
    subprocess.run([str(cli), "-x", "-f", "png", "-e", "-b", "0", "-s", "3",
                    "-o", str(args.output_dir / "workflow.drawio.png"), str(args.source)], check=True)
    source = fitz.open(native)
    page = source[0]
    canvases = [d["rect"] for d in page.get_drawings()
                if d["type"] == "f" and d["fill"] == (1, 1, 1)
                and page.rect.contains(d["rect"])
                and d["rect"].get_area() > page.rect.get_area() * .95]
    assert len(canvases) == 1, canvases
    canvas = canvases[0]
    result = fitz.open()
    target = result.new_page(width=WIDTHS_IN["workflow"] * 72, height=HEIGHT_IN * 72)
    target.show_pdf_page(target.rect, source, 0, clip=canvas, keep_proportion=False)
    result.embfile_add(args.source.name, args.source.read_bytes(), desc="Editable Draw.io source")
    result.save(args.output_dir / "workflow.pdf", garbage=4, deflate=True)
    target.get_pixmap(matrix=fitz.Matrix(240/72, 240/72)).save(args.output_dir / "workflow.png")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (args.output_dir / "workflow-export.json").write_text(json.dumps({
        "source":str(args.source), "source_sha256":sha(args.source),
        "generator_sha256":sha(Path(__file__)),
        "layout_sha256":sha(Path(__file__).with_name("motivation_layout.py")),
        "native_pdf_sha256":sha(native), "native_canvas_bbox_pt":list(canvas),
        "final_size_in":[WIDTHS_IN["workflow"], HEIGHT_IN],
        "pdf_sha256":sha(args.output_dir / "workflow.pdf"),
        "operation":"Map the complete native canvas to its declared size; preserve all vector objects."
    }, indent=2)+"\n")


if __name__ == "__main__":
    main()
