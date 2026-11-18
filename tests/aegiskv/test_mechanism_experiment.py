"""Protection transactions and the public/controlled workload evidence boundary."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest

from moonkvsim.aegiskv import experiment as base
from moonkvsim.aegiskv.continuous_batch_des import (
    AegisContinuousBatchDESDriver,
    ContinuousBatchRequestSpec,
)
from moonkvsim.aegiskv.mechanism_experiment import MechanismConfig, MechanismRuntime, RevisionPool
from moonkvsim.aegiskv.prefix_frontier import Consumer, KVObject
from moonkvsim.config.validation import SchemaValidationError, validate_trace_span
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import AccountTransfer, CapacityLedger, CapacityResourceKind
from tests.aegiskv.test_continuous_batch_des import _bridge
from tests.aegiskv.test_experiment import _single_exact_token_record


def fixture_pool():
    runtime = SimpleNamespace(
        mechanism_config=MechanismConfig(staging_bytes=2, max_group=2),
        parameters=SimpleNamespace(
            peer_bandwidth_bytes_per_second=10**9,
            store_bandwidth_bytes_per_second=10**9,
            transfer_setup_ns=1,
        ),
        policy_cpu=[],
        executions={"r": SimpleNamespace(route_version=0)},
    )
    original = base._ModeledPool(
        pool_id="STORE_DRAM:test", capacity_bytes=6, eviction=base.EvictionKind.LRU, seed=0
    )
    pool = RevisionPool(runtime=runtime, original=original)
    chunks = tuple(
        base._Chunk(
            key=chr(97 + i),
            workflow_id="w",
            token_start=i,
            token_count=1,
            bytes=1,
            global_system_template=False,
        )
        for i in range(2)
    )
    parent = None
    for c in chunks:
        pool.policy.register_object(KVObject(c.key, parent, "test", c.bytes))
        parent = c.key
    pool.policy.update_consumer(
        Consumer("r", "test", tuple(c.key for c in chunks), (100, 90, 0), expires_ns=10**9)
    )
    pool.context = SimpleNamespace(span_id="r", path="STORE_DRAM")
    return pool, chunks


def test_staging_is_invisible_until_complete_group_ack():
    pool, chunks = fixture_pool()
    reservation = pool.reserve("copy", chunks, (Fraction(1),) * 2, now_ns=0, cause="test")
    assert reservation.bytes == 2
    assert not pool.entries and not pool.policy.committed
    assert pool.pending_bytes == pool.policy.physical_bytes == 2
    assert pool.prepare_commit("copy", 10)
    pool.commit_reservation("copy", now_ns=10, cause="ACK")
    assert set(pool.entries) == {"a", "b"}
    assert pool.pending_bytes == 0
    pool.check_revision()


def test_stale_consumer_epoch_aborts_real_copied_bytes():
    pool, chunks = fixture_pool()
    pool.reserve("copy", chunks, (Fraction(1),) * 2, now_ns=0, cause="test")
    pool.retire("r", 1)
    assert not pool.prepare_commit("copy", 10)
    pool.abort_reservation("copy", now_ns=10, cause="stale")
    assert not pool.entries
    assert pool.pending_bytes == pool.policy.physical_bytes == 0
    pool.check_revision()


def test_shared_cache_identity_does_not_use_request_id():
    a = _single_exact_token_record()
    b = deepcopy(a)
    b["span_id"] += ":revisit"
    shared = base.ModelParameters(runtime_semantics="shared_prefix_v3")
    private = base.ModelParameters(runtime_semantics="mooncake_prompt_v1")
    assert [c.key for c in base._chunks_for_record(a, shared)] == [
        c.key for c in base._chunks_for_record(b, shared)
    ]
    assert [c.key for c in base._chunks_for_record(a, private)] != [
        c.key for c in base._chunks_for_record(b, private)
    ]


def test_synthetic_revisit_cannot_masquerade_as_public_trace():
    record = _single_exact_token_record()
    record["synthetic"] = True
    with pytest.raises(SchemaValidationError):
        validate_trace_span(record)

    record.update(
        schema="moonkvsim.controlled_revisit_trace.v1",
        evidence_class="controlled_exact_input_revisit",
        mechanism_original_span_id=record["span_id"],
        mechanism_revisit_round=1,
    )
    validate_trace_span(record)
    del record["mechanism_original_span_id"]
    with pytest.raises(SchemaValidationError):
        validate_trace_span(record)


def test_kv_identity_includes_the_preceding_context():
    a = _single_exact_token_record()
    b = deepcopy(a)
    b["source_hash_ids"][0] += 1
    parameters = base.ModelParameters(runtime_semantics="shared_prefix_v3", policy_chunk_tokens=64)
    aa = base._chunks_for_record(a, parameters)
    bb = base._chunks_for_record(b, parameters)
    assert len(aa) > 1
    assert all(left.key != right.key for left, right in zip(aa, bb, strict=True))


def test_expired_store_hit_after_hbm_wait_admits_now_and_preserves_arrival():
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(des=des, bridges=(_bridge(des, index=0),))
    driver.register_suspended(
        ContinuousBatchRequestSpec(
            request_id="expired",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
        )
    )
    runtime = MechanismRuntime.__new__(MechanismRuntime)
    execution = SimpleNamespace(
        metadata=SimpleNamespace(prompt_tokens=4, output_tokens=1),
        route_version=0,
        chunks=(),
        reused_primary_tokens=0,
        reused_store_tokens=4,
        base_duration_ns=100,
        released_ns=0,
    )
    runtime.store_waiting = {"expired": ("dp-0", 1, 0)}
    runtime.executions = {"expired": execution}
    runtime.failed_gpu_ids = set()
    runtime.continuous_batch_driver = driver
    runtime.request_observations = {"expired": {"dram_hit_tokens": 4}}
    runtime._store_lookup_prefix_tokens = lambda *args, **kwargs: 0
    runtime.store_wait_events = []
    des.register_handler(EventKind.STORE_QUERY, runtime._retry_store_waiters)
    des.schedule_at(25, EventKind.STORE_QUERY)
    result = driver.run()
    request = result.requests[0]
    assert request["spec"]["release_ns"] == execution.released_ns == 0
    assert request["completion_ns"] == 125
    assert request["route_history"][0]["timestamp_ns"] == 25
    assert execution.reused_store_tokens == 0
    assert runtime.store_wait_events[0]["event"] == "CACHE_EXPIRED_OR_EVICTED_RECOMPUTE"


def test_peer_expiration_releases_hbm_even_when_next_admission_rejects(monkeypatch):
    pool, chunks = fixture_pool()
    pool.reserve("copy", chunks, (Fraction(1),) * 2, now_ns=0, cause="test")
    assert pool.prepare_commit("copy", 10)
    pool.commit_reservation("copy", now_ns=10, cause="ACK")
    pool.retire("r", 20)
    ledger = CapacityLedger(
        resource_id="hbm:peer",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=6,
        initial_accounts={base.HBM_PEER_PROTECTION_ACCOUNT: 2},
    )
    runtime = MechanismRuntime.__new__(MechanismRuntime)
    runtime.des = SimpleNamespace(now_ns=121 * 10**9)
    runtime.mechanism_config = MechanismConfig()
    runtime.failed_gpu_ids = set()
    runtime.peer_pools = {"peer": pool}
    runtime.hbm_ledgers = {"peer": ledger}
    runtime.executions = {"r": SimpleNamespace(status=base._ExecutionStatus.RUNNING)}
    runtime.pending_put_starts = {
        "new": SimpleNamespace(
            span_id="r", source_gpu_id="source", target_gpu_id="peer", path="PEER_HBM"
        )
    }
    runtime._observe_budget = lambda gpu: None
    runtime._pool_for_plan = lambda plan: pool
    runtime._commit_hbm_moves = lambda gpu, moves, **kw: ledger._replace_accounts(
        ledger.preview([AccountTransfer(*move) for move in moves])
    )
    monkeypatch.setattr(base._StudyRuntime, "_on_put_start", lambda *args: None)
    runtime._on_put_start(SimpleNamespace(payload={"plan_id": "new"}), runtime.des)
    assert pool.occupied_bytes == ledger.bytes_in(base.HBM_PEER_PROTECTION_ACCOUNT) == 0
    assert ledger.bytes_in(base.FREE_ACCOUNT) == ledger.capacity_bytes == 6
