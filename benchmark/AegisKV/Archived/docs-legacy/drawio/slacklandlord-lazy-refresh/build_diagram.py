#!/usr/bin/env python3
"""Symbolic SlackLandlord control flow, preserving the old rental/heap skeleton."""
from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
CLI = "/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
WIDTH, HEIGHT = 1320, 2810
INK, BLUE, PURPLE, GREEN, AMBER, GRAY, RED = (
    "#24364B", "#246BA2", "#7351A5", "#177F67", "#A16A17", "#647383", "#AB4346"
)
FILLS = {BLUE: "#EDF5FB", PURPLE: "#F5F0FA", GREEN: "#EBF7F1",
         AMBER: "#FFF7E8", GRAY: "#F5F7F9", RED: "#FCF0F0"}
book = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
page = ET.SubElement(book, "diagram", id="SL", name="SlackLandlord：符号与决策流程")
graph = ET.SubElement(page, "mxGraphModel", grid="1", gridSize="10", page="1",
                      pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background="#FFFFFF")
root = ET.SubElement(graph, "root")
ET.SubElement(root, "mxCell", id="0")
ET.SubElement(root, "mxCell", id="1", parent="0")
nodes: dict[str, tuple[int, int, int, int]] = {}
main: list[str] = []
edges: list[tuple[str, str]] = []


def box(key, value, x, y, w, h, *, color=BLUE, shape="process", size=26):
    style = ("whiteSpace=wrap;html=1;fontFamily=Noto Sans CJK SC;"
             "align=center;verticalAlign=middle;spacing=8;strokeWidth=2;"
             f"fontSize={size};fontColor={INK};strokeColor={color};"
             f"fillColor={FILLS.get(color, '#FFFFFF')};")
    if shape == "decision":
        style += "rhombus;"
    elif shape == "terminal":
        style += "rounded=1;arcSize=50;"
    elif shape == "text":
        style += "strokeColor=none;fillColor=none;spacing=0;"
    elif shape == "junction":
        style += f"ellipse;fillColor={color};strokeColor={color};"
    else:
        style += "rounded=1;arcSize=5;"
    cell = ET.SubElement(root, "mxCell", id=key, value=value, style=style, vertex="1", parent="1")
    ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
    nodes[key] = (x, y, w, h)


def node(key, value, y, h, *, w=760, color=BLUE, shape="process", size=26):
    box(key, f'<div style="line-height:1.35">{value}</div>', 660-w//2, y, w, h,
        color=color, shape=shape, size=size)
    main.append(key)


def edge(source, target, *, label="", points=(), out=(.5, 1), into=(.5, 0),
         color=GRAY, dashed=False, label_box=None, arrow=True):
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
             f"endArrow={'block' if arrow else 'none'};endFill=1;strokeWidth=2.5;strokeColor={color};"
             "fontFamily=Noto Sans CJK SC;fontSize=23;labelBackgroundColor=#FFFFFF;"
             "jumpStyle=arc;jumpSize=10;"
             f"exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};")
    if dashed:
        style += "dashed=1;dashPattern=6 4;"
    key = f"edge-{len(edges)}"
    cell = ET.SubElement(root, "mxCell", id=key, value="" if label_box else label,
                         style=style, edge="1", parent="1", source=source, target=target)
    geo = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
    if points:
        array = ET.SubElement(geo, "Array", **{"as": "points"})
        for x, y in points:
            ET.SubElement(array, "mxPoint", x=str(x), y=str(y))
    edges.append((source, target))
    if label_box:
        box(key+"-label", label, *label_box, color=color, shape="text", size=22)


box("canvas", "", 0, 0, WIDTH, HEIGHT, color="#FFFFFF")
box("title", "<b>SlackLandlord：KV 备份决策</b>", 60, 25, 1200, 55, shape="text", size=36)
box("containers", "单个目标池分别执行：Peer HBM / DRAM　·　<i>Q</i>：最小堆　·　<i>Y</i>：淘汰集合",
    60, 95, 1200, 42, shape="text", size=24)

