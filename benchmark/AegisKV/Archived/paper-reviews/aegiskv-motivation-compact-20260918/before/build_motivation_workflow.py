"""Editable, time-scaled workflow for the ten-branch Motivation example.

Agent bars share a time-since-fork axis: left/right ends encode
start/finish, width encodes duration, and dashed tails encode join slack.
Only the origin changes; source times and durations are not rescaled.
Main boxes and fork/join edges encode inferred dependencies. Native Draw.io
exports are made separately (see sections/README).
"""
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/motivation-wide-cc"
OUT = ROOT / "benchmark/AegisKV/paper/figures/motivation-row"
CSV = DATA / "wide-example-failure-position.csv"
EXCERPT = DATA / "selected-trace-excerpt.json"
SELECTION = DATA / "SELECTION.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def build():
    with CSV.open() as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["branch_index"]))
    assert len(rows) == 10 and len({r["workflow_id"] for r in rows}) == 1
    excerpt = json.loads(EXCERPT.read_text())
    selection = json.loads(SELECTION.read_text())
    assert rows[0]["workflow_id"] == excerpt["workflow_id"] == selection["selected_workflow_id"]
    assert [r["agent_id"] for r in rows] == [b["branch"]["agent_id"] for b in excerpt["branches"]]
    assert excerpt["preceding_main"]["type"] != "subagent" and excerpt["following_main"]["type"] != "subagent"
    for p in (CSV, EXCERPT):
        assert sha(p) == selection["files"][str(p.relative_to(ROOT))]
    join = max(float(r["branch_end_s"]) for r in rows)
    assert all(abs(join-float(r["fanout_completion_s"])) < 1e-6 for r in rows)
    assert all(abs(join-float(r["branch_end_s"])-float(r["slack_s"])) < 1e-6 for r in rows)
    assert abs(selection["selected_duration_gap_s"]-selection["target_median_s"]) <= 35
    assert float(excerpt["following_main"]["t"]) >= join

    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mxfile, "diagram", id="motivation-workflow", name="Ten-branch workflow")
    model = ET.SubElement(diagram, "mxGraphModel", page="1", pageScale="1",
                          pageWidth="215.04", pageHeight="230.4", background="#ffffff")
    graph = ET.SubElement(model, "root")
    ET.SubElement(graph, "mxCell", id="0")
    ET.SubElement(graph, "mxCell", id="1", parent="0")
    text = "html=0;whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily=Helvetica;fontSize=14.5;spacing=0;"

    def node(ident, value, x, y, w, h, style):
        c = ET.SubElement(graph, "mxCell", id=ident, value=value, vertex="1", parent="1", style=text+style)
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as":"geometry"})

    def edge(ident, source, target, sy=.5, ty=.5, arrow="block", critical=False, dashed=False):
        style = (f"html=0;rounded=0;endArrow={arrow};endFill=1;endSize=4;"
                 f"strokeColor={'#B6404F' if critical else '#6B7785'};strokeWidth={1.8 if critical else 1.1};"
                 f"dashed={int(dashed)};dashPattern=3 3;"
                 f"exitX=1;exitY={sy};exitPerimeter=0;entryX=0;entryY={ty};entryPerimeter=0;")
        c = ET.SubElement(graph, "mxCell", id=ident, edge="1", parent="1", source=source, target=target, style=style)
        ET.SubElement(c, "mxGeometry", relative="1", **{"as":"geometry"})

    def line(ident, x1, y1, x2, y2, color="#AEB9C2", dashed=False):
        c = ET.SubElement(graph, "mxCell", id=ident, edge="1", parent="1",
                          style=f"endArrow=none;strokeColor={color};strokeWidth=0.7;dashed={int(dashed)};")
        g = ET.SubElement(c, "mxGeometry", relative="1", **{"as":"geometry"})
        ET.SubElement(g, "mxPoint", x=str(x1), y=str(y1), **{"as":"sourcePoint"})
        ET.SubElement(g, "mxPoint", x=str(x2), y=str(y2), **{"as":"targetPoint"})

    # Same compact insertion size and font as the other two panels.
    node("canvas", "", 0, 0, 215.04, 230.4, "fillColor=#ffffff;strokeColor=none;pointerEvents=0;")
    time_origin = min(float(r["branch_start_s"]) for r in rows)
    plot_left, plot_right = 45.0, 166.0
    scale = (plot_right-plot_left)/(join-time_origin)
    to_x = lambda t: plot_left+(t-time_origin)*scale
    label_style = "fillColor=none;strokeColor=none;fontColor=#475569;"
    ticks = (0, 100, 200)
    for tick in ticks:
        x = to_x(time_origin+tick)
        line(f"grid_{tick}", x, 30, x, 184, color="#E4E9ED")
        line(f"tick_{tick}", x, 197, x, 201, color="#6B7785")
        node(f"tick_label_{tick}", str(tick), x-15, 201, 30, 16, label_style)
    line("time_axis", plot_left, 197, plot_right, 197, color="#6B7785")
    node("time_axis_label", "Time since fork (s)", 20, 217, 175, 13, label_style)
    node("duration_heading", "Dur.(s)", 163.5, 3, 51.5, 20, label_style+"whiteSpace=nowrap;")
    box = "rounded=1;arcSize=12;fillColor=#EFF5FA;strokeColor=#66869C;strokeWidth=1.1;fontColor=#263A49;"
    node("main_before", "Main", 18.5, 3, 35, 20, box)
    node("main_after", "Main", 125, 3, 35, 20, box)
    node("fork_bus", "", 36, 38, 0.6, 139.5, "fillColor=#6B7785;strokeColor=none;")
    node("join_bus", "", 166, 38, 0.6, 139.5, "fillColor=#6B7785;strokeColor=none;")
    # Put schematic Main nodes above the rows so they cannot obscure labels.
    line("main_fork", 36, 23, 36, 38, color="#6B7785")
    line("join_rise", 166, 38, 166, 29, color="#6B7785")
    line("join_turn", 166, 29, 142.5, 29, color="#6B7785")
    c=ET.SubElement(graph,"mxCell",id="join_main",edge="1",parent="1",
                   style="endArrow=block;endFill=1;endSize=4;strokeColor=#6B7785;strokeWidth=1.1;")
    g=ET.SubElement(c,"mxGeometry",relative="1",**{"as":"geometry"})
    ET.SubElement(g,"mxPoint",x="142.5",y="29",**{"as":"sourcePoint"})
    ET.SubElement(g,"mxPoint",x="142.5",y="23",**{"as":"targetPoint"})
    bar_geometry = []
    for i, r in enumerate(rows):
        ident = f"agent_a{i+1}"
        critical = float(r["slack_s"]) == 0
        style = box if not critical else ("rounded=1;arcSize=12;fillColor=#F9E6E8;strokeColor=#B6404F;"
                                           "strokeWidth=1.8;fontColor=#9A2636;fontStyle=1;")
        start, finish = float(r["branch_start_s"]), float(r["branch_end_s"])
        duration = finish-start
        assert abs(duration-float(r["duration_s"])) < 1e-6
        left, right = to_x(start), to_x(finish)
        cy=38+i*15.5
        node(ident, "", left, cy-6, right-left, 12, style)
        node(f"label_a{i+1}", f"A{i+1}", 0, cy-7.5, 32, 15, label_style+
             ("fontColor=#9A2636;fontStyle=1;" if critical else ""))
        node(f"duration_a{i+1}", f"{duration:.1f}", 174, cy-7.5, 41, 15, label_style+
             ("fontColor=#9A2636;fontStyle=1;" if critical else ""))
        edge(f"fork_a{i+1}", "fork_bus", ident, sy=i/(len(rows)-1))
        edge(f"a{i+1}_join", ident, "join_bus", ty=i/(len(rows)-1), arrow="none",
             critical=critical, dashed=not critical)
        assert abs((right-left)/scale-duration) < 1e-9
        assert abs((plot_right-right)/scale-float(r["slack_s"])) < 1e-9
        bar_geometry.append(dict(branch=f"A{i+1}", x_css_px=left,
                                 width_css_px=right-left, finish_x_css_px=right,
                                 slack_width_css_px=plot_right-right))
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT / "motivation-workflow.drawio"
    ET.indent(mxfile, space="  ")
    ET.ElementTree(mxfile).write(source, encoding="utf-8", xml_declaration=True)
    record = {
        "generator":str(Path(__file__).relative_to(ROOT)), "generator_sha256":sha(Path(__file__)),
        "source_sha256":{str(p.relative_to(ROOT)):sha(p) for p in (CSV, EXCERPT, SELECTION)},
        "drawio_sha256":sha(source), "workflow_id":rows[0]["workflow_id"],
        "semantics":"Agent bars retain actual start/finish differences on a linear time-since-fork axis; zero is the earliest branch start. Dashed tails are slack assuming the inferred join. Main boxes and dependency edges are schematic.",
        "node_labels":"Agent ID and execution duration in seconds; horizontal position encodes elapsed time from the first branch start. A10 runs longest and finishes last. Duration labels form a separate column because short bars cannot contain readable text.",
        "time_mapping":dict(origin_s=time_origin, origin_x_css_px=plot_left,
                            pixels_per_second=scale, join_x_css_px=plot_right,
                            displayed_ticks_s=list(ticks), ticks_relative_to_origin=True,
                            bar_geometry=bar_geometry),
        "critical_branches":[f"A{i+1}" for i,r in enumerate(rows) if float(r["slack_s"]) == 0],
        "join_s":join, "failure_time_s":float(rows[0]["failure_time_s"]),
        "join_time_since_fork_s":join-time_origin,
        "failure_time_since_fork_s":float(rows[0]["failure_time_s"])-time_origin,
        "duration_gap_s":selection["selected_duration_gap_s"],
        "population_median_s":selection["target_median_s"],
        "branches":[dict(branch=f"A{i+1}", agent_id=r["agent_id"], start_s=float(r["branch_start_s"]),
                         finish_s=float(r["branch_end_s"]), duration_s=float(r["duration_s"]),
                         slack_s=float(r["slack_s"])) for i,r in enumerate(rows)],
        "insertion_width_in":2.24, "canvas_css_px":[215.04,230.4], "font_css_px":14.5,
    }
    (OUT / "motivation-workflow.json").write_text(json.dumps(record,indent=2)+"\n")
    print(source)


if __name__ == "__main__":
    build()
