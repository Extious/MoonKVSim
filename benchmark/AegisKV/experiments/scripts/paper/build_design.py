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
          [(608, 165), (608, 478)])
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
    d = Diagram('system-overview', 624, 700)
    d.root = graph
    cells['canvas'].find('mxGeometry').set('height', '700')
    cells['engine'].find('mxGeometry').set('height', '446')
    tree.find('.//mxGraphModel').set('pageHeight', '700')
    d.origins = {'1': (0, 0), 'application': (8, 6),
                 'dp0': (20, 285), 'dp1': (316, 285),
                 'tracker': (20, 123), 'router': (213, 123), 'master': (402, 123)}
    cells['request'].set('value', 'Agent workflow')
    # Each box is an invocation. Repeated B/C calls stay on their branches;
    # the initiating A and downstream D are different Agent identities.
    for ident, label, left, top, fill, stroke in [
        ('a', 'A1', 204, 20, '#FFFFFF', LINE),
        ('b', 'B1', 304, 3, MINT, GREEN),
        ('c', 'C1', 304, 35, PALE, BLUE),
        ('d', 'D1', 504, 20, '#FFFFFF', LINE),
    ]:
        cell = cells[ident]
        cell.set('value', label)
        cell.find('mxGeometry').set('x', str(left))
        cell.find('mxGeometry').set('y', str(top))
        update_style(cell, fillColor=fill, strokeColor=stroke)
    for ident, label, top, fill, stroke in [
        ('b2', 'B2', 9, MINT, GREEN),
        ('c2', 'C2', 41, PALE, BLUE),
    ]:
        d.node(ident, label, 412, top, 64, 25,
               parent='application', fill=fill, stroke=stroke)
        update_style(graph[-1], strokeWidth=1)
    cells['bd'].set('source', 'b2')
    cells['cd'].set('source', 'c2')
    for ident, end_y in [('ab', .3), ('ac', .7)]:
        update_style(cells[ident], exitY=end_y)
    for ident in ['ab', 'ac', 'bd', 'cd']:
        update_style(cells[ident], strokeWidth=1.5, endSize=3)
    for first, second in [('b', 'b2'), ('c', 'c2')]:
        d.edge(f'{first}-next', first, second, start=(1, .5), end=(0, .5), color=LINE)
        update_style(graph[-1], strokeWidth=1.5, endSize=3)
    (OUT / 'data/overview-workflow.json').write_text(json.dumps({
        'evidence': 'constructed invocation DAG, not the Figure 2 trace',
        'notation': 'Xr is invocation r of Agent X, without parentheses; each box is one invocation',
        'nodes': [
            {'id': ident, 'agent': agent, 'invocation': invocation}
            for ident, agent, invocation in [
                ('a', 'A', 1), ('b', 'B', 1), ('b2', 'B', 2),
                ('c', 'C', 1), ('c2', 'C', 2), ('d', 'D', 1)]
        ],
        'edges': [['a', 'b'], ['b', 'b2'], ['b2', 'd'],
                  ['a', 'c'], ['c', 'c2'], ['c2', 'd']],
        'reuse_requires': 'materialized exact compatible prefix; Agent identity alone is insufficient',
    }, indent=2) + '\n')
    # Small object diagrams convey roles without mechanism labels.
    def icon_edge(ident, source, target, **kwargs):
        d.edge(ident, source, target, color=LINE, **kwargs)
        update_style(graph[-1], strokeWidth=1.5, endSize=3)

    # Workflow nodes with distinct states, connected through a fork/join.
    for ident, x, y, filled in [
        ('start', 38, 181, True), ('upper', 91, 162, True),
        ('lower', 91, 199, False), ('join', 146, 181, False),
    ]:
        d.node(f'tracker-icon-{ident}', '', x, y, 30, 20, parent='tracker',
               fill=GREEN if filled else '#FFFFFF', stroke=GREEN)
    for source, target in [('start', 'upper'), ('start', 'lower'),
                           ('upper', 'join'), ('lower', 'join')]:
        start_y = (.2 if target == 'upper' else .8) if source == 'start' else .5
        end_y = (.2 if source == 'upper' else .8) if target == 'join' else .5
        icon_edge(f'tracker-icon-{source}-{target}', f'tracker-icon-{source}',
                  f'tracker-icon-{target}', start=(1, start_y), end=(0, end_y))

    # Requests pass through a routing point to worker destinations.
    for i, y in enumerate([167, 183, 199]):
        d.node(f'router-icon-request-{i}', '', 227, y, 36, 12,
               parent='router', fill='#FFFFFF', stroke=BLUE)
    d.node('router-icon-switch', '', 282, 183, 12, 12,
           parent='router', fill=LINE, stroke=LINE, extra='shape=rhombus;')
    icon_edge('router-icon-input', 'router-icon-request-1', 'router-icon-switch',
              start=(1, .5), end=(0, .5))
    for i, y in enumerate([160, 195]):
        d.node(f'router-icon-worker-{i}', '', 329, y, 31, 25,
               parent='router', fill=PALE if i == 0 else '#FFFFFF', stroke=BLUE)
        icon_edge(f'router-icon-route-{i}', 'router-icon-switch',
                  f'router-icon-worker-{i}', start=(1, .5), end=(0, .5),
                  points=[(309, 189), (309, y+12.5)])

    # Filled and outlined KV blocks distinguish the selected subset.
    for row in range(2):
        for col in range(4):
            selected = (row, col) in {(0, 0), (0, 2), (1, 1)}
            d.node(f'master-icon-block-{row}-{col}', '',
                   425+33*col, 164+30*row, 27, 24, parent='master',
                   fill=BLUE if selected else '#FFFFFF',
                   stroke=BLUE if selected else LINE)
    for worker, x in [(0, 20), (1, 316)]:
        cells[f'dp{worker}'].find('mxGeometry').set('height', '398')
        cells[f'dp{worker}-name'].set('value', f'DP{worker} / Host{worker}')
        cells[f'local-header{worker}'].set('value', 'Exec.')
        cells[f'peer-header{worker}'].set('value', 'Replica')
        cells[f'adapter{worker}'].set('value', 'Adapter')
        # Redistribute the previous bottom gap into evenly padded TP rows.
        for header, left in [('local', 61), ('peer', 161)]:
            geometry = cells[f'{header}-header{worker}'].find('mxGeometry')
            geometry.set('x', str(left))
            geometry.set('width', '90')
        for rank, top in [(0, 90), (1, 217)]:
            prefix = f'dp{worker}-tp{rank}'
            geometry = cells[prefix].find('mxGeometry')
            geometry.set('y', str(top))
            geometry.set('height', '119')
            cells[f'{prefix}-label'].find('mxGeometry').set('y', '9')
            # One rank owns one HBM resource, partitioned into execution and
            # replica allocations. Connector stays outside this memory shell.
            d.origins[prefix] = (x+7, 285+top)
            hbm = f'{prefix}-hbm'
            d.node(hbm, '', x+57, 288+top, 197, 81, parent=prefix,
                   fill='#F7F9FB', stroke=LINE, extra='rounded=1;arcSize=4;')
            shell = graph[-1]
            update_style(shell, strokeWidth=1)
            graph.remove(shell)
            graph.insert(list(graph).index(cells[f'{prefix}-local']), shell)
            # Three offset planes provide a compact, editable memory-stack icon.
            for plane in range(3):
                d.node(f'{hbm}-plane-{plane}', '', x+115+2*plane,
                       298+top-2*plane, 20, 12, parent=hbm,
                       fill='#E4EBF1', stroke=LINE)
                update_style(graph[-1], strokeWidth=1)
            d.node(f'{hbm}-label', 'HBM', x+140, 289+top, 64, 24,
                   parent=hbm)
            for tier, left in [('local', 54), ('peer', 154)]:
                cells[f'{prefix}-{tier}'].set('parent', hbm)
                geometry = cells[f'{prefix}-{tier}'].find('mxGeometry')
                for key, value in {'x': left-50, 'y': 27, 'width': 90, 'height': 52}.items():
                    geometry.set(key, str(value))
                label = cells[f'{prefix}-{tier}-label'].find('mxGeometry')
                for key, value in {'x': 3, 'y': 2, 'width': 84, 'height': 23}.items():
                    label.set(key, str(value))
                for ident, cell in cells.items():
                    if ident.startswith(f'{prefix}-{tier}-kv'):
                        row, col = map(int, ident.split('-kv')[1].split('-'))
                        block = cell.find('mxGeometry')
                        block.set('x', str(4+17*col))
                        block.set('y', str(29+11*row))
                        block.set('width', '14')
                        block.set('height', '8')
            connector = cells[f'connector-dp{worker}-tp{rank}'].find('mxGeometry')
            connector.set('x', '6')
            connector.set('y', '90')
            connector.set('width', '238')
            connector.set('height', '26')
            # Align the short memory connections with the two column centers.
            update_style(cells[f'{prefix}-local-io'], entryX=93/238)
            update_style(cells[f'{prefix}-peer-io'], entryX=193/238)
        ident = f'peer-dram-dp{worker}'
        d.node(ident, '', x+27, 632, 210, 45, parent=f'dp{worker}', fill=MINT, stroke=GREEN)
        d.node(f'{ident}-label', 'DRAM', x+29, 633, 206, 25, parent=ident, font=FONT)
        for chip in range(6):
            d.node(f'{ident}-chip-{chip}', '', x+40+33*chip, 662, 25, 11,
                   parent=ident, fill=GREEN, stroke=GREEN)
        outer_x = x+3 if worker == 0 else x+261
        connector_x = x+24.9 if worker == 0 else x+239.1
        d.edge(f'host-dram-dp{worker}-tp0', f'connector-dp{worker}-tp0', ident,
               start=(.05 if worker == 0 else .95, 1),
               end=(0 if worker == 0 else 1, .5),
               points=[(connector_x,496),(outer_x,496),(outer_x,654.5)],
               both=True, color=BLUE)
        update_style(graph[-1], startSize=3, endSize=3, strokeWidth=1.6)
        d.edge(f'host-dram-dp{worker}-tp1', f'connector-dp{worker}-tp1', ident,
               start=(.5,1), end=(.5,0),
               both=True, color=BLUE)
        update_style(graph[-1], startArrow='none', endArrow='none', strokeWidth=1.6)
    # A modest hierarchy balances labels against the resource objects.
    # These sizes apply only to the Overview; mechanism figures keep FONT.
    section_titles = {'app-label', 'ctrl-label', 'engine-label'}
    component_titles = {'tracker-label', 'router-label', 'master-label',
                        'adapter0', 'adapter1'}
    for cell in graph.findall('mxCell'):
        if cell.get('vertex'):
            ident = cell.get('id')
            size = 26.5 if ident in section_titles else 25 if ident in component_titles else 23.5
            update_style(cell, fontFamily='Linux Libertine O', fontSize=size)
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
               parent='annotations', font=24, bold=True,
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
        'HBM_resources': [f'dp{w}-tp{r}-hbm' for w in range(2) for r in range(2)],
        'HBM_allocations': ['execution', 'replica'],
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


