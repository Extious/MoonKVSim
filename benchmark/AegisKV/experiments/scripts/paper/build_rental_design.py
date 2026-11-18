#!/usr/bin/env python3
"""Editable architecture and constructed credit ledger for the rental revision."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import build_storage_design as base
from build_storage_design import Diagram, BLUE, PALE, GREEN, MINT, LINE, WHITE, GRAY

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'exports/three-tier-rental-design-20260921'
base.OUT = OUT


def overview():
    source = ROOT/'exports/system-design-submit-review-20260921/sources/system-overview.drawio'
    tree = ET.parse(source)
    changes = {'cost': 'Rent / value', 'choice': 'L,K · H,D,S',
               'directory': 'Manifests / log / leases · H,D,S rent',
               'adapter0': 'Adapter · AIMD', 'adapter1': 'Adapter · AIMD'}
    found = set()
    for c in tree.findall('.//mxCell'):
        if c.get('id') in changes:
            found.add(c.get('id'))
            c.set('value', changes[c.get('id')])
    assert found == set(changes)
    dest = OUT/'sources/system-overview.drawio'
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    return dest


def credit():
    data = json.loads((OUT/'data/credit-example.json').read_text())
    d = Diagram('renewable-credit', 600, 354)
    def n(*args, **kw):
        kw.setdefault('font', 26)
        return d.node(*args, **kw)
    n('a', 'Agent A', 10, 12, 132, 38, fill=MINT, stroke=GREEN)
    n('x', 'Prefix x', 210, 12, 180, 38, fill=PALE, stroke=BLUE, bold=True)
    n('b', 'Agent B', 458, 12, 132, 38, fill=MINT, stroke=GREEN)
    d.edge('a-x', 'a', 'x', start=(1,.5), end=(0,.5), color=GREEN)
    d.edge('b-x', 'b', 'x', start=(0,.5), end=(1,.5), color=GREEN)
    n('once', 'One physical copy · two credit shares', 8, 61, 584, 34)
    cols = [(10,280), (294,92), (390,92), (486,104)]
    for i, (label, (x,w)) in enumerate(zip(['Event', 'A', 'B', 'Total'], cols)):
        n(f'h-{i}', label, x, 107, w, 34, fill=GRAY, bold=True,
          align='left' if i == 0 else 'center')
    for row, vals in enumerate(data['ledger']):
        y = 147 + row*44
        fill = WHITE if row % 2 == 0 else '#F4F6F7'
        for col, ((x,w), key) in enumerate(zip(cols, ['event','A','B','total'])):
            label = vals[key] if col == 0 else f"{vals[key]:.1f}"
            n(f'r-{row}-{col}', label, x, y, w, 36, fill=fill,
              align='left' if col == 0 else 'center', bold=col==3)
    n('note', 'Refresh keeps rent; reuse renews A.',
      8, 321, 584, 28, font=25.6)
    return d.save()


if __name__ == '__main__':
    print(overview())
    print(credit())
