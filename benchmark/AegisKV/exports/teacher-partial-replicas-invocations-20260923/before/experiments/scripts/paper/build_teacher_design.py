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
OUT = ROOT / 'exports/teacher-system-design-20260923'
drawing.OUT = OUT
FONT = 26.5


def update_style(cell, **updates):
    parts = [x for x in cell.get('style', '').split(';') if x]
    flags = [x for x in parts if '=' not in x]
    values = dict(x.split('=', 1) for x in parts if '=' in x)
    values.update({k: str(v) for k, v in updates.items()})
    cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')


def overview():
    source = ROOT / 'exports/system-overview-dp-tp-20260923/sources/system-overview.drawio'
    tree = ET.parse(source)
    graph = tree.find('.//root')
    cells = {c.get('id'): c for c in graph.findall('mxCell')}
    remove = {i for i in cells if i.startswith('storage')}
    remove |= {'lower-tier-io', 'tracker-number', 'router-number',
               'master-number', 'adapter-number'}
    for ident, cell in cells.items():
        if cell.get('source') in remove or cell.get('target') in remove:
            remove.add(ident)
    for ident in remove:
        graph.remove(cells[ident])
    replacements = {
        'request': 'DAG / token log',
        'cost': 'O1: Agent sets',
        'choice': 'O2: KV regions',
        'adapter0': 'Adapter: O3 quota',
        'adapter1': 'Adapter: O3 quota',
        'dram-label': 'Fault-safe DRAM: complete checkpoints',
    }
    for ident, value in replacements.items():
        cells[ident].set('value', value)
    for ident in ['tracker-label', 'router-label', 'master-label']:
        geom = cells[ident].find('mxGeometry')
        geom.set('x', '0')
        geom.set('width', '176')
    for ident in ['dram0', 'dram1', 'dram2'] + [
            f'chip{level}-{chip}' for level in range(3) for chip in range(6)]:
        geom = cells[ident].find('mxGeometry')
        geom.set('x', str(float(geom.get('x')) + 160))
    cells['dram-label'].find('mxGeometry').attrib.update(x='18', width='588')
    update_style(cells['dram-io'], exitX=(311.5 - 16) / 574)
    tree.find('.//diagram').set('name', 'Two-tier system overview')
    dest = OUT / 'sources/teacher-system-overview.drawio'
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    return dest


def selective():
    d = Diagram('teacher-selective-recovery', 624, 500)

    def n(*args, **kwargs):
        kwargs.setdefault('font', FONT)
        return d.node(*args, **kwargs)

    n('title', 'One checkpoint, two memory tiers', 8, 2, 608, 33, bold=True)
    n('dram-title', 'DRAM: complete', 8, 43, 290, 31, bold=True)
    n('peer-title', 'Peer: selected copies', 326, 43, 290, 31, bold=True)
    hot = {(0, 0), (0, 2), (1, 1)}
    for tier, offset in [('dram', 0), ('peer', 323)]:
        for b in range(4):
            n(f'{tier}-head-{b}', f'B{b}', 63 + offset + 55*b, 81, 48, 30)
        for layer in range(3):
            y = 119 + 43*layer
            n(f'{tier}-layer-{layer}', f'L{layer+1}', 12 + offset, y, 43, 35)
            for block in range(4):
                resident = tier == 'dram' or (layer, block) in hot
                fill = MINT if tier == 'dram' else PALE if resident else '#FFFFFF'
                stroke = GREEN if tier == 'dram' else BLUE if resident else '#B6C0C7'
                n(f'{tier}-{layer}-{block}', 'D' if tier == 'dram' else 'P' if resident else '',
                  63 + offset + 55*block, y, 48, 35, fill=fill, stroke=stroke,
                  extra='' if resident else 'dashed=1;dashPattern=3 3;')
    n('prefix', 'M: committed history; all TP shards per cell',
      8, 252, 608, 32)
    n('demand', 'Layer 1 demand: B0, B1, B2', 8, 300, 608, 32, bold=True)
    for ident, label, x, resident in [
            ('hit0', 'B0: Peer hit', 8, True),
            ('miss1', 'B1: DRAM read', 218, False),
            ('hit2', 'B2: Peer hit', 428, True)]:
        n(ident, label, x, 344, 188, 42,
          fill=PALE if resident else MINT, stroke=BLUE if resident else GREEN)
    n('replay', 'Replay tail N; resume', 157, 427, 310, 37, fill=GRAY, stroke=LINE)
    d.edge('use0', 'hit0', 'replay', start=(.5, 1), end=(.1, 0),
           points=[(102, 409), (188, 409)], color=BLUE)
    d.edge('fetch1', 'miss1', 'replay', start=(.5, 1), end=(.5, 0), color=BLUE)
    d.edge('use2', 'hit2', 'replay', start=(.5, 1), end=(.9, 0),
           points=[(522, 409), (436, 409)], color=BLUE)
    n('footer', 'Dropping Peer replicas preserves DRAM coverage', 8, 468, 608, 30)
    for c in d.root.findall('mxCell'):
        if c.get('vertex'):
            update_style(c, fontFamily='Linux Libertine O')
    (OUT / 'data/selective-state.json').write_text(json.dumps({
        'evidence': 'constructed state diagram; no timing or throughput claim',
        'dram': [[l, b] for l in range(1, 4) for b in range(4)],
        'peer': [[l+1, b] for l, b in sorted(hot)],
        'layer1_demand': [0, 1, 2], 'peer_hits': [0, 2], 'dram_misses': [1],
        'managed_physical_region_copies': 15,
        'logical_checkpoint_regions': 12,
        'execution_kv_and_staging': 'separately charged; omitted from map',
        'tail': 'accepted tokens after complete frontier, replayed from token log',
    }, indent=2) + '\n')
    return d.save()


if __name__ == '__main__':
    for subdir in ['sources', 'data', 'figures', 'review']:
        (OUT / subdir).mkdir(parents=True, exist_ok=True)
    for build in [overview, selective]:
        print(build())
