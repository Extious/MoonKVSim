from dataclasses import replace

import pytest

from moonkvsim.aegiskv.foreground_budget import (
    ForegroundBudget,
    MemoryEnvelope,
    Observation,
    QoSCertificate,
    TransferBucket,
    TransferBudget,
)
from moonkvsim.aegiskv.prefix_frontier import Consumer, KVObject, PrefixPool
from moonkvsim.aegiskv.revision_runtime import RevisionRuntime


def certificate(**kwargs):
    return replace(QoSCertificate(
        "gpu:model:allocator", "load-bin-1", 10**12, 500, 1000, 50, 10,
        .005, .008, .003, "synthetic-contract-fixture", kind="modeled",
    ), **kwargs)


def observation(sequence, now, **kwargs):
    return replace(Observation(
        7, sequence, now, now, "gpu:model:allocator", "load-bin-1",
        MemoryEnvelope(1000, 200, 100, 0, 100, 50, 1000),
        0, 0, 500, certificate=certificate(),
    ), **kwargs)


def governor(**kwargs):
    return ForegroundBudget(epoch=7, registered_bytes=1000, policy_cap_bytes=500,
                            stable_ns=100, grow_bytes_per_second=10**9,
                            max_observation_age_ns=100, allow_modeled=True, **kwargs)


def grown(g):
    decisions = [g.observe(observation(i, i * 100)) for i in range(6)]
    assert decisions[-1].quota_bytes == 500
    return decisions


def test_quota_grows_only_with_stable_valid_demand():
    g = governor()
    decisions = grown(g)
    assert [d.quota_bytes for d in decisions] == [0, 100, 200, 300, 400, 500]
    assert decisions[-1].alpha == .5


def test_next_primary_event_shrinks_without_periodic_window_and_waits_for_ack():
    g = governor()
    grown(g)
    obs = observation(6, 501, backup_physical_bytes=500,
                      memory=MemoryEnvelope(1000, 200, 100, 500, 100, 50, 1000))
    decision = g.observe(obs)
    assert decision.quota_bytes == 50
    assert decision.pause_copy and not decision.foreground_ready
    assert decision.reclaim_needed_bytes == 450
    after = g.observe(replace(obs, sequence=7, now_ns=502, sampled_ns=502,
                             backup_physical_bytes=50))
    assert after.foreground_ready and after.reclaim_needed_bytes == 0


@pytest.mark.parametrize("change", [
    {"certificate": None}, {"valid": False}, {"foreground_violation": True},
    {"sampled_ns": 0}, {"region": "unseen-burst"},
    {"certificate": certificate(ttft_p99_relative_ucb=.011)},
    {"certificate": certificate(tpot_p99_relative_ucb=.011)},
    {"certificate": certificate(goodput_relative_loss_ucb=.011)},
    {"certificate": certificate(expires_ns=500)},
])
def test_unknown_or_excessive_interference_revokes_without_optimistic_growth(change):
    g = governor()
    grown(g)
    d = g.observe(observation(6, 600, backup_physical_bytes=400, **change))
    assert d.quota_bytes == 0 and d.pause_copy and d.reclaim_needed_bytes == 400


def test_modeled_certificate_cannot_enable_production_hbm():
    g = ForegroundBudget(epoch=7, registered_bytes=1000, policy_cap_bytes=500)
    assert g.observe(observation(1, 100)).quota_bytes == 0
    assert g.observe(observation(2, 10**9)).quota_bytes == 0


def test_no_demand_no_growth_and_uncertain_sampling_resets_stability():
    g = governor()
    for i in range(5):
        assert g.observe(observation(i, i * 100, useful_demand_bytes=0)).quota_bytes == 0
    assert g.observe(observation(5, 1000)).quota_bytes == 0  # Gap, no accumulated credit.
    assert g.observe(observation(6, 1100)).quota_bytes == 100


def test_control_retry_is_idempotent_and_stale_or_conflicting_identity_rejected():
    g = governor()
    grown(g)
    obs = observation(6, 600, foreground_violation=True)
    first = g.observe(obs)
    assert g.observe(obs) is first
    with pytest.raises(ValueError, match="reused"):
        g.observe(replace(obs, foreground_violation=False))
    with pytest.raises(ValueError, match="stale"):
        g.observe(replace(obs, sequence=5))
    with pytest.raises(ValueError, match="incarnation"):
        g.observe(replace(obs, epoch=8))


def test_reclaim_debt_blocks_expansion_even_if_desired_quota_has_space():
    g = governor()
    grown(g)
    d = g.observe(observation(6, 600, backup_physical_bytes=400,
                              outstanding_reclaim_bytes=100))
    assert d.quota_bytes == 500 and d.pause_copy
    assert d.reclaim_needed_bytes == 0  # Existing task still owed despite quota satisfied.


def test_allocator_arena_that_cannot_lend_never_grants_hbm():
    g = governor()
    mem = MemoryEnvelope(1000, 0, 0, 0, 0, 0, 0)
    for i in range(6):
        assert g.observe(observation(i, i * 100, memory=mem)).quota_bytes == 0


def test_tiers_share_source_transfer_tokens_with_atomic_admission():
    budgets = TransferBudget({
        name: TransferBucket(100, 100, 50, 10**12, 100)
        for name in ("source", "hbm", "dram", "link")
    })
    assert budgets.take(("source", "link", "hbm"), 50, 0)
    assert budgets.take(("source", "link", "dram"), 50, 0)
    hbm_before = budgets.buckets["hbm"].tokens
    assert not budgets.take(("source", "link", "hbm"), 1, 0)
    assert budgets.buckets["hbm"].tokens == hbm_before
    assert not budgets.take(("source", "link", "hbm"), 51, 10**9)
    assert budgets.take(("source", "link", "hbm"), 50, 10**9)
    assert not budgets.take(("source", "link", "hbm"), 1, 10**12)


