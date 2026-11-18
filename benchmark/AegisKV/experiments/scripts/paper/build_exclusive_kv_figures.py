#!/usr/bin/env python3
"""Editable figures for exclusive managed KV; execution KV is a separate working set."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import build_storage_design as base
from build_storage_design import Diagram, BLUE, PALE, GREEN, MINT, ORANGE, SAND, LINE, WHITE, GRAY

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/exclusive-kv-master-20260921'
base.OUT = OUT


def update_style(cell, **kw):
    atoms = [x for x in cell.get('style', '').split(';') if x]
    flags = [x for x in atoms if '=' not in x]
    values = dict(x.split('=', 1) for x in atoms if '=' in x)
    values.update({k: str(v) for k, v in kw.items()})
    cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')


def overview():
    tree = ET.parse(ROOT / 'exports/connector-inline-20260921/sources/system-overview.drawio')
    for c in tree.findall('.//mxCell'):
        ident = c.get('id', '')
        if ident == 'cost':
            c.set('value', 'Value → tiers')
        elif ident == 'directory':
            c.set('value', 'Locations · D/S credit')
        elif ident.startswith('dram') and ident != 'dram-label' and c.get('vertex'):
            update_style(c, fillColor=MINT, strokeColor=GREEN)
        elif ident.startswith('chip'):
            update_style(c, fillColor=GREEN)
        elif ident in ['local0', 'local1']:
            update_style(c, fillColor=GRAY, strokeColor=LINE)
    dest = OUT / 'sources/system-overview.drawio'
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    return dest


def sparse():
    d = Diagram('sparse-recovery', 600, 436)
    def n(*a, **kw):
        kw.setdefault('font', 26)
        return d.node(*a, **kw)
    n('title', 'One checkpoint across exclusive tiers', 8, 3, 584, 30,
      bold=True, align='left')
    n('legend', 'P: Peer     D: DRAM     S: Storage', 8, 39, 584, 28)
    owners = [['P', 'D', 'S', 'P'], ['D', 'P', 'S', 'S'], ['D', 'S', 'S', 'D']]
    palette = {'P': (PALE, BLUE), 'D': (MINT, GREEN), 'S': (SAND, ORANGE)}
    xs = [119, 218, 317, 416]
    for b, x in enumerate(xs):
        n(f'col-{b}', f'B{b}', x, 77, 82, 29)
    n('tail-head', 'Tail', 515, 77, 76, 29)
    for l, row in enumerate(owners):
        y = 112 + 44*l
        n(f'layer-{l}', f'Layer {l+1}', 7, y, 101, 34, align='left')
        for b, tier in enumerate(row):
            fill, stroke = palette[tier]
            n(f'kv-{l}-{b}', tier, xs[b], y, 82, 34, fill=fill, stroke=stroke,
              bold=tier == 'P')
        n(f'tail-{l}', '', 524, y, 58, 34, fill=GRAY, stroke=LINE,
          extra='dashed=1;dashPattern=3 3;')
    n('coverage', 'L = 2; K₁ = 2, K₂ = 1', 8, 240, 584, 29)
    n('demand', 'Layer 1 needs B0, B1 and B2', 8, 277, 584, 29,
      align='left', bold=True)
    for ident, label, x, tier in [('hit', 'B0: Peer hit', 8, 'P'),
                                  ('dram', 'B1: H2D', 208, 'D'),
                                  ('storage', 'B2: read/H2D', 408, 'S')]:
        fill, stroke = palette[tier]
        n(ident, label, x, 315, 184, 33, fill=fill, stroke=stroke)
    n('execute', 'Recovery execution', 177, 371, 246, 30, fill=GRAY, stroke=LINE)
    d.edge('hit-use', 'hit', 'execute', start=(.5,1), end=(.08,0),
           points=[(100,360),(196.68,360)], color=BLUE)
    d.edge('dram-use', 'dram', 'execute', start=(.5,1), end=(.5,0), color=GREEN)
    d.edge('storage-use', 'storage', 'execute', start=(.5,1), end=(.92,0),
           points=[(500,360),(403.32,360)], color=ORANGE)
    n('footer', 'Demote P → D → S; copy before release', 8, 407, 584, 28)
    for c in d.root.findall('mxCell'):
        if c.get('vertex'):
            update_style(c, fontFamily='Linux Libertine O')
    (OUT/'data/exclusive-layout.json').write_text(json.dumps({
        'evidence':'constructed state diagram', 'owners':owners,
        'peer_layers':2, 'peer_counts':[2,1,0], 'layer1_demand':[0,1,2],
        'counts':{k:sum(row.count(k) for row in owners) for k in palette},
        'tail':'uncommitted; not part of saved checkpoint',
        'auxiliary':'selector and TP state covered by the directory, omitted from matrix'
    }, indent=2)+'\n')
    return d.save()


def credit():
    tree = ET.parse(ROOT/'exports/three-tier-rental-design-20260921/sources/renewable-credit.drawio')
    for c in tree.findall('.//mxCell'):
        if c.get('id') == 'once':
            c.set('value', 'DRAM object · two Agent shares')
        elif c.get('id') == 'x':
            update_style(c, fillColor=MINT, strokeColor=GREEN)
        if c.get('vertex'):
            update_style(c, fontFamily='Linux Libertine O')
    dest = OUT/'sources/renewable-credit.drawio'
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    return dest


if __name__ == '__main__':
    for folder in ['sources', 'data', 'figures']:
        (OUT/folder).mkdir(parents=True, exist_ok=True)
    for fn in [overview, sparse, credit]:
        print(fn())
