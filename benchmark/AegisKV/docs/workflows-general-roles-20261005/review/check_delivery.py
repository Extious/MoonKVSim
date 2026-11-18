"""Inspect actual editable sources, embedded exports and unlabeled DAG differences."""
from pathlib import Path
import json
import re
from urllib.parse import unquote
import xml.etree.ElementTree as ET

from PIL import Image

BASE = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((BASE / 'workflow-contract.json').read_text())


def inspect(diagram, wf):
    cells = diagram.findall('.//mxCell')
    nodes = {c.get('id').removeprefix('agent-') for c in cells if c.get('id', '').startswith('agent-')}
    edges = {(c.get('source').removeprefix('agent-'), c.get('target').removeprefix('agent-'))
             for c in cells if c.get('edge') == '1'}
    assert nodes == set(wf['nodes'])
    assert edges == {(a, b) for b, parents in wf['dependencies'].items() for a in parents}
    for ident, node in wf['nodes'].items():
        assert next(c.get('value') for c in cells if c.get('id') == f'scope-{ident}') in node['scope'].values()
    indegree = {n: sum(b == n for _, b in edges) for n in nodes}
    outdegree = {n: sum(a == n for a, _ in edges) for n in nodes}
    roots = [n for n in nodes if not indegree[n]]
    ends = [n for n in nodes if not outdegree[n]]
    assert roots == ['A'] and len(ends) == 1
    if wf['id'] == 'research':
        assert not any(re.search(r'topic\s*(one|two|three|\d)|子问题[一二三1-3]', c.get('value', ''), re.I) for c in cells)
    return {'actual_source_nodes': len(nodes), 'actual_source_edges': len(edges),
            'entry_outdegree': outdegree['A'], 'final_indegree': indegree[ends[0]]}


checks = {}
for lang in ['zh', 'en']:
    source = ET.parse(BASE / f'workflows-{lang}.drawio')
    for wf in CONTRACT['workflows']:
        diagram = source.getroot().find(f'diagram[@id="{wf["id"]}"]')
        result = inspect(diagram, wf)
        slug = f'{wf["slug"]}-{lang}'
        with Image.open(BASE / 'native' / f'{slug}.drawio.png') as im:
            key = next(k for k in ['mxGraphModel', 'mxfile', 'XML:com.mxgraph'] if k in im.info)
            embedded = ET.fromstring(unquote(im.info[key]))
        assert inspect(embedded.find(f'diagram[@id="{wf["id"]}"]'), wf) == result
        svg = ET.parse(BASE / 'native' / f'{slug}.drawio.svg').getroot()
        embedded_svg = ET.fromstring(unquote(svg.attrib['content']))
        assert inspect(embedded_svg.find(f'diagram[@id="{wf["id"]}"]'), wf) == result
        result.update({'native_png_metadata_key': key, 'embedded_png_svg_source_matches_contract': True})
        checks[f'{wf["id"]}-{lang}'] = result
assert checks['research-zh']['entry_outdegree'] == 3
assert checks['software-zh']['entry_outdegree'] == 2
assert checks['research-zh']['final_indegree'] == 2
assert checks['software-zh']['final_indegree'] == 3
checks['comparison'] = {'distinct_unlabeled_graphs': True,
                        'reason': 'Different vertex counts, entry fork widths and final join indegrees; not merely label changes',
                        'scope': 'Diagram structure only; not measured execution, quality, or AegisKV benefit'}
(BASE / 'review' / 'source-delivery-checks.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps(checks, indent=2))
