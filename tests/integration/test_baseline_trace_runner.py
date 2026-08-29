from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from moonkvsim.baseline.runtime import (
    BaselineCoordinator,
    BaselineReplicaRuntime,
)
from moonkvsim.baseline.trace_runner import (
    STORE_PAYLOAD_BYTE_BASIS,
    TraceFailureSpec,
    TraceReplicaBinding,
    TraceRunnerConfig,
    TraceRunResult,
    TraceRunStatus,
    TraceSelection,
    TraceSelectionError,
    VanillaBaselineTraceRunner,
    load_trace_run_input,
)
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.router import DPRouter, RoutePolicy
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.predictor import (
    AssumedIntegerMixedPhaseCompositionRule,
    CalibrationEvidence,
    ForwardBoundary,
    ForwardPredictor,
    PredictionBatch,
    PredictionProfile,
)
from moonkvsim.recovery.baseline import EngineTarget, PhysicalGPU
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import (
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.client import StoreClient
from moonkvsim.store.master import MasterService
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    Topology,
    TopologyPath,
    TransportKind,
)
from moonkvsim.store.transfer_runtime import TransferRuntime

FIXTURE = Path(__file__).parent / "fixtures/weka-real-shape-three-span.jsonl"
MODEL_ID = "Qwen/Qwen3-8B"
MODEL_REVISION = "fixture-pinned-revision"
STORE_SEGMENT_ID = "shared-store-0"


class _ShapeForwardProvider:
    """Explicit test-only shape function, never a calibrated timing source."""

    provider_name = "fixture-shape-forward"

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> int:
        return 100 + batch.shape.total_extend_length


@dataclass(slots=True)
class _Harness:
    runner: VanillaBaselineTraceRunner
    des: GlobalDES
    schedulers: tuple[ContinuousBatchScheduler, ...]
    coordinator: BaselineCoordinator


def _memory_location(gpu_id: str, node_id: str) -> MemoryLocation:
    return MemoryLocation(
        resource_id=f"{gpu_id}.hbm",
        node_id=node_id,
        numa_node_id=f"numa:{node_id}:0",
        kind=MemoryKind.GPU_HBM,
        endpoint=f"rdma://{node_id}/{gpu_id}",
        gpu_id=gpu_id,
    )


def _topology(gpus: tuple[MemoryLocation, ...]) -> Topology:
    store = MemoryLocation(
        resource_id=STORE_SEGMENT_ID,
        node_id="store-node",
        numa_node_id="numa:store-node:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="rdma://shared-store-0",
    )
    return Topology(
        [
            path
            for rank, gpu in enumerate(gpus)
            for path in (
                TopologyPath(
                    path_id=f"direct-put:dp-{rank}",
                    source_kind=gpu.kind,
                    destination_kind=store.kind,
                    transport=TransportKind.RDMA_GDR,
                    rate_resource_ids=("gpu-read", "shared-fabric", "store-write"),
                    concurrency_resource_ids=(),
                    source_endpoint=gpu.endpoint,
                    destination_endpoint=store.endpoint,
                    source_node_id=gpu.node_id,
                    destination_node_id=store.node_id,
                    source_numa_node_id=gpu.numa_node_id,
                    destination_numa_node_id=store.numa_node_id,
                    source_hca_id=f"{gpu.node_id}.hca-0",
                    destination_hca_id="store-node.hca-0",
                ),
                TopologyPath(
                    path_id=f"direct-get:dp-{rank}",
                    source_kind=store.kind,
                    destination_kind=gpu.kind,
                    transport=TransportKind.RDMA_GDR,
                    rate_resource_ids=("store-read", "shared-fabric", "gpu-write"),
                    concurrency_resource_ids=(),
                    source_endpoint=store.endpoint,
                    destination_endpoint=gpu.endpoint,
                    source_node_id=store.node_id,
                    destination_node_id=gpu.node_id,
                    source_numa_node_id=store.numa_node_id,
                    destination_numa_node_id=gpu.numa_node_id,
                    source_hca_id="store-node.hca-0",
                    destination_hca_id=f"{gpu.node_id}.hca-0",
                ),
            )
        ]
    )


