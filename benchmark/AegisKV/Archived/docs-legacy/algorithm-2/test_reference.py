"""Behavior/counterexample tests. Independent oracle enumerates physical sets."""
from dataclasses import replace
from fractions import Fraction as Q
import random
import unittest

from reference import (Agent, Chunk, ComponentCache, Model, Node, Problem, Scenario, ValueCache,
                       Workflow, exhaustive, fractional_bound, solve, solve_components,
                       ProfileBudgetExceeded, components)


def chain_model():
    return Model(
        [Chunk('a1', None, 1), Chunk('a2', 'a1', 1), Chunk('a3', 'a2', 1), Chunk('b1', None, 1)],
        [Agent('a', ('a1', 'a2', 'a3'), tuple(map(Q, (12, 11, 9, 6)))),
         Agent('b', ('b1',), (Q(6), Q(2)))],
        [Workflow('wa', (Node('a', Q(0), agent='a'), Node('tool', Q(4)))),
         Workflow('wb', (Node('b', Q(0), agent='b'),))],
        [Scenario('source_failure', frozenset(('a', 'b')))])


def slack_model(slack):
    return Model([Chunk('a', None, 1), Chunk('b', None, 1)],
                 [Agent('a', ('a',), (Q(12), Q(8))), Agent('b', ('b',), (Q(3), Q(1)))],
                 [Workflow('wa', (Node('a', Q(0), agent='a'), Node('tool', Q(slack)))),
                  Workflow('wb', (Node('b', Q(0), agent='b'),))],
                 [Scenario('f', frozenset(('a', 'b')))])


def random_model(rng, n=None):
    n = n or rng.randint(1, 8)
    chunks = [Chunk(f'x{i}', None if i == 0 or rng.random() < .45 else f'x{rng.randrange(i)}',
                    rng.randint(1, 4)) for i in range(n)]
    indices = {x.key: x for x in chunks}
    agents = []
    for j in range(rng.randint(1, min(n+2, 7))):
        tail, path = rng.choice(chunks).key, []
        while tail is not None:
            path.append(tail)
            tail = indices[tail].parent
        path.reverse()
        costs = [Q(rng.randint(2, 35))]
        for _ in path:
            costs.append(max(Q(0), costs[-1] - rng.randint(0, 10)))
        agents.append(Agent(f'a{j}', tuple(path), tuple(costs)))
    groups = [[] for _ in range(rng.randint(1, min(3, len(agents))))]
    for a in agents:
        groups[rng.randrange(len(groups))].append(a)
    workflows = []
    for j, group in enumerate(groups):
        nodes = [Node('tool', Q(rng.randint(0, 20)))]
        for a in group:
            parents = tuple(v.key for v in nodes if rng.random() < .3)
            nodes.append(Node(a.key, Q(rng.randint(0, 5)), parents, a.key))
        workflows.append(Workflow(f'w{j}', tuple(nodes)))
    scenarios = [Scenario('f0', frozenset(a.key for a in agents if rng.random() < .7), Q(1, 3)),
                 Scenario('f1', frozenset(a.key for a in agents if rng.random() < .7), Q(2, 3))]
    return Model(chunks, agents, workflows, scenarios)


