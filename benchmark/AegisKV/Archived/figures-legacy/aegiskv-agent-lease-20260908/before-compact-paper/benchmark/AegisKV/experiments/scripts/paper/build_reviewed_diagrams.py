"""Split conceptual panels into editable, standalone native Draw.io figures."""

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import build_submission_diagrams as old
import pymupdf


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    old.OUT = args.output
    old.system()
    old.workflow()
    for name, remove, change in (
        ("system-overview", (), {"legend": "Solid: KV data | Dashed: control"}),
        ("motivation-workflow", ("heading",), {}),
    ):
        path = args.output / (name + ".drawio")
        tree = ET.parse(path)
        for root in tree.iter("root"):
            for cell in tuple(root):
                if cell.get("id") in remove:
                    root.remove(cell)
                if cell.get("id") in change:
                    cell.set("value", change[cell.get("id")])
        tree.write(path, encoding="utf-8", xml_declaration=True)
    d = old.Diagram("commit-tier-timeline", 365)
    for ident, text, x, width in (
        ("seal", "Seal / reserve", 190, 220),
        ("ack", "HBM copy ACK", 470, 235),
        ("fault", "Source failure", 780, 235),
    ):
        d.node(
            ident,
            text,
            x,
            0,
            width,
            48,
            label=True,
            bold=True,
            stroke=old.RED if ident == "fault" else old.INK,
        )
    d.line("ack-line", 550, 50, 550, 290, color=old.BLUE, dashed=True)
    d.line("fault-line", 855, 50, 855, 290, color=old.RED, dashed=True)
    for i, label in enumerate(("Source", "Peer HBM", "Store DRAM")):
        d.node("row" + str(i), label, 0, 67 + 78 * i, 195, 45, label=True, align="left")
    d.node("source", "Sealed buffers readable", 210, 68, 645, 45, fill="#E8EDF2")
    d.node(
        "hbm-pending", "Pending", 265, 145, 285, 48, stroke=old.BLUE, fill="#EDF5FA", dashed=True
    )
    d.node("hbm-committed", "Committed", 550, 145, 625, 48, stroke=old.BLUE, fill="#DCECF6")
    d.node(
        "dram-pending", "Pending", 265, 223, 590, 48, stroke=old.ORANGE, fill="#FFF5E5", dashed=True
    )
    d.node("dram-aborted", "Aborted", 855, 223, 320, 48, stroke=old.RED, fill="#F8E7E8")
    d.line("axis", 210, 307, 1175, 307, arrow=True)
    d.node("axis-label", "Logical event order", 400, 317, 570, 45, label=True)
    d.write()
    d = old.Diagram("commit-recoverable-prefix", 290)
    for row, tier, color in ((0, "Peer HBM", old.BLUE), (1, "Store DRAM", old.ORANGE)):
        y = 30 + row * 140
        d.node(tier, tier, 0, y, 230, 85, label=True, align="left", bold=True, stroke=color)
        for j in range(3):
            state = (
                "Committed" if j == 0 or row == 0 and j == 1 else "Aborted" if j == 1 else "Absent"
            )
            c = color if state == "Committed" else old.RED if state == "Aborted" else old.GRAY
            d.node(
                f"{row}-{j}",
                f"Chunk {j}\n{state}",
                250 + j * 310,
                y,
                290,
                85,
                stroke=c,
                fill="#F5F8FB",
                dashed=state != "Committed",
            )
    d.write()
    d = old.Diagram("commit-materialize-recompute", 190)
    d.node(
        "backup", "Committed backup\nChunks 0–1", 10, 65, 320, 85, stroke=old.BLUE, fill="#DCECF6"
    )
    d.node("primary", "New primary buffers\nChunks 0–1", 445, 65, 330, 85, fill="#E8EDF2")
    d.node("suffix", "Recompute\nSuffix 2", 900, 65, 290, 85, stroke=old.RED, fill="#F8E7E8")
    d.edge("copy", "backup", "primary", color=old.GREEN)
    d.edge("compute", "primary", "suffix", color=old.RED)
    d.node("copy-label", "KV copy", 305, 15, 175, 40, label=True, stroke=old.GREEN)
    d.write()
    records = []
    for name in (
        "system-overview",
        "motivation-workflow",
        "commit-tier-timeline",
        "commit-recoverable-prefix",
        "commit-materialize-recompute",
    ):
        source = args.output / (name + ".drawio")
        for ext in ("png", "pdf", "svg"):
            output = args.output / (name + "." + ext)
            command = [old.CLI, "-x", "-f", ext, "-e", "-b", "0", "-o", str(output), str(source)]
            if ext == "pdf":
                command.insert(5, "--crop")
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        with pymupdf.open(args.output / (name + ".pdf")) as doc:
            assert len(doc) == 1
        records.append(
            {
                "name": name,
                "type": "editable_native_drawio",
                "evidence": "conceptual_or_trace_reconstruction_not_system_performance",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    (args.output / "diagrams-figure-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Exported {len(records)} standalone editable diagrams")


if __name__ == "__main__":
    main()
