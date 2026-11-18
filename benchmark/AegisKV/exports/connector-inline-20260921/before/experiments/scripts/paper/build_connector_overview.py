#!/usr/bin/env python3
"""Make control/transfer paths explicit in the compact, editable Overview."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/connector-overview-links-20260921'
SOURCE = ROOT / 'exports/design-observations-compact-20260921/sources/system-overview.drawio'


def main():
    tree = ET.parse(SOURCE)
    root = tree.find('.//root')
    cells = {c.get('id'): c for c in root.findall('mxCell')}

    def style(cell, **updates):
        atoms = [x for x in cell.get('style', '').split(';') if x]
        flags = [x for x in atoms if '=' not in x]
        values = dict(x.split('=', 1) for x in atoms if '=' in x)
        values.update({k: str(v) for k, v in updates.items()})
        cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')

    def route(cell, points):
        geom = cell.find('mxGeometry')
        for old in list(geom):
            geom.remove(old)
        arr = ET.SubElement(geom, 'Array', {'as': 'points'})
        for x, y in points:
            ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))

    # Reserve a visible, independent right-hand lane for Master/Connector RPCs.
    cells['canvas'].find('mxGeometry').set('width', '624')
    for ident in ['application', 'controller', 'engine']:
        cells[ident].find('mxGeometry').set('width', '608')
    cells['directory'].find('mxGeometry').set('width', '416')
    cells['directory'].find('mxGeometry').set('y', '163')

    short = {'predict-cpm', 'target', 'local-io0', 'local-io1', 'peer-io0', 'peer-io1'}
    for ident, cell in cells.items():
        if cell.get('vertex'):
            # Maintain the previous physical text size at the wider crop.
            style(cell, fontSize=26.5)
        elif cell.get('edge'):
            if ident in {'ab', 'ac', 'bd', 'cd'}:
                style(cell, strokeWidth=1.8, endSize=5)
            else:
                style(cell, strokeWidth=1.8 if ident in short else 2.2,
                      endSize=2 if ident in short else 4,
                      startSize=2 if ident in short else 4,
                      dashPattern='4 3')

    style(cells['progress'], exitX=(206.56-8)/608)
    style(cells['requests'], exitX=(296-8)/608)
    route(cells['slack-value'], [(164.5, 230), (434.04, 230)])
    route(cells['dispatch'], [(200, 169), (200, 240), (13, 240),
                              (13, 316), (152, 316)])
    route(cells['retry'], [(389, 138), (389, 240), (589, 240),
                           (589, 317), (448, 317)])

    # Adapter publishes its quota; it does not stand in for the transfer executor.
    budget = cells['budget']
    style(budget, startArrow='none', entryX=.41, entryY=1,
          strokeWidth=2.2, jumpStyle='arc', jumpSize=6)
    route(budget, [(295, 370), (295, 282), (474.98, 282)])

    # A distinct bidirectional control edge: plan down, completion/status up.
    exchange = ET.SubElement(root, 'mxCell', {
        'id': 'master-connector', 'parent': '1', 'edge': '1',
        'source': 'master', 'target': 'connector1',
        'style': 'rounded=0;strokeColor=#243746;strokeWidth=2.6;'
                 'dashed=1;dashPattern=4 3;startArrow=block;startFill=1;'
                 'startSize=4;endArrow=block;endFill=1;endSize=4;'
                 'exitX=1;exitY=0.62;exitPerimeter=0;'
                 'entryX=1;entryY=0.5;entryPerimeter=0;'
    })
    ET.SubElement(exchange, 'mxGeometry', relative='1', **{'as': 'geometry'})
    route(exchange, [(608, 185), (608, 451.5)])

    dest = OUT / 'sources/system-overview.drawio'
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    print(dest)


if __name__ == '__main__':
    main()
