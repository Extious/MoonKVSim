"""Semantic and timeline checks for the checkpointed-count algorithm revision."""

from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.current.policy import hbm_gain, top_blocks
from moonkvsim.aegiskv.current.runtime import Checkpoint, CurrentRuntime, LoadBatch
from moonkvsim.aegiskv.current.workload import mechanism_workload


def config(**changes):
    return replace(Config(), layers=4, depth=2, **changes)


def test_checkpoint_and_physical_blocks_are_independent_and_validate_alignment():
    c = Config()
    assert c.checkpoint_tokens == 256 and c.block_tokens == 64
    assert c.checkpoint_tokens // c.block_tokens == 4
    assert replace(c, checkpoint_tokens=512).checkpoint_tokens == 512
    with pytest.raises(ValueError, match="multiple"):
        replace(c, checkpoint_tokens=250)


def test_hysteresis_is_strict_and_retains_a_near_tie():
    incumbent = (0, 1)
    counts = {(0, 0): 20, (0, 1): 10, (0, 2): 11}
    assert top_blocks(counts, 0, 3, 2, incumbent=incumbent, hysteresis=0.1) == incumbent
    counts[0, 2] = 11.01
    assert top_blocks(counts, 0, 3, 2, incumbent=incumbent, hysteresis=0.1) == (0, 2)
    assert top_blocks(counts, 0, 3, 0, incumbent=incumbent, hysteresis=0.1) == ()


def test_gain_is_difference_of_exposed_delays_and_skips_no_benefit():
    assert hbm_gain(100, 90, 0) == 10
    assert hbm_gain(80, 30, 0) == 50
    assert hbm_gain(80, 30, 50) == 30
    assert hbm_gain(80, 30, 90) == 0
    assert hbm_gain(30, 80, 0) == 0


def test_query_head_dedup_and_decay_apply_once_per_checkpoint():
    queries = []

    def provider(c, invocation, layer, query, blocks):
        queries.append((layer, query))
        return [0, 0, 0]  # same block selected by three heads

    c = config(count_decay=0.5)
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1), demand_provider=provider)
    state = next(iter(runtime.states.values()))
    state.call, state.worker, state.peer = 0, 0, 1
    state.checkpoint = Checkpoint(state.spec.key, 42, 0, 1)
    runtime._step = lambda state: None
    runtime._rebalance = lambda: None
    runtime._forward_done(state, 0, 128, False)
    assert state.counts[0, 0] == 128
    assert not state.count_snapshots
    runtime._forward_done(state, 128, 256, False)
    assert state.counts[0, 0] == 128  # beta * 256, never 3 heads * 256
    assert state.count_snapshots[256][0, 0] == 128
    runtime._forward_done(state, 256, 512, False)
    assert state.counts[0, 0] == 192  # beta * (128 + 256)
    assert state.count_snapshots[256][0, 0] == 128  # old frontier immutable
    assert len(queries) == c.layers * 512


def test_external_selector_cannot_read_future_blocks():
    runtime = CurrentRuntime(
        config(),
        mechanism_workload(workflows=1),
        demand_provider=lambda c, inv, layer, q, n: [q // c.block_tokens + 1],
    )
    state = next(iter(runtime.states.values()))
    state.call = 0
    with pytest.raises(ValueError, match="causally invisible"):
        runtime._demand(state, 0, 0, 10)


def test_first_layers_rank_only_when_a_checkpoint_publishes():
    runtime = CurrentRuntime(config(), mechanism_workload(workflows=1))
    result = runtime.run()
    assert result["metrics"]["topk_layer_reranks"] == result["metrics"]["checkpoint_commits"] * 2
    assert "recovery_layer_reranks" not in result["metrics"]
    updates = [e for e in runtime.events if e["kind"] == "topk_update"]
    commits = [e for e in runtime.events if e["kind"] == "checkpoint_commit"]
    assert [(e["agent"], e["frontier"], e["time_ns"]) for e in updates] == [
        (e["agent"], e["frontier"], e["time_ns"]) for e in commits
    ]


def test_checkpoint_bytes_include_live_and_pending_atomic_metadata_versions():
    c = config(network_bytes_per_second=1e8)
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1))
    runtime.des.run(until_ns=500_000_000)
    cps = [cp for cp in runtime.checkpoints if cp.frontier or cp.pending]
    assert cps
    for cp in cps:
        expected = (c.checkpoint_bytes(cp.frontier) + cp.pending_bytes) * c.tp
        assert runtime.ledgers[f"dram:{c.hosts[cp.peer]}"].bytes_in(cp.account) == expected
        assert cp.pending == bool(cp.pending_bytes)
        assert all(-block <= cp.frontier for _, block in cp.hbm if block < 0)


