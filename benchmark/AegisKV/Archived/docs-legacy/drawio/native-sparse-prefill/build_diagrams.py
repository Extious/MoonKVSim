#!/usr/bin/env python3
"""Editable mechanism diagrams; hand-constructed causal examples, not traces."""
from __future__ import annotations

import copy
import json
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
OUT = REPO / "output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page"
OUT.mkdir(parents=True, exist_ok=True)
W = 1080
FONT = "Noto Sans CJK SC"
INK = "#19344A"
GRAY = "#5B6875"
GRID = "#CCD5DD"
BLUE = "#528ECB"
GOLD = "#E9B75B"
GREEN = "#55A18A"
PALE = "#EAF2FA"
FUTURE = "#DDE2E8"
M, N, B = 24, 8, 4
NSA_WINDOW = 4  # Illustrative token count, including the current position.
book = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
pages = []
mask_record = {}


class Page:
    def __init__(self, name, title, height):
        self.name = name
        self.height = height
        self.page = ET.SubElement(book, "diagram", id=name, name=title)
        graph = ET.SubElement(self.page, "mxGraphModel", grid="1", gridSize="10",
                              page="1", pageWidth=str(W), pageHeight=str(height),
                              background="#FFFFFF")
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.n = 0
        self.box("", 0, 0, W, height, fill="#FFFFFF", stroke="none")
        pages.append(self)

    def box(self, text, x, y, w, h, *, fill="none", stroke="none", color=INK,
            size=22, bold=False, align="center", rounded=False, pad=0, html=False):
        self.n += 1
        key = f"{self.name}-{self.n}"
        value = text if html else escape(text).replace("\n", "<br>")
        value = '<div style="line-height:1.25">' + value + "</div>"
        style = (f"html=1;whiteSpace=wrap;fontFamily={FONT};fontSize={size};"
                 f"fontColor={color};align={align};verticalAlign=middle;spacing={pad};"
                 f"fillColor={fill};strokeColor={stroke};strokeWidth=1;"
                 f"rounded={int(rounded)};arcSize=10;")
        if bold:
            style += "fontStyle=1;"
        node = ET.SubElement(self.root, "mxCell", id=key, value=value, style=style,
                             vertex="1", parent="1")
        ET.SubElement(node, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h),
                      attrib={"as": "geometry"})
        return key

    def line(self, points, color=GRID, width=1, arrow=False, dashed=False):
        self.n += 1
        key = f"{self.name}-{self.n}"
        style = (f"strokeColor={color};strokeWidth={width};rounded=0;"
                 f"endArrow={'block' if arrow else 'none'};endFill=1;endSize=8;"
                 f"dashed={int(dashed)};")
        node = ET.SubElement(self.root, "mxCell", id=key, style=style, edge="1", parent="1")
        geom = ET.SubElement(node, "mxGeometry", relative="1", attrib={"as": "geometry"})
        ET.SubElement(geom, "mxPoint", x=str(points[0][0]), y=str(points[0][1]),
                      attrib={"as": "sourcePoint"})
        ET.SubElement(geom, "mxPoint", x=str(points[-1][0]), y=str(points[-1][1]),
                      attrib={"as": "targetPoint"})
        if len(points) > 2:
            arr = ET.SubElement(geom, "Array", attrib={"as": "points"})
            for x, y in points[1:-1]:
                ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))
        return key

    def header(self, title, subtitle):
        self.box(title, 30, 20, 1020, 45, size=32, bold=True, align="left")
        self.box(subtitle, 30, 75, 1020, 52, size=22, color=GRAY, align="left")


def legend(p, y, common=False, cis=True, forced=True):
    items = [(BLUE if not common else PALE, "Q 相关选择" if not common else "因果可见"),
             (GOLD, "首部 / 局部"), (GREEN, "CIS 补入"),
             ("#FFFFFF", "未选中"), (FUTURE, "未来屏蔽")]
    xs = [35, 245, 460, 655, 835]
    if not cis:
        items.pop(2)
        xs = [35, 300, 565, 835]
    if not forced:
        items = [item for item in items if item[0] != GOLD]
        xs = [35, 420, 805]
    for (color, label), x in zip(items, xs):
        p.box("", x, y + 5, 20, 20, fill=color, stroke=GRID)
        p.box(label, x + 29, y, 170, 32, size=22, align="left")


def block_tokens(block):
    return set(range((block - 1) * B + 1, block * B + 1))