node("event", "<b>请求 / 新 chunk / 状态事件</b>", 170, 65, w=640, shape="terminal")
node("metadata", "更新 Slack 与共享引用；必要时修复排序下界<br>"
     "x ← 首个尚未备份的完整 chunk",
     290, 110, w=920, size=25)

node("priority", "<b>计算保护收益与 Priority</b><br>"
     "单请求贡献 = max(保护前恢复时间 − Slack, 0)<br>"
     "− max(保护后恢复时间 − Slack, 0)<br>"
     "G<sub>k</sub> ← 汇总共享请求贡献　；　P<sub>k</sub> = G<sub>k</sub> / b<sub>k</sub>",
     455, 155, w=940, color=PURPLE)
node("credit", "<b>Landlord：租金阈值与 Credit</b><br>"
     "H<sub>k</sub> = 入池租金 + P<sub>k</sub>　；　credit<sub>k</sub> = b<sub>k</sub> max(H<sub>k</sub> − L, 0)<br>"
     "价值刷新沿用原入池租金，不自动续租",
     665, 145, w=920, color=PURPLE)
node("preview", "<b>创建临时堆与租金状态，仅用于预演</b><br>"
     "Θ<sub>x</sub> ← L + P<sub>x</sub>　；　Y ← ∅<br>"
     "后续 Q、L 均指预演状态；拒绝时丢弃",
     865, 125, w=820)

node("capacity", "<b>规划空间足够？</b>", 1045, 125, w=470, shape="decision", color=AMBER, size=29)
node("pop", "<b>Lazy Refresh</b><br>"
     "从 Q 弹出最小下界项 y<br>"
     "按需刷新 G<sub>y</sub>、P<sub>y</sub>、H<sub>y</sub>",
     1225, 125, w=720, color=PURPLE)
node("minimum", "<b>刷新后仍为最小项？</b><br>与其余候选下界比较",
     1405, 125, w=600, shape="decision", color=PURPLE, size=27)
node("threshold", "<b>H<sub>y</sub> &lt; Θ<sub>x</sub> ?</b>",
     1585, 125, w=470, shape="decision", color=AMBER, size=29)

node("victim", "Y ← Y ∪ {y}　；　L ← max(L, H<sub>y</sub>)<br>"
     "credit<sub>y</sub> = 0；累计拟释放空间<br>"
     "将新暴露的合法尾块加入 Q",
     1765, 145, w=820, color=PURPLE)
node("admit", "<b>G<sub>x</sub> &gt; D<sub>Y</sub> ?</b><br>且前置检查通过",
     2000, 145, w=600, shape="decision", color=AMBER, size=27)
node("copy", "<b>淘汰 Y、提交租金 L、为 x 分配空间</b><br>"
     "复制 → 完整有效 ACK → 发布备份",
     2210, 100, w=760, color=GREEN)
node("next", "<b>下一 chunk / 等待状态事件</b>", 2370, 65, w=640, shape="terminal", color=GRAY)

# One shared rejection path, kept outside the single main column.
for key, y in (("bypass-pop", 1287), ("bypass-threshold", 1647),
               ("bypass-admit", 2072), ("bypass-copy", 2260)):
    box(key, "", 1247, y-3, 6, 6, color=RED, shape="junction")

edge("event", "metadata")
edge("metadata", "priority")
edge("priority", "credit")
edge("credit", "preview")
edge("preview", "capacity")
edge("capacity", "pop", label="否", label_box=(670, 1180, 65, 34))
edge("capacity", "admit", label="是：空间足够", out=(0,.5), into=(0,.5),
     points=((90,1107),(90,2072)), color=GREEN, label_box=(100,1120,220,35))
edge("pop", "minimum")
edge("minimum", "threshold", label="是", label_box=(670,1540,65,34), color=PURPLE)
edge("minimum", "pop", label="否<br>更新下界<br>重新入堆 Q",
     out=(1,.5), into=(1,.85), points=((1080,1467),(1080,1331)),
     color=PURPLE, label_box=(1090,1360,145,100))
