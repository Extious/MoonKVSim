"""Accounting and decision counterexamples for the Agent rental design."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import random
import unittest

from agent_lease_slacklandlord import CostOracle, Lease, SlackLandlord
from reference import Model
from test_reference import chain_model, random_model, slack_model
from test_simple_slacklandlord import parallel_model


def seeded(model, mask):
    """An explicit pre-existing cache fixture, including zero-credit blocks."""
    p = SlackLandlord(model)
    for i, chunk in enumerate(model.chunks):
        if mask >> i & 1:
            p.current |= 1 << i
            p._refresh(chunk.key, p.current)
    return p


class AgentLeaseTests(unittest.TestCase):
    def test_one_physical_rent_is_split_without_double_charging(self):
        lease = Lease({'a': Q(3), 'b': Q(5)}, {'a': 1, 'b': 1})
        lease.debit(Q(2))
        self.assertEqual(lease.credit, {'a': Q(9, 4), 'b': Q(15, 4)})
        self.assertEqual(lease.total, 6)

    def test_refresh_without_request_never_refunds_spent_credit(self):
        p = seeded(parallel_model(shared=True, separate=True), 1)
        p.leases['p'].debit(Q(2))
        p.L = Q(2)
        self.assertEqual(p.leases['p'].credit, {'a': 3, 'b': 3})
        p.refresh_frontier()
        self.assertEqual((p.leases['p'].total, p.key('p')), (6, 8))
        calls = p.values.evaluations
        for _ in range(10):
            p.refresh_frontier()
        self.assertEqual((p.leases['p'].total, p.key('p'), p.values.evaluations), (6, 8, calls))

    def test_active_keys_stay_constant_under_rent_and_charge_sums_to_physical_bytes(self):
        p = seeded(slack_model(2), 3)
        old_keys = {x: p.key(x) for x in p.tails()}
        self.assertEqual(p._rent_step(p.current), 'b')
        self.assertEqual((p.L, p.rent_charged), (2, 4))
        self.assertEqual({x: p.key(x) for x in p.tails()}, old_keys)
        self.assertEqual([p.leases[x].total for x in ('a', 'b')], [2, 0])

    def test_only_requesting_agent_renews_and_event_is_idempotent(self):
        p = seeded(parallel_model(shared=True, separate=True), 1)
        p.leases['p'].debit(Q(2))
        old = deepcopy(p.leases)
        calls = p.values.evaluations
        self.assertTrue(p.new_request('a', 2))
        self.assertEqual((p.leases, p.values.evaluations), (old, calls))
        p.refresh_frontier()
        self.assertEqual(p.leases['p'].credit, {'a': 4, 'b': 3})
        p.leases['p'].debit(Q(7, 4))
        after = deepcopy(p.leases)
        self.assertFalse(p.new_request('a', 2))
        p.refresh_frontier()
        self.assertEqual(p.leases, after)

    def test_same_workflow_shared_value_is_not_summed_twice(self):
        joint = seeded(parallel_model(shared=True), 1)
        separate = seeded(parallel_model(shared=True, separate=True), 1)
        self.assertEqual(joint.leases['p'].credit, {'a': 0, 'b': 4})
        self.assertEqual((joint.leases['p'].total, separate.leases['p'].total), (4, 8))
        joint.leases['p'].debit(Q(1))
        joint.new_request('a', 2)
        joint.refresh_frontier()
        self.assertEqual(joint.leases['p'].credit, {'a': 0, 'b': 3})

    def test_pending_rounds_coalesce_without_accumulating_grants(self):
        p = seeded(parallel_model(shared=True, separate=True), 1)
        p.leases['p'].debit(Q(2))
        p.new_request('a', 2)
        p.new_request('a', 3)
        self.assertEqual(p.leases['p'].credit, {'a': 3, 'b': 3})
        p.refresh_frontier()
        self.assertEqual(p.leases['p'].credit, {'a': 4, 'b': 3})
        self.assertEqual(p.leases['p'].seen_round['a'], 3)

    def test_internal_prefix_does_not_expire_with_the_highest_value_tail(self):
        p = seeded(chain_model(), 7)
        self.assertEqual([p.leases[x].total for x in ('a1', 'a2', 'a3')], [1, 2, 3])
        result = p.admit('b1', 3)
        self.assertEqual((result.victims, result.net), (('a3',), 1))
        self.assertEqual([p.leases[x].total for x in ('a1', 'a2')], [1, 2])
        self.assertEqual(p.L, 3)
        p.refresh_frontier()
        self.assertEqual((p.leases['a2'].total, p.key('a2')), (2, 5))

    def test_newly_exposed_tail_preserves_spent_balance_without_new_round(self):
        p = seeded(chain_model(), 1)
        p.leases['a1'].debit(Q(1, 2))
        self.assertEqual(p.admit('a2', 3).status, 'ADMIT')
        self.assertEqual(p.admit('a3', 3).status, 'ADMIT')
        p.reclaim(1)
        self.assertEqual(p.leases['a1'].total, Q(1, 2))
        p.refresh_frontier()
        self.assertEqual(p.leases['a1'].total, Q(1, 2))

    def test_all_tails_checked_when_an_old_nonminimum_key_drops(self):
        p = seeded(slack_model(2), 3)
        self.assertEqual((p.key('a'), p.key('b')), (4, 2))
        calls = p.values.evaluations
        p.new_request('a', 2, slack_model(15))
        self.assertEqual(p.values.evaluations, calls)
        result = p.reclaim(1)
        self.assertEqual(result.victims, ('a',))
        self.assertEqual(p.L, 0)

    def test_cost_change_caps_credit_but_does_not_authorize_topup(self):
        m = slack_model(2)
        p = seeded(m, 1)
        # Keep the workflow/Slack fixed; only the recovery-cost estimate changes.
        revised = Model(m.chunks, [replace(m.agents['a'], recovery=(Q(12),Q(10))), m.agents['b']],
                        m.workflows.values(), m.scenarios)
        p.update_inputs(revised)
        p.refresh_frontier()
        self.assertEqual(p.leases['a'].total, 2)
        p.update_inputs(m)
        p.refresh_frontier()
        self.assertEqual(p.leases['a'].total, 2)

    def test_lifecycle_survives_request_finish_and_end_removes_only_own_share(self):
        p = seeded(parallel_model(shared=True, separate=True), 1)
        p.leases['p'].debit(Q(2))
        p.request_finished('a')
        self.assertEqual(p.leases['p'].credit, {'a': 3, 'b': 3})
        p.end_agent('a')
        p.refresh_frontier()
        self.assertEqual((p.leases['p'].credit, p.current), ({'b': 3}, 1))
        with self.assertRaises(ValueError):
            p.new_request('a', 2)

    def test_detach_and_reattach_same_round_does_not_reissue_credit(self):
        m = parallel_model(shared=True, separate=True)
        p = seeded(m, 1)
        p.leases['p'].debit(Q(2))
        detached = Model(m.chunks, [replace(m.agents['a'], path=(), recovery=(Q(6),)), m.agents['b']],
                         m.workflows.values(), m.scenarios)
        p.update_inputs(detached)
        p.refresh_frontier()
        self.assertEqual(p.leases['p'].credit, {'b': 3})
        p.update_inputs(m)
        p.refresh_frontier()
        self.assertEqual(p.leases['p'].credit, {'a': 0, 'b': 3})
        p.new_request('a', 2)
        p.refresh_frontier()
        self.assertEqual(p.leases['p'].credit, {'a': 4, 'b': 3})

    def test_failed_trial_does_not_collect_rent_or_consume_pending_renewal(self):
        p = seeded(parallel_model(), 1)
        p.new_request('a', 2)
        old = deepcopy((p.leases, p.current, p.L, p.rent_charged))
        result = p.admit('b', 1)
        self.assertEqual(result.status, 'BYPASS')
        self.assertEqual((p.leases, p.current, p.L, p.rent_charged), old)

    def test_one_chunk_pins_and_quota_shrink(self):
        p = seeded(chain_model(), 7)
        self.assertEqual(p.admit('b1', 3, pinned=7).status, 'BYPASS')
        self.assertEqual(p.reclaim(1, pinned=3).status, 'WAIT_FOR_UNPIN')
        self.assertEqual(p.reclaim(1).victims, ('a3', 'a2'))
        self.assertEqual(p.current, 1)
        self.assertEqual(p.admit('a3', 3).status, 'WAIT_FOR_PREFIX')
        self.assertEqual(p.admit('a2', 3, available=1).status, 'WAIT_FOR_SOURCE')

    def test_strict_single_chunk_combination_limit_is_retained(self):
        p = SlackLandlord(parallel_model())
        self.assertEqual((p.admit('a', 2).status, p.admit('b', 2).status), ('BYPASS', 'BYPASS'))
        self.assertEqual(p.model.gain(3), 4)

    def test_random_accounting_against_independent_physical_DAG_model(self):
        rng = random.Random(20260910)
        for _ in range(200):
            m = random_model(rng)
            legal = [mask for mask in range(m.all_mask+1) if m.legal(mask)]
            current = rng.choice(legal)
            p = seeded(m, current)
            # Independent Model.gain checks the ordered accounting total.
            for tail in p.tails():
                without = current ^ (1 << m.index[tail])
                shares = p.values.shares(without, current, tail)
                self.assertEqual(sum(shares.values()), m.gain(current)-m.gain(without))
            capacity = rng.randrange(m.size(current), m.size(m.all_mask)+1)
            candidate = rng.choice(m.chunks).key
            result = p.admit(candidate, capacity)
            self.assertTrue(m.legal(p.current))
            self.assertLessEqual(m.size(p.current), capacity)
            if result.status in ('ADMIT', 'REPLACE'):
                self.assertEqual(m.keys(p.current & ~current), (candidate,))
                self.assertEqual(result.net, m.gain(p.current)-m.gain(current))
                self.assertGreater(result.net, 0)
            else:
                self.assertEqual(p.current, current)
            for tail in p.tails():
                p._refresh(tail, p.current)
                without = p.current ^ (1 << m.index[tail])
                self.assertLessEqual(p.leases[tail].total, m.gain(p.current)-m.gain(without))
            new_capacity = rng.randrange(m.size(p.current)+1)
            result = p.reclaim(new_capacity)
            self.assertTrue(m.legal(p.current))
            self.assertLessEqual(m.size(p.current), new_capacity)
            self.assertTrue(all(lease.total >= 0 for lease in p.leases.values()))


if __name__ == '__main__':
    import sys
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AgentLeaseTests))
    out = Path(__file__).resolve().parent
    report = {'status': 'PASS' if result.wasSuccessful() else 'FAIL',
              'scope': 'CPU exact-rational metadata accounting; not deployed, calibrated or performance evidence',
              'unit_tests': result.testsRun, 'random_small_instances': 200,
              'retained_limits': ['strict single-chunk admission misses some positive combinations',
                                  'fixed ordered WCT attribution is not a unique or symmetric allocation',
                                  'no classic Landlord competitive ratio is claimed'],
              'sha256': {name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in
                         ('agent_lease_slacklandlord.py', 'test_agent_lease_slacklandlord.py', 'reference.py',
                          'test_reference.py', 'test_simple_slacklandlord.py')}}
    (out/'AGENT_LEASE_VALIDATION.json').write_text(json.dumps(report, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
