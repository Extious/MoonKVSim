#!/usr/bin/env python3
"""Two editable pages for the 2026-09-08 Agent rental SlackLandlord policy.

Native Draw.io exports are authoritative. Previous diagram sources are
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
PREVIOUS = OUT / 'references/user-edited-before-agent-priority-0cb1e5eeb7ba.drawio'
PATENT = ROOT / 'benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx'
FONT = 'Noto Sans CJK SC'
INK = BLUE = GREEN = AMBER = RED = MUTED = '#000000'
PALE_BLUE = PALE_GREEN = PALE_AMBER = PALE_RED = GRAY = '#FFFFFF'
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
        color, fill = '#000000', '#FFFFFF'
        stroke = 'none' if stroke == 'none' else '#000000'
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

    def shift_body(self, dy):
        """Make room for the opening legend; children keep relative geometry."""
        for c in self.root.findall('mxCell'):
            if c.get('vertex') == '1':
                key = c.get('id').removeprefix(f'sla-{self.key}-')
                if key in ('canvas', 'title', 'subtitle'):
                    continue
                x, y, w, h = self.nodes[key]
                self.nodes[key] = (x, y+dy, w, h)
                if c.get('parent') == '1':
                    g = c.find('mxGeometry')
                    g.set('y', str(float(g.get('y'))+dy))
            elif c.get('edge') == '1':
                for point in c.findall('.//mxPoint'):
                    point.set('y', str(float(point.get('y'))+dy))

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
    p.title('SlackLandlord  ·  Agent 级 KV 管理', 'Agent 提供本轮工作流信息；Request 生产 KV；Peer HBM Pool 按物理 chunk 分配与回收。')
    p.box('scope', r'\(C\)：算法 3 给定的备份可用容量；\(a\)：Agent；\(s_a\)：该 Agent 的本轮 Slack。'+'\n算法 2 以恢复 WCT 收益分配备份；新请求只更新对应 Agent 的本轮输入。',
          60, 210, 2280, 115, fill=PALE_BLUE, stroke=BLUE, color=BLUE, size=27)
    a = p.panel('agents-panel', 'Agent / 当前执行分支', 60, 385, 540, 665)
    for name, y, slack, rnd in [('A', 475, 8, 3), ('B', 655, 3, 2), ('C', 835, 12, 1)]:
        p.box('agent-'+name, f'Agent {name} · 第 {rnd} 轮\n本轮 Slack = {slack} ms\nKV 路径 + 工作流节点 + 版本',
              85, y, 490, 145, parent=a, size=26, fill=GRAY, stroke='#A6B7C8')
    r = p.panel('references', '逻辑引用：多个 Agent 可以指向同一物理前缀', 665, 385, 1675, 665)
    p.box('reference-note', 'P1 / P2 是共享对象；虚线 A5 已完整生成，但复制尚未完成。',
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
    p.box('physical-note', 'Pool 包含 9 个已提交块；A5 另占 1 块空间。\n恢复仅使用已提交的连续前缀；内部共享块有后继时不能单独删除。',
          85, 1450, 1390, 80, text=True, parent=physical, size=24, color=MUTED)
    states = p.panel('state-panel', 'Pool 需要维护的状态', 1560, 1110, 780, 435)
    p.box('state', '容量与物理分配记录\nCOMMITTED / COPYING / RETIRING\n固定读取引用与分配代次\nAgent 子租约余额与已兑现轮号',
          1590, 1200, 720, 205, parent=states, size=27, fill=GRAY, stroke='#A6B7C8')
    p.box('state-note', '每个 Agent 单独续租；物理块只收一份租金。\n只有释放 ACK 才减少实际占用。',
          1590, 1425, 720, 95, parent=states, text=True, color=MUTED, size=24)
    steps = [
        ('round', '新请求开始\n替换本轮输入，登记一次续租资格\n本轮生成过程中不调整 Slack'),
        ('produce', '生成完整 chunk\n发布可读源与前缀关系\n进入第 2 页的容量决策'),
        ('ack', '请求结束：保留 Agent 的租约\nAgent 结束：撤销自己的份额\n共享物理块按尾块规则回收')]
    for j, (key, value) in enumerate(steps):
        p.box(key, value, 60+j*795, 1630, 690, 150, size=26, fill=PALE_BLUE, stroke=BLUE)
        if j:
            p.edge(steps[j-1][0], key, out=(1, .5), into=(0, .5))
    p.footer('第 2 页：逐块准入与收租。内部前缀 / 固定读取块保存剩余信用；成为可释放尾块后继续收租。', height=55)


def page_flow():
    from rental_flow import draw_rental_flow
    draw_rental_flow(Page)


def write_source():
    manifest = OUT / 'MANIFEST.json'
    if manifest.exists() and any(json.loads(manifest.read_text()).get(key) for key in ('admission_revision', 'decision_flow_revision')):
        raise SystemExit('Current diagram contains preserved manual edits and the conditional zero-gain gate. Edit the native source; use --export-only to refresh exports.')
    if SOURCE.exists():
        accepted = {digest(PREVIOUS)}
        if (OUT / 'MANIFEST.json').exists():
            accepted.update(json.loads((OUT / 'MANIFEST.json').read_text()).get('output_sha256', {}).values())
        if digest(SOURCE) not in accepted:
            raise SystemExit('New manual Draw.io edits detected: preserve and incorporate before regenerating.')
    page_agents()
    page_flow()
    checks = {p.key: p.validate() for p in pages}
    ET.indent(book)
    ET.ElementTree(book).write(SOURCE, encoding='utf-8', xml_declaration=True)
    record = {
        'status': 'AGENT_SUBLEASE_SLACKLANDLORD_DESIGN_NOT_DEPLOYED',
        'date': '2026-09-08', 'rent_semantics': 'request-authorized Agent subleases; proportional physical rent on eligible tails only; internal balances paused',
        'production_algorithm_code_changed': False, 'patent_docx_changed': False,
        'notation': {'authority': str(PATENT.relative_to(ROOT)), 'paragraphs_zero_based': [90, 91, 125],
                     'decision_object': 'one physical chunk x',
                     'reused': ['s_a', 'T_a', 'W_{a,x}', 'P_{a,x}', 'G_x', 'Credit_x', 'H_x', 'L', 'b_x', 'f', 'Y', 'D_Y'],
                     'extensions': ['k/k_a and n_a: prefix and generated lengths', 'reuse/recompute: user recovery cost notation',
                                    'Delta T_a,x: recovery saving; W_a,x: nonduplicated Agent WCT share; P_a,x=W_a,x/b_x',
                                    'w/u/v, d_v/t_v: DAG workflow and node times', 'T and T^(i): node recovery-time vectors used in shared attribution',
                                    'Credit_x: remaining rental credit; c_a,x: Agent sublease; W_a,x: ordered exact WCT attribution; L/H/delta: rental state'],
                     'legend_position': 'before flow inputs', 'candidate_bundles_removed': True},
        'appearance': 'black strokes and text on white; no semantic color encoding',
        'manual_edits_incorporated': '0cb1e5eeb7ba source preserved; retain removed main joint-gain node, reuse/recompute notation, user wording and priority node y=1777; expand gain box only to state sharing condition',
        'lazy_refresh_semantics': 'request records renewal eligibility; pending rounds settle at next eligible-tail rent barrier using current benefits; no ordinary refresh topup; all eligible tails checked before L advances',
        'formulas': 'P_a,x=W_a,x/b_x; Agent WCT shares feed corresponding credit; one G_x aggregation; no redundant W_x or G_a,x notation; rental accounting unchanged',
        'rent_key_review': {'path': str((DESIGN/'RENT_KEY_REVIEW.md').relative_to(ROOT)), 'sha256': digest(DESIGN/'RENT_KEY_REVIEW.md')},
        'baseline': {'path': str(PATENT.relative_to(ROOT)), 'sha256': digest(PATENT)},
        'design_sources': {str(q.relative_to(ROOT)): digest(q) for q in
                           [DESIGN/'README.md', DESIGN/'AGENT_LEASE_DESIGN.md', DESIGN/'agent_lease_slacklandlord.py', DESIGN/'reference.py']},
        'user_reference': {'path': str(REFERENCE.relative_to(ROOT)), 'sha256': digest(REFERENCE)},
        'previous_diagram': {'path': str(PREVIOUS.relative_to(ROOT)), 'sha256': digest(PREVIOUS)},
        'style_reference': {'path': str(STYLE.relative_to(ROOT)), 'sha256': digest(STYLE)},
        'pages': checks, 'mathjax': True, 'generator_sha256': digest(Path(__file__)),
        'output_sha256': {SOURCE.name: digest(SOURCE)}, 'export_checks': 'PENDING', 'visual_review': 'PENDING'}
    (OUT/'MANIFEST.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('Two native editable pages written.', flush=True)


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
        meta.update(title='SlackLandlord: Agent subleases and frontier rent, 2026-09-08', subject=quote(SOURCE.read_text(), safe=''))
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