edge("threshold", "victim", label="是", label_box=(670,1720,65,34), color=PURPLE)
edge("victim", "capacity", out=(0,.5), into=(.5,0),
     points=((210,1837),(210,1015),(660,1015)), color=PURPLE,
     label="继续选取", label_box=(215,1640,140,40))
edge("admit", "copy", label="是", label_box=(670,2160,65,34), color=GREEN)
edge("copy", "next", color=GREEN)

edge("pop", "bypass-pop", label="<i>Q</i> = ∅", out=(1,.2), into=(.5,0),
     points=((1250,1250),), color=RED, label_box=(1070,1200,170,38), arrow=False)
edge("threshold", "bypass-threshold", label="否", out=(1,.5), into=(0,.5),
     color=RED, label_box=(1020,1595,70,38), arrow=False)
edge("admit", "bypass-admit", label="否", out=(1,.5), into=(0,.5),
     color=RED, label_box=(1020,2020,70,38), arrow=False)
edge("copy", "bypass-copy", label="失败 / 版本失效", out=(1,.5), into=(0,.5),
     color=RED, label_box=(1030,2210,210,38), arrow=False)
edge("bypass-pop", "bypass-threshold", color=RED, arrow=False)
edge("bypass-threshold", "bypass-admit", color=RED, arrow=False)
edge("bypass-admit", "bypass-copy", color=RED, arrow=False)
edge("bypass-copy", "next", out=(.5,1), into=(1,.5), points=((1250,2402),),
     color=RED, label="暂停本层备份", label_box=(1010,2320,230,38))

box("notation-title", "<b>符号速查：10 类核心记号；x、y、k 仅区分对象</b>",
    90, 2470, 1140, 38, shape="text", size=24)
legend = [
    "Q：最小堆　·　Y：拟淘汰集合　·　x：新候选　·　y：淘汰候选　·　k：任意块",
    "G：保护收益　·　P：每字节 Priority　·　b：chunk 字节数",
    "L：累计租金　·　H：chunk 租金阈值　·　credit：扣租后剩余额度",
    "Θ：新候选准入阈值　·　D：淘汰集合的整体损失",
    "←：赋值　·　∅：空集　·　Y ∪ {y}：将 y 加入 Y　·　max：取最大值",
]
for index, label in enumerate(legend):
    box(f"notation-{index}", label, 90, 2520+index*40, 1140, 36, shape="text", size=23)
box("scope", "Slack：请求的时间余量　·　设计草案：共享贡献汇总与续租规则待定",
    50, 2760, 1220, 35, shape="text", size=20)

cells = root.findall("mxCell")
ids = [c.get("id") for c in cells]
assert len(ids) == len(set(ids))
assert len({nodes[k][0] + nodes[k][2] / 2 for k in main}) == 1
assert all(0 <= x <= x+w <= WIDTH and 0 <= y <= y+h <= HEIGHT
           for x,y,w,h in nodes.values())
for c in cells:
    if c.get("edge") == "1":
        assert c.get("source") in nodes and c.get("target") in nodes
        assert c.find("mxGeometry").get("relative") == "1"

# Legacy mxCodec stores objects in an Array. Bare IDs such as "pop" resolve
# to inherited functions and fail in mxCellCodec.beforeDecode (obj.setId).
# Keep builder keys readable, but namespace every serialized cell/reference.
id_map = {c.get("id"): c.get("id") if c.get("id") in {"0", "1"}
          else "slr-" + c.get("id") for c in cells}
for c in cells:
    for attr in ("id", "parent", "source", "target"):
        if c.get(attr) in id_map:
            c.set(attr, id_map[c.get(attr)])
assert all(c.get("id") in {"0", "1"} or c.get("id").startswith("slr-") for c in cells)
assert len({c.get("id") for c in cells}) == len(cells)
assert all(c.get(attr) in set(id_map.values()) for c in cells
           for attr in ("parent", "source", "target") if c.get(attr) is not None)
