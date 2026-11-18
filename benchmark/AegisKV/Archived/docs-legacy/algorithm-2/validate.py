"""Reproduce all model checks and illustrative solver-work measurements."""
from __future__ import annotations

import argparse
from dataclasses import replace
from fractions import Fraction as Q
import hashlib
import io
import json
from pathlib import Path
import platform
import random
from time import perf_counter
import unittest

from reference import (Agent, Chunk, ComponentCache, Model, Node, Problem,
                       ProfileBudgetExceeded, Scenario, ValueCache, Workflow,
                       exhaustive, solve, solve_components)
from test_reference import chain_model, random_model
from policy import Controller


def independent_model(n=24):
    chunks, agents, workflows = [], [], []
    # Unequal, exact synthetic values avoid an exponential set of equal optima.
    for j in reversed(range(n)):
        key, value = f'a{j}', Q(4**j)
        chunks += [Chunk(key+'p', None, 1), Chunk(key+'q', key+'p', 1)]
        agents.append(Agent(key, (key+'p', key+'q'), (3*value+1, 2*value+1, Q(1))))
        workflows.append(Workflow(key, (Node(key, Q(0), agent=key), Node('tool', Q(0)))))
    return Model(chunks, agents, workflows, [Scenario('f', frozenset(a.key for a in agents))])


def coupled_model(n=20):
    chunks = [Chunk('p', None, 1)] + [Chunk(f'x{i}', 'p', 1) for i in range(n)]
    agents = [Agent(f'a{i}', ('p', f'x{i}'), (Q(10), Q(9), Q(0))) for i in range(n)]
    return Model(chunks, agents,
                 [Workflow('w', tuple(Node(a.key, Q(0), agent=a.key) for a in agents))],
                 [Scenario('f', frozenset(a.key for a in agents))])


