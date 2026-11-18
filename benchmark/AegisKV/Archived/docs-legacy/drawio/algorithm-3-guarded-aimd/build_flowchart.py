#!/usr/bin/env python3
"""Single-window AIMD: two external inputs, native MathJax formula labels."""
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
STEM = 'algorithm-3-guarded-aimd'
FONT = 'Noto Sans CJK SC'
W, H = 1800, 1830
INK, BLUE, TEAL, AMBER, GRAY = '#19334A', '#2865A1', '#177D6E', '#A36A18', '#617488'
FILL = {INK: '#F3F6FA', BLUE: '#EDF4FD', TEAL: '#ECF8F3', AMBER: '#FFF7E8', GRAY: '#F4F6F8'}
book = ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
page = ET.SubElement(book, 'diagram', id='window-aimd', name='算法三 · 双输入单窗口决策')
graph = ET.SubElement(page, 'mxGraphModel', math='1', grid='1', gridSize='10', page='1',
                      pageWidth=str(W), pageHeight=str(H), background='#FFFFFF')
root = ET.SubElement(graph, 'root')
ET.SubElement(root, 'mxCell', id='0')
ET.SubElement(root, 'mxCell', id='1', parent='0')
nodes, edges = {}, []


def label_html(value):
    return '<div style="line-height:1.55">' + escape(value).replace('\n', '<br>') + '</div>'


def box(key, value, x, y, w, h, *, color=INK, size=25, bold=False,
        text=False, decision=False, align='center', group=False, parent='1'):
    style = (f'fontFamily={FONT};fontSize={size};fontColor={color};whiteSpace=wrap;'
             f'html=1;align={align};verticalAlign=middle;spacing=14;strokeWidth=2;')
    if text:
        style += 'text;strokeColor=none;fillColor=none;'
    else:
        style += f'strokeColor={color};fillColor={FILL[color]};'
        style += 'rhombus;' if decision else 'rounded=1;arcSize=10;'
    if bold:
        style += 'fontStyle=1;'
    if group:
        style += 'container=1;pointerEvents=0;'
    px, py = x, y
    if parent != '1':
        px -= nodes[parent][0]
        py -= nodes[parent][1]
    cell = ET.SubElement(root, 'mxCell', id=key, value=label_html(value), style=style, vertex='1', parent=parent)
    ET.SubElement(cell, 'mxGeometry', x=str(px), y=str(py), width=str(w), height=str(h), attrib={'as': 'geometry'})
    nodes[key] = (x, y, w, h)


def edge(source, target, *, out=(.5, 1), into=(.5, 0), points=(), color=BLUE,
         label='', label_box=None):
    key = f'edge-{len(edges)}'
    style = (f'edgeStyle=orthogonalEdgeStyle;rounded=0;strokeColor={color};strokeWidth=3;'
             'endArrow=block;endFill=1;endSize=11;jettySize=25;'
             f'exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};'
             'exitPerimeter=1;entryPerimeter=1;')
    cell = ET.SubElement(root, 'mxCell', id=key, style=style, edge='1', parent='1', source=source, target=target)
    geom = ET.SubElement(cell, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
    if points:
        arr = ET.SubElement(geom, 'Array', attrib={'as': 'points'})
        for x, y in points:
            ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))
    edges.append((source, target))
    if label:
        assert label_box is not None
        box(key + '-label', label, *label_box, text=True, color=color, size=24)
        root[-1].set('style', root[-1].get('style') + 'fillColor=#FFFFFF;spacing=2;')


box('canvas', '', 0, 0, W, H)
root[-1].set('style', root[-1].get('style') + 'strokeColor=none;fillColor=#FFFFFF;')
box('title', '算法三  ·  一个窗口如何决定 Peer HBM 额度', 45, 25, 1680, 65,
    text=True, bold=True, size=37, align='left')
box('subtitle', '两个外部输入：显存预算限制上限；前台性能反馈驱动 AIMD。每个窗口结束时决策一次。',
    45, 105, 1690, 55, text=True, color=GRAY, size=25, align='left')

box('memory',
    '显存预算 '+r'\(C_t\)'+'\n先为正常 KV、正常缓存和下一窗口增长留出空间\n'
    +r'\(\displaystyle C_t=\min\!\left\{L_t,\,[M_{\mathrm{KV}}-P_t-R_t]_+\right\}\)',
    80, 215, 750, 225, color=BLUE, size=26)
box('feedback',
    '前台性能反馈 '+r'\(e_t\)'+'\n使用按工作量校准的推理 step 时延预警\n'
    +r'\(e_t=1\)'+'：需退让；'+r'\(e_t=0\)'+'：本窗口无预警',
    1040, 215, 690, 225, color=AMBER, size=26)

# Q and z are controller state, not extra external metrics.
box('internal-state', 'AIMD 内部状态\n当前额度 '+r'\(Q_t\)'+'，连续稳定窗口数 '+r'\(z_t\)',
    1110, 520, 600, 90, text=True, color=GRAY, size=25)