def _layout() -> StageBlockLayout:
    return StageBlockLayout(
        pp_stage=0,
        tensor_parallel_rank=0,
        block_size_tokens=16,
        layer_names=("fixture.layer.0.self_attn",),
        layer_indices=(0,),
        tensor_payload_bytes=100,
        auxiliary_payload_bytes=4,
        payload_bytes=104,
        layout_padding_bytes=8,
        allocator_metadata_bytes=4,
        requested_bytes=112,
        internal_fragmentation_bytes=12,
        allocated_bytes=128,
        allocator_alignment_bytes=16,
    )


def _predictor() -> ForwardPredictor:
    profile = PredictionProfile(
        provider_name=_ShapeForwardProvider.provider_name,
        provider_version="test-only-1",
        provider_source_revision="1" * 40,
        database_mode="explicit-assumed-shape-formula",
        database_sha256=hashlib.sha256(b"fixture-shape-forward-v1").hexdigest(),
        hardware_profile_id="fixture-gpu-profile",
        hardware_profile_fingerprint=hashlib.sha256(b"fixture-gpu-profile-v1").hexdigest(),
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )
    return ForwardPredictor(
        profile=profile,
        evidence=CalibrationEvidence.preliminary(profile.fingerprint),
        provider=_ShapeForwardProvider(),
    )


def _harness(
    *,
    replica_count: int = 2,
    max_running: int = 1,
    token_budget: int = 1_024,
    mixed_phase_rule: AssumedIntegerMixedPhaseCompositionRule | None = None,
) -> _Harness:
    des = GlobalDES()
    registry = AllocationRegistry(journal=des.journal)
    master = MasterService(
        allocation_strategy=RandomAllocationStrategy(seed=17),
        journal=des.journal,
        allocation_registry=registry,
    )
    master.mount_segment(
        Segment(
            segment_id=STORE_SEGMENT_ID,
            name=STORE_SEGMENT_ID,
            node_id="store-node",
            numa_node_id="numa:store-node:0",
            transport_endpoint="rdma://shared-store-0",
            capacity_bytes=16_384,
            allocation_alignment_bytes=64,
            allocator_metadata_bytes=0,
        ),
        CapacityLedger(
            resource_id=STORE_SEGMENT_ID,
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=16_384,
        ),
        timestamp_ns=0,
    )
    gpu_locations = tuple(
        _memory_location(f"gpu-{rank}", f"node-{rank}") for rank in range(replica_count)
    )
    topology = _topology(gpu_locations)
    model = FlowContentionModel(
        [
            RateResource("gpu-read", 1_000_000_000.0),
            RateResource("shared-fabric", 500_000_000.0),
            RateResource("store-write", 1_000_000_000.0),
            RateResource("store-read", 1_000_000_000.0),
            RateResource("gpu-write", 1_000_000_000.0),
        ]
    )
    transfer_runtime = TransferRuntime(controller=FlowDESController(des=des, model=model))
    layout = _layout()
    runtimes: list[BaselineReplicaRuntime] = []
    bindings: dict[str, TraceReplicaBinding] = {}
    schedulers: list[ContinuousBatchScheduler] = []
    hbm_ledgers: dict[str, CapacityLedger] = {}
    hbm_observers: list[HbmBlockLedgerBridge] = []
    for dp_rank in range(replica_count):
        replica_id = f"dp-{dp_rank}"
        gpu_id = f"gpu-{dp_rank}"
        resource_id = f"{gpu_id}.hbm"
        ledger = CapacityLedger(
            resource_id=resource_id,
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=128 * 128,
        )
        hbm_ledgers[resource_id] = ledger
        bridge = HbmBlockLedgerBridge(
            bridge_id=f"bridge-{replica_id}",
            bindings=(HbmStageRankBinding(resource_id, layout),),
            ledgers={resource_id: ledger},
            registry=registry,
            journal=des.journal,
            now_ns=lambda: des.now_ns,
        )
        scheduler = ContinuousBatchScheduler(
            block_pool=BlockPool(128, enable_caching=False),
            block_size_tokens=16,
            max_num_scheduled_tokens=token_budget,
            max_num_running_requests=max_running,
            block_lifecycle_observer=bridge,
        )
        gpu = gpu_locations[dp_rank]
        client = StoreClient(
            client_id=f"client-{replica_id}",
            master=master,
            topology=topology,
            local_gpu=gpu,
            registered_at_ns=0,
            slice_size_bytes=416,
        )
        runtime = BaselineReplicaRuntime(
            replica_id,
            dp_rank,
            f"scheduler-{dp_rank}",
            gpu_id,
            scheduler,
            client,
        )
        runtimes.append(runtime)
        bindings[replica_id] = TraceReplicaBinding(runtime, bridge)
        schedulers.append(scheduler)
        hbm_observers.append(bridge)
    coordinator = BaselineCoordinator(
        des=des,
        router=DPRouter(router_id="trace-router", policy=RoutePolicy.ROUND_ROBIN),
        replicas=runtimes,
        master=master,
        transfer_runtime=transfer_runtime,
        gpus=tuple(
            PhysicalGPU(f"gpu-{rank}", f"node-{rank}", (f"gpu-{rank}.hbm",))
            for rank in range(replica_count)
        ),
        targets=tuple(
            EngineTarget(
                f"dp-{rank}",
                rank,
                (f"gpu-{rank}",),
                "qwen3-tp1-pp1",
            )
            for rank in range(replica_count)
        ),
        hbm_ledgers=hbm_ledgers,
        hbm_failure_observers=hbm_observers,
    )
    runner = VanillaBaselineTraceRunner(
        coordinator=coordinator,
        replicas=bindings,
        predictor=_predictor(),
        mixed_phase_composition_rule=mixed_phase_rule,
        config=TraceRunnerConfig(
            tenant_id="fixture-tenant",
            target_model_id=MODEL_ID,
            target_model_revision=MODEL_REVISION,
            kv_dtype="bf16",
            kv_abi="vllm-v1",
            kv_layout="fixture-tp1-pp1",
            tensor_parallel_size=1,
            pipeline_parallel_size=1,
            store_payload_bytes_per_source_block=416,
            store_payload_byte_basis=STORE_PAYLOAD_BYTE_BASIS,
            preferred_store_segment_ids=(STORE_SEGMENT_ID,),
        ),
    )
    return _Harness(runner, des, tuple(schedulers), coordinator)


