"""Compact AegisKV overview with editable resource and KV-object topology.

Draws design semantics only. No algorithm implementation or experiments run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

import build_paper_story_diagrams as native
from build_paper_story_diagrams import Diagram, INK, GRAY, BLUE, ORANGE, GREEN, RED, PALE, PB, PO, PG
from paper_paths import ROOT
from three_system_data import sha


def draw():
    d = Diagram("system-overview", 785)
    d.text("workflow-title", "Workflow context", 18, 5, 294, bold=True)
    for key, y, color, fill in [("A", 61, ORANGE, PO), ("B", 129, BLUE, PB)]:
        d.box("dag-" + key, key, 26, y, 54, 44, fill=fill, stroke=color, shape="ellipse")
        d.path("dag-edge-" + key, [(80, y + 22), (124, y + 22), (124, 117), (172, 117)], color=GRAY, width=1.7)
    d.box("dag-join", "Join", 172, 95, 85, 44, fill=PALE)
    d.path("state-to-priority", [(257, 117), (296, 117), (296, 73), (335, 73)], dashed=True)
    d.text("priority-title", "Agent priorities", 335, 5, 310, bold=True)
    d.text("priority-detail", "Slack + recovery cost", 335, 53, 328, 40, size=24)
    d.path("priority-admission", [(480, 97), (480, 123)], dashed=True)
    d.text("admission-title", "Per-tier admission", 335, 121, 320, bold=True)
    d.text("admission-detail", "Independent pool decisions", 335, 165, 355, 42, size=24)
    d.path("admission-source", [(480, 210), (480, 230), (176, 230), (176, 280)], dashed=True)

    d.text("controller-title", "Peer HBM control", 708, 5, 473, bold=True)
    d.text("controller-detail", "Headroom + forward latency", 708, 57, 473, 44, size=24)
    d.text("controller-invariant", "Foreground memory first", 708, 104, 473, 38, color=GRAY, size=24)
    d.path("quota-control", [(730, 148), (730, 260)], dashed=True)
    d.path("foreground-feedback", [(800, 260), (800, 148)], dashed=True)
    d.text("quota-label", "Grant /\nrevoke", 606, 207, 113, 50, color=GRAY, size=24, align="right")
    d.text("feedback-label", "Observe", 817, 187, 157, 43, color=GRAY, size=24)

    # Three columns express source, independent replica tiers, and failover.
    for key, title, x, y, width, height in [
        ("source", "Source worker", 18, 280, 312, 268),
        ("peer", "Peer worker", 470, 260, 370, 270),
        ("dram", "DRAM store", 470, 585, 370, 155),
        ("recovery", "Recovery worker", 935, 400, 247, 293),
    ]:
        d.box(key + "-boundary", "", x, y, width, height, stroke=GRAY)
        d.box(key + "-heading", title, x, y, width, 42, fill=PALE, stroke=GRAY, bold=True, size=24 if key == "recovery" else 26)

    d.text("source-hbm", "Primary HBM", 34, 331, 280, 36, size=24)
    d.chunks("source-prefix", ["C0", "C1"], 36, 375, cell=83, height=42)
    d.chunks("source-active", ["C2"], 220, 375, cell=83, height=42)
    d.text("source-sealed", "Sealed prefix", 30, 428, 187, 40, size=24, align="center")
    d.text("source-active-label", "Active", 213, 428, 97, 40, size=24, align="center")
    d.text("source-shared", "A and B share C0", 34, 486, 279, 40, size=24)

    d.text("peer-foreground", "Foreground HBM", 485, 307, 338, 36, size=24)
    d.chunks("peer-foreground-chunks", ["P0", "P1"], 486, 350, cell=77, height=39)
    d.box("foreground-reserve", "Reserve", 658, 350, 166, 39, stroke=GREEN, fill=PG, size=24)
    d.text("peer-backup", "Revocable backup HBM", 485, 398, 341, 37, color=BLUE, size=24)
    d.chunks("peer-prefix", ["C0", "C1"], 486, 441, cell=96, height=40, color=BLUE, fill=PB)
    d.text("peer-committed", "Readable after copy ACK", 485, 488, 341, 34, color=BLUE, size=24)

    d.chunks("dram-prefix", ["C0", "C1"], 486, 635, cell=96, height=40, color=ORANGE, fill=PO)
    d.text("dram-committed", "Readable after copy ACK", 485, 690, 341, 34, color=ORANGE, size=24)

    # Both copies originate at the primary; the DRAM path is not write-back.
    d.path("source-to-peer", [(330, 396), (420, 396), (420, 461), (486, 461)], color=BLUE)
    d.text("peer-copy-label", "Peer\ncopy", 341, 310, 116, 66, color=BLUE, size=24, align="center")
    d.path("source-to-dram", [(330, 490), (414, 490), (414, 655), (486, 655)], color=ORANGE)
    d.text("dram-copy-label", "DRAM\ncopy", 283, 578, 123, 68, color=ORANGE, size=24, align="center")

    d.text("failure-condition", "On source failure", 935, 335, 247, 45, color=RED, size=24, bold=True)
    d.text("recovery-hbm", "New primary HBM", 946, 451, 223, 37, size=24)
    d.chunks("restored-prefix", ["C0", "C1"], 950, 501, cell=103, height=43, color=GREEN, fill=PG)
    d.text("restored-label", "Loaded prefix", 950, 553, 215, 39, color=GREEN, size=24, align="center")
    d.chunks("recomputed-suffix", ["C2"], 950, 613, cell=65, height=43)
    d.text("recomputed-label", "Recompute", 1025, 615, 146, 38, size=24)
    # Alternative readable replicas restore the same logical C0/C1 identity.
    d.path("peer-to-recovery", [(840, 461), (887, 461), (887, 515), (935, 515)], color=GREEN)
    d.path("dram-to-recovery", [(840, 655), (887, 655), (887, 535), (935, 535)], color=GREEN)
    d.text("restore-label", "Restore", 841, 390, 91, 42, color=GREEN, size=24, align="center")

    d.text("legend", "Colored arrows: KV transfer     |     Dashed arrows: control", 18, 750, 1164, 34, size=24, align="center")
    # Attach important data edges to the real editable source/destination cells.
    anchors = {
        "source-to-peer": ("source-boundary", "peer-prefix-0", 1, 116 / 268, 0, .5),
        "source-to-dram": ("source-boundary", "dram-prefix-0", 1, 210 / 268, 0, .5),
        "peer-to-recovery": ("peer-boundary", "recovery-boundary", 1, 201 / 270, 0, 115 / 293),
        "dram-to-recovery": ("dram-boundary", "recovery-boundary", 1, 70 / 155, 0, 135 / 293),
    }
    for c in d.root:
        if c.get("id") in anchors:
            src, dst, ex, ey, ix, iy = anchors[c.get("id")]
            c.set("source", src)
            c.set("target", dst)
            c.set("style", c.get("style") + f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;exitPerimeter=0;entryX={ix};entryY={iy};entryDx=0;entryDy=0;entryPerimeter=0;")
    d.write()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/aegiskv-revision-20260909")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    native.OUT = out
    draw()
    source = out / "system-overview.drawio"
    tree = ET.parse(source)
    cells = list(tree.iter("mxCell"))
    ids = [c.get("id") for c in cells]
    assert len(ids) == len(set(ids))
    assert all(c.find("mxGeometry") is not None for c in cells if c.get("edge") == "1")
    labels = "\n".join(c.get("value", "") for c in cells)
    assert "joint" not in labels.lower()
    expected_edges = ["source-to-peer", "source-to-dram", "peer-to-recovery", "dram-to-recovery", "quota-control", "foreground-feedback"]
    assert all(k in ids for k in expected_edges)
    temp = ROOT / "tmp/pdfs/revised-overview-native"
    temp.mkdir(parents=True, exist_ok=True)
    for ext in ["png", "svg", "pdf"]:
        dest = temp / "system-overview-native.pdf" if ext == "pdf" else out / ("system-overview." + ext)
        command = [native.CLI, "-x", "-f", ext, "-e", "-b", "0", "-o", str(dest), str(source)]
        if ext == "pdf":
            command.insert(5, "--crop")
        if ext == "png":
            command[5:5] = ["-s", "1.5"]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    with pymupdf.open(temp / "system-overview-native.pdf") as src:
        target = pymupdf.open()
        page = target.new_page(width=504, height=src[0].rect.height * 504 / src[0].rect.width)
        page.show_pdf_page(page.rect, src, 0)
        target.set_metadata({"title": "AegisKV System Overview", "subject": "Design: independent tier copies, committed-prefix recovery, and foreground-aware peer memory"})
        target.embfile_add("system-overview.drawio", source.read_bytes())
        target.save(out / "system-overview.pdf", garbage=4, deflate=True, no_new_id=True)
    with pymupdf.open(out / "system-overview.pdf") as doc:
        assert len(doc) == 1 and abs(doc[0].rect.width - 504) < .01
        doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(out / "system-overview-pdf-preview.png")
        spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        min_font = min(s["size"] for s in spans)
        assert min_font >= 9.9
        assert all(s["bbox"][0] >= -.5 and s["bbox"][1] >= -.5 and s["bbox"][2] <= doc[0].rect.width + .5 and s["bbox"][3] <= doc[0].rect.height + .5 for s in spans)
        record = dict(name="system-overview", evidence="design", width_in=7, height_in=doc[0].rect.height / 72,
            min_font_pt=min_font, sources=[str(Path(__file__).relative_to(ROOT))],
            files={ext: sha(out / ("system-overview." + ext)) for ext in ["pdf", "svg", "png", "drawio"]},
            reference_figures=[
                dict(paper="Mooncake, FAST 2025 Best Paper", figure="Fig. 2, PDF p. 3", url="https://www.usenix.org/system/files/fast25-qin.pdf", borrowed="Resource-local responsibilities and distinct cache-tier boundaries"),
                dict(paper="Enso, OSDI 2023 Best Paper", figure="Figs. 1 and 3, PDF pp. 4-5", url="https://www.usenix.org/system/files/osdi23-sadok.pdf", borrowed="Concrete named objects carried through operations")],
            checks={"xml_unique_ids": True, "edge_geometry_present": True, "same_C0_C1_identity": True,
                "independent_source_owned_copies": True, "no_joint_value_claim": True, "embedded_editable_xml": True,
                "one_page_7_inch_pdf": True, "text_within_page": True, "actual_png_pdf_visual_review": "PENDING"},
            note="Replica drawings illustrate eligible committed copies, not guaranteed equal coverage or simultaneous availability. Recovery may use either surviving compatible prefix. Reserved/foreground/backup geometry is qualitative, not a capacity measurement. Algorithm 2 internals remain deferred.")
    (out / "overview-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(out), "size_in": [7, record["height_in"]], "minimum_font_pt": min_font}))


if __name__ == "__main__":
    main()
