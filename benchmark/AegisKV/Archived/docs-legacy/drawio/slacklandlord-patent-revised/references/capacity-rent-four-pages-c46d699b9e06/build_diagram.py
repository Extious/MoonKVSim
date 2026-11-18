#!/usr/bin/env python3
"""Four editable pages for the 2026-09-08 capacity-rent design.

Native Draw.io exports are authoritative. The old cumulative-rent diagram is
preserved under references; this generator never changes the patent or runtime.
"""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import subprocess
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
DESIGN = OUT.parent.parent / 'algorithm-2'
STEM = 'algorithm-2-patent-revised'
SOURCE = OUT / (STEM + '.drawio')
CLI = '/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
STYLE = OUT.parent / 'algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio'
REFERENCE = OUT / 'references/user-edited-19ff14bc521a.drawio'
PREVIOUS = OUT / 'references/previous-cumulative-rent-136d94493763.drawio'
PATENT = ROOT / 'benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx'
FONT = 'Noto Sans CJK SC'
INK, BLUE, GREEN, AMBER, RED, MUTED = '#23384B', '#2E6FA8', '#118575', '#B17A1D', '#AE4B45', '#657B90'
PALE_BLUE, PALE_GREEN, PALE_AMBER, PALE_RED, GRAY = '#EDF4FD', '#EDF8F4', '#FFF7E8', '#FCEEEB', '#F3F5F8'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
book = ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
pages = []


class Page:
    def __init__(self, key, name, height, width=2400):
        self.key, self.name, self.W, self.H = key, name, width, height
        page = ET.SubElement(book, 'diagram', id=key, name=name)
        graph = ET.SubElement(page, 'mxGraphModel', math='1', grid='0', gridSize='10',
                              page='1', pageWidth=str(width), pageHeight=str(height), background='#FFFFFF')
        self.root = ET.SubElement(graph, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.nodes, self.edges, self.formulas = {}, [], {}
        self.box('canvas', '', 0, 0, width, height, stroke='none')
        pages.append(self)

    def uid(self, key):
        return f'sla-{self.key}-{key}'

    def box(self, key, value, x, y, w, h, *, size=27, text=False, decision=False,
            fill='#FFFFFF', stroke=INK, color=INK, bold=False, dashed=False,
            align='center', parent=None, container=False):
        assert key not in self.nodes, key
        style = (f'fontFamily={FONT};fontSize={size};fontColor={color};whiteSpace=wrap;html=1;'
                 f'align={align};verticalAlign=middle;spacing=12;strokeWidth=2;')
        if text:
            style += 'text;strokeColor=none;fillColor=none;'
        else:
            style += f'fillColor={fill};strokeColor={stroke};'
            style += 'rhombus;' if decision else 'rounded=1;arcSize=9;'
        if bold:
            style += 'fontStyle=1;'
        if dashed:
            style += 'dashed=1;dashPattern=7 5;'
        if container:
            style += 'container=1;pointerEvents=0;'
        if key == 'canvas':
            style += 'locked=1;connectable=0;'
        value_html = '<div style="line-height:1.4">' + escape(value).replace('\n', '<br>') + '</div>'
        c = ET.SubElement(self.root, 'mxCell', id=self.uid(key), value=value_html, style=style,
                          vertex='1', parent=self.uid(parent) if parent else '1')
        px, py = self.nodes[parent][:2] if parent else (0, 0)
        ET.SubElement(c, 'mxGeometry', x=str(x-px), y=str(y-py), width=str(w), height=str(h),
                      attrib={'as': 'geometry'})
        self.nodes[key] = (x, y, w, h)
        if r'\(' in value:
            self.formulas[key] = value
        return c

    def panel(self, key, title, x, y, w, h):
        self.box(key, '', x, y, w, h, container=True, stroke='#C1CEDB')
        self.box(key+'-title', title, x+20, y+12, w-40, 65,
                 text=True, size=29, bold=True, color=BLUE, align='left', parent=key)
        return key

    def edge(self, source, target, *, out=(.5, 1), into=(.5, 0), points=(),
             text='', at=None, color=BLUE, dashed=False, arrow=True):
        key = f'edge-{len(self.edges)}'
        style = (f'edgeStyle=orthogonalEdgeStyle;rounded=0;strokeColor={color};strokeWidth=2.4;'
                 f'endArrow={"block" if arrow else "none"};endFill=1;endSize=9;jettySize=20;'
                 f'exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};'
                 'jumpStyle=arc;jumpSize=9;')
        if dashed:
            style += 'dashed=1;dashPattern=6 4;'
        c = ET.SubElement(self.root, 'mxCell', id=self.uid(key), style=style,
                          edge='1', parent='1', source=self.uid(source), target=self.uid(target))
        g = ET.SubElement(c, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
        if points:
            arr = ET.SubElement(g, 'Array', attrib={'as': 'points'})
            for x, y in points:
                ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))
        self.edges.append((source, target))
        if text:
            assert at
            cell = self.box(key+'-label', text, *at, text=True, size=24, color=color)
            cell.set('style', cell.get('style') + 'fillColor=#FFFFFF;spacing=1;')

    def title(self, title, subtitle):
        self.box('title', title, 60, 30, self.W-120, 75, size=40, bold=True,
                 text=True, color=INK, align='left')
        self.box('subtitle', subtitle, 60, 115, self.W-120, 70, size=26,
                 text=True, color=MUTED, align='left')

    def footer(self, value, height=95):
        self.box('footer', value, 60, self.H-height-25, self.W-120, height,
                 text=True, size=22, color=MUTED, align='left')

    def validate(self):
        cells = self.root.findall('mxCell')
        ids = [c.get('id') for c in cells]
        assert len(ids) == len(set(ids))
        for c in cells:
            assert c.get('id') in ('0', '1') or c.get('id').startswith('sla-')
            for name in ('parent', 'source', 'target'):
                assert c.get(name) is None or c.get(name) in ids
            if c.get('edge') == '1':
                assert c.find('mxGeometry').get('relative') == '1'
            elif c.get('vertex') == '1':
                key = c.get('id').removeprefix(f'sla-{self.key}-')
                x, y, w, h = self.nodes[key]
                assert 0 <= x < x+w <= self.W and 0 <= y < y+h <= self.H, (key, x, y, w, h)
                parent = c.get('parent')
                if parent != '1':
                    pk = parent.removeprefix(f'sla-{self.key}-')
                    px, py, pw, ph = self.nodes[pk]
                    assert px <= x and py <= y and x+w <= px+pw and y+h <= py+ph, (key, pk)
        return {'cells': len(cells), 'edges': len(self.edges),
                'formula_nodes': list(self.formulas), 'page_size': [self.W, self.H]}


