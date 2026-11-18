"""Tensor-free adapter for the pinned vLLM V1 KV connector lifecycle.

This module mirrors scheduler/worker metadata ownership and completion gates.
It deliberately does not own a KV directory or transfer bytes: the caller's
single baseline Mooncake Store remains the external lookup/save truth source.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class StoreRole(StrEnum):
    CONSUMER = "kv_consumer"
    PRODUCER = "kv_producer"
    BOTH = "kv_both"


@dataclass(frozen=True, slots=True)
class ConnectorRequest:
    request_id: str
    token_ids: tuple[int, ...]
    block_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.request_id or not self.token_ids:
            raise ValueError("connector request identity and tokens must be non-empty")
        if any(type(token_id) is not int or token_id < 0 for token_id in self.token_ids):
            raise ValueError("connector token IDs must be non-negative integers")
        if any(not block_hash for block_hash in self.block_hashes):
            raise ValueError("connector block hashes must be non-empty")

    @property
    def num_tokens(self) -> int:
        return len(self.token_ids)


@dataclass(slots=True)
class StoreLoadSpec:
    local_cached_tokens: int
    store_cached_tokens: int
    can_load: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "local_cached_tokens": self.local_cached_tokens,
            "store_cached_tokens": self.store_cached_tokens,
            "can_load": self.can_load,
        }


@dataclass(frozen=True, slots=True)
class ConnectorScheduledRequest:
    request: ConnectorRequest
    block_ids: tuple[tuple[int, ...], ...]
    num_computed_tokens: int
    num_scheduled_tokens: int
    new_block_ids: tuple[tuple[int, ...], ...] = ()
    resumed_from_preemption: bool = False

    def __post_init__(self) -> None:
        if not self.block_ids or any(not group for group in self.block_ids):
            raise ValueError("scheduled connector request must bind every block group")
        if self.num_computed_tokens < 0 or self.num_scheduled_tokens <= 0:
            raise ValueError("scheduled connector token counters are invalid")
        if self.num_computed_tokens + self.num_scheduled_tokens > self.request.num_tokens:
            raise ValueError("scheduled connector tokens exceed request materialization")
        _validate_block_groups(self.block_ids)
        if self.new_block_ids:
            _validate_block_groups(self.new_block_ids)
            if len(self.new_block_ids) != len(self.block_ids):
                raise ValueError("new block groups must align with full block groups")


@dataclass(frozen=True, slots=True)
class ConnectorScheduleStep:
    new_requests: tuple[ConnectorScheduledRequest, ...] = ()
    cached_requests: tuple[ConnectorScheduledRequest, ...] = ()
    finished_request_ids: frozenset[str] = frozenset()
    preempted_request_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        scheduled_ids = [
            item.request.request_id for item in (*self.new_requests, *self.cached_requests)
        ]
        if len(scheduled_ids) != len(set(scheduled_ids)):
            raise ValueError("connector step schedules a request more than once")
        if self.finished_request_ids & self.preempted_request_ids:
            raise ValueError("one connector step cannot finish and preempt the same request")


@dataclass(frozen=True, slots=True)
class ConnectorRequestMetadata:
    request_id: str
    token_len: int
    block_ids: tuple[tuple[int, ...], ...]
    block_hashes: tuple[str, ...]
    can_save: bool
    load_spec: StoreLoadSpec | None
    is_last_chunk: bool
    token_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.request_id or self.token_len <= 0:
            raise ValueError("connector request metadata is incomplete")
        if self.can_save and self.load_spec is not None:
            raise ValueError("one connector metadata row cannot both save and load")
        if not self.can_save and self.load_spec is None:
            raise ValueError("connector metadata row must carry one operation")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "token_len": self.token_len,
            "block_ids": [list(group) for group in self.block_ids],
            "block_hashes": list(self.block_hashes),
            "can_save": self.can_save,
            "load_spec": self.load_spec.to_dict() if self.load_spec is not None else None,
            "is_last_chunk": self.is_last_chunk,
            "token_ids": list(self.token_ids),
        }


@dataclass(frozen=True, slots=True)
class ConnectorMetadata:
    requests: tuple[ConnectorRequestMetadata, ...]
    unfinished_request_ids: frozenset[str]
    preempted_request_ids: frozenset[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "requests": [request.to_dict() for request in self.requests],
            "unfinished_request_ids": sorted(self.unfinished_request_ids),
            "preempted_request_ids": sorted(self.preempted_request_ids),
        }


@dataclass(frozen=True, slots=True)
class ConnectorCompletion:
    finished_sending: frozenset[str] = frozenset()
    finished_receiving: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, object]:
        return {
            "finished_sending": sorted(self.finished_sending),
            "finished_receiving": sorted(self.finished_receiving),
        }


@dataclass(slots=True)
class _RequestTracker:
    request: ConnectorRequest
    token_len: int
    block_ids: list[list[int]]
    num_saved_tokens: int = 0
    prefill_end_tokens: int = 0

    def extend(self, new_block_ids: tuple[tuple[int, ...], ...]) -> None:
        if len(new_block_ids) != len(self.block_ids):
            raise ValueError("connector tracker block-group count drift")
        for existing, new in zip(self.block_ids, new_block_ids, strict=True):
            existing.extend(new)


class TensorFreeStoreConnectorScheduler:
    """Scheduler-side pinned Store metadata and delayed-free state machine."""

    def __init__(
        self,
        *,
        block_size_tokens: int,
        role: StoreRole,
        lookup: Callable[[int, tuple[str, ...]], int],
        load_async: bool = True,
    ) -> None:
        if type(block_size_tokens) is not int or block_size_tokens <= 0:
            raise ValueError("connector block_size_tokens must be positive")
        if not load_async:
            raise ValueError("pinned Mooncake Store adapter requires async load completion")
        self.block_size_tokens = block_size_tokens
        self.role = role
        self.lookup = lookup
        self.load_async = load_async
        self._load_specs: dict[str, StoreLoadSpec] = {}
        self._lookup_observations: dict[tuple[str, int], int] = {}
        self._unfinished: dict[str, tuple[ConnectorRequest, tuple[tuple[int, ...], ...]]] = {}
        self._trackers: dict[str, _RequestTracker] = {}
        self._waiting_receives: set[str] = set()
        self._ready_receives_next_pass: set[str] = set()
        self._delayed_free: set[str] = set()

    def get_num_new_matched_tokens(
        self,
        request: ConnectorRequest,
        num_computed_tokens: int,
    ) -> tuple[int, bool]:
        """Return a block-aligned Store delta with idempotent repeated lookup."""

        if num_computed_tokens < 0 or num_computed_tokens > request.num_tokens:
            raise ValueError("connector local computed-token counter is invalid")
        token_len = request.num_tokens // self.block_size_tokens * self.block_size_tokens
        if token_len < self.block_size_tokens:
            return 0, False
        store_hit_tokens = self.lookup(token_len, request.block_hashes)
        if (
            type(store_hit_tokens) is not int
            or store_hit_tokens < 0
            or store_hit_tokens > token_len
            or store_hit_tokens % self.block_size_tokens
        ):
            raise ValueError("Store lookup returned an invalid block-aligned prefix")
        observation_key = (request.request_id, num_computed_tokens)
        prior = self._lookup_observations.setdefault(observation_key, store_hit_tokens)
        if prior != store_hit_tokens:
            raise ValueError("repeated connector lookup changed before allocation")
        if store_hit_tokens == request.num_tokens:
            store_hit_tokens = (
                (request.num_tokens - 1) // self.block_size_tokens * self.block_size_tokens
            )
        delta = max(0, store_hit_tokens - num_computed_tokens)
        if delta == 0:
            return 0, False
        candidate = StoreLoadSpec(num_computed_tokens, store_hit_tokens)
        existing = self._load_specs.setdefault(request.request_id, candidate)
        if (
            existing.local_cached_tokens != candidate.local_cached_tokens
            or existing.store_cached_tokens != candidate.store_cached_tokens
        ):
            raise ValueError("connector load spec changed before allocation")
        return delta, self.load_async

    def update_state_after_alloc(
        self,
        request: ConnectorRequest,
        block_ids: tuple[tuple[int, ...], ...],
        num_external_tokens: int,
    ) -> None:
        _validate_block_groups(block_ids)
        if num_external_tokens < 0:
            raise ValueError("num_external_tokens must be non-negative")
        owned_blocks = block_ids if num_external_tokens else tuple(() for _ in block_ids)
        self._unfinished[request.request_id] = (request, owned_blocks)
        load_spec = self._load_specs.get(request.request_id)
        if load_spec is None:
            if num_external_tokens:
                raise ValueError("external allocation has no preceding Store lookup")
            return
        expected = load_spec.store_cached_tokens - load_spec.local_cached_tokens
        if num_external_tokens == 0:
            load_spec.can_load = False
        elif num_external_tokens != expected:
            raise ValueError("external allocation differs from Store lookup token delta")
        else:
            load_spec.can_load = True

    def build_connector_meta(self, step: ConnectorScheduleStep) -> ConnectorMetadata:
        """Build one immutable scheduler→worker message and consume step state."""

        for request_id in step.finished_request_ids:
            self._load_specs.pop(request_id, None)
            self._trackers.pop(request_id, None)
            self._unfinished.pop(request_id, None)
            self._waiting_receives.discard(request_id)
        for request_id in step.preempted_request_ids:
            self._load_specs.pop(request_id, None)
            self._trackers.pop(request_id, None)
            self._unfinished.pop(request_id, None)
            self._waiting_receives.discard(request_id)

        rows: list[ConnectorRequestMetadata] = []
        for scheduled in step.new_requests:
            request = scheduled.request
            stored = self._unfinished.get(request.request_id)
            if stored is None or stored[0] != request:
                raise ValueError("new connector request was not observed after allocation")
            token_len = scheduled.num_computed_tokens + scheduled.num_scheduled_tokens
            tracker = _RequestTracker(
                request=request,
                token_len=token_len,
                block_ids=[list(group) for group in scheduled.block_ids],
                prefill_end_tokens=request.num_tokens,
            )
            self._trackers[request.request_id] = tracker
            load_spec = self._load_specs.pop(request.request_id, None)
            row = self._make_metadata(tracker, load_spec=load_spec)
            if row is not None:
                rows.append(row)

        for scheduled in step.cached_requests:
            request_id = scheduled.request.request_id
            cached_tracker = self._trackers.get(request_id)
            if cached_tracker is None:
                if not scheduled.resumed_from_preemption:
                    raise ValueError("cached connector request has no tracker")
                cached_tracker = _RequestTracker(
                    request=scheduled.request,
                    token_len=0,
                    block_ids=[list(group) for group in scheduled.block_ids],
                    prefill_end_tokens=scheduled.request.num_tokens,
                )
                self._trackers[request_id] = cached_tracker
            elif scheduled.new_block_ids:
                cached_tracker.extend(scheduled.new_block_ids)
            cached_tracker.token_len = (
                scheduled.num_computed_tokens + scheduled.num_scheduled_tokens
            )
            if scheduled.num_computed_tokens >= cached_tracker.prefill_end_tokens:
                continue
            row = self._make_metadata(
                cached_tracker,
                load_spec=self._load_specs.pop(request_id, None),
            )
            if row is not None:
                rows.append(row)

        return ConnectorMetadata(
            requests=tuple(rows),
            unfinished_request_ids=frozenset(self._unfinished),
            preempted_request_ids=step.preempted_request_ids,
        )

    def request_finished(
        self,
        request_id: str,
        block_ids: tuple[tuple[int, ...], ...],
    ) -> bool:
        """Transfer block ownership to async send completion when required."""

        _validate_block_groups(block_ids)
        if self.role is StoreRole.CONSUMER:
            return False
        tracker = self._trackers.get(request_id)
        delay = tracker is not None and tracker.num_saved_tokens > 0
        if delay:
            self._delayed_free.add(request_id)
        return delay

    def apply_worker_completion(self, completion: ConnectorCompletion) -> frozenset[str]:
        """Consume worker output; only send completion releases delayed blocks."""

        unknown_sends = completion.finished_sending - self._delayed_free
        unknown_receives = completion.finished_receiving - self._waiting_receives
        if unknown_sends:
            raise ValueError(f"send completion has no delayed-free owner: {sorted(unknown_sends)}")
        if unknown_receives:
            raise ValueError(f"receive completion has no remote waiter: {sorted(unknown_receives)}")
        self._delayed_free.difference_update(completion.finished_sending)
        self._waiting_receives.difference_update(completion.finished_receiving)
        self._ready_receives_next_pass.update(completion.finished_receiving)
        return completion.finished_sending

    def begin_scheduler_pass(self) -> frozenset[str]:
        """Expose completed receives only at the next scheduler-pass boundary."""

        ready = frozenset(self._ready_receives_next_pass)
        self._ready_receives_next_pass.clear()
        return ready

    @property
    def delayed_free_request_ids(self) -> frozenset[str]:
        return frozenset(self._delayed_free)

    def _make_metadata(
        self,
        tracker: _RequestTracker,
        *,
        load_spec: StoreLoadSpec | None,
    ) -> ConnectorRequestMetadata | None:
        num_tokens_to_save = tracker.token_len // self.block_size_tokens * self.block_size_tokens
        next_save_boundary = (
            (tracker.num_saved_tokens + self.block_size_tokens)
            // self.block_size_tokens
            * self.block_size_tokens
        )
        can_save = (
            self.role is not StoreRole.CONSUMER
            and num_tokens_to_save >= next_save_boundary
            and not (load_spec is not None and load_spec.can_load)
        )
        active_load = load_spec if load_spec is not None and load_spec.can_load else None
        if not can_save and active_load is None:
            return None
        if can_save:
            tracker.num_saved_tokens = num_tokens_to_save
        if active_load is not None:
            self._waiting_receives.add(tracker.request.request_id)
        return ConnectorRequestMetadata(
            request_id=tracker.request.request_id,
            token_len=num_tokens_to_save,
            block_ids=tuple(tuple(group) for group in tracker.block_ids),
            block_hashes=tracker.request.block_hashes,
            can_save=can_save,
            load_spec=active_load,
            is_last_chunk=tracker.token_len
            >= (tracker.prefill_end_tokens // self.block_size_tokens * self.block_size_tokens),
            token_ids=tracker.request.token_ids[: tracker.token_len],
        )


class TensorFreeStoreConnectorWorker:
    """Worker-side bind→issue/completion→clear lifecycle without tensors."""

    def __init__(self, *, role: StoreRole) -> None:
        self.role = role
        self._metadata: ConnectorMetadata | None = None
        self._pending_loads: set[str] = set()
        self._pending_saves: set[str] = set()
        self._completed_loads: set[str] = set()
        self._completed_saves: set[str] = set()
        self._finished_save_requests: set[str] = set()

    @property
    def has_connector_metadata(self) -> bool:
        return self._metadata is not None

    def bind_connector_metadata(self, metadata: ConnectorMetadata) -> None:
        if self._metadata is not None:
            raise ValueError("connector metadata is already bound for this worker step")
        self._metadata = metadata

    def clear_connector_metadata(self) -> None:
        if self._metadata is None:
            raise ValueError("connector metadata is not bound")
        self._metadata = None

    def complete_transfers(
        self,
        *,
        receiving: frozenset[str] = frozenset(),
        sending: frozenset[str] = frozenset(),
    ) -> None:
        if receiving - self._pending_loads:
            raise ValueError("cannot complete a receive that was never issued")
        if sending - self._pending_saves:
            raise ValueError("cannot complete a send that was never issued")
        self._completed_loads.update(receiving)
        self._completed_saves.update(sending)

    def get_finished(self, finished_request_ids: frozenset[str]) -> ConnectorCompletion:
        metadata = self._metadata
        if metadata is None:
            raise ValueError("worker completion requires bound connector metadata")
        for request_id in metadata.preempted_request_ids:
            self._pending_saves.discard(request_id)
            self._completed_saves.discard(request_id)
            self._finished_save_requests.discard(request_id)
        for row in metadata.requests:
            if row.load_spec is not None:
                self._pending_loads.add(row.request_id)
            if row.can_save:
                if self.role is StoreRole.CONSUMER:
                    raise ValueError("consumer worker received save metadata")
                self._pending_saves.add(row.request_id)

        self._finished_save_requests.update(finished_request_ids)
        done_receiving = frozenset(self._completed_loads)
        done_sending = frozenset(self._completed_saves & self._finished_save_requests)
        self._pending_loads.difference_update(done_receiving)
        self._completed_loads.difference_update(done_receiving)
        self._pending_saves.difference_update(done_sending)
        self._completed_saves.difference_update(done_sending)
        self._finished_save_requests.difference_update(done_sending)
        return ConnectorCompletion(done_sending, done_receiving)

    def snapshot(self) -> Mapping[str, Any]:
        return {
            "metadata_bound": self.has_connector_metadata,
            "pending_loads": sorted(self._pending_loads),
            "pending_saves": sorted(self._pending_saves),
            "completed_loads": sorted(self._completed_loads),
            "completed_saves": sorted(self._completed_saves),
            "finished_save_requests": sorted(self._finished_save_requests),
        }


def _validate_block_groups(block_ids: tuple[tuple[int, ...], ...]) -> None:
    if not block_ids:
        raise ValueError("connector block groups must be non-empty")
    flattened = [block_id for group in block_ids for block_id in group]
    if any(type(block_id) is not int or block_id < 0 for block_id in flattened):
        raise ValueError("connector block IDs must be non-negative integers")
    if len(flattened) != len(set(flattened)):
        raise ValueError("connector block IDs must be unique across groups")
