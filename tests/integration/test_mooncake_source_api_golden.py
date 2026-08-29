from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.eviction import FIFOEvictionStrategy, LRUEvictionStrategy
from moonkvsim.store.master import MasterService
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    SliceStatus,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = PROJECT_ROOT / "reference/goldens/mooncake-f161118-store-te-source-api.json"
OFFICIAL_VALIDATION = (
    PROJECT_ROOT / "reference/goldens/mooncake-f161118-official-test-validation.json"
)
GENERATOR = PROJECT_ROOT / "scripts/generate_mooncake_source_api_golden.py"


def _golden() -> dict[str, Any]:
    value = json.loads(GOLDEN.read_bytes())
    assert isinstance(value, dict)
    return value


def _identity() -> KVIdentity:
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash="hash-0",
        token_start=0,
        token_end=16,
        shard_id="tp0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def _master(*, capacities: tuple[int, ...]) -> MasterService:
    service = MasterService(allocation_strategy=RandomAllocationStrategy(seed=7))
    for index, capacity in enumerate(capacities):
        resource_id = f"store-{index}"
        service.mount_segment(
            Segment(
                segment_id=resource_id,
                name=resource_id,
                node_id=f"node-{index}",
                numa_node_id=f"numa:node-{index}:0",
                transport_endpoint=f"tcp://store-{index}",
                capacity_bytes=capacity,
                allocation_alignment_bytes=64,
                allocator_metadata_bytes=8,
            ),
            CapacityLedger(
                resource_id=resource_id,
                resource_kind=CapacityResourceKind.STORE_DRAM,
                capacity_bytes=capacity,
            ),
            timestamp_ns=0,
        )
    return service


def _transfer_metadata(*, total_bytes: int) -> TransferMetadata:
    source = MemoryLocation(
        resource_id="gpu-0.hbm",
        node_id="node-0",
        numa_node_id="numa:node-0:0",
        kind=MemoryKind.GPU_HBM,
        endpoint="rdma://node-0/gpu-0",
        gpu_id="gpu-0",
    )
    destination = MemoryLocation(
        resource_id="store-0.dram",
        node_id="node-1",
        numa_node_id="numa:node-1:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="rdma://node-1/store-0",
    )
    path = TopologyPath(
        path_id="rdma",
        source_kind=MemoryKind.GPU_HBM,
        destination_kind=MemoryKind.STORE_DRAM,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=("gpu.read", "nic", "fabric", "store.write"),
        concurrency_resource_ids=("copy", "qp"),
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id="node-0.hca-0",
        destination_hca_id="node-1.hca-0",
    )
    return TransferMetadata(
        transfer_id="transfer-source-golden",
        object_id="object-0",
        replica_id="replica-0",
        source=source,
        destination=destination,
        opcode=TransferOpcode.WRITE,
        total_bytes=total_bytes,
        cause="BASELINE_STORE_PUT",
        route_version=0,
        ready_ns=10,
        path=path,
    )


def test_checked_in_golden_is_hash_bound_fail_closed_reference() -> None:
    document = _golden()

    assert document["schema"] == "moonkvsim.mooncake-source-api-golden.v1"
    assert document["evidence_class"] == "E1_pinned_source_api_reference_only"
    assert document["formal_use_allowed"] is False
    assert document["provenance"]["commit"] == ("f161118c18dbea1b56dd5c7908b9eaa440353e2e")
    assert document["provenance"]["worktree_files_read"] is False
    assert len(document["provenance"]["files"]) == 27
    assert document["external_runtime_capture"]["status"] == "NOT_CAPTURED"
    assert "communication_timing_or_calibration" in document["claim_exclusions"]


def test_official_test_validation_stays_e2_subset_and_binds_source_golden() -> None:
    document = json.loads(OFFICIAL_VALIDATION.read_bytes())

    assert document["schema"] == "moonkvsim.mooncake-official-test-validation.v1"
    assert document["evidence_class"] == "E2_external_official_unit_execution_subset"
    assert document["formal_use_allowed"] is False
    assert document["provenance"]["worktree_files_copied"] is False
    assert (
        document["provenance"]["source_golden"]["sha256"]
        == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    )
    assert document["validation"]["build"]["dependency_prefix_hash_locked"] is False
    assert document["validation"]["runtime_boundaries"] == {
        "gpu_or_cuda_kernel_executed": False,
        "rdma_device_available": False,
        "test_timing_is_performance_evidence": False,
    }
    selected = document["validation"]["selected_ctest"]
    assert selected["status"] == "PASS"
    assert selected["failed"] == 0
    assert selected["gtest_cases_total"] == 250
    assert selected["gtest_cases_passed"] == 248
    assert selected["gtest_cases_skipped"] == 2
    assert "E3, E4, or E5 evidence" in document["claim_exclusions"]


def test_generator_check_reads_only_pinned_commit_objects() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    report = json.loads(result.stdout)

    assert report["status"] == "checked"
    assert report["source_file_count"] == 27
    assert report["evidence_class"] == "E1_pinned_source_api_reference_only"


