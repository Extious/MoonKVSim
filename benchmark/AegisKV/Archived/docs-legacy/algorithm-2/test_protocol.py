import unittest
from protocol import Pool
from reference import Problem, solve
from test_reference import chain_model


class ProtocolTests(unittest.TestCase):
    def prepare(self):
        m = chain_model()
        p = Problem(m, 3, current=7)
        pool = Pool(m, 3, committed=7)
        return m, p, pool, solve(p)

    def test_waits_for_free_and_all_shards(self):
        m, p, pool, result = self.prepare()
        t = pool.begin(p, result, 0, shards=2)
        self.assertEqual(pool.committed, 3)
        self.assertEqual(pool.physical_bytes, 3)
        self.assertNotIn('b1', pool.allocations)
        self.assertTrue(pool.free_ack('a3', 0))
        self.assertEqual(pool.physical_bytes, 3)
        self.assertEqual(pool.allocations['b1'], 'COPYING')
        pool.copy_ack(t, 'b1', 0)
        pool.copy_ack(t, 'b1', 0)  # duplicate must not stand for another shard
        self.assertEqual(pool.committed, 3)
        pool.copy_ack(t, 'b1', 1)
        self.assertEqual(pool.committed, result.mask)
        self.assertEqual(pool.transactions[t].state, 'COMMITTED')
        self.assertFalse(pool.copy_ack(t, 'b1', 1))

    def test_abort_never_restores_deleted_victims(self):
        m, p, pool, result = self.prepare()
        t = pool.begin(p, result, 0)
        pool.free_ack('a3', 0)
        pool.copy_ack(t, 'b1', 0, success=False)
        self.assertEqual(pool.committed, 3)
        self.assertNotIn('a3', pool.allocations)
        self.assertEqual(pool.physical_bytes, 3)
        pool.free_ack('b1', t)
        self.assertEqual(pool.physical_bytes, 2)
        self.assertFalse(pool.copy_ack(t, 'b1', 0))

    def test_stale_plan_and_quota_shrink(self):
        m, p, pool, result = self.prepare()
        pool.external_change()
        with self.assertRaises(RuntimeError):
            pool.begin(p, result, 0)
        pool = Pool(m, 3, committed=7)
        t = pool.begin(p, result, 0)
        pool.external_change(quota=1)
        pool.free_ack('a3', 0)
        self.assertEqual(pool.transactions[t].state, 'ABORTED')
        self.assertNotIn('b1', pool.allocations)
        # Physical reclamation is asynchronous; no new allocation is allowed.
        shrink = Problem(m, 1, current=pool.committed, available=pool.committed)
        r = solve(shrink)
        pool.begin(shrink, r, pool.epoch, force=True)
        pool.free_ack('a2', 0)
        self.assertLessEqual(pool.physical_bytes, 1)

    def test_search_timeout_is_not_an_admission_certificate(self):
        m, p, pool, _ = self.prepare()
        r = solve(p, max_pops=0)
        with self.assertRaises(RuntimeError):
            pool.begin(p, r, 0)

    def test_stale_free_ack_cannot_free_reallocated_copy(self):
        m, p, pool, result = self.prepare()
        first = pool.begin(p, result, 0)
        pool.free_ack('a3', 0)
        pool.abort(first)
        pool.free_ack('b1', first)
        p2 = Problem(m, 3, current=pool.committed)
        second = pool.begin(p2, solve(p2), pool.epoch)
        pool.abort(second)
        self.assertFalse(pool.free_ack('b1', first))
        self.assertIn('b1', pool.allocations)
        self.assertTrue(pool.free_ack('b1', second))


if __name__ == '__main__':
    unittest.main()
