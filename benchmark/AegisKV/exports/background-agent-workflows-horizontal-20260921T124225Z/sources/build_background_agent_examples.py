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
WIDTH, HEIGHT = 1220, 680


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
              stroke=EDGE, size=25, bold=False, extra=""):
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
    # Each LLM result causes a tool call; its returned data extends the next request.
    code = [
        ("API\nagent", ["Inspect", "Read\nfiles", "Code", "Edit\nfiles", "Review"]),
        ("UI\nagent", ["Inspect", "Read\nfiles", "Code", "Edit\nfiles", "Review"]),
        ("Test\nagent", ["Plan tests", "Read\nspec", "Author", "Edit\ntests", "Review"]),
        ("Docs\nagent", ["Outline", "Read\nspec", "Draft", "Edit\ndocs", "Review"]),
    ]
    research = [
        ("Technical\nagent", ["Plan", "Web\nsearch", "Assess", "Read\npapers", "Report"]),
        ("Cost\nagent", ["Plan", "Web\nsearch", "Assess", "Read\nreports", "Report"]),
        ("Safety\nagent", ["Plan", "Web\nsearch", "Assess", "Read\nstudies", "Report"]),
        ("Supply\nagent", ["Plan", "Web\nsearch", "Assess", "Read\nreports", "Report"]),
    ]
    configs = [
        ("code", 0, "(a) Code generation: add CSV export", "Main agent\nPlan tasks",
         "Main agent\nMerge & test", "CSV patch", code),
        ("research", 350, "(b) Deep research: compare battery technologies", "Lead agent\nPlan tasks",
         "Lead agent\nSynthesize", "Cited report", research),
    ]
    for ident, oy, title, first, last, output, branches in configs:
        label(ident+"-title", title, 4, oy, 842, 32, size=27, bold=True,
              extra="align=left;")
        cy = oy + 184
        shape(ident+"-plan", first, 4, cy-39, 134, 78, fill="#F0F2F4", stroke=EDGE)
        shape(ident+"-join", last, 1030, cy-39, 186, 78, fill="#F0F2F4", stroke=EDGE)
        label(ident+"-output", output, 1030, cy+45, 186, 30, bold=True)
        # Explicit junctions keep the common trunk single and arrowheads away from labels.
        for name, x in [("fork", 159), ("merge", 1004)]:
            shape(ident+"-"+name, "", x-2, cy-2, 4, 4,
                  fill=EDGE, stroke="none", extra="shape=ellipse;")
        edge(ident+"-delegate", ident+"-plan", ident+"-fork", arrow="none")
        edge(ident+"-aggregate", ident+"-merge", ident+"-join")
        for j, (name, events) in enumerate(branches):
            aid = f"{ident}-agent-{j}"
            ay = oy+44+j*72
            shape(aid, "", 176, ay, 800, 64, fill="#F7F9FB", stroke="#B1BEC8",
                  extra="container=1;pointerEvents=0;")
            label(aid+"-name", name, 3, 2, 134, 60, parent=aid, bold=True)
            for k, value in enumerate(events):
                is_llm = k % 2 == 0
                node = aid+f"-event-{k}"
                shape(node, f"LLM {k//2+1}\n{value}" if is_llm else value,
                      142+k*132, 2, 112, 60, parent=aid,
                      fill=PALE if is_llm else TOOL,
                      stroke=BLUE if is_llm else TOOL_EDGE,
                      extra="" if is_llm else "rounded=0;")
                if k:
                    edge(aid+f"-step-{k}", aid+f"-event-{k-1}", node, parent=aid)
            # External edges carry task assignment / agent outputs, not shared conversation or KV.
            edge(aid+"-assigned", ident+"-fork", aid, ex=.5, ey=.5,
                 points=[(159, ay+32)])
            edge(aid+"-returned", aid, ident+"-merge", tx=.5, ty=.5,
                 points=[(1004, ay+32)], arrow="none")

    # One shared key; explicit LLM labels and square tool boxes also work in grayscale.
    shape("llm-key", "", 867, 7, 21, 19, fill=PALE, stroke=BLUE)
    label("llm-key-text", "LLM request", 895, 1, 147, 31,
          extra="align=left;")
    shape("tool-key", "", 1050, 7, 21, 19, fill=TOOL, stroke=TOOL_EDGE,
          extra="rounded=0;")
    label("tool-key-text", "Tool call", 1078, 1, 138, 31,
          extra="align=left;")

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
