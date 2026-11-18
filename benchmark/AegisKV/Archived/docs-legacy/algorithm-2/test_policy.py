import unittest

from policy import Controller
from test_reference import chain_model, slack_model


class PolicyTests(unittest.TestCase):
    def finish(self, c, transaction):
        pool = c.pool
        for key, state in tuple(pool.allocations.items()):
            if state == 'RETIRING':
                pool.free_ack(key, pool.allocation_ids[key])
        t = pool.transactions[transaction]
        for key, shard in sorted(t.required_acks):
            pool.copy_ack(transaction, key, shard)

    def test_round_update_replaces_only_after_frees_and_acks(self):
        c = Controller(slack_model(0), 1, committed=1)
        self.assertEqual(c.decide().action, 'KEEP')
        c.update(model=slack_model(20))
        d = c.decide(shards=2)
        self.assertEqual(d.action, 'REPLACE')
        self.assertTrue(d.result.exact)
        self.finish(c, d.transaction)
        self.assertEqual(c.pool.committed, 2)
        self.assertEqual(c.decide().action, 'KEEP')

    def test_bounded_mode_never_calls_an_incumbent_optimal(self):
        from validate import coupled_model
        c = Controller(coupled_model(), 10, max_configurations=0, max_pops=100)
        d = c.decide()
        self.assertEqual(d.action, 'REPLACE')
        self.assertFalse(d.result.exact)
        self.assertGreater(d.result.gap, 0)
        self.assertGreater(d.result.value, 0)
        self.finish(c, d.transaction)
        self.assertEqual(c.decide().action, 'KEEP')
        strict = Controller(coupled_model(), 10, require_exact=True,
                            max_configurations=0, max_pops=100)
        self.assertEqual(strict.decide().action, 'DEFER')

    def test_quota_shrink_never_waits_for_value_improvement(self):
        c = Controller(chain_model(), 3, committed=7,
                       max_configurations=0, max_pops=0)
        c.update(quota=1)
        d = c.decide()
        self.assertEqual(d.action, 'RECLAIM')
        self.assertFalse(d.result.exact)
        self.finish(c, d.transaction)
        self.assertLessEqual(c.pool.physical_bytes, 1)

    def test_infeasible_pins_defer_physical_shrink(self):
        c = Controller(chain_model(), 3, committed=7)
        c.update(quota=1)
        self.assertEqual(c.decide(required=3).action, 'DEFER')
        self.assertEqual(c.pool.physical_bytes, 3)

    def test_value_updates_coalesce_without_copy_starvation(self):
        c = Controller(slack_model(0), 1)
        first = c.decide()
        c.update(model=slack_model(10))
        c.update(model=slack_model(20))
        self.assertEqual(c.pool.transactions[first.transaction].state, 'COPYING')
        self.assertEqual(c.decide().action, 'DEFER')
        self.finish(c, first.transaction)
        self.assertEqual(c.pool.committed, 1)
        second = c.decide()
        self.assertEqual(second.action, 'REPLACE')
        self.assertEqual(second.result.mask, 2)
        self.assertIsNone(c.queued_model)

    def test_source_invalidation_is_never_queued_behind_copy(self):
        c = Controller(slack_model(0), 1)
        first = c.decide()
        c.update(model=slack_model(20))
        c.update(hard=True)
        self.assertEqual(c.pool.transactions[first.transaction].state, 'ABORTED')
        self.assertIsNone(c.queued_model)
        self.assertFalse(c.pool.copy_ack(first.transaction, 'a', 0))


if __name__ == '__main__':
    unittest.main()
