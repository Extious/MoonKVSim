#!/usr/bin/env python3
"""Expand the AegisKV Overview into an editable DP=2, TP=2 deployment.

The example uses compatible head-sharded TP layouts. Rank i owns shard i;
Peer objects on the corresponding remote rank are selected layer/block
objects, not a second complete KV cache on every GPU.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/system-overview-dp-tp-20260923'
SOURCE = ROOT / 'exports/fixed-peer-lazy-credit-20260921/sources/system-overview.drawio'
FONT = 26.5
INK, EDGE = '#243746', '#70808A'
GRAY, ENGINE = '#F1F3F4', '#F4F5F1'
MINT, TEAL = '#E1EEE8', '#39756A'
PALE, BLUE = '#DDEBF3', '#23688D'
AMBER, AMBER_EDGE = '#F3E5D1', '#9B6428'


def main():
    tree = ET.parse(SOURCE)
    graph = tree.find('.//root')
    cells = {c.get('id'): c for c in graph.findall('mxCell')}

    def style(cell, **updates):
        atoms = [x for x in cell.get('style', '').split(';') if x]
        flags = [x for x in atoms if '=' not in x]
        values = dict(x.split('=', 1) for x in atoms if '=' in x)
        values.update({k: str(v) for k, v in updates.items()})
        cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')

    def geometry(ident, **updates):
        cells[ident].find('mxGeometry').attrib.update({k: str(v) for k, v in updates.items()})

    def route(cell, points):
        g = cell.find('mxGeometry')
        for old in list(g):
            g.remove(old)
        a = ET.SubElement(g, 'Array', {'as': 'points'})
        for x, y in points:
            ET.SubElement(a, 'mxPoint', x=str(x), y=str(y))

    def node(ident, text, x, y, w, h, *, parent='1', fill='none',
             stroke='none', bold=False, align='center', extra=''):
        c = ET.SubElement(graph, 'mxCell', id=ident, value=text, vertex='1', parent=parent)
        c.set('style', 'html=0;whiteSpace=wrap;verticalAlign=middle;spacing=1;'
              f'fontFamily=Linux Libertine O;fontSize={FONT};fontColor={INK};'
              f'fillColor={fill};strokeColor={stroke};strokeWidth=1;'
              f'fontStyle={int(bold)};align={align};{extra}')
        ET.SubElement(c, 'mxGeometry', x=str(x), y=str(y), width=str(w),
                      height=str(h), **{'as': 'geometry'})
        cells[ident] = c
        return c

    def edge(ident, source, target, *, start=(1, .5), end=(0, .5),
             color=BLUE, both=True, points=(), small=False, arrow=True):
        c = ET.SubElement(graph, 'mxCell', id=ident, parent='1', edge='1',
                          source=source, target=target)
        c.set('style', 'rounded=0;'
              f'strokeColor={color};strokeWidth={1.8 if small else 2.2};'
              f'startArrow={"block" if both else "none"};startFill=1;'
              f'endArrow={"block" if arrow else "none"};endFill=1;'
              f'startSize={2 if small else 4};endSize={2 if small else 4};'
              f'exitX={start[0]};exitY={start[1]};exitPerimeter=0;'
              f'entryX={end[0]};entryY={end[1]};entryPerimeter=0;')
        ET.SubElement(c, 'mxGeometry', relative='1', **{'as': 'geometry'})
        if points:
            route(c, points)
        cells[ident] = c
        return c

    # Keep the controller mechanisms and palette. Reclaim the metadata strip
    # for the deployment detail instead of shrinking the complete drawing.
    remove = {'directory'}
    descendants = {'engine'}
    while True:
        new = {i for i, c in cells.items() if c.get('parent') in descendants}
        if new <= descendants:
            break
        descendants |= new
    remove |= descendants - {'engine'}
    keep_edges = {'dispatch', 'retry', 'budget', 'master-connector'}
    for i, c in cells.items():
        if c.get('edge') and i not in keep_edges and (
                c.get('source') in remove or c.get('target') in remove):
            remove.add(i)
    for ident in remove:
        graph.remove(cells.pop(ident))

    geometry('canvas', height=650)
    geometry('controller', height=152)
    geometry('engine', y=247, height=396)
    node('engine-label', 'Engine', 12, 1, 113, 27, parent='engine', bold=True, align='left')
    node('normal', 'Run', 171, 1, 64, 26, parent='engine')
    node('retry-label', 'Retry', 449, 1, 91, 26, parent='engine')

    route(cells['dispatch'], [(200, 169), (200, 240), (13, 240), (13, 276), (152, 276)])
    route(cells['retry'], [(389, 138), (389, 240), (589, 240), (589, 277), (448, 277)])
    route(cells['budget'], [(295, 330), (295, 244), (474.98, 244)])

    # Each DP contains two GPU/HBM ranks. The rank-level Connector makes both
    # matched Peer transfers and shared-tier access paths explicit.
    for dp in range(2):
        x = 20 + 296 * dp
        node(f'dp{dp}', '', x-8, 38, 264, 270, parent='engine', fill='#FFFFFF', stroke=EDGE,
             extra='rounded=1;arcSize=6;container=1;collapsible=0;')
        node(f'dp{dp}-name', f'DP{dp} · TP = 2', 5, 1, 254, 26, parent=f'dp{dp}')
        node(f'adapter{dp}', 'Adapter (AIMD)', 7, 32, 250, 26,
             parent=f'dp{dp}', fill=GRAY, stroke=EDGE)
        node(f'local-header{dp}', 'Local', 61, 60, 91, 26, parent=f'dp{dp}')
        node(f'peer-header{dp}', 'Peer', 158, 60, 93, 26, parent=f'dp{dp}')
        for tp in range(2):
            rank = f'dp{dp}-tp{tp}'
            y = 90 + tp * 87
            node(rank, '', 7, y, 250, 76, parent=f'dp{dp}',
                 fill='#FFFFFF', stroke='#C5D6E1',
                 extra='rounded=1;arcSize=6;container=1;collapsible=0;')
            node(f'{rank}-label', f'TP{tp}', 1, 4, 49, 26, parent=rank)
            for pool, bx, bw, fill, stroke in [('local', 54, 91, GRAY, TEAL),
                                              ('peer', 151, 93, PALE, BLUE)]:
                pool_id = f'{rank}-{pool}'
                node(pool_id, '', bx, 1, bw, 38, parent=rank,
                     fill=fill, stroke=stroke, extra='rounded=1;arcSize=6;')
                node(f'{pool_id}-label', f'shard {tp}', 1, 0, bw-2, 26,
                     parent=pool_id)
                # Two rows stand for K and V; token blocks are schematic.
                # Peer contains a selected subset; orange is an unsealed tail.
                for kv in range(2):
                    count = 5 if pool == 'local' else 2
                    for block in range(count):
                        tail = pool == 'local' and block == 4
                        node(f'{pool_id}-kv{kv}-{block}', '', 5 + block*16, 27+kv*6,
                             11, 4, parent=pool_id,
                             fill=AMBER if tail else '#FFFFFF',
                             stroke=AMBER_EDGE if tail else stroke)
            conn = f'connector-dp{dp}-tp{tp}'
            node(conn, 'Connector', 54, 49, 190, 25, parent=rank,
                 fill='#FFFFFF', stroke=BLUE)
            edge(f'{rank}-local-io', f'{rank}-local', conn,
                 start=(.5, 1), end=(45.5/190, 0), small=True)
            edge(f'{rank}-peer-io', f'{rank}-peer', conn,
                 start=(.5, 1), end=(143.5/190, 0), small=True)

    geometry('adapter-number', y=315.5)
    cells['master-connector'].set('target', 'connector-dp1-tp0')
    style(cells['master-connector'], entryX=1, entryY=0)
    route(cells['master-connector'], [(608, 185), (608, 424)])
    for tp in range(2):
        edge(f'peer-copy-tp{tp}', f'connector-dp0-tp{tp}', f'connector-dp1-tp{tp}')

    # A shared transfer fabric, outside either DP failure boundary. Put its
    # vertical access spines on the outside, away from the two Peer links.
    node('fabric', '', 16, 568, 574, 5, fill='#ABC5D6', stroke=BLUE)
    for dp, spine in [(0, 16), (1, 590)]:
        node(f'fabric-tap{dp}', '', spine, 523.5, 0, 0)
        if dp == 0:
            start, end = (0, .5), (0, 0)
        else:
            start, end = (1, .5), (1, 0)
        edge(f'shared-access{dp}', f'connector-dp{dp}-tp0', 'fabric',
             start=start, end=end, points=[(spine, 436.5), (spine, 568)])
        edge(f'shared-branch{dp}', f'connector-dp{dp}-tp1', f'fabric-tap{dp}',
             start=start, end=(0, 0), arrow=False)

    # Preserve the storage-resource glyphs and the Overview's established colors.
    for level in range(3):
        node(f'dram{level}', '', 54+level*4, 590+level*4, 195, 8, fill=MINT, stroke=TEAL)
        for k in range(6):
            node(f'chip{level}-{k}', '', 62+level*4+k*29, 592+level*4,
                 20, 4, fill=TEAL)
        node(f'storage{level}', '', 428-level*4, 589+level*4,
             74, 14, fill=AMBER, stroke=AMBER_EDGE, extra='rounded=1;arcSize=12;')
    node('dram-label', 'Shared DRAM', 30, 614, 247, 26)
    node('storage-label', 'Shared storage', 323, 614, 257, 26)
    edge('dram-io', 'fabric', 'dram0', start=((151.5-16)/574, 1), end=(.5, 0))
    edge('storage-io', 'fabric', 'storage0', start=((465-16)/574, 1), end=(.5, 0))
    edge('lower-tier-io', 'dram2', 'storage2', start=(1, .75))

    # Draw paths above the DP containers so their in-board endpoints remain visible.
    for c in list(graph):
        if c.get('edge'):
            graph.remove(c)
            graph.append(c)

    # Keep callout annotations as the top Draw.io layer.
    model = tree.find('.//mxGraphModel')
    model.set('pageWidth', '624')
    model.set('pageHeight', '650')
    dest = OUT / 'sources/system-overview.drawio'
    dest.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree)
    tree.write(dest, encoding='utf-8', xml_declaration=True)
    print(dest)


if __name__ == '__main__':
    main()
