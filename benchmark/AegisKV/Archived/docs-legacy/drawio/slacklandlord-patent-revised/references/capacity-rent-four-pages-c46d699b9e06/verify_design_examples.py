#!/usr/bin/env python3
"""Check current diagram numbers against the capacity-model reference."""
from dataclasses import replace
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
DESIGN = OUT.parent.parent / 'algorithm-2'
sys.path.insert(0, str(DESIGN))
from reference import Agent, Chunk, Model, Node, Problem, Scenario, ValueCache, Workflow, exhaustive, fractional_bound, solve
from test_reference import chain_model

source = OUT/'algorithm-2-patent-revised.drawio'
tree = ET.parse(source).getroot()
assert [p.get('id') for p in tree.findall('diagram')] == ['agents', 'flow', 'value', 'lazy']
labels = {c.get('id'): c.get('value', '') for c in tree.findall('.//mxCell')}
all_labels = '\n'.join(labels.values())
for obsolete in (r'\Theta', r'H_x\leftarrow', r'G_x=\max', r'P_B=', r'\mathrm{Credit}_x'):
    assert obsolete not in all_labels, obsolete
assert r'\Delta F-\lambda\Delta b' in labels['sla-lazy-credit']

checks = []
load, recompute, slack = [2]*3, [3, 4, 5], 4
times = [sum(load[:k])+sum(recompute[k:]) for k in range(4)]
losses = [max(t-slack, 0) for t in times]
gains = [losses[0]-j for j in losses]
assert times == [12, 11, 9, 6] and losses == [8, 7, 5, 2] and gains == [0, 1, 3, 6]
for k in range(4):
    assert f'T = {times[k]} ms' in labels[f'sla-value-k{k}-numbers']
    assert f'J = {losses[k]} ms' in labels[f'sla-value-k{k}-numbers']
    assert f'U = {gains[k]} ms' in labels[f'sla-value-k{k}-label']
checks.append({'name': 'rendered_recovery_rows', 'times_ms': times, 'losses_ms': losses, 'gains_ms': gains})

MiB = 1024*1024
base = chain_model()
m = Model([replace(c, size=2*MiB) for c in base.chunks], base.agents.values(),
          base.workflows.values(), base.scenarios)
p = Problem(m, 6*MiB, current=7)
best, value, _ = exhaustive(p)
r = solve(p)
assert (r.mask, r.value, r.exact) == (best, value, True)
assert m.keys(best) == ('a1', 'a2', 'b1') and value == 7 and m.gain(7) == 6
rb = fractional_bound(m, m.all_mask, p.capacity)
assert rb.value == 9 and rb.rent*MiB == Q(1, 2)
assert m.action_credit(7, best, rb.rent) == 1
assert not m.legal(m.mask(('a2', 'a3', 'b1')))
checks.append({'name': 'tail_replacement_and_capacity_rent', 'capacity_MiB': 6,
               'before_gain_ms': 6, 'after_gain_ms': 7, 'action_credit_ms': 1,
               'fractional_upper_bound_ms': 9, 'rent_ms_per_MiB': '1/2'})

agents = [Agent(a, (a,), (Q(12), Q(8))) for a in ('a', 'b')]
m = Model([Chunk(a, None, 1) for a in ('a', 'b')], agents,
          [Workflow('w', tuple(Node(a, Q(0), agent=a) for a in ('a', 'b')))],
          [Scenario('f', frozenset(('a', 'b')))])
assert [m.gain(s) for s in range(4)] == [0, 0, 0, 4]
checks.append({'name': 'parallel_workflow_complementarity', 'gains_ms': [0, 0, 0, 4]})

def drift_model(slack):
    return Model([Chunk(a, None, 1) for a in ('a', 'b')],
                 [Agent('a', ('a',), (Q(12), Q(6))), Agent('b', ('b',), (Q(9), Q(2)))],
                 [Workflow('wa', (Node('a', Q(0), agent='a'), Node('tool', Q(slack)))),
                  Workflow('wb', (Node('b', Q(0), agent='b'),))],
                 [Scenario('f', frozenset(('a', 'b')))])
old, new = drift_model(8), drift_model(9)
cache = ValueCache(old)
assert cache.exact(1) == 4
cache.update(new)
assert cache.interval(1) == (2, 6)
assert new.gain(2) == 7 and new.gain(1) == 3
checks.append({'name': 'lazy_interval_example', 'cached_ms': 4, 'E_ms': 1,
               'interval_ms': [2, 6], 'better_feasible_ms': 7, 'unneeded_exact_value_ms': 3})

physical_ids = {'P1', 'P2', 'A3', 'A4', 'B3', 'C1', 'C2', 'C3', 'C4', 'A5'}
physical = [labels['sla-agents-physical-'+key] for key in physical_ids]
assert sum('COPYING' in text for text in physical) == 1
checks.append({'name': 'physical_sharing', 'committed_objects': 9, 'copying_objects': 1})

validation = json.loads((DESIGN/'VALIDATION.json').read_text())
for name, expected in validation['sha256'].items():
    assert hashlib.sha256((DESIGN/name).read_bytes()).hexdigest() == expected
work = validation['measurements']['cross_round_refresh']
assert work['full_rebuild_workflow_evaluations'] == 48
assert work['one_workflow_update']['workflow_evaluations'] == 2
assert work['one_workflow_update']['component_hits'] == 23
checks.append({'name': 'component_reuse_matches_reference_report', 'full_evaluations': 48,
               'local_update_evaluations': 2, 'unchanged_components_reused': 23})

report = {'status': 'PASS', 'scope': 'diagram numerical examples and source-model alignment; no production performance tests',
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'reference_validation_sha256': hashlib.sha256((DESIGN/'VALIDATION.json').read_bytes()).hexdigest(),
          'checks': checks}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