def _record_positions(result: TraceRunResult, record_type: str) -> list[int]:
    journal = result.journal
    return [
        record.journal_sequence for record in journal.records if record.record_type == record_type
    ]


def _set_source_hash_ids(record: dict[str, object], values: list[int]) -> None:
    record["source_hash_ids"] = values
    record["source_hash_ids_sha256"] = hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record["prompt_tokens"] = len(values) * 64
    record["total_model_tokens"] = record["prompt_tokens"] + record["output_tokens"]  # type: ignore[operator]


def _write_trace(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
        ),
        encoding="utf-8",
    )
    return path


def test_full_real_shape_trace_is_deterministic_multi_dp_and_causal(tmp_path: Path) -> None:
    run_input = load_trace_run_input(FIXTURE)
    first = _harness().runner.run(run_input)
    second = _harness().runner.run(run_input)

    assert first.status is TraceRunStatus.PASS
    assert not first.gaps
    assert all(item.status.value == "COMPLETED" for item in first.executions)
    assert first.capacity_audit.valid
    assert first.capacity_audit.final_snapshot_byte_identical
    assert first.journal.to_jsonl_bytes() == second.journal.to_jsonl_bytes()
    assert first.summary_document() == second.summary_document()
    admitted_targets = {
        record.data["target_replica_id"]
        for record in first.journal.records
        if record.record_type == "TRACE_RUNNER_SPAN_ADMITTED"
    }
    assert admitted_targets == {"dp-0", "dp-1"}
    child = next(item for item in first.executions if "subagent" in item.trace_span.span_id)
    parent = next(
        item
        for item in first.executions
        if item.trace_span.span_id == "weka:wf-toy-001:main:000000"
    )
    assert child.restored_tokens == 128
    assert child.completed_ns is not None
    assert parent.completed_ns is not None
    child_release = next(
        record
        for record in first.journal.records
        if record.record_type == "WORKLOAD_SPAN_RELEASED"
        and record.data["span_id"] == child.trace_span.span_id
    )
    assert child_release.timestamp_ns == (
        parent.completed_ns + child.trace_span.metadata.tool_delay_ns
    )
    assert _record_positions(first, "STORE_CLIENT_GET_STARTED")
    assert _record_positions(first, "RESOURCE_TRANSACTION")
    assert first.transfer_resource_calendar_replay_byte_identical
    assert first.run_audit_document()["transfer_resource_calendar_replay_byte_identical"] is True
    assert first.flow_rate_state_replay_byte_identical
    assert first.run_audit_document()["flow_rate_state_replay_byte_identical"] is True
    assert first.run_audit_document()["journal_replay_byte_identical"] is True

    output = tmp_path / "run"
    first.write_section_16_artifacts(output)
    assert {item.name for item in output.iterdir()} == set(first.present_section_16_artifacts)
    assert (output / "resource-ledger-deltas.parquet").read_bytes()[:4] == b"PAR1"
    assert (output / "flow-rate-events.parquet").read_bytes()[:4] == b"PAR1"
    run_audit = json.loads((output / "run-audit.json").read_text())
    assert run_audit["predictor"]["database_sha256"] is None
    assert run_audit["predictor"]["calibration_status"] == "not_calibrated"
    assert run_audit["transfer_resource_calendar_replay_byte_identical"] is True
    assert run_audit["flow_rate_state_replay_byte_identical"] is True
    assert run_audit["section_16"]["complete_file_set"] is True
    assert run_audit["trace_runner"]["section_16"]["complete"] is True