box('pressure', '① 本窗口需要退让？\n'+r'\(e_t=1\)',
    665, 650, 490, 185, color=AMBER, decision=True, bold=True, size=26)
box('decrease', '乘性减少\n'+r'\(\widetilde Q_{t+1}=\beta Q_t,\quad 0<\beta<1\)'+'\n稳定窗口计数归零',
    140, 970, 410, 170, color=AMBER, size=25)
box('grow', '② 连续稳定达到 '+r'\(K\)'+' 个窗口\n且允许扩张？',
    650, 965, 520, 190, color=AMBER, decision=True, bold=True, size=25)
box('increase', '加性增加\n'+r'\(\widetilde Q_{t+1}=Q_t+\Delta\)'+'\n'+r'\(\Delta\)'+' 为固定字节步长',
    1310, 985, 410, 170, color=TEAL, size=25)
box('hold', '保持额度\n'+r'\(\widetilde Q_{t+1}=Q_t\)',
    700, 1290, 420, 115, color=GRAY, size=27)
box('output',
    '③ 发布下一窗口额度\n'
    +r'\(\displaystyle Q_{t+1}=\min\!\left\{C_t,\widetilde Q_{t+1}\right\}\)'+'\n'
    +r'\(\displaystyle \alpha_{t+1}=\frac{Q_{t+1}}{M}\)',
    470, 1520, 880, 220, color=BLUE, size=29)

# Budget bypasses the feedback loop and caps the final quota directly.
edge('memory', 'output', out=(0, .5), into=(0, .5),
     points=((45, 327.5), (45, 1630)), color=BLUE,
     label='硬上限', label_box=(12, 1450, 115, 48))
edge('feedback', 'pressure', into=(.5, 0), points=((1385, 485), (910, 485)), color=AMBER)
edge('pressure', 'decrease', out=(0, .5), into=(.5, 0), points=((345, 742.5),),
     color=AMBER, label='是', label_box=(470, 715, 70, 45))
edge('pressure', 'grow', color=BLUE, label='否', label_box=(925, 875, 70, 45))
edge('grow', 'increase', out=(1, .5), into=(0, .5),
     color=TEAL, label='是', label_box=(1205, 1030, 70, 45))
edge('grow', 'hold', color=GRAY, label='否', label_box=(925, 1195, 70, 45))
edge('decrease', 'output', out=(0, .5), into=(.15, 0),
     points=((110, 1055), (110, 1460), (602, 1460)), color=AMBER)
edge('increase', 'output', out=(1, .5), into=(.85, 0),
     points=((1760, 1070), (1760, 1460), (1218, 1460)), color=TEAL)
edge('hold', 'output')

box('separation-note', '同一轮的两项职责\n'+r'\(C_t\)'+' 决定最多借多少\n'+r'\(e_t\)'+' 决定是否乘性退让',
    145, 1210, 430, 160, text=True, color=BLUE, size=24)
box('grow-note', '允许扩张\n'+r'\(C_t>Q_t\)'+'，且有待备份内容\n上次调额已经完成',
    1260, 1220, 450, 160, text=True, color=TEAL, size=24)
box('budget-note',
    r'\(L_t\)'+'：可借总额度；'+r'\(P_t\)'+'：正常占用与预留；'+r'\(R_t\)'+'：窗口及回收期间增长储备；'
    +r'\(M\)'+'：固定分母。',
    105, 1750, 1590, 40, text=True, color=GRAY, size=19)
box('scope-note', '复制限速由执行层处理；本图仅描述窗口额度决策，低干扰效果仍需实验验证。',
    105, 1790, 1590, 35, text=True, color=GRAY, size=19)


def validate():
    assert graph.get('math') == '1'
    cells = root.findall('mxCell')
    ids = [c.get('id') for c in cells]
    assert len(ids) == len(set(ids))
    for cell in cells:
        if cell.get('parent') is not None:
            assert cell.get('parent') in ids
        if cell.get('edge') == '1':
            assert cell.find('mxGeometry') is not None
            assert cell.get('source') in ids and cell.get('target') in ids
    for key, (x, y, w, h) in nodes.items():
        assert 0 <= x < x+w <= W and 0 <= y < y+h <= H, key
    labels = '\n'.join(c.get('value', '') for c in cells)
    assert all(s not in labels for s in ('算法二', '算法 2', 'SlackLandlord', 'FreeACK', 'DMA', 'D_t', '复制余量', 'Q试'))
    assert ('memory', 'output') in edges
    assert ('feedback', 'pressure') in edges
    assert not any(s == 'feedback' and t == 'memory' for s, t in edges)


if __name__ == '__main__':
    validate()
    ET.indent(book)
    path = OUT / f'{STEM}.drawio'
    ET.ElementTree(book).write(path, encoding='utf-8', xml_declaration=True)
    print(path)
