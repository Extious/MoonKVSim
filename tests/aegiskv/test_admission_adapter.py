from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pytest

from moonkvsim.aegiskv.admission_adapter import (
    AdmissionPolicyAdapter,
    AdmissionSignalSource,
)
from moonkvsim.aegiskv.controller import AdmissionPolicy, AllocationQuote
from moonkvsim.aegiskv.kv_directory import ResidencyOutcome
from moonkvsim.aegiskv.rental_value import RentalValueInputs, compute_rental_value
from moonkvsim.aegiskv.slack_landlord import SlackLandlord, StalePreviewError
from moonkvsim.aegiskv.types import (
    AdmissionOutcome,
    PathCommitState,
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
)
from tests.aegiskv._integration_support import (
    PEER_RESOURCE_ID,
    STORE_SEGMENT_ID,
    build_env,
)


class ExactSignalSource(AdmissionSignalSource):
    def __init__(self, benefits: dict[PolicyPool, Fraction]) -> None:
        self.benefits = benefits
        self.chunk_benefits: dict[tuple[PolicyPool, str], Fraction] = {}
        self.candidates: dict[tuple[PolicyPool, str], SealedChunk] = {}
        self.allocation_ids: dict[tuple[PolicyPool, str], str] = {}
        self.latest_calls: list[tuple[PolicyPool, str]] = []

    def remember(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        *,
        allocation_id: str | None = None,
        benefit: Fraction | None = None,
    ) -> None:
        self.candidates[(pool, candidate.chunk_id)] = candidate
        if benefit is not None:
            self.chunk_benefits[(pool, candidate.chunk_id)] = benefit
        if allocation_id is not None:
            self.allocation_ids[(pool, candidate.chunk_id)] = allocation_id

    def candidate_inputs(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        now_ns: int,
        pool_rent: Fraction,
    ) -> RentalValueInputs:
        self.remember(pool, candidate)
        return self._inputs(pool, candidate, now_ns, pool_rent)

    def latest_inputs(
        self,
        pool: PolicyPool,
        chunk_id: str,
        now_ns: int,
        pool_rent: Fraction,
    ) -> RentalValueInputs:
        self.latest_calls.append((pool, chunk_id))
        return self._inputs(
            pool,
            self.candidates[(pool, chunk_id)],
            now_ns,
            pool_rent,
        )

    def allocation_id_for_chunk(self, pool: PolicyPool, chunk_id: str) -> str:
        return self.allocation_ids[(pool, chunk_id)]

    def _inputs(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        now_ns: int,
        pool_rent: Fraction,
    ) -> RentalValueInputs:
        version = now_ns
        return RentalValueInputs(
            candidate=candidate,
            pool=pool,
            signals=RentalSignals(
                slack=SlackSignal(Fraction(0, 1), observed_at_ns=now_ns, version=version),
                hit_probability=Fraction(0, 1),
                reuse_saving=Fraction(0, 1),
                lru_utility=Fraction(0, 1),
                last_access_ns=now_ns,
                versions=SignalVersions(version, version, version, version),
            ),
            recovery_time_before=self.chunk_benefits.get(
                (pool, candidate.chunk_id),
                self.benefits[pool],
            ),
            recovery_time_after=Fraction(0, 1),
            weights=RentalWeights(Fraction(1, 1), Fraction(0, 1), Fraction(0, 1)),
            pool_rent=pool_rent,
            now_ns=now_ns,
        )


@dataclass(slots=True)
class FakeTicket:
    allocation_id: str
    state: PathCommitState = PathCommitState.PENDING


def _adapter(
    *,
    peer_capacity: int,
    store_capacity: int,
    peer_benefit: Fraction,
    store_benefit: Fraction,
) -> tuple[AdmissionPolicyAdapter, ExactSignalSource, SlackLandlord, SlackLandlord]:
    peer = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=peer_capacity)
    store = SlackLandlord(pool=PolicyPool.STORE_DRAM, capacity_bytes=store_capacity)
    source = ExactSignalSource(
        {
            PolicyPool.PEER_HBM: peer_benefit,
            PolicyPool.STORE_DRAM: store_benefit,
        }
    )
    adapter = AdmissionPolicyAdapter(
        landlords={PolicyPool.PEER_HBM: peer, PolicyPool.STORE_DRAM: store},
        signal_source=source,
    )
    policy: AdmissionPolicy = adapter
    assert policy is adapter
    return adapter, source, peer, store