def make_masks():
    # Different illustrative score orderings are allowed. These are not results
    # of checkpoint inference and are not meant as equal-budget comparisons.
    nsa_blocks = [[2, 5], [2, 5], [3, 6], [3, 5], [2, 7], [4, 7], [2, 5], [4, 7]]
    moba_blocks = [[2, 5], [3, 5], [2, 6], [4, 6], [2, 7], [4, 7], [3, 5], [2, 6]]
    inf_blocks = [2, 3, 2, 4, 2, 4, 3, 5]
    nosa_blocks = [2, 4, 2, 5, 4, 2, 5, 4]
    dsa_tokens = [[2, 6, 11, 17, 23, 25], [2, 7, 12, 18, 24, 26],
                  [1, 6, 11, 19, 25, 27], [2, 8, 13, 20, 26, 28],
                  [2, 6, 14, 21, 27, 29], [1, 9, 15, 22, 28, 30],
                  [2, 7, 16, 23, 29, 31], [3, 6, 12, 24, 30, 32]]
    result = {}
    for name in ["causal", "nsa", "nsa-window", "moba", "infllm-v2", "dsa", "nosa"]:
        rows = []
        for r in range(N):
            pos = M + r + 1
            current = (pos - 1) // B + 1
            row = ["future" if j > pos else "none" for j in range(1, M + N + 1)]
            selected, forced, stable = set(), set(), set()
            if name == "causal":
                selected = set(range(1, pos + 1))
            elif name == "nsa":
                selected = set().union(*(block_tokens(b) for b in nsa_blocks[r]))
            elif name == "moba":
                selected = set().union(*(block_tokens(b) for b in moba_blocks[r]))
                forced = block_tokens(current)
            elif name == "infllm-v2":
                selected = block_tokens(inf_blocks[r])
                forced = block_tokens(1) | block_tokens(current - 1) | block_tokens(current)
            elif name == "dsa":
                selected = set(dsa_tokens[r])
            elif name == "nosa":
                selected = block_tokens(nosa_blocks[r])
                forced = block_tokens(1) | block_tokens(current - 1) | block_tokens(current)
                # A valid constructed case: B3 has the highest available
                # query-agnostic score and is not in this row's protected set.
                stable = block_tokens(3)
            for j in range(1, pos + 1):
                if j in selected:
                    row[j - 1] = "selected"
                if j in stable:
                    row[j - 1] = "stable"
                if j in forced:
                    row[j - 1] = "forced"
                if name == "nsa-window" and j >= max(1, pos - NSA_WINDOW + 1):
                    row[j - 1] = "window"
            assert all(row[j - 1] == "future" for j in range(pos + 1, M + N + 1))
            assert all(v != "future" for v in row[:pos])
            if name == "dsa":
                assert row.count("selected") == 6
            if name in {"moba", "infllm-v2", "nosa"}:
                assert row[pos - 1] == "forced"
            rows.append(row)
        result[name] = rows
    return result


MASKS = make_masks()


def matrix(p, name, x, y, *, cw=18, rh=24, annotate=True):
    """y is the top of token cells; distinct bands above hold title and ticks."""
    width = (M + N) * cw
    p.box("历史 M = 24", x, y - 86, M * cw, 30, color=INK, bold=True)
    p.box("后续 N = 8", x + M * cw, y - 86, N * cw, 30, color=INK, bold=True)
    for b in range(8):
        p.box(f"B{b+1}", x + b * B * cw, y - 55, B * cw, 27, size=22)
        p.box(f"{b*B+1}–{(b+1)*B}", x + b * B * cw, y - 28, B * cw, 25, size=20, color=GRAY)
    p.box("Query", x - 90, y - 30, 80, 28, bold=True)
    colors = {"selected": PALE if name == "causal" else BLUE,
              "stable": GREEN, "forced": GOLD, "window": GOLD,
              "none": "#FFFFFF", "future": FUTURE}
    for r, row in enumerate(MASKS[name]):
        p.box(f"q{M+r+1}", x - 63, y + r * rh, 47, rh, size=22, align="right")
        for c, v in enumerate(row):
            p.box("", x + c * cw, y + r * rh, cw, rh, fill=colors[v], stroke=GRID)
            if v == "future":
                p.line([(x+c*cw+4, y+r*rh+rh-4), (x+(c+1)*cw-4, y+r*rh+4)],
                       color="#A9B2BD", width=1)
        # Outline logical selected block runs to retain a non-color indication.
        if name == "nsa-window":
            inds = [c for c, v in enumerate(row) if v == "window"]
            p.box("", x + min(inds)*cw, y + r*rh, len(inds)*cw, rh,
                  stroke="#946B27")
        elif name not in {"dsa", "causal"}:
            for b in range(8):
                inds = [c for c in range(b*B, (b+1)*B)
                        if row[c] in {"selected", "stable", "forced"}]
                if inds:
                    kind = row[inds[0]]
                    p.box("", x + min(inds)*cw, y + r*rh, len(inds)*cw, rh,
                          stroke={"selected":"#2C659C", "forced":"#946B27", "stable":"#276C59"}[kind])
    for b in range(9):
        p.line([(x+b*B*cw, y), (x+b*B*cw, y+N*rh)], color="#9AA9B7", width=1)
    p.line([(x+M*cw, y-88), (x+M*cw, y+N*rh+3)], color=INK, width=3)
    if annotate:
        p.box("每个小格 = 1 个 Token；粗边界每 4 个 Token 一块。", x, y+N*rh+9,
              width, 28, size=20, color=GRAY, align="left")
    mask_record[name] = {"row_query_positions": list(range(M+1, M+N+1)), "cells": MASKS[name]}


