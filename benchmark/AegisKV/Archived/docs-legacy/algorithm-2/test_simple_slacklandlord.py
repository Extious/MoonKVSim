"""Behavior checks for the minimal policy, including its deliberate limitation."""
from dataclasses import replace
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import random
import unittest

from reference import Agent, Chunk, Model, Node, Problem, Scenario, Workflow, exhaustive
from simple_slacklandlord import LazyValue, decide
from test_reference import chain_model, random_model, slack_model


def parallel_model(shared=False, separate=False):
    chunks = [Chunk('p', None, 1)] if shared else [Chunk(a, None, 1) for a in ('a', 'b')]
    agents = [Agent(a, ('p' if shared else a,), (Q(6), Q(2))) for a in ('a', 'b')]
    nodes = tuple(Node(a, Q(0), agent=a) for a in ('a', 'b'))
    workflows = [Workflow(a, (n,)) for a, n in zip(('a', 'b'), nodes)] if separate else [Workflow('w', nodes)]
    return Model(chunks, agents, workflows, [Scenario('f', frozenset(('a', 'b')))])


class SimplePolicyTests(unittest.TestCase):
    def test_tail_replacement_keeps_useful_prefix(self):
        m = chain_model()
        p = decide(m, 7, 3)
        self.assertEqual(m.keys(p.mask), ('a1', 'a2', 'b1'))
        self.assertEqual((p.gain, p.rent, p.credit, p.victims), (4, 3, 1, ('a3',)))

    def test_retry_after_generation_and_zero_gain_prefix(self):
        base = chain_model()
        a = replace(base.agents['a'], recovery=tuple(map(Q, (12, 12, 12, 9))))
        m = Model(base.chunks[:3], [a], [base.workflows['wa']], [Scenario('f', frozenset(('a',)))])
        self.assertEqual(decide(m, 0, 3, available=3).status, 'KEEP')
        p = decide(m, 0, 3, available=7)
        self.assertEqual((p.mask, p.gain, p.rent, p.credit), (7, 3, 0, 3))
        self.assertEqual(decide(m, 0, 3, available=5).status, 'KEEP')  # missing middle source

    def test_shared_capacity_and_joint_workflow_value(self):
        for separate, value in [(False, 4), (True, 8)]:
            m = parallel_model(shared=True, separate=separate)
            p = decide(m, 0, 1)
            self.assertEqual((m.size(p.mask), p.credit), (1, value))

    def test_new_round_invalidates_only_changed_workflow_on_use(self):
        old, new = slack_model(2), slack_model(10)
        values = LazyValue(old)
        self.assertEqual(values(1), 4)
        initial = values.evaluations
        values.update(new)
        self.assertEqual(values.evaluations, initial)
        self.assertEqual(values(1), 2)
        self.assertEqual(values.evaluations, initial + 1)
        self.assertEqual(values(1), 2)
        self.assertEqual(values.evaluations, initial + 1)

    def test_capacity_shrink_reprices_new_tail(self):
        m = chain_model()
        p = decide(m, 7, 1)
        self.assertEqual((p.status, p.mask, p.rent, p.victims), ('RECLAIM', 1, 5, ('a3', 'a2')))
        self.assertEqual(decide(m, 7, 0).rent, 6)

    def test_pins_prevent_impossible_reclaim(self):
        m = chain_model()
        self.assertEqual(decide(m, 7, 1, pinned=3).status, 'WAIT_FOR_UNPIN')
        self.assertEqual(decide(m, 7, 2, pinned=3).mask, 3)
        with self.assertRaises(ValueError):
            decide(m, 7, 3, pinned=2)

    def test_rent_is_conditional_on_added_prefix(self):
        m = parallel_model()
        # Existing A alone has zero value; deleting it AFTER adding B loses 4.
        # Charging its stand-alone value (zero) would falsely report Credit=4.
        self.assertEqual([m.gain(s) for s in range(4)], [0, 0, 0, 4])
        self.assertEqual(decide(m, 1, 1).status, 'KEEP')

    def test_parallel_joint_admission_is_documented_limitation(self):
        m = parallel_model()
        p = decide(m, 0, 2)
        best, value, _ = exhaustive(Problem(m, 2))
        self.assertEqual((p.mask, m.gain(p.mask), best, value), (0, 0, 3, 4))

    def test_random_physical_capacity_prefixes_and_accounting(self):
        rng = random.Random(20260908)
        for _ in range(160):
            m = random_model(rng)
            legal = [s for s in range(m.all_mask + 1) if m.legal(s)]
            current = rng.choice(legal)
            capacity = rng.randrange(m.size(m.all_mask) + 1)
            p = decide(m, current, capacity)
            with self.subTest(current=current, capacity=capacity):
                self.assertTrue(m.legal(p.mask))
                self.assertLessEqual(m.size(p.mask), capacity)
                self.assertEqual(p.credit, m.gain(p.mask) - m.gain(current))
                draft = current | p.mask
                self.assertEqual(p.rent, m.gain(draft) - m.gain(p.mask))
                for key in p.victims:
                    i = m.index[key]
                    self.assertFalse(any(m.parents[j] == i and draft >> j & 1 for j in range(len(m.chunks))))
                    draft ^= 1 << i
                self.assertEqual(draft, p.mask)
                if p.status != 'RECLAIM':
                    self.assertGreaterEqual(p.credit, 0)
                    if p.mask != current:
                        self.assertGreater(p.credit, 0)


if __name__ == '__main__':
    import sys
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SimplePolicyTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    out = Path(__file__).resolve().parent
    report = {
        'status': 'PASS' if result.wasSuccessful() else 'FAIL',
        'scope': 'CPU metadata policy and modeled WCT accounting; no runtime or latency claim',
        'unit_tests': result.testsRun, 'random_small_instances': 160,
        'retained_negative_case': {'parallel_joint_admission': {'local_gain_ms': 0, 'global_gain_ms': 4}},
        'sha256': {name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in
                   ('simple_slacklandlord.py', 'test_simple_slacklandlord.py', 'reference.py', 'test_reference.py')},
    }
    (out/'SIMPLE_VALIDATION.json').write_text(json.dumps(report, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
