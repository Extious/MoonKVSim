"""Exact, GlobalDES-only SlackLandlord admission kernel.

Each instance owns exactly one capacity pool and one independent rent.  It keeps a
two-level index: request-local contiguous chunk sequences, plus a global min-heap
containing only each request's currently releasable tail.  Preview is immutable and
temporary; apply is rejected unless the pool epoch is unchanged.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction

from moonkvsim.aegiskv.lazy_refresh import (
    RefreshResult,
    RefreshTrigger,
    RentalEntry,
    refresh_if_stale,
)
from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta,
    VictimSetHarmDelta,
)
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.types import (
    AdmissionOutcome,
    PathCommitState,
    PolicyPool,
    SealedChunk,
    fraction_to_json,
    require_fraction,
    require_nonnegative_int,
)

JOINT_LOSS_INTERPRETATION = "sum_latest_G_at_each_selection_step"
JOINT_LOSS_REVIEW_STATUS = "machine_interpretation_pending_manual_review"
EXACT_JOINT_LOSS_INTERPRETATION = "recompute_once_per_affected_request_from_tentative_victim_set"
EXACT_JOINT_LOSS_REVIEW_STATUS = "current_design_exact"


class StalePreviewError(RuntimeError):
    """Raised when a preview is applied after its source pool changed."""


class MissingLatestRentalError(RuntimeError):
    """Raised when an authorized lazy-refresh site has no latest exact value."""


class PoolLifecycleAction(StrEnum):
    """Audited mutations outside ordinary candidate admission."""

    EXPLICIT_SUFFIX_RELEASE = "EXPLICIT_SUFFIX_RELEASE"
    CAPACITY_CHANGE = "CAPACITY_CHANGE"
    FAILURE_DOMAIN_INVALIDATE = "FAILURE_DOMAIN_INVALIDATE"
    FAILURE_DOMAIN_RESTORE = "FAILURE_DOMAIN_RESTORE"


@dataclass(frozen=True, slots=True, order=True)
class _HeapItem:
    rental_key: Fraction
    request_id: str
    sequence_index: int
    chunk_id: str
    entry: RentalEntry = field(compare=False)

    @classmethod
    def from_entry(cls, entry: RentalEntry) -> _HeapItem:
        return cls(
            rental_key=entry.value.rental_key,
            request_id=entry.request_id,
            sequence_index=entry.sequence_index,
            chunk_id=entry.chunk_id,
            entry=entry,
        )


@dataclass(frozen=True, slots=True)
class AdmissionPreview:
    """An auditable, non-mutating proposal tied to one pool epoch."""

    pool: PolicyPool
    base_epoch: int
    outcome: AdmissionOutcome
    candidate_value: RentalValue
    threshold: Fraction
    selected_victims: tuple[RentalEntry, ...]
    refresh_checks: tuple[RefreshResult, ...]
    joint_loss: Fraction
    candidate_gain_evidence: AdmissionHarmDelta | None
    joint_loss_evidence: VictimSetHarmDelta | None
    free_bytes_before: int
    free_bytes_after_selection: int
    proposed_rent: Fraction
    bypass_reason: str | None
    excluded_victim_chunk_ids: tuple[str, ...] = ()
    joint_loss_interpretation: str = JOINT_LOSS_INTERPRETATION
    interpretation_review_status: str = JOINT_LOSS_REVIEW_STATUS
    manual_review_confirmed: bool = False

    def __post_init__(self) -> None:
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(self.outcome) is not AdmissionOutcome:
            raise TypeError("outcome must be an exact AdmissionOutcome")
        if type(self.candidate_value) is not RentalValue:
            raise TypeError("candidate_value must be an exact RentalValue")
        if type(self.manual_review_confirmed) is not bool:
            raise TypeError("manual_review_confirmed must be a boolean")
        if (
            self.candidate_gain_evidence is not None
            and type(self.candidate_gain_evidence) is not AdmissionHarmDelta
        ):
            raise TypeError("candidate_gain_evidence must be exact or None")
        if (
            self.joint_loss_evidence is not None
            and type(self.joint_loss_evidence) is not VictimSetHarmDelta
        ):
            raise TypeError("joint_loss_evidence must be exact or None")
        require_nonnegative_int(self.base_epoch, "base_epoch")
        require_fraction(self.threshold, "threshold")
        require_fraction(self.joint_loss, "joint_loss")
        require_fraction(self.proposed_rent, "proposed_rent")
        require_nonnegative_int(self.free_bytes_before, "free_bytes_before")
        require_nonnegative_int(
            self.free_bytes_after_selection,
            "free_bytes_after_selection",
        )
        if self.candidate_value.pool is not self.pool:
            raise ValueError("preview candidate belongs to a different pool")
        if self.threshold != self.candidate_value.rental_key:
            raise ValueError("threshold must equal the candidate rental key")
        exact_mode = self.candidate_gain_evidence is not None
        if exact_mode:
            candidate_gain = self.candidate_gain_evidence
            assert candidate_gain is not None
            if (
                candidate_gain.before.request_id != self.candidate.request_id
                or candidate_gain.before.pool is not self.pool
            ):
                raise ValueError("candidate gain evidence belongs to another candidate")
            if self.candidate_value.composite_benefit != candidate_gain.gain_ns:
                raise ValueError("candidate G must equal exact recovery-harm gain A")
            expected_requests = {entry.request_id for entry in self.selected_victims}
            if expected_requests:
                if self.joint_loss_evidence is None:
                    raise ValueError("exact victim selection requires joint-loss evidence")
                evidence_requests = {
                    item.request_id for item in self.joint_loss_evidence.before_by_request
                }
                if not expected_requests.issubset(evidence_requests):
                    raise ValueError(
                        "joint-loss evidence must cover every selected victim request"
                    )
                if self.candidate.request_id in evidence_requests:
                    raise ValueError(
                        "same-request exclusion forbids candidate harm in victim evidence"
                    )
                if any(
                    item.pool is not self.pool
                    for item in self.joint_loss_evidence.before_by_request
                    + self.joint_loss_evidence.after_by_request
                ):
                    raise ValueError("joint-loss evidence belongs to another pool")
                if self.joint_loss != self.joint_loss_evidence.joint_loss_ns:
                    raise ValueError("joint_loss must equal exact victim-set harm delta")
            elif self.joint_loss_evidence is not None or self.joint_loss != 0:
                raise ValueError("an empty victim set has zero joint loss and no evidence")
        else:
            if self.joint_loss_evidence is not None:
                raise ValueError("legacy preview cannot carry exact joint-loss evidence")
            selected_loss = sum(
                (entry.value.composite_benefit for entry in self.selected_victims),
                start=Fraction(0, 1),
            )
            if self.joint_loss != selected_loss:
                raise ValueError("joint_loss must equal selected victims' latest G values")
        if len({entry.chunk_id for entry in self.selected_victims}) != len(self.selected_victims):
            raise ValueError("selected victims must be unique")
        if len(set(self.excluded_victim_chunk_ids)) != len(
            self.excluded_victim_chunk_ids
        ):
            raise ValueError("excluded victim chunk IDs must be unique")
        if any(
            entry.chunk_id in self.excluded_victim_chunk_ids
            for entry in self.selected_victims
        ):
            raise ValueError("a selected victim is protected by alias exclusion")
        expected_free = self.free_bytes_before + sum(
            entry.allocated_bytes for entry in self.selected_victims
        )
        if self.free_bytes_after_selection != expected_free:
            raise ValueError("free-bytes projection does not match selected actual allocations")
        if self.outcome is AdmissionOutcome.ADMIT and self.bypass_reason is not None:
            raise ValueError("an admitted preview cannot have a bypass reason")
        if self.outcome is AdmissionOutcome.BYPASS and not self.bypass_reason:
            raise ValueError("a bypassed preview must state its reason")
        if self.outcome is AdmissionOutcome.ADMIT:
            if self.free_bytes_after_selection < self.candidate.allocated_bytes:
                raise ValueError("an admitted preview must establish sufficient capacity")
            if any(entry.value.rental_key >= self.threshold for entry in self.selected_victims):
                raise ValueError("admitted victims must satisfy strict H_y < Theta")
            if self.candidate_value.composite_benefit <= self.joint_loss:
                raise ValueError("admission must satisfy strict G_x > D_Y")
            expected_rent = max(
                (entry.value.rental_key for entry in self.selected_victims),
                default=self.candidate_value.pool_rent,
            )
            expected_rent = max(self.candidate_value.pool_rent, expected_rent)
            if self.proposed_rent != expected_rent:
                raise ValueError("proposed rent does not match the selected victim keys")
        elif self.proposed_rent != self.candidate_value.pool_rent:
            raise ValueError("a bypassed preview cannot change pool rent")
        expected_interpretation = (
            EXACT_JOINT_LOSS_INTERPRETATION if exact_mode else JOINT_LOSS_INTERPRETATION
        )
        expected_review_status = (
            EXACT_JOINT_LOSS_REVIEW_STATUS if exact_mode else JOINT_LOSS_REVIEW_STATUS
        )
        if self.joint_loss_interpretation != expected_interpretation:
            raise ValueError("unsupported joint-loss interpretation")
        if self.interpretation_review_status != expected_review_status:
            raise ValueError("joint-loss interpretation review status is inconsistent")
        if self.manual_review_confirmed:
            raise ValueError("this machine interpretation must not claim manual confirmation")

    @property
    def candidate(self) -> SealedChunk:
        """The sealed candidate, without duplicating it in the preview."""

        return self.candidate_value.candidate

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "base_epoch": self.base_epoch,
            "bypass_reason": self.bypass_reason,
            "excluded_victim_chunk_ids": list(self.excluded_victim_chunk_ids),
            "candidate_value": self.candidate_value.to_canonical_json(),
            "candidate_gain_evidence": (
                None
                if self.candidate_gain_evidence is None
                else self.candidate_gain_evidence.to_canonical_json()
            ),
            "free_bytes_after_selection": self.free_bytes_after_selection,
            "free_bytes_before": self.free_bytes_before,
            "joint_loss_D_Y": fraction_to_json(self.joint_loss),
            "joint_loss_evidence": (
                None
                if self.joint_loss_evidence is None
                else self.joint_loss_evidence.to_canonical_json()
            ),
            "joint_loss_interpretation": self.joint_loss_interpretation,
            "joint_loss_manual_review_confirmed": self.manual_review_confirmed,
            "joint_loss_review_status": self.interpretation_review_status,
            "outcome": self.outcome.value,
            "pool": self.pool.value,
            "proposed_rent": fraction_to_json(self.proposed_rent),
            "refresh_checks": [item.to_canonical_json() for item in self.refresh_checks],
            "selected_victims": [item.to_canonical_json() for item in self.selected_victims],
            "threshold_Theta": fraction_to_json(self.threshold),
        }


@dataclass(frozen=True, slots=True)
class PendingAdmission:
    """Reserved capacity that is deliberately absent from the eviction heap."""

    value_at_admission: RentalValue
    applied_epoch: int
    state: PathCommitState = PathCommitState.PENDING

    def __post_init__(self) -> None:
        if type(self.value_at_admission) is not RentalValue:
            raise TypeError("value_at_admission must be an exact RentalValue")
        require_nonnegative_int(self.applied_epoch, "applied_epoch")
        if self.state is not PathCommitState.PENDING:
            raise ValueError("PendingAdmission state must be PENDING")

    @property
    def chunk_id(self) -> str:
        return self.value_at_admission.candidate.chunk_id

    @property
    def request_id(self) -> str:
        return self.value_at_admission.candidate.request_id

    @property
    def allocated_bytes(self) -> int:
        return self.value_at_admission.actual_allocated_bytes

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "applied_epoch": self.applied_epoch,
            "state": self.state.value,
            "value_at_admission": self.value_at_admission.to_canonical_json(),
        }


@dataclass(frozen=True, slots=True)
class PathResolution:
    """Result of completing or aborting one pending allocation."""

    chunk_id: str
    state: PathCommitState
    epoch: int
    latest_value: RentalValue | None

    def __post_init__(self) -> None:
        if type(self.state) is not PathCommitState:
            raise TypeError("state must be an exact PathCommitState")
        if self.latest_value is not None and type(self.latest_value) is not RentalValue:
            raise TypeError("latest_value must be an exact RentalValue or None")
        require_nonnegative_int(self.epoch, "epoch")
        if self.state is PathCommitState.PENDING:
            raise ValueError("a resolved path cannot remain PENDING")
        if (self.state is PathCommitState.COMMITTED) != (self.latest_value is not None):
            raise ValueError("only COMMITTED resolution carries the latest rental value")

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "epoch": self.epoch,
            "latest_value": (
                None if self.latest_value is None else self.latest_value.to_canonical_json()
            ),
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class CapacityChangePreview:
    """Epoch-bound safe-tail plan for one serialized quota update.

    Capacity growth has an empty victim set.  Capacity contraction may select
    only the currently exposed request tails, exposing one predecessor at a
    time.  PENDING chunks are never selected: their owning transfer must abort
    before a quota smaller than the pending footprint can be installed.
    """

    pool: PolicyPool
    base_epoch: int
    available: bool
    capacity_bytes_before: int
    capacity_bytes_after: int
    committed_bytes_before: int
    pending_bytes_before: int
    rent_before: Fraction
    proposed_rent: Fraction
    selected_victims: tuple[RentalEntry, ...]
    refresh_checks: tuple[RefreshResult, ...]

    def __post_init__(self) -> None:
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(self.available) is not bool:
            raise TypeError("available must be a boolean")
        for name, value in (
            ("base_epoch", self.base_epoch),
            ("capacity_bytes_before", self.capacity_bytes_before),
            ("capacity_bytes_after", self.capacity_bytes_after),
            ("committed_bytes_before", self.committed_bytes_before),
            ("pending_bytes_before", self.pending_bytes_before),
        ):
            require_nonnegative_int(value, name)
        require_fraction(self.rent_before, "rent_before")
        require_fraction(self.proposed_rent, "proposed_rent")
        if self.proposed_rent < self.rent_before:
            raise ValueError("capacity change cannot decrease accumulated rent")
        if len({entry.chunk_id for entry in self.selected_victims}) != len(self.selected_victims):
            raise ValueError("capacity victims must be unique")
        required_release = max(
            0,
            self.committed_bytes_before + self.pending_bytes_before - self.capacity_bytes_after,
        )
        released_bytes = sum(entry.allocated_bytes for entry in self.selected_victims)
        if released_bytes < required_release:
            raise ValueError("capacity victims do not establish the new quota")
        if self.selected_victims and (
            released_bytes - self.selected_victims[-1].allocated_bytes >= required_release
        ):
            raise ValueError("capacity victim plan selected an unnecessary final tail")
        expected_rent = max(
            (entry.value.rental_key for entry in self.selected_victims),
            default=self.rent_before,
        )
        if self.proposed_rent != max(self.rent_before, expected_rent):
            raise ValueError("capacity change rent does not match selected tail keys")

    @property
    def released_bytes(self) -> int:
        return sum(entry.allocated_bytes for entry in self.selected_victims)

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "available": self.available,
            "base_epoch": self.base_epoch,
            "capacity_bytes_after": self.capacity_bytes_after,
            "capacity_bytes_before": self.capacity_bytes_before,
            "committed_bytes_before": self.committed_bytes_before,
            "pending_bytes_before": self.pending_bytes_before,
            "pool": self.pool.value,
            "proposed_rent": fraction_to_json(self.proposed_rent),
            "refresh_checks": [item.to_canonical_json() for item in self.refresh_checks],
            "released_bytes": self.released_bytes,
            "rent_before": fraction_to_json(self.rent_before),
            "selected_victims": [item.to_canonical_json() for item in self.selected_victims],
        }


@dataclass(frozen=True, slots=True)
class PoolLifecycleResolution:
    """Canonical audit record for a completed pool lifecycle mutation."""

    pool: PolicyPool
    action: PoolLifecycleAction
    cause: str
    epoch: int
    available_before: bool
    available_after: bool
    capacity_bytes_before: int
    capacity_bytes_after: int
    rent_before: Fraction
    rent_after: Fraction
    released_entries: tuple[RentalEntry, ...] = ()
    aborted_pending: tuple[PendingAdmission, ...] = ()
    refresh_checks: tuple[RefreshResult, ...] = ()

    def __post_init__(self) -> None:
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(self.action) is not PoolLifecycleAction:
            raise TypeError("action must be an exact PoolLifecycleAction")
        if type(self.cause) is not str or not self.cause:
            raise ValueError("lifecycle cause must be a non-empty string")
        if type(self.available_before) is not bool or type(self.available_after) is not bool:
            raise TypeError("lifecycle availability fields must be booleans")
        require_nonnegative_int(self.epoch, "epoch")
        require_nonnegative_int(self.capacity_bytes_before, "capacity_bytes_before")
        require_nonnegative_int(self.capacity_bytes_after, "capacity_bytes_after")
        require_fraction(self.rent_before, "rent_before")
        require_fraction(self.rent_after, "rent_after")
        if self.rent_after < self.rent_before:
            raise ValueError("a lifecycle mutation cannot refund accumulated rent")
        if len({entry.chunk_id for entry in self.released_entries}) != len(self.released_entries):
            raise ValueError("released lifecycle entries must be unique")
        if len({item.chunk_id for item in self.aborted_pending}) != len(self.aborted_pending):
            raise ValueError("aborted lifecycle pending entries must be unique")

    @property
    def released_bytes(self) -> int:
        return sum(entry.allocated_bytes for entry in self.released_entries)

    @property
    def aborted_pending_bytes(self) -> int:
        return sum(item.allocated_bytes for item in self.aborted_pending)

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "aborted_pending": [item.to_canonical_json() for item in self.aborted_pending],
            "aborted_pending_bytes": self.aborted_pending_bytes,
            "action": self.action.value,
            "available_after": self.available_after,
            "available_before": self.available_before,
            "capacity_bytes_after": self.capacity_bytes_after,
            "capacity_bytes_before": self.capacity_bytes_before,
            "cause": self.cause,
            "epoch": self.epoch,
            "pool": self.pool.value,
            "refresh_checks": [item.to_canonical_json() for item in self.refresh_checks],
            "released_bytes": self.released_bytes,
            "released_entries": [item.to_canonical_json() for item in self.released_entries],
            "rent_after": fraction_to_json(self.rent_after),
            "rent_before": fraction_to_json(self.rent_before),
        }


class SlackLandlord:
    """One independent exact-rent policy instance for one physical capacity pool."""

    def __init__(
        self,
        *,
        pool: PolicyPool,
        capacity_bytes: int,
        initial_rent: Fraction = Fraction(0, 1),
    ) -> None:
        if type(pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(capacity_bytes, "capacity_bytes")
        require_fraction(initial_rent, "initial_rent")
        self._pool = pool
        self._capacity_bytes = capacity_bytes
        self._rent = initial_rent
        self._epoch = 0
        self._available = True
        self._by_request: dict[str, list[RentalEntry]] = {}
        self._pending: dict[str, PendingAdmission] = {}
        self._heap: list[_HeapItem] = []
        self._known_chunk_ids: set[str] = set()
        self._committed_bytes = 0
        self._pending_bytes = 0

    @property
    def pool(self) -> PolicyPool:
        return self._pool

    @property
    def capacity_bytes(self) -> int:
        return self._capacity_bytes

    @property
    def rent(self) -> Fraction:
        return self._rent

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def available(self) -> bool:
        return self._available

    @property
    def committed_bytes(self) -> int:
        return self._committed_bytes

    @property
    def pending_bytes(self) -> int:
        return self._pending_bytes

    @property
    def free_bytes(self) -> int:
        if not self.available:
            return 0
        return self.capacity_bytes - self.committed_bytes - self.pending_bytes

    @property
    def heap_chunk_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.chunk_id for item in self._heap))

    @property
    def pending_chunk_ids(self) -> tuple[str, ...]:
        return tuple(
            item.chunk_id
            for item in sorted(
                self._pending.values(),
                key=lambda pending: (
                    pending.request_id,
                    pending.value_at_admission.candidate.sequence_index,
                    pending.chunk_id,
                ),
            )
        )

    def committed_entries(self, request_id: str) -> tuple[RentalEntry, ...]:
        return tuple(self._by_request.get(request_id, ()))

    def register_committed(self, value: RentalValue) -> RentalEntry:
        """Seed an already committed chunk while enforcing contiguous suffix safety."""

        if not self.available:
            raise RuntimeError("an unavailable failure domain cannot register committed KV")
        self._validate_current_value(value)
        candidate = value.candidate
        self._validate_new_chunk(candidate.chunk_id)
        if self._pending_for_request(candidate.request_id):
            raise ValueError("cannot seed a committed chunk beyond a PENDING frontier")
        if candidate.allocated_bytes > self.free_bytes:
            raise ValueError("committed chunk exceeds pool capacity")
        entries = self._by_request.get(candidate.request_id)
        current_length = 0 if entries is None else len(entries)
        if candidate.sequence_index != current_length:
            raise ValueError("request-local chunk indices must be contiguous from zero")
        if entries is None:
            entries = []
            self._by_request[candidate.request_id] = entries
        entry = RentalEntry(value)
        entries.append(entry)
        self._committed_bytes += entry.allocated_bytes
        self._known_chunk_ids.add(candidate.chunk_id)
        self._epoch += 1
        self._rebuild_heap()
        return entry

    def preview(
        self,
        candidate_value: RentalValue,
        *,
        latest_values: Mapping[str, RentalValue],
        candidate_gain_evidence: AdmissionHarmDelta | None = None,
        joint_loss_provider: (
            Callable[[tuple[RentalEntry, ...]], VictimSetHarmDelta] | None
        ) = None,
        excluded_victim_chunk_ids: frozenset[str] = frozenset(),
    ) -> AdmissionPreview:
        """Build a temporary admission/eviction view without mutating pool state."""

        self._validate_current_value(candidate_value)
        candidate = candidate_value.candidate
        self._validate_new_chunk(candidate.chunk_id)
        if joint_loss_provider is not None and candidate_gain_evidence is None:
            raise ValueError("exact joint-loss provider requires candidate gain evidence")
        if any(type(chunk_id) is not str or not chunk_id for chunk_id in excluded_victim_chunk_ids):
            raise ValueError("excluded victim chunk IDs must be non-empty strings")
        expected_index = self._next_sequence_index(candidate.request_id)
        if candidate.sequence_index != expected_index:
            raise ValueError("candidate must extend its request's committed-plus-pending tail")

        if not self.available:
            return AdmissionPreview(
                pool=self.pool,
                base_epoch=self.epoch,
                outcome=AdmissionOutcome.BYPASS,
                candidate_value=candidate_value,
                threshold=candidate_value.rental_key,
                selected_victims=(),
                refresh_checks=(),
                joint_loss=Fraction(0, 1),
                candidate_gain_evidence=candidate_gain_evidence,
                joint_loss_evidence=None,
                free_bytes_before=0,
                free_bytes_after_selection=0,
                proposed_rent=self.rent,
                bypass_reason="FAILURE_DOMAIN_UNAVAILABLE",
                excluded_victim_chunk_ids=tuple(sorted(excluded_victim_chunk_ids)),
                joint_loss_interpretation=(
                    EXACT_JOINT_LOSS_INTERPRETATION
                    if candidate_gain_evidence is not None
                    else JOINT_LOSS_INTERPRETATION
                ),
                interpretation_review_status=(
                    EXACT_JOINT_LOSS_REVIEW_STATUS
                    if candidate_gain_evidence is not None
                    else JOINT_LOSS_REVIEW_STATUS
                ),
            )

        view = list(self._heap)
        heapq.heapify(view)
        free_before = self.free_bytes
        free_after = free_before
        selected: list[RentalEntry] = []
        refresh_checks: list[RefreshResult] = []
        threshold = candidate_value.rental_key
        bypass_reason: str | None = None

        while free_after < candidate.allocated_bytes:
            selected_entry: RentalEntry | None = None
            while view:
                top = heapq.heappop(view).entry
                if (
                    top.request_id == candidate.request_id
                    or top.chunk_id in excluded_victim_chunk_ids
                ):
                    # The candidate request is protected as a whole during this preview.
                    continue
                refreshed = self._refresh_from_mapping(
                    top,
                    latest_values,
                    trigger=RefreshTrigger.HEAP_TOP,
                )
                refresh_checks.append(refreshed)
                if refreshed.refreshed:
                    heapq.heappush(view, _HeapItem.from_entry(refreshed.after))
                    continue
                selected_entry = refreshed.after
                break

            if selected_entry is None:
                bypass_reason = "INSUFFICIENT_CAPACITY_OR_NO_LEGAL_VICTIM"
                break
            # Strict patent boundary: equality is not evictable.
            if selected_entry.value.rental_key >= threshold:
                bypass_reason = "VICTIM_KEY_NOT_STRICTLY_BELOW_THRESHOLD"
                break

            selected.append(selected_entry)
            free_after += selected_entry.allocated_bytes
            predecessor = self._predecessor(selected_entry)
            if predecessor is not None:
                refreshed = self._refresh_from_mapping(
                    predecessor,
                    latest_values,
                    trigger=RefreshTrigger.NEWLY_EXPOSED,
                )
                refresh_checks.append(refreshed)
                heapq.heappush(view, _HeapItem.from_entry(refreshed.after))

        joint_loss_evidence: VictimSetHarmDelta | None = None
        if selected and candidate_gain_evidence is not None:
            if joint_loss_provider is None:
                raise ValueError("exact victim selection requires a joint-loss provider")
            joint_loss_evidence = joint_loss_provider(tuple(selected))
            joint_loss = joint_loss_evidence.joint_loss_ns
        else:
            joint_loss = sum(
                (entry.value.composite_benefit for entry in selected),
                start=Fraction(0, 1),
            )
        if bypass_reason is None and candidate_value.composite_benefit <= joint_loss:
            # This also rejects zero-benefit candidates when the pool is idle.
            bypass_reason = "CANDIDATE_G_NOT_STRICTLY_ABOVE_JOINT_LOSS"

        if bypass_reason is None:
            outcome = AdmissionOutcome.ADMIT
            proposed_rent = max(
                (entry.value.rental_key for entry in selected),
                default=self.rent,
            )
            proposed_rent = max(self.rent, proposed_rent)
        else:
            outcome = AdmissionOutcome.BYPASS
            proposed_rent = self.rent

        return AdmissionPreview(
            pool=self.pool,
            base_epoch=self.epoch,
            outcome=outcome,
            candidate_value=candidate_value,
            threshold=threshold,
            selected_victims=tuple(selected),
            refresh_checks=tuple(refresh_checks),
            joint_loss=joint_loss,
            candidate_gain_evidence=candidate_gain_evidence,
            joint_loss_evidence=joint_loss_evidence,
            free_bytes_before=free_before,
            free_bytes_after_selection=free_after,
            proposed_rent=proposed_rent,
            bypass_reason=bypass_reason,
            excluded_victim_chunk_ids=tuple(sorted(excluded_victim_chunk_ids)),
            joint_loss_interpretation=(
                EXACT_JOINT_LOSS_INTERPRETATION
                if candidate_gain_evidence is not None
                else JOINT_LOSS_INTERPRETATION
            ),
            interpretation_review_status=(
                EXACT_JOINT_LOSS_REVIEW_STATUS
                if candidate_gain_evidence is not None
                else JOINT_LOSS_REVIEW_STATUS
            ),
        )

    def apply(self, preview: AdmissionPreview) -> PendingAdmission | None:
        """Atomically apply one still-current preview and reserve a PENDING chunk."""

        if preview.pool is not self.pool:
            raise ValueError("preview belongs to a different capacity pool")
        if preview.base_epoch != self.epoch:
            raise StalePreviewError("pool epoch changed after preview")
        if preview.outcome is AdmissionOutcome.BYPASS:
            return None
        self._validate_current_value(preview.candidate_value)
        self._validate_new_chunk(preview.candidate.chunk_id)
        if preview.free_bytes_before != self.free_bytes:
            raise StalePreviewError("preview free capacity does not match the current pool")
        expected_candidate_index = self._next_sequence_index(
            preview.candidate.request_id
        )
        if preview.candidate.sequence_index != expected_candidate_index:
            raise StalePreviewError(
                "candidate no longer extends its request's committed-plus-pending tail"
            )

        # Revalidate the exact request-local tails before performing any mutation.
        staged_lengths: dict[str, int] = {
            request_id: len(entries) for request_id, entries in self._by_request.items()
        }
        for victim in preview.selected_victims:
            expected = staged_lengths.get(victim.request_id, 0) - 1
            if expected < 0:
                raise StalePreviewError("preview victim request no longer exists")
            current = self._by_request[victim.request_id][expected]
            if current.value.candidate != victim.value.candidate:
                raise StalePreviewError("preview victim is no longer a request tail")
            staged_lengths[victim.request_id] = expected

        resulting_free = self.free_bytes + sum(
            victim.allocated_bytes for victim in preview.selected_victims
        )
        if resulting_free < preview.candidate.allocated_bytes:
            raise StalePreviewError("preview no longer establishes sufficient capacity")

        selected_ids = {entry.chunk_id for entry in preview.selected_victims}
        refresh_updates: dict[tuple[str, int], RentalEntry] = {}
        for refresh in preview.refresh_checks:
            if not refresh.refreshed or refresh.after.chunk_id in selected_ids:
                continue
            resulting_length = staged_lengths.get(refresh.after.request_id, 0)
            if refresh.after.sequence_index >= resulting_length:
                raise StalePreviewError("refreshed survivor is absent from projected state")
            current = self._by_request[refresh.after.request_id][refresh.after.sequence_index]
            if current.value.candidate != refresh.after.value.candidate:
                raise StalePreviewError("refreshed entry no longer matches the request index")
            key = (refresh.after.request_id, refresh.after.sequence_index)
            previous = refresh_updates.get(key)
            if previous is not None and previous != refresh.after:
                raise StalePreviewError("preview contains conflicting refreshed values")
            refresh_updates[key] = refresh.after

        for victim in preview.selected_victims:
            entries = self._by_request[victim.request_id]
            removed = entries.pop()
            if removed.chunk_id != victim.chunk_id:  # pragma: no cover - guarded above
                raise AssertionError("tail revalidation and removal diverged")
            if not entries:
                del self._by_request[victim.request_id]
        self._committed_bytes -= sum(
            victim.allocated_bytes for victim in preview.selected_victims
        )

        # Persist authorized refreshed values for surviving committed chunks only.
        for (request_id, sequence_index), refreshed_entry in refresh_updates.items():
            self._by_request[request_id][sequence_index] = refreshed_entry

        self._rent = preview.proposed_rent
        self._epoch += 1
        pending = PendingAdmission(
            value_at_admission=preview.candidate_value,
            applied_epoch=self.epoch,
        )
        self._pending[pending.chunk_id] = pending
        self._pending_bytes += pending.allocated_bytes
        self._known_chunk_ids.add(pending.chunk_id)
        self._rebuild_heap()
        return pending

    def complete_pending(
        self,
        chunk_id: str,
        *,
        latest_inputs: RentalValueInputs,
    ) -> PathResolution:
        """Recompute from latest exact signals, then commit the completed path."""

        return self.complete_pending_value(
            chunk_id,
            latest_value=compute_rental_value(latest_inputs),
        )

    def complete_pending_value(
        self,
        chunk_id: str,
        *,
        latest_value: RentalValue,
    ) -> PathResolution:
        """Commit one path using a value recomputed by the exact signal owner."""

        pending = self._pending.get(chunk_id)
        if pending is None:
            raise KeyError(f"unknown pending chunk: {chunk_id}")
        if type(latest_value) is not RentalValue:
            raise TypeError("latest_value must be an exact RentalValue")
        pending.value_at_admission._require_same_identity(latest_value)
        self._validate_current_value(latest_value)
        if latest_value.evaluated_at_ns < pending.value_at_admission.evaluated_at_ns:
            raise ValueError("completion value cannot predate admission")
        if not latest_value.signal_versions.is_at_least(pending.value_at_admission.signal_versions):
            raise ValueError("completion cannot regress any signal version")
        candidate = latest_value.candidate
        entries = self._by_request.get(candidate.request_id)
        current_length = 0 if entries is None else len(entries)
        request_pending = self._pending_for_request(candidate.request_id)
        if not request_pending or request_pending[0].chunk_id != chunk_id:
            raise ValueError("completion must commit the earliest PENDING sequence")
        if candidate.sequence_index != current_length:
            raise ValueError("completion must extend the latest contiguous request tail")
        if entries is None:
            entries = []
            self._by_request[candidate.request_id] = entries
        del self._pending[chunk_id]
        self._pending_bytes -= pending.allocated_bytes
        committed = RentalEntry(latest_value)
        entries.append(committed)
        self._committed_bytes += committed.allocated_bytes
        self._epoch += 1
        self._rebuild_heap()
        return PathResolution(
            chunk_id=chunk_id,
            state=PathCommitState.COMMITTED,
            epoch=self.epoch,
            latest_value=latest_value,
        )

    def abort_pending(self, chunk_id: str) -> PathResolution:
        pending = self._pending.get(chunk_id)
        if pending is None:
            raise KeyError(f"unknown pending chunk: {chunk_id}")
        request_pending = self._pending_for_request(pending.request_id)
        if request_pending[-1].chunk_id != chunk_id:
            raise ValueError("abort must remove the latest PENDING suffix tail")
        del self._pending[chunk_id]
        self._pending_bytes -= pending.allocated_bytes
        self._epoch += 1
        self._rebuild_heap()
        return PathResolution(
            chunk_id=chunk_id,
            state=PathCommitState.ABORTED,
            epoch=self.epoch,
            latest_value=None,
        )

    def release_committed_suffix(
        self,
        request_id: str,
        chunk_ids: tuple[str, ...],
        *,
        cause: str,
    ) -> PoolLifecycleResolution:
        """Release exactly one committed request suffix without changing rent.

        This is for explicit lifecycle removal such as request completion or a
        role transition whose physical owner moves elsewhere.  It is not an
        admission eviction and therefore does not charge new rent.  Historical
        chunk IDs remain known, preventing repair/release from reissuing their
        original credit under the same identity.
        """

        self._require_cause(cause)
        if type(request_id) is not str or not request_id:
            raise ValueError("request_id must be a non-empty string")
        if type(chunk_ids) is not tuple or not chunk_ids:
            raise ValueError("chunk_ids must be a non-empty tuple")
        if len(set(chunk_ids)) != len(chunk_ids) or any(
            type(chunk_id) is not str or not chunk_id for chunk_id in chunk_ids
        ):
            raise ValueError("released chunk IDs must be unique non-empty strings")
        if any(item.request_id == request_id for item in self._pending.values()):
            raise ValueError("cannot release a committed suffix while its request is pending")
        entries = self._by_request.get(request_id)
        if entries is None or len(chunk_ids) > len(entries):
            raise ValueError("released chunks are not a committed request suffix")
        suffix = tuple(entries[-len(chunk_ids) :])
        if tuple(entry.chunk_id for entry in suffix) != chunk_ids:
            raise ValueError("released chunks must exactly match the current committed suffix")

        capacity_before = self.capacity_bytes
        rent_before = self.rent
        available_before = self.available
        del entries[-len(chunk_ids) :]
        self._committed_bytes -= sum(entry.allocated_bytes for entry in suffix)
        if not entries:
            del self._by_request[request_id]
        self._epoch += 1
        self._rebuild_heap()
        return PoolLifecycleResolution(
            pool=self.pool,
            action=PoolLifecycleAction.EXPLICIT_SUFFIX_RELEASE,
            cause=cause,
            epoch=self.epoch,
            available_before=available_before,
            available_after=self.available,
            capacity_bytes_before=capacity_before,
            capacity_bytes_after=self.capacity_bytes,
            rent_before=rent_before,
            rent_after=self.rent,
            released_entries=suffix,
        )

    def preview_capacity_change(
        self,
        capacity_bytes: int,
        *,
        latest_values: Mapping[str, RentalValue],
        excluded_chunk_ids: frozenset[str] = frozenset(),
    ) -> CapacityChangePreview:
        """Plan a quota change using only successively exposed safe tails."""

        require_nonnegative_int(capacity_bytes, "capacity_bytes")
        if capacity_bytes < self.pending_bytes:
            raise ValueError("new capacity is below PENDING bytes; abort pending paths first")

        required_release = max(
            0,
            self.committed_bytes + self.pending_bytes - capacity_bytes,
        )
        view = list(self._heap)
        heapq.heapify(view)
        selected: list[RentalEntry] = []
        refresh_checks: list[RefreshResult] = []
        released_bytes = 0
        while released_bytes < required_release:
            selected_entry: RentalEntry | None = None
            while view:
                top = heapq.heappop(view).entry
                if top.chunk_id in excluded_chunk_ids:
                    # A pinned tail also prevents exposing its predecessors.
                    continue
                refreshed = self._refresh_from_mapping(
                    top,
                    latest_values,
                    trigger=RefreshTrigger.HEAP_TOP,
                )
                refresh_checks.append(refreshed)
                if refreshed.refreshed:
                    heapq.heappush(view, _HeapItem.from_entry(refreshed.after))
                    continue
                selected_entry = refreshed.after
                break
            if selected_entry is None:
                raise RuntimeError("capacity contraction found no safe committed tail")
            selected.append(selected_entry)
            released_bytes += selected_entry.allocated_bytes
            predecessor = self._predecessor(selected_entry)
            if predecessor is not None:
                refreshed = self._refresh_from_mapping(
                    predecessor,
                    latest_values,
                    trigger=RefreshTrigger.NEWLY_EXPOSED,
                )
                refresh_checks.append(refreshed)
                heapq.heappush(view, _HeapItem.from_entry(refreshed.after))

        proposed_rent = max(
            self.rent,
            max(
                (entry.value.rental_key for entry in selected),
                default=self.rent,
            ),
        )
        return CapacityChangePreview(
            pool=self.pool,
            base_epoch=self.epoch,
            available=self.available,
            capacity_bytes_before=self.capacity_bytes,
            capacity_bytes_after=capacity_bytes,
            committed_bytes_before=self.committed_bytes,
            pending_bytes_before=self.pending_bytes,
            rent_before=self.rent,
            proposed_rent=proposed_rent,
            selected_victims=tuple(selected),
            refresh_checks=tuple(refresh_checks),
        )

    def apply_capacity_change(
        self,
        preview: CapacityChangePreview,
        *,
        cause: str,
    ) -> PoolLifecycleResolution:
        """Apply one still-current quota plan and persist its audit record."""

        self._require_cause(cause)
        if preview.pool is not self.pool:
            raise ValueError("capacity preview belongs to a different pool")
        if preview.base_epoch != self.epoch:
            raise StalePreviewError("pool epoch changed after capacity preview")
        if preview.available is not self.available:
            raise StalePreviewError("failure-domain availability changed after preview")
        if (
            preview.capacity_bytes_before != self.capacity_bytes
            or preview.committed_bytes_before != self.committed_bytes
            or preview.pending_bytes_before != self.pending_bytes
            or preview.rent_before != self.rent
        ):
            raise StalePreviewError("capacity preview no longer matches pool state")

        staged_lengths = self._revalidate_tail_sequence(preview.selected_victims)
        refresh_updates = self._surviving_refresh_updates(
            preview.refresh_checks,
            selected_ids={entry.chunk_id for entry in preview.selected_victims},
            staged_lengths=staged_lengths,
        )
        resulting_committed = self.committed_bytes - preview.released_bytes
        if resulting_committed + self.pending_bytes > preview.capacity_bytes_after:
            raise StalePreviewError("capacity preview no longer establishes the quota")

        capacity_before = self.capacity_bytes
        rent_before = self.rent
        available_before = self.available
        self._remove_tail_sequence(preview.selected_victims)
        self._committed_bytes -= preview.released_bytes
        for (request_id, sequence_index), refreshed_entry in refresh_updates.items():
            self._by_request[request_id][sequence_index] = refreshed_entry
        self._capacity_bytes = preview.capacity_bytes_after
        self._rent = preview.proposed_rent
        self._epoch += 1
        self._rebuild_heap()
        return PoolLifecycleResolution(
            pool=self.pool,
            action=PoolLifecycleAction.CAPACITY_CHANGE,
            cause=cause,
            epoch=self.epoch,
            available_before=available_before,
            available_after=self.available,
            capacity_bytes_before=capacity_before,
            capacity_bytes_after=self.capacity_bytes,
            rent_before=rent_before,
            rent_after=self.rent,
            released_entries=preview.selected_victims,
            refresh_checks=preview.refresh_checks,
        )

    def change_capacity(
        self,
        capacity_bytes: int,
        *,
        latest_values: Mapping[str, RentalValue],
        cause: str,
    ) -> PoolLifecycleResolution:
        """Serialized convenience wrapper around preview/apply capacity change."""

        return self.apply_capacity_change(
            self.preview_capacity_change(capacity_bytes, latest_values=latest_values),
            cause=cause,
        )

    def invalidate_failure_domain(self, *, cause: str) -> PoolLifecycleResolution:
        """Invalidate all bytes in this pool while preserving quota, rent, and history.

        Whole-pool removal is legal only because the physical failure domain is
        unavailable; it is deliberately separate from suffix-safe policy
        eviction.  PENDING records are returned as aborted audit entries and can
        never become recovery-visible after this call.
        """

        self._require_cause(cause)
        if not self.available:
            raise RuntimeError("failure domain is already unavailable")
        capacity_before = self.capacity_bytes
        rent_before = self.rent
        released = tuple(
            entry
            for request_id in sorted(self._by_request)
            for entry in self._by_request[request_id]
        )
        aborted = tuple(self._pending[chunk_id] for chunk_id in self.pending_chunk_ids)
        self._by_request.clear()
        self._pending.clear()
        self._heap.clear()
        self._committed_bytes = 0
        self._pending_bytes = 0
        self._available = False
        self._epoch += 1
        return PoolLifecycleResolution(
            pool=self.pool,
            action=PoolLifecycleAction.FAILURE_DOMAIN_INVALIDATE,
            cause=cause,
            epoch=self.epoch,
            available_before=True,
            available_after=False,
            capacity_bytes_before=capacity_before,
            capacity_bytes_after=self.capacity_bytes,
            rent_before=rent_before,
            rent_after=self.rent,
            released_entries=released,
            aborted_pending=aborted,
        )

    def restore_failure_domain(
        self,
        *,
        cause: str,
        capacity_bytes: int | None = None,
    ) -> PoolLifecycleResolution:
        """Restore an empty failure domain without refunding rent or chunk history."""

        self._require_cause(cause)
        if self.available:
            raise RuntimeError("failure domain is already available")
        if self._by_request or self._pending or self._heap:
            raise RuntimeError("unavailable failure domain retained policy state")
        if capacity_bytes is not None:
            require_nonnegative_int(capacity_bytes, "capacity_bytes")
        capacity_before = self.capacity_bytes
        rent_before = self.rent
        if capacity_bytes is not None:
            self._capacity_bytes = capacity_bytes
        self._available = True
        self._epoch += 1
        self._rebuild_heap()
        return PoolLifecycleResolution(
            pool=self.pool,
            action=PoolLifecycleAction.FAILURE_DOMAIN_RESTORE,
            cause=cause,
            epoch=self.epoch,
            available_before=False,
            available_after=True,
            capacity_bytes_before=capacity_before,
            capacity_bytes_after=self.capacity_bytes,
            rent_before=rent_before,
            rent_after=self.rent,
        )

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "available": self.available,
            "capacity_bytes": self.capacity_bytes,
            "committed": {
                request_id: [entry.to_canonical_json() for entry in entries]
                for request_id, entries in sorted(self._by_request.items())
            },
            "committed_bytes": self.committed_bytes,
            "epoch": self.epoch,
            "free_bytes": self.free_bytes,
            "heap_tail_chunk_ids": list(self.heap_chunk_ids),
            "pending": [
                self._pending[chunk_id].to_canonical_json() for chunk_id in self.pending_chunk_ids
            ],
            "pending_bytes": self.pending_bytes,
            "pool": self.pool.value,
            "rent": fraction_to_json(self.rent),
        }

    def _validate_current_value(self, value: RentalValue) -> None:
        if value.pool is not self.pool:
            raise ValueError("rental value belongs to a different pool")
        if value.pool_rent != self.rent:
            raise ValueError("rental value was not computed from the current pool rent")

    def _validate_new_chunk(self, chunk_id: str) -> None:
        if chunk_id in self._known_chunk_ids:
            raise ValueError(f"chunk id is already known to this pool: {chunk_id}")

    def _pending_for_request(self, request_id: str) -> tuple[PendingAdmission, ...]:
        pending = tuple(
            sorted(
                (
                    item
                    for item in self._pending.values()
                    if item.request_id == request_id
                ),
                key=lambda item: item.value_at_admission.candidate.sequence_index,
            )
        )
        committed_length = len(self._by_request.get(request_id, ()))
        if any(
            item.value_at_admission.candidate.sequence_index
            != committed_length + offset
            for offset, item in enumerate(pending)
        ):
            raise AssertionError("request-local PENDING indices lost contiguity")
        return pending

    def _next_sequence_index(self, request_id: str) -> int:
        return len(self._by_request.get(request_id, ())) + len(
            self._pending_for_request(request_id)
        )

    def _predecessor(self, entry: RentalEntry) -> RentalEntry | None:
        if entry.sequence_index == 0:
            return None
        entries = self._by_request[entry.request_id]
        predecessor = entries[entry.sequence_index - 1]
        if predecessor.sequence_index + 1 != entry.sequence_index:
            raise AssertionError("request-local index lost contiguity")
        return predecessor

    def _refresh_from_mapping(
        self,
        entry: RentalEntry,
        latest_values: Mapping[str, RentalValue],
        *,
        trigger: RefreshTrigger,
    ) -> RefreshResult:
        try:
            latest = latest_values[entry.chunk_id]
        except KeyError as exc:
            raise MissingLatestRentalError(
                f"missing latest rental value at {trigger.value}: {entry.chunk_id}"
            ) from exc
        if latest.pool_rent != self.rent:
            raise ValueError("latest lazy-refresh value must use the current pool rent")
        return refresh_if_stale(entry, latest, trigger=trigger)

    def _revalidate_tail_sequence(
        self,
        selected: tuple[RentalEntry, ...],
    ) -> dict[str, int]:
        staged_lengths: dict[str, int] = {
            request_id: len(entries) for request_id, entries in self._by_request.items()
        }
        for victim in selected:
            expected = staged_lengths.get(victim.request_id, 0) - 1
            if expected < 0:
                raise StalePreviewError("preview victim request no longer exists")
            current = self._by_request[victim.request_id][expected]
            if current.value.candidate != victim.value.candidate:
                raise StalePreviewError("preview victim is no longer a request tail")
            staged_lengths[victim.request_id] = expected
        return staged_lengths

    def _surviving_refresh_updates(
        self,
        refresh_checks: tuple[RefreshResult, ...],
        *,
        selected_ids: set[str],
        staged_lengths: Mapping[str, int],
    ) -> dict[tuple[str, int], RentalEntry]:
        refresh_updates: dict[tuple[str, int], RentalEntry] = {}
        for refresh in refresh_checks:
            if not refresh.refreshed or refresh.after.chunk_id in selected_ids:
                continue
            resulting_length = staged_lengths.get(refresh.after.request_id, 0)
            if refresh.after.sequence_index >= resulting_length:
                raise StalePreviewError("refreshed survivor is absent from projected state")
            current = self._by_request[refresh.after.request_id][refresh.after.sequence_index]
            if current.value.candidate != refresh.after.value.candidate:
                raise StalePreviewError("refreshed entry no longer matches the request index")
            key = (refresh.after.request_id, refresh.after.sequence_index)
            previous = refresh_updates.get(key)
            if previous is not None and previous != refresh.after:
                raise StalePreviewError("preview contains conflicting refreshed values")
            refresh_updates[key] = refresh.after
        return refresh_updates

    def _remove_tail_sequence(self, selected: tuple[RentalEntry, ...]) -> None:
        for victim in selected:
            entries = self._by_request[victim.request_id]
            removed = entries.pop()
            if removed.chunk_id != victim.chunk_id:  # pragma: no cover - revalidated first
                raise AssertionError("tail revalidation and removal diverged")
            if not entries:
                del self._by_request[victim.request_id]

    @staticmethod
    def _require_cause(cause: str) -> None:
        if type(cause) is not str or not cause:
            raise ValueError("lifecycle cause must be a non-empty string")

    def _rebuild_heap(self) -> None:
        pending_requests = {item.request_id for item in self._pending.values()}
        self._heap = [
            _HeapItem.from_entry(entries[-1])
            for request_id, entries in self._by_request.items()
            if entries and request_id not in pending_requests
        ]
        heapq.heapify(self._heap)
