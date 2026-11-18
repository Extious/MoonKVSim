#!/usr/bin/env python3
"""Native editable Agent-task DAGs, ordered left to right.

Dependencies come from the current application design, not a measured trace.
Only Agent roles and completion dependencies appear in the diagrams.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
CONTRACT = REPO / 'benchmark/AegisKV/docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json'
WIDTH, HEIGHT = 1008, 488
NODE_W, NODE_H = 184, 82
FONT = 'Linux Libertine O,FandolSong'
INK, EDGE = '#24323B', '#53636B'
COLORS = {
    'analysis': ('#EAF4F1', '#4D8074'),
    'synthesis': ('#EDF2F8', '#647F9E'),
    'final': ('#FCF2E4', '#AC864B'),
}
PANELS = [
    {
        'id': 'research', 'title': '(a) 软件市场研究报告',
        'slug': 'software-market-research-workflow',
        'roles': {'A': '产品研究', 'B': '用户与场景', 'C': '商业与市场',
                  'D': '产品与场景匹配', 'E': '竞争定位',
                  'F': '需求缺口与趋势', 'G': '报告编辑'},
        'positions': {'C': (24, 80), 'A': (24, 216), 'B': (24, 352),
                      'E': (276, 80), 'D': (276, 284),
                      'F': (528, 284), 'G': (780, 216)},
        'routes': {
            ('C', 'E'): (.5, .5, []),
            ('A', 'E'): (.35, .75, [(248, 244.7), (248, 141.5)]),
            ('A', 'D'): (.65, .25, [(232, 269.3), (232, 304.5)]),
            ('B', 'D'): (.35, .75, [(252, 380.7), (252, 345.5)]),
            ('B', 'F'): (.65, .75, [(504, 405.3), (504, 345.5)]),
            ('D', 'F'): (.5, .5, []),
            ('E', 'G'): (.5, .25, [(744, 121), (744, 236.5)]),
            ('F', 'G'): (.5, .75, [(728, 325), (728, 277.5)]),
        },
        'final': 'G',
    },
    {
        'id': 'review', 'title': '(b) 代码仓库变更评审',
        'slug': 'repository-change-review-workflow',
        'roles': {'A': '行为与接口', 'B': '实现与调用关系', 'C': '现有测试与覆盖',
                  'D': '根因分析', 'E': '兼容与回归风险',
                  'F': '改动方案', 'G': '回归测试方案', 'H': '最终评审'},
        'positions': {'A': (24, 80), 'B': (24, 216), 'C': (24, 352),
                      'D': (276, 80), 'E': (276, 352),
                      'F': (528, 80), 'G': (528, 216), 'H': (780, 216)},
        'routes': {
            ('A', 'D'): (.5, .5, []),
            ('B', 'D'): (.35, .75, [(240, 244.7), (240, 141.5)]),
            ('B', 'E'): (.65, .25, [(252, 269.3), (252, 372.5)]),
            ('C', 'E'): (.5, .5, []),
            ('D', 'F'): (.5, .5, []),
            ('D', 'G'): (.75, .25, [(500, 141.5), (500, 236.5)]),
            ('C', 'G'): (.65, .75, [(232, 405.3), (232, 456),
                                   (504, 456), (504, 277.5)]),
            ('E', 'H'): (.5, .75, [(744, 393), (744, 277.5)]),
            ('F', 'H'): (.5, .25, [(728, 121), (728, 236.5)]),
            ('G', 'H'): (.5, .5, []),
        },
        'final': 'H',
    },
]


def vertex(root, ident, value, box, style):
    cell = ET.SubElement(root, 'mxCell', id=ident, value=value,
                         vertex='1', parent='1', style=style)
    x, y, w, h = box
    ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w),
                  height=str(h), **{'as': 'geometry'})


def build():
    design = json.loads(CONTRACT.read_text())
    mxfile = ET.Element('mxfile', host='app.diagrams.net', type='device')
    for panel in PANELS:
        diagram = ET.SubElement(mxfile, 'diagram', id=panel['id'], name=panel['title'])
        model = ET.SubElement(diagram, 'mxGraphModel', grid='1', gridSize='10',
                              page='1', pageWidth=str(WIDTH), pageHeight=str(HEIGHT),
                              background='#FFFFFF', math='0')
        root = ET.SubElement(model, 'root')
        ET.SubElement(root, 'mxCell', id='0')
        ET.SubElement(root, 'mxCell', id='1', parent='0')
        vertex(root, 'canvas', '', (0, 0, WIDTH, HEIGHT),
               'rounded=0;fillColor=#FFFFFF;strokeColor=none;')
        vertex(root, 'title', panel['title'], (24, 14, 940, 36),
               f'html=0;whiteSpace=wrap;fontFamily={FONT};fontSize=26;'
               f'fontColor={INK};fontStyle=1;align=left;verticalAlign=middle;'
               'fillColor=none;strokeColor=none;spacing=0;')
        for letter, (x, y) in panel['positions'].items():
            group = 'analysis' if letter in 'ABC' else 'final' if letter == panel['final'] else 'synthesis'
            fill, stroke = COLORS[group]
            vertex(root, f'agent-{letter}', f'{letter}\n{panel["roles"][letter]}',
                   (x, y, NODE_W, NODE_H),
                   f'rounded=1;arcSize=9;whiteSpace=wrap;html=0;fontFamily={FONT};'
                   f'fontSize=22;fontColor={INK};align=center;verticalAlign=middle;'
                   f'fillColor={fill};strokeColor={stroke};strokeWidth=1.6;spacing=6;')
        graph = design['dependencies'][panel['id']]
        required = {(a, b) for b, parents in graph.items() for a in parents}
        assert set(panel['routes']) == required
        for (a, b), (exit_y, entry_y, points) in panel['routes'].items():
            cell = ET.SubElement(root, 'mxCell', id=f'dependency-{a}-{b}', value='',
                                 edge='1', parent='1', source=f'agent-{a}', target=f'agent-{b}',
                                 style=f'html=0;rounded=0;strokeColor={EDGE};strokeWidth=1.65;'
                                 'endArrow=block;endFill=1;endSize=6;jumpStyle=arc;jumpSize=10;'
                                 f'exitX=1;exitY={exit_y};exitPerimeter=0;'
                                 f'entryX=0;entryY={entry_y};entryPerimeter=0;')
            geo = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
            if points:
                arr = ET.SubElement(geo, 'Array', **{'as': 'points'})
                for px, py in points:
                    ET.SubElement(arr, 'mxPoint', x=str(px), y=str(py))
    if hasattr(ET, 'indent'):
        ET.indent(mxfile)
    dest = ROOT / 'sources/application-workflows.drawio'
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(mxfile).write(dest, encoding='utf-8', xml_declaration=True)
    contract = {
        'scope': 'Agent roles and task-completion dependencies only',
        'direction': 'left_to_right', 'target_width_mm': 168,
        'evidence_level': 'project_authored_application_design_not_measured_trace',
        'dependencies_source': str(CONTRACT.relative_to(REPO)),
        'dependencies_source_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        'semantics': 'All required predecessor Agent tasks finish before the successor becomes ready; no whole-layer barrier.',
        'internal_invocations': 'Agent-local consecutive multi-round calls; deliberately omitted from diagram.',
        'workflows': [dict(id=p['id'], title=p['title'], slug=p['slug'], roles=p['roles'],
                           dependencies=design['dependencies'][p['id']]) for p in PANELS],
    }
    (dest.parent / 'figure-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')
    print(dest)


if __name__ == '__main__':
    build()