LAYERS, BLOCKS = 3, 4
ACCESS = {  # constructed access factors p for one protected Agent
    (1, 0): .9, (1, 1): .2, (1, 2): .8, (1, 3): .1,
    (2, 0): .3, (2, 1): .7, (2, 2): .2, (2, 3): .1,
    (3, 0): .8, (3, 1): .1, (3, 2): .6, (3, 3): .2,
}
SELECTED_COUNT, DEPTH_L, HBM_QUOTA = 5, 2, 2
TRANSFER_UNITS, COMPUTE_UNITS = 1, 2


def layer_schedule(dram):
    """Layer-ordered recovery: DRAM regions load in layer order over one H2D
    link; a layer starts after the previous layer and its own loads finish."""
    loads, compute, clock, previous = [], [], 0, 0
    for layer in range(1, LAYERS + 1):
        count = sum(1 for l, _ in dram if l == layer)
        if count:
            loads.append((layer, clock, clock + count*TRANSFER_UNITS))
            clock += count*TRANSFER_UNITS
        start = max(previous, clock if count else 0)
        if start > previous:
            compute.append(('Wait', previous, start))
        compute.append((f'L{layer}', start, start + COMPUTE_UNITS))
        previous = start + COMPUTE_UNITS
    return loads, compute, previous


