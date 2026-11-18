"""Editable, time-scaled workflow for the four-branch Motivation example.

Agent bars share an implicit linear time scale: left/right ends encode
start/finish, width encodes duration, and dashed tails encode join slack.
Only the origin changes; source times and durations are not rescaled.
Main boxes and fork/join edges encode inferred dependencies. Native Draw.io
exports and review files remain under exports/, outside the Overleaf inputs.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from motivation_layout import HEIGHT_IN, BOTTOM_IN, WIDTHS_IN

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/motivation-compact-cc"
OUT = ROOT / "benchmark/AegisKV/exports/motivation-layout/sources"
CSV = DATA / "compact-example-failure-position.csv"
EXCERPT = DATA / "selected-trace-excerpt.json"
SELECTION = DATA / "SELECTION.json"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def build(out=OUT):
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
    canvas_w, canvas_h = WIDTHS_IN["workflow"] * 96, HEIGHT_IN * 96
    model = ET.SubElement(diagram, "mxGraphModel", page="1", pageScale="1",
                          pageWidth=str(canvas_w), pageHeight=str(canvas_h), background="#ffffff")
    graph = ET.SubElement(model, "root")
    ET.SubElement(graph, "mxCell", id="0")
    ET.SubElement(graph, "mxCell", id="1", parent="0")
    text = "html=0;whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily=Cantarell;fontSize=14.0;spacing=0;"

    def node(ident, value, x, y, w, h, style):
        c = ET.SubElement(graph, "mxCell", id=ident, value=value, vertex="1", parent="1", style=text+style)
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as":"geometry"})

    def edge(ident, source, target, sy=.5, ty=.5, arrow="none", critical=False, dashed=False):
        style = (f"html=0;rounded=0;endArrow={arrow};endFill=0;endSize=2.5;"
                 f"strokeColor={'#B6404F' if critical else '#8293A0'};strokeWidth={1.4 if critical else 1.0};"
                 f"dashed={int(dashed)};dashPattern=3 3;"
                 f"exitX=1;exitY={sy};exitPerimeter=0;entryX=0;entryY={ty};entryPerimeter=0;")
        c = ET.SubElement(graph, "mxCell", id=ident, edge="1", parent="1", source=source, target=target, style=style)
        ET.SubElement(c, "mxGeometry", relative="1", **{"as":"geometry"})

    # Reserve a wider panel for the workflow instead of squeezing its Main nodes.
    node("canvas", "", 0, 0, canvas_w, canvas_h, "fillColor=#ffffff;strokeColor=none;pointerEvents=0;")
    time_origin = min(float(r["branch_start_s"]) for r in rows)
    # Main nodes flank the time-scaled branches: Main -> fork -> join -> Main.
    # Only the central branch region is quantitative; Main nodes are schematic.
    # Main widths are schematic. All four branches retain the same 154 px
    # quantitative time span; widening the endpoints never distorts one bar.
    plot_left, plot_right = 50.0, 204.0
    scale = (plot_right-plot_left)/(join-time_origin)
    to_x = lambda t: plot_left+(t-time_origin)*scale
    box = "rounded=1;arcSize=12;fillColor=#EFF5FA;strokeColor=#66869C;strokeWidth=1.0;fontColor=#263A49;"
    critical_box = ("rounded=1;arcSize=12;fillColor=#F9E6E8;strokeColor=#B6404F;"
                    "strokeWidth=1.4;fontColor=#9A2636;fontStyle=1;")
    # Balance the complete visible panel, including the plots' header/footer.
    # The diagram has no plot legend above it, so use that band for branches.
    # Quantitative horizontal geometry remains exactly the same.
    plot_top, plot_bottom = .04 * 96, canvas_h - BOTTOM_IN * 96
    bar_height = 22.0
    first_row_y = plot_top + bar_height / 2
    row_spacing = (plot_bottom - plot_top - bar_height) / (len(rows) - 1)
    bus_height = row_spacing*(len(rows)-1)
    middle_y = first_row_y+bus_height/2
    node("main_before", "A0", 2, middle_y-15, 35, 30, critical_box)
    node("main_after", "A5", 217.4, middle_y-15, 35, 30, critical_box)
    node("fork_bus", "", 43, first_row_y, 1.0, bus_height,
         "fillColor=#8293A0;strokeColor=none;")
    node("join_bus", "", plot_right, first_row_y, 1.0, bus_height,
         "fillColor=#8293A0;strokeColor=none;")
    edge("main_fork", "main_before", "fork_bus", arrow="none")
    # The shared fork/join connectors already convey the four dependencies.
    # One small, open arrow states the overall direction without four wedges.
    edge("join_main", "join_bus", "main_after", arrow="open")
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
        node(ident, f"A{i+1} {duration:.1f}s", left, cy-bar_height/2,
             right-left, bar_height, style+"whiteSpace=nowrap;")
        edge(f"fork_a{i+1}", "fork_bus", ident, sy=i/(len(rows)-1))
        edge(f"a{i+1}_join", ident, "join_bus", ty=i/(len(rows)-1), arrow="none",
             critical=critical, dashed=not critical)
        assert abs((right-left)/scale-duration) < 1e-9
        assert abs((plot_right-right)/scale-float(r["slack_s"])) < 1e-9
        bar_geometry.append(dict(branch=f"A{i+1}", x_css_px=left,
                                 width_css_px=right-left, finish_x_css_px=right,
                                 slack_width_css_px=plot_right-right))
    # Explain the two visual encodings at the same level as the plot x labels.
    # These are legend keys, not additional workflow nodes or a time axis.
    legend_y = 149.62
    node("legend_critical_key", "", 26, legend_y-6, 14, 12, critical_box)
    legend_text = ("fillColor=none;strokeColor=none;align=left;whiteSpace=nowrap;"
                   "fontFamily=DejaVu Sans;fontSize=13.6666667;fontColor=#263A49;")
    node("legend_critical_text", "Critical path", 46, legend_y-7, 91, 14, legend_text)
    key = ET.SubElement(graph, "mxCell", id="legend_slack_key", edge="1", parent="1",
                        style="endArrow=none;startArrow=none;strokeColor=#8293A0;strokeWidth=1;dashed=1;dashPattern=3 3;")
    geom = ET.SubElement(key, "mxGeometry", relative="1", **{"as":"geometry"})
    ET.SubElement(geom, "mxPoint", x="147", y=str(legend_y), **{"as":"sourcePoint"})
    ET.SubElement(geom, "mxPoint", x="167", y=str(legend_y), **{"as":"targetPoint"})
    node("legend_slack_text", "Join slack", 174, legend_y-7, 78, 14, legend_text)
    out.mkdir(parents=True, exist_ok=True)
    source = out / "motivation-workflow.drawio"
    ET.indent(mxfile, space="  ")
    ET.ElementTree(mxfile).write(source, encoding="utf-8", xml_declaration=True)
    record = {
        "generator":str(Path(__file__).relative_to(ROOT)), "generator_sha256":sha(Path(__file__)),
        "layout_sha256":sha(Path(__file__).with_name("motivation_layout.py")),
        "source_sha256":{str(p.relative_to(ROOT)):sha(p) for p in (CSV, EXCERPT, SELECTION)},
        "drawio_sha256":sha(source), "workflow_id":rows[0]["workflow_id"],
        "semantics":"Left-to-right A0 (Main before fork) / parallel branches / assumed join / A5 (Main after join). Agent bars retain actual start/finish differences on an implicit linear time scale; visible axis and ticks are omitted. Dashed tails are slack assuming the inferred join. A0/A5 boxes and dependency edges are schematic, outside the quantitative time region.",
        "node_labels":"A1-A4 IDs and execution duration in seconds appear on one line inside each bar. All branch widths use one common time scale. A0 and A5 name the two Main stages and flank the branch group in wider, padded schematic nodes. A0, A2 and A5 use the same red styling for the assumed critical path.",
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
        "insertion_width_in":2.65, "canvas_css_px":[canvas_w,canvas_h],
        "main_node_css_px":[35,30],
        "diagram_region_in":{"top":.04,"bottom":HEIGHT_IN-BOTTOM_IN},
        "optical_layout":"Branch group fills the header+plot height; encoding legend shares the plots' xlabel band. Equal full-panel visible height takes priority over forcing the diagram into the axes-only band.",
        "branch_bar_height_css_px":bar_height,
        "connectors":"Thin fork/join lines; no branch-entry arrowheads; one small open arrow into A5.",
        "font_family":"Cantarell", "font_css_px":14.0,
    }
    (out / "motivation-workflow.json").write_text(json.dumps(record,indent=2)+"\n")
    print(source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    build(parser.parse_args().output_dir)
