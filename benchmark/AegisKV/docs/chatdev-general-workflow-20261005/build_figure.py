#!/usr/bin/env python3
"""Render the pinned ChatDev template as an editable Agent dependency graph."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import fitz
from PIL import Image
import yaml


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source' / 'general_problem_solving_team.yaml'
COMMIT = '4fb2db0ea90375ce1059f44fe03ffbd191a7a169'
SOURCE_URL = f'https://github.com/OpenBMB/ChatDev/blob/{COMMIT}/yaml_instance/general_problem_solving_team.yaml'
SOURCE_SHA = '5ae158b1bc900b7590c6d90ea2b6c2d29c0f257dc32619b7ed5e910e86d96870'
WIDTH, HEIGHT, W, H = 1008, 604, 180, 100
FONT = 'Noto Sans CJK SC'
INK, EDGE = '#243746', '#70808A'
CRITICAL_INK = '#23688D'
TIMING_DATA = json.loads((ROOT / 'illustrative-slack.json').read_text())
TIMING = {row['agent']: row for row in TIMING_DATA['agents']}
PREDECESSORS = {'A': [], 'B': ['A'], 'C': ['A'], 'D': ['A'], 'E': ['A', 'B', 'C'], 'F': ['B', 'C', 'D', 'E']}
CRITICAL_EDGES = {(a, b) for path in TIMING_DATA['critical_paths'] for a, b in zip(path, path[1:])}
SHORTCUT_EDGES = {('A', 'E'), ('B', 'F'), ('C', 'F')}
NODES = {
    'A': ('Demand Analyze', '需求分析', 20, 248, '#EDF0F2', '#667883'),
    'B': ('Information Searcher', '信息搜集', 280, 84, '#E1EEE8', '#39756A'),
    'C': ('Technician', '技术实现', 280, 248, '#DDEBF3', '#23688D'),
    'D': ('Scheme Generater', '方案生成', 280, 412, '#F3E5D1', '#9B6428'),
    'E': ('Reasoner', '逻辑推理', 550, 248, '#DDEBF3', '#23688D'),
    'F': ('Summary Department', '最终汇总', 806, 248, '#F3E5D1', '#9B6428'),
}
# Each route records real connection ports and an orthogonal path. The B->E
# connection enters E from above so the retained shortcut edges do not cross.
ROUTES = [
    ('A', 'B', (1, .05), (0, .5), [(210, 253), (210, 134)]),
    ('A', 'C', (1, .5), (0, .5), []),
    ('A', 'D', (1, .9), (0, .5), [(240, 338), (240, 462)]),
    ('A', 'E', (1, .2), (0, .15), [(226, 268), (226, 220), (526, 220), (526, 263)]),
    ('B', 'E', (1, .7), (.47, 0), [(634.6, 154)]),
    ('C', 'E', (1, .5), (0, .5), []),
    ('B', 'F', (1, .25), (0, .15), [(770, 109), (770, 263)]),
    ('C', 'F', (1, .85), (0, .82), [(490, 333), (490, 382), (760, 382), (760, 330)]),
    ('D', 'F', (1, .5), (0, .95), [(784, 462), (784, 343)]),
    ('E', 'F', (1, .5), (0, .5), []),
]


def vertex(root, ident, label, x, y, w, h, style, parent='1'):
    cell = ET.SubElement(root, 'mxCell', id=ident, value=label, vertex='1', parent=parent, style=style)
    ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), **{'as': 'geometry'})


def points(route):
    a, b, ap, bp, bends = route
    return [(NODES[a][2] + W * ap[0], NODES[a][3] + H * ap[1]), *bends,
            (NODES[b][2] + W * bp[0], NODES[b][3] + H * bp[1])]


def check_structure(graph):
    source_nodes = {n['id'] for n in graph['nodes']}
    source_edges = {(e['from'], e['to']) for e in graph['edges']}
    assert source_nodes == {n[0] for n in NODES.values()}
    assert source_edges == {(NODES[a][0], NODES[b][0]) for a, b, *_ in ROUTES}
    assert {(a, b) for b, parents in PREDECESSORS.items() for a in parents} == {(a, b) for a, b, *_ in ROUTES}
    assert len(source_edges) == len(ROUTES) == 10
    segments = []
    for route in ROUTES:
        a, b = route[:2]
        for p, q in zip(points(route), points(route)[1:]):
            assert abs(p[0] - q[0]) < 1e-6 or abs(p[1] - q[1]) < 1e-6
            assert p != q
            for ident, (_, _, x, y, *_colors) in NODES.items():
                if ident in {a, b}:
                    continue
                if abs(p[1] - q[1]) < 1e-6:
                    collision = y < p[1] < y + H and max(min(p[0], q[0]), x) < min(max(p[0], q[0]), x + W)
                else:
                    collision = x < p[0] < x + W and max(min(p[1], q[1]), y) < min(max(p[1], q[1]), y + H)
                assert not collision, f'{a}->{b} crosses node {ident}'
            segments.append(((a, b), p, q))
    for i, (edge, p, q) in enumerate(segments):
        for other, r, s in segments[i + 1:]:
            if edge == other:
                continue
            ph, rh = abs(p[1] - q[1]) < 1e-6, abs(r[1] - s[1]) < 1e-6
            if ph == rh:
                axis = 0 if ph else 1
                collision = abs(p[1 - axis] - r[1 - axis]) < 1e-6 and max(min(p[axis], q[axis]), min(r[axis], s[axis])) <= min(max(p[axis], q[axis]), max(r[axis], s[axis]))
            else:
                hp, hq, vp, vq = (p, q, r, s) if ph else (r, s, p, q)
                collision = min(hp[0], hq[0]) <= vp[0] <= max(hp[0], hq[0]) and min(vp[1], vq[1]) <= hp[1] <= max(vp[1], vq[1])
            assert not collision, f'{edge} crosses or overlaps {other}'
    return {'agent_count': 6, 'edge_count': 10, 'matches_pinned_yaml': True,
            'orthogonal_routes': True, 'edge_node_collisions': 0, 'edge_edge_collisions': 0}


def build():
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    diagram = ET.SubElement(mx, 'diagram', id='chatdev-general', name='ChatDev 通用问题解决工作流')
    model = ET.SubElement(diagram, 'mxGraphModel', page='1', pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background='#FFFFFF')
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')
    text = f'html=0;whiteSpace=wrap;fontFamily={FONT};fontColor={INK};fillColor=none;strokeColor=none;'
    vertex(root, 'canvas', '', 0, 0, WIDTH, HEIGHT, 'fillColor=#FFFFFF;strokeColor=none;')
    vertex(root, 'title', 'ChatDev 通用问题解决工作流', 20, 3, 960, 37, text + 'fontSize=29;fontStyle=1;align=left;')
    vertex(root, 'subtitle', '六个 Agent · 十条依赖 · 预设时长示例（WCT = 170 s）', 20, 41, 960, 25, text + 'fontSize=22;fontColor=#5E6D76;align=left;')
    vertex(root, 'frame', '', 8, 72, 992, 456, 'rounded=1;arcSize=4;fillColor=#FAFBFB;strokeColor=#D8DEE1;strokeWidth=1;')
    for ident, (source_id, label, x, y, fill, stroke) in NODES.items():
        parent = f'agent-{ident}'
        node_stroke = CRITICAL_INK if TIMING[ident]['slack_s'] == 0 else stroke
        vertex(root, parent, '', x, y, W, H, f'rounded=1;arcSize=5;fillColor={fill};strokeColor={node_stroke};strokeWidth=1.5;')
        agent = root[-1]
        agent.set('sourceNodeId', source_id)
        vertex(root, f'id-{ident}', ident, 10, 10, 28, 28,
               f'ellipse;html=0;fontFamily={FONT};fontSize=23;fontColor={INK};fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=1;align=center;', parent)
        vertex(root, f'label-{ident}', label, 43, 5, 131, 36, text + 'fontSize=26;align=center;spacing=0;', parent)
        timing = f"t={TIMING[ident]['duration_s']}s   S={TIMING[ident]['slack_s']}s"
        deps = '前驱：' + (','.join(PREDECESSORS[ident]) or '无')
        vertex(root, f'time-{ident}', timing, 8, 43, 164, 25, text + 'fontSize=22;align=center;spacing=0;', parent)
        vertex(root, f'pred-{ident}', deps, 8, 71, 164, 25, text + 'fontSize=22;align=center;spacing=0;', parent)
    for a, b, ap, bp, bends in ROUTES:
        critical, shortcut = (a, b) in CRITICAL_EDGES, (a, b) in SHORTCUT_EDGES
        color, stroke_width = (CRITICAL_INK, 2.5) if critical else (EDGE, 1.5)
        style = f'edgeStyle=none;orthogonal=1;rounded=0;html=0;strokeColor={color};strokeWidth={stroke_width};endArrow=block;endFill=1;endSize=8;exitX={ap[0]};exitY={ap[1]};entryX={bp[0]};entryY={bp[1]};exitPerimeter=0;entryPerimeter=0;'
        if shortcut:
            style += f'dashed=1;dashPattern=5 3;fontFamily={FONT};fontSize=22;fontColor={INK};labelBackgroundColor=#FAFBFB;'
        cell = ET.SubElement(root, 'mxCell', id=f'edge-{a}-{b}', value=f'{a}→{b}' if shortcut else '', edge='1', parent='1', source=f'agent-{a}', target=f'agent-{b}', style=style)
        geo = ET.SubElement(cell, 'mxGeometry', relative='1', y='-12' if shortcut else '0', **{'as': 'geometry'})
        if bends:
            arr = ET.SubElement(geo, 'Array', **{'as': 'points'})
            for x, y in bends:
                ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))
    vertex(root, 'legend-critical', '━━ 关键路径 A→C→E→F', 20, 540, 490, 25, text + f'fontSize=22;fontColor={CRITICAL_INK};align=left;')
    vertex(root, 'legend-other', '━━ 其他依赖   ┄┄ 跨级直接连接', 516, 540, 472, 25, text + 'fontSize=22;align=left;')
    vertex(root, 'footer', '全部箭头均为真实依赖；t = 预设执行时长，S = Slack；非实测。', 20, 574, 960, 25, text + 'fontSize=22;align=left;')
    ET.indent(mx)
    path = ROOT / 'workflow-zh.drawio'
    ET.ElementTree(mx).write(path, encoding='utf-8', xml_declaration=True)
    cells = ET.parse(path).findall('.//mxCell')
    assert len({c.get('id') for c in cells}) == len(cells)
    assert len([c for c in cells if c.get('edge') == '1']) == 10
    return path


def main():
    graph = yaml.safe_load(SOURCE.read_text())['graph']
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA
    structure = check_structure(graph)
    contract = {'source_url': SOURCE_URL, 'source_commit': COMMIT, 'source_sha256': SOURCE_SHA,
                'evidence_level': 'SOURCE_TEMPLATE_DEPENDENCY_GRAPH', 'models_executed': False, 'captured_calls': 0,
                'node_semantics': 'one Agent task, not one model request',
                'edge_semantics': 'original carry_data and trigger dependency',
                'execution_boundary': 'The graph does not certify multi-turn histories, short tool times, or dependency-ready scheduling without layer barriers.',
                'visual_encoding': {'blue_solid': 'critical path under the illustrative durations', 'gray_solid': 'other direct dependency', 'gray_dashed': 'explicit original edge whose precedence is also implied by an indirect path; still a real dependency'},
                'timing_source': 'illustrative-slack.json',
                'nodes': {k: {'source_id': v[0], 'label_zh': v[1]} for k, v in NODES.items()},
                'edges': [{'from': a, 'to': b} for a, b, *_ in ROUTES]}
    (ROOT / 'source-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')
    src = build()
    native, review = ROOT / 'native', ROOT / 'review'
    native.mkdir(exist_ok=True)
    review.mkdir(exist_ok=True)
    cli = shutil.which('drawio') or '/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
    for fmt in ('pdf', 'png'):
        out = native / f'workflow-zh.drawio.{fmt}'
        args = [cli, '-x', '-f', fmt, '-e', '-b', '0', '-o', str(out)]
        args += ['--crop'] if fmt == 'pdf' else ['-s', '2']
        result = subprocess.run(args + [str(src)], capture_output=True, text=True, timeout=90, env=dict(os.environ))
        (native / f'{fmt}-export.log').write_text(result.stdout + result.stderr)
        if result.returncode or not out.exists():
            raise RuntimeError(f'Draw.io {fmt} export failed; see export log')
        print(f'Exported native {fmt}', flush=True)
    with Image.open(native / 'workflow-zh.drawio.png') as im:
        payload = im.info.get('mxGraphModel') or im.info.get('mxfile')
        assert payload, 'PNG is missing its editable embedded source'
        embedded = ET.fromstring(unquote(payload))
        assert len(embedded.findall('.//mxCell[@edge="1"]')) == 10
        assert ET.tostring(embedded) == ET.tostring(ET.parse(src).getroot()), 'Embedded PNG source differs from the delivered source'
    with fitz.open(native / 'workflow-zh.drawio.pdf') as original, fitz.open() as final:
        width = 168 / 25.4 * 72
        page = final.new_page(width=width, height=original[0].rect.height * width / original[0].rect.width)
        page.show_pdf_page(page.rect, original, 0)
        final.set_metadata({'title': 'ChatDev 通用问题解决工作流', 'subject': f'Agent dependency graph of the pinned ChatDev template {COMMIT}; not a measured execution trace', 'creator': 'Draw.io native vector export'})
        final.save(ROOT / 'workflow-zh.pdf', garbage=4, deflate=True)
    with fitz.open(ROOT / 'workflow-zh.pdf') as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(ROOT / 'workflow-zh.png')
        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(review / 'workflow-168mm-color.png')
        page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False).save(review / 'workflow-168mm-gray.png')
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        min_font = min(s['size'] for s in spans)
        assert min_font >= 10
        labels = ''.join(s['text'] for s in spans).replace(' ', '')
        assert all(n[1] in labels for n in NODES.values()), 'Missing or wrapped Agent labels'
        for ident, parents in PREDECESSORS.items():
            assert ('前驱：' + (','.join(parents) or '无')) in labels, f'Missing predecessor label for {ident}'
            timing = f"t={TIMING[ident]['duration_s']}sS={TIMING[ident]['slack_s']}s"
            assert timing in labels, f'Missing timing annotation for {ident}'
        assert all(f'{a}→{b}' in labels for a, b in SHORTCUT_EDGES)
        metrics = {'width_mm': 168, 'height_mm': page.rect.height / 72 * 25.4, 'minimum_font_pt': min_font}
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*') if p.suffix in {'.drawio', '.png', '.pdf'}}
    audit = {'scope': 'Source correspondence and diagram rendering only', 'structure': structure,
             'pdf_metrics': metrics, 'embedded_png_source_checked': True, 'sha256': hashes,
             'visual_review': 'PENDING'}
    (review / 'checks.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'structure': structure, 'pdf_metrics': metrics}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