def test_hash_exact_store_lookup_ignores_parent_metric_and_stops_at_first_miss(
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in FIXTURE.read_text().splitlines()[1:]]
    parent, child = records
    _set_source_hash_ids(parent, [0, 99, 2])
    child["cached_prefix_tokens"] = 0
    trace_path = _write_trace(tmp_path / "non-contiguous-prefix.jsonl", records)

    result = _harness().runner.run(load_trace_run_input(trace_path))

    assert result.status is TraceRunStatus.PASS
    admitted = next(
        record
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_SPAN_ADMITTED"
        and record.data["span_id"] == child["span_id"]
    )
    assert admitted.data["normalized_parent_prefix_tokens"] == 0
    assert admitted.data["visible_committed_prefix_tokens"] == 64
    assert admitted.data["committed_prefix_lookup"] == {
        "mode": "full_hash_vector_from_block_zero_first_miss",
        "visibility": "committed_published_store_replicas_only",
        "candidate_block_count": 3,
        "queried_block_count": 2,
        "observed_committed_block_count": 1,
        "first_miss_block_index": 1,
        "normalized_parent_prefix_used_as_query_limit": False,
    }
    child_gets = [
        record
        for record in result.journal.records
        if record.record_type == "STORE_CLIENT_GET_STARTED"
        and child["span_id"] in record.data["get_id"]
    ]
    assert len(child_gets) == 1
    [child_get] = child_gets
    assert child_get.data["client_id"] == "client-dp-1"
    assert any(
        record.record_type == "STORE_CLIENT_PUT_STARTED"
        and record.data["client_id"] == "client-dp-0"
        and record.data["object_id"] == child_get.data["object_id"]
        for record in result.journal.records
    )
    child_audit = next(
        item
        for item in result.trace_audit_document()["spans"]
        if item["span_id"] == child["span_id"]
    )
    assert child_audit["normalized_parent_prefix_tokens"] == 0
    assert child_audit["visible_committed_store_prefix_tokens"] == 64


def test_pending_store_replica_is_not_observed_as_committed_prefix(tmp_path: Path) -> None:
    template = json.loads(FIXTURE.read_text().splitlines()[1])
    producer = dict(template)
    consumer = json.loads(json.dumps(template))
    for record, index, submit_ns in (
        (producer, 0, 0),
        (consumer, 1, 200),
    ):
        record["workflow_id"] = "wf-pending-prefix"
        record["session_id"] = "wf-pending-prefix"
        record["span_id"] = f"weka:wf-pending-prefix:main:{index:06d}"
        record["observed_submit_ns"] = submit_ns
        record["observed_finish_ns"] = submit_ns + 1_000
        record["recorded_api_time_ns"] = 1_000
        record["output_tokens"] = 1
        record["cached_prefix_tokens"] = 0
        record["source_position"] = {
            "workflow_line": 1,
            "top_level_index": index,
            "inner_index": None,
        }
        _set_source_hash_ids(record, [0])
    trace_path = _write_trace(tmp_path / "pending-prefix.jsonl", [producer, consumer])

    result = _harness().runner.run(load_trace_run_input(trace_path))

    assert result.status is TraceRunStatus.PASS
    admitted = next(
        record
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_SPAN_ADMITTED"
        and record.data["span_id"] == consumer["span_id"]
    )
    assert admitted.timestamp_ns == 200
    assert admitted.data["visible_committed_prefix_tokens"] == 0
    assert admitted.data["committed_prefix_lookup"]["first_miss_block_index"] == 0
    producer_put = next(
        record
        for record in result.journal.records
        if record.record_type == "STORE_CLIENT_PUT_STARTED"
        and producer["span_id"] in record.data["put_id"]
    )
    producer_commit = next(
        record
        for record in result.journal.records
        if record.record_type == "STORE_CLIENT_PUT_COMMITTED"
        and producer["span_id"] in record.data["put_id"]
    )
    assert producer_put.timestamp_ns < admitted.timestamp_ns < producer_commit.timestamp_ns