class ReferenceTests(unittest.TestCase):
    def assert_all_solvers(self, problem):
        expected, value, _ = exhaustive(problem)
        for lazy in (False, True):
            result = solve(problem, lazy=lazy)
            self.assertTrue(result.exact)
            self.assertEqual((result.mask, result.value), (expected, value))
            self.assertEqual(result.gap, 0)
        self.assertEqual(solve_components(problem)[:2], (expected, value))
        return expected, value

    def test_short_prefix_can_be_optimal(self):
        m = chain_model()
        result = self.assert_all_solvers(Problem(m, 3, current=m.mask(('a1', 'a2', 'a3'))))
        self.assertEqual(result, (m.mask(('a1', 'a2', 'b1')), Q(7)))

    def test_true_suffix_losses(self):
        m = chain_model()
        full = m.mask(('a1', 'a2', 'a3'))
        self.assertEqual([m.gain(full)-m.gain(m.mask(('a1', 'a2')[:k])) for k in (2, 1, 0)],
                         [3, 5, 6])
        self.assertFalse(m.legal(m.mask(('a1', 'a3'))))

    def test_zero_gain_prefix_bundle(self):
        m = chain_model()
        m = Model(m.chunks[:3], [replace(m.agents['a'], recovery=tuple(map(Q, (12, 12, 12, 9))))],
                  [m.workflows['wa']], [Scenario('f', frozenset(('a',)))])
        self.assertEqual(self.assert_all_solvers(Problem(m, 3)), (7, Q(3)))
        self.assertEqual(self.assert_all_solvers(Problem(m, 2))[1], 0)

    def test_slack_is_a_threshold(self):
        self.assertEqual([slack_model(s).gain(1) for s in (2, 10, 15)], [4, 2, 0])

    def test_sharing_counts_one_physical_copy(self):
        chunks = [Chunk('p', None, 3)]
        agents = [Agent(a, ('p',), (Q(6), Q(2))) for a in ('a', 'b')]
        separate = [Workflow(a, (Node(a, Q(0), agent=a),)) for a in ('a', 'b')]
        scenarios = [Scenario('both', frozenset(('a', 'b')))]
        m = Model(chunks, agents, separate, scenarios)
        self.assertEqual((m.size(1), m.gain(1)), (3, 8))
        self.assertEqual(self.assert_all_solvers(Problem(m, 3)), (1, 8))
        joint = Model(chunks, agents, [Workflow('w', tuple(Node(a, Q(0), agent=a)
                                                           for a in ('a', 'b')))], scenarios)
        self.assertEqual(joint.gain(1), 4)
        weighted = Model(chunks, agents, separate,
                         [Scenario('fa', frozenset(('a',)), Q(1, 2)),
                          Scenario('fb', frozenset(('b',)), Q(1, 2))])
        self.assertEqual(weighted.gain(1), 4)

    def test_parallel_recovery_is_not_submodular(self):
        m = Model([Chunk('a', None, 1), Chunk('b', None, 1)],
                  [Agent(a, (a,), (Q(12), Q(8))) for a in ('a', 'b')],
                  [Workflow('w', tuple(Node(a, Q(0), agent=a) for a in ('a', 'b')))],
                  [Scenario('both', frozenset(('a', 'b')))])
        self.assertEqual([m.gain(s) for s in (0, 1, 2, 3)], [0, 0, 0, 4])
        self.assertEqual(self.assert_all_solvers(Problem(m, 2)), (3, 4))

    def test_scenario_specific_recovery_and_drift(self):
        old = slack_model(0)
        scenarios = [Scenario('f', frozenset(('a', 'b')), Q(1),
                              (('a', (Q(12), Q(11))),))]
        new = Model(old.chunks, old.agents.values(), old.workflows.values(), scenarios)
        self.assertEqual(new.gain(1), 1)
        cache = ValueCache(old)
        cache.exact(1)
        cache.update(new)
        lo, hi = cache.interval(1)
        self.assertLessEqual(lo, 1)
        self.assertGreaterEqual(hi, 1)
        self.assertEqual(solve(Problem(new, 1), cache).mask, 2)
        self.assert_all_solvers(Problem(new, 1))

    def test_raw_rent_is_not_an_integer_solution(self):
        m = chain_model()
        p = Problem(m, 2, available=7)
        rb = fractional_bound(m, 7, 2)
        self.assertEqual(rb.value, 5)
        result = solve(p)
        self.assertEqual(result.value, 3)
        self.assertGreater(rb.value, result.value)

    def test_cross_round_decrease_does_not_hide_candidate(self):
        old = slack_model(0)
        cache = ValueCache(old)
        for s in range(4):
            cache.exact(s)
        unchanged_calls = cache.calls_by_workflow['wb']
        new = slack_model(20)
        cache.update(new)
        for s in range(4):
            lo, hi = cache.interval(s)
            self.assertLessEqual(lo, new.gain(s))
            self.assertGreaterEqual(hi, new.gain(s))
        result = solve(Problem(new, 1, current=1), cache)
        self.assertEqual(result.mask, 2)
        self.assertEqual(cache.calls_by_workflow['wb'], unchanged_calls)

    def test_other_workflow_scenario_change_preserves_cache(self):
        old = slack_model(0)
        cache = ValueCache(old)
        cache.exact(3)
        calls = cache.calls_by_workflow['wb']
        new = Model(old.chunks, old.agents.values(), old.workflows.values(),
                    [Scenario('f', frozenset(('b',)))])
        cache.update(new)
        self.assertEqual(cache.exact(3), 2)
        self.assertEqual(cache.calls_by_workflow['wb'], calls)

    def test_source_availability_and_pins(self):
        m = chain_model()
        self.assert_all_solvers(Problem(m, 3, current=7, required=3))
        self.assert_all_solvers(Problem(m, 1, current=7, available=7))
        with self.assertRaises(ValueError):
            Problem(m, 1, required=3)
        with self.assertRaises(ValueError):
            Problem(m, 3, available=6)
        with self.assertRaises(ValueError):
            Problem(m, 3, required=2)

    def test_cache_topology_generation_and_eviction(self):
        old = slack_model(0)
        cache = ValueCache(old, max_entries=1)
        for s in range(4):
            cache.exact(s)
        self.assertLessEqual(len(cache.entries), 1)
        new = Model(old.chunks, old.agents.values(),
                    [Workflow('wa', (Node('tool', Q(10)), Node('a', Q(0), ('tool',), 'a'))),
                     old.workflows['wb']], old.scenarios)
        cache.update(new)
        result = solve(Problem(new, 1), cache)
        self.assertEqual((result.mask, result.value), exhaustive(Problem(new, 1))[:2])

    def test_components_refresh_only_affected_workflow(self):
        m = slack_model(0)
        profiles, values = ComponentCache(), ValueCache(m)
        self.assertEqual(len(components(m)), 2)
        solve_components(Problem(m, 1), profiles, values)
        self.assertEqual(profiles.builds, 2)
        m2 = slack_model(20)
        values.update(m2)
        result = solve_components(Problem(m2, 1), profiles, values)
        self.assertEqual(result[:2], (2, 2))
        self.assertEqual(profiles.builds, 3)
        self.assertEqual(profiles.hits, 1)
        with self.assertRaises(ProfileBudgetExceeded):
            solve_components(Problem(m2, 1), max_configurations=0)
        with self.assertRaises(ProfileBudgetExceeded):
            solve_components(Problem(m2, 1), max_transitions=0)

    def test_ties_prefer_current_without_access_frequency(self):
        m = Model([Chunk('a', None, 1), Chunk('b', None, 1)],
                  [Agent(a, (a,), (Q(3), Q(1))) for a in ('a', 'b')],
                  [Workflow(a, (Node(a, Q(0), agent=a),)) for a in ('a', 'b')],
                  [Scenario('f', frozenset(('a', 'b')))])
        self.assertEqual(self.assert_all_solvers(Problem(m, 1, current=2))[0], 2)

    def test_budget_reports_valid_gap(self):
        rng = random.Random(781)
        for _ in range(25):
            m = random_model(rng, 7)
            p = Problem(m, rng.randrange(m.size(m.all_mask)+1))
            _, optimum, _ = exhaustive(p)
            for budget in (0, 1, 3, 9):
                r = solve(p, max_pops=budget)
                self.assertTrue(p.feasible(r.mask))
                self.assertLessEqual(r.value, optimum)
                self.assertGreaterEqual(r.upper_bound, optimum)

    def test_random_oracle_eager_lazy_equivalence(self):
        rng = random.Random(20260908)
        for _ in range(240):
            m = random_model(rng)
            legal = [s for s in range(m.all_mask+1) if m.legal(s)]
            available = rng.choice(legal)
            current = rng.choice([s for s in legal if not s & ~available])
            capacity = rng.randrange(m.size(available)+1)
            pins = rng.choice([s for s in legal if not s & ~current and m.size(s) <= capacity])
            self.assert_all_solvers(Problem(m, capacity, current, pins, available))

    def test_random_drift_intervals_multiple_unrefreshed_rounds(self):
        rng = random.Random(567)
        for _ in range(24):
            m = random_model(rng, 6)
            cache = ValueCache(m)
            legal = [s for s in range(m.all_mask+1) if m.legal(s)]
            for s in legal:
                cache.exact(s)
            for _round in range(3):
                workflows = [replace(w, nodes=tuple(replace(n, duration=Q(rng.randrange(12)))
                                                    for n in w.nodes)) for w in m.workflows.values()]
                agents = []
                for a in m.agents.values():
                    shift = Q(rng.randrange(-3, 4))
                    agents.append(replace(a, recovery=tuple(max(Q(0), t+shift) for t in a.recovery)))
                m = Model(m.chunks, agents, workflows, m.scenarios)
                cache.update(m)
                for s in legal:
                    lo, hi = cache.interval(s)
                    self.assertLessEqual(lo, m.gain(s))
                    self.assertGreaterEqual(hi, m.gain(s))
            result = solve(Problem(m, m.size(m.all_mask)//2), cache)
            self.assertEqual((result.mask, result.value), exhaustive(Problem(m, m.size(m.all_mask)//2))[:2])


if __name__ == '__main__':
    unittest.main()
