"""Editable AegisKV overview; export with the official Draw.io CLI.

This is a logical design diagram, not a deployment or implementation claim.
The independent Annotations layer contains the four paper cross-reference badges.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "benchmark/AegisKV/paper/figures"
W, H = 1200, 930
INK, GRAY, BLUE, GOLD, RED = "#243443", "#637481", "#2174A5", "#A46D20", "#B34852"


def build():
    doc = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
    page = ET.SubElement(doc, "diagram", id="aegiskv-overview", name="System overview")
    model = ET.SubElement(page, "mxGraphModel", page="1", pageScale="1", pageWidth=str(W),
                          pageHeight=str(H), background="#ffffff", grid="1", gridSize="10")
    graph = ET.SubElement(model, "root")
    ET.SubElement(graph, "mxCell", id="0")
    ET.SubElement(graph, "mxCell", id="1", value="Architecture", parent="0")
    ET.SubElement(graph, "mxCell", id="annotations", value="Paper annotations", parent="0")
    base = ("html=0;whiteSpace=wrap;align=center;verticalAlign=middle;spacing=0;"
            f"fontFamily=Helvetica;fontSize=25;fontColor={INK};")

    def box(ident, value, x, y, w, h, style="", parent="1"):
        c = ET.SubElement(graph, "mxCell", id=ident, value=value, vertex="1", parent=parent,
                          style=base + style)
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
        return ident

    def text(ident, value, x, y, w, h=38, style="", parent="1"):
        return box(ident, value, x, y, w, h, "fillColor=none;strokeColor=none;" + style, parent)

    def edge(ident, source, target, *, color=GRAY, dashed=False, points=(),
             exit=(.5, 1), entry=(.5, 0), both=False, arrow="block", width=2.4):
        style = (f"html=0;rounded=0;strokeColor={color};strokeWidth={width};endArrow={arrow};"
                 f"endFill=1;endSize=8;exitX={exit[0]};exitY={exit[1]};exitPerimeter=0;"
                 f"entryX={entry[0]};entryY={entry[1]};entryPerimeter=0;"
                 "labelBackgroundColor=#ffffff;jumpStyle=arc;jumpSize=8;")
        if dashed:
            style += "dashed=1;dashPattern=6 4;"
        if both:
            style += "startArrow=block;startFill=1;startSize=8;"
        c = ET.SubElement(graph, "mxCell", id=ident, edge="1", parent="1", source=source, target=target, style=style)
        geom = ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            pts = ET.SubElement(geom, "Array", **{"as": "points"})
            for x, y in points:
                ET.SubElement(pts, "mxPoint", x=str(x), y=str(y))

    box("canvas", "", 0, 0, W, H, "fillColor=#ffffff;strokeColor=none;pointerEvents=0;")
    # Three open bands establish ownership; only the DP memory domains get frames.
    box("applications", "", 16, 16, 1168, 166, "fillColor=#F1F6F9;strokeColor=none;rounded=1;arcSize=8;")
    box("control", "", 16, 216, 1168, 250, "fillColor=#F5F4F8;strokeColor=none;rounded=1;arcSize=6;")
    box("engines", "", 16, 524, 1168, 390, "fillColor=#F6F8F9;strokeColor=none;rounded=1;arcSize=5;")
    text("applications-title", "Applications", 38, 30, 260, style="align=left;fontSize=32;fontStyle=1;")
    text("request", "LLM requests", 45, 93, 230, 44, "fontStyle=1;")
    text("request-meta", "Workflow + node IDs", 37, 139, 280, 30)
    text("dag-title", "Agent workflow", 432, 33, 250, 34, "fontStyle=1;")
    circle = "ellipse;fillColor=#ffffff;strokeColor=#6C8799;strokeWidth=2;"
    for name, x, y in [("start", 405, 105), ("a1", 540, 78), ("a2", 540, 130), ("join", 675, 105)]:
        box(name, "", x, y, 32, 32, circle)
    for name, src, dst in [("e1", "start", "a1"), ("e2", "start", "a2"), ("e3", "a1", "join"), ("e4", "a2", "join")]:
        edge(name, src, dst, exit=(1, .5), entry=(0, .5), width=2)
    text("app-description", "Dependencies\n+ progress", 813, 76, 294, 76, "align=left;")
    text("control-title", "Control plane", 38, 223, 263, 40, "align=left;fontSize=32;fontStyle=1;")
    box("router", "Router", 46, 307, 214, 75,
        "rounded=1;arcSize=12;fillColor=#E4EEF5;strokeColor=#93A8B7;strokeWidth=1.5;fontStyle=1;fontSize=28;")
    text("router-detail", "Load + KV locality", 32, 397, 242, 35)
    text("controller-title", "AegisKV Controller", 573, 223, 580, 40, "align=left;fontSize=32;fontStyle=1;")
    text("tracker", "Workflow\nTracker", 342, 299, 226, 72, "fontSize=28;fontStyle=1;")
    box("planner", "", 623, 291, 285, 142,
        "rounded=1;arcSize=6;fillColor=#E4EAF4;strokeColor=none;container=1;collapsible=0;")
    text("planner-name", "KV Placement\nPlanner", 0, 9, 285, 76,
         "fontSize=28;fontStyle=1;", "planner")
    text("planner-detail", "Placement + transfer", 0, 103, 285, 34, parent="planner")
    box("recovery", "", 944, 299, 229, 133,
        "fillColor=none;strokeColor=none;container=1;collapsible=0;")
    text("recovery-name", "Recovery\nManager", 0, 0, 229, 72,
         "fontSize=28;fontStyle=1;", "recovery")
    text("recovery-detail", "Health + retry", 0, 95, 229, 34, parent="recovery")
    text("tracker-detail", "DAG slack", 342, 397, 226, 34)
    edge("slack", "tracker", "planner", exit=(1, .5), entry=(0, .31))
    edge("dag-metadata", "a2", "tracker", dashed=True,
         exit=(.5, 1), entry=(.5, 0), points=[(556, 195), (455, 195)])
    edge("submit", "request-meta", "router", color=INK, exit=(1, .5), entry=(1, .35),
         points=[(316, 154), (316, 333)])
    # DP domains are symmetrical. Each has a runtime adapter and a transfer connector.
    for dp, x in [(0, 42), (1, 646)]:
        group = f"dp{dp}"
        box(group, "", x, 559, 512, 231,
            "rounded=1;arcSize=5;fillColor=#ffffff;strokeColor=#B4C0C9;strokeWidth=1.7;container=1;collapsible=0;")
        text(f"dp-title-{dp}", f"DP{dp}", 23, 9, 105, 38,
             "align=left;fontSize=31;fontStyle=1;", group)
        text(f"adapter{dp}", "Adapter", 193, 10, 190, 40,
             "fontSize=28;fontStyle=1;", group)
        text(f"hbm-title-{dp}", "HBM", 24, 61, 87, 31, "align=left;", group)
        # The smaller Peer region is an illustrative capacity split, not a measured ratio.
        locx, peerx = ((24, 368) if dp == 0 else (144, 24))
        box(f"local{dp}", "Local KV", locx, 101, 344, 58,
            "fillColor=#E5EEE9;strokeColor=#749787;strokeWidth=1.8;fontStyle=1;", group)
        box(f"peer{dp}", "Peer KV", peerx, 101, 120, 58,
            "fillColor=#DBEAF5;strokeColor=#4E85A7;strokeWidth=1.8;", group)
        cx = 275 if dp == 0 else 27
        text(f"connector{dp}", "Connector", cx, 180, 210, 40, "fontStyle=1;", group)
    text("engines-title", "Inference engines", 39, 482, 353, 39,
         "align=left;fontSize=32;fontStyle=1;")
    edge("dispatch", "router", "dp0", color=INK, exit=(0, .5), entry=(.13, 0),
         points=[(28, 344), (28, 541), (109, 541)])
    # Representative control edges, explicitly rooted at the policy component.
    edge("plans", "planner", "adapter1", dashed=True, exit=(.68, 1), entry=(.12, 0),
         points=[(817, 447), (862, 447)])
    text("plans-label", "Plans", 785, 474, 110, 33, "fillColor=#ffffff;")
    edge("telemetry", "adapter1", "planner", dashed=True, exit=(.80, 0), entry=(.90, 1),
         points=[(991, 447), (880, 447)])
    text("status-label", "Ranks / capacity", 883, 515, 218, 33, "fillColor=#ffffff;")
    edge("retry", "recovery", "adapter1", color=RED, dashed=True,
         exit=(.80, 1), entry=(1, .5), points=[(1127.2, 589)])
    text("retry-label", "Retry", 1075, 473, 95, 32, f"fillColor=#ffffff;fontColor={RED};")
    # A Connector transfers both local sealed KV and incoming peer KV; policy is above.
    edge("sealed0", "local0", "connector0", color=GRAY,
         exit=(.67, 1), entry=(.18, 0), points=[(296, 731), (355, 731)])
    edge("sealed1", "local1", "connector1", color=GRAY,
         exit=(.33, 1), entry=(.82, 0), points=[(904, 731), (845, 731)])
    edge("peer-write0", "connector0", "peer0", color=BLUE, exit=(.82, 0), entry=(.65, 1))
    edge("peer-write1", "connector1", "peer1", color=BLUE, exit=(.18, 0), entry=(.35, 1))
    edge("peer-transfer", "connector0", "connector1", color=BLUE, both=True, exit=(1, .5), entry=(0, .5), width=3)
    text("peer-transfer-label", "Peer KV", 540, 716, 127, 31, f"fontColor={BLUE};")
    box("dram", "Shared DRAM · full sealed KV", 272, 849, 656, 55,
        f"rounded=1;arcSize=18;fillColor=#FBF0DE;strokeColor={GOLD};strokeWidth=1.8;fontStyle=1;")
    edge("dram0", "connector0", "dram", color=GOLD, both=True, exit=(.5, 1), entry=(.23, 0), width=3)
    edge("dram1", "connector1", "dram", color=GOLD, both=True, exit=(.5, 1), entry=(.77, 0), width=3)
    text("dram-label", "Copy / restore", 458, 805, 283, 32,
         f"fillColor=#F6F8F9;fontColor={GOLD};")
    # External, removable annotations; the engine copy is labeled only once.
    for num, x, y in [(1, 321, 284), (2, 603, 274), (3, 935, 284), (4, 221, 554)]:
        box(f"badge{num}", str(num), x, y, 38, 38,
            "ellipse;fillColor=#161616;strokeColor=none;fontColor=#ffffff;fontSize=28;fontStyle=1;",
            "annotations")
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT / "system-overview-v10.drawio"
    ET.indent(doc, space="  ")
    ET.ElementTree(doc).write(source, encoding="utf-8", xml_declaration=True)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT / "system-overview-v10.json").write_text(json.dumps({
        "evidence": "logical system design; capacities and DAG schematic",
        "generator": str(Path(__file__).relative_to(ROOT)), "generator_sha256": sha(Path(__file__)),
        "source_sha256": sha(source), "canvas": [W, H], "placed_width_in": 7,
        "annotations": {"1": "Workflow Tracker", "2": "KV Placement Planner", "3": "Recovery Manager", "4": "Adapter on DP0 only"},
        "connector": "un-numbered transfer executor; policy owned by KV Placement Planner",
        "control_paths": "Representative arrows; both DPs expose the same control and execution interfaces.",
        "review": "Pending native exports and integrated-PDF inspection."
    }, indent=2) + "\n")
    print(source)


if __name__ == "__main__":
    build()
