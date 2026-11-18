"""Editable, time-scaled workflow for the four-branch Motivation example.

Agent bars share an implicit linear time scale: left/right ends encode
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
DATA = ROOT / "benchmark/AegisKV/experiments/data/motivation-compact-cc"
OUT = ROOT / "benchmark/AegisKV/paper/figures/motivation-row"
CSV = DATA / "compact-example-failure-position.csv"
EXCERPT = DATA / "selected-trace-excerpt.json"
SELECTION = DATA / "SELECTION.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def build():
    with CSV.open() as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["branch_index"]))
    assert len(rows) == 4 and len({r["workflow_id"] for r in rows}) == 1
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
    assert abs(selection["selected_duration_gap_s"]-selection["target_gap_s"]) <= 15
    assert float(excerpt["following_main"]["t"]) >= join

    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mxfile, "diagram", id="motivation-workflow", name="Four-branch workflow")
    model = ET.SubElement(diagram, "mxGraphModel", page="1", pageScale="1",
                          pageWidth="215.04", pageHeight="177.6", background="#ffffff")
    graph = ET.SubElement(model, "root")
    ET.SubElement(graph, "mxCell", id="0")
    ET.SubElement(graph, "mxCell", id="1", parent="0")
    text = "html=0;whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily=Cantarell;fontSize=14.5;spacing=0;"

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

    # Same compact insertion size and font as the other two panels.
    node("canvas", "", 0, 0, 215.04, 177.6, "fillColor=#ffffff;strokeColor=none;pointerEvents=0;")
    time_origin = min(float(r["branch_start_s"]) for r in rows)
    # Main nodes flank the time-scaled branches: Main -> fork -> join -> Main.
    # Only the central branch region is quantitative; Main nodes are schematic.
    # Compact Main aliases leave more width for all time-scaled branch bars.
    # The common scale is retained even though the visible axis is omitted.
    plot_left, plot_right = 30.0, 184.0
    scale = (plot_right-plot_left)/(join-time_origin)
    to_x = lambda t: plot_left+(t-time_origin)*scale
    box = "rounded=1;arcSize=12;fillColor=#EFF5FA;strokeColor=#66869C;strokeWidth=1.1;fontColor=#263A49;"
    critical_box = ("rounded=1;arcSize=12;fillColor=#F9E6E8;strokeColor=#B6404F;"
                    "strokeWidth=1.8;fontColor=#9A2636;fontStyle=1;")
    first_row_y, row_spacing = 30.0, 39.0
    bus_height = row_spacing*(len(rows)-1)
    middle_y = first_row_y+bus_height/2
    node("main_before", "A0", 0.8, middle_y-12, 22, 24, critical_box)
    node("main_after", "A5", 192.2, middle_y-12, 22, 24, critical_box)
    node("fork_bus", "", 26, first_row_y, 0.6, bus_height,
         "fillColor=#6B7785;strokeColor=none;")
    node("join_bus", "", plot_right, first_row_y, 0.6, bus_height,
         "fillColor=#6B7785;strokeColor=none;")
    edge("main_fork", "main_before", "fork_bus", arrow="none")
    edge("join_main", "join_bus", "main_after")
    bar_geometry = []
    for i, r in enumerate(rows):
        ident = f"agent_a{i+1}"
        critical = float(r["slack_s"]) == 0
        style = critical_box if critical else box
        start, finish = float(r["branch_start_s"]), float(r["branch_end_s"])
        duration = finish-start
        assert abs(duration-float(r["duration_s"])) < 1e-6
        left, right = to_x(start), to_x(finish)
        cy=first_row_y+i*row_spacing
        # Single-line labels fit by widening the common scale, not just A1.
        node(ident, f"A{i+1} {duration:.1f}s", left, cy-12,
             right-left, 24, style+"whiteSpace=nowrap;")
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
        "semantics":"Left-to-right A0 (Main before fork) / parallel branches / assumed join / A5 (Main after join). Agent bars retain actual start/finish differences on an implicit linear time scale; visible axis and ticks are omitted. Dashed tails are slack assuming the inferred join. A0/A5 boxes and dependency edges are schematic, outside the quantitative time region.",
        "node_labels":"A1-A4 IDs and execution duration in seconds appear on one line inside each bar. All branch widths use the same expanded time scale. A0 and A5 name the two Main stages and flank the branch group. A0, A2 and A5 use the same red styling for the assumed critical path.",
        "node_aliases":{"A0":"Main before fork", "A5":"Main after join"},
        "time_mapping":dict(origin_s=time_origin, origin_x_css_px=plot_left,
                            pixels_per_second=scale, join_x_css_px=plot_right,
                            displayed_ticks_s=[], axis_visible=False,
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
        "insertion_width_in":2.24, "canvas_css_px":[215.04,177.6],
        "font_family":"Cantarell", "font_css_px":14.5,
    }
    (OUT / "motivation-workflow.json").write_text(json.dumps(record,indent=2)+"\n")
    print(source)


if __name__ == "__main__":
    build()