def test_generator_is_no_clobber_and_check_detects_byte_drift(tmp_path: Path) -> None:
    output = tmp_path / "golden.json"
    command = [sys.executable, str(GENERATOR), "--output", str(output)]

    subprocess.run(command, check=True, capture_output=True, cwd=PROJECT_ROOT)
    duplicate = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert duplicate.returncode == 2
    assert "refusing to overwrite" in duplicate.stderr

    output.write_bytes(output.read_bytes() + b" ")
    drift = subprocess.run(
        [*command, "--check"],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert drift.returncode == 2
    assert "not byte-identical" in drift.stderr


def test_generator_rejects_a_symlink_output_without_touching_target(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_bytes(b"unchanged\n")
    output = tmp_path / "golden.json"
    output.symlink_to(victim)
    command = [sys.executable, str(GENERATOR), "--output", str(output)]

    create = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert create.returncode == 2
    assert "refusing to overwrite" in create.stderr
    assert victim.read_bytes() == b"unchanged\n"

    check = subprocess.run(
        [*command, "--check"],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert check.returncode == 2
    assert "without following symlinks" in check.stderr
    assert victim.read_bytes() == b"unchanged\n"


def test_source_mapped_master_visibility_and_best_effort_cases() -> None:
    cases = _golden()["moonkvsim_mapping_cases"]
    service = _master(capacities=(1024,))
    identity = _identity()

    ticket = service.put_start(
        identity,
        put_id="put-source-golden",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    actual_steps: list[dict[str, object]] = [
        {"operation": "put_start", "ticket_state": ticket.state.value},
        {
            "operation": "get_replica_list",
            "visible_replica_count": len(service.get_replica_list(identity)),
        },
    ]
    committed = service.put_end(
        ticket.put_id,
        successful_replica_ids=ticket.replica_ids,
        timestamp_ns=2,
    )
    actual_steps.extend(
        [
            {"operation": "put_end", "committed_replica_count": len(committed)},
            {
                "operation": "get_replica_list",
                "visible_replica_count": len(service.get_replica_list(identity)),
            },
            {
                "operation": "remove",
                "removed_replica_count": service.remove(identity, timestamp_ns=3),
            },
            {
                "operation": "get_replica_list",
                "visible_replica_count": len(service.get_replica_list(identity)),
            },
        ]
    )
    assert actual_steps == cases["master_visibility_single_dram"]["steps"]

    best_effort = cases["best_effort_distinct_segments"]
    allocation_service = _master(capacities=(1024, 64, 1024))
    allocation_ticket = allocation_service.put_start(
        identity,
        put_id="put-best-effort-source-golden",
        payload_bytes=100,
        replica_count=best_effort["requested_replicas"],
        timestamp_ns=1,
    )
    resources = {
        allocation_service.allocation_registry.get(allocation_id).resource_id
        for allocation_id in allocation_ticket.allocation_ids
    }
    assert len(allocation_ticket.replica_ids) == best_effort["expected_allocated_replicas"]
    assert len(resources) == best_effort["expected_distinct_segments"]


def test_source_mapped_eviction_sequences_include_fifo_remove_noop() -> None:
    cases = _golden()["moonkvsim_mapping_cases"]

    lru = LRUEvictionStrategy()
    lru.add_key("key1")
    lru.add_key("key2")
    lru_evicted = [lru.evict_key()]
    lru.add_key("key3")
    lru.add_key("key4")
    lru.update_key("key2")
    lru.update_key("key3")
    lru_evicted.append(lru.evict_key())
    assert lru_evicted == cases["lru_eviction"]["expected_evicted_keys"]

    fifo = FIFOEvictionStrategy()
    fifo.add_key("key1")
    fifo.add_key("key2")
    assert fifo.remove_key("key2") is False
    fifo_evicted = [fifo.evict_key()]
    fifo.add_key("key3")
    fifo.add_key("key4")
    fifo.update_key("key2")
    fifo.update_key("key3")
    fifo_evicted.append(fifo.evict_key())
    assert fifo_evicted == cases["fifo_eviction"]["expected_evicted_keys"]


def test_source_mapped_default_slicing_and_success_bytes() -> None:
    case = _golden()["moonkvsim_mapping_cases"]["default_slicing"]
    source = _transfer_metadata(total_bytes=case["payload_bytes"])
    task = TransferTask.create(source)

    assert [item.length_bytes for item in task.slices] == case["expected_slice_lengths"]
    task.start(timestamp_ns=source.ready_ns)
    for index, item in enumerate(tuple(task.slices)):
        task.update_slice(item.post(timestamp_ns=source.ready_ns + 1 + index))
        posted = task.slices[index]
        task.update_slice(
            posted.finish(SliceStatus.SUCCESS, timestamp_ns=source.ready_ns + 10 + index)
        )

    assert task.status is TransferStatus(case["expected_terminal_status"])
    assert task.transferred_bytes == case["expected_transferred_bytes"]
    task.audit()
