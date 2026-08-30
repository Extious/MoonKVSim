from __future__ import annotations

import json

import pytest

from moonkvsim.aegiskv.failure_fence import (
    AegisFailureFence,
    FailureOperation,
    FailureReplica,
    FailureRoute,
    FenceRouteStatus,
    GPUFailureContext,
    OperationDependency,
    ReplicaResidentShard,
)
from moonkvsim.common.hash import canonical_json_bytes, sha256_json


def context() -> GPUFailureContext:
    return GPUFailureContext(
        failure_id="failure-0",
        gpu_id="node-0.gpu-1",
        failed_target_ids=("engine-dp1",),
        failed_hbm_resource_ids=("gpu1.hbm",),
        timestamp_ns=14_641_778_519,
    )


def replica(
    replica_id: str,
    *,
    location: str,
    target_id: str,
    resources: tuple[str, str],
    source_gpu_id: str = "node-0.gpu-0",
) -> FailureReplica:
    return FailureReplica(
        replica_id=replica_id,
        location=location,
        resident_target_id=target_id,
        expected_shard_ids=("tp0", "tp1"),
        shards=(
            ReplicaResidentShard("tp0", f"{replica_id}-a0", resources[0]),
            ReplicaResidentShard("tp1", f"{replica_id}-a1", resources[1]),
        ),
        source_lineage_gpu_id=source_gpu_id,
    )


def test_failure_fences_only_live_route_and_preserves_independent_store() -> None:
    routes = (
        FailureRoute("request-live", 0, "engine-dp1", FenceRouteStatus.ACTIVE, True),
        FailureRoute("request-done", 0, "engine-dp1", FenceRouteStatus.FINISHED, True),
        FailureRoute("request-other", 0, "engine-dp0", FenceRouteStatus.ACTIVE, True),
    )
    peer_failed_target = replica(
        "peer-failed-target",
        location="PEER_HBM",
        target_id="engine-dp1",
        resources=("gpu1.hbm", "gpu2.hbm"),
    )
    # The lineage GPU failed, but residence is healthy.  This replica must not be
    # rejected merely because of its source provenance.
    peer_healthy_residence = replica(
        "peer-healthy-residence",
        location="PEER_HBM",
        target_id="engine-dp0",
        resources=("gpu0.hbm", "gpu3.hbm"),
        source_gpu_id="node-0.gpu-1",
    )
    store = replica(
        "store-independent",
        location="STORE_DRAM",
        target_id="store-pool-0",
        resources=("store0.segment0", "store0.segment1"),
        source_gpu_id="node-0.gpu-1",
    )
    operations = (
        FailureOperation(
            "forward-live",
            OperationDependency.EXECUTOR_ROUTE,
            ("gpu2.compute",),
            "request-live",
            0,
        ),
        FailureOperation(
            "store-independent-transfer",
            OperationDependency.INDEPENDENT_POOL_PATH,
            ("store0.nic",),
            "request-live",
            0,
            "STORE_DRAM",
        ),
        FailureOperation(
            "peer-transfer-on-failed-gpu",
            OperationDependency.INDEPENDENT_POOL_PATH,
            ("gpu1.hbm",),
            "request-other",
            0,
            "PEER_HBM",
        ),
        FailureOperation(
            "finished-route-work",
            OperationDependency.EXECUTOR_ROUTE,
            ("gpu2.compute",),
            "request-done",
            0,
        ),
    )

    plan = AegisFailureFence().plan(
        context(),
        routes=routes,
        replicas=(peer_failed_target, peer_healthy_residence, store),
        operations=operations,
    )

    assert [(route.request_id, route.route_version) for route in plan.fenced_routes] == [
        ("request-live", 0)
    ]
    assert plan.invalidated_peer_replica_ids == ("peer-failed-target",)
    assert plan.physically_lost_allocation_ids == ("peer-failed-target-a0",)
    assert plan.stranded_healthy_allocation_ids == ("peer-failed-target-a1",)
    assert plan.recovery_eligibility_revoked_allocation_ids == (
        "peer-failed-target-a0",
        "peer-failed-target-a1",
    )
    assert plan.preserved_peer_replica_ids == ("peer-healthy-residence",)
    assert plan.preserved_store_replica_ids == ("store-independent",)
    assert plan.canceled_operation_ids == (
        "forward-live",
        "peer-transfer-on-failed-gpu",
    )
    assert plan.preserved_operation_ids == (
        "finished-route-work",
        "store-independent-transfer",
    )
    assert (
        plan.canonical_fields()["eligibility_basis"]
        == "RESIDENT_TARGET_AND_PHYSICAL_RESOURCE_NOT_SOURCE_LINEAGE"
    )


def test_store_record_may_not_be_backed_by_failed_gpu_hbm() -> None:
    malformed_store = replica(
        "bad-store",
        location="STORE_DRAM",
        target_id="store-pool-0",
        resources=("gpu1.hbm", "store0.segment1"),
    )

    with pytest.raises(ValueError, match="Store-DRAM replica"):
        AegisFailureFence().plan(
            context(),
            routes=(),
            replicas=(malformed_store,),
            operations=(),
        )


def test_partial_or_duplicate_replica_shard_bindings_fail_closed() -> None:
    with pytest.raises(ValueError, match="exactly bind"):
        FailureReplica(
            replica_id="partial",
            location="PEER_HBM",
            resident_target_id="engine-dp1",
            expected_shard_ids=("tp0", "tp1"),
            shards=(ReplicaResidentShard("tp0", "a0", "gpu1.hbm"),),
        )


def test_failure_plan_json_and_fingerprint_are_stable() -> None:
    peer = replica(
        "peer",
        location="PEER_HBM",
        target_id="engine-dp1",
        resources=("gpu1.hbm", "gpu2.hbm"),
    )
    left = AegisFailureFence().plan(context(), routes=(), replicas=(peer,), operations=())
    right = AegisFailureFence().plan(context(), routes=(), replicas=(peer,), operations=())

    assert left.to_json_bytes() == right.to_json_bytes()
    document = json.loads(left.to_json_bytes())
    assert left.to_json_bytes() == canonical_json_bytes(document) + b"\n"
    canonical = {key: value for key, value in document.items() if key != "fingerprint"}
    assert document["fingerprint"] == sha256_json(canonical)
