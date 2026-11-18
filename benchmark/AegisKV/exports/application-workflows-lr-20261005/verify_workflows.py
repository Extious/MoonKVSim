#!/usr/bin/env python3
"""Check drawn task edges against the independent living dependency file."""
from pathlib import Path
import hashlib
import json
import urllib.parse
import xml.etree.ElementTree as ET
import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]


def verify():
    source = ROOT / 'sources/application-workflows.drawio'
    contract = json.loads((source.parent / 'figure-contract.json').read_text())
    original_path = REPO / contract['dependencies_source']
    original = json.loads(original_path.read_text())
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == contract['dependencies_source_sha256']
    xml = ET.parse(source).getroot()
    assert len(xml.findall('diagram')) == 2
    checks = []
    for diagram, cfg in zip(xml.findall('diagram'), contract['workflows']):
        cells = diagram.findall('./mxGraphModel/root/mxCell')
        drawn_nodes = {c.get('id')[6:] for c in cells if c.get('id', '').startswith('agent-')}
        drawn_edges = {(c.get('source')[6:], c.get('target')[6:]) for c in cells if c.get('edge') == '1'}
        graph = original['dependencies'][cfg['id']]
        required = {(a, b) for b, parents in graph.items() for a in parents}
        assert drawn_nodes == set(graph)
        assert drawn_edges == required
        positions = {c.get('id')[6:]: float(c.find('mxGeometry').get('x')) for c in cells
                     if c.get('id', '').startswith('agent-')}
        assert all(positions[a] < positions[b] for a, b in drawn_edges)
        completed = set()
        while len(completed) < len(graph):
            ready = {a for a, parents in graph.items() if a not in completed and set(parents) <= completed}
            assert ready
            completed |= ready
        png = ROOT / 'native' / (cfg['slug'] + '.drawio.png')
        with Image.open(png) as im:
            embedded = im.info.get('mxGraphModel', im.info.get('mxfile'))
            assert embedded, png
            embedded = urllib.parse.unquote(embedded)
            embedded_xml = ET.fromstring(embedded)
            embedded_page = embedded_xml.find(f"diagram[@id='{cfg['id']}']")
            assert embedded_page is not None
            assert ET.tostring(embedded_page) == ET.tostring(diagram)
        with fitz.open(ROOT / (cfg['slug'] + '.pdf')) as doc:
            assert len(doc) == 1
            assert abs(doc[0].rect.width / 72 * 25.4 - 168) < .001
            text = doc[0].get_text()
            assert all(role in text.replace('\n', '') for role in cfg['roles'].values())
        checks.append({'workflow': cfg['id'], 'agents': len(drawn_nodes), 'task_edges': len(drawn_edges),
                       'all_edges_left_to_right': True, 'exact_dependencies': True,
                       'native_png_embeds_current_page_source': True, 'pdf_width_mm': 168,
                       'pdf_roles_preserved': True})
    with fitz.open(ROOT / 'application-workflows.pdf') as doc:
        assert len(doc) == 2
    review = {'status': 'PASS_STATIC_DEPENDENCIES_AND_EXPORTS_PENDING_VISUAL_REVIEW',
              'evidence_level': contract['evidence_level'], 'checks': checks,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'manuscript_modified': False, 'performance_runs': 0,
              'historical_lessons_limit': 'One existing record has a fingerprint mismatch; valid applicable records read, no global append attempted.'}
    (ROOT / 'FIGURE_REVIEW.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == '__main__':
    verify()