def _mixed_phase_trace(tmp_path: Path) -> Path:
    records = [json.loads(line) for line in FIXTURE.read_text().splitlines()[:2]]
    long_request = records[0]
    long_request["observed_submit_ns"] = 1
    long_request["observed_finish_ns"] = long_request["recorded_api_time_ns"] + 1
    path = tmp_path / "mixed-phase.jsonl"
    path.write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records),
        encoding="utf-8",
    )
    return path


def _mixed_phase_rule() -> AssumedIntegerMixedPhaseCompositionRule:
    return AssumedIntegerMixedPhaseCompositionRule(
        parameter_fingerprint=hashlib.sha256(b"fixture-mixed-rule-v1").hexdigest(),
        base_ns=7,
        batch_request_overhead_ns=3,
        prefill_ns_per_scheduled_token=2,
        decode_ns_per_request=5,
        decode_ns_per_past_token=1,
    )


def test_mixed_phase_requires_explicit_rule_and_records_joint_assumption(
    tmp_path: Path,
) -> None:
    run_input = load_trace_run_input(_mixed_phase_trace(tmp_path))
    blocked = _harness(replica_count=1, max_running=2).runner.run(run_input)

    assert blocked.status is TraceRunStatus.BLOCKED
    assert {gap.code for gap in blocked.gaps} == {"TRC-BLOCK-FORWARD-PREDICTOR"}
    assert any("no explicit rule" in gap.message for gap in blocked.gaps)

    rule = _mixed_phase_rule()
    completed = _harness(
        replica_count=1,
        max_running=2,
        mixed_phase_rule=rule,
    ).runner.run(run_input)

    assert completed.status is TraceRunStatus.PASS
    assert completed.mixed_phase_composition_count > 0
    mixed_records = [
        record
        for record in completed.journal.records
        if record.record_type == "TRACE_RUNNER_FORWARD_PREDICTED"
        and record.data["composition"]["mode"] == "mixed_phase_joint_composition"
    ]
    assert mixed_records
    for record in mixed_records:
        prediction = record.data["prediction"]
        assert [item["phase"] for item in prediction["phase_shapes"]] == [
            "prefill",
            "decode",
        ]
        assert prediction["composition_rule"]["fingerprint"] == rule.fingerprint
        assert prediction["calibration_status"] == "not_calibrated"
        assert prediction["formal_use_allowed"] is False
        shapes = {item["phase"]: item["shape"] for item in prediction["phase_shapes"]}
        expected = (
            rule.base_ns
            + rule.batch_request_overhead_ns
            * (shapes["prefill"]["batch_size"] + shapes["decode"]["batch_size"])
            + rule.prefill_ns_per_scheduled_token * shapes["prefill"]["total_extend_length"]
            + rule.decode_ns_per_request * shapes["decode"]["batch_size"]
            + rule.decode_ns_per_past_token * sum(shapes["decode"]["past_kv_lengths"])
        )
        assert prediction["predicted_forward_duration_ns"] == expected


