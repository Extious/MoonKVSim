"""AegisKV system overview for the 2026-09-15 paper draft (editable Draw.io + native exports).

Design semantics only: Slack-derived request tiers, the (layer, token-block) KV objects of one
request on the source GPU, their destinations on the fixed Retry DP (Peer HBM) and in the DRAM
pool, and the recovery order after the source GPU fails.  No algorithm is executed here.

Run:  .venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_draft_overview.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[5]
assert (ROOT / "benchmark/AegisKV").is_dir(), ROOT
OUT = ROOT / "benchmark/AegisKV/paper/figures"
TMP = ROOT / "benchmark/AegisKV/paper/figures/.drawio-tmp"
CLI = Path.home() / ".cursor/skills/drawio/scripts/drawio-cli"

INK, GRAY, BLUE, ORANGE, GREEN, RED = "#303943", "#69737E", "#0072B2", "#B86B00", "#007D60", "#B83C46"
PALE, PB, PO, PG, PR, FAINT = "#EEF0F3", "#E4F1F8", "#FFF0DB", "#E9F5EF", "#FBECEE", "#FBF7F0"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Diagram:
    def __init__(self, name, width, height):
        self.name = name
        self.doc = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
        page = ET.SubElement(self.doc, "diagram", id=name, name=name)
        graph = ET.SubElement(page, "mxGraphModel", grid="1", gridSize="10", page="1", pageWidth=str(width),
                              pageHeight=str(height), background="#FFFFFF", math="0")
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.box("canvas", "", 0, 0, width, height, stroke="#FFFFFF")

    def box(self, key, text, x, y, w, h, *, fill="#FFFFFF", stroke=INK, color=None, dashed=False, size=24,
            bold=False, label=False, align="center", valign="middle", shape=None, width=1.6):
        style = (f"rounded=0;whiteSpace=wrap;html=0;strokeWidth={width};strokeColor={stroke};fillColor={fill};"
                 f"fontFamily=DejaVu Sans;fontSize={size};fontColor={color or stroke};align={align};verticalAlign={valign};spacing=2;")
        if label:
            style += "strokeColor=none;fillColor=none;"
        if dashed:
            style += "dashed=1;dashPattern=4 3;"
        if bold:
            style += "fontStyle=1;"
        if shape:
            style += f"shape={shape};"
        c = ET.SubElement(self.root, "mxCell", id=key, value=text, style=style, vertex="1", parent="1")
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), attrib={"as": "geometry"})

    def text(self, key, text, x, y, w, h=34, *, color=INK, bold=False, align="left", size=24, valign="middle"):
        self.box(key, text, x, y, w, h, label=True, stroke=color, bold=bold, align=align, size=size, valign=valign)

    def path(self, key, points, *, color=INK, dashed=False, arrow=True, width=2.3):
        style = (f"edgeStyle=none;rounded=0;strokeColor={color};strokeWidth={width};"
                 f"endArrow={'block' if arrow else 'none'};endSize=7;endFill=1;")
        if dashed:
            style += "dashed=1;dashPattern=5 4;"
        c = ET.SubElement(self.root, "mxCell", id=key, edge="1", parent="1", style=style)
        g = ET.SubElement(c, "mxGeometry", relative="1", attrib={"as": "geometry"})
        ET.SubElement(g, "mxPoint", x=str(points[0][0]), y=str(points[0][1]), attrib={"as": "sourcePoint"})
        ET.SubElement(g, "mxPoint", x=str(points[-1][0]), y=str(points[-1][1]), attrib={"as": "targetPoint"})
        if len(points) > 2:
            arr = ET.SubElement(g, "Array", attrib={"as": "points"})
            for x, y in points[1:-1]:
                ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))

    def write(self, path: Path):
        ET.indent(self.doc)
        path.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(self.doc, encoding="unicode") + "\n")


W, H = 1200, 800
LAYER_FILL = {"app": "#F3F5F7", "ctl": "#EAF1F9", "eng": "#FBF7F0"}


def module(d: Diagram, key, title, x, y, w, h, *, sub=None, stroke=INK, fill="#FFFFFF", title_size=26, sub_size=24):
    """Rounded module box: a bold name, optionally one short gray sub-line.  No prose, no section references."""
    valign = "top" if sub else "middle"
    style = (f"rounded=1;arcSize=10;whiteSpace=wrap;html=0;strokeWidth=1.6;strokeColor={stroke};fillColor={fill};"
             f"fontFamily=DejaVu Sans;fontSize={title_size};fontColor={stroke};align=center;verticalAlign={valign};"
             f"fontStyle=1;spacingTop={14 if sub else 0};")
    c = ET.SubElement(d.root, "mxCell", id=key, value=title, style=style, vertex="1", parent="1")
    ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), attrib={"as": "geometry"})
    if sub:
        d.text(key + "-sub", sub, x + 6, y + h - 44, w - 12, 34, color=GRAY, align="center", size=sub_size)


def circled(d: Diagram, key, n, x, y, color=INK, *, on_line=False):
    """Circled step number; on_line=True paints a white disc so the number can sit on top of an edge."""
    if on_line:
        d.box(key + "-bg", "", x + 2, y + 2, 26, 26, fill="#FFFFFF", stroke="none", shape="ellipse", width=0)
    d.text(key, chr(0x2460 + n - 1), x, y, 30, 30, color=color, align="center", size=26, bold=True)


def draw() -> Diagram:
    """Three-layer architecture with names only; every flow is a numbered arrow explained in the caption.
    Text budget: DejaVu Sans 24 px ~ 13.5 px/char (bold 26 px ~ 15.5), so 24 px on a 1200 px canvas prints at 10 pt."""
    d = Diagram("system-overview", W, H)
    # ---------------------------------------------------------------- layer bands
    bands = [("app", "Application layer", 10, 150), ("ctl", "Control plane", 162, 342), ("eng", "Engine layer", 354, 790)]
    for key, title, y0, y1 in bands:
        d.box(f"band-{key}", "", 8, y0, W - 16, y1 - y0, fill=LAYER_FILL[key], stroke="none", width=0)
        d.text(f"band-{key}-title", title, 20, y0 + 4, 400, 34, bold=True, size=26)

    # ---------------------------------------------------------------- application layer
    module(d, "agent-runtime", "Agent runtime", 15, 56, 290, 76)
    nodes = {"A1": (350, 80), "A2": (450, 42), "A3": (450, 80), "A4": (450, 118), "A5": (550, 80)}
    for key, (x, y) in nodes.items():
        d.box("dag-" + key, key, x, y, 46, 30, fill="#FFFFFF", stroke=INK, shape="ellipse", bold=True, size=24, width=1.4)
    for key in ("A2", "A3", "A4"):
        x, y = nodes[key]
        cy = y + 15
        d.path(f"e-A1-{key}", [(396, 95), (423, 95), (423, cy), (450, cy)], color=GRAY, width=1.5)
        d.path(f"e-{key}-A5", [(496, cy), (523, cy), (523, 95), (550, 95)], color=GRAY, width=1.5)
    d.text("dag-caption", "workflow DAG", 615, 82, 220, 26, color=GRAY, align="left", size=24)

    # ---------------------------------------------------------------- control plane
    module(d, "tracker", "Workflow Tracker", 15, 214, 250, 106)
    module(d, "planner", "Placement Planner", 300, 214, 330, 106, sub="Slack order · L · B")
    module(d, "detector", "Failure Detector", 665, 214, 235, 106)
    module(d, "recovery-mgr", "Recovery Manager", 930, 214, 255, 106)
    d.box("offline", "Offline: block size, K, C", 300, 168, 330, 30, fill="none", stroke=GRAY, color=GRAY, dashed=True,
          size=24, width=1.2)
    d.path("offline-to-planner", [(465, 198), (465, 214)], color=GRAY, width=1.5)

    # ---------------------------------------------------------------- engine layer: source GPU g
    d.box("src-box", "", 15, 404, 585, 302, stroke=GRAY, width=1.4)
    d.box("src-head", "Source GPU g", 15, 404, 585, 32, fill=PALE, stroke=GRAY, bold=True, size=24, align="left")
    d.text("src-fail", "✗", 556, 403, 34, 34, color=RED, bold=True, align="center", size=30)          # the failure event
    module(d, "hotness", "Hotness Counter", 30, 452, 265, 96, sub="block ranking")
    module(d, "backup-agent", "Backup Agent", 320, 452, 265, 96)
    module(d, "sparse-attn", "Sparse attention", 30, 596, 265, 84)
    module(d, "kv-blocks", "KV blocks", 320, 596, 265, 84)
    d.path("attn-to-hot", [(162, 596), (162, 548)], color=GRAY, width=1.5)                   # selected block ids
    d.path("kv-to-backup", [(452, 596), (452, 548)], color=GRAY, width=1.5)                  # sealed blocks

    # ---------------------------------------------------------------- engine layer: Retry DP p(g)
    d.box("rdp-box", "", 640, 404, 545, 302, stroke=GRAY, width=1.4)
    d.box("rdp-head", "Retry DP p(g)", 640, 404, 545, 32, fill=PALE, stroke=GRAY, bold=True, size=24, align="left")
    module(d, "peer-region", "Peer Region", 655, 452, 265, 96, stroke=BLUE)
    module(d, "budget", "Peer Budget", 940, 452, 230, 96, sub="watermark → B")
    module(d, "loader", "Recovery Loader", 655, 596, 265, 84, stroke=RED)
    module(d, "fg-kv", "Foreground KV", 940, 596, 230, 84)
    d.path("fg-to-budget", [(1055, 596), (1055, 548)], color=GRAY, width=1.5)                # occupancy watermark

    # ---------------------------------------------------------------- DRAM pool
    d.box("dram", "Host DRAM pool", 15, 726, 1170, 50, fill=PO, stroke=ORANGE, bold=True, size=26)

    # ---------------------------------------------------------------- flows (numbers explained in the caption)
    d.path("f1", [(250, 132), (250, 214)], color=INK)                                        # submit with DAG metadata
    circled(d, "n1", 1, 258, 150)
    d.path("f1b", [(230, 320), (230, 404)], color=INK)                                       # dispatch to the engine
    circled(d, "n1b", 1, 238, 346)
    d.path("f2", [(265, 267), (300, 267)], color=INK)                                        # Slack snapshot
    circled(d, "n2", 2, 268, 232)
    d.path("f3", [(280, 452), (280, 372), (330, 372), (330, 320)], color=GRAY, dashed=True)  # block ranking (per window)
    circled(d, "n3", 3, 338, 330, color=GRAY)
    d.path("f4", [(1000, 452), (1000, 386), (600, 386), (600, 320)], color=GRAY, dashed=True)  # budget B (per window)
    circled(d, "n4", 4, 608, 330, color=GRAY)
    d.path("f5", [(450, 320), (450, 452)], color=INK)                                        # placement plan
    circled(d, "n5", 5, 458, 346)
    d.path("f6", [(585, 495), (655, 495)], color=BLUE)                                       # Peer copy
    circled(d, "n6", 6, 605, 460, color=BLUE)
    d.path("f7", [(585, 528), (620, 528), (620, 726)], color=ORANGE)                         # DRAM copy
    circled(d, "n7", 7, 605, 630, color=ORANGE, on_line=True)
    d.path("f8", [(900, 267), (930, 267)], color=RED, dashed=True)                           # failure -> recovery manager
    circled(d, "n8", 8, 900, 232, color=RED)
    d.path("f9", [(1057, 320), (1057, 404)], color=RED, dashed=True)                         # parallel retries on p(g)
    circled(d, "n9", 9, 1065, 346, color=RED)
    d.path("f9-peer", [(787, 548), (787, 596)], color=RED, dashed=True)                      # zero-copy read of Peer Region
    d.path("f9-dram", [(787, 726), (787, 680)], color=RED, dashed=True)                      # preload + demand fetch from DRAM
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    d = draw()
    source = OUT / "system-overview.drawio"
    d.write(source)
    tree = ET.parse(source)
    cells = list(tree.iter("mxCell"))
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    assert all(c.find("mxGeometry") is not None for c in cells if c.get("edge") == "1")
    for ext in ("png", "svg", "pdf"):
        dest = TMP / "system-overview-native.pdf" if ext == "pdf" else OUT / f"system-overview.{ext}"
        cmd = [str(CLI), "-x", "-f", ext, "-e", "-b", "0", "-o", str(dest), str(source)]
        if ext == "pdf":
            cmd.insert(5, "--crop")
        if ext == "png":
            cmd[5:5] = ["-s", "1.5"]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    with pymupdf.open(TMP / "system-overview-native.pdf") as src:
        target = pymupdf.open()
        page = target.new_page(width=504, height=src[0].rect.height * 504 / src[0].rect.width)
        page.show_pdf_page(page.rect, src, 0)
        target.set_metadata({"title": "AegisKV System Overview (draft 2026-09-17)",
                             "subject": "Design: Slack order, offline block size and K, per-window L and Peer budget, online block identity"})
        target.embfile_add("system-overview.drawio", source.read_bytes())
        target.save(OUT / "system-overview.pdf", garbage=4, deflate=True, no_new_id=True)
    with pymupdf.open(OUT / "system-overview.pdf") as doc:
        assert len(doc) == 1 and abs(doc[0].rect.width - 504) < .01
        doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(OUT / "system-overview-pdf-preview.png")
        spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        min_font = min(s["size"] for s in spans)
        oob = [s["text"] for s in spans if not (s["bbox"][0] >= -.5 and s["bbox"][1] >= -.5 and s["bbox"][2] <= doc[0].rect.width + .5 and s["bbox"][3] <= doc[0].rect.height + .5)]
        record = dict(name="system-overview", evidence="design", width_in=7, height_in=round(doc[0].rect.height / 72, 3),
                      min_font_pt=round(min_font, 2), out_of_page_text=oob,
                      generator=str(Path(__file__).relative_to(ROOT)),
                      files={ext: sha(OUT / f"system-overview.{ext}") for ext in ("pdf", "svg", "png", "drawio")},
                      note="Three-layer architecture with module names only; the nine numbered flows, the colours and the "
                           "failure mark on the source GPU are explained in the Figure 5 caption. Normal path 1-7: submit/dispatch, "
                           "Slack snapshot, per-window block ranking, per-window Peer budget B from the watermark, placement plan "
                           "(tier, L(Lr), block identities), Peer copy, DRAM copy. Failure path 8-9: detector -> recovery manager, "
                           "parallel retries on p(g) reading the Peer Region zero-copy and the DRAM pool via preload + demand fetch. "
                           "Offline tables (block size, K_l, C) feed the planner. Design semantics only; no algorithm is executed. "
                           "Visual review of the native PNG/PDF is required after regeneration.")
    (OUT / "system-overview-manifest.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"height_in": record["height_in"], "min_font_pt": record["min_font_pt"], "out_of_page_text": oob}))


if __name__ == "__main__":
    main()
