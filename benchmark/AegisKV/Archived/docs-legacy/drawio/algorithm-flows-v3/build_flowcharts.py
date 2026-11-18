#!/usr/bin/env python3
"""Editable, source-bound Chinese revision-3 flowcharts; official Draw.io export."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
CLI = "/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
FONT = "Noto Sans CJK SC"
INK, BLUE, PURPLE, GREEN, RED, AMBER, GRAY = (
    "#24364B", "#246BA2", "#7351A5", "#177F67", "#AB4346", "#A16A17", "#647383"
)
FILLS = {INK: "#F5F7FA", BLUE: "#EDF5FB", PURPLE: "#F5F0FA", GREEN: "#EBF7F1",
         RED: "#FCF0F0", AMBER: "#FFF7E8", GRAY: "#F5F7F9"}
WIDTH, HEIGHT = 2400, 1800


class Book:
    def __init__(self, stem: str):
        self.stem = stem
        self.xml = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
        self.pages: list[Page] = []

    def page(self, code: str, title: str, subtitle: str, lanes: tuple[str, str, str]) -> Page:
        result = Page(self.xml, code, title, subtitle, lanes)
        self.pages.append(result)
        return result

    def save(self) -> Path:
        for page in self.pages:
            page.validate()
        ET.indent(self.xml)
        path = OUT / (self.stem + ".drawio")
        ET.ElementTree(self.xml).write(path, encoding="utf-8", xml_declaration=True)
        return path


class Page:
    def __init__(self, book, code, title, subtitle, lanes):
        self.code = code
        self.nodes: dict[str, tuple[int, int, int, int]] = {}
        self.edges: list[tuple[str, str]] = []
        self.sources: dict[str, str] = {}
        page = ET.SubElement(book, "diagram", id=code, name=code + " " + title)
        graph = ET.SubElement(page, "mxGraphModel", grid="1", gridSize="10", page="1",
                              pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background="#FFFFFF")
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.box("canvas", "", 0, 0, WIDTH, HEIGHT, fill="#FFFFFF", color="#FFFFFF")
        self.box("title", code + "  |  " + title, 45, 25, 2310, 62,
                 text=True, size=38, bold=True, align="left")
        self.box("subtitle", subtitle, 45, 94, 2310, 42, text=True, size=23,
                 color=GRAY, align="left")
        for i, heading in enumerate(lanes):
            self.box("lane" + str(i), "", 35 + i * 800, 150, 730, 1475,
                     color="#D5DEE8", fill="#FBFCFE", container=True)
            self.box("lane-title" + str(i), heading, 55 + i * 800, 159, 690, 48,
                     text=True, color=BLUE, size=28, bold=True, align="left")

    def box(self, key, value, x, y, w, h, *, color=INK, fill=None, size=24, bold=False,
            text=False, decision=False, container=False, align="center", source=""):
        style = (f"fontFamily={FONT};fontSize={size};fontColor={color};whiteSpace=wrap;html=0;"
                 f"align={align};verticalAlign=middle;spacing=12;strokeWidth=2;")
        if text:
            style += "text;strokeColor=none;fillColor=none;"
        else:
            style += f"strokeColor={color};fillColor={fill or FILLS.get(color, '#FFFFFF')};"
            style += "rhombus;" if decision else "rounded=1;arcSize=8;"
        if bold:
            style += "fontStyle=1;"
        parent = "1"
        px, py = x, y
        if container:
            style += "container=1;pointerEvents=0;"
        elif not text and key != "canvas":
            lane = min(2, max(0, x // 800))
            if 150 <= y and y + h <= 1625 and 35 + lane * 800 <= x < x + w <= 765 + lane * 800:
                parent = "lane" + str(lane)
                px, py = x - (35 + lane * 800), y - 150
        attrs = dict(id=key, value=value, style=style, vertex="1", parent=parent)
        if source:
            attrs["data-source"] = source
            self.sources[key] = source
        cell = ET.SubElement(self.root, "mxCell", attrs)
        ET.SubElement(cell, "mxGeometry", x=str(px), y=str(py), width=str(w), height=str(h),
                      attrib={"as": "geometry"})
        self.nodes[key] = (x, y, w, h)

    def n(self, lane, key, value, y, h=110, **kwargs):
        self.box(key, value, 120 + lane * 800, y, 560, h, **kwargs)

    def d(self, lane, key, value, y, h=165, **kwargs):
        self.box(key, value, 90 + lane * 800, y, 620, h,
                 decision=True, color=AMBER, size=24, **kwargs)

    def e(self, source, target, label="", *, out=(.5, 1), into=(.5, 0), points=(),
          color=BLUE, dashed=False, label_pos=None):
        key = f"edge-{len(self.edges)}"
        style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;strokeColor={color};strokeWidth=2.8;"
                 f"endArrow=block;endFill=1;endSize=10;fontFamily={FONT};fontSize=22;"
                 f"fontColor={color};labelBackgroundColor=#FFFFFF;jettySize=20;"
                 f"exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};"
                 "exitPerimeter=1;entryPerimeter=1;")
        if dashed:
            style += "dashed=1;dashPattern=6 4;"
        cell = ET.SubElement(self.root, "mxCell", id=key, value="" if label_pos else label, style=style,
                             edge="1", parent="1", source=source, target=target)
        geom = ET.SubElement(cell, "mxGeometry", relative="1", attrib={"as": "geometry"})
        if points:
            array = ET.SubElement(geom, "Array", attrib={"as": "points"})
            for x, y in points:
                ET.SubElement(array, "mxPoint", x=str(x), y=str(y))
        self.edges.append((source, target))
        if label_pos:
            self.box(key + "-label", label, *label_pos, color=color, text=True, size=22)
            self.root[-1].set("style", self.root[-1].get("style") + "fillColor=#FFFFFF;spacing=2;")

    def foot(self, text, sources):
        self.box("invariant", text, 45, 1650, 2310, 85, color=PURPLE, size=25)
        self.box("source-footer", sources + "  |  Revision 3：参考协议；native 集成未完成",
                 45, 1740, 2310, 45, color=GRAY, text=True, size=20, align="left")

    def validate(self):
        ids = [c.attrib["id"] for c in self.root.findall("mxCell")]
        assert len(ids) == len(set(ids)), self.code
        for a, b in self.edges:
            assert a in self.nodes and b in self.nodes
        for key, (x, y, w, h) in self.nodes.items():
            assert 0 <= x < x + w <= WIDTH and 0 <= y < y + h <= HEIGHT, key
        for cell in self.root.findall("mxCell[@edge='1']"):
            assert cell.find("mxGeometry") is not None


def algorithm2():
    book = Book("algorithm-2-prefix-admission")
    p = book.page("2A", "算法 2：事件入口、独立层准入与计划选择",
                  "按左 → 中 → 右阅读；2B 是候选组子流程，2C 是异步提交/回收流程。暂停备份不会停止正常推理。",
                  ("① 事件与消费者状态", "② 本 tier 是否允许计划", "③ 连续候选与计划结果"))
    p.n(0, "event", "新块完成 / Slack 或引用变化\n容量 / FreeACK / 许可变化：唤醒", 235, source="RevisionRuntime.begin_independent")
    p.n(0, "identity", "校验不可变对象、内容身份与父链\n更新唯一消费者、路由和价值 epoch", 430, 125, source="PrefixPool.register_object / update_consumer")
    p.d(0, "active", "请求仍活跃\n且未过期？", 640)
    p.box("done", "否：停止本次准入\n结束 / TTL → 2C", 75, 900, 275, 115, color=GRAY)
    p.box("frontier", "计算 C 与连续前缀 f\n查找第一个缺口", 420, 900, 325, 115, color=BLUE, source="PrefixPool.frontier")
    p.n(0, "reuse", "已有兼容 COMMITTED 前缀：直接关联\n不重复复制 / 计 bytes；更新共享损失", 1110, 135, color=GREEN)
    p.n(0, "tiers", "分别调用 HBM 与 DRAM 准入\n两条复制都从 Source 出发", 1370, 115, color=PURPLE)
    p.e("event", "identity"); p.e("identity", "active")
    p.e("active", "done", "否", out=(.25, .75), color=GRAY)
    p.e("active", "frontier", "是", out=(.75, .75))
    p.e("frontier", "reuse"); p.e("reuse", "tiers")
    p.d(1, "hbm", "本层是 Peer HBM？", 225)
    p.d(1, "permit", "算法 3 已给有效许可\n且未暂停复制？", 490)
    p.d(1, "idle", "本 pool 无 pending 组\n且无未确认回收？", 785)
    p.n(1, "continue", "可继续构造本层保护计划", 1050, 100, color=GREEN)
    p.n(1, "paused", "PAUSED：只暂停本 tier 备份\n等新 KV / 价值 / 容量 / 许可事件\n下一次从实际首缺口重评估", 1370, 160, color=AMBER)
    p.e("tiers", "hbm", "本 tier", out=(1, .5), into=(0, .5), points=((790, 1428), (790, 307)))
    p.e("hbm", "permit", "是")
    p.e("hbm", "idle", "DRAM\n直达", out=(1, .5), into=(1, .5), points=((1550, 307), (1550, 867)), color=PURPLE, label_pos=(1505, 670, 90, 80))
    p.e("permit", "idle", "是")
    p.e("permit", "paused", "否", out=(0, .5), into=(0, .3), points=((855, 572), (855, 1418)), color=AMBER)
    p.e("idle", "paused", "否", out=(0, .5), into=(0, .65), points=((875, 867), (875, 1474)), color=AMBER)
    p.e("idle", "continue", "是")
    p.n(2, "enumerate", "从 f+1 起枚举已封口连续组 X\n最多 Gmax；仅使用源仍可读的 KV", 235, 125, source="PrefixPool.plan")
    p.n(2, "subroutine", "子流程 2B：EvaluateGroup(X)\n可行性 → 删除闭包 → 当前联合损失", 460, 125, color=PURPLE)
    p.d(2, "more", "还有可枚举的候选终点？", 680)
    p.d(2, "best", "存在严格改善的可行组？", 955)
    p.n(2, "select", "选择最终 Φ 最小的计划\n平手：复制 bytes 更少；仍平手保留先者", 1200, 110)
    p.d(2, "begin", "begin 再校验快照\n与资源通过？", 1370, 155, source="PrefixPool.begin")
    p.box("stale", "陈旧计划：重新评估\n↩ 2A", 1645, 1550, 300, 75, color=AMBER, size=22)
    p.box("pending", "预留 X / PENDING\n旧 C 保留 → 2C", 2005, 1550, 310, 75, color=GREEN, size=22)
    p.e("continue", "enumerate", out=(1, .5), into=(0, .5), points=((1590, 1100), (1590, 298)))
    p.e("enumerate", "subroutine"); p.e("subroutine", "more")
    p.e("more", "enumerate", "下一\n终点", out=(1, .5), into=(1, .5), points=((2340, 762), (2340, 298)), dashed=True, label_pos=(2300, 440, 80, 75))
    p.e("more", "best", "否"); p.e("best", "select", "是"); p.e("select", "begin")
    p.e("best", "paused", "否", out=(0, .5), into=(1, .5), points=((1615, 1037), (1615, 1450)), color=AMBER)
    p.e("begin", "stale", "否", out=(.25, .75), color=AMBER)
    p.e("begin", "pending", "是", out=(.75, .75), color=GREEN)
    p.foot("独立的是 tier 的准入和提交；源、链路等共同物理瓶颈仍共享预算。返回计划 ≠ 已获得可恢复副本。",
           "源码：revision_runtime.py · begin_independent；prefix_frontier.py · plan / begin / frontier")

    p = book.page("2B", "算法 2：连续候选组与共享删除闭包",
                  "本页针对一个 X；输出可行计划或拒绝当前组，再返回 2A 继续枚举。所有 victims 都只是预览，尚未物理删除。",
                  ("① 候选组的资源与时限", "② 选择安全的删除闭包", "③ 比较完整最终状态"))
    p.n(0, "input", "输入：X、当前 C、Q、S、源可读范围\n以及 copy budget / lease / deadline", 235, 125)
    p.n(0, "compatible", "已完成、不可变、父链和 namespace 兼容\n源 lease / 目标放置 / 分片身份有效", 445, 135, color=PURPLE)
    p.d(0, "source", "源可读且路径许可有效？", 665)
    p.n(0, "constraints", "b(X) ≤ min(S, Bcopy)\nBphysical + b(X) ≤ Q\nt + 预计复制时长 < deadline\ndeadline = min(请求有效期−最短驻留, 许可到期)", 905, 205, size=23)
    p.d(0, "feasible", "容量和完成时限均满足？", 1195)
    p.n(0, "reject", "当前 X 不可行 → 2A 下一候选\n若缺少源前缀：本次停止继续延长组", 1470, 120, color=AMBER)
    p.e("input", "compatible"); p.e("compatible", "source")
    p.e("source", "constraints", "是")
    p.e("source", "reject", "否", out=(0, .5), into=(0, .3), points=((65, 747), (65, 1506)), color=AMBER)
    p.e("constraints", "feasible")
    p.e("feasible", "reject", "否", out=(0, .5), into=(0, .7), points=((85, 1277), (85, 1554)), color=AMBER)
    p.n(1, "initialize", "C′ ← C；Y ← ∅\n只修改暂定视图，不减物理占用", 235, 115)
    p.d(1, "fits", "b(C′ ∪ X)\n≤ max(0, Q−S)？", 435)
    p.n(1, "closures", "枚举已提交根 k 的完整后代闭包 Z\n排除候选祖先与所有 read pin\nbytes 按物理对象去重", 705, 145, source="PrefixPool._closure / _victims")
    p.d(1, "legal", "还存在合法闭包 Z？", 935)
    p.n(1, "density", "重算每个 Z 的当前联合损失 / bytes\n选最小 ρ；平手按 bytes、根 ID 排序", 1180, 125)
    p.n(1, "remove", "C′ ← C′ \\ Z；Y ← Y ∪ Z\n重算受影响消费者的连续前缀\n重新检查容量", 1410, 155)
    p.e("feasible", "initialize", "是", out=(1, .5), into=(0, .5), points=((785, 1277), (785, 292)))
    p.e("initialize", "fits"); p.e("fits", "closures", "否")
    p.e("closures", "legal"); p.e("legal", "density", "是"); p.e("density", "remove")
    p.e("legal", "reject", "否", out=(0, .5), into=(1, .5), points=((820, 1017), (820, 1530)), color=AMBER)
    p.e("remove", "fits", "下一轮", out=(0, .5), into=(0, .5), points=((865, 1487), (865, 517)), dashed=True, label_pos=(820, 1100, 90, 50))
    p.n(2, "state", "计算最终提交状态\nCafter = (C \\ Y) ∪ X", 235, 115)
    p.n(2, "phi", "Φ(C,t) = Σ活跃调用 wi · [Ti(fi(C))−si(t)]₊\nT 包含完整重算这一合法退路\n物理 bytes 去重；不同真实调用各计一次\n结束轮和未知未来轮不产生活跃收益", 445, 205, size=23, color=PURPLE, source="PrefixPool.harm")
    p.d(2, "improves", "Δ = Φ(C,t)−Φ(Cafter,t)\n严格大于 η？", 760, 175)
    p.box("accepted", "是：收录 (X,Y)\n返回 2A 继续比较", 1640, 1030, 320, 115, color=GREEN)
    p.box("nonpositive", "否：不收录当前 X\n返回 2A 下一候选", 2015, 1030, 320, 115, color=AMBER)
    p.n(2, "rationale", "为何不再维护逐块历史 credit\n每次删除都重算前缀损失；尾块低价值\n不代表此前所有块都应立即删除。\n\n零收益首块可与后续已生成块成组。\nGmax / staging 有界：不保证全局最优。", 1280, 285, color=GRAY, size=24)
    p.e("fits", "state", "是", out=(1, .5), into=(0, .5), points=((1585, 517), (1585, 292)))
    p.e("state", "phi"); p.e("phi", "improves")
    p.e("improves", "accepted", "是", out=(.25, .75), color=GREEN)
    p.e("improves", "nonpositive", "否", out=(.75, .75), color=AMBER)
    p.foot("闭包密度 ρ(Z) = [ Φ((C′ \\ Z) ∪ X,t) − Φ(C′ ∪ X,t) ] / b(Z)；收益必须比较完整状态，不能简单相加逐块分数。",
           "源码：prefix_frontier.py · plan / _victims / _closure / harm；外部接入负责真实 source lease 与 placement 校验")

    p = book.page("2C", "算法 2：异步提交、物理回收与多轮共享",
                  "左列处理一个复制组；中列 R 是所有撤销/取消共用的 FreeACK 协议；右列处理消费者复用与结束。",
                  ("① PENDING → 提交或中止", "② R：回收确认与物理账本", "③ 多轮引用与前缀复用"))
    p.n(0, "pending", "进入：begin 已在 Q 内预留 X\nPENDING 不可恢复，旧 C 仍可读", 235, 115)
    p.n(0, "copy", "按 3B 逐批复制、保持源 lease\n按 (对象, 分片) 去重收 ACK\n非法 ACK 拒绝；终态迟到 ACK 忽略", 435, 145)
    p.d(0, "failed", "组失败 / deadline 到期\n或被撤销？", 645)
    p.d(0, "allack", "所有预期分片 ACK 齐全？", 900)
    p.d(0, "valid", "finish 再校验通过？\nepoch / route / layout / 时限\nlease / 配额 / 当前 Δ > η", 1150, 200, source="PrefixPool.finish")
    p.box("abort", "ABORTED：旧 C 不变\nX → R 取消/回收", 65, 1470, 310, 115, color=RED)
    p.box("commit", "原子发布 (C \\ Y) ∪ X\nCOMMITTED；Y → R", 435, 1470, 325, 115, color=GREEN)
    p.e("pending", "copy"); p.e("copy", "failed"); p.e("failed", "allack", "否")
    p.e("failed", "abort", "是", out=(0, .5), into=(0, .35), points=((60, 727), (60, 1510)), color=RED)
    p.e("allack", "copy", "否：等\nACK", out=(0, .5), into=(0, .5), points=((90, 982), (90, 497)), dashed=True, label_pos=(45, 820, 90, 70))
    p.e("allack", "valid", "是")
    p.e("valid", "abort", "否", out=(.25, .75), color=RED)
    p.e("valid", "commit", "是", out=(.75, .75), color=GREEN)
    p.n(1, "r", "R：替换 victims Y / 失败组 X\n压力撤销 / 最后引用过期的对象", 235, 125)
    p.n(1, "queue", "保留每个对象的 reclaim ID / generation\n撤销恢复可见性，禁止新读\n仍计入 RECLAIMING 物理占用", 455, 150, source="PrefixPool._queue_reclaim / reclaim_tasks")
    p.d(1, "fenced", "所有读和 DMA 已完成\n或取消已有确认？", 705)
    p.box("waitreads", "否：重试取消 / 等待\n超时 ≠ 已结束 DMA", 860, 955, 305, 120, color=AMBER)
    p.box("free", "是：请求 Worker\n实际释放物理分配", 1220, 955, 315, 120, color=BLUE)
    p.d(1, "freeack", "收到匹配 generation\n的物理 FreeACK？", 1170)
    p.n(1, "debit", "此时才从物理账本扣除对象 bytes\n旧 / 重复 ACK 不影响新分配\n唤醒 2A 或重做 3A 前台预算", 1440, 145, color=GREEN, source="PrefixPool.acknowledge_free")
    p.e("commit", "r", out=(1, .5), into=(0, .5), points=((800, 1527), (800, 297)), color=GREEN)
    p.e("abort", "r", out=(.5, 1), into=(0, .8), points=((220, 1635), (820, 1635), (820, 335)), color=RED)
    p.e("r", "queue"); p.e("queue", "fenced")
    p.e("fenced", "waitreads", "否", out=(.25, .75), color=AMBER)
    p.e("fenced", "free", "是", out=(.75, .75))
    p.e("waitreads", "fenced", "等取消\nACK", out=(0, .5), into=(0, .5), points=((850, 1015), (850, 787)), dashed=True, color=AMBER, label_pos=(810, 880, 85, 65))
    p.e("free", "freeack")
    p.e("freeack", "queue", "否：\n重发", out=(0, .5), into=(0, .5), points=((840, 1252), (840, 530)), dashed=True, color=AMBER, label_pos=(807, 1090, 80, 65))
    p.e("freeack", "debit", "是", color=GREEN)
    p.n(2, "round", "新轮次：注册唯一消费者\n验证身份，关联已有兼容前缀\n共享对象不重复复制 / 计 bytes", 235, 145)
    p.d(2, "resident", "已生成 KV 全部有\n兼容 COMMITTED 副本？", 440)
    p.box("attach", "无需复制新对象\n直接复用当前连续前缀", 1640, 690, 320, 115, color=GREEN)
    p.box("missing", "已有部分直接复用\n缺口 → 2A 成组准入", 2010, 690, 325, 115, color=PURPLE)
    p.n(2, "sharedvalue", "更新所有活跃消费者的当前 Φ\n一次删除要计算全部受影响用户", 930, 115)
    p.n(2, "end", "轮次结束：移除活跃恢复价值\n可保留零权重、可驱逐的 TTL 引用\nTTL 到期时移除该引用", 1130, 135)
    p.d(2, "last", "无引用、无读取 pin\n且不被存活后代依赖？", 1330, 155)
    p.box("collect", "回收无用对象\n→ R 的 FreeACK 协议", 1640, 1510, 320, 90, color=RED, size=23)
    p.box("retain", "保留共享依赖 / 读取占用\n结束一轮不会立即删除", 2010, 1510, 325, 90, color=GREEN, size=23)
    p.e("round", "resident")
    p.e("resident", "attach", "是", out=(.25, .75), color=GREEN)
    p.e("resident", "missing", "否", out=(.75, .75), color=PURPLE)
    p.e("attach", "sharedvalue"); p.e("missing", "sharedvalue", "准入 / 暂停", dashed=True)
    p.e("sharedvalue", "end", "结束或 TTL 事件", dashed=True)
    p.e("end", "last"); p.e("last", "collect", "是", out=(.25, .75), color=RED)
    p.e("last", "retain", "否", out=(.75, .75), color=GREEN)
    p.foot("Bphysical = Bcommitted + Bcopying + Breclaiming。普通替换失败保留旧 C；硬前台收缩允许撤销保护，但不能提前复用物理地址。",
           "源码：prefix_frontier.py · acknowledge_shard / finish / acknowledge_free / collect_expired；watchdog 见 3B")
    return book


def algorithm3():
    book = Book("algorithm-3-foreground-budget")
    p = book.page("3A", "算法 3：从前台预留推导可撤销 HBM 额度",
                  "先验证观测与物理账本，再计算可借 bytes；α = Q / Mregistered 是输出。快速收缩，按真实时间限速扩张。",
                  ("① 观测身份与物理对账", "② 安全上界与认证域", "③ 收缩 / 保持 / 扩张"))
    p.n(0, "event", "初始 Q=0；新请求 / token step\n恢复预留 / 有效样本 / watchdog", 235, 115)
    p.d(0, "identity", "epoch / sequence / payload\n与上一报告的关系？", 465, 190)
    p.box("duplicate", "完全重复：返回原决定\n不重复收缩或重放副作用", 60, 750, 300, 125, color=GRAY)
    p.box("stale", "过期 / 冲突：拒绝\n新 epoch 禁保护并对账", 445, 750, 310, 125, color=RED)
    p.d(0, "ledger", "占用与回收债务\n匹配 pool 物理账本？", 1030, 175)
    p.box("mismatch", "拒绝观测，不更新状态\n接入方暂停保护并对账", 60, 1320, 300, 130, color=RED)
    p.box("new", "新序号且时间单调\n再检查样本有效性和新鲜度", 445, 1320, 310, 130, color=GREEN)
    p.e("event", "identity")
    p.e("identity", "duplicate", "完全重复", out=(.25, .75), color=GRAY)
    p.e("identity", "stale", "过期 / 冲突", out=(.75, .75), color=RED)
    p.e("identity", "ledger", "新的报告", points=((400, 920),))
    p.e("ledger", "mismatch", "否", out=(.25, .75), color=RED)
    p.e("ledger", "new", "是", out=(.75, .75), color=GREEN)
    p.n(1, "memory", "H = max(0, Mphys − Mfixed − Mprimary\n                        − Mnext − Rburst − Ralloc)\nQmem = min(Mreg, Qpolicy, Lalloc, H)\n\n各项互不重复；Mnext 只指本次新增\nLalloc 来自真实可借页，不是 CUDA free\nRburst 覆盖取消和 FreeACK 前的增长", 235, 305, color=PURPLE, size=23, source="MemoryEnvelope.backup_limit")
    p.d(1, "healthy", "样本有效且新鲜？\n无前台违约？\n认证域 / 证书有效？", 665, 195)
    p.n(1, "cap", "Q* = min(Qmem, Qcert, D)\nD 含值得保留的保护、新组和 staging\n首次 / 采样断档 / 认证域变化：\n重置稳定起点；本次 Δt = 0", 1010, 205)
    p.n(1, "zero", "Q ← 0；清空稳定计时\n停止新 HBM 批次，撤销保护额度\n已占用 bytes 等取消 / FreeACK 后归还", 1400, 175, color=RED)
    p.e("new", "memory", out=(1, .5), into=(0, .5), points=((790, 1385), (790, 387)))
    p.e("memory", "healthy"); p.e("healthy", "cap", "是")
    p.e("healthy", "zero", "否", out=(0, .5), into=(0, .5), points=((860, 762), (860, 1487)), color=RED)
    p.d(2, "shrink", "Q* < 当前 Q？", 235)
    p.box("checkgrowth", "否：先保持当前 Q\n继续检查扩张条件", 1640, 490, 320, 115)
    p.box("contract", "是：立即 Q ← Q*\n重置稳定计时", 2020, 490, 310, 115, color=RED)
    p.d(2, "grow", "稳定时长 ≥ Tstable？\n回收债务=0 且 Bphys≤Q？\n有增量需求 Q*>Q？", 780, 195)
    p.box("increase", "Q ← min(Q*, Q + vgrow·Δt)\n按 bytes/s 限制增长", 1640, 1100, 325, 120, color=GREEN, size=23)
    p.box("hold", "保持 Q\n等待有效状态变化", 2020, 1100, 310, 120, color=AMBER)
    p.n(2, "publish", "发布 Q 与 α = Q / Mreg\npause：不健康 / Q=0 / Bphys>Q / 有回收债务\n许可到期 = min(证书到期, 样本时间+最大年龄)\n配额、复制速率、单批大小 → 3B", 1390, 200, color=PURPLE, size=22, source="ForegroundBudget.observe")
    p.e("cap", "shrink", out=(1, .5), into=(0, .5), points=((1590, 1112), (1590, 317)))
    p.e("shrink", "checkgrowth", "否", out=(.25, .75))
    p.e("shrink", "contract", "是", out=(.75, .75), color=RED)
    p.e("checkgrowth", "grow")
    p.e("grow", "increase", "是", out=(.25, .75), color=GREEN)
    p.e("grow", "hold", "否", out=(.75, .75), color=AMBER)
    p.e("increase", "publish", color=GREEN); p.e("hold", "publish", color=AMBER)
    p.e("contract", "publish", out=(1, .5), into=(1, .3), points=((2350, 547), (2350, 1450)), color=RED)
    p.e("zero", "publish", out=(1, .5), into=(0, .5), color=RED)
    p.foot("有效认证：profile/region 匹配、证书未到期、释放时限满足配置；TTFT / TPOT / goodput 损失上界均 ≤ ε。默认 ε=1%，仍需实测认证。",
           "源码：foreground_budget.py · MemoryEnvelope / _certificate_valid / observe；revision_runtime.py · observe_foreground")

    p = book.page("3B", "算法 3：额度执行、共享传输预算与 watchdog",
                  "三列是互相触发的事件处理器，不要求全局串行。前台依据真实可用内存开始，复制逐批检查，超时走明确取消/ACK 协议。",
                  ("① 执行配额与前台资源检查", "② 每个 DMA 批次的许可", "③ 超时、TTL 与读取 lease"))
    p.n(0, "decision", "接收 3A 的新 publication\n完全重复消息不重放同一副作用", 235, 115)
    p.d(0, "enforce", "Q 已改变，或 committed\n超出 max(0,Q−S)？", 445)
    p.n(0, "setquota", "set_quota：中止 pending，撤销安全闭包\nHBM 可独立回收，无须先有 DRAM 副本\n读取 pin 阻止该对象被立即删除", 720, 150, color=RED, source="PrefixPool.set_quota")
    p.n(0, "reclaim", "RECLAIMING 仍计物理占用\n按算法 2C-R 重发取消 / free 任务\nFreeACK 后才可把 bytes 借给前台", 985, 145, color=AMBER)
    p.d(0, "foreground", "样本仍有效，且 Bphys\n不超过当前内存安全上界？", 1220, 175)
    p.box("allocate", "是：允许进入前台分配\n接入 allocator 仍须原子预留", 60, 1500, 315, 100, color=GREEN, size=23)
    p.box("waitmemory", "否：等待真实释放或新观测\n不得使用未释放的地址", 435, 1500, 325, 100, color=AMBER, size=23)
    p.e("decision", "enforce"); p.e("enforce", "setquota", "是", color=RED)
    p.e("enforce", "foreground", "否", out=(1, .5), into=(1, .5), points=((790, 527), (790, 1307)))
    p.e("setquota", "reclaim"); p.e("reclaim", "foreground")
    p.e("foreground", "allocate", "是", out=(.25, .75), color=GREEN)
    p.e("foreground", "waitmemory", "否", out=(.75, .75), color=AMBER)
    p.n(1, "batch", "算法 2 的组复制拆为有界 DMA 批\n每个物理瓶颈只有一个共享 bucket", 235, 120)
    p.d(1, "hbmblocked", "HBM 且无有效额度\n或已暂停 / 超过单批上限？", 455, 175)
    p.d(1, "tokens", "路径 token / 单批上限满足？\nHBM 另需治理器 token\n所有许可均未过期？", 740, 190, source="TransferBudget.take")
    p.n(1, "take", "一次性扣减路径的全部资源 token\n任一资源不足：一项也不扣减", 1040, 120)
    p.n(1, "dma", "启动有界 DMA，完成后收集 shard ACK\n下一批重新检查；已耗服务 token 不退\n整组齐全 / 失败 → 2C", 1270, 155, color=GREEN)
    p.n(1, "waittokens", "等待许可 / token / ACK 事件\n不阻塞前台；组到期则取消 → 2C", 1485, 110, color=AMBER)
    p.e("batch", "hbmblocked"); p.e("hbmblocked", "tokens", "否（含 DRAM）")
    p.e("hbmblocked", "waittokens", "是", out=(0, .5), into=(0, .3), points=((850, 542), (850, 1518)), color=AMBER)
    p.e("tokens", "waittokens", "否", out=(0, .5), into=(0, .7), points=((875, 835), (875, 1562)), color=AMBER)
    p.e("tokens", "take", "是"); p.e("take", "dma", color=GREEN)
    p.e("dma", "hbmblocked", "下一批", out=(1, .5), into=(1, .5), points=((1550, 1347), (1550, 542)), dashed=True, label_pos=(1505, 960, 95, 55))
    p.e("waittokens", "hbmblocked", "重试", out=(1, .5), into=(1, .25), points=((1585, 1540), (1585, 499)), dashed=True, color=AMBER, label_pos=(1545, 1190, 80, 55))
    p.n(2, "timer", "独立 watchdog 事件\n定时器不是一条新的健康样本", 235, 115, color=PURPLE)
    p.n(2, "timeout", "① pending deadline 到期：中止复制组\n旧 C 保留；组占用等取消 / FreeACK\n未到期则保持 pending", 455, 145, color=RED)
    p.n(2, "ttl", "② TTL 到期：删除到期消费者引用\n仅回收无剩余引用且未 pinned 的对象\n物理回收沿用 2C-R", 710, 140)
    p.n(2, "reads", "③ read lease 到期：返回待取消 ID\n恢复先预留 primary，才能获取源 read lease\n到期不代表 DMA 结束，不直接 free\nread-done / cancel ACK 后才解除 pin", 950, 200, color=AMBER, size=23)
    p.n(2, "expired", "④ 许可到期：保留原 sample 时间\n新 sequence + valid=false → 3A\n不制造健康样本、不积累稳定时间", 1250, 160, color=RED, source="RevisionRuntime.watchdog")
    p.n(2, "scope", "无域内认证 ⇒ 不启用新 HBM 保护\n有内存余量 ≠ 已证明推理零干扰\n实测证书由接入/校准方提供", 1500, 105, color=GRAY, size=23)
    p.e("timer", "timeout"); p.e("timeout", "ttl"); p.e("ttl", "reads"); p.e("reads", "expired")
    p.foot("两算法闭环：3A 授权 → 2A/2B 计划 → 3B 批次许可 → 2C 提交/释放 ACK → 新观测回 3A；配额决策与物理兑现必须分开。",
           "源码：revision_runtime.py · observe_foreground / copy_batch / watchdog；prefix_frontier.py · set_quota / acquire_read")
    return book


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_exports_and_combine(books: list[Book]) -> dict:
    """Check official exports and assemble a reading copy without rerendering."""
    import pymupdf
    from PIL import Image

    combined = pymupdf.open()
    checks = {}
    toc = []
    for book in books:
        source = OUT / (book.stem + ".drawio")
        expected = [p.code for p in book.pages]
        readback = ET.parse(source).getroot()
        assert [p.get("id") for p in readback.findall("diagram")] == expected
        with pymupdf.open(str(source) + ".pdf") as doc:
            assert len(doc) == len(expected)
            embedded_text = unquote(doc.metadata["subject"])
            # Desktop 31.1.5 may retain PDF literal-string escapes around
            # parentheses in the URL-encoded subject. Normalize transport only;
            # assert the exact original XML before replacing the metadata.
            if embedded_text != source.read_text():
                assert embedded_text.replace("\\(", "(").replace("\\)", ")") == source.read_text()
                metadata = {k: v for k, v in doc.metadata.items()
                            if k not in {"format", "encryption"}}
                metadata["subject"] = quote(source.read_text(), safe="")
                metadata["title"] = book.stem
                doc.set_metadata(metadata)
                doc.saveIncr()
            embedded = ET.fromstring(unquote(doc.metadata["subject"]))
            assert ET.tostring(embedded) == ET.tostring(readback), "PDF source mismatch"
            for index, page in enumerate(doc):
                assert expected[index] in page.get_text() and "算法" in page.get_text()
                assert all(page.rect.contains(pymupdf.Rect(block[:4]))
                           for block in page.get_text("blocks")), "PDF text outside page"
                toc.append([1, book.pages[index].code + " " + book.pages[index].root.find(
                    "mxCell[@id='title']").get("value").split("  |  ", 1)[1],
                            len(combined) + index + 1])
            combined.insert_pdf(doc)
        combined.embfile_add(source.name, source.read_bytes(), filename=source.name,
                             desc="Editable Draw.io source")
        png_checks = {}
        for code in expected:
            with Image.open(OUT / (code.lower() + ".png")) as im:
                xml = ET.fromstring(unquote(im.info["mxGraphModel"]))
                assert [p.get("id") for p in xml.findall("diagram")] == [code]
                assert im.width >= 3000 and im.height >= 2200
                png_checks[code] = {"pixels": list(im.size), "embedded_page": "PASS"}
        checks[book.stem] = {"pages": len(expected), "pdf_embedded_source": "PASS",
                             "searchable_chinese": "PASS", "pdf_text_bounds": "PASS",
                             "png": png_checks}
    combined.set_toc(toc)
    combined.set_metadata({"title": "AegisKV Algorithms 2 and 3 - Revision 3",
                           "subject": "Five-page flowcharts with two editable Draw.io attachments",
                           "creator": "Official Draw.io exports; assembled with PyMuPDF"})
    combined.save(OUT / "algorithms-2-3-complete.pdf", garbage=4, deflate=True)
    combined.close()
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    books = [algorithm2(), algorithm3()]
    for book in books:
        src = book.save()
        if args.export:
            subprocess.run([CLI, "-x", "-f", "pdf", "-e", "-a", "--crop", "-b", "0",
                            "-o", str(src) + ".pdf", str(src)], check=True)
            for number, page in enumerate(book.pages, 1):
                subprocess.run([CLI, "-x", "-f", "png", "-e", "-b", "0", "-s", "1.25",
                                "-p", str(number), "-o", str(OUT / (page.code.lower() + ".png")),
                                str(src)], check=True)
    export_checks = validate_exports_and_combine(books) if args.export else "NOT_RUN"
    inputs = [ROOT / "python/moonkvsim/aegiskv" / (name + ".py") for name in
              ("prefix_frontier", "foreground_budget", "revision_runtime")]
    inputs += [ROOT / "benchmark/AegisKV/docs/patent/ALGORITHMS_2_3_REVISION.md",
               ROOT / "benchmark/AegisKV/paper/sections/algorithm-prefix-admission.tex",
               ROOT / "benchmark/AegisKV/paper/sections/algorithm-foreground-budget.tex"]
    mapping = {p.code: dict(nodes=len(p.nodes), edges=len(p.edges), source_functions=p.sources)
               for book in books for p in book.pages}
    record = {"schema": "aegiskv.algorithm-flows.v3", "date": "2026-09-07",
              "scope": "revision-3 executable reference and required worker/allocator contracts",
              "native_integrated": False, "full_des_integrated": False,
              "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
              "generator_sha256": digest(Path(__file__)), "pages": mapping,
              "output_sha256": {p.name: digest(p) for p in sorted(OUT.iterdir())
                                if p.suffix in {".drawio", ".pdf", ".png"}},
              "xml_checks": "PASS", "export_checks": export_checks,
              "visual_review": "PENDING"}
    (OUT / "MANIFEST.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print("Created 2 editable books, 5 flowchart pages")


if __name__ == "__main__":
    main()