def test_same_dp_same_phase_requests_share_one_journaled_compute_lease() -> None:
    harness = _harness(replica_count=1, max_running=2)
    run_input = load_trace_run_input(FIXTURE)

    result = harness.runner.run(run_input)

    assert result.status is TraceRunStatus.PASS
    predicted = [
        record
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_FORWARD_PREDICTED"
    ]
    first = predicted[0]
    assert first.data["batch_size"] == 2
    assert "scheduler_output" not in first.data
    assert "adapted_step" not in first.data
    assert len(first.data["adapter"]["fingerprint"]) == 64
    assert len(first.data["adapter"]["scheduler_output_fingerprint"]) == 64
    assert [item["phase"] for item in first.data["phase_shapes"]] == ["prefill"]
    first_participants = first.data["participants"]
    assert isinstance(first_participants, list)
    assert len(first_participants) == 2
    assert {item["phase"] for item in first_participants} == {"PREFILL"}
    assert len({item["request_id"] for item in first_participants}) == 2
    assert any(
        record.record_type == "BASELINE_FORWARD_BATCH_COMPLETED"
        and len(record.data["participants"]) == 2
        for record in result.journal.records
    )

    active_replica_leases: set[str] = set()
    for record in result.journal.records:
        if record.record_type == "TRACE_RUNNER_GPU_COMPUTE_LEASE_ACQUIRED":
            replica_id = record.data["replica_id"]
            assert replica_id not in active_replica_leases
            assert record.data["capacity"] == 1
            active_replica_leases.add(replica_id)
        elif record.record_type == "TRACE_RUNNER_GPU_COMPUTE_LEASE_RELEASED":
            replica_id = record.data["replica_id"]
            assert replica_id in active_replica_leases
            active_replica_leases.remove(replica_id)
    assert not active_replica_leases
    expected_outputs = sum(item.metadata.output_tokens for item in run_input.spans)
    assert len(harness.coordinator.failure_controller.emitted_outputs) == expected_outputs


def test_chunked_prefill_emits_only_after_prompt_is_fully_computed() -> None:
    harness = _harness(
        replica_count=1,
        max_running=1,
        token_budget=64,
    )
    run_input = load_trace_run_input(FIXTURE, selection=TraceSelection(max_spans=1))

    result = harness.runner.run(run_input)

    assert result.status is TraceRunStatus.PASS
    [execution] = result.executions
    assert execution.request is not None
    participant_rows = [
        record.data["participants"][0]
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_FORWARD_PREDICTED"
    ]
    prefill_rows = [item for item in participant_rows if item["phase"] == "PREFILL"]
    decode_rows = [item for item in participant_rows if item["phase"] == "DECODE"]
    assert len(prefill_rows) == 10
    assert [item["produces_output"] for item in prefill_rows] == [False] * 9 + [True]
    assert all(item["chunked"] for item in prefill_rows[:-1])
    assert prefill_rows[-1]["num_computed_tokens_after"] == 640
    assert len(decode_rows) == 19
    assert all(item["produces_output"] for item in decode_rows)
    assert execution.scheduler_step_count == 29
    assert execution.request.num_output_tokens == execution.trace_span.metadata.output_tokens
    assert len(harness.coordinator.failure_controller.emitted_outputs) == 20
    assert (
        sum(record.record_type == "BASELINE_OUTPUT_ACTIVATED" for record in result.journal.records)
        == 20
    )


def test_compute_failure_atomically_loses_hbm_reroutes_and_replays_exactly() -> None:
    harness = _harness()
    result = harness.runner.run(
        load_trace_run_input(FIXTURE),
        failures=(TraceFailureSpec("failure-0", "gpu-0", at_ns=50),),
    )

    assert result.status is TraceRunStatus.PASS
    assert not result.gaps
    assert result.capacity_audit.valid
    assert result.allocation_registry_replay_byte_identical
    failed_hbm = result.final_ledgers["gpu-0.hbm"]
    assert failed_hbm.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == failed_hbm.capacity_bytes
    failed_allocations = harness.coordinator.master.allocation_registry.allocations_on_resources(
        ("gpu-0.hbm",)
    )
    assert failed_allocations
    assert all(item.state is AllocationState.LOST for item in failed_allocations)
    assert any(record.record_type == "BASELINE_REROUTED" for record in result.journal.records)
    assert any(
        record.record_type == "TRACE_RUNNER_RECOVERY_STARTED" for record in result.journal.records
    )
    replay_predictions = [
        record
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_SILENT_REPLAY_FORWARD_PREDICTED"
    ]
    assert replay_predictions
    assert all(record.data["formal_use_allowed"] is False for record in replay_predictions)
    assert all(
        record.data["participant"]["externally_emitted"] is False for record in replay_predictions
    )
    replay_completed_position = min(
        _record_positions(result, "TRACE_RUNNER_SILENT_REPLAY_FORWARD_COMPLETED")
    )
    recovery_activated_position = min(_record_positions(result, "TRACE_RUNNER_RECOVERY_ACTIVATED"))
    assert replay_completed_position < recovery_activated_position
    assert all(
        record.data["activation_gate"] == "READY_TO_ACTIVATE_after_modeled_forward_completion"
        for record in result.journal.records
        if record.record_type == "TRACE_RUNNER_RECOVERY_ACTIVATED"
    )
    assert any(
        record.record_type == "VLLM_HBM_RESOURCES_FAILED" for record in result.journal.records
    )
    outputs = harness.coordinator.failure_controller.emitted_outputs
    output_keys = {(item.request_id, item.output_index) for item in outputs}
    assert (
        len(output_keys)
        == len(outputs)
        == sum(item.metadata.output_tokens for item in result.run_input.spans)
    )
    assert result.summary_document()["gap_codes"] == []
    assert result.run_audit_document()["journal_replay_byte_identical"] is True
    assert result.run_audit_document()["formal_use_allowed"] is False


