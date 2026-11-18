#!/usr/bin/env python3
"""Editable Background schematic: DAG invocations, durable history and TP KV.

This is a conceptual example, not a trace or performance measurement.
Export with the native Draw.io CLI; see the review directory for commands.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

FONT = "Linux Libertine O"
INK = "#243746"
EDGE = "#667783"
BLUE = "#367594"
PALE = "#EDF4F8"
AMBER = "#A47A3F"
WARM = "#FBF3E8"
WIDTH, HEIGHT = 480, 570


def build(path: Path) -> None:
    mx = ET.Element("mxfile", host="app.diagrams.net", type="device")
    diagram = ET.SubElement(mx, "diagram", id="serving-model", name="Serving model")
    model = ET.SubElement(diagram, "mxGraphModel", grid="1", gridSize="10",
                          page="1", pageWidth=str(WIDTH), pageHeight=str(HEIGHT),
                          background="#FFFFFF")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def shape(ident, value, x, y, w, h, *, fill="#FFFFFF", stroke=EDGE,
              size=20.6, bold=False, extra=""):
        style = (f"rounded=1;arcSize=10;whiteSpace=wrap;html=0;"
                 f"fontFamily={FONT};fontSize={size};fontColor={INK};"
                 f"fontStyle={int(bold)};align=center;verticalAlign=middle;"
                 f"fillColor={fill};strokeColor={stroke};strokeWidth=1.5;"
                 f"spacing=1;{extra}")
        cell = ET.SubElement(root, "mxCell", id=ident, value=value,
                             style=style, vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w),
                      height=str(h), **{"as": "geometry"})

    def text(ident, value, x, y, w, h, **kw):
        shape(ident, value, x, y, w, h, fill="none", stroke="none", **kw)

    def edge(ident, points, *, dashed=False, arrow="block", color=EDGE):
        cell = ET.SubElement(root, "mxCell", id=ident, value="", edge="1", parent="1",
                             style=f"rounded=0;html=0;strokeColor={color};strokeWidth=1.6;"
                                   f"endArrow={arrow};endSize=5;endFill=1;"
                                   f"dashed={int(dashed)};dashPattern=5 4;")
        geom = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        ET.SubElement(geom, "mxPoint", x=str(points[0][0]), y=str(points[0][1]),
                      **{"as": "sourcePoint"})
        ET.SubElement(geom, "mxPoint", x=str(points[-1][0]), y=str(points[-1][1]),
                      **{"as": "targetPoint"})
        if len(points) > 2:
            arr = ET.SubElement(geom, "Array", **{"as": "points"})
            for x, y in points[1:-1]:
                ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))

    shape("canvas", "", 0, 0, WIDTH, HEIGHT, stroke="none", extra="rounded=0;")
    shape("runtime", "", 6, 32, 468, 172, fill="#F7F9FA", stroke="#AAB5BD")
    text("runtime-title", "Workflow runtime", 8, 0, 330, 30, size=22, bold=True,
         extra="align=left;")

    # Two unfolded, acyclic invocation graphs. A1/A2 and D1/D2 are two turns
    # of the same coordinator agent, not different agents.
    for prefix, ox, title, coord, branches in [
        ("w1", 16, "Workflow 1", "A", ("B", "C")),
        ("w2", 254, "Workflow 2", "D", ("E", "F")),
    ]:
        text(prefix+"-title", title, ox, 38, 204, 26, bold=True)
        shape(prefix+"-start", coord+"1", ox, 94, 36, 32, fill="#E4E9EC")
        shape(prefix+"-upper", branches[0]+"1", ox+82, 72, 40, 32,
              fill=PALE, stroke=BLUE)
        shape(prefix+"-lower", branches[1]+"1", ox+82, 116, 40, 32,
              fill=WARM, stroke=AMBER)
        shape(prefix+"-join", coord+"2", ox+170, 94, 36, 32, fill="#FFFFFF")
        for suffix, cy in [("upper", 88), ("lower", 132)]:
            edge(prefix+"-fork-"+suffix, [(ox+36,110),(ox+55,110),(ox+55,cy),(ox+82,cy)])
            edge(prefix+"-join-"+suffix, [(ox+122,cy),(ox+147,cy),(ox+147,110),(ox+170,110)])
    shape("histories", "Accepted histories + tool results", 20, 163, 440, 30,
          fill="#FFFFFF", stroke="#9DAEB9")

    # Inference requests go down, accepted outputs return to the runtime.
    edge("ready", [(146,204),(146,256)], color=BLUE)
    text("ready-label", "Ready requests", 155, 209, 178, 28,
         extra="align=left;")
    edge("accepted", [(375,271),(450,271),(450,205)], dashed=True)
    text("accepted-label", "Outputs", 363, 228, 82, 28)
    shape("scheduler", "Serving scheduler", 102, 256, 273, 36,
          fill="#F1F4F6", stroke=EDGE, bold=True)
    edge("to-worker0", [(158,292),(158,311),(116,311),(116,334)], color=BLUE)
    edge("to-worker1", [(320,292),(320,311),(356,311),(356,334)], color=BLUE)

    for wi, ox, agents in [(0, 8, "B, E"), (1, 252, "C, F")]:
        ident = f"worker{wi}"
        # This dashed container is the logical worker failure scope in the
        # example. No host-level mapping or failure measurement is assumed.
        shape(ident, "", ox, 334, 220, 154, fill="#FFFFFF", stroke=EDGE,
              extra="dashed=1;dashPattern=5 4;")
        text(ident+"-title", f"Worker {wi}: TP2 replica", ox+4, 337, 212, 28, bold=True)
        for rank, rx in [(0, ox+10), (1, ox+116)]:
            shape(ident+f"-rank{rank}", "", rx, 372, 94, 80,
                  fill="#F3F5F6", stroke="#A2AFB8")
            text(ident+f"-rank-label{rank}", f"Rank {rank}", rx+2, 375, 90, 26)
            shape(ident+f"-kv{rank}", f"KV {agents}", rx+4, 411, 86, 32,
                  fill=PALE if wi == 0 else WARM,
                  stroke=BLUE if wi == 0 else AMBER, extra="rounded=0;")
        text(ident+"-metadata", "KV shards + metadata", ox+4, 455, 212, 28)
        return_path = ([(210,334),(210,305),(230,305),(230,292)] if wi == 0
                       else [(438,334),(438,318),(370,318),(370,292)])
        edge(ident+"-outputs", return_path, dashed=True)

    # A later request uses the cached prefix only while that prefix remains
    # available. This inset specifies no cache hit rate or time/byte ratio.
    text("later-turn", "Next turn of B", 8, 504, 153, 28, bold=True,
         extra="align=left;")
    shape("prefix", "Cached prefix", 162, 504, 185, 30, fill=PALE, stroke=BLUE,
          extra="rounded=0;")
    shape("suffix", "New input", 347, 504, 125, 30, fill=WARM, stroke=AMBER,
          extra="rounded=0;")
    text("reuse", "reuse KV", 165, 538, 180, 28)
    text("prefill", "prefill", 347, 538, 125, 28)

    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(mx)
    ET.indent(tree)
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
