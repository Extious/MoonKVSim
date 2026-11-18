#!/usr/bin/env python3
"""Editable two-tier diagrams for the teacher edition's O1/O2/O3 design.

The overview reuses only deployment geometry and typography. The region
map is constructed state, not an access trace or measured recovery result.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import build_storage_design as drawing
from build_storage_design import Diagram, BLUE, PALE, GREEN, MINT, LINE, GRAY

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/teacher-four-components-peer-memory-20260923'
drawing.OUT = OUT
FONT = 26.5


def update_style(cell, **updates):
    parts = [x for x in cell.get('style', '').split(';') if x]
    flags = [x for x in parts if '=' not in x]
    values = dict(x.split('=', 1) for x in parts if '=' in x)
    values.update({k: str(v) for k, v in updates.items()})
    cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')


def overview():
    source = ROOT / 'exports/teacher-partial-replicas-invocations-20260923/sources/teacher-system-overview.drawio'
    tree = ET.parse(source)
    graph = tree.find('.//root')
    cells = {c.get('id'): c for c in graph.findall('mxCell')}
    remove = {i for i in cells if i.startswith(('dram', 'chip', 'fabric', 'shared-'))}
    for ident, cell in cells.items():
        if cell.get('source') in remove or cell.get('target') in remove:
            remove.add(ident)
    for ident in remove:
        graph.remove(cells[ident])
    update_style(cells['target'], startArrow='block', startFill=1, startSize=5)
    d = Diagram('teacher-system-overview', 624, 650)
    d.root = graph
    d.origins = {'1': (0, 0), 'dp0': (20, 285), 'dp1': (316, 285)}
    for worker, x in [(0, 20), (1, 316)]:
        cells[f'dp{worker}'].find('mxGeometry').set('height', '348')
        cells[f'dp{worker}-name'].set('value', f'DP{worker} / Host{worker}')
        cells[f'local-header{worker}'].set('value', 'Exec.')
        cells[f'peer-header{worker}'].set('value', 'Replica')
        ident = f'peer-dram-dp{worker}'
        d.node(ident, '', x+27, 578, 230, 45, parent=f'dp{worker}', fill=MINT, stroke=GREEN)
        d.node(f'{ident}-label', 'Peer DRAM', x+29, 579, 226, 30, parent=ident, font=FONT)
        for chip in range(6):
            d.node(f'{ident}-chip-{chip}', '', x+40+33*chip, 612, 25, 6,
                   parent=ident, fill=GREEN, stroke=GREEN)
        d.edge(f'host-dram-dp{worker}-tp0', f'connector-dp{worker}-tp0', ident,
               start=(0,.5), end=(0,.5), points=[(x+3,436.5),(x+3,600.5)],
               both=True, color=BLUE)
        d.edge(f'host-dram-dp{worker}-tp1', f'connector-dp{worker}-tp1', ident,
               start=(.5,1), end=(.6,0), points=[(x+156,560),(x+165,560)],
               both=True, color=BLUE)
    for cell in graph.findall('mxCell'):
        if cell.get('vertex'):
            update_style(cell, fontFamily='Linux Libertine O')
    tree.find('.//diagram').set('name', 'Four components with peer-owned HBM and DRAM')
    dest = OUT / 'sources/teacher-system-overview.drawio'
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    (OUT / 'data/peer-topology.json').write_text(json.dumps({
        'evidence': 'constructed deployment diagram',
        'hosts': {'Host0': ['DP0'], 'Host1': ['DP1']},
        'TP_ranks_per_worker': 2,
        'peer_pairs': [['DP0','DP1'], ['DP1','DP0']],
        'host_DRAM_owners': {'peer-dram-dp0':'DP0','peer-dram-dp1':'DP1'},
        'separate_DRAM_service': False,
        'roles': 'execution and replica are relative to different Agent histories',
        'shared_host_accounting': 'workers on one host would share one physical DRAM ledger',
    }, indent=2)+'\n')
    return dest


def styled(d):
    for c in d.root.findall('mxCell'):
        if c.get('vertex'):
            update_style(c, fontFamily='Linux Libertine O')
    return d.save()


def invocation_reuse():
    d = Diagram('teacher-invocation-reuse', 624, 303)

    def n(*args, **kwargs):
        kwargs.setdefault('font', FONT)
        return d.node(*args, **kwargs)

    n('title', 'One Agent, three invocation nodes', 8, 2, 608, 33, bold=True)
    for i, x in enumerate([122, 308, 494], 1):
        n(f'a{i}', f'A({i})', x, 51, 92, 36, fill=PALE, stroke=BLUE)
    for i in [1, 2]:
        d.edge(f'next{i}', f'a{i}', f'a{i+1}', start=(1,.5), end=(0,.5))
    n('history1-label', 'After A(1)', 8, 113, 147, 35, align='left')
    n('history1', 'H1', 158, 113, 180, 35, fill=MINT, stroke=GREEN)
    n('input2-label', 'A(2) input', 8, 159, 147, 35, align='left')
    n('prefix2', 'H1', 158, 159, 180, 35, fill=MINT, stroke=GREEN)
    n('new2', 'U2', 338, 159, 105, 35, fill=GRAY, stroke=LINE)
    n('input3-label', 'A(3) input', 8, 205, 147, 35, align='left')
    n('prefix3', 'H1', 158, 205, 180, 35, fill=MINT, stroke=GREEN)
    n('extension2', 'E2', 338, 205, 150, 35, fill=MINT, stroke=GREEN)
    n('new3', 'U3', 488, 205, 113, 35, fill=GRAY, stroke=LINE)
    n('extension-note', 'E2 = U2 + accepted A(2) output', 8, 257, 608, 33)
    (OUT / 'data/invocation-state.json').write_text(json.dumps({
        'evidence': 'constructed append-only history example, not a measured workload',
        'agent': 'A', 'nodes': ['A(1)', 'A(2)', 'A(3)'],
        'edges': [['A(1)', 'A(2)'], ['A(2)', 'A(3)']],
        'after_A1': ['H1'], 'A2_input': ['H1', 'U2'],
        'A3_input': ['H1', 'E2', 'U3'],
        'E2': 'U2 plus accepted A(2) output',
        'reuse_requires': 'exact compatible prefix; only materialized, valid KV may be consumed',
        'bars': 'logical histories, not full backup allocations',
        'lifetime': 'invocation completion preserves selected history for later consumers',
    }, indent=2) + '\n')
    return styled(d)


def selective():
    d = Diagram('teacher-selective-recovery', 624, 472)

    def n(*args, **kwargs):
        kwargs.setdefault('font', FONT)
        return d.node(*args, **kwargs)

    n('title', 'Select Agent → select KV → place', 8, 2, 608, 33, bold=True)
    n('selected-title', 'Selected regions', 8, 50, 290, 31, bold=True)
    n('placed-title', 'On one peer (L = 2)', 326, 50, 290, 31, bold=True)
    selected = {(0, 0), (0, 2), (1, 1), (2, 0), (2, 2)}
    peer = {(0, 0), (0, 2)}
    dram = selected - peer
    for panel, offset in [('selected', 0), ('placed', 323)]:
        for b in range(4):
            n(f'{panel}-head-{b}', f'B{b}', 63 + offset + 55*b, 91, 48, 30)
        for layer in range(3):
            y = 129 + 45*layer
            n(f'{panel}-layer-{layer}', f'L{layer+1}', 12 + offset, y, 43, 35)
            for block in range(4):
                key = (layer, block)
                present = key in selected
                label = 'S' if panel == 'selected' else 'H' if key in peer else 'D'
                fill = GRAY if panel == 'selected' else PALE if key in peer else MINT
                stroke = LINE if panel == 'selected' else BLUE if key in peer else GREEN
                n(f'{panel}-{layer}-{block}', label if present else '–',
                  63 + offset + 55*block, y, 48, 35, fill=fill, stroke=stroke,
                  extra='' if present else 'fillColor=#FFFFFF;strokeColor=#B6C0C7;dashed=1;dashPattern=3 3;')
    n('place-arrow', '→', 295, 172, 33, 35)
    n('legend', 'S: selected | H/D: peer HBM/DRAM', 8, 271, 608, 32)
    n('overflow', 'HBM full: L2/B1 → peer DRAM', 8, 316, 608, 32)
    n('depth', 'Beyond L → peer DRAM', 8, 352, 608, 32)
    n('count', 'H ∪ D: 5/12 regions backed up', 8, 392, 608, 32, bold=True)
    n('missing', 'Unbacked demand → reconstruct dependencies', 8, 432, 608, 32)
    (OUT / 'data/selective-state.json').write_text(json.dumps({
        'evidence': 'constructed state diagram; no timing or throughput claim',
        'selected': [[l+1, b] for l, b in sorted(selected)],
        'dram': [[l+1, b] for l, b in sorted(dram)],
        'peer': [[l+1, b] for l, b in sorted(peer)],
        'L': 2, 'peer_capacity_regions': 2,
        'peer_worker': 'DP1', 'dram_host': 'Host1',
        'tier_labels': {'peer': 'Peer HBM', 'dram': 'Peer DRAM'},
        'early_layer_overflow': [[2, 1]],
        'managed_physical_region_copies': 5,
        'logical_history_regions': 12,
        'complete_backup': False,
        'execution_kv_and_staging': 'separately charged; omitted from map',
        'unbacked_demand': 'reconstruct native dependencies; full-prefix fallback if needed',
    }, indent=2) + '\n')
    return styled(d)


if __name__ == '__main__':
    for subdir in ['sources', 'data', 'figures', 'review']:
        (OUT / subdir).mkdir(parents=True, exist_ok=True)
    for build in [overview, invocation_reuse, selective]:
        print(build())