@pytest.mark.parametrize(
    ("peer_outcome", "store_outcome", "expected"),
    [
        (AdmissionOutcome.ADMIT, AdmissionOutcome.BYPASS, ResidencyOutcome.HBM_ONLY),
        (AdmissionOutcome.BYPASS, AdmissionOutcome.ADMIT, ResidencyOutcome.DRAM_ONLY),
        (AdmissionOutcome.ADMIT, AdmissionOutcome.ADMIT, ResidencyOutcome.HBM_AND_DRAM),
        (AdmissionOutcome.BYPASS, AdmissionOutcome.BYPASS, ResidencyOutcome.BYPASS),
    ],
)
def test_controller_four_results_use_quotes_and_keep_physical_truth_owned_elsewhere(
    peer_outcome: AdmissionOutcome,
    store_outcome: AdmissionOutcome,
    expected: ResidencyOutcome,
) -> None:
    env = build_env()
    adapter, source, peer_landlord, store_landlord = _adapter(
        peer_capacity=512,
        store_capacity=512,
        peer_benefit=Fraction(1 if peer_outcome is AdmissionOutcome.ADMIT else 0, 1),
        store_benefit=Fraction(1 if store_outcome is AdmissionOutcome.ADMIT else 0, 1),
    )
    directory = env.directory
    registry = env.registry
    peer_ledger = env.peer_ledger
    store_ledger = env.master.ledgers[STORE_SEGMENT_ID]

    admission = env.controller(adapter).reserve_independently(
        env.production,
        operation_id=f"adapter-matrix:{expected.value}",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )
    peer_binding = adapter.bind_path_admission(admission.peer)
    store_binding = adapter.bind_path_admission(admission.store)

    assert admission.reserved_outcome is expected
    assert source.candidates[(PolicyPool.PEER_HBM, "chunk-0")].allocated_bytes == 256
    assert source.candidates[(PolicyPool.STORE_DRAM, "chunk-0")].allocated_bytes == 128
    assert (peer_binding is not None) == (peer_outcome is AdmissionOutcome.ADMIT)
    assert (store_binding is not None) == (store_outcome is AdmissionOutcome.ADMIT)
    assert adapter.landlord(PolicyPool.PEER_HBM) is peer_landlord
    assert adapter.landlord(PolicyPool.STORE_DRAM) is store_landlord
    assert env.directory is directory and env.registry is registry
    assert env.peer_ledger is peer_ledger
    assert env.master.ledgers[STORE_SEGMENT_ID] is store_ledger
    assert not any(
        hasattr(adapter, name) for name in ("directory", "registry", "ledger", "ledgers")
    )

    if admission.peer.peer_ticket is not None:
        ticket = admission.peer.peer_ticket
        env.peer_pool.commit(ticket, timestamp_ns=1)
        adapter.on_physical_commit(
            PolicyPool.PEER_HBM,
            "chunk-0",
            ticket=ticket,
            now_ns=1,
        )
    if admission.store.store_ticket is not None:
        ticket_store = admission.store.store_ticket
        env.store_pool.commit(ticket_store, timestamp_ns=1)
        adapter.on_physical_commit(
            PolicyPool.STORE_DRAM,
            "chunk-0",
            ticket=ticket_store,
            now_ns=1,
        )
    assert env.directory.residency_outcome(env.identity) is expected


def test_quote_actual_allocated_bytes_is_a_fail_closed_boundary() -> None:
    adapter, _, _, _ = _adapter(
        peer_capacity=8,
        store_capacity=8,
        peer_benefit=Fraction(1, 1),
        store_benefit=Fraction(1, 1),
    )
    quote = AllocationQuote(
        pool=PolicyPool.PEER_HBM,
        resource_id="peer",
        payload_bytes=6,
        allocated_bytes=8,
        allocator_metadata_bytes=1,
        internal_fragmentation_bytes=1,
        alignment_bytes=8,
    )

    with pytest.raises(ValueError, match="actual allocated_bytes"):
        adapter.preview(
            PolicyPool.PEER_HBM,
            SealedChunk("chunk", "request", 0, allocated_bytes=7),
            quote,
            0,
        )


