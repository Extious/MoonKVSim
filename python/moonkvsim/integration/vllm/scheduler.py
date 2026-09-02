"""Deterministic, tensor-free core of the source-locked vLLM V1 scheduler.

This module preserves only the ordinary decoder-only continuous-batching path
from ``vllm/v1/core/sched/scheduler.py::Scheduler.schedule`` at the pinned
commit.  It is static E1 evidence, not a differential or runtime parity claim.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol

from moonkvsim.integration.vllm.block_hash import (
    BlockHashWitness,
    hash_full_block_witnesses,
)
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.request import Request, RequestStatus

VLLM_SOURCE_COMMIT = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
VLLM_SCHEDULER_SHA256 = "cba4e57618c38bd3b0fc97eadc5a7bbad78d8304617cb2241b2f0ea2c4b8a623"
VLLM_SCHEDULE_SYMBOL = "vllm/v1/core/sched/scheduler.py::Scheduler.schedule"
EVIDENCE_CLASS = "E1"

FIDELITY_GAPS = (
    "GAP-001:pinned E2 CPU differential covers only two ordinary FCFS scheduler/block traces",
    "per-GPU HBM block-ledger bridge is E1/E2-toy only, not a pinned-vLLM trace pass",
    "fork-specific DDTree and speculative decoding are not modeled",
    "LoRA admission constraints are not modeled",
    "multimodal and encoder compute/cache budgets are not modeled",
    "prefix caching, KV connectors, hybrid caches, and priority policy are not modeled",
)


class SchedulingOrigin(StrEnum):
    RUNNING = "RUNNING"
    NEW = "NEW"
    RESUMED = "RESUMED"


class SchedulingPhase(StrEnum):
    PREFILL = "PREFILL"
    DECODE = "DECODE"


class SchedulerInvariantError(RuntimeError):
    """Raised when scheduler/request/block state no longer has one interpretation."""


class BlockLifecycleObserver(Protocol):
    """Optional physical-capacity boundary for ordinary vLLM KV blocks.

    Implementations must reject an allocation before mutating their own state.
    The scheduler invokes allocation before changing pool/request ownership and
    invokes release before returning a block to the free pool.
    """

    @property
    def num_free_blocks(self) -> int: ...

    def num_free_blocks_for_request(self, request_id: str) -> int:
        """Return pages this request can allocate without stealing active KV."""

        ...

    def try_reclaim_blocks(self, request_id: str, required_blocks: int) -> bool:
        """Try to establish physical capacity before recompute preemption."""

        ...

    def validate_scheduler_layout(
        self, *, block_size_tokens: int, usable_block_capacity: int
    ) -> None: ...

    def allocate_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
        evicted_cache_hashes: Mapping[int, str] | None = None,
    ) -> None: ...

    def activate_cached_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        request_id: str,
        cause: str,
    ) -> None: ...

    def mark_cacheable_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        cause: str,
    ) -> None: ...

    def release_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None: ...

    def reserve_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> tuple[tuple[str, ...], ...]: ...

    def commit_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None: ...

    def abort_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None: ...

    def audit_scheduler_blocks(
        self,
        block_ref_counts: Mapping[int, int],
        cached_block_hashes: Mapping[int, str],
        reserved_block_ids: set[int],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ScheduledRequest:
    request_id: str
    origin: SchedulingOrigin
    phase: SchedulingPhase
    num_scheduled_tokens: int
    num_computed_tokens_before: int
    num_computed_tokens_after: int
    new_block_ids: tuple[int, ...]
    block_ids: tuple[int, ...]
    local_cache_hit_tokens: int = 0
    local_cache_hit_block_ids: tuple[int, ...] = ()
    recompute: bool = False
    chunked: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["origin"] = self.origin.value
        value["phase"] = self.phase.value
        return value


@dataclass(frozen=True, slots=True)
class RecoveryPrefixReservation:
    """Block-pool/HBM hold created before a recovery Store GET."""

    request_id: str
    restored_tokens: int
    block_ids: tuple[int, ...]
    destination_allocation_ids: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("recovery reservation request_id must be non-empty")
        if self.restored_tokens <= 0:
            raise ValueError("recovery reservation tokens must be positive")
        if not self.block_ids or len(self.block_ids) != len(self.destination_allocation_ids):
            raise ValueError("recovery reservation must bind every logical block")
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("recovery reservation block IDs must be unique")
        if any(
            not allocation_ids
            or any(not allocation_id for allocation_id in allocation_ids)
            or len(set(allocation_ids)) != len(allocation_ids)
            for allocation_ids in self.destination_allocation_ids
        ):
            raise ValueError("every recovery block must bind unique physical allocations")
        allocation_group_by_id: dict[str, tuple[str, ...]] = {}
        positions_by_group: dict[tuple[str, ...], list[int]] = {}
        for block_index, allocation_ids in enumerate(self.destination_allocation_ids):
            positions_by_group.setdefault(allocation_ids, []).append(block_index)
            for allocation_id in allocation_ids:
                previous_group = allocation_group_by_id.setdefault(
                    allocation_id, allocation_ids
                )
                if previous_group != allocation_ids:
                    raise ValueError(
                        "one physical recovery allocation belongs to conflicting groups"
                    )
        for positions in positions_by_group.values():
            if positions != list(range(positions[0], positions[-1] + 1)):
                raise ValueError(
                    "shared physical recovery allocations must cover contiguous blocks"
                )

    @property
    def physical_allocation_ids(self) -> frozenset[str]:
        """Return unique physical destinations, collapsing rounded page aliases."""

        return frozenset(
            allocation_id
            for allocation_ids in self.destination_allocation_ids
            for allocation_id in allocation_ids
        )


@dataclass(frozen=True, slots=True)
class SchedulerOutput:
    """Deterministic scheduler result corresponding to one model-execution step."""

    scheduled_new_reqs: tuple[ScheduledRequest, ...]
    scheduled_resumed_reqs: tuple[ScheduledRequest, ...]
    scheduled_running_reqs: tuple[ScheduledRequest, ...]
    num_scheduled_tokens: dict[str, int]
    total_num_scheduled_tokens: int
    token_budget_remaining: int
    preempted_req_ids: tuple[str, ...]
    preemption_details: tuple[dict[str, Any], ...] = ()
    evidence_class: str = EVIDENCE_CLASS
    source_commit: str = VLLM_SOURCE_COMMIT
    source_sha256: str = VLLM_SCHEDULER_SHA256
    source_symbol: str = VLLM_SCHEDULE_SYMBOL
    fidelity_gaps: tuple[str, ...] = FIDELITY_GAPS

    @property
    def scheduled_cached_reqs(self) -> tuple[ScheduledRequest, ...]:
        """Pinned output groups already-known RUNNING and resumed requests."""

        return self.scheduled_running_reqs + self.scheduled_resumed_reqs

    @property
    def scheduled_req_ids(self) -> tuple[str, ...]:
        """Return actual scheduling order: RUNNING, then NEW/RESUMED waiting work."""

        return tuple(self.num_scheduled_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled_new_reqs": [item.to_dict() for item in self.scheduled_new_reqs],
            "scheduled_resumed_reqs": [item.to_dict() for item in self.scheduled_resumed_reqs],
            "scheduled_running_reqs": [item.to_dict() for item in self.scheduled_running_reqs],
            "num_scheduled_tokens": dict(self.num_scheduled_tokens),
            "total_num_scheduled_tokens": self.total_num_scheduled_tokens,
            "token_budget_remaining": self.token_budget_remaining,
            "preempted_req_ids": list(self.preempted_req_ids),
            "preemption_details": [dict(item) for item in self.preemption_details],
            "evidence_class": self.evidence_class,
            "source_commit": self.source_commit,
            "source_sha256": self.source_sha256,
            "source_symbol": self.source_symbol,
            "fidelity_gaps": list(self.fidelity_gaps),
        }

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()


class ContinuousBatchScheduler:
    """FCFS continuous batching with explicit KV-block ownership.

    Model outputs are deliberately external to ``schedule``.  Call
    :meth:`append_output_tokens` after a model step to materialize decode tokens;
    the next schedule call allocates and computes those tokens exactly as the
    pinned scheduler closes the ``num_tokens - num_computed_tokens`` gap.
    """

    def __init__(
        self,
        *,
        block_pool: BlockPool,
        block_size_tokens: int,
        max_num_scheduled_tokens: int,
        max_num_running_requests: int,
        long_prefill_token_threshold: int = 0,
        enable_chunked_prefill: bool = True,
        policy: str = "fcfs",
        block_lifecycle_observer: BlockLifecycleObserver | None = None,
        prefix_hash_seed: str | None = None,
        eager_audit: bool = True,
    ) -> None:
        _require_positive_int(block_size_tokens, "block_size_tokens")
        _require_positive_int(max_num_scheduled_tokens, "max_num_scheduled_tokens")
        _require_positive_int(max_num_running_requests, "max_num_running_requests")
        if type(long_prefill_token_threshold) is not int or long_prefill_token_threshold < 0:
            raise ValueError("long_prefill_token_threshold must be a non-negative integer")
        if type(enable_chunked_prefill) is not bool:
            raise TypeError("enable_chunked_prefill must be bool")
        if policy != "fcfs":
            raise ValueError("only source-locked FCFS policy is modeled at E1")
        if block_pool.enable_caching and not prefix_hash_seed:
            raise ValueError("prefix caching requires an explicit deterministic prefix_hash_seed")
        if not block_pool.enable_caching and prefix_hash_seed is not None:
            raise ValueError("prefix_hash_seed is valid only when prefix caching is enabled")
        if type(eager_audit) is not bool:
            raise TypeError("eager_audit must be bool")

        self.block_pool = block_pool
        self.block_size_tokens = block_size_tokens
        self.max_num_scheduled_tokens = max_num_scheduled_tokens
        self.max_num_running_requests = max_num_running_requests
        self.long_prefill_token_threshold = long_prefill_token_threshold
        self.enable_chunked_prefill = enable_chunked_prefill
        self.policy = policy
        self.block_lifecycle_observer = block_lifecycle_observer
        self.prefix_hash_seed = prefix_hash_seed
        self.eager_audit = eager_audit
        if block_lifecycle_observer is not None:
            block_lifecycle_observer.validate_scheduler_layout(
                block_size_tokens=block_size_tokens,
                usable_block_capacity=len(block_pool.blocks) - 1,
            )
        self._waiting: deque[Request] = deque()
        self._running: list[Request] = []
        self._requests: dict[str, Request] = {}
        self._request_blocks: dict[str, list[int]] = {}
        self._request_prefix_witnesses: dict[str, tuple[BlockHashWitness, ...]] = {}
        self._remote_prefix_ready_tokens: dict[str, int] = {}
        self._recovery_priority_request_ids: set[str] = set()
        self._recovery_prefix_reservations: dict[str, RecoveryPrefixReservation] = {}
        self._terminal_output_request_ids: set[str] = set()
        self._audit_state()

    @property
    def running_request_ids(self) -> tuple[str, ...]:
        return tuple(request.request_id for request in self._running)

    @property
    def waiting_request_ids(self) -> tuple[str, ...]:
        return tuple(request.request_id for request in self._waiting)

    @property
    def queued_tokens(self) -> int:
        """Return the remaining materialized tokens in this scheduler only.

        The external DP router consumes this value as an immutable snapshot.  It
        does not make the scheduler share queues or ownership with another DP
        rank.
        """

        self._audit_state()
        return sum(self._remaining_tokens(request) for request in (*self._running, *self._waiting))

    def request_block_ids(self, request_id: str) -> tuple[int, ...]:
        self._require_known_request(request_id)
        return tuple(self._request_blocks.get(request_id, ()))

    def recovery_prefix_reservation(self, request_id: str) -> RecoveryPrefixReservation:
        try:
            return self._recovery_prefix_reservations[request_id]
        except KeyError as error:
            raise KeyError(f"request has no recovery prefix reservation: {request_id}") from error

    def reserve_recovery_prefix(
        self,
        request_id: str,
        *,
        restored_tokens: int,
    ) -> RecoveryPrefixReservation:
        """Reserve scheduler blocks and physical HBM before Store GET starts."""

        self._audit_state()
        if not request_id:
            raise ValueError("recovery reservation request_id must be non-empty")
        if request_id in self._requests or request_id in self._recovery_prefix_reservations:
            raise ValueError("request already owns scheduler or recovery-reservation state")
        if type(restored_tokens) is not int or restored_tokens <= 0:
            raise ValueError("restored_tokens must be a positive integer")
        if restored_tokens % self.block_size_tokens != 0:
            raise ValueError("recovery reservation must contain whole KV blocks")
        block_count = restored_tokens // self.block_size_tokens
        if block_count > self._num_free_blocks_for_request(request_id):
            raise ValueError("insufficient scheduler/HBM capacity for recovery reservation")
        observer = self.block_lifecycle_observer
        if observer is None:
            raise ValueError("recovery destination reservation requires a physical HBM observer")

        preview_ids = self.block_pool.peek_allocatable_block_ids(block_count)
        destination_ids = observer.reserve_recovery_blocks(
            preview_ids,
            request_id=request_id,
            cause="vllm.recovery-prefix",
        )
        pool_allocated = False
        try:
            allocated = self.block_pool.allocate(block_count)
            pool_allocated = True
            if tuple(block.block_id for block in allocated) != preview_ids:
                raise SchedulerInvariantError(
                    "recovery block-pool allocation diverged from its preview"
                )
            reservation = RecoveryPrefixReservation(
                request_id=request_id,
                restored_tokens=restored_tokens,
                block_ids=preview_ids,
                destination_allocation_ids=destination_ids,
            )
            self._validate_recovery_allocation_ids_available(reservation)
            self._recovery_prefix_reservations[request_id] = reservation
        except Exception:
            if pool_allocated:
                self.block_pool.free(reversed(preview_ids))
            observer.abort_recovery_blocks(
                preview_ids,
                request_id=request_id,
                cause="vllm.recovery-prefix:local-rollback",
            )
            raise
        self._audit_state()
        return reservation

    def validate_recovery_prefix_commit(
        self,
        request: Request,
        reservation: RecoveryPrefixReservation,
    ) -> None:
        """Preflight the no-allocation commit used after all Store GETs finish."""

        self._audit_state()
        current = self.recovery_prefix_reservation(request.request_id)
        if current != reservation:
            raise ValueError("recovery reservation binding changed before commit")
        if request.status is not RequestStatus.WAITING:
            raise ValueError("recovery commit requires a fresh WAITING request")
        if request.num_computed_tokens or request.num_output_tokens or request.num_preemptions:
            raise ValueError("recovery commit requires fresh request counters")
        if reservation.restored_tokens > request.prompt_tokens:
            raise ValueError("restored prefix cannot exceed the prompt")
        if len(self._running) >= self.max_num_running_requests:
            raise ValueError("no running-request slot is available for recovery commit")
        effective_tokens = (
            reservation.restored_tokens - 1
            if reservation.restored_tokens == request.num_tokens
            else reservation.restored_tokens
        )
        if effective_tokens <= 0:
            raise ValueError("full restored prefix must leave a token to recompute")
        if len(reservation.block_ids) != _ceil_div(effective_tokens, self.block_size_tokens):
            raise SchedulerInvariantError(
                "recovery reservation block count disagrees with computed prefix"
            )

    def commit_recovery_prefix(
        self,
        request: Request,
        reservation: RecoveryPrefixReservation,
    ) -> None:
        """Promote a completed recovery destination RESERVED -> ACTIVE once."""

        self.validate_recovery_prefix_commit(request, reservation)
        effective_tokens = (
            reservation.restored_tokens - 1
            if reservation.restored_tokens == request.num_tokens
            else reservation.restored_tokens
        )
        observer = self.block_lifecycle_observer
        if observer is None:
            raise SchedulerInvariantError("recovery reservation lost its HBM observer")
        witnesses = self._build_request_prefix_witnesses(request)
        observer.commit_recovery_blocks(
            reservation.block_ids,
            request_id=request.request_id,
            cause="vllm.recovery-prefix",
        )
        self._requests[request.request_id] = request
        self._request_blocks[request.request_id] = list(reservation.block_ids)
        self._request_prefix_witnesses[request.request_id] = witnesses
        request.mark_running()
        request.record_computed_tokens(effective_tokens)
        self._cache_computed_prompt_blocks(request)
        self._running.append(request)
        del self._recovery_prefix_reservations[request.request_id]
        self._audit_state()

    def abort_recovery_prefix(self, request_id: str, *, cause: str) -> None:
        """Release an uncommitted recovery destination without double charging."""

        self._audit_state()
        if not cause:
            raise ValueError("recovery reservation abort cause must be non-empty")
        reservation = self.recovery_prefix_reservation(request_id)
        observer = self.block_lifecycle_observer
        if observer is None:
            raise SchedulerInvariantError("recovery reservation lost its HBM observer")
        observer.abort_recovery_blocks(
            reservation.block_ids,
            request_id=request_id,
            cause=cause,
        )
        self.block_pool.free(reversed(reservation.block_ids))
        del self._recovery_prefix_reservations[request_id]
        self._audit_state()

    def add_request(self, request: Request) -> None:
        """Append one fresh WAITING request to the deterministic FCFS queue."""

        self._audit_state()
        if request.request_id in self._requests:
            raise ValueError(f"duplicate request_id: {request.request_id}")
        if request.status is not RequestStatus.WAITING:
            raise ValueError("only a fresh WAITING request can be added")
        self._validate_request_counters(request)
        if request.num_tokens == 0:
            raise ValueError("an empty materialized prompt cannot enter this scheduler core")
        self._requests[request.request_id] = request
        self._request_blocks[request.request_id] = []
        self._request_prefix_witnesses[request.request_id] = self._build_request_prefix_witnesses(
            request
        )
        self._waiting.append(request)
        self._audit_state()

    def prioritize_waiting_recovery(self, request_id: str) -> None:
        """Place one failure-requeued request ahead of ordinary waiting work."""

        self._audit_state()
        request = self._require_known_request(request_id)
        if request not in self._waiting or request.status not in {
            RequestStatus.WAITING,
            RequestStatus.WAITING_FOR_REMOTE_KVS,
        }:
            raise ValueError("recovery priority requires an admitted waiting request")
        self._recovery_priority_request_ids.add(request_id)
        self._waiting.remove(request)
        priority_owner_count = sum(
            item.request_id in self._recovery_priority_request_ids for item in self._waiting
        )
        self._waiting.insert(priority_owner_count, request)
        self._audit_state()

    def restore_request_prefix(self, request: Request, *, restored_tokens: int) -> None:
        """Admit a request with an explicitly restored, block-aligned KV prefix.

        This is the tensor-free remote-KV handoff boundary.  The caller must
        first prove that the bytes were loaded; this method only materializes
        the corresponding scheduler/block-pool ownership.  It deliberately
        rejects partial blocks because their slot-level layout is not modeled.
        """

        self._audit_state()
        if request.request_id in self._requests:
            raise ValueError(f"duplicate request_id: {request.request_id}")
        if request.status is not RequestStatus.WAITING:
            raise ValueError("only a fresh WAITING request can restore a prefix")
        if type(restored_tokens) is not int or restored_tokens <= 0:
            raise ValueError("restored_tokens must be a positive integer")
        if restored_tokens > request.prompt_tokens:
            raise ValueError("restored prefix cannot exceed the prompt")
        if restored_tokens % self.block_size_tokens != 0:
            raise ValueError("restored prefix must contain whole KV blocks")
        self._validate_request_counters(request)
        if (
            request.num_computed_tokens != 0
            or request.num_output_tokens != 0
            or request.num_preemptions != 0
        ):
            raise ValueError("restored prefix requires fresh request counters")
        if len(self._running) >= self.max_num_running_requests:
            raise ValueError("no running-request slot is available for direct restore")
        effective_tokens = (
            restored_tokens - 1 if restored_tokens == request.num_tokens else restored_tokens
        )
        if effective_tokens <= 0:
            raise ValueError("full restored prefix must leave a token to recompute")
        required_blocks = restored_tokens // self.block_size_tokens
        if required_blocks > self._num_free_blocks_for_request(request.request_id):
            raise ValueError("insufficient free KV blocks for the restored prefix")

        witnesses = self._build_request_prefix_witnesses(request)
        preview_ids = self.block_pool.peek_allocatable_block_ids(required_blocks)
        self._observe_allocate(
            preview_ids,
            request_id=request.request_id,
            cause="vllm.restore-prefix",
        )
        allocated = self.block_pool.allocate(required_blocks)
        if tuple(block.block_id for block in allocated) != preview_ids:
            raise SchedulerInvariantError("block-pool allocation diverged from its preview")
        self._requests[request.request_id] = request
        self._request_blocks[request.request_id] = [block.block_id for block in allocated]
        self._request_prefix_witnesses[request.request_id] = witnesses
        request.mark_running()
        request.record_computed_tokens(effective_tokens)
        self._cache_computed_prompt_blocks(request)
        self._running.append(request)
        self._audit_state()

    def restore_waiting_request_prefix(self, request_id: str, *, restored_tokens: int) -> None:
        """Record a fetched prefix without bypassing ordinary admission.

        The Store/transfer owner must invoke this only after all bytes have
        completed successfully.  The request remains in the waiting deque and
        in ``WAITING_FOR_REMOTE_KVS`` until :meth:`schedule` traverses it.  That
        traversal promotes it to ``WAITING``/``PREEMPTED`` and only then applies
        the normal running-slot, token-budget, and HBM-allocation checks.

        A full prompt hit follows the pinned vLLM connector rule and recomputes
        the last prompt token so the model step can sample the first output.
        ``restored_tokens`` records bytes proven by Store; the internal ready
        counter therefore becomes ``prompt_tokens - 1`` for a full hit.
        """

        self._audit_state()
        request = self._require_known_request(request_id)
        if (
            request.status is not RequestStatus.WAITING_FOR_REMOTE_KVS
            or request not in self._waiting
        ):
            raise ValueError(
                "restored remote prefix requires an admitted WAITING_FOR_REMOTE_KVS request"
            )
        if type(restored_tokens) is not int or restored_tokens <= 0:
            raise ValueError("restored_tokens must be a positive integer")
        if restored_tokens > request.prompt_tokens:
            raise ValueError("restored prefix cannot exceed the prompt")
        if restored_tokens % self.block_size_tokens != 0:
            raise ValueError("restored prefix must contain whole KV blocks")
        if request.num_computed_tokens != 0 or request.num_output_tokens != 0:
            raise ValueError("restored waiting prefix requires fresh request counters")
        if request_id in self._remote_prefix_ready_tokens:
            raise ValueError("remote prefix completion was already recorded")
        effective_tokens = (
            restored_tokens - 1 if restored_tokens == request.num_tokens else restored_tokens
        )
        if effective_tokens <= 0:
            raise ValueError("full remote prefix must leave a token to recompute")
        self._remote_prefix_ready_tokens[request_id] = effective_tokens
        self._waiting.remove(request)
        ready_owner_count = sum(
            item.request_id in self._recovery_priority_request_ids
            or item.request_id in self._remote_prefix_ready_tokens
            for item in self._waiting
        )
        self._waiting.insert(ready_owner_count, request)
        self._audit_state()

    def mark_waiting_for_remote_kv(self, request_id: str) -> None:
        """Move one admitted fresh request into pinned remote-KV wait state.

        The request remains in the FCFS waiting deque so its position is
        observable, but :meth:`schedule` skips it until the Store owner proves
        completion through :meth:`restore_waiting_request_prefix`.
        """

        self._audit_state()
        request = self._require_known_request(request_id)
        if request not in self._waiting:
            raise ValueError("remote KV wait requires an admitted waiting request")
        if request.num_computed_tokens != 0 or request.num_output_tokens != 0:
            raise ValueError("remote KV wait requires fresh request counters")
        if request_id in self._remote_prefix_ready_tokens:
            raise ValueError("remote prefix completion is already recorded")
        request.wait_for_remote_kv()
        self._audit_state()

    def rollback_unstarted_request(self, request_id: str) -> Request:
        """Undo a coordinator admission that never reached model execution.

        This is a narrow exception-safety boundary for composed recovery.  It
        may remove only a fresh waiting request with no computed/output tokens,
        KV blocks, or terminal-output pin.  Ordinary admitted/running requests
        must continue to use :meth:`finish_request` so physical block release
        remains observable.
        """

        self._audit_state()
        request = self._require_known_request(request_id)
        if request not in self._waiting or request.status not in {
            RequestStatus.WAITING,
            RequestStatus.WAITING_FOR_REMOTE_KVS,
        }:
            raise ValueError("only an unstarted waiting request may be rolled back")
        if (
            request.num_computed_tokens != 0
            or request.num_output_tokens != 0
            or request.num_preemptions != 0
            or self._request_blocks[request_id]
            or request_id in self._terminal_output_request_ids
        ):
            raise SchedulerInvariantError(
                "unstarted-request rollback found materialized scheduler state"
            )
        self._waiting.remove(request)
        self._remote_prefix_ready_tokens.pop(request_id, None)
        self._recovery_priority_request_ids.discard(request_id)
        del self._request_blocks[request_id]
        del self._request_prefix_witnesses[request_id]
        del self._requests[request_id]
        request.finish(RequestStatus.FINISHED_ABORTED)
        self._audit_state()
        return request

    def append_output_tokens(
        self,
        request_id: str,
        count: int = 1,
        *,
        terminal: bool = False,
        audit: bool = True,
    ) -> None:
        """Apply tensor-free model output before its next decode allocation."""

        if audit:
            self._audit_state()
        request = self._require_known_request(request_id)
        if type(terminal) is not bool:
            raise TypeError("terminal must be bool")
        if terminal and count != 1:
            raise ValueError("terminal model output must contain exactly one token")
        if terminal and request.num_output_tokens + count != request.max_output_tokens:
            raise ValueError("terminal output must reach the request output reserve")
        request.append_output_tokens(count)
        if terminal:
            self._terminal_output_request_ids.add(request_id)
        if audit:
            self._audit_state()

    def finish_request(self, request_id: str, status: RequestStatus) -> None:
        """Remove a request and release its KV blocks in pinned reverse order."""

        self._audit_state()
        if not status.finished:
            raise ValueError("finish_request requires a terminal RequestStatus")
        request = self._require_known_request(request_id)
        if request.status not in {
            RequestStatus.RUNNING,
            RequestStatus.WAITING,
            RequestStatus.WAITING_FOR_REMOTE_KVS,
            RequestStatus.PREEMPTED,
        }:
            raise ValueError(f"unsupported finish source state: {request.status.name}")
        self._free_request_blocks(
            request_id,
            cause=f"vllm.finish:{status.name.lower()}",
        )
        if request.status is RequestStatus.RUNNING:
            self._running.remove(request)
        else:
            self._waiting.remove(request)
        self._remote_prefix_ready_tokens.pop(request_id, None)
        self._recovery_priority_request_ids.discard(request_id)
        self._terminal_output_request_ids.discard(request_id)
        request.finish(status)
        self._audit_state()

    def audit(self) -> None:
        """Run the complete scheduler, block-pool, and observer invariant set."""

        self._audit_state(force=True)

    def schedule(self) -> SchedulerOutput:
        """Schedule one deterministic token-budgeted continuous-batching step."""

        self._audit_state()
        scheduled_new: list[ScheduledRequest] = []
        scheduled_resumed: list[ScheduledRequest] = []
        scheduled_running: list[ScheduledRequest] = []
        preempted_request_ids: list[str] = []
        preemption_details: list[dict[str, Any]] = []
        num_scheduled_tokens: dict[str, int] = {}
        token_budget = self.max_num_scheduled_tokens

        if (
            self._waiting
            and self._waiting[0].request_id in self._recovery_priority_request_ids
            and len(self._running) == self.max_num_running_requests
        ):
            victim_index = next(
                (
                    index
                    for index in range(len(self._running) - 1, -1, -1)
                    if self._running[index].request_id
                    not in self._terminal_output_request_ids
                ),
                None,
            )
            if victim_index is not None:
                victim = self._running.pop(victim_index)
                free_evidence = self._free_block_evidence(
                    self._waiting[0].request_id
                )
                preemption_details.append(
                    {
                        "reason": "RECOVERY_RUNNING_SLOT",
                        "trigger_request_id": self._waiting[0].request_id,
                        "victim_request_id": victim.request_id,
                        "required_blocks": 0,
                        "free_blocks_before_reclaim": free_evidence["effective_free"],
                        "free_blocks_after_reclaim": free_evidence["effective_free"],
                        "logical_blocks_before_reclaim": free_evidence[
                            "logical_block_pool_free"
                        ],
                        "logical_blocks_after_reclaim": free_evidence[
                            "logical_block_pool_free"
                        ],
                        "physical_blocks_before_reclaim": free_evidence[
                            "physical_authority_free"
                        ],
                        "physical_blocks_after_reclaim": free_evidence[
                            "physical_authority_free"
                        ],
                    }
                )
                self._preempt_for_recompute(victim)
                preempted_request_ids.append(victim.request_id)

        request_index = 0
        while (
            not preempted_request_ids
            and request_index < len(self._running)
            and token_budget > 0
        ):
            request = self._running[request_index]
            remaining_tokens = self._remaining_tokens(request)
            if remaining_tokens == 0:
                request_index += 1
                continue
            num_new_tokens = self._limited_tokens(remaining_tokens, token_budget)
            required_blocks = self._new_blocks_needed(request, num_new_tokens)
            current_was_preempted = False

            free_before = self._free_block_evidence(request.request_id)
            self._try_reclaim_blocks(request.request_id, required_blocks)
            free_after = self._free_block_evidence(request.request_id)
            while required_blocks > self._num_free_blocks_for_request(
                request.request_id
            ):
                victim_index = next(
                    (
                        index
                        for index in range(len(self._running) - 1, -1, -1)
                        if self._running[index].request_id
                        not in self._terminal_output_request_ids
                    ),
                    None,
                )
                if victim_index is None:
                    raise SchedulerInvariantError(
                        "all KV-pressure victims are pinned for terminal Store save"
                    )
                victim = self._running.pop(victim_index)
                if victim.request_id in num_scheduled_tokens:
                    raise SchedulerInvariantError(
                        "FCFS preemption selected a request scheduled earlier in this step"
                    )
                preemption_details.append(
                    {
                        "reason": "KV_BLOCK_PRESSURE",
                        "trigger_request_id": request.request_id,
                        "victim_request_id": victim.request_id,
                        "required_blocks": required_blocks,
                        "free_blocks_before_reclaim": free_before["effective_free"],
                        "free_blocks_after_reclaim": free_after["effective_free"],
                        "logical_blocks_before_reclaim": free_before[
                            "logical_block_pool_free"
                        ],
                        "logical_blocks_after_reclaim": free_after[
                            "logical_block_pool_free"
                        ],
                        "physical_blocks_before_reclaim": free_before[
                            "physical_authority_free"
                        ],
                        "physical_blocks_after_reclaim": free_after[
                            "physical_authority_free"
                        ],
                    }
                )
                self._preempt_for_recompute(victim)
                preempted_request_ids.append(victim.request_id)
                if victim is request:
                    current_was_preempted = True
                    break

            if current_was_preempted:
                break

            item = self._schedule_request(
                request,
                num_new_tokens,
                remaining_tokens,
                SchedulingOrigin.RUNNING,
            )
            scheduled_running.append(item)
            num_scheduled_tokens[request.request_id] = num_new_tokens
            token_budget -= num_new_tokens
            request_index += 1

        if not preempted_request_ids:
            waiting_index = 0
            while waiting_index < len(self._waiting) and token_budget > 0:
                if len(self._running) == self.max_num_running_requests:
                    break
                request = self._waiting[waiting_index]
                if (
                    request.status is RequestStatus.WAITING_FOR_REMOTE_KVS
                    and not self._try_promote_remote_prefix(request)
                ):
                    waiting_index += 1
                    continue
                local_hit_blocks = self._lookup_local_prefix(request)
                local_hit_tokens = len(local_hit_blocks) * self.block_size_tokens
                effective_computed_tokens = request.num_computed_tokens + local_hit_tokens
                remaining_tokens = request.num_tokens - effective_computed_tokens
                if remaining_tokens <= 0:
                    raise SchedulerInvariantError(
                        "WAITING request has no materialized tokens left to compute"
                    )
                threshold_limited = self._apply_long_prefill_threshold(remaining_tokens)
                if not self.enable_chunked_prefill and threshold_limited > token_budget:
                    break
                num_new_tokens = min(threshold_limited, token_budget)
                required_blocks = (
                    _ceil_div(
                        effective_computed_tokens + num_new_tokens,
                        self.block_size_tokens,
                    )
                    - len(self._request_blocks[request.request_id])
                    - len(local_hit_blocks)
                )
                inactive_hit_count = sum(
                    self.block_pool.blocks[block_id].ref_count == 0 for block_id in local_hit_blocks
                )
                self._try_reclaim_blocks(
                    request.request_id,
                    required_blocks + inactive_hit_count,
                )
                if (
                    required_blocks
                    > self._num_free_blocks_for_request(request.request_id)
                    - inactive_hit_count
                ):
                    break

                previous_status = request.status
                origin = (
                    SchedulingOrigin.NEW
                    if previous_status is RequestStatus.WAITING
                    else SchedulingOrigin.RESUMED
                )
                self._attach_local_prefix(request, local_hit_blocks)
                item = self._schedule_request(
                    request,
                    num_new_tokens,
                    remaining_tokens,
                    origin,
                    local_cache_hit_block_ids=local_hit_blocks,
                )
                queued = self._waiting[waiting_index]
                if queued is not request:
                    raise SchedulerInvariantError("waiting queue changed during allocation")
                del self._waiting[waiting_index]
                self._running.append(request)
                self._remote_prefix_ready_tokens.pop(request.request_id, None)
                self._recovery_priority_request_ids.discard(request.request_id)
                if origin is SchedulingOrigin.NEW:
                    scheduled_new.append(item)
                else:
                    scheduled_resumed.append(item)
                num_scheduled_tokens[request.request_id] = num_new_tokens
                token_budget -= num_new_tokens

        total_num_scheduled_tokens = sum(num_scheduled_tokens.values())
        if total_num_scheduled_tokens + token_budget != self.max_num_scheduled_tokens:
            raise SchedulerInvariantError("global token budget does not conserve")
        if len(self._running) > self.max_num_running_requests:
            raise SchedulerInvariantError("running-request limit exceeded")
        self._audit_state()

        return SchedulerOutput(
            scheduled_new_reqs=tuple(scheduled_new),
            scheduled_resumed_reqs=tuple(scheduled_resumed),
            scheduled_running_reqs=tuple(scheduled_running),
            num_scheduled_tokens=num_scheduled_tokens,
            total_num_scheduled_tokens=total_num_scheduled_tokens,
            token_budget_remaining=token_budget,
            preempted_req_ids=tuple(preempted_request_ids),
            preemption_details=tuple(preemption_details),
        )

    def _schedule_request(
        self,
        request: Request,
        num_new_tokens: int,
        remaining_tokens: int,
        origin: SchedulingOrigin,
        local_cache_hit_block_ids: tuple[int, ...] = (),
    ) -> ScheduledRequest:
        computed_before = request.num_computed_tokens
        phase = (
            SchedulingPhase.PREFILL
            if computed_before < request.prompt_tokens
            else SchedulingPhase.DECODE
        )
        new_block_count = self._new_blocks_needed(request, num_new_tokens)
        preview_ids = self.block_pool.peek_allocatable_block_ids(new_block_count)
        self._observe_allocate(
            preview_ids,
            request_id=request.request_id,
            cause=f"vllm.schedule:{phase.value.lower()}:{origin.value.lower()}",
        )
        new_blocks = self.block_pool.allocate(new_block_count) if new_block_count else ()
        if tuple(block.block_id for block in new_blocks) != preview_ids:
            raise SchedulerInvariantError("block-pool allocation diverged from its preview")
        block_ids = self._request_blocks[request.request_id]
        new_block_ids = tuple(block.block_id for block in new_blocks)
        block_ids.extend(new_block_ids)
        if origin is not SchedulingOrigin.RUNNING:
            request.mark_running()
        request.record_computed_tokens(num_new_tokens)
        self._cache_computed_prompt_blocks(request)
        return ScheduledRequest(
            request_id=request.request_id,
            origin=origin,
            phase=phase,
            num_scheduled_tokens=num_new_tokens,
            num_computed_tokens_before=computed_before,
            num_computed_tokens_after=request.num_computed_tokens,
            new_block_ids=new_block_ids,
            block_ids=tuple(block_ids),
            local_cache_hit_tokens=(len(local_cache_hit_block_ids) * self.block_size_tokens),
            local_cache_hit_block_ids=local_cache_hit_block_ids,
            recompute=origin is SchedulingOrigin.RESUMED,
            chunked=num_new_tokens < remaining_tokens,
        )

    def _preempt_for_recompute(self, request: Request) -> None:
        if request.request_id in self._remote_prefix_ready_tokens:
            raise SchedulerInvariantError("RUNNING request retained remote-prefix ready state")
        self._free_request_blocks(
            request.request_id,
            cause="vllm.preempt:recompute",
        )
        request.preempt()
        request.num_computed_tokens = 0
        ready_owner_count = sum(
            item.request_id in self._recovery_priority_request_ids
            or item.request_id in self._remote_prefix_ready_tokens
            for item in self._waiting
        )
        self._waiting.insert(ready_owner_count, request)

    def _free_request_blocks(self, request_id: str, *, cause: str) -> None:
        block_ids = self._request_blocks[request_id]
        if block_ids:
            released_ids = tuple(reversed(block_ids))
            self._observe_release(
                released_ids,
                request_id=request_id,
                cause=cause,
            )
            self.block_pool.free(released_ids)
            block_ids.clear()

    @property
    def _num_free_blocks(self) -> int:
        observer = self.block_lifecycle_observer
        if observer is None:
            return self.block_pool.num_free_blocks
        return min(self.block_pool.num_free_blocks, observer.num_free_blocks)

    def _num_free_blocks_for_request(self, request_id: str) -> int:
        observer = self.block_lifecycle_observer
        if observer is None:
            return self.block_pool.num_free_blocks
        return min(
            self.block_pool.num_free_blocks,
            observer.num_free_blocks_for_request(request_id),
        )

    def _free_block_evidence(self, request_id: str) -> dict[str, int]:
        observer = self.block_lifecycle_observer
        physical = (
            self.block_pool.num_free_blocks
            if observer is None
            else observer.num_free_blocks_for_request(request_id)
        )
        return {
            "logical_block_pool_free": self.block_pool.num_free_blocks,
            "physical_authority_free": physical,
            "effective_free": min(self.block_pool.num_free_blocks, physical),
        }

    def _try_reclaim_blocks(self, request_id: str, required_blocks: int) -> bool:
        if required_blocks <= self._num_free_blocks_for_request(request_id):
            return True
        observer = self.block_lifecycle_observer
        if observer is None:
            return False
        reclaimed = observer.try_reclaim_blocks(request_id, required_blocks)
        if reclaimed and required_blocks > self._num_free_blocks_for_request(request_id):
            raise SchedulerInvariantError(
                "physical reclaim reported success without establishing capacity"
            )
        return reclaimed

    def _observe_allocate(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        if block_ids and self.block_lifecycle_observer is not None:
            evicted_cache_hashes = {
                block_id: block_hash
                for block_id in block_ids
                if (block_hash := self.block_pool.blocks[block_id].block_hash) is not None
            }
            self.block_lifecycle_observer.allocate_blocks(
                block_ids,
                request_id=request_id,
                cause=cause,
                evicted_cache_hashes=evicted_cache_hashes,
            )

    def _observe_release(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        if block_ids and self.block_lifecycle_observer is not None:
            self.block_lifecycle_observer.release_blocks(
                block_ids,
                request_id=request_id,
                cause=cause,
            )

    def _build_request_prefix_witnesses(self, request: Request) -> tuple[BlockHashWitness, ...]:
        if not self.block_pool.enable_caching:
            return ()
        if request.prompt_token_ids is None:
            raise ValueError(
                "prefix-caching requests require exact prompt_token_ids; token counts alone "
                "cannot establish a local HBM cache key"
            )
        seed = self.prefix_hash_seed
        if seed is None:
            raise SchedulerInvariantError("prefix cache lost its deterministic hash seed")
        witnesses = hash_full_block_witnesses(
            request.prompt_token_ids,
            block_size=self.block_size_tokens,
            python_hash_seed=seed,
        )
        for witness in witnesses:
            self.block_pool.validate_hash_witness(
                witness.digest,
                group_id=0,
                witness=witness,
            )
        return witnesses

    def _lookup_local_prefix(self, request: Request) -> tuple[int, ...]:
        """Return a side-effect-free, block-aligned local HBM prefix hit."""

        if not self.block_pool.enable_caching or request.num_computed_tokens:
            return ()
        witnesses = self._request_prefix_witnesses[request.request_id]
        max_hit_blocks = (request.num_tokens - 1) // self.block_size_tokens
        hit_ids: list[int] = []
        for witness in witnesses[:max_hit_blocks]:
            cached = self.block_pool.get_cached(
                witness.digest,
                group_id=0,
                witness=witness,
            )
            if cached is None:
                break
            if cached.block_id in hit_ids:
                raise SchedulerInvariantError(
                    "one request prefix resolved two positions to the same physical block"
                )
            hit_ids.append(cached.block_id)
        return tuple(hit_ids)

    def _attach_local_prefix(
        self,
        request: Request,
        block_ids: tuple[int, ...],
    ) -> None:
        if not block_ids:
            return
        if request.num_computed_tokens or self._request_blocks[request.request_id]:
            raise SchedulerInvariantError("local prefix attachment requires empty request state")
        block_hashes = {
            block_id: self.block_pool.blocks[block_id].block_hash for block_id in block_ids
        }
        if any(block_hash is None for block_hash in block_hashes.values()):
            raise SchedulerInvariantError("local prefix hit lost its cache hash")
        observer = self.block_lifecycle_observer
        if observer is not None:
            observer.activate_cached_blocks(
                {
                    block_id: block_hash
                    for block_id, block_hash in block_hashes.items()
                    if block_hash is not None
                },
                request_id=request.request_id,
                cause="vllm.prefix-cache:touch",
            )
        self.block_pool.touch(block_ids)
        self._request_blocks[request.request_id].extend(block_ids)
        request.num_computed_tokens = len(block_ids) * self.block_size_tokens

    def _cache_computed_prompt_blocks(self, request: Request) -> None:
        if not self.block_pool.enable_caching:
            return
        witnesses = self._request_prefix_witnesses[request.request_id]
        num_full_prompt_blocks = (
            min(
                request.num_computed_tokens,
                request.prompt_tokens,
            )
            // self.block_size_tokens
        )
        block_ids = self._request_blocks[request.request_id]
        newly_cacheable: dict[int, str] = {}
        for block_index in range(num_full_prompt_blocks):
            block_id = block_ids[block_index]
            block = self.block_pool.blocks[block_id]
            witness = witnesses[block_index]
            if block.block_hash is None:
                self.block_pool.cache(
                    block_id,
                    block_hash=witness.digest,
                    group_id=0,
                    witness=witness,
                )
                newly_cacheable[block_id] = witness.digest
            elif block.block_hash != witness.digest or block.hash_witness != witness:
                raise SchedulerInvariantError("request block cache identity drift")
        if newly_cacheable and self.block_lifecycle_observer is not None:
            self.block_lifecycle_observer.mark_cacheable_blocks(
                newly_cacheable,
                cause="vllm.prefix-cache:cache-full-blocks",
            )

    def _remaining_tokens(self, request: Request) -> int:
        if request.request_id in self._terminal_output_request_ids:
            return 0
        computed_tokens = request.num_computed_tokens
        if request.status is RequestStatus.WAITING_FOR_REMOTE_KVS:
            computed_tokens = self._remote_prefix_ready_tokens.get(
                request.request_id,
                computed_tokens,
            )
        remaining = request.num_tokens - computed_tokens
        if remaining < 0:
            raise SchedulerInvariantError("computed tokens exceed materialized tokens")
        return remaining

    def _try_promote_remote_prefix(self, request: Request) -> bool:
        """Promote a completed connector wait, without admitting it RUNNING."""

        effective_tokens = self._remote_prefix_ready_tokens.get(request.request_id)
        if effective_tokens is None:
            return False
        if request.status is not RequestStatus.WAITING_FOR_REMOTE_KVS:
            raise SchedulerInvariantError("remote-prefix promotion has an invalid status")
        if request.num_computed_tokens != 0:
            raise SchedulerInvariantError("remote-prefix promotion is not fresh")
        request.resume_after_remote_kv()
        request.num_computed_tokens = effective_tokens
        return True

    def _limited_tokens(self, remaining_tokens: int, token_budget: int) -> int:
        return min(self._apply_long_prefill_threshold(remaining_tokens), token_budget)

    def _apply_long_prefill_threshold(self, remaining_tokens: int) -> int:
        threshold = self.long_prefill_token_threshold
        if 0 < threshold < remaining_tokens:
            return threshold
        return remaining_tokens

    def _new_blocks_needed(self, request: Request, num_new_tokens: int) -> int:
        if num_new_tokens <= 0:
            raise SchedulerInvariantError("scheduled token count must be positive")
        total_tokens_after = request.num_computed_tokens + num_new_tokens
        target_blocks = _ceil_div(total_tokens_after, self.block_size_tokens)
        current_blocks = len(self._request_blocks[request.request_id])
        if target_blocks < current_blocks:
            raise SchedulerInvariantError("request owns more blocks than its computed tokens")
        return target_blocks - current_blocks

    def _require_known_request(self, request_id: str) -> Request:
        request = self._requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown request_id: {request_id}")
        return request

    def _validate_recovery_allocation_ids_available(
        self, reservation: RecoveryPrefixReservation
    ) -> None:
        for existing in self._recovery_prefix_reservations.values():
            duplicate = (
                reservation.physical_allocation_ids
                & existing.physical_allocation_ids
            )
            if duplicate:
                raise ValueError(
                    "physical recovery allocations are shared across requests: "
                    f"{sorted(duplicate)}"
                )

    def _audit_state(self, *, force: bool = False) -> None:
        if not self.eager_audit and not force:
            return
        try:
            self.block_pool.audit()
        except (RuntimeError, ValueError) as error:
            raise SchedulerInvariantError(f"block pool invariant failed: {error}") from error

        if len(self._running) > self.max_num_running_requests:
            raise SchedulerInvariantError("running-request limit exceeded")

        queued_ids: set[str] = set()
        for request in self._running:
            if request.status is not RequestStatus.RUNNING:
                raise SchedulerInvariantError("running queue contains a non-RUNNING request")
            self._audit_queued_request(request, queued_ids)
        for request in self._waiting:
            if request.status not in {
                RequestStatus.WAITING,
                RequestStatus.WAITING_FOR_REMOTE_KVS,
                RequestStatus.PREEMPTED,
            }:
                raise SchedulerInvariantError("waiting queue contains an unsupported status")
            self._audit_queued_request(request, queued_ids)
            remote_ready_tokens = self._remote_prefix_ready_tokens.get(request.request_id)
            if request.status is RequestStatus.WAITING_FOR_REMOTE_KVS:
                if request.num_computed_tokens != 0:
                    raise SchedulerInvariantError(
                        "WAITING_FOR_REMOTE_KVS request must not publish computed tokens"
                    )
            elif remote_ready_tokens is None and request.num_computed_tokens != 0:
                raise SchedulerInvariantError(
                    "ordinary WAITING/PREEMPTED request must start from zero"
                )
            elif (
                remote_ready_tokens is not None
                and request.num_computed_tokens != remote_ready_tokens
            ):
                raise SchedulerInvariantError(
                    "promoted remote prefix disagrees with its computed-token counter"
                )

        for request_id, effective_tokens in self._remote_prefix_ready_tokens.items():
            ready_request = self._requests.get(request_id)
            if ready_request is None or ready_request not in self._waiting:
                raise SchedulerInvariantError(
                    "remote-prefix ready state is not owned by the waiting queue"
                )
            if ready_request.status not in {
                RequestStatus.WAITING_FOR_REMOTE_KVS,
                RequestStatus.WAITING,
                RequestStatus.PREEMPTED,
            }:
                raise SchedulerInvariantError(
                    "remote-prefix ready state has an unsupported request status"
                )
            if effective_tokens <= 0 or effective_tokens >= ready_request.num_tokens:
                raise SchedulerInvariantError(
                    "remote-prefix ready counter must leave positive suffix work"
                )

        priority_prefix_open = True
        for request in self._waiting:
            prioritized = request.request_id in self._recovery_priority_request_ids
            if prioritized and not priority_prefix_open:
                raise SchedulerInvariantError(
                    "recovery-priority requests must form a waiting-queue prefix"
                )
            if not prioritized:
                priority_prefix_open = False
        for request_id in self._recovery_priority_request_ids:
            priority_request = self._requests.get(request_id)
            if priority_request is None or priority_request not in self._waiting:
                raise SchedulerInvariantError(
                    "recovery-priority state is not owned by the waiting queue"
                )

        for request_id in self._terminal_output_request_ids:
            terminal_request = self._requests.get(request_id)
            if (
                terminal_request is None
                or terminal_request not in self._running
                or terminal_request.status is not RequestStatus.RUNNING
            ):
                raise SchedulerInvariantError(
                    "terminal output pin is not owned by a RUNNING request"
                )
            if terminal_request.num_output_tokens != terminal_request.max_output_tokens:
                raise SchedulerInvariantError(
                    "terminal output pin has not reached the output reserve"
                )
            if terminal_request.num_tokens - terminal_request.num_computed_tokens != 1:
                raise SchedulerInvariantError(
                    "terminal output pin must cover exactly one sampled token"
                )

        for request_id, request in self._requests.items():
            if request.finished:
                if request_id in queued_ids or self._request_blocks.get(request_id):
                    raise SchedulerInvariantError("finished request still owns scheduler state")
            elif request_id not in queued_ids:
                raise SchedulerInvariantError("unfinished request is absent from both queues")
        if set(self._request_prefix_witnesses) != set(self._requests):
            raise SchedulerInvariantError("request/prefix-witness registries disagree")
        if not self.block_pool.enable_caching and any(self._request_prefix_witnesses.values()):
            raise SchedulerInvariantError("non-caching scheduler retained prefix witnesses")

        owner_ref_counts: Counter[int] = Counter()
        for request_id, block_ids in self._request_blocks.items():
            if request_id not in self._requests:
                raise SchedulerInvariantError("block owner is not a known request")
            if len(block_ids) != len(set(block_ids)):
                raise SchedulerInvariantError("request owns a duplicate block ID")
            request = self._requests[request_id]
            expected_blocks = (
                0
                if request.status is not RequestStatus.RUNNING
                else _ceil_div(request.num_computed_tokens, self.block_size_tokens)
            )
            if len(block_ids) != expected_blocks:
                raise SchedulerInvariantError("request block count does not match computed tokens")
            for block_id in block_ids:
                if block_id <= 0 or block_id >= len(self.block_pool.blocks):
                    raise SchedulerInvariantError("request owns an invalid block ID")
                owner_ref_counts[block_id] += 1

        free_block_ids = set(self.block_pool.free_block_ids)
        for block_id, expected_ref_count in owner_ref_counts.items():
            block = self.block_pool.blocks[block_id]
            if block.ref_count != expected_ref_count or block_id in free_block_ids:
                raise SchedulerInvariantError(
                    "owned block reference count differs from scheduler aliases"
                )

        reserved_block_ids = {
            block_id
            for reservation in self._recovery_prefix_reservations.values()
            for block_id in reservation.block_ids
        }
        if reserved_block_ids & set(owner_ref_counts):
            raise SchedulerInvariantError("a block is both recovery-reserved and active")
        if len(reserved_block_ids) != sum(
            len(reservation.block_ids)
            for reservation in self._recovery_prefix_reservations.values()
        ):
            raise SchedulerInvariantError("recovery reservations share a scheduler block")
        recovery_allocation_owner: dict[str, str] = {}
        for request_id, reservation in self._recovery_prefix_reservations.items():
            if request_id != reservation.request_id or request_id in self._requests:
                raise SchedulerInvariantError("recovery reservation ownership is ambiguous")
            if reservation.restored_tokens % self.block_size_tokens != 0:
                raise SchedulerInvariantError("recovery reservation tokens are not block aligned")
            if len(reservation.block_ids) != (
                reservation.restored_tokens // self.block_size_tokens
            ):
                raise SchedulerInvariantError("recovery reservation block count drifted")
            for block_id in reservation.block_ids:
                if block_id <= 0 or block_id >= len(self.block_pool.blocks):
                    raise SchedulerInvariantError("recovery reservation owns an invalid block")
                block = self.block_pool.blocks[block_id]
                if block.ref_count != 1 or block_id in self.block_pool.free_block_ids:
                    raise SchedulerInvariantError(
                        "recovery-reserved block is not exclusively referenced"
                    )
            for allocation_id in reservation.physical_allocation_ids:
                previous_owner = recovery_allocation_owner.setdefault(
                    allocation_id, request_id
                )
                if previous_owner != request_id:
                    raise SchedulerInvariantError(
                        "physical recovery allocation is shared across requests"
                    )

        referenced_block_ids = {
            block.block_id for block in self.block_pool.blocks[1:] if block.ref_count > 0
        }
        held_block_ids = set(owner_ref_counts) | reserved_block_ids
        if referenced_block_ids != held_block_ids:
            raise SchedulerInvariantError("block pool has ownership outside the scheduler")
        if self.block_lifecycle_observer is not None:
            try:
                self.block_lifecycle_observer.audit_scheduler_blocks(
                    dict(owner_ref_counts),
                    self.block_pool.cached_hashes(),
                    reserved_block_ids,
                )
            except (RuntimeError, ValueError) as error:
                raise SchedulerInvariantError(
                    f"physical block lifecycle invariant failed: {error}"
                ) from error

    def _audit_queued_request(self, request: Request, queued_ids: set[str]) -> None:
        if request.request_id in queued_ids:
            raise SchedulerInvariantError("request appears in multiple queue positions")
        if self._requests.get(request.request_id) is not request:
            raise SchedulerInvariantError("queue request is not the registered request object")
        self._validate_request_counters(request)
        queued_ids.add(request.request_id)

    @staticmethod
    def _validate_request_counters(request: Request) -> None:
        counters = (
            request.prompt_tokens,
            request.max_output_tokens,
            request.num_computed_tokens,
            request.num_output_tokens,
            request.num_preemptions,
        )
        if any(type(value) is not int or value < 0 for value in counters):
            raise SchedulerInvariantError("request counters must be non-negative integers")
        if request.max_output_tokens <= 0:
            raise SchedulerInvariantError("max_output_tokens must be positive")
        if request.num_output_tokens > request.max_output_tokens:
            raise SchedulerInvariantError("output tokens exceed request maximum")
        if request.num_computed_tokens > request.num_tokens:
            raise SchedulerInvariantError("computed tokens exceed materialized tokens")
        if request.num_tokens > request.max_model_len_tokens:
            raise SchedulerInvariantError("request exceeds its model-length guard")


def _require_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor
