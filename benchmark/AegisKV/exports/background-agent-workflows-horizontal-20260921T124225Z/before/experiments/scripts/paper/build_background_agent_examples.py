#!/usr/bin/env python3
"""Draw illustrative multi-agent examples; no trace or performance data."""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


FONT = "Linux Libertine O"
INK = "#243746"
EDGE = "#627887"
BLUE = "#3377A0"
PALE = "#EAF3F8"
TOOL = "#FBF1E1"
TOOL_EDGE = "#AE844B"


def build(path: Path) -> None:
    mx = ET.Element("mxfile", host="app.diagrams.net", type="device")
    diagram = ET.SubElement(mx, "diagram", id="agent-examples", name="Agent workflows")
    model = ET.SubElement(diagram, "mxGraphModel", grid="1", gridSize="10",
                          page="1", pageWidth="1100", pageHeight="490",
                          background="#FFFFFF")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def shape(ident, value, x, y, w, h, *, parent="1", fill="#FFFFFF",
              stroke=EDGE, size=24, bold=False, extra=""):
        style = (f"rounded=1;arcSize=10;whiteSpace=wrap;html=0;"
                 f"fontFamily={FONT};fontSize={size};fontColor={INK};"
                 f"fontStyle={int(bold)};align=center;verticalAlign=middle;"
                 f"fillColor={fill};strokeColor={stroke};strokeWidth=1.6;"
                 f"spacing=2;{extra}")
        cell = ET.SubElement(root, "mxCell", id=ident, value=value,
                             style=style, vertex="1", parent=parent)
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                      width=str(w), height=str(h), **{"as": "geometry"})
        return cell

    def label(ident, value, x, y, w, h, **kw):
        return shape(ident, value, x, y, w, h, fill="none", stroke="none", **kw)

    def edge(ident, source, target, *, parent="1", ex=.5, ey=1,
             tx=.5, ty=0, points=(), dashed=False, arrow="block", color=EDGE):
        style = (f"rounded=0;html=0;strokeColor={color};strokeWidth=1.8;"
                 f"endArrow={arrow};endSize=6;endFill=1;"
                 f"exitX={ex};exitY={ey};exitPerimeter=0;"
                 f"entryX={tx};entryY={ty};entryPerimeter=0;"
                 f"dashed={int(dashed)};dashPattern=4 3;")
        cell = ET.SubElement(root, "mxCell", id=ident, value="", style=style,
                             edge="1", source=source, target=target, parent=parent)
        geom = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            arr = ET.SubElement(geom, "Array", **{"as": "points"})
            for px, py in points:
                ET.SubElement(arr, "mxPoint", x=str(px), y=str(py))

    shape("canvas", "", 0, 0, 1100, 490, stroke="none", extra="rounded=0;")
    shape("separator", "", 549, 5, 1, 476, fill="#DCE3E8", stroke="none")

    configs = [
        ("code", 0, "(a) Code generation", "Task: Add CSV export",
         "Main agent\nPlan & delegate", "Main agent\nAccept or revise", "Tested patch",
         [("Code agent", "Tool: file editor", "Patch"),
          ("Test agent", "Tool: test runner", "Tests")]),
        ("research", 560, "(b) Deep research", "Task: Compare battery technologies",
         "Lead researcher\nDecompose question", "Lead researcher\nSynthesize evidence", "Cited report",
         [("Technical agent", "Tool: web search", "Performance"),
          ("Cost agent", "Tool: read reports", "Costs")]),
    ]

    for ident, ox, title, task, first, last, output, branches in configs:
        label(f"{ident}-title", title, ox+20, 0, 500, 30, size=26, bold=True)
        label(f"{ident}-task", task, ox+20, 32, 500, 28)
        shape(f"{ident}-plan", first, ox+125, 68, 300, 60, fill=PALE, stroke=BLUE)
        shape(f"{ident}-join", last, ox+125, 386, 300, 60, fill=PALE, stroke=BLUE)
        label(f"{ident}-output", output, ox+135, 459, 280, 28, bold=True)

        for j, (name, tool, result) in enumerate(branches):
            ax = ox + (20 if j == 0 else 310)
            aid = f"{ident}-agent-{j}"
            shape(aid, "", ax, 151, 220, 196, fill="#F7F9FB", stroke="#94A7B4",
                  extra="container=1;pointerEvents=0;")
            label(aid+"-name", name, 5, 4, 210, 27, parent=aid, bold=True)
            shape(aid+"-llm1", "LLM call", 14, 37, 188, 30,
                  parent=aid, fill=PALE, stroke=BLUE)
            shape(aid+"-tool", tool, 14, 83, 188, 30,
                  parent=aid, fill=TOOL, stroke=TOOL_EDGE, size=23)
            shape(aid+"-llm2", "Next LLM call", 14, 129, 188, 30,
                  parent=aid, fill=PALE, stroke=BLUE)
            label(aid+"-history", "Own conversation", 9, 166, 202, 25,
                  parent=aid, size=23)
            edge(aid+"-call-tool", aid+"-llm1", aid+"-tool", parent=aid)
            edge(aid+"-tool-result", aid+"-tool", aid+"-llm2", parent=aid)
            edge(aid+"-repeat", aid+"-llm2", aid+"-llm1", parent=aid,
                 ex=1, ey=.5, tx=1, ty=.5, points=[(212,144),(212,52)], dashed=True)

            # The root edges use page coordinates; child edges use agent-local coordinates.
            branch_center = ax+110
            if ident == "research" or j == 0:
                edge(aid+"-assigned", f"{ident}-plan", aid,
                     ex=.28 if j==0 else .72, points=[(ox+209 if j==0 else ox+341,140),
                                                               (branch_center,140)])
            if ident == "research":
                edge(aid+"-returned", aid, f"{ident}-join", tx=.2 if j==0 else .8,
                     points=[(branch_center,375),(ox+185 if j==0 else ox+365,375)])
                label(aid+"-result", result, ax+120 if j==0 else ax-40,
                      348, 126, 27, size=23)

        if ident == "code":
            # Testing depends on the patch; it is not an independent fork branch.
            edge("code-patch", "code-agent-0", "code-agent-1", ex=1, ey=.5, tx=0, ty=.5)
            label("code-patch-label", "Patch", 240, 216, 70, 27, size=23)
            edge("code-test-report", "code-agent-1", "code-join", tx=.8,
                 points=[(420,375),(365,375)])
            label("code-test-report-label", "Test report", 425, 348, 122, 27, size=23)
            edge("code-revise", "code-join", "code-agent-0", ex=0, ey=.5, tx=0, ty=.5,
                 points=[(7,416),(7,249)], dashed=True)
            label("code-revise-label", "Revise if needed", 14, 355, 225, 27, size=23)

        edge(ident+"-answer", ident+"-join", ident+"-output")

    tree = ET.ElementTree(mx)
    ET.indent(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
