from __future__ import annotations

import pytest

from moonkvsim.aegiskv.kv_directory import ResidencyOutcome
from moonkvsim.aegiskv.types import AdmissionOutcome, PolicyPool
from tests.aegiskv._integration_support import (
    PEER_RESOURCE_ID,
    STORE_SEGMENT_ID,
    FixedPolicy,
    build_env,
)


@pytest.mark.parametrize(
    ("peer_decision", "store_decision", "expected"),
    [
        (AdmissionOutcome.ADMIT, AdmissionOutcome.BYPASS, ResidencyOutcome.HBM_ONLY),
        (AdmissionOutcome.BYPASS, AdmissionOutcome.ADMIT, ResidencyOutcome.DRAM_ONLY),
        (
            AdmissionOutcome.ADMIT,
            AdmissionOutcome.ADMIT,
            ResidencyOutcome.HBM_AND_DRAM,
        ),
        (AdmissionOutcome.BYPASS, AdmissionOutcome.BYPASS, ResidencyOutcome.BYPASS),
    ],
)
def test_all_four_residency_outcomes_are_exact_independent_decisions(
    peer_decision: AdmissionOutcome,
    store_decision: AdmissionOutcome,
    expected: ResidencyOutcome,
) -> None:
    env = build_env()
    policy = FixedPolicy(
        {
            PolicyPool.PEER_HBM: peer_decision,
            PolicyPool.STORE_DRAM: store_decision,
        }
    )
    admission = env.controller(policy).reserve_independently(
        env.production,
        operation_id=f"matrix:{expected.value}",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )

    assert admission.reserved_outcome is expected
    assert [call[0] for call in policy.calls] == [PolicyPool.PEER_HBM, PolicyPool.STORE_DRAM]
    assert all(call[1].allocated_bytes == call[2].allocated_bytes for call in policy.calls)
    if admission.peer.peer_ticket is not None:
        env.peer_pool.commit(admission.peer.peer_ticket, timestamp_ns=1)
    if admission.store.store_ticket is not None:
        env.store_pool.commit(admission.store.store_ticket, timestamp_ns=1)
    assert env.directory.residency_outcome(env.identity) is expected


def test_peer_reservation_failure_does_not_mask_or_abort_store_admission() -> None:
    env = build_env(peer_capacity=128)
    policy = FixedPolicy(
        {
            PolicyPool.PEER_HBM: AdmissionOutcome.ADMIT,
            PolicyPool.STORE_DRAM: AdmissionOutcome.ADMIT,
        }
    )
    admission = env.controller(policy).reserve_independently(
        env.production,
        operation_id="peer-pressure-independent",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )

    assert admission.peer.peer_ticket is None
    assert admission.peer.error is not None and "cannot transfer" in admission.peer.error
    assert admission.store.store_ticket is not None
    assert admission.reserved_outcome is ResidencyOutcome.DRAM_ONLY
    env.store_pool.commit(admission.store.store_ticket, timestamp_ns=1)
    assert env.directory.residency_outcome(env.identity) is ResidencyOutcome.DRAM_ONLY


def test_store_reservation_failure_does_not_mask_or_abort_peer_admission() -> None:
    env = build_env(store_capacity=64)
    policy = FixedPolicy(
        {
            PolicyPool.PEER_HBM: AdmissionOutcome.ADMIT,
            PolicyPool.STORE_DRAM: AdmissionOutcome.ADMIT,
        }
    )
    admission = env.controller(policy).reserve_independently(
        env.production,
        operation_id="store-pressure-independent",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )

    assert admission.peer.peer_ticket is not None
    assert admission.store.store_ticket is None
    assert admission.store.error is not None and "NO_AVAILABLE_HANDLE" in admission.store.error
    assert admission.reserved_outcome is ResidencyOutcome.HBM_ONLY
    env.peer_pool.commit(admission.peer.peer_ticket, timestamp_ns=1)
    assert env.directory.residency_outcome(env.identity) is ResidencyOutcome.HBM_ONLY


def test_admission_journal_keeps_both_tier_results_and_source_owned_cause() -> None:
    env = build_env()
    policy = FixedPolicy(
        {
            PolicyPool.PEER_HBM: AdmissionOutcome.ADMIT,
            PolicyPool.STORE_DRAM: AdmissionOutcome.BYPASS,
        }
    )
    env.controller(policy).reserve_independently(
        env.production,
        operation_id="journal",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )

    record = env.journal.records[-1]
    assert record.record_type == "AEGIS_INDEPENDENT_ADMISSION"
    assert record.data["peer_decision"] == "ADMIT"
    assert record.data["store_decision"] == "BYPASS"
    assert record.data["cause"] == "AEGIS_SOURCE_OWNED_INDEPENDENT_ADMISSION"
