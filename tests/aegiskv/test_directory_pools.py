from __future__ import annotations

import pytest

from moonkvsim.aegiskv.kv_directory import ResidencyOutcome
from moonkvsim.aegiskv.peer_hbm_pool import (
    PEER_COMMITTED_ACCOUNT,
    PEER_PENDING_ACCOUNT,
)
from moonkvsim.aegiskv.types import AdmissionOutcome, PathCommitState
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.simulation.allocation import AllocationRole, AllocationState
from moonkvsim.simulation.allocation_registry import replay_allocation_registry
from moonkvsim.store.master import STORE_COMMITTED_ACCOUNT, STORE_PENDING_ACCOUNT
from tests.aegiskv._integration_support import (
    PEER_RESOURCE_ID,
    SOURCE_ALLOCATION_ID,
    STORE_SEGMENT_ID,
    build_env,
    identity,
    reserve,
)


def test_aegis_facade_reuses_master_directory_and_registry_and_dual_roles_charge_once() -> None:
    env = build_env()

    assert env.directory.directory is env.master.directory
    assert env.directory.allocation_registry is env.master.allocation_registry
    accounts_before = env.source_ledger.accounts
    env.directory.add_roles(
        SOURCE_ALLOCATION_ID,
        (AllocationRole.CACHE_REUSE, AllocationRole.FAILURE_PROTECTION),
        timestamp_ns=0,
        event_id_prefix="test-dual-role",
    )

    allocation = env.registry.get(SOURCE_ALLOCATION_ID)
    assert allocation.roles == {
        AllocationRole.ACTIVE_PRIMARY,
        AllocationRole.CACHE_REUSE,
        AllocationRole.FAILURE_PROTECTION,
    }
    assert env.source_ledger.accounts == accounts_before
    assert env.source_ledger.bytes_in("ACTIVE_PRIMARY") == allocation.allocated_bytes
    env.directory.assert_shared_truth()


def test_peer_and_store_pending_commit_abort_are_independent_shared_truth() -> None:
    env = build_env()
    admission = reserve(
        env,
        operation_id="both",
        peer=AdmissionOutcome.ADMIT,
        store=AdmissionOutcome.ADMIT,
    )
    peer = admission.peer.peer_ticket
    store = admission.store.store_ticket
    assert peer is not None and store is not None

    assert peer.state is store.state is PathCommitState.PENDING
    assert env.directory.residency_outcome(env.identity) is ResidencyOutcome.BYPASS
    assert env.peer_ledger.bytes_in(PEER_PENDING_ACCOUNT) == 256
    assert env.master.ledgers[STORE_SEGMENT_ID].bytes_in(STORE_PENDING_ACCOUNT) == 128

    env.peer_pool.commit(peer, timestamp_ns=1)
    env.store_pool.abort(store, timestamp_ns=1, reason="INJECTED_STORE_PATH_FAILURE")

    assert peer.state is PathCommitState.COMMITTED
    assert store.state is PathCommitState.ABORTED
    assert env.registry.get(peer.allocation_id).state is AllocationState.COMMITTED
    assert env.registry.get(store.allocation_id).state is AllocationState.RELEASED
    assert env.peer_ledger.bytes_in(PEER_COMMITTED_ACCOUNT) == 256
    assert env.master.ledgers[STORE_SEGMENT_ID].bytes_in(STORE_PENDING_ACCOUNT) == 0
    assert env.directory.residency_outcome(env.identity) is ResidencyOutcome.HBM_ONLY
    env.peer_pool.audit()
    env.store_pool.audit()
    assert replay_allocation_registry(env.journal).snapshot_bytes() == env.registry.snapshot_bytes()


def test_ordinary_master_lookup_is_store_location_safe_with_peer_in_same_directory() -> None:
    env = build_env()
    admission = reserve(
        env,
        operation_id="location-safe",
        peer=AdmissionOutcome.ADMIT,
        store=AdmissionOutcome.ADMIT,
    )
    peer = admission.peer.peer_ticket
    store = admission.store.store_ticket
    assert peer is not None and store is not None
    peer_replica = env.peer_pool.commit(peer, timestamp_ns=1)
    store_replica = env.store_pool.commit(store, timestamp_ns=1)

    assert env.master.get_replica_list(env.identity) == (store_replica,)
    replicas = env.directory.replicas(env.identity)
    assert peer_replica in replicas and store_replica in replicas
    assert {replica.location for replica in replicas} == {
        KVLocation.PRIMARY_HBM,
        KVLocation.PEER_HBM,
        KVLocation.STORE_DRAM,
    }


