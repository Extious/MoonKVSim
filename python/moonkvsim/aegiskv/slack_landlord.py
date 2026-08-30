"""Exact, GlobalDES-only SlackLandlord admission kernel.

Each instance owns exactly one capacity pool and one independent rent.  It keeps a
two-level index: request-local contiguous chunk sequences, plus a global min-heap
containing only each request's currently releasable tail.  Preview is immutable and
temporary; apply is rejected unless the pool epoch is unchanged.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction

from moonkvsim.aegiskv.lazy_refresh import (
    RefreshResult,
    RefreshTrigger,
    RentalEntry,
    refresh_if_stale,
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


class StalePreviewError(RuntimeError):
    """Raised when a preview is applied after its source pool changed."""


class MissingLatestRentalError(RuntimeError):
    """Raised when an authorized lazy-refresh site has no latest exact value."""


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
    free_bytes_before: int
    free_bytes_after_selection: int
    proposed_rent: Fraction
    bypass_reason: str | None
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
        selected_loss = sum(
            (entry.value.composite_benefit for entry in self.selected_victims),
            start=Fraction(0, 1),
        )
        if self.joint_loss != selected_loss:
            raise ValueError("joint_loss must equal selected victims' latest G values")
        if len({entry.chunk_id for entry in self.selected_victims}) != len(
            self.selected_victims
        ):
            raise ValueError("selected victims must be unique")
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
            if any(
                entry.value.rental_key >= self.threshold for entry in self.selected_victims
            ):
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
        if self.joint_loss_interpretation != JOINT_LOSS_INTERPRETATION:
            raise ValueError("unsupported joint-loss interpretation")
        if self.interpretation_review_status != JOINT_LOSS_REVIEW_STATUS:
            raise ValueError("joint-loss interpretation review status must remain explicit")
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
            "candidate_value": self.candidate_value.to_canonical_json(),
            "free_bytes_after_selection": self.free_bytes_after_selection,
            "free_bytes_before": self.free_bytes_before,
            "joint_loss_D_Y": fraction_to_json(self.joint_loss),
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
        self._by_request: dict[str, list[RentalEntry]] = {}
        self._pending: dict[str, PendingAdmission] = {}
        self._heap: list[_HeapItem] = []
        self._known_chunk_ids: set[str] = set()

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
    def committed_bytes(self) -> int:
        return sum(
            entry.allocated_bytes
            for entries in self._by_request.values()
            for entry in entries
        )

    @property
    def pending_bytes(self) -> int:
        return sum(item.allocated_bytes for item in self._pending.values())

    @property
    def free_bytes(self) -> int:
        return self.capacity_bytes - self.committed_bytes - self.pending_bytes

    @property
    def heap_chunk_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.chunk_id for item in self._heap))

    @property
    def pending_chunk_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))

    def committed_entries(self, request_id: str) -> tuple[RentalEntry, ...]:
        return tuple(self._by_request.get(request_id, ()))

    def register_committed(self, value: RentalValue) -> RentalEntry:
        """Seed an already committed chunk while enforcing contiguous suffix safety."""

        self._validate_current_value(value)
        candidate = value.candidate
        self._validate_new_chunk(candidate.chunk_id)
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
        self._known_chunk_ids.add(candidate.chunk_id)
        self._epoch += 1
        self._rebuild_heap()
        return entry

    def preview(
        self,
        candidate_value: RentalValue,
        *,
        latest_values: Mapping[str, RentalValue],
    ) -> AdmissionPreview:
        """Build a temporary admission/eviction view without mutating pool state."""

        self._validate_current_value(candidate_value)
        candidate = candidate_value.candidate
        self._validate_new_chunk(candidate.chunk_id)
        if any(item.request_id == candidate.request_id for item in self._pending.values()):
            raise ValueError("only one pending chunk per request is permitted")
        expected_index = len(self._by_request.get(candidate.request_id, ()))
        if candidate.sequence_index != expected_index:
            raise ValueError("candidate must extend its request's contiguous tail")

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
                if top.request_id == candidate.request_id:
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
            free_bytes_before=free_before,
            free_bytes_after_selection=free_after,
            proposed_rent=proposed_rent,
            bypass_reason=bypass_reason,
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
        if any(item.request_id == preview.candidate.request_id for item in self._pending.values()):
            raise StalePreviewError("candidate request gained another pending chunk")
        expected_candidate_index = len(self._by_request.get(preview.candidate.request_id, ()))
        if preview.candidate.sequence_index != expected_candidate_index:
            raise StalePreviewError("candidate no longer extends its request tail")

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

        pending = self._pending.get(chunk_id)
        if pending is None:
            raise KeyError(f"unknown pending chunk: {chunk_id}")
        latest_value = compute_rental_value(latest_inputs)
        pending.value_at_admission._require_same_identity(latest_value)
        self._validate_current_value(latest_value)
        if latest_value.evaluated_at_ns < pending.value_at_admission.evaluated_at_ns:
            raise ValueError("completion value cannot predate admission")
        if not latest_value.signal_versions.is_at_least(
            pending.value_at_admission.signal_versions
        ):
            raise ValueError("completion cannot regress any signal version")
        candidate = latest_value.candidate
        entries = self._by_request.get(candidate.request_id)
        current_length = 0 if entries is None else len(entries)
        if candidate.sequence_index != current_length:
            raise ValueError("completion must extend the latest contiguous request tail")
        if entries is None:
            entries = []
            self._by_request[candidate.request_id] = entries
        del self._pending[chunk_id]
        entries.append(RentalEntry(latest_value))
        self._epoch += 1
        self._rebuild_heap()
        return PathResolution(
            chunk_id=chunk_id,
            state=PathCommitState.COMMITTED,
            epoch=self.epoch,
            latest_value=latest_value,
        )

    def abort_pending(self, chunk_id: str) -> PathResolution:
        pending = self._pending.pop(chunk_id, None)
        if pending is None:
            raise KeyError(f"unknown pending chunk: {chunk_id}")
        self._epoch += 1
        self._rebuild_heap()
        return PathResolution(
            chunk_id=chunk_id,
            state=PathCommitState.ABORTED,
            epoch=self.epoch,
            latest_value=None,
        )

    def to_canonical_json(self) -> dict[str, object]:
        return {
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
                self._pending[chunk_id].to_canonical_json()
                for chunk_id in self.pending_chunk_ids
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

    def _rebuild_heap(self) -> None:
        self._heap = [
            _HeapItem.from_entry(entries[-1])
            for entries in self._by_request.values()
            if entries
        ]
        heapq.heapify(self._heap)
