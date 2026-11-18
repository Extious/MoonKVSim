#!/usr/bin/env python3
"""Illustrative left-to-right multi-agent workflows, without timing data."""
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
WIDTH, HEIGHT = 640, 730


def build(path: Path) -> None:
    mx = ET.Element("mxfile", host="app.diagrams.net", type="device")
    diagram = ET.SubElement(mx, "diagram", id="agent-examples", name="Agent workflows")
    model = ET.SubElement(diagram, "mxGraphModel", grid="1", gridSize="10",
                          page="1", pageWidth=str(WIDTH), pageHeight=str(HEIGHT),
                          background="#FFFFFF")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def shape(ident, value, x, y, w, h, *, parent="1", fill="#FFFFFF",
              stroke=EDGE, size=27, bold=False, extra=""):
        style = (f"rounded=1;arcSize=10;whiteSpace=wrap;html=0;"
                 f"fontFamily={FONT};fontSize={size};fontColor={INK};"
                 f"fontStyle={int(bold)};align=center;verticalAlign=middle;"
                 f"fillColor={fill};strokeColor={stroke};strokeWidth=1.5;"
                 f"spacing=1;{extra}")
        cell = ET.SubElement(root, "mxCell", id=ident, value=value,
                             style=style, vertex="1", parent=parent)
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y),
                      width=str(w), height=str(h), **{"as": "geometry"})
        return cell

    def label(ident, value, x, y, w, h, **kw):
        return shape(ident, value, x, y, w, h, fill="none", stroke="none", **kw)

    def edge(ident, source, target, *, parent="1", ex=1, ey=.5,
             tx=0, ty=.5, points=(), arrow="block", color=EDGE):
        style = (f"rounded=0;html=0;strokeColor={color};strokeWidth=1.6;"
                 f"endArrow={arrow};endSize=5;endFill=1;"
                 f"exitX={ex};exitY={ey};exitPerimeter=0;"
                 f"entryX={tx};entryY={ty};entryPerimeter=0;")
        cell = ET.SubElement(root, "mxCell", id=ident, value="", style=style,
                             edge="1", source=source, target=target, parent=parent)
        geom = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            arr = ET.SubElement(geom, "Array", **{"as": "points"})
            for px, py in points:
                ET.SubElement(arr, "mxPoint", x=str(px), y=str(py))

    shape("canvas", "", 0, 0, WIDTH, HEIGHT, stroke="none", extra="rounded=0;")
    # Different lengths and starting positions denote unsynchronized request sequences,
    # not measured durations. Labels identify each agent without a repeated table grid.
    code = [
        ("API agent", 100, ["Read", "Edit", "Lint"]),
        ("UI agent", 126, ["Read", "Edit"]),
        ("Test agent", 112, ["Read", "Edit"]),
        ("Docs agent", 151, ["Read"]),
    ]
    research = [
        ("Technical agent", 100, ["Search", "Read", "Read"]),
        ("Cost agent", 138, ["Search"]),
        ("Safety agent", 117, ["Search", "Read"]),
        ("Supply agent", 156, ["Read"]),
    ]
    configs = [
        ("code", 0, "(a) Code generation: CSV export", "Main\nPlan",
         "Main\nMerge\n& test", "Patch", code),
        ("research", 350, "(b) Deep research: batteries", "Lead\nPlan",
         "Lead\nWrite", "Report", research),
    ]
    tool_widths = {"Read": 64, "Edit": 60, "Lint": 54, "Search": 78}
    for ident, oy, title, first, last, output, branches in configs:
        label(ident+"-title", title, 4, oy, 630, 34, size=28, bold=True,
              extra="align=left;")
        cy = oy + 194
        shape(ident+"-plan", first, 4, cy-35, 66, 70, fill="#F0F2F4", stroke=EDGE)
        end_height = 98 if ident == "code" else 70
        shape(ident+"-join", last, 548, cy-end_height/2, 88, end_height,
              fill="#F0F2F4", stroke=EDGE)
        label(ident+"-output", output, 548, cy+end_height/2+3, 88, 32)
        for name, x in [("fork", 84), ("merge", 536)]:
            shape(ident+"-"+name, "", x-2, cy-2, 4, 4,
                  fill=EDGE, stroke="none", extra="shape=ellipse;")
        edge(ident+"-delegate", ident+"-plan", ident+"-fork", arrow="none")
        edge(ident+"-aggregate", ident+"-merge", ident+"-join")
        for j, (name, start_x, tool_calls) in enumerate(branches):
            aid = f"{ident}-agent-{j}"
            ay = oy+38+j*72
            events = []
            for k, tool in enumerate(tool_calls):
                events.extend([(f"R{k+1}", 38, True), (tool, tool_widths[tool], False)])
            events.append((f"R{len(tool_calls)+1}", 38, True))
            row_width = sum(w for _, w, _ in events) + 11*(len(events)-1)
            shape(aid, "", start_x, ay, row_width, 68, fill="none", stroke="none",
                  extra="container=1;pointerEvents=0;")
            label(aid+"-name", name, 0, 0, 240, 30, parent=aid, bold=True,
                  extra="align=left;")
            x = 0
            for k, (value, width, is_llm) in enumerate(events):
                node = aid+f"-event-{k}"
                shape(node, value, x, 32, width, 36, parent=aid,
                      fill=PALE if is_llm else TOOL,
                      stroke=BLUE if is_llm else TOOL_EDGE,
                      extra="" if is_llm else "rounded=0;")
                if k:
                    edge(aid+f"-step-{k}", aid+f"-event-{k-1}", node, parent=aid)
                x += width+11
            # Branches fork at assignment and join only after their respective last request.
            edge(aid+"-assigned", ident+"-fork", aid+"-event-0", ex=.5, ey=.5,
                 points=[(84, ay+50)])
            edge(aid+"-returned", aid+f"-event-{len(events)-1}", ident+"-merge",
                 tx=.5, ty=.5, points=[(536, ay+50)], arrow="none")

    # Shared key; numbered rounded requests and named square tools remain distinct in grayscale.
    shape("llm-key", "R1", 96, 692, 38, 36, fill=PALE, stroke=BLUE)
    label("llm-key-text", "LLM request", 141, 694, 153, 32, extra="align=left;")
    shape("tool-key", "", 340, 701, 21, 19, fill=TOOL, stroke=TOOL_EDGE,
          extra="rounded=0;")
    label("tool-key-text", "Tool call", 370, 694, 150, 32, extra="align=left;")

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
