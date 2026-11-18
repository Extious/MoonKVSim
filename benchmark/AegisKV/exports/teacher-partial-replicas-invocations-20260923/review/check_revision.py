"""Finite manuscript/diagram checks; this does not exercise a serving runtime."""
from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
OLD = json.loads((OUT / 'before/manifest.json').read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
checks = {}
checks['canonical_files_unchanged'] = all(
    (ROOT/'paper'/p).is_file() and sha(ROOT/'paper'/p) == h
    for p, h in OLD['paper'].items()
) and set(OLD['paper']) == {
    str(p.relative_to(ROOT/'paper')) for p in (ROOT/'paper').rglob('*') if p.is_file()
}
checks['teacher_supplied_chapters_unchanged'] = all(
    sha(ROOT/'paper_teacher'/p) == OLD['paper_teacher'][p]
    for p in ['background.tex', 'motivation.tex']
)
checks['teacher_four_tex_files'] = {
    p.name for p in (ROOT/'paper_teacher').glob('*.tex')
} == {'main.tex', 'background.tex', 'motivation.tex', 'system_design.tex'}
state = json.loads((OUT/'data/selective-state.json').read_text())
S, H, D = (set(map(tuple, state[k])) for k in ['selected', 'peer', 'dram'])
checks['selected_union_equals_placements'] = S == H | D
checks['one_stable_backup_per_region'] = not H & D
checks['partial_backup'] = len(S) == 5 < state['logical_history_regions'] == 12
checks['first_L_peer_constraint'] = all(l <= state['L'] for l, b in H)
checks['peer_overflow_in_DRAM'] = all(
    tuple(x) in D for x in state['early_layer_overflow']
) and len(H) == state['peer_capacity_regions']
checks['later_selected_layers_in_DRAM'] = all(
    (l, b) in D for l, b in S if l > state['L']
)
checks['source_and_placement_grid_agree'] = True
cells = {c.get('id'): c for c in ET.parse(
    OUT/'sources/teacher-selective-recovery.drawio').findall('.//mxCell')}
for l in range(1, 4):
    for b in range(4):
        key = (l, b)
        checks['source_and_placement_grid_agree'] &= (
            cells[f'selected-{l-1}-{b}'].get('value') == ('S' if key in S else '–')
            and cells[f'placed-{l-1}-{b}'].get('value') ==
            ('H' if key in H else 'D' if key in D else '–')
        )
cells = {c.get('id'): c for c in ET.parse(
    OUT/'sources/teacher-invocation-reuse.drawio').findall('.//mxCell')}
checks['same_agent_three_invocations'] = [
    cells[f'a{i}'].get('value') for i in [1, 2, 3]
] == ['A(1)', 'A(2)', 'A(3)']
checks['consecutive_invocation_edges'] = {
    (c.get('source'), c.get('target')) for c in cells.values() if c.get('edge')
} == {('a1', 'a2'), ('a2', 'a3')}
checks['compatible_prefix_reused'] = (
    cells['history1'].get('value') == cells['prefix2'].get('value') ==
    cells['prefix3'].get('value') == 'H1'
)
figs = ['teacher-system-overview', 'teacher-invocation-reuse', 'teacher-selective-recovery']
checks['native_PNG_sources_embedded'] = all(
    any('mx' in key.lower() for key in Image.open(OUT/f'figures/{f}.native.png').info)
    for f in figs
)
source = (ROOT/'paper_teacher/system_design.tex').read_text()
checks['block_ids_distinct_from_invocation_ordinals'] = not re.search(r'/B\(', source)
checks['new_design_excluded_features_absent'] = not re.search(
    r'\btool(?:[- ]use|[- ]handoff|s)?\b|shared storage|\brental\b|\bLandlord\b',
    source, re.I
)
log = (ROOT/'exports/latex-build-teacher/main.log').read_text()
checks['no_undefined_references_or_citations'] = not re.search(r'undefined', log, re.I)
checks['no_overfull_boxes'] = 'Overfull' not in log
checks['final_log_no_tex_error'] = not re.search(r'^!', log, re.M)
doc = fitz.open(ROOT/'paper_teacher/main.pdf')
for i, page in enumerate(doc):
    page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(OUT/f'review/page-{i+1}.png')
    (OUT/f'review/page-{i+1}.txt').write_text(page.get_text())
    if i+1 in [4, 6]:
        page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), colorspace=fitz.csGRAY).save(
            OUT/f'review/page-{i+1}.gray.png')
report = {
    'checks': checks, 'pages': len(doc), 'canonical_files_checked': len(OLD['paper']),
    'paper_sha256': sha(ROOT/'paper_teacher/main.pdf'),
    'figure_metadata': json.loads((OUT/'review/figure-metadata.json').read_text()),
    'evidence_level': 'Source/state arithmetic, native exports, and manuscript build only; no runtime or performance validation.'
}
(OUT/'review/checks.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
assert all(checks.values()), [k for k, v in checks.items() if not v]
