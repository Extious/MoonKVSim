#!/usr/bin/env python3
"""Sequential native Draw.io exports, followed by final-width PDF previews."""
from pathlib import Path
import argparse
import json
import subprocess
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
OUT = REPO / "output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page"
CLI = "/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
ALL_PAGES = ["01-nsa-prefill", "02-moba-prefill", "03-infllmv2-prefill", "04-dsa-prefill", "05-nosa-prefill"]
ap = argparse.ArgumentParser()
ap.add_argument("--formats", nargs="+", default=["png", "svg", "pdf"])
ap.add_argument("--pages", nargs="+", default=ALL_PAGES)
args = ap.parse_args()
for name in args.pages:
    for fmt in args.formats:
        command = [CLI, "-x", "-f", fmt, "-e", "-b", "0"]
        command += ["--crop"] if fmt == "pdf" else (["--width", "1080"] if fmt == "png" else [])
        command += ["-o", str(OUT / f"{name}.{fmt}"), str(HERE / f"{name}.drawio")]
        subprocess.run(command, check=True)
        if fmt == "pdf":
            import pymupdf
            # Draw.io's PDF string escaping can leave literal backslashes around
            # parentheses in its URI-encoded Subject. Encode all punctuation to
            # preserve the exact editable source without changing page content.
            native_pdf = pymupdf.open(OUT / f"{name}.pdf")
            metadata = native_pdf.metadata
            metadata["subject"] = quote((HERE / f"{name}.drawio").read_text(), safe="")
            native_pdf.set_metadata(metadata)
            native_pdf.saveIncr()
            native_pdf.close()
        print(f"Exported {name}.{fmt}", flush=True)

if "pdf" in args.formats:
    import pymupdf
    reports = []
    combined = pymupdf.open()
    width_pt = 178 / 25.4 * 72
    for name in ALL_PAGES:
        path = OUT / f"{name}.pdf"
        doc = pymupdf.open(path)
        assert len(doc) == 1
        page = doc[0]
        ratio = width_pt / page.rect.width
        spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        page.get_pixmap(matrix=pymupdf.Matrix(ratio*150/72, ratio*150/72), alpha=False).save(OUT / f"{name}.pdf-preview.png")
        # Reading booklet at the declared 178 mm width. Individual native PDFs
        # retain their original embedded editable XML; booklet is for reading.
        dest = combined.new_page(width=width_pt, height=page.rect.height*ratio)
        dest.show_pdf_page(dest.rect, doc, 0)
        reports.append({"file": str(path), "native_size_pt": list(page.rect)[2:],
                        "placed_width_mm": 178, "placed_min_font_pt": min(s["size"] for s in spans)*ratio,
                        "placed_max_font_pt": max(s["size"] for s in spans)*ratio,
                        "text_span_count": len(spans), "preview_dpi": 150})
    combined.save(OUT / "native-sparse-prefill-178mm.pdf")
    (OUT / "PDF-METADATA.json").write_text(json.dumps(reports, indent=2))