ET.indent(book)
src = OUT / "slacklandlord-lazy-refresh.drawio"
ET.ElementTree(book).write(src, encoding="utf-8", xml_declaration=True)
for fmt in ("pdf", "png"):
    options = ["-a", "--crop"] if fmt == "pdf" else ["-s", "1.25"]
    subprocess.run([CLI, "-x", "-f", fmt, "-e", "-b", "0", *options,
                    "-o", str(src) + "." + fmt, str(src)], check=True)

import pymupdf
from PIL import Image

with pymupdf.open(str(src) + ".pdf") as pdf:
    assert len(pdf) == 1 and "SlackLandlord" in pdf[0].get_text()
    raw = unquote(pdf.metadata["subject"])
    if raw != src.read_text():
        # Normalize Desktop 31.1.5 PDF metadata escaping; preserve page artwork.
        assert raw.replace("\\(", "(").replace("\\)", ")") == src.read_text()
        metadata = {k: v for k, v in pdf.metadata.items() if k not in {"format", "encryption"}}
        metadata["subject"] = quote(src.read_text(), safe="")
        metadata["title"] = "SlackLandlord - symbolic rental and heap flow (design)"
        pdf.set_metadata(metadata)
        pdf.saveIncr()
    assert unquote(pdf.metadata["subject"]) == src.read_text()
    assert all(pdf[0].rect.contains(pymupdf.Rect(block[:4])) for block in pdf[0].get_text("blocks"))
with Image.open(str(src) + ".png") as im:
    embedded = ET.fromstring(unquote(im.info["mxGraphModel"]))
    assert [x.get("id") for x in embedded.findall("diagram")] == ["SL"]
    embedded_cells = embedded.findall(".//mxCell")
    assert [dict(c.attrib) for c in embedded_cells] == [dict(c.attrib) for c in cells]
    png_size = list(im.size)

digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
inputs = [ROOT / "python/moonkvsim/aegiskv" / f for f in
          ("slack_landlord.py", "lazy_refresh.py", "rental_value.py", "prefix_frontier.py")]
native_design = Path("/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/design/current_design.md")
record = {
    "scope": "Symbolic SlackLandlord flow with explicit decisions, heap refresh and victim-selection loops",
    "status": "DESIGN_ONLY", "algorithm_changed": False,
    "lower_bound_index_implemented": False,
    "open_choices": ["shared-value aggregation", "renewal policy", "legacy key-refresh compatibility", "physical candidate/group index"],
    "source_sha256": {str(f.relative_to(ROOT)): digest(f) for f in inputs},
    "external_reference_sha256": {str(native_design): digest(native_design)},
    "generator_sha256": {str(Path(__file__).relative_to(ROOT)): digest(Path(__file__))},
    "output_sha256": {f.name: digest(f) for f in OUT.iterdir() if f.suffix in {".drawio", ".png", ".pdf"}},
    "documentation_sha256": {"README.md": digest(OUT / "README.md")},
    "notation": {"core_symbols": ["Q", "Y", "G", "P", "b", "L", "H", "credit", "Theta", "D"],
                 "core_symbol_count": 10, "object_aliases": ["x", "y", "k"], "legend_in_diagram": True},
    "xml_checks": {"unique_ids": "PASS", "edge_endpoints": "PASS", "legacy_safe_ids": "PASS", "geometry_bounds": "PASS", "single_column": "PASS", "flow_nodes": len(main), "decision_nodes": 4, "control_edges": len(edges)},
    "export_checks": {"pdf_pages": 1, "pdf_text_bounds": "PASS", "pdf_embedded_source": "PASS", "png_embedded_source": "PASS", "png_pixels": png_size},
    "visual_review": "PENDING",
}
(OUT / "MANIFEST.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
print("Symbolic SlackLandlord flow exported and structurally checked")