def test_hbm_admits_larger_gain_instead_of_larger_dram_delay():
    c = replace(config(), depth=1, top_k=1, hbm_cap_bytes=131168, initial_quota_bytes=131168)
    agents = tuple(
        Agent("w", name, (), (Invocation(tuple(range(256)), (1,)),), 1000)
        for name in ("a", "b", "zero")
    )
    runtime = CurrentRuntime(c, agents)
    runtime.tracker.slack = lambda now: {a.key: 0 for a in agents}
    for state in runtime.states.values():
        state.call, state.worker, state.peer, state.computed, state.durable = 0, 0, 1, 256, 256
        cp = Checkpoint(state.spec.key, runtime.sequence + 1, 0, 1, frontier=256)
        runtime._id("test-cp")
        cp.hot_sets = {0: (0,)}
        state.checkpoint = cp
        runtime.checkpoints.append(cp)
        runtime._dram_move(cp, "FREE", cp.account, c.checkpoint_bytes(256))
    delays = {"a": (100, 90), "b": (80, 30), "zero": (60, 60)}
    runtime._recovery_estimate = lambda state, hbm=False: delays[state.spec.name][int(hbm)]
    runtime._rebalance()
    assert not runtime.states["w/a"].checkpoint.desired_hot
    assert runtime.states["w/b"].checkpoint.desired_hot == {(0, 0), (0, -256)}
    assert not runtime.states["w/zero"].checkpoint.desired_hot
    assert runtime.states["w/b"].checkpoint.gain_ns == 50


def test_priority_preemption_preserves_bytes_and_resumes_the_prefetch():
    c = replace(
        config(),
        layers=2,
        depth=1,
        tp=1,
        h2d_bytes_per_second=1e6,
        selector_metadata_bytes_per_block_per_layer_rank=0,
        count_bytes_per_block_per_layer_rank=0,
    )
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1))
    # Isolate a recovery pipeline from unrelated foreground arrivals.
    runtime.des._heap.clear()
    state = next(iter(runtime.states.values()))
    state.call, state.worker = 0, 1
    cp = Checkpoint(state.spec.key, 999, 0, 1, frontier=256, readers=1, retired=True)
    state.recovering = cp
    runtime.checkpoints.append(cp)
    runtime._dram_move(cp, "FREE", cp.account, c.checkpoint_bytes(256))
    state.available = {(layer, b) for layer in range(2) for b in range(4)} - {(0, 0), (1, 0)}
    state.load_queue.append(LoadBatch(((1, 0),)))
    state.load_queue.append(LoadBatch(((0, 0),)))
    runtime._rebalance = lambda: None
    runtime._load_next(state)
    runtime.des.run(until_ns=50_000_000)
    times = []
    runtime._require(state, {(0, 0)}, lambda: times.append(runtime.des.now_ns))
    assert runtime.metrics["recovery_prefetch_preemptions"] == 1
    runtime.des.run()
    # 50ms already served to layer1; layer0 starts immediately at demand reveal.
    assert times == [50_000_000 + c.block_bytes * 1000]
    assert runtime.des.now_ns == 2 * c.block_bytes * 1000
    assert runtime.metrics["restore_bytes"] == 2 * c.block_bytes
    assert state.recovering is None


def test_hit_compute_overlaps_a_miss_instead_of_waiting_for_it():
    c = replace(
        config(),
        layers=1,
        depth=1,
        tp=1,
        h2d_bytes_per_second=1e6,
        selector_metadata_bytes_per_block_per_layer_rank=0,
        count_bytes_per_block_per_layer_rank=0,
    )
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1))
    runtime.des._heap.clear()
    state = next(iter(runtime.states.values()))
    state.call, state.worker = 0, 1
    cp = Checkpoint(state.spec.key, 999, 0, 1, frontier=256, readers=1, retired=True)
    state.recovering = cp
    runtime.checkpoints.append(cp)
    runtime._dram_move(cp, "FREE", cp.account, c.checkpoint_bytes(256))
    state.available = {(0, 0), (0, 1), (0, 2)}
    state.load_queue.append(LoadBatch(((0, 3),)))
    runtime._rebalance = lambda: None
    done = []
    runtime._layer_step(state, 256, 257, 0, 200_000_000, lambda: done.append(runtime.des.now_ns))
    runtime.des.run()
    # Hit work = 3/4*200ms=150ms; the 131.072ms miss is fully hidden.
    assert done == [200_000_000]
    assert runtime.metrics["recovery_exposed_miss_wait_ns"] == 0
    assert runtime.metrics["recovery_hit_compute_ns"] == 150_000_000


def test_duration_provider_and_light_logs_preserve_results():
    seen = []

    def profile(c, invocation, start, end, stage):
        seen.append((start, end, stage))
        return (end - start) * (
            c.prefill_ns_per_token if stage == "prefill" else c.decode_ns_per_token
        )

    kwargs = dict(
        config=config(), agents=mechanism_workload(workflows=1), failure=Failure("wf00/slow")
    )
    baseline = CurrentRuntime(**kwargs).run()
    runtime = CurrentRuntime(**kwargs, duration_profile=profile, retain_detailed_logs=False)
    result = runtime.run()
    assert result["workflows"] == baseline["workflows"]
    assert result["metrics"] == baseline["metrics"]
    assert any(start == 0 and end >= 256 and stage == "prefill" for start, end, stage in seen)
    assert not runtime.des.journal.records
    assert not runtime.flow_model.intervals
    assert not result["detailed_event_and_flow_logs_retained"]


