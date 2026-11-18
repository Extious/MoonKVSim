"""Single-chunk boundaries and exact modeled rent accounting."""
import hashlib
import json
from pathlib import Path
import random
import unittest

from chunk_slacklandlord import decide_chunk
from simple_slacklandlord import LazyValue
from test_reference import chain_model, random_model, slack_model
from test_simple_slacklandlord import parallel_model


class ChunkPolicyTests(unittest.TestCase):
    def test_one_chunk_replaces_only_one_tail(self):
        m = chain_model()
        p = decide_chunk(m, 7, 3, 'b1')
        self.assertEqual((m.keys(p.mask), p.gain, p.rent, p.credit, p.victims),
                         (('a1', 'a2', 'b1'), 4, 3, 1, ('a3',)))

    def test_missing_prefix_never_creates_a_bundle(self):
        m = chain_model()
        self.assertEqual(decide_chunk(m, 0, 4, 'a3').status, 'WAIT_FOR_PREFIX')
        self.assertEqual(decide_chunk(m, 1, 4, 'a3').status, 'WAIT_FOR_PREFIX')
        p = decide_chunk(m, 3, 4, 'a3')
        self.assertEqual(m.keys(p.mask & ~3), ('a3',))

    def test_reuse_records_inputs_without_recopies_or_eager_value_refresh(self):
        m = parallel_model(shared=True, separate=True)
        values = LazyValue(m)
        p = decide_chunk(m, 1, 1, 'p', values=values)
        self.assertEqual((p.status, p.mask, values.evaluations), ('REUSE', 1, 0))
        old, new = slack_model(2), slack_model(10)
        values = LazyValue(old)
        self.assertEqual(values(1), 4)
        calls = values.evaluations
        values.update(new)
        self.assertEqual(values.evaluations, calls)
        self.assertEqual(values(1), 2)
        self.assertEqual(values.evaluations, calls+1)

    def test_sources_pins_and_reduced_capacity(self):
        m = chain_model()
        self.assertEqual(decide_chunk(m, 3, 4, 'a3', available=3).status, 'WAIT_FOR_SOURCE')
        self.assertEqual(decide_chunk(m, 7, 2, 'b1').status, 'WAIT_FOR_RECLAIM')
        self.assertEqual(decide_chunk(m, 7, 3, 'b1', pinned=7).status, 'BYPASS')

    def test_parallel_values_are_joint_and_can_block_single_chunk_admission(self):
        m = parallel_model()
        self.assertEqual([m.gain(s) for s in range(4)], [0, 0, 0, 4])
        self.assertEqual(decide_chunk(m, 1, 1, 'b').status, 'BYPASS')
        self.assertEqual(decide_chunk(m, 0, 2, 'a').status, 'BYPASS')
        shared = parallel_model(shared=True)
        self.assertEqual(decide_chunk(shared, 0, 1, 'p').credit, 4)

    def test_direct_slack_clipping_formula(self):
        for recovery in range(16):
            for saved in range(recovery+1):
                for slack in range(18):
                    direct = min(saved, max(recovery-slack, 0))
                    reference = max(recovery-slack, 0)-max(recovery-saved-slack, 0)
                    self.assertEqual(direct, reference)

    def test_random_physical_single_chunk_invariants(self):
        rng = random.Random(20260909)
        for _ in range(160):
            m = random_model(rng)
            current = rng.choice([s for s in range(m.all_mask+1) if m.legal(s)])
            capacity = rng.randrange(m.size(current), m.size(m.all_mask)+1)
            x = rng.choice(m.chunks).key
            p = decide_chunk(m, current, capacity, x)
            self.assertTrue(m.legal(p.mask))
            self.assertLessEqual(m.size(p.mask), capacity)
            if p.status in ('ADMIT', 'REPLACE'):
                self.assertEqual(m.keys(p.mask & ~current), (x,))
                self.assertEqual(p.credit, m.gain(p.mask)-m.gain(current))
                self.assertGreater(p.credit, 0)
                trial = current | m.mask((x,))
                self.assertEqual(p.rent, m.gain(trial)-m.gain(p.mask))
                for key in p.victims:
                    j = m.index[key]
                    self.assertFalse(any(parent == j and trial >> i & 1 for i, parent in enumerate(m.parents)))
                    trial ^= 1 << j
                self.assertEqual(trial, p.mask)
            else:
                self.assertEqual(p.mask, current)


if __name__ == '__main__':
    import sys
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ChunkPolicyTests))
    out = Path(__file__).resolve().parent
    report = {'status': 'PASS' if result.wasSuccessful() else 'FAIL',
              'scope': 'single physical chunk CPU metadata policy; no deployment or performance claim',
              'unit_tests': result.testsRun, 'random_small_instances': 160,
              'retained_limit': 'single-chunk admission can miss positive multi-chunk combinations',
              'sha256': {name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in
                         ('chunk_slacklandlord.py', 'test_chunk_slacklandlord.py', 'simple_slacklandlord.py', 'reference.py')}}
    (out/'CHUNK_VALIDATION.json').write_text(json.dumps(report, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
