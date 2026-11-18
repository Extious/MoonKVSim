#!/usr/bin/env python3
"""Artifact checks accompanying the recorded manual final-size inspection."""
from pathlib import Path
from urllib.parse import unquote
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import pymupdf
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
OUT = REPO / "output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page"
names = ["01-nsa-prefill", "02-moba-prefill", "03-infllmv2-prefill", "04-dsa-prefill", "05-nosa-prefill"]
expected_tabs = ["1 · NSA", "2 · MoBA", "3 · InfLLM-V2", "4 · DSA", "5 · NOSA"]
main_source = ET.parse(HERE / "native-sparse-prefill.drawio").getroot()
assert [p.get("name") for p in main_source] == expected_tabs

def cell_signature(node):
    # Native SVG export normalizes editor metadata and drops zero-valued x/y.
    attrs = dict(node.attrib)
    if node.tag in {"mxGeometry", "mxPoint"}:
        for key in {"x", "y", "width", "height"} & attrs.keys():
            attrs[key] = format(float(attrs[key]), ".15g")
    attrs = {k: v for k, v in attrs.items() if not (k in {"x", "y"} and v == "0")}
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
    text = doc[0].get_text()
    assert "Query" in text
    assert all(re.search(rf"\bq{pos}\b", text) for pos in range(25, 33)), name
    assert not re.search(r"\bq[1-8]\b", text), name
    results.append({"page": name, "png_px": list(png.size), "png_embedded_source_matches": True,
                    "svg_embedded_cell_labels_styles_geometry_match": True, "pdf_subject_embedded_source_matches": True,
                    "native_png_visually_reviewed": True, "pdf_at_178mm_visually_reviewed": True})

book = pymupdf.open(OUT / "native-sparse-prefill-178mm.pdf")
assert len(book) == 5
assert all(abs(p.rect.width/72*25.4 - 178) < 0.01 for p in book)
static = json.loads((OUT / "schematic-masks.json").read_text())
for name, data in static["masks"].items():
    for pos, row in zip(data["row_query_positions"], data["cells"]):
        assert all(v == "future" for v in row[pos:])
        assert all(v != "future" for v in row[:pos])
        if name == "dsa":
            assert row.count("selected") == 6
        if name == "nsa-window":
            window = static["nsa_window"]["tokens_including_current"]
            assert [j for j, v in enumerate(row, 1) if v == "window"] == list(range(max(1, pos-window+1), pos+1))
    if name in {"moba", "infllm-v2", "nosa"}:
        for pos, row in zip(data["row_query_positions"], data["cells"]):
            assert row[pos-1] == "forced"

review = {
    "evidence": "algorithm mechanism illustration; constructed selections and derived causal window; no new model execution",
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
        "NSA has separate selected-attention and sliding-window matrices on the same page; each has its own legend",
        "NSA local window contains exactly four tokens including the current position and moves one token per query",
        "NSA reference block boundaries do not determine the token-granular local window; no top-k or score threshold is applied",
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
                          "one algorithm per Draw.io tab and per PDF page; context repeated on every page",
                          "each legend includes only categories used by that algorithm"],
               "paper_embedding": "standalone figures and 178mm booklet reviewed; no manuscript layout changed"},
    "pages": results,
    "booklet_pages": len(book),
    "drawio_tabs": expected_tabs,
    "query_labels": "absolute positions q25 through q32 on every page; no q1 through q8 aliases",
    "source_embedding_review": {
        "PNG": "URL-decoded mxGraphModel metadata exactly matches source XML",
        "SVG": "editor metadata normalized; cell IDs, labels, styles and geometry match, preserving waypoint order",
        "PDF": "editable XML is in Subject rather than attachments; Subject fully percent-encoded to preserve exact source"
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