def flow(p, y, labels):
    xs = [35, 385, 735]
    for x, label in zip(xs, labels):
        p.box(label, x, y, 310, 67, fill=PALE, stroke="#B9CFE2", rounded=True, pad=4)
    for a, b in zip(xs, xs[1:]):
        p.line([(a+310, y+33), (b-4, y+33)], color=GRAY, width=2, arrow=True)


def card(p, y, title, name, labels, notes, footer):
    p.box(title, 30, y, 1020, 42, size=28, bold=True, align="left")
    flow(p, y+55, labels)
    matrix(p, name, 110, y+225)
    p.box(notes, 725, y+165, 320, 239, size=22, align="left", pad=8,
          fill="#F4F7FA", rounded=True)
    p.box(footer, 35, y+460, 1010, 44, size=22, color=GRAY, align="left")


def context(p):
    p.box("M = 24，N = 8；后续 Query 为 q25 … q32；每 4 个 Token 画一个参考块。\n"
          "同层 N 行可并行，各行选择可不同；Query q_t 只能选择位置 j ≤ t 的 KV。",
          35, 140, 1010, 72, fill=PALE, size=22)


def shift_content(p, first, dy):
    """Translate one page's body, including all absolute edge waypoints."""
    for cell in list(p.root)[first:]:
        geom = cell.find("mxGeometry")
        if cell.get("vertex") == "1":
            geom.set("y", str(float(geom.get("y", "0")) + dy))
        elif cell.get("edge") == "1":
            for point in geom.iter("mxPoint"):
                point.set("y", str(float(point.get("y", "0")) + dy))


def placement_footer(p, y):
    p.box("所选历史 KV：Peer HBM 直接复用，DRAM 需 H2D；存放位置不改变模型选择。",
          35, y, 1010, 34, size=22, color=GRAY, align="left")


# Page 1: NSA must retain compression output and a separate sliding output.
p = Page("01-nsa-prefill", "1 · NSA", 1560)
p.header("NSA：压缩得分选原始块，三个分支分别计算", 
         "机制示意；同一层、同一 GQA 组。蓝色矩阵画精选分支，金色矩阵画滑动窗口。")
context(p)
body_start = len(p.root)
p.box("每个后续 Query\nq25 … q32", 35, 225, 220, 80, fill=PALE, stroke="#B9CFE2", bold=True)
p.box("压缩 K / V attention\n输出 Oc；权重用于选块", 350, 150, 310, 76,
      fill=PALE, stroke="#B9CFE2")
p.box("Top-k 原始 KV 块\n精选 attention → Os", 350, 280, 310, 76,
      fill=PALE, stroke="#B9CFE2")
p.box("滑动窗口内的 KV\n局部 attention → Ow", 350, 410, 310, 76,
      fill="#FFF3D9", stroke="#D8B16A")
p.box("学习得到的门控\n\nO = gc·Oc\n    + gs·Os\n    + gw·Ow", 805, 265, 240, 190,
      fill="#EDF5F2", stroke="#A6CDBE", bold=True)
for yy in [188, 318, 448]:
    p.line([(255,265), (300,265), (300,yy), (347,yy)], color=GRAY, width=2, arrow=True)
p.line([(505,226), (505,277)], color=BLUE, width=2, arrow=True)
p.box("得分用于选块", 525, 233, 165, 33, size=20, color=GRAY, align="left")
p.line([(660,188), (750,188), (750,298), (802,298)], color=BLUE, width=2, arrow=True)
p.line([(660,318), (802,318)], color=BLUE, width=2, arrow=True)
p.line([(660,448), (750,448), (750,420), (802,420)], color="#BA8B39", width=2, arrow=True)
p.box("精选分支 Os：示意每个 Query 选择 2 个原始 KV 块", 35, 530, 1010, 39,
      size=26, bold=True, align="left")
