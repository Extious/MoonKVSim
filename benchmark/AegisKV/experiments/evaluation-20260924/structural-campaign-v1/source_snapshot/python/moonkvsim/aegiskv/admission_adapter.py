"""Adapter from controller admission quotes to exact SlackLandlord policy state.

The adapter owns neither a KV directory nor a physical capacity ledger.  It stages an
epoch-bound policy preview, applies it only after a physical pool has returned a PENDING
ticket, and then observes the pool's commit/abort callback.  Its only physical reference is
the minimum in-flight ``chunk_id -> (allocation_id, ticket)`` binding needed to correlate
those callbacks.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from moonkvsim.aegiskv.controller import AdmissionDecision, AllocationQuote, PathAdmission
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.slack_landlord import (
    JOINT_LOSS_REVIEW_STATUS,
    AdmissionPreview,
    PathResolution,
    PendingAdmission,
    SlackLandlord,
)
from moonkvsim.aegiskv.types import (
    AdmissionOutcome,
    PathCommitState,
    PolicyPool,
    SealedChunk,
    require_nonnegative_int,
)


class AdmissionSignalSource(Protocol):
    """Read-only, exact signal boundary implemented by the workflow/cache owners."""

    def candidate_inputs(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        now_ns: int,
        pool_rent: Fraction,
    ) -> RentalValueInputs: ...

    def latest_inputs(
        self,
        pool: PolicyPool,
        chunk_id: str,
        now_ns: int,
        pool_rent: Fraction,
    ) -> RentalValueInputs: ...

    def allocation_id_for_chunk(self, pool: PolicyPool, chunk_id: str) -> str: ...


class PhysicalPathTicket(Protocol):
    """The small common surface of controller-owned Peer-HBM/Store-DRAM tickets."""

    @property
    def allocation_id(self) -> str: ...

    state: PathCommitState


@dataclass(frozen=True, slots=True)
class InFlightBinding:
    """Minimal callback correlation; it is not a directory or allocation registry."""

    pool: PolicyPool
    candidate: SealedChunk
    allocation_id: str
    ticket: PhysicalPathTicket
    pending: PendingAdmission

    def __post_init__(self) -> None:
        if type(self.pool) is not PolicyPool:
            raise TypeError("binding pool must be an exact PolicyPool")
        if type(self.candidate) is not SealedChunk:
            raise TypeError("binding candidate must be an exact SealedChunk")
        if not self.allocation_id:
            raise ValueError("binding allocation_id must be non-empty")
        if self.ticket.allocation_id != self.allocation_id:
            raise ValueError("binding allocation_id must match the physical ticket")
        if self.ticket.state is not PathCommitState.PENDING:
            raise ValueError("a new in-flight binding requires a PENDING physical ticket")
        if self.pending.chunk_id != self.candidate.chunk_id:
            raise ValueError("physical and policy PENDING chunks diverge")

    @property
    def chunk_id(self) -> str:
        return self.candidate.chunk_id

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "allocation_id": self.allocation_id,
            "chunk_id": self.chunk_id,
            "physical_ticket_state": self.ticket.state.value,
            "policy_pending": self.pending.to_canonical_json(),
            "pool": self.pool.value,
        }


@dataclass(frozen=True, slots=True)
class _StagedPlan:
    plan_id: str
    preview: AdmissionPreview
    victim_allocation_ids: tuple[str, ...]

    @property
    def key(self) -> tuple[PolicyPool, str]:
        return (self.preview.pool, self.preview.candidate.chunk_id)


class _LazyLatestValues(Mapping[str, RentalValue]):
    """Key-addressed view that evaluates signals only at landlord-authorized refresh sites."""

    def __init__(
        self,
        *,
        source: AdmissionSignalSource,
        pool: PolicyPool,
        now_ns: int,
        pool_rent: Fraction,
    ) -> None:
        self._source = source
        self._pool = pool
        self._now_ns = now_ns
        self._pool_rent = pool_rent
        self._cache: dict[str, RentalValue] = {}

    def __getitem__(self, chunk_id: str) -> RentalValue:
        try:
            return self._cache[chunk_id]
        except KeyError:
            inputs = self._source.latest_inputs(
                self._pool,
                chunk_id,
                self._now_ns,
                self._pool_rent,
            )
            _validate_inputs(
                inputs,
                pool=self._pool,
                now_ns=self._now_ns,
                pool_rent=self._pool_rent,
                expected_chunk_id=chunk_id,
            )
            value = compute_rental_value(inputs)
            self._cache[chunk_id] = value
            return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)


class SlackLandlordAdmissionPolicy:
    """Concrete implementation of :class:`controller.AdmissionPolicy`.

    There is one referenced SlackLandlord per tier.  The adapter never mirrors their rent,
    suffix index, heap, or PENDING state, and never performs a physical pool operation.
    """

    def __init__(
        self,
        *,
        landlords: Mapping[PolicyPool, SlackLandlord],
        signal_source: AdmissionSignalSource,
    ) -> None:
        if set(landlords) != set(PolicyPool):
            raise ValueError("adapter requires exactly one landlord for each policy pool")
        if any(landlords[pool].pool is not pool for pool in PolicyPool):
            raise ValueError("landlord keys and owned pools must match")
        self._landlords = dict(landlords)
        self._signal_source = signal_source
        self._staged: dict[str, _StagedPlan] = {}
        self._staged_by_chunk: dict[tuple[PolicyPool, str], str] = {}
        self._inflight: dict[tuple[PolicyPool, str], InFlightBinding] = {}
        self._next_plan_sequence = 0

    def landlord(self, pool: PolicyPool) -> SlackLandlord:
        """Return the original policy object, never a copied policy state."""

        return self._landlords[pool]

    @property
    def staged_plan_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._staged))

    @property
    def inflight_keys(self) -> tuple[tuple[PolicyPool, str], ...]:
        return tuple(sorted(self._inflight, key=lambda item: (item[0].value, item[1])))

    def binding(self, pool: PolicyPool, chunk_id: str) -> InFlightBinding:
        try:
            return self._inflight[(pool, chunk_id)]
        except KeyError as error:
            raise KeyError(f"no in-flight {pool.value} binding for chunk {chunk_id}") from error

    def preview(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        allocation_quote: AllocationQuote,
        now_ns: int,
    ) -> AdmissionDecision:
        """Translate an actual-allocation quote into one epoch-bound policy preview."""

        if type(pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(candidate) is not SealedChunk:
            raise TypeError("candidate must be an exact SealedChunk")
        if type(allocation_quote) is not AllocationQuote:
            raise TypeError("allocation_quote must be an exact AllocationQuote")
        require_nonnegative_int(now_ns, "now_ns")
        if allocation_quote.pool is not pool:
            raise ValueError("allocation quote belongs to another policy pool")
        if candidate.allocated_bytes != allocation_quote.allocated_bytes:
            raise ValueError("candidate must use the quote's actual allocated_bytes")
        key = (pool, candidate.chunk_id)
        if key in self._staged_by_chunk or key in self._inflight:
            raise ValueError("chunk already has a staged or in-flight path in this pool")

        landlord = self._landlords[pool]
        inputs = self._signal_source.candidate_inputs(
            pool,
            candidate,
            now_ns,
            landlord.rent,
        )
        _validate_inputs(
            inputs,
            pool=pool,
            now_ns=now_ns,
            pool_rent=landlord.rent,
            expected_candidate=candidate,
        )
        candidate_value = compute_rental_value(inputs)
        preview = landlord.preview(
            candidate_value,
            latest_values=_LazyLatestValues(
                source=self._signal_source,
                pool=pool,
                now_ns=now_ns,
                pool_rent=landlord.rent,
            ),
        )
        plan_id = self._new_plan_id(preview)
        reason = (
            f"SLACK_LANDLORD_{preview.outcome.value}:"
            f"{preview.bypass_reason or 'STRICT_G_AND_H_GATES_PASSED'}:"
            f"{JOINT_LOSS_REVIEW_STATUS}"
        )
        if preview.outcome is AdmissionOutcome.BYPASS:
            return AdmissionDecision(
                outcome=AdmissionOutcome.BYPASS,
                plan_id=plan_id,
                reason=reason,
            )

        victim_allocation_ids = tuple(
            self._allocation_id_for_victim(pool, entry.chunk_id)
            for entry in preview.selected_victims
        )
        if len(set(victim_allocation_ids)) != len(victim_allocation_ids):
            raise ValueError("selected policy victims resolve to duplicate physical allocations")
        staged = _StagedPlan(
            plan_id=plan_id,
            preview=preview,
            victim_allocation_ids=victim_allocation_ids,
        )
        self._staged[plan_id] = staged
        self._staged_by_chunk[key] = plan_id
        return AdmissionDecision(
            outcome=AdmissionOutcome.ADMIT,
            plan_id=plan_id,
            victim_allocation_ids=victim_allocation_ids,
            reason=reason,
        )

    def bind_pending(
        self,
        plan_id: str,
        *,
        allocation_id: str,
        ticket: PhysicalPathTicket,
    ) -> InFlightBinding:
        """Apply a staged plan after its physical pool returned a PENDING ticket."""

        try:
            staged = self._staged[plan_id]
        except KeyError as error:
            raise KeyError(f"unknown or terminal policy plan: {plan_id}") from error
        if not allocation_id or ticket.allocation_id != allocation_id:
            raise ValueError("physical ticket and allocation_id do not match")
        if ticket.state is not PathCommitState.PENDING:
            raise ValueError("bind_pending requires a PENDING physical ticket")

        self._drop_staged(staged)
        pending = self._landlords[staged.preview.pool].apply(staged.preview)
        if pending is None:  # pragma: no cover - an admitted staged plan cannot bypass
            raise RuntimeError("admitted staged plan did not produce policy PENDING state")
        binding = InFlightBinding(
            pool=staged.preview.pool,
            candidate=staged.preview.candidate,
            allocation_id=allocation_id,
            ticket=ticket,
            pending=pending,
        )
        self._inflight[staged.key] = binding
        return binding

    def bind_path_admission(self, path: PathAdmission) -> InFlightBinding | None:
        """Adapt one controller path result without coupling it to the other tier."""

        if path.decision.outcome is AdmissionOutcome.BYPASS:
            return None
        if path.error is not None:
            self.discard_staged(path.decision.plan_id)
            return None
        tickets = tuple(
            ticket for ticket in (path.peer_ticket, path.store_ticket) if ticket is not None
        )
        if len(tickets) != 1:
            raise ValueError("an admitted controller path must contain exactly one ticket")
        ticket = tickets[0]
        staged = self._require_staged(path.decision.plan_id)
        if staged.preview.pool is not path.pool:
            raise ValueError("controller path pool differs from its policy plan")
        return self.bind_pending(
            path.decision.plan_id,
            allocation_id=ticket.allocation_id,
            ticket=ticket,
        )

    def discard_staged(self, plan_id: str) -> None:
        """Discard a preview when its physical reservation never succeeded."""

        staged = self._require_staged(plan_id)
        self._drop_staged(staged)

    def on_physical_commit(
        self,
        pool: PolicyPool,
        chunk_id: str,
        *,
        ticket: PhysicalPathTicket,
        now_ns: int,
    ) -> PathResolution:
        """Observe a physical COMMITTED callback and recompute latest policy value."""

        require_nonnegative_int(now_ns, "now_ns")
        binding = self._require_binding(pool, chunk_id, ticket)
        if ticket.state is not PathCommitState.COMMITTED:
            raise ValueError("policy commit callback requires a COMMITTED physical ticket")
        landlord = self._landlords[pool]
        inputs = self._signal_source.latest_inputs(
            pool,
            chunk_id,
            now_ns,
            landlord.rent,
        )
        _validate_inputs(
            inputs,
            pool=pool,
            now_ns=now_ns,
            pool_rent=landlord.rent,
            expected_candidate=binding.candidate,
        )
        resolution = landlord.complete_pending(chunk_id, latest_inputs=inputs)
        del self._inflight[(pool, chunk_id)]
        return resolution

    def on_physical_abort(
        self,
        pool: PolicyPool,
        chunk_id: str,
        *,
        ticket: PhysicalPathTicket,
    ) -> PathResolution:
        """Observe one physical ABORTED callback without touching the other tier."""

        self._require_binding(pool, chunk_id, ticket)
        if ticket.state is not PathCommitState.ABORTED:
            raise ValueError("policy abort callback requires an ABORTED physical ticket")
        resolution = self._landlords[pool].abort_pending(chunk_id)
        del self._inflight[(pool, chunk_id)]
        return resolution

    def _new_plan_id(self, preview: AdmissionPreview) -> str:
        sequence = self._next_plan_sequence
        self._next_plan_sequence += 1
        return (
            f"slack-landlord:{preview.pool.value}:{preview.candidate.chunk_id}:"
            f"epoch-{preview.base_epoch}:plan-{sequence}"
        )

    def _allocation_id_for_victim(self, pool: PolicyPool, chunk_id: str) -> str:
        allocation_id = self._signal_source.allocation_id_for_chunk(pool, chunk_id)
        if type(allocation_id) is not str or not allocation_id:
            raise ValueError("policy victim must resolve to one physical allocation_id")
        return allocation_id

    def _require_staged(self, plan_id: str) -> _StagedPlan:
        try:
            return self._staged[plan_id]
        except KeyError as error:
            raise KeyError(f"unknown or terminal policy plan: {plan_id}") from error

    def _drop_staged(self, staged: _StagedPlan) -> None:
        del self._staged[staged.plan_id]
        del self._staged_by_chunk[staged.key]

    def _require_binding(
        self,
        pool: PolicyPool,
        chunk_id: str,
        ticket: PhysicalPathTicket,
    ) -> InFlightBinding:
        try:
            binding = self._inflight[(pool, chunk_id)]
        except KeyError as error:
            raise KeyError(f"no in-flight {pool.value} binding for chunk {chunk_id}") from error
        if binding.ticket is not ticket:
            raise ValueError("physical callback supplied a foreign ticket")
        return binding


def _validate_inputs(
    inputs: RentalValueInputs,
    *,
    pool: PolicyPool,
    now_ns: int,
    pool_rent: Fraction,
    expected_candidate: SealedChunk | None = None,
    expected_chunk_id: str | None = None,
) -> None:
    if type(inputs) is not RentalValueInputs:
        raise TypeError("signal source must return exact RentalValueInputs")
    if inputs.pool is not pool:
        raise ValueError("signal source returned inputs for another pool")
    if inputs.now_ns != now_ns:
        raise ValueError("signal source must evaluate at the requested virtual time")
    if inputs.pool_rent != pool_rent:
        raise ValueError("signal source must use the current independent pool rent")
    if expected_candidate is not None and inputs.candidate != expected_candidate:
        raise ValueError("signal source changed the quoted candidate")
    if expected_chunk_id is not None and inputs.candidate.chunk_id != expected_chunk_id:
        raise ValueError("signal source returned another chunk at lazy refresh")


# Concise export for callers that name the boundary after its role rather than its mechanism.
AdmissionPolicyAdapter = SlackLandlordAdmissionPolicy
