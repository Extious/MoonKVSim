#!/usr/bin/env python3
"""Draw proposed whole-Agent DAGs; export native editable figures and review views."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET

import fitz

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT, W, H = 1008, 306, 210, 66
INK, EDGE = '#243746', '#70808A'
PALETTE = {
    'researcher': ('#E1EEE8', '#39756A'),
    'analyst': ('#DDEBF3', '#23688D'),
    'writer': ('#F3E5D1', '#9B6428'),
    'investigator': ('#E1EEE8', '#39756A'),
    'developer': ('#DDEBF3', '#23688D'),
    'validator': ('#F3E5D1', '#9B6428'),
}
WORKFLOWS = [
    {
        'id': 'research', 'slug': 'research-report',
        'title': {'zh': '资料驱动的研究报告', 'en': 'Evidence-based research report'},
        'nodes': {
            'A': {'role': 'researcher', 'pos': [24, 74],
                  'label': {'zh': '研究员', 'en': 'Researcher'},
                  'scope': {'zh': '子问题一', 'en': 'Subquestion A'}},
            'B': {'role': 'researcher', 'pos': [24, 196],
                  'label': {'zh': '研究员', 'en': 'Researcher'},
                  'scope': {'zh': '子问题二', 'en': 'Subquestion B'}},
            'C': {'role': 'analyst', 'pos': [394, 74],
                  'label': {'zh': '分析员', 'en': 'Analyst'},
                  'scope': {'zh': '专题分析', 'en': 'Focused analysis'}},
            'D': {'role': 'analyst', 'pos': [394, 196],
                  'label': {'zh': '分析员', 'en': 'Analyst'},
                  'scope': {'zh': '联合评估', 'en': 'Joint assessment'}},
            'E': {'role': 'writer', 'pos': [764, 135],
                  'label': {'zh': '报告作者', 'en': 'Report writer'},
                  'scope': {'zh': '整合与修订', 'en': 'Synthesis / revision'}},
        },
        'dependencies': {'A': [], 'B': [], 'C': ['A'], 'D': ['A', 'B'], 'E': ['C', 'D']},
        'routes': [
            ['A', 'C', .35, .35, []],
            ['A', 'D', .75, .25, [[326, 123.5], [326, 212.5]]],
            ['B', 'D', .60, .60, []],
            ['C', 'E', .50, .25, [[694, 107], [694, 151.5]]],
            ['D', 'E', .50, .75, [[714, 229], [714, 184.5]]],
        ],
    },
    {
        'id': 'software', 'slug': 'software-issue',
        'title': {'zh': '软件问题调查、修复与验证', 'en': 'Software issue investigation, repair and validation'},
        'nodes': {
            'A': {'role': 'investigator', 'pos': [24, 74],
                  'label': {'zh': '调查员', 'en': 'Investigator'},
                  'scope': {'zh': '问题与实现', 'en': 'Issue / source'}},
            'B': {'role': 'investigator', 'pos': [24, 196],
                  'label': {'zh': '调查员', 'en': 'Investigator'},
                  'scope': {'zh': '测试与接口', 'en': 'Tests / interfaces'}},
            'C': {'role': 'developer', 'pos': [274, 74],
                  'label': {'zh': '开发者', 'en': 'Developer'},
                  'scope': {'zh': '修改实现', 'en': 'Implementation'}},
            'D': {'role': 'validator', 'pos': [524, 196],
                  'label': {'zh': '验证员', 'en': 'Validator'},
                  'scope': {'zh': '回归验证', 'en': 'Regression checks'}},
            'E': {'role': 'validator', 'pos': [774, 135],
                  'label': {'zh': '验证员', 'en': 'Validator'},
                  'scope': {'zh': '最终评审', 'en': 'Final review'}},
        },
        'dependencies': {'A': [], 'B': [], 'C': ['A'], 'D': ['B', 'C'], 'E': ['C', 'D']},
        'routes': [
            ['A', 'C', .50, .50, []],
            ['B', 'D', .50, .50, []],
            ['C', 'D', .75, .25, [[504, 123.5], [504, 212.5]]],
            ['C', 'E', .30, .25, [[704, 93.8], [704, 151.5]]],
            ['D', 'E', .50, .75, [[754, 229], [754, 184.5]]],
        ],
    },
]


def vertex(root, ident, text, x, y, w, h, style, parent='1'):
    cell = ET.SubElement(root, 'mxCell', id=ident, value=text, vertex='1', parent=parent, style=style)
    ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), **{'as': 'geometry'})


def route_points(wf, route):
    a, b, sy, ty, bends = route
    ax, ay = wf['nodes'][a]['pos']
    bx, by = wf['nodes'][b]['pos']
    return [(ax + W, ay + H * sy), *map(tuple, bends), (bx, by + H * ty)]


def inspect_structure(wf):
    # Check the supplied dependency contract and the actual source routes separately.
    required = {(a, b) for b, parents in wf['dependencies'].items() for a in parents}
    assert required == {(r[0], r[1]) for r in wf['routes']}
    done, layers = set(), []
    while len(done) < len(wf['nodes']):
        ready = [a for a, parents in wf['dependencies'].items() if a not in done and set(parents) <= done]
        assert ready, 'Cycle or missing predecessor'
        layers.append(ready)
        done.update(ready)
    segments = []
    for route in wf['routes']:
        points = route_points(wf, route)
        assert points[-1][0] - points[-2][0] >= 18, 'Arrow needs an aligned terminal shaft'
        for p, q in zip(points, points[1:]):
            assert abs(p[0] - q[0]) < 1e-8 or abs(p[1] - q[1]) < 1e-8, 'Nonorthogonal route'
            assert q[0] >= p[0], 'Backward horizontal detour'
            for ident, node in wf['nodes'].items():
                x, y = node['pos']
                if p[1] == q[1]:
                    hit = y < p[1] < y + H and max(p[0], q[0]) > x and min(p[0], q[0]) < x + W
                else:
                    hit = x < p[0] < x + W and max(p[1], q[1]) > y and min(p[1], q[1]) < y + H
                assert not hit, f'Route crosses node {ident}'
            segments.append((tuple(route[:2]), p, q))
    for i, (edge, p, q) in enumerate(segments):
        for other, r, s in segments[i + 1:]:
            if edge == other:
                continue
            h1, h2 = p[1] == q[1], r[1] == s[1]
            if h1 == h2:
                collision = (p[1] == r[1] and max(min(p[0], q[0]), min(r[0], s[0])) <= min(max(p[0], q[0]), max(r[0], s[0]))) if h1 else (p[0] == r[0] and max(min(p[1], q[1]), min(r[1], s[1])) <= min(max(p[1], q[1]), max(r[1], s[1])))
            else:
                hp, hq, vp, vq = (p, q, r, s) if h1 else (r, s, p, q)
                collision = min(hp[0], hq[0]) <= vp[0] <= max(hp[0], hq[0]) and min(vp[1], vq[1]) <= hp[1] <= max(vp[1], vq[1])
            assert not collision, f'Intersecting or overlapping routes {edge}, {other}'
    return {'agent_count': len(wf['nodes']), 'role_count': len({n['role'] for n in wf['nodes'].values()}),
            'edge_count': len(required), 'topological_layers_for_audit_only': layers,
            'orthogonal_routes': True, 'edge_node_collisions': 0, 'edge_edge_collisions': 0}


def build(lang):
    font = 'Noto Sans CJK SC' if lang == 'zh' else 'Linux Libertine O'
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    for wf in WORKFLOWS:
        d = ET.SubElement(mx, 'diagram', id=wf['id'], name=wf['title'][lang])
        model = ET.SubElement(d, 'mxGraphModel', page='1', pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background='#FFFFFF')
        root = ET.SubElement(model, 'root')
        ET.SubElement(root, 'mxCell', id='0')
        ET.SubElement(root, 'mxCell', id='1', parent='0')
        text_style = f'html=0;whiteSpace=wrap;fontFamily={font};fontColor={INK};fillColor=none;strokeColor=none;'
        vertex(root, 'canvas', '', 0, 0, WIDTH, HEIGHT, 'fillColor=#FFFFFF;strokeColor=none;')
        vertex(root, 'title', wf['title'][lang], 24, 4, 960, 36, text_style + 'fontSize=29;fontStyle=1;align=left;')
        status = '设计方案 · 尚未执行验证' if lang == 'zh' else 'Proposed design; execution and application quality remain unvalidated'
        vertex(root, 'status', status, 24, 41, 960, 23, text_style + 'fontSize=20;fontColor=#5E6D76;align=left;')
        vertex(root, 'frame', '', 8, 66, 992, 208, 'rounded=1;arcSize=4;fillColor=#FAFBFB;strokeColor=#D8DEE1;strokeWidth=1;')
        for ident, node in wf['nodes'].items():
            x, y = node['pos']
            fill, stroke = PALETTE[node['role']]
            parent = f'agent-{ident}'
            vertex(root, parent, '', x, y, W, H, f'rounded=1;arcSize=5;fillColor={fill};strokeColor={stroke};strokeWidth=1.3;')
            vertex(root, f'id-{ident}', ident, 10, 20, 27, 27, f'ellipse;html=0;fontFamily={font};fontSize=23;fontColor={INK};fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=1;align=center;', parent)
            label_size = 26 if lang == 'zh' else 24
            vertex(root, f'role-{ident}', node['label'][lang], 43, 5, 162, 30, text_style + f'fontSize={label_size};align=center;spacing=0;', parent)
            vertex(root, f'scope-{ident}', node['scope'][lang], 43, 36, 162, 25, text_style + 'fontSize=20;align=center;spacing=0;', parent)
        for a, b, sy, ty, bends in wf['routes']:
            style = f'edgeStyle=none;orthogonal=1;rounded=0;html=0;strokeColor={EDGE};strokeWidth=1.35;endArrow=block;endFill=1;endSize=8;exitX=1;exitY={sy};entryX=0;entryY={ty};exitPerimeter=0;entryPerimeter=0;'
            cell = ET.SubElement(root, 'mxCell', id=f'edge-{a}-{b}', edge='1', parent='1', source=f'agent-{a}', target=f'agent-{b}', style=style)
            geo = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
            if bends:
                arr = ET.SubElement(geo, 'Array', **{'as': 'points'})
                for x, y in bends:
                    ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))
        footer = '节点 = Agent 任务；箭头 = 完成依赖；内部多轮保留各自历史' if lang == 'zh' else 'Node: one Agent task. Edge: completion dependency. Local multi-turn histories stay private.'
        vertex(root, 'footer', footer, 24, 279, 960, 24, text_style + 'fontSize=20;align=left;')
    path = ROOT / f'workflows-{lang}.drawio'
    ET.indent(mx)
    ET.ElementTree(mx).write(path, encoding='utf-8', xml_declaration=True)
    ET.parse(path)
    return path


def render(src, lang):
    native, review = ROOT / 'native', ROOT / 'review'
    native.mkdir(exist_ok=True)
    review.mkdir(exist_ok=True)
    env = dict(os.environ, FONTCONFIG_FILE=str(ROOT / 'fontconfig.conf'))
    metrics = []
    for number, wf in enumerate(WORKFLOWS, 1):
        slug = f'{wf["slug"]}-{lang}'
        for fmt in ('pdf', 'svg', 'png'):
            output = native / f'{slug}.drawio.{fmt}'
            args = ['drawio', '-x', '-f', fmt, '-e', '-p', str(number), '-b', '0', '-o', str(output)]
            if fmt == 'pdf':
                args.append('--crop')
            if fmt == 'png':
                args += ['-s', '2']
            result = subprocess.run(args + [str(src)], env=env, capture_output=True, text=True, timeout=90)
            (native / f'{slug}-{fmt}.log').write_text(result.stdout + result.stderr)
            if result.returncode or not output.exists():
                raise RuntimeError(f'Export failed: {slug}/{fmt}; see native log')
            print(f'Exported {slug}/{fmt}', flush=True)
        # Native PDF keeps the editable source; the placed PDF has explicit 168-mm width.
        with fitz.open(native / f'{slug}.drawio.pdf') as doc, fitz.open() as final:
            width = 168 / 25.4 * 72
            page = final.new_page(width=width, height=doc[0].rect.height * width / doc[0].rect.width)
            page.show_pdf_page(page.rect, doc, 0)
            final.set_metadata({'title': wf['title'][lang], 'subject': 'Proposed custom DAG; not an executed trace or validated workflow', 'creator': 'Draw.io native vector export'})
            final.save(ROOT / f'{slug}.pdf', garbage=4, deflate=True)
        with fitz.open(ROOT / f'{slug}.pdf') as doc:
            page = doc[0]
            page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(ROOT / f'{slug}.png')
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(review / f'{slug}-168mm-color.png')
            page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False).save(review / f'{slug}-168mm-gray.png')
            spans = [s for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for s in line['spans'] if s['text'].strip()]
            minimum = min(s['size'] for s in spans)
            assert minimum >= 9, f'Too small at declared width: {minimum}'
            labels = ''.join(s['text'] for s in spans).replace(' ', '').replace('\n', '')
            for node in wf['nodes'].values():
                assert node['label'][lang].replace(' ', '') in labels, f'Missing or wrapped Agent label: {node}'
            metrics.append({'workflow': wf['id'], 'language': lang, 'width_mm': 168, 'height_mm': page.rect.height / 72 * 25.4, 'minimum_font_pt': minimum})
    return metrics


def main():
    audit = {wf['id']: inspect_structure(wf) for wf in WORKFLOWS}
    contract = {'evidence_level': 'PROPOSED_DESIGN_NOT_EXECUTED', 'captured_calls': 0,
                'semantics': {'node': 'whole Agent task', 'edge': 'all predecessor tasks must complete',
                              'scheduling': 'each dependency-ready Agent may start; no global level barrier',
                              'internal_rounds': 'task-driven; counts and compatible prefix reuse require execution validation',
                              'tool_time': 'not measured for this design; software tests may be long'},
                'workflows': WORKFLOWS}
    (ROOT / 'workflow-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')
    metrics = []
    for lang in ('zh', 'en'):
        metrics.extend(render(build(lang), lang))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.iterdir() if p.suffix in {'.drawio', '.pdf', '.png'}}
    (ROOT / 'review' / 'checks.json').write_text(json.dumps({'scope': 'Diagram structure and rendering only; not application execution or quality', 'structure': audit, 'pdf_metrics': metrics, 'sha256': hashes}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
