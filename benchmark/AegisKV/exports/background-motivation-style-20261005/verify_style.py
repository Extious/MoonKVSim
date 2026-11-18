#!/usr/bin/env python3
"""Check unchanged DAG/evidence semantics and actual exported paper figures."""
from pathlib import Path
import hashlib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
PAPER = AEGIS / 'paper'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def structure(n):
    return (n.tag, tuple(sorted(n.attrib.items())),
            n.text if n.text and n.text.strip() else None,
            tuple(structure(c) for c in n))


def verify():
    source = ROOT / 'sources/application-workflows.drawio'
    cfg = json.loads((source.parent / 'figure-contract.json').read_text())
    deps = AEGIS / 'docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json'
    required = json.loads(deps.read_text())['dependencies']
    assert sha(deps) == cfg['dependencies_source_sha256']
    dag_checks = []
    pdfs = []
    for diagram, panel in zip(ET.parse(source).getroot().findall('diagram'), cfg['workflows']):
        cells = diagram.findall('mxGraphModel/root/mxCell')
        nodes = {c.get('id')[6:]: c for c in cells if c.get('id', '').startswith('agent-')}
        drawn = {(c.get('source')[6:], c.get('target')[6:]) for c in cells if c.get('edge') == '1'}
        expected = {(a, b) for b, parents in required[panel['id']].items() for a in parents}
        assert set(nodes) == set(required[panel['id']]) and drawn == expected
        assert all(float(nodes[a].find('mxGeometry').get('x')) < float(nodes[b].find('mxGeometry').get('x')) for a, b in drawn)
        with Image.open(ROOT / 'native' / f"{panel['slug']}.drawio.png") as img:
            payload = img.info.get('mxGraphModel', img.info.get('mxfile'))
            embed = ET.fromstring(urllib.parse.unquote(payload)).find(f"diagram[@id='{panel['id']}']")
            assert structure(embed) == structure(diagram)
        path = ROOT / f"{panel['slug']}.pdf"
        with fitz.open(path) as doc:
            text = re.sub(r'\s+', '', doc[0].get_text())
            assert all(re.sub(r'\s+', '', role) in text for role in panel['roles'].values())
            assert abs(doc[0].rect.width / 72 * 25.4 - 168) < .002
        dag_checks.append({'id': panel['id'], 'agents': len(nodes), 'dependencies': len(drawn),
            'exact_dependencies': True, 'left_to_right': True, 'editable_png_matches_source': True})
        pdfs.append(path)
    pdfs.extend(sorted((ROOT / 'schematics').glob('*.pdf')))
    metrics = []
    for path in pdfs:
        assert sha(path) == sha(PAPER / 'figures' / path.name)
        with fitz.open(path) as doc:
            page = doc[0]
            spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
            assert min(s['size'] for s in spans) >= 10
            for s in spans:
                r = fitz.Rect(s['bbox'])
                assert r.x0 >= -.1 and r.y0 >= -.1 and r.x1 <= page.rect.width + .1 and r.y1 <= page.rect.height + .1
            assert len(page.get_images()) == 0
            metrics.append({'name': path.name, 'width_mm': page.rect.width / 72 * 25.4,
                'height_mm': page.rect.height / 72 * 25.4, 'min_font_pt': min(s['size'] for s in spans),
                'vector_only': True, 'unclipped_text': True})
    assert sha(PAPER / 'figures/serving_model.pdf') == sha(ROOT / 'before/figures/serving_model.pdf')
    active = '\n'.join((PAPER / p).read_text().split(r'\iffalse')[0] for p in ('background.tex', 'motivation.tex'))
    assert 'arbitrary time units' in active and 'Illustrative' in active
    assert not any(x in active for x in ('91.2', '33.2', '87.64', 'figures/kv_value.pdf', 'figures/agent_value_b.pdf'))
    campaign_path = AEGIS / 'docs/workflow-evaluation-20261005/CAMPAIGN.json'
    campaign = json.loads(campaign_path.read_text())
    assert campaign['llm_calls'] == campaign['physical_runs'] == 0
    assert not campaign['paper_result_claims_allowed']
    log = (AEGIS / 'exports/latex-build/main.log').read_text()
    assert not re.search(r'(^!|undefined|Overfull \\hbox)', log, re.M)
    assert sha(PAPER / 'main.pdf') == sha(AEGIS / 'exports/latex-build/main.pdf')
    pages = []
    with fitz.open(PAPER / 'main.pdf') as doc:
        total_pages = len(doc)
        for i, page in enumerate(doc):
            if any(x in page.get_text() for x in ('Complete DRAM coverage', 'Reconstruction time (u)', 'Two application Agent-task DAGs', 'Replica space')):
                pages.append(i + 1)
                for kind, space in [('color', fitz.csRGB), ('gray', fitz.csGRAY)]:
                    page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), colorspace=space, alpha=False).save(ROOT / 'review' / f'paper-page-{i+1:02}-{kind}.png')
    report = {'status': 'PASS_STATIC_AND_COMPILE_PENDING_FINAL_VISUAL_REVIEW',
        'dag_checks': dag_checks, 'pdf_metrics': metrics, 'paper_pages': total_pages,
        'changed_figure_pages': pages, 'unchanged_serving_model': True,
        'new_measured_results': 0, 'scope': 'Style restoration only; new workloads and evidence boundaries preserved',
        'compile_method': 'Canonical build_paper.sh; compile_latex_document unavailable in this session',
        'memory_record_limit': 'Historical fingerprint mismatch blocks global append; correction retained in project'}
    (ROOT / 'FIGURE_REVIEW.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest_paths = [PAPER / 'background.tex', PAPER / 'motivation.tex', PAPER / 'main.pdf', *pdfs,
        *(PAPER / 'figures' / p.name for p in pdfs), source, ROOT / 'build_style.py', ROOT / 'verify_style.py', campaign_path]
    (ROOT / 'DELIVERY_MANIFEST.json').write_text(json.dumps([{'path': str(p.relative_to(AEGIS)), 'sha256': sha(p)} for p in manifest_paths], indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    verify()