def page_agents():
    p = Page('agents', '1 · Agent、共享 KV 与容量', 1930)
    p.title('SlackLandlord  ·  容量租金版', 'Agent 提供本轮工作流信息；Request 生产 KV；Peer HBM Pool 按物理 chunk 分配与回收。')
    p.box('scope', '算法 3 给定可用容量 C；算法 2 比较当前备份的 WCT 收益。\n本版使用容量价格 λ；旧版累计 L、租值键 H 与分账续租不在本图中执行。',
          60, 210, 2280, 115, fill=PALE_BLUE, stroke=BLUE, color=BLUE, size=27)
    a = p.panel('agents-panel', 'Agent / 当前执行分支', 60, 385, 540, 665)
    for name, y, slack, rnd in [('A', 475, 8, 3), ('B', 655, 3, 2), ('C', 835, 12, 1)]:
        p.box('agent-'+name, f'Agent {name} · 第 {rnd} 轮\n本轮 Slack = {slack} ms\nKV 路径 + 工作流节点 + 版本',
              85, y, 490, 145, parent=a, size=26, fill=GRAY, stroke='#A6B7C8')
    r = p.panel('references', '逻辑引用：多个 Agent 可以指向同一物理前缀', 665, 385, 1675, 665)
    p.box('reference-note', '蓝色 P1 / P2 是共享对象；A5 已完整生成，但复制尚未完成。',
          690, 460, 1605, 65, text=True, color=MUTED, size=25, align='left', parent=r)
    rows = [('A', 560, ['P1', 'P2', 'A3', 'A4', 'A5']),
            ('B', 730, ['P1', 'P2', 'B3']), ('C', 900, ['C1', 'C2', 'C3', 'C4'])]
    for agent, y, keys in rows:
        p.box('row-'+agent, 'Agent '+agent, 700, y, 180, 85, text=True, bold=True, parent=r)
        for j, key in enumerate(keys):
            pending = key == 'A5'
            p.box('ref-'+agent+'-'+key, key+('\nCOPYING' if pending else ''),
                  915+j*270, y, 230, 85, parent=r, size=26,
                  fill=PALE_AMBER if pending else PALE_BLUE if key[0] == 'P' else '#FFFFFF',
                  stroke=AMBER if pending else BLUE, dashed=pending)
            if j:
                p.edge('ref-'+agent+'-'+keys[j-1], 'ref-'+agent+'-'+key,
                       out=(1, .5), into=(0, .5), color=MUTED)
        p.edge('agent-'+agent, 'row-'+agent, out=(1, .5), into=(0, .5),
               points=((625, y+42.5),), color=MUTED, dashed=True)
    physical = p.panel('physical', 'Pool 物理占用：共享对象只存一份', 60, 1110, 1440, 435)
    for j, key in enumerate(['P1', 'P2', 'A3', 'A4', 'B3', 'C1', 'C2', 'C3', 'C4', 'A5']):
        pending = key == 'A5'
        p.box('physical-'+key, key+('\nCOPYING' if pending else ''),
              95+(j % 5)*280, 1220+(j//5)*120, 250, 85, parent=physical, size=25,
              fill=PALE_AMBER if pending else PALE_BLUE if key[0] == 'P' else PALE_GREEN,
              stroke=AMBER if pending else BLUE if key[0] == 'P' else GREEN, dashed=pending)
    p.box('physical-note', 'S 包含 9 个已提交块；A5 另占 1 块空间。\n恢复仅使用 S 中的连续前缀；内部共享块有后继时不能单独删除。',
          85, 1450, 1390, 80, text=True, parent=physical, size=24, color=MUTED)
    states = p.panel('state-panel', 'Pool 需要维护的状态', 1560, 1110, 780, 435)
    p.box('state', '容量与物理分配记录\nCOMMITTED / COPYING / RETIRING\n固定读取引用与分配代次\nAgent 前缀、工作流版本、收益缓存',
          1590, 1200, 720, 205, parent=states, size=27, fill=GRAY, stroke='#A6B7C8')
    p.box('state-note', '不为每块保存一份固定收益信用。\n只有对应的释放 ACK 才减少实际占用。',
          1590, 1425, 720, 95, parent=states, text=True, color=MUTED, size=24)
    steps = [
        ('round', '新请求开始\n替换该 Agent 的本轮输入\n本轮生成过程中不调整 Slack'),
        ('produce', '生成完整 chunk\n发布可读源与前缀关系\n进入第 2 页的容量决策'),
        ('ack', '备份提交 / 读取结束\n更新恢复前沿与固定引用\n合并新事件，再次决策')]
    for j, (key, value) in enumerate(steps):
        p.box(key, value, 60+j*795, 1630, 690, 150, size=26, fill=PALE_BLUE, stroke=BLUE)
        if j:
            p.edge(steps[j-1][0], key, out=(1, .5), into=(0, .5))
    p.footer('C：算法 3 发布的备份可用容量；S：已提交的物理备份集合。\n第 2 页：准入与回收；第 3 页：WCT 收益；第 4 页：容量租金与 Lazy Refresh。')


def page_flow():
    p = Page('flow', '2 · KV 备份准入与回收', 2940)
    p.title('算法 2  ·  KV 备份决策流程', '主流程沿一列向下；比较合法前缀组合。Peer HBM 容量有限，备份复制的带宽干扰暂不计入目标。')
    p.box('event', '新请求 / 新完整 chunk / 引用变化 / 容量变化', 425, 215, 1060, 105,
          fill=PALE_BLUE, stroke=BLUE)
    p.box('snapshot', '① 更新 Agent、工作流与可读源\n纯价值更新可合并；源、布局、固定引用或容量变化立即使旧事务失效\n尚有复制或实际释放未完成时，暂缓新事务',
          385, 400, 1140, 180, size=26, stroke=BLUE, fill=PALE_BLUE)
    p.box('feasible', '② 固定读取引用、连续前缀与容量\n能同时满足吗？', 560, 665, 790, 180,
          decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('infeasible', 'DEFER\n停止新分配\n等待引用解除\n或实际回收',
          50, 675, 270, 165, size=25, fill=GRAY, stroke=MUTED)
    p.box('solve', '③ 选择合法备份组合 S′\n复用未变组件；完整组件表 + 整数动态规划\n计算超预算 → 第 4 页的有界搜索\n'+r'\(\max F(S^\prime)\quad\mathrm{s.t.}\ b(S^\prime)\le C\)',
          385, 950, 1140, 210, size=26, stroke=BLUE, fill=PALE_BLUE)
    p.box('accept', '④ 满足本次执行条件？\n正常：模式允许且 '+r'\(F(S^\prime)>F(S)\)'+'\n缩额：已找到合法回收方案',
          505, 1270, 900, 225, size=26, decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('keep', 'KEEP / DEFER\n没有更好方案则保留\n精确模式未证最优\n则暂缓',
          40, 1300, 280, 175, size=24, fill=GRAY, stroke=MUTED)
    p.box('revoke', '⑤ 重验版本并撤销拟淘汰后缀的恢复可见性\n受害块进入 RETIRING，发起实际释放\n仍计入物理占用；已删除的旧副本不会自动回滚',
          385, 1590, 1140, 180, size=26, stroke=BLUE, fill=PALE_BLUE)
    p.box('freed', '⑥ 所需空间已经\n收到实际释放 ACK？', 580, 1880, 750, 165,
          decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('wait-free', '等待释放 ACK\n保留实际占用记录\nACK 后再检查⑥',
          40, 1885, 280, 155, size=24, fill=GRAY, stroke=MUTED)
    p.box('copy', '⑦ 空间足够后才分配并复制新增块\nCOPYING 占用容量，尚不能用于恢复\n纯回收没有新增复制，直接满足下一步完成条件',
          385, 2140, 1140, 165, size=26, fill=PALE_BLUE, stroke=BLUE)
    p.box('ack', '⑧ 全部分片成功，\n且发布版本有效？', 580, 2395, 750, 170,
          decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('wait-copy', '等待剩余分片\n重复 ACK\n不代替其他分片',
          40, 2400, 280, 155, size=24, fill=GRAY, stroke=MUTED)
    p.box('abort', 'ABORTED\n撤销新副本；等待对应分配代次的释放 ACK\n迟到 copy ACK / 旧 free ACK 均不生效',
          1625, 2385, 715, 180, size=25, fill=PALE_RED, stroke=RED, color=RED)
    p.box('commit', '⑨ 发布连续 COMMITTED 前缀\n更新 Agent 恢复前沿；发布合并的价值更新，进入下一次决策',
          385, 2670, 1140, 145, size=27, fill=PALE_GREEN, stroke=GREEN, color=GREEN)
    for a, b in [('event', 'snapshot'), ('snapshot', 'feasible'), ('feasible', 'solve'),
                 ('solve', 'accept'), ('accept', 'revoke'), ('revoke', 'freed'),
                 ('freed', 'copy'), ('copy', 'ack'), ('ack', 'commit')]:
        at = {'feasible': (970, 870, 80, 45), 'accept': (970, 1515, 80, 45),
              'freed': (970, 2060, 80, 45), 'ack': (970, 2590, 80, 45)}.get(a)
        p.edge(a, b, text='是' if at else '', at=at)
    for a, b, label, y in [('feasible', 'infeasible', '否', 700),
                            ('accept', 'keep', '否', 1315),
                            ('freed', 'wait-free', '否', 1910),
                            ('ack', 'wait-copy', '未齐', 2430)]:
        p.edge(a, b, out=(0, .5), into=(1, .5), text=label,
               at=(345, y, 115, 45), color=MUTED)
    p.edge('ack', 'abort', out=(1, .5), into=(0, .5), text='失败 / 失效',
           at=(1360, 2420, 245, 50), color=RED)
    example = p.panel('example', '容量竞争：删尾后仍保留短前缀', 1625, 215, 715, 765)
    p.box('example-input', '容量 6 MiB；每块 2 MiB\nA 的累计收益：0、1、3、6 ms\nB1 的收益：4 ms',
          1645, 305, 675, 135, size=25, text=True, parent=example)
    for row, y, names, gain in [('before', 505, ['A1', 'A2', 'A3'], 6),
                              ('after', 720, ['A1', 'A2', 'B1'], 7)]:
        p.box(row+'-label', ('当前 S' if row == 'before' else '候选 S′')+f'：收益 {gain} ms',
              1645, y-65, 675, 50, text=True, size=26, bold=True, parent=example)
        for j, name in enumerate(names):
            p.box(row+'-'+name, name, 1665+j*215, y, 185, 80, parent=example,
                  fill=PALE_GREEN if name == 'B1' else PALE_BLUE,
                  stroke=GREEN if name == 'B1' else BLUE)
        if row == 'after':
            p.box('example-result', '删 A3 损失 3 ms，新增 B1 收益 4 ms\n'+r'\(\Delta F=7-6=1\ \mathrm{ms}\)'+'\n继续删除 A2 会再损失 2 ms，没有必要。',
                  1645, 830, 675, 130, text=True, size=24, parent=example, color=GREEN)
    mode = p.panel('modes', '两种求解模式', 1625, 1060, 715, 560)
    p.box('mode-online', '有限预算模式\n只采用已经精算、容量合法的改善方案\n同时报告尚未闭合的最优性差距',
          1650, 1145, 665, 170, size=25, parent=mode, fill=PALE_BLUE, stroke=BLUE)
    p.box('mode-exact', '精确模式\n未完成最优性及平局选择证明 → DEFER',
          1650, 1340, 665, 115, size=25, parent=mode, fill=GRAY, stroke=MUTED)
    p.box('mode-shrink', '容量下降：只从已有前缀选子集。\n即使收益下降，也必须完成可行回收。',
          1650, 1475, 665, 115, size=25, text=True, parent=mode, color=AMBER)
    memory = p.panel('memory', '释放与复制期间的物理占用', 1625, 1700, 715, 535)
    for j, (text, fill, stroke) in enumerate([
        ('A3 已撤销，尚未释放：仍占 6 MiB', PALE_RED, RED),
        ('收到 A3 的 free ACK：降至 4 MiB', GRAY, MUTED),
        ('开始复制 B1：占用回到 6 MiB', PALE_AMBER, AMBER)]):
        p.box('physical-step-'+str(j), text, 1650, 1800+j*115, 665, 80,
              parent=memory, size=25, fill=fill, stroke=stroke)
        if j:
            p.edge('physical-step-'+str(j-1), 'physical-step-'+str(j), color=MUTED)
    p.footer('S / S′：当前 / 候选物理备份集合；b：实际字节数；F：第 3 页定义的 WCT 恢复收益。\n收益保证针对已发布快照的提交后状态；复制过渡窗口、实机代价误差另行评估。')


def page_value():
    p = Page('value', '3 · 恢复收益与 KV 示例', 2840)
    p.title('SlackLandlord  ·  从恢复时间计算 WCT 收益', '左侧：收益计算流程；右侧：连续 KV 前缀、恢复时间条与并行工作流示例。')
    p.box('inputs', '① 读取 Agent 的当前完整 KV 与本轮输入\n每条 Agent 路径只有一个连续备份前缀\n恢复代价包含读取、重算和必要同步',
          120, 230, 1140, 165, size=27, fill=PALE_BLUE, stroke=BLUE)
    p.box('time', '② 计算保留前 k 块时的最短恢复时间\n'+
          r'\(T(k)=\min_{0\le j\le k}(T_{\rm load}(j)+T_{\rm recompute}(j)+T_{\rm sync}(j))\)'+'\n读取前 j 块，重算其余已生成 KV；可回退到更短的前缀',
          90, 485, 1200, 185, size=25, fill=PALE_BLUE, stroke=BLUE)
    p.box('slack', '③ 单个受影响 Agent：扣除 Slack 可吸收的延迟\n'+
          r'\(J(k)=[T(k)-s]_+,\qquad U(k)=J(0)-J(k)\)'+'\n'+
          r'\(U(k)=[T(0)-s]_+-[T(k)-s]_+\)',
          90, 765, 1200, 185, size=27, fill=PALE_BLUE, stroke=BLUE)
    p.box('prefix', '④ 按合法前缀变化计算收益或损失\n'+
          r'\(\text{扩展收益}=U(k+m)-U(k)\)'+'\n'+
          r'\(\text{截短损失}=U(k)-U(k-m)\)',
          120, 1045, 1140, 180, size=28, fill=PALE_BLUE, stroke=BLUE)
    p.box('dag', '⑤ 多个 Agent 受影响：在工作流 DAG 中合并\n'+
          r'\(\operatorname{finish}(v)=\max_{u\to v}\operatorname{finish}(u)+d_v+T_v(S)\)'+'\n最大结束时间记为 D；同一工作流内不直接相加 Agent 收益',
          90, 1330, 1200, 195, size=26, fill=PALE_BLUE, stroke=BLUE)
    p.box('objective', '⑥ 与无备份基线比较，再跨工作流和场景求和\n'+
          r'\(F(S)=\sum_f\omega_f\sum_w[D_w(\varnothing,f)-D_w(S,f)]\)'+'\n固定一个故障场景时，权重为 1',
          90, 1630, 1200, 185, size=27, fill=PALE_BLUE, stroke=BLUE)
    p.box('operation', '⑦ 评价当前 S 到候选 S′ 的完整操作\n'+
          r'\(\Delta F=F(S^\prime)-F(S)\)'+'\n'+r'\(\Delta b=b(S^\prime)-b(S)\)'+'\n共享物理容量只计一次；后继依赖必须一起处理',
          120, 1920, 1140, 210, size=28, fill=PALE_BLUE, stroke=BLUE)
    p.box('return', '返回操作收益 ΔF 与容量变化 Δb\n第 2 页执行准入 / 回收；第 4 页计算容量租金与 Credit',
          120, 2250, 1140, 145, size=28, fill=PALE_GREEN, stroke=GREEN, color=GREEN)
    keys = ['inputs', 'time', 'slack', 'prefix', 'dag', 'objective', 'operation', 'return']
    for a, b in zip(keys, keys[1:]):
        p.edge(a, b)
    p.box('slack-threshold', 'Slack 仍然影响收益\n'+r'\(T(0)=12,\ T(1)=8\ \mathrm{ms}\)'+'\nSlack 为 2 / 10 / 15 ms 时，收益分别是 4 / 2 / 0 ms。',
          120, 2470, 1140, 160, size=27, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    plans = p.panel('plans', 'Agent A：Slack = 4 ms；每块 2 MiB', 1360, 230, 980, 1470)
    p.box('costs', '加载每块 2 ms；重算各块为 3 / 4 / 5 ms\n同步为 0；数值用于说明，不是实测结果。',
          1385, 315, 930, 95, text=True, size=25, color=MUTED, parent=plans)
    p.box('load-legend', '蓝：从备份加载', 1400, 445, 280, 65, size=24,
          fill=PALE_BLUE, stroke=BLUE, parent=plans)
    p.box('compute-legend', '橙：重算', 1720, 445, 240, 65, size=24,
          fill=PALE_AMBER, stroke=AMBER, parent=plans)
    p.box('harm-legend', '红：WCT 损失 J', 2000, 445, 305, 65, size=24,
          fill=PALE_RED, stroke=RED, parent=plans)
    values = [(12, 8, 0), (11, 7, 1), (9, 5, 3), (6, 2, 6)]
    for k, (total, loss, gain) in enumerate(values):
        y = 620+k*260
        p.box(f'k{k}-label', f'前缀 k = {k}    累计收益 U = {gain} ms',
              1390, y-65, 925, 50, text=True, align='left', bold=True, size=26, parent=plans)
        for j, recompute in enumerate([3, 4, 5]):
            loaded = j < k
            p.box(f'k{k}-x{j+1}', f'x{j+1}\n'+('加载 2 ms' if loaded else f'重算 {recompute} ms'),
                  1400+j*225, y, 195, 85, size=25, parent=plans,
                  fill=PALE_BLUE if loaded else PALE_AMBER, stroke=BLUE if loaded else AMBER)
            if j:
                p.edge(f'k{k}-x{j}', f'k{k}-x{j+1}', out=(1, .5), into=(0, .5), color=MUTED)
        p.box(f'k{k}-numbers', f'T = {total} ms\nJ = {loss} ms', 2090, y, 220, 85,
              text=True, size=26, bold=True, parent=plans)
        p.box(f'k{k}-slack', 'Slack 4 ms', 1400, y+115, 220, 60, size=22,
              fill='#E4EAF0', stroke='#A3B2C2', parent=plans)
        p.box(f'k{k}-loss', f'{loss} ms', 1620, y+115, 55*loss, 60, size=24,
              fill=PALE_RED, stroke=RED, parent=plans)
    p.box('gain-callout', '从前 2 块扩展到前 3 块：新增收益 6 − 3 = 3 ms\n3 块累计收益为 6 ms，不能把每块都赋值为 6 ms。',
          1390, 1590, 925, 90, text=True, size=25, color=GREEN, parent=plans)
    dag = p.panel('parallel', '同一工作流的并行 Agent：必须经过汇合点', 1360, 1780, 980, 850)
    p.box('parallel-note', 'A / B 各有一块独有 KV；同一次故障影响两者。\n无备份恢复 12 ms，有备份恢复 8 ms。',
          1385, 1870, 930, 95, text=True, size=25, parent=dag, color=MUTED)
    for a, y in [('A', 2010), ('B', 2170)]:
        p.box('branch-'+a, 'Agent '+a+'\n12 → 8 ms', 1410, y, 315, 110,
              size=28, fill=PALE_BLUE, stroke=BLUE, parent=dag)
    p.box('join', '汇合\nmax', 1800, 2100, 140, 110, size=26,
          fill=PALE_AMBER, stroke=AMBER, parent=dag)
    p.box('dag-result', '只备份 A：收益 0\n只备份 B：收益 0\n同时备份：收益 4',
          2010, 2065, 300, 180, size=25, fill=PALE_GREEN, stroke=GREEN, parent=dag)
    p.edge('branch-A', 'join', out=(1, .5), into=(0, .25), points=((1760, 2065),), color=MUTED)
    p.edge('branch-B', 'join', out=(1, .5), into=(0, .75), points=((1760, 2225),), color=MUTED)
    p.edge('join', 'dag-result', out=(1, .5), into=(0, .5), color=GREEN)
    p.box('parallel-explanation', '两条分支一起变快，工作流才提前结束。\n若属于两个独立工作流，总收益才可计为 4 + 4 = 8 ms。\n若它们共享同一物理块，容量仍只计一份。',
          1390, 2350, 920, 185, size=26, text=True, color=MUTED, parent=dag)
    p.footer('T：恢复时间；s：本轮 Slack；J：超过 Slack 的损失；U：单 Agent 前缀收益；[z]₊ = max(z, 0)。\nd：正常参考节点时间；D：工作流完成时间；w / f：工作流 / 故障场景；ω：明确给定的场景权重；F：总恢复收益。', height=130)


def page_lazy():
    p = Page('lazy', '4 · 容量租金与 Lazy Refresh', 2940)
    p.title('SlackLandlord  ·  容量租金与 Lazy Refresh', '求解完成时与完整刷新一致；有限预算时返回可行方案和最优性差距。容量价格用于上界，不单独决定逐块淘汰。')
    p.box('update', '① 新请求或完整 chunk 改变相关输入\n未变工作流复用缓存；结构变化建立新代次\n同一请求中不因生成进度重新估计 Slack',
          300, 235, 1040, 165, size=26, fill=PALE_BLUE, stroke=BLUE)
    p.box('interval', '② 对尚未重算的收益保留有效区间\n'+
          r'\(E_w=\sum_{v\in w}(|\Delta d_v|+\max_{f,k}|\Delta T_v^f(k)|)\)'+'\n'+
          r'\(|F_w^{\rm new}-F_w^{\rm cached}|\le 2\sum E_w\)'+'\n'+
          r'\(\overline F=\min(\text{当前可证上界},F^{\rm cached}+2\sum E_w)\)'+'\nE 为单次扰动界；跨轮按未刷新轮次累加。',
          260, 500, 1120, 270, size=25, fill=PALE_BLUE, stroke=BLUE)
    p.box('bound', '③ 给待验证分支计算收益上界 UB\n'+
          r'\(UB=\overline F(I)+\min_{\lambda\ge0}\{\lambda R+\sum_{x\in X}[u_x-\lambda b_x]_+\}\)'+'\n'+
          r'\(R=C-b(I)\)'+'\n按 u / b 解分数背包，得到该上界的租金 λ\n以合法前缀初始化最好值；将起始分支入队',
          260, 850, 1120, 240, size=24, fill=PALE_BLUE, stroke=BLUE)
    p.box('pop', '④ 取当前 UB 最高的待处理分支', 300, 1170, 1040, 105,
          size=28, fill=PALE_BLUE, stroke=BLUE)
    p.box('possible', '上界仍不低于\n当前已验证的最好收益？',
          430, 1370, 780, 180, size=28, decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('prune', '剪枝\n这个分支\n无需重算',
          30, 1390, 220, 150, size=25, fill=GRAY, stroke=MUTED)
    p.box('refresh', '⑤ 精算当前配置，更新最好可行方案与缓存\n重算上界；不可能改善则剪枝\n否则按 chunk 保留 / 不保留分支，检查前缀与容量\n给子分支设置上界并入队',
          300, 1660, 1040, 185, size=26, fill=PALE_BLUE, stroke=BLUE)
    p.box('loop', '队列非空，\n且仍有计算预算？',
          430, 1960, 780, 180, size=28, decision=True, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    p.box('return', '⑥ 返回当前最好的合法方案及证据\n'+
          r'\(F(S_{\rm found})\le F(S^*)\le UB\)'+'\n'+
          r'\(\mathrm{gap}=UB-F(S_{\rm found})\)'+'\n队列处理完才标记 exact；预算耗尽仍报告差距',
          260, 2260, 1120, 240, size=28, fill=PALE_GREEN, stroke=GREEN, color=GREEN)
    for a, b in [('update', 'interval'), ('interval', 'bound'), ('bound', 'pop'),
                 ('pop', 'possible'), ('possible', 'refresh'), ('refresh', 'loop'), ('loop', 'return')]:
        at = {'possible': (840, 1580, 80, 45), 'loop': (840, 2170, 80, 45)}.get(a)
        p.edge(a, b, text=('是' if a == 'possible' else '否') if at else '', at=at)
    p.edge('possible', 'prune', out=(0, .5), into=(1, .5),
           text='否', at=(275, 1400, 100, 45), color=MUTED)
    p.edge('prune', 'loop', out=(.5, 1), into=(0, .5),
           points=((140, 2050),), color=MUTED)
    p.edge('loop', 'pop', out=(1, .5), into=(1, .5),
           points=((1420, 2050), (1420, 1222.5)), text='是',
           at=(1315, 1975, 95, 45), color=BLUE)
    p.box('implementation', '组件表完整且规模可控时，可直接做整数 DP。\n组件表不完整时不能冒充精确结果；转入以上有界搜索。',
          300, 2610, 1040, 135, text=True, size=26, color=MUTED)
    rent = p.panel('rent', 'Priority 与 Credit 属于合法操作', 1490, 235, 850, 850)
    p.box('delta', r'\(\Delta F=F(S^\prime)-F(S)\)'+'\n'+r'\(\Delta b=b(S^\prime)-b(S)\)',
          1520, 340, 790, 130, parent=rent, size=31, fill=PALE_BLUE, stroke=BLUE)
    p.box('credit', r'\(\mathrm{Credit}(S\to S^\prime;\lambda)=\Delta F-\lambda\Delta b\)',
          1520, 510, 790, 115, parent=rent, size=28, fill=PALE_GREEN, stroke=GREEN, color=GREEN)
    p.box('credit-meaning', 'λ：单位容量的竞争价格，单位 ms/byte。\nCredit：当前操作的净值，单位 ms，可正可负。\n新增操作可报告 ΔF / Δb，不能仅按密度贪心。',
          1520, 650, 790, 155, parent=rent, text=True, size=25, color=MUTED)
    p.box('credit-example', '第 2 页的等容量替换\n'+r'\(\Delta F=1\ \mathrm{ms},\quad \Delta b=0\)'+'\n'+
          r'\(\mathrm{Credit}=1\ \mathrm{ms}\)'+'\n先比较合法组合，不让尾部过期导致整个前缀过期。',
          1520, 835, 790, 220, parent=rent, size=26, fill=PALE_GREEN, stroke=GREEN)
    upper = p.panel('upper', 'u 仅作上界，真实收益仍由 DAG 计算', 1490, 1160, 850, 530)
    p.box('u-definition', r'\(u_x=\sum_f\omega_f\sum_{a:x=a_k}[T_a^f(k-1)-T_a^f(k)]\)'+'\n求和只包含该场景中受影响的引用 Agent。',
          1515, 1240, 800, 130, parent=upper, size=26, text=True)
    p.box('relaxation', '允许分数选择并忽略前缀，仅用于计算上界。\n第 2 页例：u = 1、2、3、4 ms；每块 2 MiB。\n松弛可得 9 ms；合法整数最优解实际为 7 ms。\n租金价格本身不能替代整数选择。',
          1520, 1410, 790, 225, parent=upper, size=26, fill=PALE_AMBER, stroke=AMBER, color=AMBER)
    interval = p.panel('example', 'Lazy 判断：用上界排除无须重算的方案', 1490, 1770, 850, 395)
    p.box('cached', '旧收益\n4 ms', 1520, 1880, 210, 110, parent=interval, size=29, fill=GRAY, stroke=MUTED)
    p.box('range', '本轮 E = 1\n有效区间 [2, 6] ms', 1800, 1880, 505, 110,
          parent=interval, size=27, fill=PALE_BLUE, stroke=BLUE)
    p.edge('cached', 'range', out=(1, .5), into=(0, .5), color=MUTED)
    p.box('prune-example', '若该完整方案没有待添加块：UB = 6 ms。\n已有可行方案收益 7 ms → 直接排除，无须精算。',
          1520, 2030, 790, 100, parent=interval, size=25, text=True, color=GREEN)
    reuse = p.panel('reuse', '跨轮组件复用：只重建发生变化的组件', 1490, 2245, 850, 500)
    for i in range(24):
        changed = i == 0
        p.box('component-'+str(i), str(i+1), 1520+(i % 6)*135, 2350+(i//6)*62,
              105, 45, parent=reuse, size=22, fill=PALE_AMBER if changed else PALE_BLUE,
              stroke=AMBER if changed else BLUE)
    p.box('reuse-result', '1 个更新，23 个复用；WCT 精算 48 → 2 次。\n合成局部更新示例；冷启动 Lazy 未显示普遍收益。',
          1520, 2610, 790, 105, text=True, size=25, parent=reuse, color=MUTED)
    p.footer('I：分支中已决定保留的块；X：待定块；R：剩余字节；u：恢复收益上界；λ：松弛问题的容量价格。\nE：一次兼容更新的节点时间扰动界；UB：仍可能达到的收益上界；gap：已验证收益到上界的差距。\n本图对应独立 CPU 参考设计；旧累计 L / H 分账租金语义未在本版实现。', height=145)


def write_source():
    if SOURCE.exists():
        accepted = {digest(PREVIOUS)}
        if (OUT / 'MANIFEST.json').exists():
            accepted.update(json.loads((OUT / 'MANIFEST.json').read_text()).get('output_sha256', {}).values())
        if digest(SOURCE) not in accepted:
            raise SystemExit('New manual Draw.io edits detected: preserve and incorporate before regenerating.')
    page_agents()
    page_flow()
    page_value()
    page_lazy()
    checks = {p.key: p.validate() for p in pages}
    ET.indent(book)
    ET.ElementTree(book).write(SOURCE, encoding='utf-8', xml_declaration=True)
    record = {
        'status': 'CAPACITY_RENT_REFERENCE_DESIGN_NOT_DEPLOYED',
        'date': '2026-09-08', 'rent_semantics': 'capacity-relaxation price; not cumulative L or agent credit ledger',
        'production_algorithm_code_changed': False, 'patent_docx_changed': False,
        'baseline': {'path': str(PATENT.relative_to(ROOT)), 'sha256': digest(PATENT)},
        'design_sources': {str(q.relative_to(ROOT)): digest(q) for q in
                           [DESIGN/'README.md', DESIGN/'PROOFS.md', DESIGN/'reference.py', DESIGN/'policy.py', DESIGN/'protocol.py']},
        'user_reference': {'path': str(REFERENCE.relative_to(ROOT)), 'sha256': digest(REFERENCE)},
        'previous_diagram': {'path': str(PREVIOUS.relative_to(ROOT)), 'sha256': digest(PREVIOUS)},
        'style_reference': {'path': str(STYLE.relative_to(ROOT)), 'sha256': digest(STYLE)},
        'pages': checks, 'mathjax': True, 'generator_sha256': digest(Path(__file__)),
        'output_sha256': {SOURCE.name: digest(SOURCE)}, 'export_checks': 'PENDING', 'visual_review': 'PENDING'}
    (OUT/'MANIFEST.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('Four native editable pages written.', flush=True)


def export():
    import pymupdf
    from PIL import Image
    record = json.loads((OUT/'MANIFEST.json').read_text())
    assert digest(SOURCE) == record['output_sha256'][SOURCE.name]
    page_names = [(d.get('id'), d.get('name')) for d in ET.parse(SOURCE).getroot().findall('diagram')]
    outputs = [SOURCE]
    pdf = Path(str(SOURCE)+'.pdf')
    subprocess.run([CLI, '-x', '-f', 'pdf', '-e', '-b', '0', '-a', '--crop',
                    '-o', str(pdf), str(SOURCE)], check=True)
    outputs.append(pdf)
    for i, (key, _) in enumerate(page_names, 1):
        dest = OUT/f'{STEM}-{key}.drawio.png'
        subprocess.run([CLI, '-x', '-f', 'png', '-e', '-b', '0', '-s', '1',
                        '-p', str(i), '-o', str(dest), str(SOURCE)], check=True)
        outputs.append(dest)
        print(f'Native page {i}/{len(page_names)} exported: {key}', flush=True)
    preview = OUT/(STEM+'.drawio.png')
    preview.write_bytes((OUT/f'{STEM}-flow.drawio.png').read_bytes())
    outputs.append(preview)
    with pymupdf.open(pdf) as doc:
        assert len(doc) == len(page_names)
        meta = {k: v for k, v in doc.metadata.items() if k not in {'format', 'encryption'}}
        meta.update(title='SlackLandlord: capacity-rent design, 2026-09-08', subject=quote(SOURCE.read_text(), safe=''))
        doc.set_metadata(meta)
        doc.saveIncr()
        assert unquote(doc.metadata['subject']) == SOURCE.read_text()
        for n, (key, title) in enumerate(page_names):
            page = doc[n]
            assert page.get_text().strip()
            assert not any(token in page.get_text() for token in (r'\(', r'\)', r'\mathrm', r'\lambda', r'\sum'))
            for block in page.get_text('blocks'):
                assert page.rect.contains(pymupdf.Rect(block[:4])), (key, block)
            out = OUT/f'{STEM}-{key}.drawio.pdf'
            one = pymupdf.open()
            one.insert_pdf(doc, from_page=n, to_page=n)
            one.set_metadata({'title': title, 'subject': quote(SOURCE.read_text(), safe='')})
            one.save(out)
            one.close()
            outputs.append(out)
    source_pages = ET.parse(SOURCE).getroot().findall('diagram')
    for key, _ in page_names:
        with Image.open(OUT/f'{STEM}-{key}.drawio.png') as im:
            embedded = ET.fromstring(unquote(im.info['mxGraphModel']))
            restored = embedded.findall('diagram')
            assert len(restored) in (1, len(source_pages))
            wanted = {p.get('id'): p for p in source_pages}
            assert len(restored) != 1 or restored[0].get('id') == key
            for after in restored:
                before = wanted[after.get('id')]
                assert before.attrib == after.attrib
                assert [c.attrib for c in before.findall('.//mxCell')] == [c.attrib for c in after.findall('.//mxCell')]
    record['output_sha256'] = {p.name: digest(p) for p in outputs}
    record['export_checks'] = {'pdf_pages': len(page_names), 'pdf_embedded_source': 'PASS',
                               'png_embedded_cells_match_source': 'PASS', 'pdf_text_bounds': 'PASS',
                               'mathjax_without_literal_tex': 'PASS'}
    (OUT/'MANIFEST.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('Native exports and embedded-source checks passed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xml-only', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args()
    if not args.export_only:
        write_source()
    if not args.xml_only:
        export()
