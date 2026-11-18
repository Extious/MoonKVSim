#!/usr/bin/env python3
"""Artifact checks accompanying the recorded manual final-size inspection."""
from pathlib import Path
from urllib.parse import unquote
import hashlib
import json
import xml.etree.ElementTree as ET
import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
OUT = REPO / "output/pdf/native-sparse-prefill-20260914"
names = ["01-causal-prefill", "02-nsa-prefill", "03-moba-infllmv2-prefill", "04-dsa-nosa-prefill"]

def cell_signature(node):
    # Native SVG export normalizes editor metadata and drops zero-valued x/y.
    attrs = {k: v for k, v in node.attrib.items() if not (k in {"x", "y"} and v == "0")}
    children = list(node)
    if node.tag == "mxGeometry":
        children.sort(key=lambda child: child.get("as", ""))
    # The order within a waypoint Array is semantically significant and kept.
    return (node.tag, attrs, [cell_signature(child) for child in children])

results = []
for name in names:
    source = (HERE / f"{name}.drawio").read_text()
    png = Image.open(OUT / f"{name}.png")
    embedded = png.info.get("mxGraphModel", png.info.get("mxfile"))
    assert embedded and unquote(embedded) == source
    svg = ET.parse(OUT / f"{name}.svg").getroot()
    svg_graph = ET.fromstring(svg.get("content"))
    source_graph = ET.fromstring(source)
    original_cells = {x.get("id"): cell_signature(x) for x in source_graph.iter("mxCell")}
    exported_cells = {x.get("id"): cell_signature(x) for x in svg_graph.iter("mxCell")}
    assert original_cells == exported_cells
    doc = pymupdf.open(OUT / f"{name}.pdf")
    assert unquote(doc.metadata["subject"]) == source
    assert len(doc) == 1
    assert png.width == 1080
    assert "Query" in doc[0].get_text()
    results.append({"page": name, "png_px": list(png.size), "png_embedded_source_matches": True,
                    "svg_embedded_cell_labels_styles_geometry_match": True, "pdf_subject_embedded_source_matches": True,
                    "native_png_visually_reviewed": True, "pdf_at_178mm_visually_reviewed": True})

book = pymupdf.open(OUT / "native-sparse-prefill-178mm.pdf")
assert len(book) == 4
assert all(abs(p.rect.width/72*25.4 - 178) < 0.01 for p in book)
static = json.loads((OUT / "schematic-masks.json").read_text())
for name, data in static["masks"].items():
    for pos, row in zip(data["row_query_positions"], data["cells"]):
        assert all(v == "future" for v in row[pos:])
        assert all(v != "future" for v in row[:pos])
        if name == "dsa":
            assert row.count("selected") == 6
    if name in {"moba", "infllm-v2", "nosa"}:
        for pos, row in zip(data["row_query_positions"], data["cells"]):
            assert row[pos-1] == "forced"

review = {
    "evidence": "algorithm mechanism illustration; hand-constructed masks; no new model execution",
    "scope": "one layer and one head / KV group; N suffix queries over M+N causal candidates",
    "M": 24, "N": 8, "illustrative_block_size": 4,
    "statistical_units": "not applicable; not empirical repetitions or an equal-budget experiment",
    "sources": {
        "NSA": "https://arxiv.org/html/2502.11089v1",
        "MoBA": "https://arxiv.org/html/2502.13189v1",
        "InfLLM-V2": "https://arxiv.org/html/2509.24663v1",
        "DSA": "https://arxiv.org/html/2512.02556v1",
        "NOSA": "https://arxiv.org/html/2510.13602v2",
        "NOSA_actual_trace": str(REPO / "output/native-sparse-20260914/README.md")
    },
    "semantic_review": [
        "suffix lower triangle includes current position and excludes future positions",
        "same-layer suffix Q/K/V may be computed in parallel; no serial decode dependence introduced",
        "NSA matrix is selection branch only; compressed and local outputs remain explicit",
        "MoBA current block is compulsory and internally causal, avoiding future-dependent routing",
        "InfLLM-V2 compressed representation used for selection, single main attention output",
        "DSA selection unit is token, not displayed reference block or physical transfer chunk",
        "NOSA CIS fill and query-aware sources distinguished; stable B3 is only a constructed example",
        "physical HBM residency is not used to restrict the model's candidate set",
        "auxiliary index/compression state requirements stated in captions"
    ],
    "layout": {"placed_width_mm": 178, "native_png_width_px": 1080,
               "checks": ["titles separate from group labels and position ticks", "no observed text clipping",
                          "branch arrows and causal hatching visible", "CJK and math symbols render correctly",
                          "unused CIS legend removed from MoBA/InfLLM-V2 page"],
               "paper_embedding": "standalone figures and 178mm booklet reviewed; no manuscript layout changed"},
    "pages": results,
    "booklet_pages": len(book),
    "source_embedding_review": {
        "PNG": "URL-decoded mxGraphModel metadata exactly matches source XML",
        "SVG": "editor metadata normalized; cell IDs, labels, styles and geometry match, preserving waypoint order",
        "PDF": "editable XML is in Subject rather than attachments; page 3 Subject re-encoded to remove extra parenthesis escaping, with page content unchanged"
    },
    "limitations": ["not a measured attention heatmap or softmax mass", "not proof of latency or WCT gains",
                    "toy budgets do not match production models", "green CIS block is not guaranteed permanently fixed"],
}
(OUT / "REVIEW.json").write_text(json.dumps(review, indent=2, ensure_ascii=False))
files = sorted([p for p in HERE.iterdir() if p.is_file()] +
               [p for p in OUT.iterdir() if p.is_file() and p.name != "MANIFEST.json"])
(OUT / "MANIFEST.json").write_text(json.dumps([
    {"path": str(p), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in files], indent=2))
print(json.dumps({"status": "PASS", "pages": len(results), "source_embedding": "PNG, SVG, PDF Subject",
                  "manifest_files": len(files), "review": str(OUT / "REVIEW.json")}, indent=2))
