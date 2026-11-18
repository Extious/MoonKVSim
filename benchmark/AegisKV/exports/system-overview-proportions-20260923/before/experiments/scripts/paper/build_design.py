#!/usr/bin/env python3
"""Editable two-tier diagrams for the current O1/O2/O3 design.

The overview reuses only deployment geometry and typography. The region
map is constructed state, not an access trace or measured recovery result.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import build_storage_design as drawing
from build_storage_design import Diagram, BLUE, PALE, GREEN, MINT, LINE, GRAY

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/system-design-current'
drawing.OUT = OUT
FONT = 26.5


def update_style(cell, **updates):
    parts = [x for x in cell.get('style', '').split(';') if x]
    flags = [x for x in parts if '=' not in x]
    values = dict(x.split('=', 1) for x in parts if '=' in x)
    values.update({k: str(v) for k, v in updates.items()})
    cell.set('style', ';'.join(flags + [f'{k}={v}' for k, v in values.items()]) + ';')


def overview():
    source = ROOT / 'exports/system-design-current/inputs/system-overview-base.drawio'
    tree = ET.parse(source)
    graph = tree.find('.//root')
    cells = {c.get('id'): c for c in graph.findall('mxCell')}
    remove = {i for i in cells if i.startswith(('dram', 'chip', 'fabric', 'shared-'))}
    # Overview shows component roles; mechanisms belong in their sections.
    remove.update(i for i, c in cells.items()
                  if c.get('parent') in {'tracker', 'router', 'master'}
                  and not i.endswith('-label'))
    for ident, cell in cells.items():
        if cell.get('source') in remove or cell.get('target') in remove:
            remove.add(ident)
    for ident in remove:
        graph.remove(cells[ident])

    def route(ident, start, end, points=(), **style):
        cell = cells[ident]
        update_style(cell, exitX=start[0], exitY=start[1], entryX=end[0],
                     entryY=end[1], strokeWidth=1.6, startSize=3, endSize=3,
                     rounded=0, **style)
        geometry = cell.find('mxGeometry')
        for child in list(geometry):
            geometry.remove(child)
        if points:
            array = ET.SubElement(geometry, 'Array', **{'as': 'points'})
            for x, y in points:
                ET.SubElement(array, 'mxPoint', x=str(x), y=str(y))

    # Separate short execution paths from the control feedback lanes.
    route('target', (1, .5), (0, .5), startArrow='block', startFill=1)
    route('slack-value', (.85, 1), (.18, 1),
          [(164.5, 232), (434.04, 232)], jumpStyle='gap', jumpSize=6)
    route('dispatch', (.2, 1), (.5, 0), [(246.2, 277), (152, 277)])
    route('retry', (.8, 1), (.5, 0), [(345.8, 277), (448, 277)])
    cells['normal'].find('mxGeometry').set('x', '158')
    cells['retry-label'].find('mxGeometry').set('x', '357')
    # The equivalent right-hand Adapter avoids a cross-worker feedback loop.
    cells['budget'].set('source', 'adapter1')
    route('budget', (1, .5), (1, .91), [(594, 330), (594, 214)],
          jumpStyle='none')
    route('master-connector', (1, .42), (1, .5),
          [(608, 165), (608, 452)])
    for ident in ['progress', 'requests']:
        update_style(cells[ident], strokeWidth=1.6, startSize=3, endSize=3)
    # Separate arrowheads where branches join; short memory links need no heads.
    update_style(cells['bd'], entryY=.25, endSize=3)
    update_style(cells['cd'], entryY=.75, endSize=3)
    for ident, cell in cells.items():
        if ident.endswith(('-local-io', '-peer-io')):
            update_style(cell, startArrow='none', endArrow='none', strokeWidth=1.4)
        elif ident.startswith('peer-copy-'):
            update_style(cell, strokeWidth=1.8, startSize=3, endSize=3)
    d = Diagram('system-overview', 624, 650)
    d.root = graph
    d.origins = {'1': (0, 0), 'dp0': (20, 285), 'dp1': (316, 285),
                 'tracker': (20, 123), 'router': (213, 123), 'master': (402, 123)}
    cells['request'].set('value', 'Agent workflow')
    # Small object diagrams convey roles without mechanism labels.
    def icon_edge(ident, source, target, **kwargs):
        d.edge(ident, source, target, color=LINE, **kwargs)
        update_style(graph[-1], strokeWidth=1.5, endSize=3)

    # Workflow nodes with distinct states, connected through a fork/join.
    for ident, x, y, filled in [
        ('start', 40, 183, True), ('upper', 94, 166, True),
        ('lower', 94, 200, False), ('join', 148, 183, False),
    ]:
        d.node(f'tracker-icon-{ident}', '', x, y, 24, 14, parent='tracker',
               fill=GREEN if filled else '#FFFFFF', stroke=GREEN)
    for source, target in [('start', 'upper'), ('start', 'lower'),
                           ('upper', 'join'), ('lower', 'join')]:
        start_y = (.2 if target == 'upper' else .8) if source == 'start' else .5
        end_y = (.2 if source == 'upper' else .8) if target == 'join' else .5
        icon_edge(f'tracker-icon-{source}-{target}', f'tracker-icon-{source}',
                  f'tracker-icon-{target}', start=(1, start_y), end=(0, end_y))

    # Requests pass through a routing point to worker destinations.
    for i, y in enumerate([171, 184, 197]):
        d.node(f'router-icon-request-{i}', '', 230, y, 30, 8,
               parent='router', fill='#FFFFFF', stroke=BLUE)
    d.node('router-icon-switch', '', 284, 183, 10, 10,
           parent='router', fill=LINE, stroke=LINE, extra='shape=rhombus;')
    icon_edge('router-icon-input', 'router-icon-request-1', 'router-icon-switch',
              start=(1, .5), end=(0, .5))
    for i, y in enumerate([165, 199]):
        d.node(f'router-icon-worker-{i}', '', 330, y, 24, 19,
               parent='router', fill=PALE if i == 0 else '#FFFFFF', stroke=BLUE)
        icon_edge(f'router-icon-route-{i}', 'router-icon-switch',
                  f'router-icon-worker-{i}', start=(1, .5), end=(0, .5),
                  points=[(309, 188), (309, y+9.5)])

    # Filled and outlined KV blocks distinguish the selected subset.
    for row in range(2):
        for col in range(4):
            selected = (row, col) in {(0, 0), (0, 2), (1, 1)}
            d.node(f'master-icon-block-{row}-{col}', '',
                   426+34*col, 169+27*row, 24, 18, parent='master',
                   fill=BLUE if selected else '#FFFFFF',
                   stroke=BLUE if selected else LINE)
    for worker, x in [(0, 20), (1, 316)]:
        cells[f'dp{worker}'].find('mxGeometry').set('height', '348')
        cells[f'dp{worker}-name'].set('value', f'DP{worker} / Host{worker}')
        cells[f'local-header{worker}'].set('value', 'Exec.')
        cells[f'peer-header{worker}'].set('value', 'Replica')
        cells[f'adapter{worker}'].set('value', 'Adapter')
        # Redistribute the previous bottom gap into evenly padded TP rows.
        for header, left in [('local', 61), ('peer', 161)]:
            geometry = cells[f'{header}-header{worker}'].find('mxGeometry')
            geometry.set('x', str(left))
            geometry.set('width', '90')
        for rank, top in [(0, 90), (1, 192)]:
            prefix = f'dp{worker}-tp{rank}'
            geometry = cells[prefix].find('mxGeometry')
            geometry.set('y', str(top))
            geometry.set('height', '94')
            cells[f'{prefix}-label'].find('mxGeometry').set('y', '9')
            for tier, left in [('local', 54), ('peer', 154)]:
                geometry = cells[f'{prefix}-{tier}'].find('mxGeometry')
                for key, value in {'x': left, 'y': 6, 'width': 90, 'height': 47}.items():
                    geometry.set(key, str(value))
                label = cells[f'{prefix}-{tier}-label'].find('mxGeometry')
                for key, value in {'x': 3, 'y': 3, 'width': 84, 'height': 26}.items():
                    label.set(key, str(value))
                for ident, cell in cells.items():
                    if ident.startswith(f'{prefix}-{tier}-kv'):
                        row, col = map(int, ident.split('-kv')[1].split('-'))
                        block = cell.find('mxGeometry')
                        block.set('x', str(7+16*col))
                        block.set('y', str(33+7*row))
            connector = cells[f'connector-dp{worker}-tp{rank}'].find('mxGeometry')
            connector.set('x', '6')
            connector.set('y', '63')
            connector.set('width', '238')
            connector.set('height', '28')
            # Align the short memory connections with the two column centers.
            update_style(cells[f'{prefix}-local-io'], entryX=93/238)
            update_style(cells[f'{prefix}-peer-io'], entryX=193/238)
        ident = f'peer-dram-dp{worker}'
        d.node(ident, '', x+27, 582, 210, 45, parent=f'dp{worker}', fill=MINT, stroke=GREEN)
        d.node(f'{ident}-label', 'DRAM', x+29, 583, 206, 30, parent=ident, font=FONT)
        for chip in range(6):
            d.node(f'{ident}-chip-{chip}', '', x+40+33*chip, 616, 25, 6,
                   parent=ident, fill=GREEN, stroke=GREEN)
        outer_x = x+3 if worker == 0 else x+261
        connector_x = x+24.9 if worker == 0 else x+239.1
        d.edge(f'host-dram-dp{worker}-tp0', f'connector-dp{worker}-tp0', ident,
               start=(.05 if worker == 0 else .95, 1),
               end=(0 if worker == 0 else 1, .5),
               points=[(connector_x,471),(outer_x,471),(outer_x,604.5)],
               both=True, color=BLUE)
        update_style(graph[-1], startSize=3, endSize=3, strokeWidth=1.6)
        d.edge(f'host-dram-dp{worker}-tp1', f'connector-dp{worker}-tp1', ident,
               start=(.5,1), end=(.5,0),
               both=True, color=BLUE)
        update_style(graph[-1], startArrow='none', endArrow='none', strokeWidth=1.6)
    for cell in graph.findall('mxCell'):
        if cell.get('vertex'):
            update_style(cell, fontFamily='Linux Libertine O')
    # Independent paper annotations identify the four component types.
    d.origins['annotations'] = (0, 0)
    for ident in ['tracker', 'router', 'master']:
        label = cells[f'{ident}-label'].find('mxGeometry')
        label.set('x', '22')
        label.set('width', str(int(cells[ident].find('mxGeometry').get('width')) - 25))
    for ident, number, x, y in [
        ('tracker', '1', 11.5, 119.5),
        ('router', '2', 204.5, 119.5),
        ('master', '3', 393.5, 119.5),
        ('adapter', '4', 13.5, 315.5),
    ]:
        d.node(f'{ident}-number', number, x, y, 27, 27,
               parent='annotations', font=FONT, bold=True,
               fill='#151E24', stroke='#151E24',
               extra='shape=ellipse;fontColor=#FFFFFF;fontFamily=Linux Libertine O;')
    tree.find('.//diagram').set('name', 'Four components with peer-owned HBM and DRAM')
    dest = OUT / 'sources/system-overview.drawio'
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
    d = Diagram('invocation-reuse', 624, 303)

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
    d = Diagram('selective-recovery', 624, 472)

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