matrix(p, "nsa", 110, 680)
p.box("蓝色块由压缩得分选出。\n\n同组 Q heads 共享块；\n不同 Query 可选不同块。\n\n白色仅表示精选分支未选。\n局部窗口见下方金色矩阵。", 725, 625, 320, 258,
      fill="#F4F7FA", size=22, align="left", pad=8)
p.box("例如 q29 选中了 B7：它来自后续段，却已经处于 q29 的因果可见范围。",
      35, 922, 1010, 34, size=22, align="left")
p.box("蓝 = 精选块；白 = 精选分支未选；灰 = 未来。手工示意集合，不是实测轨迹。",
      35, 966, 1010, 30, size=22, color=GRAY, align="left")
shift_content(p, body_start, 90)
p.line([(35, 1096), (1045, 1096)], color=GRID, width=1)
p.box("局部分支 Ow：窗口内完整 attention，按位置纳入 KV", 35, 1110, 1010, 39,
      size=26, bold=True, align="left")
matrix(p, "nsa-window", 110, 1250, annotate=False)
p.box("W = 4，含当前位置\n\nq25 → KV22–25\nq28 → KV25–28\nq32 → KV29–32\n\n原始 KV；无需 Top-k\n独立计算局部输出 Ow", 725, 1195, 320, 258,
      fill="#FFF3D9", size=22, align="left", pad=8)
p.box("窗口逐 Token 滑动；B1 … B8 只作位置参考，不表示按块选择。",
      35, 1460, 1010, 30, size=22, align="left")
p.box("金 = 窗口内；白 = 窗口外；灰 = 未来。窗口范围：max(1, t−W+1) ≤ j ≤ t。",
      35, 1500, 1010, 30, size=22, color=GRAY, align="left")


# Page 2: MoBA stands alone with its own context, legend and causal matrix.
p = Page("02-moba-prefill", "2 · MoBA", 880)
p.header("MoBA：通过 Query 与整块 K 均值匹配选块", 
         "手工机制示意，非实测。固定一层、一个 attention head；当前块强制保留。")
context(p)
legend(p, 230, cis=False)
card(p, 285, "选择计算与逐 Query 模式", "moba",
     ["每块 K 求均值\n分数 = Q · mean(K块)", "按分数选历史块\n当前块强制保留", "取所选块的原始 KV\n计算 attention"],
     "蓝：2 个历史块。\n金：当前块。\n\n当前块不靠整块均值\n决定是否入选，防止\n未来 K 影响路由。\n块内仍做因果屏蔽。",
     "Query 属于同一块，也可以选择不同历史块；这里的块划分是 K/V 侧的逻辑单位。")
placement_footer(p, 825)


# Page 3: InfLLM-V2, with no independent compressed-attention output.
p = Page("03-infllmv2-prefill", "3 · InfLLM-V2", 880)
p.header("InfLLM-V2：子块评分，汇聚为整块优先级", 
         "手工机制示意，非实测。固定一层、一个 GQA 组；这里展示稀疏 Prefill 路径。")
context(p)
legend(p, 230, cis=False)
card(p, 285, "压缩表示用于选择，合并集合后计算 attention", "infllm-v2",
     ["K 子块平均池化\nQ 对压缩 K 评分", "组内聚合 + 块内 Max\n选块并加入首部 / 局部块", "集合合并去重\n单一原始 KV attention"],
     "蓝：1 个相关块。\n金：首块 + 本地 2 块。\n\n压缩 K 用于选择。\n没有 NSA 的独立\n压缩输出分支。\n本图展示稀疏路径。",
     "示意局部范围覆盖当前块与前一块；第 5 行开始，局部范围随位置向后移动。")
placement_footer(p, 825)


# Page 4: DSA token selection; no block/window legend in this page.
p = Page("04-dsa-prefill", "4 · DSA", 880)
p.header("DSA：Lightning Indexer 对历史 Token 打分", 
         "手工机制示意，非实测。固定一层的 MLA 选择；按 Token 选，不受参考块边界限制。")
context(p)
legend(p, 230, cis=False, forced=False)
card(p, 285, "轻量索引与主 attention 分开计算", "dsa",
     ["Q 的索引表示\n匹配历史索引 K", "每个 Query 独立 Top-k\n选择 Token 下标", "获取对应 MLA KV\n执行主 attention"],
     "蓝：6 个 Token。\n\nB1 … B8 只是共同\n位置参考，DSA 在\n这里按单 Token 选。\n\n索引 K 是额外状态。",
     "选择可以落在块内零散位置；逻辑 Token 数不等于系统实际需要搬运的整块字节数。")