def serializable(x):
    if isinstance(x, Q):
        return str(x)
    if isinstance(x, dict):
        return {k: serializable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [serializable(v) for v in x]
    return x


def measurements():
    m = chain_model()
    p = Problem(m, 3, current=7)
    oracle, value, feasible = exhaustive(p)
    small = {'best_physical_chunks': m.keys(oracle), 'benefit_ms': value,
             'feasible_configurations': feasible,
             'old_full_a_benefit_ms': m.gain(7),
             'suffix_losses_ms': [m.gain(7)-m.gain(s) for s in (3, 1, 0)]}

    m = independent_model()
    p = Problem(m, 24)
    comparison = {}
    for lazy in (False, True):
        start = perf_counter()
        r = solve(p, lazy=lazy, max_pops=100000)
        comparison['lazy' if lazy else 'eager'] = {
            'exact': r.exact, 'value': r.value, 'gap': r.gap,
            'workflow_evaluations': r.workflow_evaluations, 'pops': r.pops,
            'elapsed_seconds': perf_counter()-start}
    assert comparison['lazy']['exact'] and comparison['eager']['exact']
    assert comparison['lazy']['value'] == comparison['eager']['value']

    profiles, values = ComponentCache(), ValueCache(m)
    start = perf_counter()
    first = solve_components(p, profiles, values)
    cold = {'component_builds': profiles.builds, 'component_hits': profiles.hits,
            'workflow_evaluations': values.workflow_evaluations,
            'profile_configurations': profiles.configurations,
            'dp_transitions': first[2], 'elapsed_seconds': perf_counter()-start}
    # One agent's next request changes its Slack; no update to other workflows.
    workflows = list(m.workflows.values())
    affected = workflows[0]
    duration = m.agents[affected.key].recovery[0] + 1
    workflows[0] = replace(affected, nodes=(affected.nodes[0], Node('tool', duration)))
    updated = Model(m.chunks, m.agents.values(), workflows, m.scenarios)
    values.update(updated)
    start = perf_counter()
    next_result = solve_components(Problem(updated, 24, current=first[0]), profiles, values)
    warm = {'component_builds': profiles.builds-cold['component_builds'],
            'component_hits': profiles.hits-cold['component_hits'],
            'workflow_evaluations': values.workflow_evaluations-cold['workflow_evaluations'],
            'profile_configurations': profiles.configurations-cold['profile_configurations'],
            'dp_transitions': next_result[2], 'elapsed_seconds': perf_counter()-start}
    fresh_profiles, fresh_values = ComponentCache(), ValueCache(updated)
    full = solve_components(Problem(updated, 24, current=first[0]), fresh_profiles, fresh_values)
    assert next_result[:2] == full[:2]
    refresh = {'cold': cold, 'one_workflow_update': warm,
               'full_rebuild_workflow_evaluations': fresh_values.workflow_evaluations,
               'full_rebuild_component_builds': fresh_profiles.builds,
               'same_allocation_as_full_rebuild': True}

    hard = coupled_model()
    hp = Problem(hard, 10, current=1)
    stopped = False
    try:
        solve_components(hp, max_configurations=128)
    except ProfileBudgetExceeded:
        stopped = True
    r = solve(hp, max_pops=100)
    assert stopped and hp.feasible(r.mask) and r.value <= 1 <= r.upper_bound
    stress = {'physical_chunks': len(hard.chunks), 'profile_budget_exceeded': stopped,
              'search_pops': r.pops, 'exact': r.exact, 'value': r.value,
              'upper_bound': r.upper_bound, 'gap': r.gap,
              'strict_runtime_action': 'DEFER' if not r.exact else 'KEEP',
              'known_optimum_by_parallel_branch_structure': 1}
    controller = Controller(hard, 10, committed=1, max_configurations=128, max_pops=100)
    bounded = controller.decide()
    empty = Controller(hard, 10, max_configurations=128, max_pops=100).decide()
    stress['bounded_mode_with_current_prefix'] = bounded.action
    stress['bounded_mode_from_empty'] = {
        'action': empty.action, 'value': empty.result.value,
        'exact': empty.result.exact, 'gap': empty.result.gap}
    rng = random.Random(90210)
    distribution = {'seed': 90210, 'models': 80, 'eager_workflow_evaluations': 0,
                    'lazy_workflow_evaluations': 0, 'lazy_fewer': 0, 'equal': 0,
                    'lazy_more': 0, 'all_allocations_equal': True}
    for _ in range(distribution['models']):
        rm = random_model(rng, 8)
        rp = Problem(rm, rng.randrange(rm.size(rm.all_mask)+1))
        re, rl = solve(rp, lazy=False), solve(rp, lazy=True)
        assert re.exact and rl.exact and (re.mask, re.value) == (rl.mask, rl.value)
        distribution['eager_workflow_evaluations'] += re.workflow_evaluations
        distribution['lazy_workflow_evaluations'] += rl.workflow_evaluations
        field = ('lazy_fewer' if rl.workflow_evaluations < re.workflow_evaluations else
                 'equal' if rl.workflow_evaluations == re.workflow_evaluations else 'lazy_more')
        distribution[field] += 1
    return {'prefix_counterexample': small, 'cold_search': comparison,
            'cross_round_refresh': refresh, 'coupled_budget_limit': stress,
            'cold_random_corpus': distribution}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, default=Path(__file__).with_name('VALIDATION.json'))
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(directory), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    print(output.getvalue(), end='')
    report = {'status': 'pass' if result.wasSuccessful() else 'fail',
              'scope': 'exact rational CPU reference; synthetic cost inputs; no physical performance claim',
              'python': platform.python_version(), 'tests_run': result.testsRun,
              'random_oracle_cases': 240, 'random_drift_models': 24,
              'round_updates_per_drift_model': 3, 'budget_certificate_models': 25,
              'failures': [str(x) for x in result.failures], 'errors': [str(x) for x in result.errors]}
    if result.wasSuccessful():
        report['measurements'] = measurements()
    report['sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(directory.glob('*.py'))}
    args.report.write_text(json.dumps(serializable(report), indent=2, ensure_ascii=False)+'\n')
    print(args.report)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    main()
