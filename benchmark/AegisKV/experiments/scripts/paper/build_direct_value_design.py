#!/usr/bin/env python3
"""Editable direct-revaluation figures; numbers are declared examples."""
from pathlib import Path
import xml.etree.ElementTree as ET
import build_storage_design as base
from build_storage_design import Diagram, BLUE, PALE, LINE, ORANGE, SAND, GRAY, WHITE

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/direct-value-design-20260921'
base.OUT = OUT


def overview():
    source = ROOT / 'exports/design-evidence-review-20260921/sources/system-overview.drawio'
    tree = ET.parse(source)
    renames = {'rental':'revalue', 'rent-title':'revalue-title',
               'rent-plan':'value-plan', 'dram-ledger':'dram-candidates',
               'ssd-ledger':'ssd-candidates'}
    for cell in tree.findall('.//mxCell'):
        for attr in ['id', 'parent', 'source', 'target']:
            old = cell.get(attr)
            if old in renames:
                cell.set(attr, renames[old])
            elif old and old.startswith('credit-'):
                cell.set(attr, old.replace('credit-', 'candidate-', 1))
        if cell.get('id') == 'revalue-title':
            cell.set('value', 'Revalue')
    (OUT / 'sources').mkdir(parents=True, exist_ok=True)
    target = OUT / 'sources/system-overview.drawio'
    tree.write(target, encoding='utf-8', xml_declaration=True)
    return target


def competition():
    d = Diagram('placement-competition', 480, 460)
    n, g, e = d.node, d.group, d.edge
    n('title', 'Revalue the complete replacement', 8, 4, 464, 29, bold=True)
    g('incoming', 18, 46, 444, 58, fill=PALE, stroke=BLUE)
    n('incoming-name', 'Promote x · size 1', 22, 49, 436, 26, bold=True, parent='incoming')
    n('incoming-value', 'Current saving: 6 s', 22, 77, 436, 24, parent='incoming')
    n('assumptions', 'Equal-size groups · migration cost 1 s', 12, 114, 456, 27)
    g('safe', 15, 154, 298, 128, fill='#F7F9FA', stroke=BLUE)
    n('safe-title', 'Safe victims Q', 22, 157, 284, 26, bold=True, parent='safe')
    for key, x, label, value in [('y', 22, 'Demote y', 'Loss: 2 s'),
                                  ('z', 167, 'Demote z', 'Loss: 5 s'),
                                  ('reader', 328, 'Read lease', 'Loss: 1 s')]:
        parent = 'safe' if key != 'reader' else '1'
        n(key+'-name', label, x, 194, 132, 25, bold=True, parent=parent)
        n(key+'-loss', value, x+2, 225, 128, 27,
          fill=SAND if key == 'y' else GRAY, stroke=ORANGE if key == 'y' else LINE, parent=parent)
        if key == 'reader':
            n('excluded', 'Not in Q', x, 259, 132, 25)
    n('compare', 'Complete-plan cost change', 12, 301, 456, 28, bold=True)
    n('plan-y', 'x in, y out: 1 + 2 − 6 = −3 s', 20, 340, 440, 30,
      fill=PALE, stroke=BLUE)
    n('plan-z', 'x in, z out: 1 + 5 − 6 = 0 s', 20, 375, 440, 30,
      fill=WHITE, stroke=LINE)
    n('commit', 'Select → reserve → commit → release', 14, 423, 452, 29)
    assert 1 + 2 - 6 == -3 and 1 + 5 - 6 == 0
    return d.save()


if __name__ == '__main__':
    print(overview())
    print(competition())