placement_footer(p, 825)


# Page 5: NOSA retains both score sources and the fill-to-budget operation.
p = Page("05-nosa-prefill", "5 · NOSA", 1000)
p.header("NOSA：Query 相关选择与 CIS 重要性选择结合", 
         "手工机制示意，非实测。固定一层、一个 KV 组；颜色区分选择来源，不表示权重。")
context(p)
legend(p, 230)
body_start = len(p.root)
p.box("两类评分共同决定最终 KV 集合", 30, 745, 1020, 43,
      size=28, bold=True, align="left")
p.box("Query 相关块评分\nQ × 压缩 K", 35, 812, 265, 67, fill=PALE, stroke="#B9CFE2")
p.box("保留相关块\n以及首部 / 局部块", 360, 812, 270, 67, fill=PALE, stroke="#B9CFE2")
p.box("KV 自身的重要性\nCIS：不依赖当前 Query", 35, 916, 360, 67, fill="#E5F2ED", stroke="#A6CDBE")
p.box("优先保留上面的块\n其余按 CIS 补齐到预算\n所选 KV → attention", 715, 845, 330, 124,
      fill="#EDF5F2", stroke="#A6CDBE", bold=True)
p.line([(300,845), (357,845)], color=BLUE, width=2, arrow=True)
p.line([(630,845), (675,845), (675,874), (712,874)], color=BLUE, width=2, arrow=True)
p.line([(395,950), (712,950)], color=GREEN, width=2, arrow=True)
matrix(p, "nosa", 110, 1112)
p.box("蓝：1 个相关块。\n金：首块 + 本地 2 块。\n绿：按 CIS 补入 1 块。\n\n本例中 B3 反复入选；\n这是示意的排序条件，\n不代表永久固定。", 725, 1055, 320, 250,
      fill="#F4F7FA", size=22, align="left", pad=8)
p.box("本次真实实验使用 NOSA-1B；图中块长 4 是说明用缩小例子，实测使用块长 64。",
      35, 1358, 1010, 34, size=22, align="left")
p.box("原始模型还将 CIS 用于 attention 的加权归一化；图中选择后计算保留该机制。",
      35, 1398, 1010, 30, size=22, color=GRAY, align="left")
shift_content(p, body_start, -475)


for p in pages:
    single = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
    single.append(copy.deepcopy(p.page))
    ET.indent(single)
    ET.ElementTree(single).write(HERE / f"{p.name}.drawio", encoding="utf-8", xml_declaration=True)
    # Every edge must have geometry, and all IDs must be unique.
    ids = [x.get("id") for x in p.root]
    assert len(ids) == len(set(ids))
    assert all(x.find("mxGeometry") is not None for x in p.root if x.get("edge") == "1")
    for c in p.root:
        if c.get("vertex") != "1":
            continue
        g = c.find("mxGeometry")
        assert float(g.get("x")) >= 0 and float(g.get("y")) >= 0
        assert float(g.get("x")) + float(g.get("width")) <= W
        assert float(g.get("y")) + float(g.get("height")) <= p.height

ET.indent(book)
assert [page.get("name") for page in book] == ["1 · NSA", "2 · MoBA", "3 · InfLLM-V2", "4 · DSA", "5 · NOSA"]
ET.ElementTree(book).write(HERE / "native-sparse-prefill.drawio", encoding="utf-8", xml_declaration=True)
(OUT / "schematic-masks.json").write_text(json.dumps({
    "evidence_type": "mechanism illustration: constructed selections and derived causal window; not checkpoint inference",
    "M": M, "N": N, "illustrative_block_tokens": B,
    "selection_budgets": {"nsa": "2 selected blocks; other branches separate", "moba": "2 past + current",
                           "infllm-v2": "1 related + sink + 2 local", "dsa": "6 tokens",
                           "nosa": "1 related + sink + 2 local + 1 CIS"},
    "comparison": "not an equal-budget performance or locality comparison",
    "scope": "one layer and one head or KV group; no cross-layer sharing assumed",
    "nsa_window": {"tokens_including_current": NSA_WINDOW,
                   "rule": "max(1, query_position - W + 1) <= key_position <= query_position",
                   "source": "analytically derived from the illustrative window, not model traces"},
    "masks": mask_record,
    "checks": {"causality": True, "dsa_six_tokens": True, "forced_current_block": True,
               "xml_edge_geometry_and_unique_ids": True, "canvas_bounds": True}
}, indent=2, ensure_ascii=False))
print(json.dumps({"source": str(HERE), "output": str(OUT), "pages": [p.name for p in pages]}, indent=2))
