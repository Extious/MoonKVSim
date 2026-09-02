"""Physical HBM authority for the experiment continuous-batch scheduler.

The vLLM mirror owns logical 16-token pages only.  This adapter is the sole
owner of the corresponding physical bytes in the experiment ``CapacityLedger``.
Four logical pages share one 64-token source allocation; a final partial group
still consumes one complete source allocation, matching the experiment's
source-chunk accounting.

All ordinary scheduler mutations call this observer *before* mutating
``BlockPool``.  The adapter previews the complete ledger transaction first and
only publishes logical ownership after the transaction commits.  A rejected
transaction therefore leaves both physical and logical state unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
)
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction


class ExperimentHBMAuthorityError(RuntimeError):
    """Logical scheduler ownership and the physical HBM ledger diverged."""


@dataclass(slots=True)
class _SourceAllocation:
    allocation_id: str
    request_id: str
    source_chunk_index: int
    block_ids: set[int] = field(default_factory=set)
    cache_hashes: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _ResidentIntervalBinding:
    start_source_chunk: int
    source_chunk_count: int
    account: str
    activate: Callable[[int], int]

    def contains(self, source_chunk_index: int) -> bool:
        return self.start_source_chunk <= source_chunk_index < (
            self.start_source_chunk + self.source_chunk_count
        )


@dataclass(slots=True)
class _RecoveryReservation:
    request_id: str
    block_ids: tuple[int, ...]
    allocations: tuple[_SourceAllocation, ...]


@dataclass(slots=True)
class _ExternalRecoveryReservation:
    source_chunk_count: int
    reserved_source_chunk_indices: set[int]
    bound_source_chunk_indices: set[int] = field(default_factory=set)


class ExperimentHBMAuthority:
    """Map scheduler pages to one experiment-owned physical HBM ledger.

    ``reclaim_free_bytes`` may evict inactive or Peer-HBM objects through the
    enclosing experiment.  It must return only after the shared ledger exposes
    at least the requested FREE bytes.  ``bind_inactive_prefix`` installs a
    one-shot callback which removes exactly that prefix from the experiment's
    inactive ``_ModeledPool``; the matching ledger move is committed here as
    ``INACTIVE -> ACTIVE`` in the same scheduler admission boundary.
    """

    def __init__(
        self,
        *,
        authority_id: str,
        ledger: CapacityLedger,
        journal: EventJournal,
        now_ns: Callable[[], int],
        logical_block_tokens: int,
        source_chunk_tokens: int,
        source_chunk_bytes: int,
        active_account: str,
        inactive_account: str,
        recovery_reserved_account: str,
        reclaim_free_bytes: Callable[[int], bool] | None = None,
        on_commit: Callable[[str], None] | None = None,
    ) -> None:
        if not authority_id:
            raise ValueError("authority_id must be non-empty")
        if logical_block_tokens <= 0 or source_chunk_tokens <= 0:
            raise ValueError("block and source-chunk token sizes must be positive")
        if source_chunk_tokens % logical_block_tokens:
            raise ValueError("source chunks must contain a whole number of logical pages")
        if source_chunk_bytes <= 0:
            raise ValueError("source_chunk_bytes must be positive")
        if not active_account or not inactive_account or not recovery_reserved_account:
            raise ValueError("HBM accounts must be non-empty")
        self.authority_id = authority_id
        self.ledger = ledger
        self.ledgers = {ledger.resource_id: ledger}
        self.journal = journal
        self._now_ns = now_ns
        self.logical_block_tokens = logical_block_tokens
        self.source_chunk_tokens = source_chunk_tokens
        self.source_chunk_bytes = source_chunk_bytes
        self.active_account = active_account
        self.inactive_account = inactive_account
        self.recovery_reserved_account = recovery_reserved_account
        self._pages_per_source_chunk = source_chunk_tokens // logical_block_tokens
        self._reclaim_free_bytes = reclaim_free_bytes
        self._on_commit = on_commit
        self._blocks: dict[int, _SourceAllocation] = {}
        self._request_blocks: dict[str, list[int]] = {}
        self._source_allocations: dict[tuple[str, int], _SourceAllocation] = {}
        self._resident_intervals: dict[str, list[_ResidentIntervalBinding]] = {}
        self._recovery: dict[str, _RecoveryReservation] = {}
        self._external_recovery_reservations: dict[
            str, _ExternalRecoveryReservation
        ] = {}
        self._operation_sequence = 0
        self._failed = False

    @property
    def num_free_blocks(self) -> int:
        """Return only globally fungible pages, excluding request-private tails."""

        if self._failed:
            return 0
        physically_reclaimable_source_chunks = (
            self.ledger.bytes_in(FREE_ACCOUNT)
            + self.ledger.bytes_in(self.inactive_account)
        ) // self.source_chunk_bytes
        bound_inactive_chunks = sum(
            binding.source_chunk_count
            for bindings in self._resident_intervals.values()
            for binding in bindings
            if binding.account == self.inactive_account
        )
        # A foreground pool eviction can invalidate a previously bound
        # inactive interval before its request reaches admission. Never reserve
        # more private inactive chunks than still physically exist.
        request_private_inactive_chunks = min(
            bound_inactive_chunks,
            self.ledger.bytes_in(self.inactive_account) // self.source_chunk_bytes,
        )
        free_source_chunks = (
            physically_reclaimable_source_chunks - request_private_inactive_chunks
        )
        if free_source_chunks < 0:
            raise ExperimentHBMAuthorityError(
                "inactive resident bindings exceed reclaimable HBM"
            )
        return free_source_chunks * self._pages_per_source_chunk

    def num_free_blocks_for_request(self, request_id: str) -> int:
        """Return fungible pages plus this request's own rounded-chunk tail.

        A partial 64-token source allocation cannot hold another request's
        logical pages.  Reporting all such tails as one global pool lets a
        high-concurrency scheduler over-admit even though the physical HBM
        ledger has no FREE source chunk left.
        """

        self._require_available()
        if not request_id:
            raise ValueError("request_id must be non-empty")
        private_tail_slots = sum(
            self._pages_per_source_chunk - len(allocation.block_ids)
            for allocation in self._source_allocations.values()
            if allocation.request_id == request_id and allocation.block_ids
        )
        external_recovery = self._external_recovery_reservations.get(request_id)
        recovery_source_chunks = (
            0
            if external_recovery is None
            else len(external_recovery.bound_source_chunk_indices)
        )
        inactive_source_chunks = sum(
            binding.source_chunk_count
            for binding in self._resident_intervals.get(request_id, ())
            if binding.account == self.inactive_account
        )
        other_resident_source_chunks = sum(
            binding.source_chunk_count
            for binding in self._resident_intervals.get(request_id, ())
            if binding.account not in {
                self.inactive_account,
                self.recovery_reserved_account,
            }
        )
        return (
            self.num_free_blocks
            + private_tail_slots
            + (
                recovery_source_chunks
                + inactive_source_chunks
                + other_resident_source_chunks
            )
            * self._pages_per_source_chunk
        )

    def try_reclaim_blocks(self, request_id: str, required_blocks: int) -> bool:
        """Establish foreground capacity before scheduler victim selection."""

        self._require_available()
        if not request_id:
            raise ValueError("request_id must be non-empty")
        if type(required_blocks) is not int or required_blocks < 0:
            raise ValueError("required_blocks must be a non-negative integer")
        available_blocks = self.num_free_blocks_for_request(request_id)
        if required_blocks <= available_blocks:
            return True
        if self._reclaim_free_bytes is None:
            return False
        required_free_bytes = self.ledger.bytes_in(FREE_ACCOUNT)
        while available_blocks < required_blocks:
            missing_blocks = required_blocks - available_blocks
            required_free_bytes += (
                _ceil_div(missing_blocks, self._pages_per_source_chunk)
                * self.source_chunk_bytes
            )
            if required_free_bytes > self.ledger.capacity_bytes:
                return False
            free_before = self.ledger.bytes_in(FREE_ACCOUNT)
            if not self._reclaim_free_bytes(required_free_bytes):
                return False
            updated_blocks = self.num_free_blocks_for_request(request_id)
            if (
                updated_blocks <= available_blocks
                and self.ledger.bytes_in(FREE_ACCOUNT) <= free_before
            ):
                return False
            available_blocks = updated_blocks
        return True

    @property
    def active_block_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._blocks))

    @property
    def active_request_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                request_id
                for request_id, block_ids in self._request_blocks.items()
                if block_ids
            )
        )

    @property
    def active_physical_bytes(self) -> int:
        return len(self._source_allocations) * self.source_chunk_bytes

    def physical_bytes_for_request(self, request_id: str) -> int:
        """Return rounded physical ACTIVE bytes owned by one logical request."""

        return sum(
            self.source_chunk_bytes
            for (owner_id, _source_index) in self._source_allocations
            if owner_id == request_id
        )

    @property
    def failed(self) -> bool:
        return self._failed

    def validate_scheduler_layout(
        self, *, block_size_tokens: int, usable_block_capacity: int
    ) -> None:
        if block_size_tokens != self.logical_block_tokens:
            raise ValueError("scheduler logical page size differs from HBM authority")
        if usable_block_capacity <= 0:
            raise ValueError("scheduler must expose at least one usable logical page")

    def bind_inactive_prefix(
        self,
        *,
        request_id: str,
        restored_tokens: int,
        activate: Callable[[int], int],
    ) -> None:
        """Bind a block-aligned inactive prefix for a one-shot zero-copy admission.

        The callback receives the exact source-chunk count and must remove that
        many complete source chunks from the inactive policy pool without
        touching the capacity ledger.  It returns the adopted physical bytes.
        """

        self._require_available()
        self.bind_resident_interval(
            request_id=request_id,
            start_token=0,
            token_count=restored_tokens,
            account=self.inactive_account,
            activate=activate,
        )

    def bind_resident_interval(
        self,
        *,
        request_id: str,
        start_token: int,
        token_count: int,
        account: str,
        activate: Callable[[int], int],
    ) -> None:
        """Bind source-resident chunks for atomic role reclassification."""

        self._require_available()
        if not request_id or not account:
            raise ValueError("resident interval identity must be non-empty")
        if start_token < 0 or start_token % self.source_chunk_tokens:
            raise ValueError("resident interval must start on a source-chunk boundary")
        if token_count <= 0 or token_count % self.logical_block_tokens:
            raise ValueError("resident interval must end on a logical-page boundary")
        start_source_chunk = start_token // self.source_chunk_tokens
        source_chunk_count = _ceil_div(token_count, self.source_chunk_tokens)
        new_binding = _ResidentIntervalBinding(
            start_source_chunk=start_source_chunk,
            source_chunk_count=source_chunk_count,
            account=account,
            activate=activate,
        )
        bindings = self._resident_intervals.get(request_id, [])
        new_indices = set(
            range(start_source_chunk, start_source_chunk + source_chunk_count)
        )
        if any(
            new_indices
            & set(
                range(
                    binding.start_source_chunk,
                    binding.start_source_chunk + binding.source_chunk_count,
                )
            )
            for binding in bindings
        ):
            raise ValueError("resident source intervals overlap")
        if any(
            (request_id, source_index) in self._source_allocations
            for source_index in new_indices
        ):
            raise ValueError("resident source interval is already ACTIVE")
        required_bytes = source_chunk_count * self.source_chunk_bytes
        if self.ledger.bytes_in(account) < required_bytes:
            raise ValueError("resident HBM account cannot cover the bound interval")
        external_recovery: _ExternalRecoveryReservation | None = None
        if account == self.recovery_reserved_account:
            external_recovery = self._external_recovery_reservations.get(request_id)
            if external_recovery is None:
                raise ValueError(
                    "recovery-resident interval lacks a per-request external reservation"
                )
            if not new_indices <= external_recovery.reserved_source_chunk_indices:
                raise ValueError(
                    "recovery-resident interval exceeds its per-request reservation"
                )
            if new_indices & external_recovery.bound_source_chunk_indices:
                raise ValueError("recovery-resident source chunks are already bound")
        self._resident_intervals.setdefault(request_id, []).append(new_binding)
        if external_recovery is not None:
            external_recovery.bound_source_chunk_indices.update(new_indices)
        self.audit()

    def unbind_resident_intervals(self, request_id: str) -> int:
        """Rollback pre-admission resident bindings without releasing bytes.

        Scheduler admission owns the later account transition.  Until logical
        pages are allocated, an exception may safely remove only the one-shot
        binding.  External recovery bytes remain RESERVED and can be rebound
        by a later route attempt.
        """

        self._require_available()
        if not request_id:
            raise ValueError("resident interval rollback requires a request ID")
        bindings = self._resident_intervals.get(request_id, [])
        if not bindings:
            return 0
        active_indices = {
            source_index
            for owner_id, source_index in self._source_allocations
            if owner_id == request_id
        }
        bound_indices = {
            source_index
            for binding in bindings
            for source_index in range(
                binding.start_source_chunk,
                binding.start_source_chunk + binding.source_chunk_count,
            )
        }
        if active_indices & bound_indices:
            raise ExperimentHBMAuthorityError(
                "cannot unbind a resident interval after ACTIVE adoption"
            )
        external = self._external_recovery_reservations.get(request_id)
        recovery_indices = {
            source_index
            for binding in bindings
            if binding.account == self.recovery_reserved_account
            for source_index in range(
                binding.start_source_chunk,
                binding.start_source_chunk + binding.source_chunk_count,
            )
        }
        if recovery_indices:
            if external is None or not recovery_indices <= (
                external.bound_source_chunk_indices
            ):
                raise ExperimentHBMAuthorityError(
                    "recovery resident binding lost its external reservation"
                )
            external.bound_source_chunk_indices.difference_update(recovery_indices)
        del self._resident_intervals[request_id]
        self.audit()
        return len(bound_indices) * self.source_chunk_bytes

    def observe_external_recovery_reservation(
        self,
        *,
        request_id: str,
        reserved_bytes: int,
    ) -> None:
        """Adopt an experiment recovery reservation into scheduler ownership.

        The enclosing recovery planner may combine inactive, Peer-HBM, and
        FREE account moves in one transaction before a scheduler request
        exists.  This method immediately records the resulting complete
        source-chunk reservation so subsequent scheduler audits still have one
        exact physical owner.
        """

        self._require_available()
        if not request_id or request_id in self._external_recovery_reservations:
            raise ValueError("external recovery reservation identity is invalid")
        if reserved_bytes <= 0 or reserved_bytes % self.source_chunk_bytes:
            raise ValueError("external recovery reservation must use source chunks")
        source_chunk_count = reserved_bytes // self.source_chunk_bytes
        tracked_reserved_bytes = self._tracked_recovery_reserved_bytes()
        if self.ledger.bytes_in(self.recovery_reserved_account) != (
            tracked_reserved_bytes + reserved_bytes
        ):
            raise ValueError(
                "external recovery reservation does not match unowned RESERVED bytes"
            )
        self._external_recovery_reservations[request_id] = (
            _ExternalRecoveryReservation(
                source_chunk_count=source_chunk_count,
                reserved_source_chunk_indices=set(range(source_chunk_count)),
            )
        )
        self.audit()

    def trim_external_recovery_reservation(
        self,
        *,
        request_id: str,
        retained_bytes: int,
        cause: str,
    ) -> None:
        """Release a reserved recompute suffix while retaining a prefix."""

        self._require_available()
        if retained_bytes < 0 or retained_bytes % self.source_chunk_bytes:
            raise ValueError("retained recovery bytes must use source chunks")
        try:
            reservation = self._external_recovery_reservations[request_id]
        except KeyError as error:
            raise ValueError("unknown external recovery reservation") from error
        retained_chunks = retained_bytes // self.source_chunk_bytes
        if retained_chunks > reservation.source_chunk_count:
            raise ValueError("retained recovery prefix exceeds its reservation")
        active_source_indices = {
            source_index
            for owner_id, source_index in self._source_allocations
            if owner_id == request_id
        }
        if any(source_index >= retained_chunks for source_index in active_source_indices):
            raise ValueError("retained recovery prefix excludes ACTIVE source chunks")
        released_indices = {
            source_index
            for source_index in reservation.reserved_source_chunk_indices
            if source_index >= retained_chunks
        }
        if released_indices & reservation.bound_source_chunk_indices:
            raise ValueError("cannot trim a bound recovery-resident interval")
        if released_indices:
            self._commit(
                [
                    self._delta(
                        _SourceAllocation(
                            allocation_id=(
                                f"{self.authority_id}:recovery-trim:{request_id}:"
                                f"source:{source_index}"
                            ),
                            request_id=request_id,
                            source_chunk_index=source_index,
                        ),
                        account_from=self.recovery_reserved_account,
                        account_to=FREE_ACCOUNT,
                    )
                    for source_index in sorted(released_indices)
                ],
                cause=cause,
            )
        reservation.source_chunk_count = retained_chunks
        reservation.reserved_source_chunk_indices.difference_update(released_indices)
        if not reservation.reserved_source_chunk_indices:
            del self._external_recovery_reservations[request_id]
        self.audit()

    def allocate_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
        evicted_cache_hashes: Mapping[int, str] | None = None,
    ) -> None:
        self._require_available()
        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._normalize_new_blocks(block_ids)
        if not normalized:
            return
        if evicted_cache_hashes:
            raise ValueError("experiment scheduler does not evict logical prefix-cache pages")

        request_blocks = self._request_blocks.get(request_id, [])
        start_ordinal = len(request_blocks)
        new_allocations: dict[int, _SourceAllocation] = {}
        assignments: list[tuple[int, _SourceAllocation]] = []
        for offset, block_id in enumerate(normalized):
            ordinal = start_ordinal + offset
            source_index = ordinal // self._pages_per_source_chunk
            key = (request_id, source_index)
            allocation = self._source_allocations.get(key)
            if allocation is None:
                allocation = new_allocations.setdefault(
                    source_index,
                    _SourceAllocation(
                        allocation_id=(
                            f"{self.authority_id}:request:{request_id}:source:{source_index}"
                        ),
                        request_id=request_id,
                        source_chunk_index=source_index,
                    ),
                )
            assignments.append((block_id, allocation))

        bindings = self._resident_intervals.get(request_id, [])

        def bound_interval(source_index: int) -> _ResidentIntervalBinding | None:
            matching = [binding for binding in bindings if binding.contains(source_index)]
            if len(matching) > 1:
                raise ExperimentHBMAuthorityError("resident source bindings overlap")
            return None if not matching else matching[0]

        bound_new: dict[int, tuple[_ResidentIntervalBinding, int]] = {}
        for source_index in new_allocations:
            binding = bound_interval(source_index)
            if binding is None:
                continue
            binding_identity = id(binding)
            previous = bound_new.get(binding_identity)
            bound_new[binding_identity] = (
                binding,
                1 if previous is None else previous[1] + 1,
            )
        resident_new = sum(count for _binding, count in bound_new.values())
        free_new = len(new_allocations) - resident_new
        free_bytes = free_new * self.source_chunk_bytes
        if free_bytes > self.ledger.bytes_in(FREE_ACCOUNT) and (
            self._reclaim_free_bytes is None
            or not self._reclaim_free_bytes(free_bytes)
        ):
            raise ValueError("foreground scheduler pages cannot fit physical HBM")
        if free_bytes > self.ledger.bytes_in(FREE_ACCOUNT):
            raise ExperimentHBMAuthorityError("reclaim callback did not establish FREE bytes")

        for binding, count in bound_new.values():
            if count * self.source_chunk_bytes > self.ledger.bytes_in(binding.account):
                raise ValueError("resident zero-copy interval lost physical residency")
        adopted_recovery_indices = {
            source_index
            for source_index in new_allocations
            if (
                (binding := bound_interval(source_index)) is not None
                and binding.account == self.recovery_reserved_account
            )
        }
        external_recovery = None
        if adopted_recovery_indices:
            external_recovery = self._external_recovery_reservations.get(request_id)
            if external_recovery is None:
                raise ExperimentHBMAuthorityError(
                    "recovery-resident admission lacks an external reservation"
                )
            if not adopted_recovery_indices <= (
                external_recovery.reserved_source_chunk_indices
                & external_recovery.bound_source_chunk_indices
            ):
                raise ExperimentHBMAuthorityError(
                    "recovery-resident admission exceeds its bound reservation"
                )
        deltas = []
        for source_index, allocation in sorted(new_allocations.items()):
            resident_binding = bound_interval(source_index)
            from_account = (
                FREE_ACCOUNT if resident_binding is None else resident_binding.account
            )
            deltas.append(
                self._delta(
                    allocation,
                    account_from=from_account,
                    account_to=self.active_account,
                )
            )
        if deltas:
            # Preflight every deterministic transaction rejection before the
            # pool callback.  Within one DES handler there is no interleaving
            # mutation between this preview and commit.
            self._preflight(deltas)
            for resident_binding, count in bound_new.values():
                adopted = resident_binding.activate(count)
                if adopted != count * self.source_chunk_bytes:
                    raise ExperimentHBMAuthorityError(
                        "resident pool activation returned the wrong physical byte count"
                    )
            self._commit(deltas, cause=cause)
            if external_recovery is not None:
                external_recovery.reserved_source_chunk_indices.difference_update(
                    adopted_recovery_indices
                )
                external_recovery.bound_source_chunk_indices.difference_update(
                    adopted_recovery_indices
                )
                if not external_recovery.reserved_source_chunk_indices:
                    del self._external_recovery_reservations[request_id]

        for block_id, allocation in assignments:
            allocation.block_ids.add(block_id)
            self._blocks[block_id] = allocation
        request_blocks.extend(normalized)
        self._request_blocks[request_id] = request_blocks
        if bindings:
            retained = [
                binding
                for binding in bindings
                if not all(
                    (request_id, source_index) in self._source_allocations
                    or source_index in new_allocations
                    for source_index in range(
                        binding.start_source_chunk,
                        binding.start_source_chunk + binding.source_chunk_count,
                    )
                )
            ]
            if retained:
                self._resident_intervals[request_id] = retained
            else:
                self._resident_intervals.pop(request_id, None)
        self._source_allocations.update(
            ((request_id, index), allocation)
            for index, allocation in new_allocations.items()
        )
        self.audit()

    def activate_cached_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        """Attach a logical alias without charging physical bytes again."""

        self._require_available()
        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        for block_id, cache_hash in block_hashes.items():
            allocation = self._blocks.get(block_id)
            if allocation is None or cache_hash not in allocation.cache_hashes:
                raise ValueError("logical prefix alias lacks matching physical content")
        # The BlockPool increments refcounts after this callback.  Physical bytes
        # and source ownership intentionally remain unchanged.

    def mark_cacheable_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        cause: str,
    ) -> None:
        self._require_available()
        if not cause:
            raise ValueError("cause must be non-empty")
        for block_id, cache_hash in block_hashes.items():
            if not cache_hash:
                raise ValueError("cache hash must be non-empty")
            self._blocks[block_id].cache_hashes.add(cache_hash)

    def release_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        self._require_available()
        normalized = self._normalize_existing_blocks(block_ids, request_id=request_id)
        if not normalized:
            return
        affected = {self._blocks[block_id].source_chunk_index for block_id in normalized}
        remaining = set(self._request_blocks[request_id]) - set(normalized)
        released_allocations = [
            self._source_allocations[(request_id, source_index)]
            for source_index in sorted(affected)
            if not (
                self._source_allocations[(request_id, source_index)].block_ids
                - set(normalized)
            )
        ]
        if released_allocations:
            self._commit(
                [
                    self._delta(
                        allocation,
                        account_from=self.active_account,
                        account_to=FREE_ACCOUNT,
                    )
                    for allocation in released_allocations
                ],
                cause=cause,
            )
        for block_id in normalized:
            allocation = self._blocks.pop(block_id)
            allocation.block_ids.remove(block_id)
        for allocation in released_allocations:
            del self._source_allocations[(request_id, allocation.source_chunk_index)]
        if remaining:
            self._request_blocks[request_id] = [
                block_id
                for block_id in self._request_blocks[request_id]
                if block_id in remaining
            ]
        else:
            del self._request_blocks[request_id]
            self._resident_intervals.pop(request_id, None)
        self.audit()

    def reserve_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> tuple[tuple[str, ...], ...]:
        self._require_available()
        if request_id in self._recovery:
            raise ValueError("request already owns a recovery reservation")
        normalized = self._normalize_new_blocks(block_ids)
        allocations = self._allocations_for_fresh_blocks(request_id, normalized)
        required_bytes = len(allocations) * self.source_chunk_bytes
        if required_bytes > self.ledger.bytes_in(FREE_ACCOUNT) and (
            self._reclaim_free_bytes is None
            or not self._reclaim_free_bytes(required_bytes)
        ):
            raise ValueError("recovery destination cannot fit physical HBM")
        if required_bytes > self.ledger.bytes_in(FREE_ACCOUNT):
            raise ExperimentHBMAuthorityError("reclaim did not establish recovery bytes")
        self._commit(
            [
                self._delta(
                    allocation,
                    account_from=FREE_ACCOUNT,
                    account_to=self.recovery_reserved_account,
                )
                for allocation in allocations
            ],
            cause=f"{cause}:reserve",
        )
        self._recovery[request_id] = _RecoveryReservation(
            request_id=request_id,
            block_ids=normalized,
            allocations=allocations,
        )
        allocation_ids = {
            allocation.source_chunk_index: allocation.allocation_id
            for allocation in allocations
        }
        return tuple(
            (allocation_ids[index // self._pages_per_source_chunk],)
            for index in range(len(normalized))
        )

    def commit_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        reservation = self._recovery_record(request_id, block_ids)
        self._commit(
            [
                self._delta(
                    allocation,
                    account_from=self.recovery_reserved_account,
                    account_to=self.active_account,
                )
                for allocation in reservation.allocations
            ],
            cause=f"{cause}:commit",
        )
        for ordinal, block_id in enumerate(reservation.block_ids):
            allocation = reservation.allocations[
                ordinal // self._pages_per_source_chunk
            ]
            allocation.block_ids.add(block_id)
            self._blocks[block_id] = allocation
        self._request_blocks[request_id] = list(reservation.block_ids)
        self._source_allocations.update(
            ((request_id, allocation.source_chunk_index), allocation)
            for allocation in reservation.allocations
        )
        del self._recovery[request_id]
        self.audit()

    def abort_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        reservation = self._recovery_record(request_id, block_ids)
        self._commit(
            [
                self._delta(
                    allocation,
                    account_from=self.recovery_reserved_account,
                    account_to=FREE_ACCOUNT,
                )
                for allocation in reservation.allocations
            ],
            cause=f"{cause}:abort",
        )
        del self._recovery[request_id]
        self.audit()

    def observe_external_failure(self) -> None:
        """Fence logical ownership after the experiment applies physical loss once."""

        if self._failed:
            raise ExperimentHBMAuthorityError("HBM authority was failed twice")
        if self.ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) != self.ledger.capacity_bytes:
            raise ExperimentHBMAuthorityError(
                "external failure did not move complete HBM capacity to UNAVAILABLE"
            )
        self._failed = True
        self._blocks.clear()
        self._request_blocks.clear()
        self._source_allocations.clear()
        self._resident_intervals.clear()
        self._recovery.clear()
        self._external_recovery_reservations.clear()

    def audit_scheduler_blocks(
        self,
        block_ref_counts: Mapping[int, int],
        cached_block_hashes: Mapping[int, str],
        reserved_block_ids: set[int],
    ) -> None:
        if self._failed:
            return
        ordinary = set(block_ref_counts)
        if ordinary != set(self._blocks):
            raise ExperimentHBMAuthorityError(
                "scheduler logical pages and physical authority ownership diverged"
            )
        if any(value <= 0 for value in block_ref_counts.values()):
            raise ExperimentHBMAuthorityError("scheduler reported non-positive page refcount")
        if set(cached_block_hashes) - ordinary:
            raise ExperimentHBMAuthorityError("cached logical page has no physical owner")
        expected_reserved = {
            block_id
            for reservation in self._recovery.values()
            for block_id in reservation.block_ids
        }
        if reserved_block_ids != expected_reserved:
            raise ExperimentHBMAuthorityError(
                "scheduler recovery reservations and physical HBM diverged"
            )
        self.audit()

    def audit(self) -> None:
        if self._failed:
            if self._blocks or self._source_allocations or self._request_blocks:
                raise ExperimentHBMAuthorityError("failed authority retained ownership")
            return
        if set(self._blocks) != {
            block_id
            for allocation in self._source_allocations.values()
            for block_id in allocation.block_ids
        }:
            raise ExperimentHBMAuthorityError("logical block index diverged")
        for request_id, block_ids in self._request_blocks.items():
            if len(block_ids) != len(set(block_ids)):
                raise ExperimentHBMAuthorityError("request contains duplicate logical pages")
            if any(self._blocks[block_id].request_id != request_id for block_id in block_ids):
                raise ExperimentHBMAuthorityError("logical page belongs to another request")
        if self.ledger.bytes_in(self.active_account) != self.active_physical_bytes:
            raise ExperimentHBMAuthorityError(
                "physical ACTIVE bytes disagree with rounded source-chunk ownership"
            )
        reserved_bytes = sum(
            len(reservation.allocations) * self.source_chunk_bytes
            for reservation in self._recovery.values()
        ) + sum(
            len(reservation.reserved_source_chunk_indices) * self.source_chunk_bytes
            for reservation in self._external_recovery_reservations.values()
        )
        if self.ledger.bytes_in(self.recovery_reserved_account) != reserved_bytes:
            raise ExperimentHBMAuthorityError("physical recovery reserve diverged")

        recovery_binding_indices: dict[str, set[int]] = {}
        for request_id, bindings in self._resident_intervals.items():
            for binding in bindings:
                if binding.account != self.recovery_reserved_account:
                    continue
                indices = {
                    source_index
                    for source_index in range(
                        binding.start_source_chunk,
                        binding.start_source_chunk + binding.source_chunk_count,
                    )
                    if (request_id, source_index) not in self._source_allocations
                }
                already_bound = recovery_binding_indices.setdefault(request_id, set())
                if already_bound & indices:
                    raise ExperimentHBMAuthorityError(
                        "recovery-resident source chunks are multiply bound"
                    )
                already_bound.update(indices)
        if set(recovery_binding_indices) - set(self._external_recovery_reservations):
            raise ExperimentHBMAuthorityError(
                "recovery-resident binding lacks an external reservation"
            )
        for request_id, reservation in self._external_recovery_reservations.items():
            valid_indices = set(range(reservation.source_chunk_count))
            if (
                not reservation.reserved_source_chunk_indices
                or not reservation.reserved_source_chunk_indices <= valid_indices
                or not reservation.bound_source_chunk_indices
                <= reservation.reserved_source_chunk_indices
            ):
                raise ExperimentHBMAuthorityError(
                    "external recovery reservation chunk ownership is invalid"
                )
            if reservation.bound_source_chunk_indices != recovery_binding_indices.get(
                request_id, set()
            ):
                raise ExperimentHBMAuthorityError(
                    "recovery-resident bindings and reserved chunks diverged"
                )

    def _tracked_recovery_reserved_bytes(self) -> int:
        return (
            sum(
                len(reservation.allocations)
                for reservation in self._recovery.values()
            )
            + sum(
                len(reservation.reserved_source_chunk_indices)
                for reservation in self._external_recovery_reservations.values()
            )
        ) * self.source_chunk_bytes

    def _allocations_for_fresh_blocks(
        self, request_id: str, block_ids: tuple[int, ...]
    ) -> tuple[_SourceAllocation, ...]:
        count = _ceil_div(len(block_ids), self._pages_per_source_chunk)
        return tuple(
            _SourceAllocation(
                allocation_id=f"{self.authority_id}:recovery:{request_id}:source:{index}",
                request_id=request_id,
                source_chunk_index=index,
            )
            for index in range(count)
        )

    def _recovery_record(
        self, request_id: str, block_ids: tuple[int, ...]
    ) -> _RecoveryReservation:
        try:
            reservation = self._recovery[request_id]
        except KeyError as error:
            raise ValueError("unknown recovery reservation") from error
        if reservation.block_ids != tuple(block_ids):
            raise ValueError("recovery logical block binding changed")
        return reservation

    def _normalize_new_blocks(self, block_ids: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(block_ids)
        if len(normalized) != len(set(normalized)) or any(block_id <= 0 for block_id in normalized):
            raise ValueError("logical block IDs must be unique positive integers")
        if set(normalized) & set(self._blocks):
            raise ValueError("logical block is already physically owned")
        if any(
            block_id in reservation.block_ids
            for reservation in self._recovery.values()
            for block_id in normalized
        ):
            raise ValueError("logical block is already recovery-reserved")
        return normalized

    def _normalize_existing_blocks(
        self, block_ids: tuple[int, ...], *, request_id: str
    ) -> tuple[int, ...]:
        normalized = tuple(block_ids)
        if len(normalized) != len(set(normalized)):
            raise ValueError("released logical block IDs must be unique")
        for block_id in normalized:
            allocation = self._blocks.get(block_id)
            if allocation is None or allocation.request_id != request_id:
                raise ValueError("released logical block lacks matching physical owner")
        return normalized

    def _delta(
        self,
        allocation: _SourceAllocation,
        *,
        account_from: str,
        account_to: str,
    ) -> AllocationDelta:
        return AllocationDelta(
            resource_id=self.ledger.resource_id,
            account_from=account_from,
            account_to=account_to,
            delta_bytes=self.source_chunk_bytes,
            allocation_id=allocation.allocation_id,
            object_id=f"request:{allocation.request_id}",
        )

    def _commit(self, deltas: list[AllocationDelta], *, cause: str) -> None:
        if not deltas:
            return
        self._operation_sequence += 1
        ResourceTransaction(
            event_id=f"{self.authority_id}:op:{self._operation_sequence:08d}",
            timestamp_ns=self._now_ns(),
            cause=cause,
            allocation_deltas=deltas,
        ).commit(self.ledgers, journal=self.journal)
        if self._on_commit is not None:
            self._on_commit(cause)

    def _preflight(self, deltas: list[AllocationDelta]) -> None:
        timestamp_ns = self._now_ns()
        if timestamp_ns < 0:
            raise ValueError("HBM authority transaction time must be non-negative")
        last_timestamp_ns = self.journal.last_timestamp_ns
        if last_timestamp_ns is not None and timestamp_ns < last_timestamp_ns:
            raise ValueError("transaction timestamp would move journal backwards")
        self.ledger.preview([delta.as_transfer() for delta in deltas])

    def _require_available(self) -> None:
        if self._failed:
            raise ExperimentHBMAuthorityError("failed HBM authority is immutable")


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


__all__ = ["ExperimentHBMAuthority", "ExperimentHBMAuthorityError"]