def place_hbm(selected):
    """Promote HBM-eligible regions by recovery time removed (ties by p)."""
    hbm = set()
    for _ in range(HBM_QUOTA):
        eligible = [r for r in selected - hbm if r[0] <= DEPTH_L]
        base = layer_schedule(selected - hbm)[2]
        gain = {r: base - layer_schedule(selected - hbm - {r})[2] for r in eligible}
        best = max(eligible, key=lambda r: (gain[r], ACCESS[r]), default=None)
        if best is None or gain[best] <= 0:
            break
        hbm.add(best)
    return hbm


def selective():
    d = Diagram('selective-recovery', 624, 258)

    def n(*args, **kwargs):
        kwargs.setdefault('font', FONT)
        return d.node(*args, **kwargs)

    ranked = sorted(ACCESS, key=lambda r: (-ACCESS[r], r))
    selected = set(ranked[:SELECTED_COUNT])
    hbm = place_hbm(selected)
    dram = selected - hbm
    unbacked = 'fillColor=#FFFFFF;strokeColor=#B6C0C7;dashed=1;dashPattern=3 3;'

    n('select-title', '(a) Access factor p', 8, 4, 290, 33)
    n('place-title', f'(b) Placement, L = {DEPTH_L}', 326, 4, 290, 33)
    for panel, offset in [('select', 0), ('place', 323)]:
        for b in range(BLOCKS):
            n(f'{panel}-head-{b}', f'B{b}', 63 + offset + 55*b, 44, 48, 30)
        for layer in range(1, LAYERS + 1):
            y = 80 + 45*(layer - 1)
            n(f'{panel}-layer-{layer}', f'L{layer}', 12 + offset, y, 43, 35)
            for block in range(BLOCKS):
                key, x = (layer, block), 63 + offset + 55*block
                if panel == 'select':
                    label = f'{ACCESS[key]:.1f}'.lstrip('0')
                    if key in selected:
                        n(f'select-{layer}-{block}', label, x, y, 48, 35,
                          fill=GRAY, stroke=drawing.INK, bold=True)
                    else:
                        n(f'select-{layer}-{block}', label, x, y, 48, 35,
                          extra=unbacked + 'fontColor=#7A8790;')
                elif key in hbm:
                    n(f'place-{layer}-{block}', 'H', x, y, 48, 35, fill=PALE, stroke=BLUE)
                elif key in dram:
                    n(f'place-{layer}-{block}', 'D', x, y, 48, 35, fill=MINT, stroke=GREEN)
                else:
                    n(f'place-{layer}-{block}', '–', x, y, 48, 35, extra=unbacked)
    n('place-arrow', '→', 283, 123, 40, 35)
    n('depth-line', '', 383, 160, 220, 10,
      extra=f'shape=line;dashed=1;dashPattern=4 3;strokeColor={drawing.INK};')
    n('legend-selected', '', 64, 222, 40, 30, fill=GRAY, stroke=drawing.INK)
    n('legend-selected-text', 'Selected', 112, 222, 170, 30, align='left')
    n('legend-hbm', 'H', 348, 222, 36, 30, fill=PALE, stroke=BLUE)
    n('legend-hbm-text', 'HBM', 390, 222, 72, 30, align='left')
    n('legend-dram', 'D', 470, 222, 36, 30, fill=MINT, stroke=GREEN)
    n('legend-dram-text', 'DRAM', 512, 222, 90, 30, align='left')

    timings = {}
    for key, in_dram in [('placement', dram), ('all-dram', selected)]:
        loads, compute, finish = layer_schedule(in_dram)
        timings[key] = {'loads': loads, 'compute': compute, 'T': finish}

    (OUT / 'data/selective-state.json').write_text(json.dumps({
        'evidence': 'constructed example; access factors, sizes and time units are '
                    'illustrative, not measurements',
        'access_factor': {f'L{l}/B{b}': p for (l, b), p in sorted(ACCESS.items())},
        'selected': [f'L{l}/B{b}' for l, b in sorted(selected)],
        'selection_rule': f'{SELECTED_COUNT} hottest regions, assumed to meet the target',
        'L': DEPTH_L, 'hbm_quota_regions': HBM_QUOTA,
        'hbm': [f'L{l}/B{b}' for l, b in sorted(hbm)],
        'dram': [f'L{l}/B{b}' for l, b in sorted(dram)],
        'hbm_rule': 'greedy promotion of first-L regions by recovery time removed',
        'time_model': {'transfer_units_per_region': TRANSFER_UNITS,
                       'compute_units_per_layer': COMPUTE_UNITS,
                       'h2d': 'single link, layer order',
                       'unbacked_demand': 'omitted'},
        'placement_timelines': timings,
        'timelines_drawn': False,
        'complete_backup': False,
    }, indent=2) + '\n')
    return styled(d)


BUILDS = {'system-overview': overview, 'invocation-reuse': invocation_reuse,
          'selective-recovery': selective}


if __name__ == '__main__':
    import sys
    for subdir in ['sources', 'data', 'figures', 'review']:
        (OUT / subdir).mkdir(parents=True, exist_ok=True)
    for name in sys.argv[1:] or BUILDS:
        print(BUILDS[name]())