def test_metadata_arrives_before_a_layer_can_reveal_sparse_demand():
    seen = []
    c = replace(config(), layers=1, depth=1, tp=1, h2d_bytes_per_second=1e6)

    def provider(c, inv, layer, query, blocks):
        seen.append(runtime.des.now_ns)
        return [0]

    runtime = CurrentRuntime(c, mechanism_workload(workflows=1), demand_provider=provider)
    runtime.des._heap.clear()
    state = next(iter(runtime.states.values()))
    state.call, state.worker = 0, 1
    cp = Checkpoint(state.spec.key, 999, 0, 1, frontier=256, readers=1, retired=True)
    state.recovering = cp
    runtime.checkpoints.append(cp)
    runtime._dram_move(cp, "FREE", cp.account, c.checkpoint_bytes(256))
    state.available = {(0, b) for b in range(4)}
    state.load_queue.append(LoadBatch(((0, -256),)))
    runtime._rebalance = lambda: None
    done = []
    runtime._layer_step(state, 256, 257, 0, 10_000, lambda: done.append(runtime.des.now_ns))
    assert seen == []  # selection is not available before metadata transfer
    runtime.des.run()
    # Full data restoration may finish with the metadata; then no demand
    # callback is needed because every block is already available.
    assert all(t >= c.metadata_layer_bytes(256) * 1000 for t in seen)
    assert done == [c.metadata_layer_bytes(256) * 1000 + 10_000]


def test_prefill_chunk_is_independent_of_checkpoint_interval():
    c = config(checkpoint_tokens=512, prefill_chunk_tokens=128)
    seen = []

    def profile(c, inv, start, end, stage):
        seen.append((start, end, stage))
        return (end - start) * 100_000

    inv = Invocation(tuple(range(700)), (1,))
    runtime = CurrentRuntime(
        c, (Agent("w", "a", (), (inv,), 1_000_000_000),), policy="none", duration_profile=profile
    )
    runtime.run()
    # The control-plane estimator also calls the profile with full prefixes;
    # take the direct sequence of actual request progress from the event log.
    forwards = [
        r
        for r in runtime.des.journal.records
        if r.record_type == "EVENT_EXECUTING" and r.data["kind"] == "FORWARD_COMPLETE"
    ]
    assert len(forwards) == 7  # 128*5 + 60 prefill, one decode
    assert (512, 640, "prefill") in seen and (640, 700, "prefill") in seen


def test_configured_dma_sensitivity_produces_explicit_nonzero_overhead():
    agents = mechanism_workload(workflows=1)
    baseline = CurrentRuntime(config(), agents, retain_detailed_logs=False).run()
    result = CurrentRuntime(
        config(compute_dma_slowdown=0.25), agents, retain_detailed_logs=False
    ).run()
    assert result["metrics"]["modeled_dma_compute_slowdown_ns"] > 0
    assert result["workflows"]["wf00"]["wct_ns"] > baseline["workflows"]["wf00"]["wct_ns"]


def test_mixed_partial_prefetch_yields_its_undemanded_objects_without_recopy():
    c = replace(
        config(),
        layers=1,
        depth=1,
        tp=1,
        h2d_bytes_per_second=1e6,
        selector_metadata_bytes_per_block_per_layer_rank=0,
        count_bytes_per_block_per_layer_rank=0,
    )
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1))
    runtime.des._heap.clear()
    state = next(iter(runtime.states.values()))
    state.call, state.worker = 0, 1
    cp = Checkpoint(state.spec.key, 999, 0, 1, frontier=256, readers=1, retired=True)
    state.recovering = cp
    runtime.checkpoints.append(cp)
    runtime._dram_move(cp, "FREE", cp.account, c.checkpoint_bytes(256))
    state.available = {(0, 3)}
    state.load_queue.extend([LoadBatch(((0, 0), (0, 1))), LoadBatch(((0, 2),))])
    runtime._rebalance = lambda: None
    runtime._load_next(state)
    runtime.des.run(until_ns=50_000_000)
    ready = []
    runtime._require(state, {(0, 0), (0, 2)}, lambda: ready.append(runtime.des.now_ns))
    runtime.des.run()
    # 25kB of the initial service belongs to each predictive object. Demand
    # finishes block0 and block2 before spending the remaining 106072B on block1.
    assert ready == [50_000_000 + (2 * c.block_bytes - 25_000) * 1000]
    assert runtime.des.now_ns == 3 * c.block_bytes * 1000
    assert runtime.metrics["restore_bytes"] == 3 * c.block_bytes