def test_store_aegis_pressure_fails_closed_without_hidden_lru() -> None:
    env = build_env(store_capacity=128)
    first = reserve(
        env,
        operation_id="store-first",
        peer=AdmissionOutcome.BYPASS,
        store=AdmissionOutcome.ADMIT,
    )
    first_ticket = first.store.store_ticket
    assert first_ticket is not None
    env.store_pool.commit(first_ticket, timestamp_ns=1)
    second_identity = identity(stable_block_hash="hash-1", request_id="request-1")

    with pytest.raises(RuntimeError, match="NO_AVAILABLE_HANDLE"):
        env.store_pool.reserve(
            second_identity,
            operation_id="store-second",
            quote=env.store_pool.quote(segment_id=STORE_SEGMENT_ID, payload_bytes=100),
            victim_allocation_ids=(),
            timestamp_ns=2,
        )

    assert env.master.directory.get_replica(first_ticket.replica_id).state is ReplicaState.COMMITTED
    assert env.master.ledgers[STORE_SEGMENT_ID].bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    [pressure] = [
        record
        for record in env.journal.records
        if record.record_type == "MASTER_STORE_CAPACITY_PRESSURE"
    ]
    assert pressure.data["policy"] == "explicit_aegiskv_admission_plan"
    assert pressure.data["candidate_victim_allocation_ids"] == []


def test_peer_pressure_revoke_precedes_atomic_victim_release_and_pending_reserve() -> None:
    env = build_env(peer_capacity=256)
    old = env.peer_pool.reserve(
        env.identity,
        operation_id="peer-old",
        quote=env.peer_pool.quote(resource_id=PEER_RESOURCE_ID, payload_bytes=100),
        timestamp_ns=0,
    )
    env.peer_pool.commit(old, timestamp_ns=1)
    new_identity = identity(stable_block_hash="hash-new", request_id="request-new")
    new = env.peer_pool.reserve(
        new_identity,
        operation_id="peer-new",
        quote=env.peer_pool.quote(resource_id=PEER_RESOURCE_ID, payload_bytes=100),
        victim_allocation_ids=(old.allocation_id,),
        timestamp_ns=2,
    )

    assert env.registry.get(old.allocation_id).state is AllocationState.RELEASED
    assert env.master.directory.get_replica(old.replica_id).state is ReplicaState.EVICTED
    assert not env.registry.overlay(old.allocation_id).recovery_eligible
    assert env.registry.get(new.allocation_id).state is AllocationState.PENDING
    assert env.peer_ledger.bytes_in(PEER_PENDING_ACCOUNT) == 256
    assert env.peer_ledger.bytes_in(PEER_COMMITTED_ACCOUNT) == 0
    env.peer_pool.audit()
    records = list(env.journal.records)
    revoke_index = next(
        index
        for index, record in enumerate(records)
        if record.record_type == "ALLOCATION_RECOVERY_ELIGIBILITY"
        and record.data["allocation_id"] == old.allocation_id
        and record.data["eligible"] is False
    )
    transaction_index = next(
        index
        for index, record in enumerate(records)
        if record.record_type == "RESOURCE_TRANSACTION"
        and record.data["cause"] == "AEGIS_PEER_HBM_EVICT_RESERVE"
    )
    assert revoke_index < transaction_index


def test_store_explicit_replacement_revokes_recovery_before_atomic_transaction() -> None:
    env = build_env(store_capacity=128)
    old_admission = reserve(
        env,
        operation_id="store-old",
        peer=AdmissionOutcome.BYPASS,
        store=AdmissionOutcome.ADMIT,
    )
    old = old_admission.store.store_ticket
    assert old is not None
    env.store_pool.commit(old, timestamp_ns=1)
    new_identity = identity(stable_block_hash="store-new", request_id="store-new")
    new = env.store_pool.reserve(
        new_identity,
        operation_id="store-replace",
        quote=env.store_pool.quote(segment_id=STORE_SEGMENT_ID, payload_bytes=100),
        victim_allocation_ids=(old.allocation_id,),
        timestamp_ns=2,
    )

    assert env.registry.get(old.allocation_id).state is AllocationState.RELEASED
    assert not env.registry.overlay(old.allocation_id).recovery_eligible
    assert env.registry.get(new.allocation_id).state is AllocationState.PENDING
    env.store_pool.audit()
    records = list(env.journal.records)
    revoke_index = next(
        index
        for index, record in enumerate(records)
        if record.record_type == "ALLOCATION_RECOVERY_ELIGIBILITY"
        and record.data["allocation_id"] == old.allocation_id
        and record.data["eligible"] is False
    )
    transaction_index = next(
        index
        for index, record in enumerate(records)
        if record.record_type == "RESOURCE_TRANSACTION"
        and record.data["cause"]
        == "AEGIS_STORE_DRAM_START_CAPACITY_PRESSURE_REPLACEMENT"
    )
    assert revoke_index < transaction_index
