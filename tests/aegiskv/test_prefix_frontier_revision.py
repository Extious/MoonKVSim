"""Adversarial and bounded exhaustive checks for the new policy, not v1 replay."""

from dataclasses import replace
from itertools import product

import pytest

from moonkvsim.aegiskv.prefix_frontier import Consumer, KVObject, PrefixPool


def consumer(pool, name, costs, *, path=None, namespace="tenant:model:abi", **kwargs):
    if path is None:
        path = []
        for index in range(len(costs) - 1):
            obj = KVObject.sealed(namespace, path[-1] if path else None,
                                  (ord(name[0]), index), 1)
            pool.register_object(obj)
            path.append(obj.key)
    c = Consumer(name, namespace, tuple(path), tuple(costs), **kwargs)
    pool.update_consumer(c)
    return c


def plan(pool, c, now=0, available=None, **kwargs):
    return pool.plan(c.request, now_ns=now,
                     source_available=set(c.path) if available is None else available,
                     copy_budget_bytes=100, copy_ns_per_byte=1, **kwargs)


def ack(pool, tx, now=1):
    for key in pool.transactions[tx].plan.add:
        for shard in range(pool.objects[key].shards):
            pool.acknowledge_shard(tx, key, shard)
    return pool.finish(tx, now)


def drain(pool):
    for key, rid in pool.reclaim_tasks():
        assert pool.acknowledge_free(key, rid)
    pool.check()


def fill(pool, c):
    while pool.frontier(c.request) < len(c.path):
        candidate = plan(pool, c)
        assert candidate is not None
        assert ack(pool, pool.begin(candidate, 0)) == "COMMITTED"
        drain(pool)


def test_group_crosses_zero_gain_first_chunk_without_future_kv():
    pool = PrefixPool(6, 2)
    c = consumer(pool, "a", [100, 100, 20])
    assert plan(pool, c, available={c.path[0]}) is None
    candidate = plan(pool, c)
    assert candidate.bytes_to_copy == 2
    tx = pool.begin(candidate, 0)
    pool.acknowledge_shard(tx, c.path[0], 0)
    assert pool.frontier(c.request) == 0
    assert ack(pool, tx) == "COMMITTED"
    assert pool.frontier(c.request) == 2


def test_tail_is_not_intrinsically_highest_historical_credit():
    # Same size, later rent larger, but marginal value much lower.
    early_key = 0 + 10 / 1
    late_key = 1 + 1 / 1
    assert late_key < early_key
    pool = PrefixPool(6, 2)
    c = consumer(pool, "a", [100, 90, 89, 88, 87])
    fill(pool, c)
    before = pool.harm(pool.committed, 0)
    assert pool.harm(pool.committed - {c.path[-1]}, 0) - before == 1
    assert pool.harm(pool.committed - set(c.path), 0) - before == 13


def test_paused_stream_resumes_after_competitor_completion_and_repairs_gap():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 99, 98, 97, 96])
    fill(pool, a)
    b = consumer(pool, "b", [100, 50, 0])
    fill(pool, b)
    assert pool.frontier(a.request) == 2
    assert plan(pool, a) is None  # Current low-value continuation loses the competition.
    pool.update_consumer(replace(b, active=False))
    assert plan(pool, a, available={a.path[-1]}) is None  # Never skip ordinal 2.
    candidate = plan(pool, a)
    assert candidate is not None
    assert ack(pool, pool.begin(candidate, 0)) == "COMMITTED"
    assert pool.frontier(a.request) == 4


def test_copy_before_delete_failure_keeps_old_recovery_prefix():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 99, 98, 97, 96])
    fill(pool, a)
    b = consumer(pool, "b", [100, 50, 0])
    old = set(pool.committed)
    candidate = plan(pool, b)
    assert candidate.victims
    tx = pool.begin(candidate, 0)
    assert pool.committed == old and pool.physical_bytes == 6
    assert pool.finish(tx, 1, success=False) == "ABORTED"
    assert pool.committed == old and pool.physical_bytes == 6
    pool.acknowledge_shard(tx, b.path[0], 0)
    assert pool.finish(tx, 2) == "ABORTED"
    assert plan(pool, b) is None  # Unacknowledged physical debt cannot be reused.
    drain(pool)
    assert pool.physical_bytes == 4


def test_partial_shards_never_commit_or_release_physically_without_ack():
    pool = PrefixPool(4, 2)
    obj = KVObject.sealed("tenant:model:abi", None, (42,), 1, shards=2)
    pool.register_object(obj)
    c = consumer(pool, "a", [10, 0], path=(obj.key,))
    tx = pool.begin(plan(pool, c), 0)
    pool.acknowledge_shard(tx, obj.key, 0)
    pool.acknowledge_shard(tx, obj.key, 0)
    assert pool.finish(tx, 1) == "ABORTED"
    assert pool.frontier(c.request) == 0 and pool.physical_bytes == 1
    tasks = pool.reclaim_tasks()
    assert tasks == pool.reclaim_tasks()  # Lost delete response is retryable.
    drain(pool)
    tx2 = pool.begin(plan(pool, c), 0)
    assert not pool.acknowledge_free(*tasks[0])
    assert pool.physical_bytes == 1 and tx2 != tx