@pytest.mark.parametrize("next_demand", range(0, 1001, 25))
def test_every_memory_envelope_preserves_reserved_foreground_bound(next_demand):
    g = governor()
    grown(g)
    mem = MemoryEnvelope(1000, 200, 100, next_demand, 100, 50, 1000)
    d = g.observe(observation(6, 501, memory=mem))
    assert d.quota_bytes <= max(0, 550 - next_demand)
    assert d.quota_bytes <= 500


def test_runtime_reconciles_before_mutation_and_independent_dram_remains_possible():
    runtime = RevisionRuntime(
        {"hbm": PrefixPool(6, 2), "dram": PrefixPool(6, 2)}, "hbm", governor(),
        TransferBudget({name: TransferBucket(100, 100, 50, 10**12, 100)
                        for name in ("source", "hbm", "dram")}),
        {"hbm": ("source", "hbm"), "dram": ("source", "dram")},
    )
    with pytest.raises(ValueError, match="reconcile"):
        runtime.observe_foreground(observation(0, 0, backup_physical_bytes=1))
    first = runtime.observe_foreground(observation(0, 0, certificate=None))
    assert first.quota_bytes == 0
    epoch = runtime.pools["hbm"].epoch
    assert runtime.observe_foreground(observation(0, 0, certificate=None)) == first
    assert runtime.pools["hbm"].epoch == epoch
    assert not runtime.copy_batch("hbm", 1, 0)
    assert runtime.copy_batch("dram", 1, 0)


def test_nonfinite_certificate_cannot_pass_comparisons():
    with pytest.raises(ValueError, match="finite"):
        certificate(ttft_p99_relative_ucb=float("nan"))


def test_two_tier_event_execution_and_duplicate_shrink_with_live_reclaim_debt():
    pools = {name: PrefixPool(6, 2) for name in ("hbm", "dram")}
    obj = KVObject.sealed("tenant:model:abi", None, (42,), 1)
    c = Consumer("round-1", obj.namespace, (obj.key,), (10, 0))
    for pool in pools.values():
        pool.register_object(obj)
        pool.update_consumer(c)
    runtime = RevisionRuntime(
        pools, "hbm", governor(),
        TransferBudget({name: TransferBucket(10**9, 100, 50, 10**12, 100)
                        for name in ("source", "hbm", "dram")}),
        {"hbm": ("source", "hbm"), "dram": ("source", "dram")},
    )
    cert = certificate(copy_bytes_per_second=10**9)
    for i in range(2):
        runtime.observe_foreground(observation(i, i * 100, certificate=cert,
                                               useful_demand_bytes=6))
    copies = runtime.begin_independent(
        c.request, 101, {obj.key}, copy_budget_bytes=2, copy_ns_per_byte=1,
        permit_expires_ns=200,
    )
    assert all(tx is not None for tx in copies.values())
    for name, tx in copies.items():
        assert runtime.copy_batch(name, 1, 101)
        pools[name].acknowledge_shard(tx, obj.key, 0)
        assert pools[name].finish(tx, 103) == "COMMITTED"
    pressure = observation(2, 104, certificate=cert, foreground_violation=True,
                           backup_physical_bytes=1)
    decision = runtime.observe_foreground(pressure)
    tasks = pools["hbm"].reclaim_tasks()
    assert tasks and decision.quota_bytes == 0
    assert runtime.observe_foreground(pressure) == decision
    assert pools["hbm"].reclaim_tasks() == tasks
    assert pools["hbm"].physical_bytes == 1  # Lost free response not an available byte.
    assert not runtime.copy_batch("hbm", 1, 105)
    assert pools["dram"].frontier(c.request) == 1
    for task in tasks:
        pools["hbm"].acknowledge_free(*task)
    assert pools["hbm"].physical_bytes == 0


def test_watchdog_aborts_unacknowledged_group_and_expires_copy_certificate():
    pools = {name: PrefixPool(6, 2) for name in ("hbm", "dram")}
    obj = KVObject.sealed("tenant:model:abi", None, (42,), 1)
    c = Consumer("round-1", obj.namespace, (obj.key,), (10, 0))
    for pool in pools.values():
        pool.register_object(obj)
        pool.update_consumer(c)
    runtime = RevisionRuntime(
        pools, "hbm", governor(), TransferBudget({}), {"hbm": (), "dram": ()},
    )
    cert = certificate(copy_bytes_per_second=10**9)
    for i in range(2):
        runtime.observe_foreground(observation(i, i * 100, certificate=cert,
                                               useful_demand_bytes=6))
    copies = runtime.begin_independent(
        c.request, 101, {obj.key}, copy_budget_bytes=2, copy_ns_per_byte=1,
        permit_expires_ns=150,
    )
    runtime.watchdog(150, 2)
    for name, tx in copies.items():
        assert pools[name].transactions[tx].terminal == "ABORTED"
        assert pools[name].physical_bytes == 1 and pools[name].reclaim_tasks()
    runtime.watchdog(200, 3)
    assert runtime.decision.pause_copy and runtime.decision.quota_bytes == 0
    assert runtime.last_observation.sampled_ns == 100  # Timer is not a fresh healthy sample.
