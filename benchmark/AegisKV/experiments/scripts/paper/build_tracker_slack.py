#!/usr/bin/env python3
"""Illustrative residual DAG and Slack update; no fitted accuracy data."""
from pathlib import Path
import json
import build_storage_design as base
from build_storage_design import Diagram, PALE, BLUE, MINT, GREEN, GRAY, LINE, WHITE

ROOT = Path(__file__).resolve().parents[3]
base.OUT = ROOT / 'exports/design-section-ready-20260921'


def build():
    d = Diagram('tracker-slack', 600, 432)
    def n(*a, **kw):
        kw.setdefault('font', 25.8)
        return d.node(*a, **kw)
    e = d.edge
    n('features', 'Role / context / elapsed / call history', 10, 5, 580, 36,
      fill=GRAY, stroke=LINE)
    n('predictor', 'GBDT: remaining segment time', 55, 60, 490, 36,
      fill=MINT, stroke=GREEN)
    e('features-predictor', 'features', 'predictor')
    n('graph-label', 'Residual DAG · version v', 10, 113, 580, 30,
      bold=True, align='left')
    n('fork-label', 'Fork', 5, 197, 76, 28)
    n('fork', '', 34, 177, 12, 12, fill=LINE, stroke=LINE,
      extra='ellipse;shape=ellipse;')
    n('b', 'B: 6 s', 125, 151, 140, 38, fill=PALE, stroke=BLUE)
    n('c', 'C: 10 s', 125, 226, 140, 38, fill=WHITE, stroke=BLUE,
      extra='strokeWidth=3;')
    n('join', '', 342, 198, 12, 12, fill=LINE, stroke=LINE,
      extra='ellipse;shape=ellipse;')
    n('join-label', 'Join', 313, 228, 72, 28)
    n('continuation', 'D: 2 s', 425, 185, 140, 38, fill=WHITE, stroke=BLUE,
      extra='strokeWidth=3;')
    for key, src, dst in [('fb','fork','b'), ('fc','fork','c'),
                          ('bj','b','join'), ('cj','c','join'),
                          ('jd','join','continuation')]:
        e(key, src, dst, start=(1,.5), end=(0,.5), color=LINE)
    n('slack', 'CPM → Slack: B = 4 s; C = 0 s', 10, 285, 580, 34,
      fill=GRAY, stroke=LINE)
    n('refresh', 'Update B → 11 s: Slack B = 0; C = 1 s', 10, 334, 580, 34,
      fill=PALE, stroke=BLUE)
    n('version', 'Version v + 1 → revalue placement', 10, 388, 580, 32,
      fill=MINT, stroke=GREEN)
    e('new-version', 'refresh', 'version')
    path = d.save()
    cases = []
    for b, c in [(6,10),(11,10)]:
        finish = max(b,c)+2
        cases.append({'B_remaining_s':b,'C_remaining_s':c,'D_remaining_s':2,
                      'finish_s':finish,'B_slack_s':finish-2-b,'C_slack_s':finish-2-c})
    assert [(x['B_slack_s'],x['C_slack_s']) for x in cases] == [(4,0),(0,1)]
    (base.OUT/'data/tracker-slack-example.json').write_text(json.dumps({
        'evidence':'constructed dependency example, not predictor measurements',
        'slack':'nominal, before calibration guard',
        'cases':cases},indent=2)+'\n')
    return path


if __name__ == '__main__':
    print(build())