def test_prefix_get_failure_aborts_transfer_then_recovers_deterministically() -> None:
    run_input = load_trace_run_input(FIXTURE)
    reference = _harness().runner.run(run_input)
    child_request_id = "trace-request:weka:wf-toy-001:subagent:000001:000000"
    prefix_wait = next(
        record
        for record in reference.journal.records
        if record.record_type == "TRACE_RUNNER_REMOTE_PREFIX_WAITING"
        and record.data["request_id"] == child_request_id
    )
    failure = TraceFailureSpec(
        "failure-during-prefix-get",
        "gpu-0",
        at_ns=prefix_wait.timestamp_ns + 1,
    )

    first_harness = _harness()
    second_harness = _harness()
    first = first_harness.runner.run(run_input, failures=(failure,))
    second = second_harness.runner.run(run_input, failures=(failure,))

    assert first.status is second.status is TraceRunStatus.PASS
    assert not first.gaps and not second.gaps
    assert first.journal.to_jsonl_bytes() == second.journal.to_jsonl_bytes()
    assert first.summary_document() == second.summary_document()
    assert first.capacity_audit.valid
    assert first.allocation_registry_replay_byte_identical
    deferred = [
        record
        for record in first.journal.records
        if record.record_type == "TRACE_RUNNER_GPU_FAILURE_TRANSFER_DEFERRED"
    ]
    assert len(deferred) == 2
    assert {record.data["phase"] for record in deferred} == {"NORMAL_PREFIX_GET"}
    assert all(record.data["request_id"] == child_request_id for record in deferred)
    recovery = next(
        record
        for record in first.journal.records
        if record.record_type == "TRACE_RUNNER_RECOVERY_STARTED"
        and record.data["request_id"] == child_request_id
    )
    assert recovery.data["target_replica_id"] == "dp-1"
    assert recovery.data["transfer_count"] == 2
    failed_hbm = first.final_ledgers["gpu-0.hbm"]
    assert failed_hbm.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == failed_hbm.capacity_bytes
    outputs = first_harness.coordinator.failure_controller.emitted_outputs
    assert (
        len({(item.request_id, item.output_index) for item in outputs})
        == len(outputs)
        == sum(item.metadata.output_tokens for item in run_input.spans)
    )
    assert first.run_audit_document()["journal_replay_byte_identical"] is True


def test_smoke_selection_never_cuts_a_workflow_dag() -> None:
    smoke = load_trace_run_input(FIXTURE, selection=TraceSelection(max_spans=1))

    assert len(smoke.spans) == 1
    assert smoke.selected_workflow_ids == ("002001296e8a8c38ad9d7cc436d691afc602",)
    with pytest.raises(TraceSelectionError, match="cut a workflow DAG"):
        load_trace_run_input(
            FIXTURE,
            selection=TraceSelection(
                workflow_ids=("wf-toy-001",),
                max_spans=1,
            ),
        )


def test_explicit_workflow_selection_still_validates_unselected_rows(
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    selected_workflow_id = records[0]["workflow_id"]
    assert records[-1]["workflow_id"] != selected_workflow_id
    records[-1]["source_hash_ids_sha256"] = "0" * 64
    corrupted = tmp_path / "corrupted-unselected.jsonl"
    corrupted.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records
        )
    )

    with pytest.raises(TraceSelectionError, match="source_hash_ids_sha256"):
        load_trace_run_input(
            corrupted,
            selection=TraceSelection(workflow_ids=(selected_workflow_id,)),
        )