def test_all_shared_consumers_count_but_physical_bytes_count_once():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 50, 0])
    fill(pool, a)
    before = pool.physical_bytes
    b = consumer(pool, "b", [100, 50, 0], path=a.path)
    assert pool.frontier(b.request) == 2 and plan(pool, b) is None
    assert pool.physical_bytes == before == 2
    assert pool.harm(set(), 0) - pool.harm(pool.committed, 0) == 200
    pool.remove_consumer(a.request)
    pool.collect_expired(0)
    assert pool.frontier(b.request) == 2 and pool.physical_bytes == 2
    pool.remove_consumer(b.request)
    pool.collect_expired(0)
    assert not pool.committed and pool.physical_bytes == 2
    drain(pool)
    assert pool.physical_bytes == 0


def test_divergent_rounds_form_shared_tree_and_cut_affects_both():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 70, 20])
    fill(pool, a)
    branch = KVObject.sealed(a.namespace, a.path[0], (999,), 1)
    pool.register_object(branch)
    b = consumer(pool, "b", [90, 60, 0], path=(a.path[0], branch.key))
    fill(pool, b)
    assert pool.physical_bytes == 3
    cut = pool._closure(a.path[0], pool.committed)
    assert len(cut) == 3
    assert pool.harm(pool.committed - cut, 0) - pool.harm(pool.committed, 0) == 170


def test_inactive_retention_has_zero_utility_and_bounded_lifetime():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 0])
    fill(pool, a)
    pool.update_consumer(replace(a, active=False, expires_ns=10))
    pool.collect_expired(9)
    assert pool.committed and pool.harm(set(), 9) == 0
    pool.collect_expired(10)
    assert not pool.committed and pool.physical_bytes == 1
    drain(pool)


@pytest.mark.parametrize("change", ["slack", "route", "completion", "pin"])
def test_snapshot_change_aborts_pending_without_displacing_old_state(change):
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 99, 98, 97, 96])
    fill(pool, a)
    b = consumer(pool, "b", [100, 50, 0])
    tx = pool.begin(plan(pool, b), 0)
    if change == "slack":
        pool.update_consumer(replace(b, slack_ms=100))
    elif change == "route":
        pool.update_consumer(replace(b, route_epoch=1))
    elif change == "completion":
        pool.remove_consumer(b.request)
    else:
        pool.acquire_read("read", set(a.path), 10, 0, primary_reserved=True)
    assert ack(pool, tx) == "ABORTED"
    assert pool.frontier(a.request) == 4


def test_expired_read_requires_cancel_ack_before_pressure_can_release_it():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 0])
    fill(pool, a)
    with pytest.raises(ValueError, match="primary"):
        pool.acquire_read("r", set(a.path), 10, 0, primary_reserved=False)
    pool.acquire_read("r", set(a.path), 10, 0, primary_reserved=True)
    assert pool.set_quota(0, 11) == 1
    assert pool.expired_reads(11) == ("r",)
    assert not pool.reclaim_tasks() and pool.physical_bytes == 1
    pool.acknowledge_read_done("r")
    pool.set_quota(0, 12)
    assert pool.reclaim_tasks() and pool.physical_bytes == 1
    drain(pool)
    assert pool.physical_bytes == 0


def test_hard_shrink_cancels_staging_and_keeps_debt_until_free_ack():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 0])
    tx = pool.begin(plan(pool, a), 0)
    assert pool.set_quota(0, 1) == 1
    assert ack(pool, tx) == "ABORTED"
    assert pool.physical_bytes == 1
    drain(pool)


def test_deadline_or_missing_source_prevents_useless_copy():
    pool = PrefixPool(6, 2, min_residence_ns=5)
    a = consumer(pool, "a", [100, 100, 0], expires_ns=8)
    assert plan(pool, a, now=1) is None  # Completion at 3, need strictly before 3.
    assert plan(pool, a, available={a.path[1]}) is None


def test_namespace_route_and_bad_numeric_values_are_rejected():
    pool = PrefixPool(6, 2)
    a = consumer(pool, "a", [100, 0])
    with pytest.raises(ValueError, match="compatible"):
        consumer(pool, "b", [100, 0], path=a.path, namespace="different-tenant")
    with pytest.raises(ValueError, match="finite"):
        replace(a, slack_ms=float("nan"))
    with pytest.raises(ValueError, match="fallback"):
        replace(a, recovery_ms=(10, 20))


@pytest.mark.parametrize("values", list(product((1, 3, 9), repeat=4)))
def test_bounded_eager_oracle_for_every_successful_exchange(values):
    """81 gain combinations: check final harm independently from cached plan fields."""
    a1, a2, b1, b2 = values
    pool = PrefixPool(4, 2)
    a = consumer(pool, "a", [a1 + a2, a2, 0])
    fill(pool, a)
    b = consumer(pool, "b", [b1 + b2, b2, 0])
    before_keys = set(pool.committed)
    candidate = plan(pool, b)
    if candidate is None:
        return
    after_keys = (before_keys - candidate.victims) | candidate.add
    def oracle(keys):
        total = 0
        for c in (a, b):
            frontier = 0
            for key in c.path:
                if key not in keys:
                    break
                frontier += 1
            total += c.recovery_ms[frontier]
        return total
    assert oracle(after_keys) < oracle(before_keys)
    tx = pool.begin(candidate, 0)
    assert pool.committed == before_keys and pool.physical_bytes <= pool.quota
    assert ack(pool, tx) == "COMMITTED"
    assert pool.committed == after_keys
    pool.check()
    drain(pool)
    assert pool.physical_bytes <= pool.steady_limit
