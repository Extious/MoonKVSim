#!/usr/bin/env python3
"""Editable three-layer AegisKV architecture, with concrete resource ownership."""
from pathlib import Path
import build_storage_design as base
from build_storage_design import Diagram, INK, LINE, BLUE, PALE, ORANGE, SAND, GREEN, MINT, WHITE

OUT = Path(__file__).resolve().parents[3] / 'exports/system-overview-three-layer-20260921'
base.OUT = OUT
RED = '#AC4251'


def main():
    d = Diagram('system-overview', 500, 542)
    def n(*args, **kwargs):
        kwargs.setdefault('font', 22)
        return d.node(*args, **kwargs)
    e = d.edge
    def region(key, x, y, w, h, fill, stroke=LINE, parent='1'):
        return n(key, '', x, y, w, h, fill=fill, stroke=stroke, parent=parent,
                 extra='rounded=1;arcSize=8;container=1;collapsible=0;')

    # Three ownership bands are explicit native groups, not just background labels.
    region('application', 8, 8, 484, 75, '#F1F4F6')
    n('application-title', 'Application', 19, 16, 146, 27, bold=True, align='left', parent='application')
    n('workflow-label', 'Workflow', 19, 46, 142, 27, align='left', parent='application')
    for key, label, x, y in [('a', 'A', 184, 33), ('b', 'B', 285, 15),
                             ('c', 'C', 285, 52), ('d', 'D', 408, 33)]:
        n(key, label, x, y, 44, 27, fill=WHITE, stroke=LINE, parent='application',
          extra='rounded=1;arcSize=20;')
    for key, src, dst in [('ab', 'a', 'b'), ('ac', 'a', 'c'), ('bd', 'b', 'd'), ('cd', 'c', 'd')]:
        e(key, src, dst, start=(1, .5), end=(0, .5), color=LINE)

    region('controller', 8, 104, 484, 174, '#EAF1F6')
    n('controller-title', 'Controller', 19, 110, 151, 29, bold=True, align='left', parent='controller')
    for key, title, detail, x, w, fill, color in [
        ('tracker', 'Tracker', 'Slack', 20, 136, MINT, GREEN),
        ('master', 'KV Master', 'Value/rent', 178, 140, PALE, BLUE),
        ('router', 'Router', 'Load/KV', 340, 138, '#DDE5EF', BLUE),
    ]:
        region(key, x, 150, w, 60, fill, color, parent='controller')
        n(key+'-title', title, x+2, 152, w-4, 27, bold=True, parent=key)
        n(key+'-detail', detail, x+2, 180, w-4, 27, parent=key)
    e('slack', 'tracker', 'master', start=(1, .5), end=(0, .5), dashed=True)
    # Persistent metadata is owned by the controller, outside compute-worker boundaries.
    n('metadata-back', '', 25, 233, 289, 32, fill='#D3DFE8', stroke=LINE, parent='controller')
    n('metadata', 'Directory / token log', 20, 237, 294, 32, fill=WHITE, stroke=LINE, parent='controller')
    e('commit-state', 'master', 'metadata', start=(.5, 1), end=(.775, 0), dashed=True, both=True)
    # Workflow edges denote dependencies; these cross-layer links denote messages.
    e('dag-metadata', 'application', 'tracker', start=(168/484, 1), end=(.5, 0),
      points=[(176, 142), (88, 142)], dashed=True)
    e('request', 'application', 'router', start=(.829, 1), end=(.5, 0))

    region('engine', 8, 294, 484, 240, '#F4F5F1')
    n('engine-title', 'Engine', 19, 297, 101, 28, bold=True, align='left', parent='engine')
    for i, x in enumerate([20, 264]):
        key = f'worker{i}'
        region(key, x, 342, 214, 91, WHITE, parent='engine')
        n(key+'-title', f'DP {i}', x+7, 344, 72, 26, bold=True, align='left', parent=key)
        n(f'gpu{i}', 'GPU', x+15, 381, 64, 34, fill='#D9E3E9', stroke=LINE, bold=True, parent=key,
          extra='rounded=1;arcSize=8;')
        for j in range(4):
            for side, yy in [('top', 377), ('bottom', 415)]:
                n(f'pin-{i}-{side}-{j}', '', x+22+j*13, yy, 5, 4, fill=LINE, parent=key)
        for j in range(3):
            for side, xx in [('left', x+11), ('right', x+79)]:
                n(f'pin-{i}-{side}-{j}', '', xx, 386+j*10, 4, 4, fill=LINE, parent=key)
        n(f'hbm{i}', '', x+104, 371, 100, 53, fill=MINT, stroke=GREEN, parent=key)
        n(f'hbm-title{i}', 'HBM', x+107, 372, 94, 25, bold=True, parent=key)
        for row in range(2):
            for col in range(4):
                hot = col == (i+row)%3
                n(f'kv-{i}-{row}-{col}', '', x+112+22*col, 400+12*row, 16, 8,
                  fill=SAND if col==3 else WHITE, stroke=BLUE if hot else '#92B5A8', parent=key,
                  extra='strokeWidth=2.3;' if hot else '')
        e(f'gpu-hbm-{i}', f'gpu{i}', f'hbm{i}', start=(1, .5), end=(0, .5), both=True, color=BLUE)

    # Both workers can serve or recover; the drawn routes are illustrative.
    e('dispatch', 'router', 'worker0', start=(.45, 1), end=(.5, 0),
      points=[(402.1, 326), (127, 326)])
    e('retry', 'router', 'worker1', start=(.82, 1), end=(.5, 0),
      points=[(453.16, 334), (371, 334)], dashed=True, color=RED)
    n('run-label', 'Run', 177, 297, 55, 25, parent='engine')
    n('retry-label', 'Retry', 366, 297, 68, 25, parent='engine')
    e('placement-plan', 'master', 'engine', start=(1, .5), end=(.5, 0),
      points=[(328, 180), (328, 285), (250, 285)], dashed=True)
    e('worker-feedback', 'worker0', 'tracker', start=(0, .45), end=(0, .5),
      points=[(3, 382.95), (3, 180)], dashed=True)

    # DRAM and SSD are outside both DP groups; Engine here includes the data plane.
    n('fabric', '', 37, 449, 428, 6, fill='#ABC5D6', stroke=BLUE, parent='engine')
    for i, xx in enumerate([174, 418]):
        e(f'worker-io-{i}', f'hbm{i}', 'fabric', start=(.5, 1), end=((xx-37)/428, 0), both=True, color=BLUE)
    for j in range(3):
        n(f'dram-bank-{j}', '', 47+5*j, 482+5*j, 150, 10, fill=PALE, stroke=BLUE, parent='engine')
        for k in range(6):
            n(f'dram-chip-{j}-{k}', '', 53+5*j+23*k, 484+5*j, 15, 6, fill='#749DB6', parent='engine')
    n('dram-label', 'DRAM pool', 29, 506, 186, 25, bold=True, parent='engine')
    for j in range(3):
        n(f'ssd-{j}', '', 350-4*j, 474+4*j, 62, 20, fill=SAND if j==2 else WHITE,
          stroke=ORANGE, parent='engine', extra='rounded=1;arcSize=15;')
    n('ssd-led', '', 349, 494, 7, 4, fill=ORANGE, parent='engine')
    n('ssd-label', 'SSD / storage', 286, 506, 192, 25, bold=True, parent='engine')
    e('dram-io', 'fabric', 'dram-bank-0', start=((122-37)/428, 1), end=(.5, 0), both=True, color=BLUE)
    e('ssd-io', 'fabric', 'ssd-0', start=((381-37)/428, 1), end=(.5, 0), both=True, color=BLUE)
    e('tier-move', 'dram-bank-2', 'ssd-2', start=(1, .5), end=(0, .75), both=True, color=BLUE)
    print(d.save())


if __name__ == '__main__':
    main()