def test_victim_translation_is_lazy_audited_and_bind_enforces_preview_epoch() -> None:
    adapter, source, peer, _ = _adapter(
        peer_capacity=16,
        store_capacity=16,
        peer_benefit=Fraction(32, 1),
        store_benefit=Fraction(1, 1),
    )
    victim = SealedChunk("victim", "victim-request", 0, allocated_bytes=8)
    source.remember(
        PolicyPool.PEER_HBM,
        victim,
        allocation_id="physical-victim",
        benefit=Fraction(8, 1),
    )
    peer.register_committed(
        compute_rental_value(
            source.latest_inputs(PolicyPool.PEER_HBM, "victim", 0, peer.rent)
        )
    )
    candidate = SealedChunk("candidate", "candidate-request", 0, allocated_bytes=16)
    quote = AllocationQuote(
        pool=PolicyPool.PEER_HBM,
        resource_id="peer",
        payload_bytes=14,
        allocated_bytes=16,
        allocator_metadata_bytes=1,
        internal_fragmentation_bytes=1,
        alignment_bytes=8,
    )

    decision = adapter.preview(PolicyPool.PEER_HBM, candidate, quote, 1)

    assert decision.victim_allocation_ids == ("physical-victim",)
    assert "machine_interpretation_pending_manual_review" in decision.reason
    assert source.latest_calls[-1] == (PolicyPool.PEER_HBM, "victim")
    concurrent = SealedChunk("concurrent", "concurrent-request", 0, allocated_bytes=8)
    source.remember(PolicyPool.PEER_HBM, concurrent)
    peer.register_committed(
        compute_rental_value(
            source.latest_inputs(PolicyPool.PEER_HBM, "concurrent", 1, peer.rent)
        )
    )

    with pytest.raises(StalePreviewError, match="epoch"):
        adapter.bind_pending(
            decision.plan_id,
            allocation_id="candidate-allocation",
            ticket=FakeTicket("candidate-allocation"),
        )
    assert adapter.staged_plan_ids == ()
    assert peer.pending_chunk_ids == ()


def test_commit_and_abort_callbacks_are_strictly_tier_local() -> None:
    env = build_env()
    adapter, _, peer_landlord, store_landlord = _adapter(
        peer_capacity=512,
        store_capacity=512,
        peer_benefit=Fraction(1, 1),
        store_benefit=Fraction(1, 1),
    )
    admission = env.controller(adapter).reserve_independently(
        env.production,
        operation_id="adapter-independent-terminal-callbacks",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )
    adapter.bind_path_admission(admission.peer)
    adapter.bind_path_admission(admission.store)
    peer_ticket = admission.peer.peer_ticket
    store_ticket = admission.store.store_ticket
    assert peer_ticket is not None and store_ticket is not None
    assert list(peer_landlord.pending_chunk_ids) == ["chunk-0"]
    assert list(store_landlord.pending_chunk_ids) == ["chunk-0"]

    env.peer_pool.commit(peer_ticket, timestamp_ns=1)
    adapter.on_physical_commit(
        PolicyPool.PEER_HBM,
        "chunk-0",
        ticket=peer_ticket,
        now_ns=1,
    )
    env.store_pool.abort(store_ticket, timestamp_ns=1, reason="INJECTED_STORE_ONLY_FAILURE")
    adapter.on_physical_abort(
        PolicyPool.STORE_DRAM,
        "chunk-0",
        ticket=store_ticket,
    )

    assert list(peer_landlord.heap_chunk_ids) == ["chunk-0"]
    assert not peer_landlord.pending_chunk_ids
    assert not store_landlord.heap_chunk_ids
    assert not store_landlord.pending_chunk_ids
    assert not adapter.inflight_keys
    assert env.directory.residency_outcome(env.identity) is ResidencyOutcome.HBM_ONLY
    env.peer_pool.audit()
    env.store_pool.audit()


def test_physical_reservation_failure_discards_preview_without_policy_pending() -> None:
    env = build_env(peer_capacity=128)
    adapter, _, peer_landlord, _ = _adapter(
        peer_capacity=512,
        store_capacity=512,
        peer_benefit=Fraction(1, 1),
        store_benefit=Fraction(0, 1),
    )

    admission = env.controller(adapter).reserve_independently(
        env.production,
        operation_id="adapter-physical-reserve-failure",
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=0,
    )

    assert admission.peer.error is not None
    assert adapter.bind_path_admission(admission.peer) is None
    assert adapter.bind_path_admission(admission.store) is None
    assert adapter.staged_plan_ids == ()
    assert peer_landlord.pending_chunk_ids == ()
    assert peer_landlord.heap_chunk_ids == ()
