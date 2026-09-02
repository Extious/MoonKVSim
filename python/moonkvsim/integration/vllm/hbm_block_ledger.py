"""Bridge ordinary vLLM logical blocks to byte-exact per-GPU HBM ledgers.

This is a baseline, tensor-free accounting adapter.  It consumes an explicit
``StageBlockLayout`` for every PP-stage/TP-rank GPU and never infers a runtime
CUDA cache capacity.  Static behavior is E1/E2-toy evidence only; it is not a
pinned-vLLM differential or physical-validation result.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.kv_layout_artifact import audit_kv_layout_document
from moonkvsim.simulation.allocation import (
    AllocationRole,
    AllocationState,
    PhysicalAllocation,
)
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction

HBM_KV_RESERVED_ACCOUNT = "ACTIVE_PRIMARY_KV_RESERVED"
HBM_KV_ACTIVE_ACCOUNT = "ACTIVE_PRIMARY_KV"
HBM_KV_INACTIVE_ACCOUNT = "INACTIVE_REUSABLE_KV"
HBM_RECOVERY_RESERVED_ACCOUNT = "RECOVERY_DEST_RESERVED"
EVIDENCE_CLASS = "E1"


@dataclass(frozen=True, slots=True)
class HbmStageRankBinding:
    """One explicit PP-stage/TP-rank layout bound to one physical GPU HBM."""

    resource_id: str
    layout: StageBlockLayout

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("resource_id must be non-empty")

    @property
    def key(self) -> tuple[int, int]:
        return (self.layout.pp_stage, self.layout.tensor_parallel_rank)


def load_hbm_stage_rank_bindings(
    layout_path: Path,
    *,
    resource_ids: Mapping[tuple[int, int], str],
) -> tuple[HbmStageRankBinding, ...]:
    """Bind every audited E1 artifact stage/rank entry to a physical GPU ID."""

    try:
        raw = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read KV layout artifact {layout_path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("KV layout artifact root must be an object")
    document = dict(raw)
    audit_kv_layout_document(document)
    raw_entries = document.get("stage_rank_layouts")
    if not isinstance(raw_entries, list):
        raise ValueError("stage_rank_layouts must be an array")

    bindings: list[HbmStageRankBinding] = []
    seen_keys: set[tuple[int, int]] = set()
    for index, raw_entry in enumerate(raw_entries):
        entry = _object(raw_entry, f"stage_rank_layouts[{index}]")
        block = _object(entry.get("block"), f"stage_rank_layouts[{index}].block")
        layout = StageBlockLayout(
            pp_stage=_integer(block, "pp_stage"),
            tensor_parallel_rank=_integer(block, "tensor_parallel_rank"),
            block_size_tokens=_integer(block, "block_size_tokens"),
            layer_names=_string_tuple(block, "layer_names"),
            layer_indices=_integer_tuple(block, "layer_indices"),
            tensor_payload_bytes=_integer(block, "tensor_payload_bytes"),
            auxiliary_payload_bytes=_integer(block, "auxiliary_payload_bytes"),
            payload_bytes=_integer(block, "payload_bytes"),
            layout_padding_bytes=_integer(block, "layout_padding_bytes"),
            allocator_metadata_bytes=_integer(block, "allocator_metadata_bytes"),
            requested_bytes=_integer(block, "requested_bytes"),
            internal_fragmentation_bytes=_integer(block, "internal_fragmentation_bytes"),
            allocated_bytes=_integer(block, "allocated_bytes"),
            allocator_alignment_bytes=_integer(block, "allocator_alignment_bytes"),
        )
        block_fingerprint = block.get("fingerprint")
        if block_fingerprint != layout.fingerprint:
            raise ValueError("stage/rank block fingerprint disagrees with decoded layout")
        key = (layout.pp_stage, layout.tensor_parallel_rank)
        if key in seen_keys:
            raise ValueError(f"duplicate stage/rank layout entry: {key}")
        seen_keys.add(key)
        if (
            _integer(entry, "pp_stage") != key[0]
            or _integer(entry, "tensor_parallel_rank") != key[1]
        ):
            raise ValueError("stage/rank entry disagrees with its block layout")
        if (
            _string_tuple(entry, "layer_names") != layout.layer_names
            or _integer_tuple(entry, "layer_indices") != layout.layer_indices
        ):
            raise ValueError("stage/rank entry layers disagree with its block layout")
        if _integer(entry, "layer_count") != len(layout.layer_names):
            raise ValueError("stage/rank layer_count disagrees with its block layout")
        resource_id = resource_ids.get(key)
        if resource_id is None:
            raise ValueError(f"no physical GPU resource for stage/rank {key}")
        bindings.append(HbmStageRankBinding(resource_id, layout))
    unknown_keys = set(resource_ids) - seen_keys
    if unknown_keys:
        raise ValueError(f"resource map has no layout entries: {sorted(unknown_keys)}")
    return tuple(bindings)


@dataclass(slots=True)
class _LogicalBlockRecord:
    block_id: int
    generation: int
    request_id: str
    object_id: str
    allocation_ids: tuple[str, ...]
    lost_allocation_ids: tuple[str, ...] = ()
    cache_hash: str | None = None
    logical_hash: str | None = None
    aliases: dict[str, str] = field(default_factory=dict)
    active_request_ids: set[str] = field(default_factory=set)


class HbmBlockLedgerBridge:
    """Physical-accounting observer for ``ContinuousBatchScheduler``.

    One scheduler block maps to one unique ``PhysicalAllocation`` on every
    bound GPU.  Capacity moves through FREE -> RESERVED -> ACTIVE and returns
    to FREE in multi-resource transactions.  Logical hashes, roles, and alias
    reference counts are overlays on those allocations and never charge bytes
    a second time.
    """

    def __init__(
        self,
        *,
        bridge_id: str,
        bindings: Iterable[HbmStageRankBinding],
        ledgers: Mapping[str, CapacityLedger],
        registry: AllocationRegistry,
        journal: EventJournal,
        now_ns: Callable[[], int] | None = None,
    ) -> None:
        if not bridge_id:
            raise ValueError("bridge_id must be non-empty")
        binding_tuple = tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.layout.pp_stage,
                    item.layout.tensor_parallel_rank,
                    item.resource_id,
                ),
            )
        )
        if not binding_tuple:
            raise ValueError("at least one HBM stage/rank binding is required")
        keys = [binding.key for binding in binding_tuple]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate PP-stage/TP-rank binding")
        block_sizes = {binding.layout.block_size_tokens for binding in binding_tuple}
        if len(block_sizes) != 1:
            raise ValueError("hybrid block sizes require an explicit group-aware bridge")
        if any(binding.layout.allocated_bytes <= 0 for binding in binding_tuple):
            raise ValueError("every stage/rank layout must allocate positive bytes")
        if registry.journal is not journal:
            raise ValueError("allocation registry and HBM bridge must share one journal")

        ledger_copy = dict(ledgers)
        for binding in binding_tuple:
            ledger = ledger_copy.get(binding.resource_id)
            if ledger is None:
                raise KeyError(f"missing HBM ledger: {binding.resource_id}")
            if ledger.resource_kind is not CapacityResourceKind.GPU_HBM:
                raise ValueError(f"binding is not GPU HBM: {binding.resource_id}")

        self.bridge_id = bridge_id
        self.bindings = binding_tuple
        self.ledgers = ledger_copy
        self.registry = registry
        self.journal = journal
        self._now_ns = now_ns or (lambda: 0)
        self._block_size_tokens = block_sizes.pop()
        self._allocated_bytes_per_resource: dict[str, int] = {}
        for binding in binding_tuple:
            self._allocated_bytes_per_resource[binding.resource_id] = (
                self._allocated_bytes_per_resource.get(binding.resource_id, 0)
                + binding.layout.allocated_bytes
            )
        self._blocks: dict[int, _LogicalBlockRecord] = {}
        self._recovery_reservations: dict[str, tuple[_LogicalBlockRecord, ...]] = {}
        self._last_generation: dict[int, int] = {}
        self._failed_resource_ids: set[str] = set()
        self._operation_sequence = 0

    @property
    def num_free_blocks(self) -> int:
        """Return free plus only the inactive physical pages that may be evicted."""

        available_bytes = {
            resource_id: self.ledgers[resource_id].bytes_in(FREE_ACCOUNT)
            for resource_id in self._allocated_bytes_per_resource
        }
        for record in self._blocks.values():
            for allocation in self._evictable_inactive_allocations(record):
                available_bytes[allocation.resource_id] += allocation.allocated_bytes

        return min(
            available_bytes[resource_id] // allocated_bytes
            for resource_id, allocated_bytes in self._allocated_bytes_per_resource.items()
        )

    def num_free_blocks_for_request(self, request_id: str) -> int:
        """Return fungible pages; this bridge charges every page independently."""

        if not request_id:
            raise ValueError("request_id must be non-empty")
        failed_resource_ids = self._unavailable_hbm_resource_ids()
        if failed_resource_ids:
            raise RuntimeError(
                "request-aware HBM capacity is unavailable because bound resources "
                f"failed or were lost: {list(failed_resource_ids)}"
            )
        return self.num_free_blocks

    def try_reclaim_blocks(self, request_id: str, required_blocks: int) -> bool:
        """Report existing evictable capacity; allocation performs the eviction."""

        if not request_id:
            raise ValueError("request_id must be non-empty")
        if type(required_blocks) is not int or required_blocks < 0:
            raise ValueError("required_blocks must be a non-negative integer")
        return required_blocks <= self.num_free_blocks_for_request(request_id)

    @property
    def active_block_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._blocks))

    @property
    def inactive_block_ids(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                block_id
                for block_id, record in self._blocks.items()
                if not record.active_request_ids
            )
        )

    @property
    def active_request_ids(self) -> tuple[str, ...]:
        """Return logical requests that currently own physical ACTIVE pages."""

        return tuple(
            sorted(
                {
                    request_id
                    for record in self._blocks.values()
                    for request_id in record.active_request_ids
                }
            )
        )

    @property
    def hbm_resource_ids(self) -> frozenset[str]:
        """Return the exact physical HBM failure domain observed by this bridge."""

        return frozenset(self._allocated_bytes_per_resource)

    def validate_scheduler_layout(
        self, *, block_size_tokens: int, usable_block_capacity: int
    ) -> None:
        if block_size_tokens != self._block_size_tokens:
            raise ValueError("scheduler block size differs from the bound stage/rank layout")
        if usable_block_capacity <= 0:
            raise ValueError("scheduler must expose at least one non-null block")

    def allocate_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
        evicted_cache_hashes: Mapping[int, str] | None = None,
    ) -> None:
        """Reserve and activate physical HBM before scheduler ownership mutates."""

        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._ordinary_block_ids(block_ids)
        if not normalized:
            return
        evicted = dict(evicted_cache_hashes or {})
        if set(evicted) - set(normalized):
            raise ValueError("evicted cache block must be part of this allocation")
        if evicted:
            self._evict_inactive_cached_blocks(
                evicted,
                cause=f"{cause}:evict-inactive-cache",
            )
        self.audit()
        reserved_block_ids = {
            record.block_id
            for records in self._recovery_reservations.values()
            for record in records
        }
        for block_id in normalized:
            if block_id in self._blocks or block_id in reserved_block_ids:
                raise ValueError(f"logical block is already physically held: {block_id}")

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        records, allocations = self._build_allocations(
            normalized,
            request_id=request_id,
            timestamp_ns=timestamp_ns,
        )
        for allocation in allocations:
            try:
                self.registry.get(allocation.allocation_id)
            except KeyError:
                pass
            else:
                raise ValueError(f"allocation ID already exists: {allocation.allocation_id}")

        reserve_event_id = self._event_id(operation, "reserve")
        ResourceTransaction(
            event_id=reserve_event_id,
            timestamp_ns=timestamp_ns,
            cause=f"{cause}:reserve",
            allocation_deltas=[
                self._allocation_delta(
                    allocation,
                    account_from=FREE_ACCOUNT,
                    account_to=HBM_KV_RESERVED_ACCOUNT,
                )
                for allocation in allocations
            ],
        ).commit(self.ledgers, journal=self.journal)

        for index, allocation in enumerate(allocations):
            self.registry.add(
                allocation,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"add:{index}"),
            )

        active_event_id = self._event_id(operation, "activate")
        ResourceTransaction(
            event_id=active_event_id,
            timestamp_ns=timestamp_ns,
            cause=f"{cause}:activate",
            allocation_deltas=[
                self._allocation_delta(
                    allocation,
                    account_from=HBM_KV_RESERVED_ACCOUNT,
                    account_to=HBM_KV_ACTIVE_ACCOUNT,
                )
                for allocation in allocations
            ],
        ).commit(self.ledgers, journal=self.journal)

        for index, allocation in enumerate(allocations):
            allocation_id = allocation.allocation_id
            self.registry.transition(
                allocation_id,
                AllocationState.PENDING,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"pending:{index}"),
            )
            self.registry.reaccount(
                allocation_id,
                HBM_KV_ACTIVE_ACCOUNT,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"reaccount:{index}"),
            )
            self.registry.transition(
                allocation_id,
                AllocationState.COMMITTED,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"commit:{index}"),
            )
            self.registry.add_role(
                allocation_id,
                AllocationRole.ACTIVE_PRIMARY,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"active-role:{index}"),
            )

        for record in records:
            self._blocks[record.block_id] = record
            self._last_generation[record.block_id] = record.generation
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_BLOCKS_ACTIVATED",
            {
                "event_id": active_event_id,
                "cause": cause,
                "blocks": [self._record_data(record) for record in records],
            },
        )
        self._operation_sequence += 1
        self.audit()

    def reserve_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> tuple[tuple[str, ...], ...]:
        """Charge a target recovery prefix before any Store GET can start."""

        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._ordinary_block_ids(block_ids)
        if not normalized:
            raise ValueError("recovery reservation must contain a physical block")
        self.audit()
        if request_id in self._recovery_reservations:
            raise ValueError("request already has an HBM recovery reservation")
        held_block_ids = set(self._blocks) | {
            record.block_id
            for records in self._recovery_reservations.values()
            for record in records
        }
        duplicate = held_block_ids & set(normalized)
        if duplicate:
            raise ValueError(f"logical recovery blocks are already held: {sorted(duplicate)}")

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        records, allocations = self._build_allocations(
            normalized,
            request_id=request_id,
            timestamp_ns=timestamp_ns,
            owner_account=HBM_RECOVERY_RESERVED_ACCOUNT,
        )
        for allocation in allocations:
            try:
                self.registry.get(allocation.allocation_id)
            except KeyError:
                pass
            else:
                raise ValueError(f"allocation ID already exists: {allocation.allocation_id}")

        reserve_event_id = self._event_id(operation, "recovery-reserve")
        ResourceTransaction(
            event_id=reserve_event_id,
            timestamp_ns=timestamp_ns,
            cause=f"{cause}:reserve",
            allocation_deltas=[
                self._allocation_delta(
                    allocation,
                    account_from=FREE_ACCOUNT,
                    account_to=HBM_RECOVERY_RESERVED_ACCOUNT,
                )
                for allocation in allocations
            ],
        ).commit(self.ledgers, journal=self.journal)
        for index, allocation in enumerate(allocations):
            self.registry.add(
                allocation,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-add:{index}"),
            )
        for record in records:
            self._last_generation[record.block_id] = record.generation
        self._recovery_reservations[request_id] = tuple(records)
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_RECOVERY_BLOCKS_RESERVED",
            {
                "event_id": reserve_event_id,
                "cause": cause,
                "request_id": request_id,
                "blocks": [self._record_data(record) for record in records],
                "account": HBM_RECOVERY_RESERVED_ACCOUNT,
            },
        )
        self._operation_sequence += 1
        self.audit()
        return tuple(record.allocation_ids for record in records)

    def commit_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        """Promote one fully transferred recovery destination to active KV."""

        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._ordinary_block_ids(block_ids)
        self.audit()
        records = self._require_recovery_reservation(request_id, normalized)
        allocations = [
            self.registry.get(allocation_id)
            for record in records
            for allocation_id in record.allocation_ids
        ]
        if any(record.lost_allocation_ids for record in records):
            raise ValueError("a degraded recovery destination cannot become active")
        if any(
            allocation.state is not AllocationState.RESERVED
            or allocation.owner_account != HBM_RECOVERY_RESERVED_ACCOUNT
            for allocation in allocations
        ):
            raise ValueError("recovery destination is not fully RESERVED")

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        commit_event_id = self._event_id(operation, "recovery-activate")
        ResourceTransaction(
            event_id=commit_event_id,
            timestamp_ns=timestamp_ns,
            cause=f"{cause}:activate",
            allocation_deltas=[
                self._allocation_delta(
                    allocation,
                    account_from=HBM_RECOVERY_RESERVED_ACCOUNT,
                    account_to=HBM_KV_ACTIVE_ACCOUNT,
                )
                for allocation in allocations
            ],
        ).commit(self.ledgers, journal=self.journal)
        for index, allocation in enumerate(allocations):
            allocation_id = allocation.allocation_id
            self.registry.transition(
                allocation_id,
                AllocationState.PENDING,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-pending:{index}"),
            )
            self.registry.reaccount(
                allocation_id,
                HBM_KV_ACTIVE_ACCOUNT,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-reaccount:{index}"),
            )
            self.registry.transition(
                allocation_id,
                AllocationState.COMMITTED,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-commit:{index}"),
            )
            self.registry.add_role(
                allocation_id,
                AllocationRole.ACTIVE_PRIMARY,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-active-role:{index}"),
            )
        for record in records:
            self._blocks[record.block_id] = record
        del self._recovery_reservations[request_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_RECOVERY_BLOCKS_ACTIVATED",
            {
                "event_id": commit_event_id,
                "cause": cause,
                "request_id": request_id,
                "block_ids": list(normalized),
                "allocation_ids": [list(record.allocation_ids) for record in records],
            },
        )
        self._operation_sequence += 1
        self.audit()

    def abort_recovery_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        """Release healthy reserved shards; retain failed shards as unavailable."""

        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._ordinary_block_ids(block_ids)
        self.audit()
        records = self._require_recovery_reservation(request_id, normalized)
        releasable: list[PhysicalAllocation] = []
        lost_allocation_ids: list[str] = []
        for record in records:
            for allocation_id in record.allocation_ids:
                allocation = self.registry.get(allocation_id)
                if allocation_id in record.lost_allocation_ids:
                    if (
                        allocation.state is not AllocationState.LOST
                        or allocation.owner_account != UNAVAILABLE_CAPACITY_ACCOUNT
                    ):
                        raise ValueError("failed recovery shard is not unavailable")
                    lost_allocation_ids.append(allocation_id)
                    continue
                if (
                    allocation.state is not AllocationState.RESERVED
                    or allocation.owner_account != HBM_RECOVERY_RESERVED_ACCOUNT
                ):
                    raise ValueError("healthy recovery shard is not RESERVED")
                releasable.append(allocation)

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        abort_event_id = self._event_id(operation, "recovery-abort")
        if releasable:
            ResourceTransaction(
                event_id=abort_event_id,
                timestamp_ns=timestamp_ns,
                cause=f"{cause}:abort",
                allocation_deltas=[
                    self._allocation_delta(
                        allocation,
                        account_from=HBM_RECOVERY_RESERVED_ACCOUNT,
                        account_to=FREE_ACCOUNT,
                    )
                    for allocation in releasable
                ],
            ).commit(self.ledgers, journal=self.journal)
        for index, allocation in enumerate(releasable):
            self.registry.transition(
                allocation.allocation_id,
                AllocationState.RELEASED,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"recovery-released:{index}"),
            )
        del self._recovery_reservations[request_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_RECOVERY_BLOCKS_ABORTED",
            {
                "event_id": abort_event_id,
                "cause": cause,
                "request_id": request_id,
                "block_ids": list(normalized),
                "released_allocation_ids": [allocation.allocation_id for allocation in releasable],
                "lost_allocation_ids": lost_allocation_ids,
            },
        )
        self._operation_sequence += 1
        self.audit()

    def mark_cacheable_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        cause: str,
    ) -> None:
        """Attach local prefix identity without changing physical capacity."""

        if not block_hashes or not cause:
            raise ValueError("cacheable block hashes and cause must be non-empty")
        self.audit()
        records: list[_LogicalBlockRecord] = []
        for block_id, logical_hash in block_hashes.items():
            if type(block_id) is not int or block_id <= 0 or not logical_hash:
                raise ValueError("cacheable block identity is invalid")
            record = self._blocks.get(block_id)
            if record is None or record.lost_allocation_ids:
                raise ValueError("cacheable block must be a healthy physical allocation")
            if not record.active_request_ids:
                raise ValueError("only an active block may become cacheable")
            if record.cache_hash not in {None, logical_hash}:
                raise ValueError("one physical block generation cannot carry two logical hashes")
            records.append(record)

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        for record in records:
            if record.cache_hash is None:
                for index, allocation_id in enumerate(record.allocation_ids):
                    allocation = self.registry.get(allocation_id)
                    if AllocationRole.CACHE_REUSE not in allocation.roles:
                        self.registry.add_role(
                            allocation_id,
                            AllocationRole.CACHE_REUSE,
                            timestamp_ns=timestamp_ns,
                            event_id=self._event_id(
                                operation,
                                f"cacheable-role:{record.block_id}:{index}",
                            ),
                        )
            record.cache_hash = block_hashes[record.block_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_BLOCKS_MARKED_CACHEABLE",
            {
                "event_id": self._event_id(operation, "cacheable"),
                "cause": cause,
                "block_hashes": {
                    str(block_id): logical_hash
                    for block_id, logical_hash in sorted(block_hashes.items())
                },
            },
        )
        self._operation_sequence += 1
        self.audit()

    def activate_cached_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        """Touch cached pages for one request without a second byte charge."""

        if not block_hashes or not request_id or not cause:
            raise ValueError("cached block hashes, request_id, and cause must be non-empty")
        self.audit()
        records: list[_LogicalBlockRecord] = []
        activate_allocations: list[PhysicalAllocation] = []
        for block_id, logical_hash in block_hashes.items():
            record = self._blocks.get(block_id)
            if record is None or record.cache_hash != logical_hash:
                raise ValueError("cached block identity differs from physical residency")
            if record.lost_allocation_ids:
                raise ValueError("degraded cached block cannot be touched")
            if request_id in record.active_request_ids:
                raise ValueError("request already references cached block")
            records.append(record)
            if not record.active_request_ids:
                activate_allocations.extend(
                    self.registry.get(allocation_id) for allocation_id in record.allocation_ids
                )

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        if activate_allocations:
            ResourceTransaction(
                event_id=self._event_id(operation, "cache-touch-activate"),
                timestamp_ns=timestamp_ns,
                cause=f"{cause}:activate",
                allocation_deltas=[
                    self._allocation_delta(
                        allocation,
                        account_from=HBM_KV_INACTIVE_ACCOUNT,
                        account_to=HBM_KV_ACTIVE_ACCOUNT,
                    )
                    for allocation in activate_allocations
                ],
            ).commit(self.ledgers, journal=self.journal)
            for index, allocation in enumerate(activate_allocations):
                self.registry.reaccount(
                    allocation.allocation_id,
                    HBM_KV_ACTIVE_ACCOUNT,
                    timestamp_ns=timestamp_ns,
                    event_id=self._event_id(operation, f"cache-touch-reaccount:{index}"),
                )
                self.registry.add_role(
                    allocation.allocation_id,
                    AllocationRole.ACTIVE_PRIMARY,
                    timestamp_ns=timestamp_ns,
                    event_id=self._event_id(operation, f"cache-touch-active:{index}"),
                )
        for record in records:
            record.active_request_ids.add(request_id)
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_CACHED_BLOCKS_TOUCHED",
            {
                "event_id": self._event_id(operation, "cache-touched"),
                "cause": cause,
                "request_id": request_id,
                "block_ids": sorted(block_hashes),
                "physical_capacity_delta_bytes": 0,
            },
        )
        self._operation_sequence += 1
        self.audit()

    def _evict_inactive_cached_blocks(
        self,
        block_hashes: Mapping[int, str],
        *,
        cause: str,
    ) -> None:
        """Return inactive LRU pages to FREE immediately before page reuse."""

        self.audit()
        records: list[_LogicalBlockRecord] = []
        allocations: list[PhysicalAllocation] = []
        for block_id, logical_hash in block_hashes.items():
            record = self._blocks.get(block_id)
            if (
                record is None
                or record.cache_hash != logical_hash
                or record.active_request_ids
                or record.aliases
                or record.lost_allocation_ids
            ):
                raise ValueError("only a healthy inactive cached block may be evicted")
            records.append(record)
            allocations.extend(
                self.registry.get(allocation_id) for allocation_id in record.allocation_ids
            )

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        ResourceTransaction(
            event_id=self._event_id(operation, "cache-evict"),
            timestamp_ns=timestamp_ns,
            cause=cause,
            allocation_deltas=[
                self._allocation_delta(
                    allocation,
                    account_from=HBM_KV_INACTIVE_ACCOUNT,
                    account_to=FREE_ACCOUNT,
                )
                for allocation in allocations
            ],
        ).commit(self.ledgers, journal=self.journal)
        for index, allocation in enumerate(allocations):
            if AllocationRole.CACHE_REUSE in allocation.roles:
                self.registry.remove_role(
                    allocation.allocation_id,
                    AllocationRole.CACHE_REUSE,
                    timestamp_ns=timestamp_ns,
                    event_id=self._event_id(operation, f"cache-evict-role:{index}"),
                )
            self.registry.transition(
                allocation.allocation_id,
                AllocationState.RELEASED,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"cache-evict-release:{index}"),
            )
        for record in records:
            del self._blocks[record.block_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_INACTIVE_BLOCKS_EVICTED",
            {
                "event_id": self._event_id(operation, "cache-evicted"),
                "cause": cause,
                "block_ids": [record.block_id for record in records],
            },
        )
        self._operation_sequence += 1
        self.audit()

    def release_blocks(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> None:
        """Release one request reference; retain cacheable pages as inactive."""

        if not request_id or not cause:
            raise ValueError("request_id and cause must be non-empty")
        normalized = self._ordinary_block_ids(block_ids)
        if not normalized:
            return
        self.audit()
        records: list[_LogicalBlockRecord] = []
        inactive_records: list[_LogicalBlockRecord] = []
        released_records: list[_LogicalBlockRecord] = []
        inactive_allocations: list[PhysicalAllocation] = []
        released_allocations: list[PhysicalAllocation] = []
        for block_id in normalized:
            record = self._blocks.get(block_id)
            if record is None:
                raise ValueError(f"logical block has no physical allocation: {block_id}")
            if request_id not in record.active_request_ids:
                raise ValueError(f"logical block {block_id} is not referenced by request")
            if record.aliases:
                raise ValueError(
                    f"logical block {block_id} retains alias references: {sorted(record.aliases)}"
                )
            records.append(record)
            if len(record.active_request_ids) > 1:
                continue
            target_allocations = (
                inactive_allocations if record.cache_hash is not None else released_allocations
            )
            if record.cache_hash is not None:
                inactive_records.append(record)
            else:
                released_records.append(record)
            for allocation_id in record.allocation_ids:
                allocation = self.registry.get(allocation_id)
                if allocation_id in record.lost_allocation_ids:
                    if allocation.state is not AllocationState.LOST:
                        raise ValueError("degraded HBM allocation is not LOST")
                    if allocation.owner_account != UNAVAILABLE_CAPACITY_ACCOUNT:
                        raise ValueError("lost HBM bytes are not unavailable")
                    continue
                if allocation.state is not AllocationState.COMMITTED:
                    raise ValueError("only committed HBM allocations can be released")
                if allocation.owner_account != HBM_KV_ACTIVE_ACCOUNT:
                    raise ValueError("HBM allocation is not charged to the active account")
                if AllocationRole.ACTIVE_PRIMARY not in allocation.roles:
                    raise ValueError("HBM allocation is missing its active-primary role")
                if self.registry.overlay(allocation_id).source_pin_count:
                    raise ValueError("HBM allocation retains source pins")
                target_allocations.append(allocation)

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        release_event_id = self._event_id(operation, "release")
        if inactive_allocations or released_allocations:
            ResourceTransaction(
                event_id=release_event_id,
                timestamp_ns=timestamp_ns,
                cause=f"{cause}:release",
                allocation_deltas=[
                    self._allocation_delta(
                        allocation,
                        account_from=HBM_KV_ACTIVE_ACCOUNT,
                        account_to=HBM_KV_INACTIVE_ACCOUNT,
                    )
                    for allocation in inactive_allocations
                ]
                + [
                    self._allocation_delta(
                        allocation,
                        account_from=HBM_KV_ACTIVE_ACCOUNT,
                        account_to=FREE_ACCOUNT,
                    )
                    for allocation in released_allocations
                ],
            ).commit(self.ledgers, journal=self.journal)

        for index, allocation in enumerate(inactive_allocations):
            self.registry.remove_role(
                allocation.allocation_id,
                AllocationRole.ACTIVE_PRIMARY,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"inactive-remove-active:{index}"),
            )
            self.registry.reaccount(
                allocation.allocation_id,
                HBM_KV_INACTIVE_ACCOUNT,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"inactive-reaccount:{index}"),
            )
        for index, allocation in enumerate(released_allocations):
            self.registry.remove_role(
                allocation.allocation_id,
                AllocationRole.ACTIVE_PRIMARY,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"remove-active-role:{index}"),
            )
            self.registry.transition(
                allocation.allocation_id,
                AllocationState.RELEASED,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"released:{index}"),
            )

        released_block_records = [self._record_data(record) for record in records]
        for record in records:
            record.active_request_ids.remove(request_id)
        for record in released_records:
            del self._blocks[record.block_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_BLOCKS_RELEASED",
            {
                "event_id": release_event_id,
                "cause": cause,
                "request_id": request_id,
                "block_count": len(records),
                "inactive_block_ids": [record.block_id for record in inactive_records],
                "physically_released_block_ids": [record.block_id for record in released_records],
                "shared_block_ids": [
                    record.block_id
                    for record in records
                    if record not in inactive_records and record not in released_records
                ],
                # Keep exact IDs even when every physical shard was already
                # LOST and therefore emitted no release mutation.  Registry
                # and transaction records own physical replay; this record
                # owns the logical block removals and binds the omitted full
                # records with a canonical digest.
                "block_ids": [record.block_id for record in records],
                "blocks_sha256": sha256_json(released_block_records),
            },
        )
        self._operation_sequence += 1
        self.audit()

    def validate_hbm_failure(self, resource_ids: frozenset[str]) -> None:
        """Preflight the logical degradation before physical ledger mutation."""

        self.audit()
        affected = resource_ids & set(self._allocated_bytes_per_resource)
        duplicate = affected & self._failed_resource_ids
        if duplicate:
            raise ValueError(f"HBM resources already failed: {sorted(duplicate)}")

    def on_hbm_resources_failed(
        self,
        resource_ids: frozenset[str],
        *,
        gpu_id: str,
        failure_id: str,
        timestamp_ns: int,
    ) -> None:
        """Mark logical blocks degraded after an atomic physical HBM fail-stop.

        Healthy shards stay physically charged until the ordinary scheduler
        release.  Lost shards remain UNAVAILABLE forever and are never moved to
        FREE by that later release.
        """

        if not gpu_id or not failure_id or timestamp_ns < 0:
            raise ValueError("failure identity and non-negative timestamp are required")
        affected = resource_ids & set(self._allocated_bytes_per_resource)
        if not affected:
            return
        if affected & self._failed_resource_ids:
            raise ValueError("logical bridge received duplicate HBM failure")

        operation = self._operation_sequence
        degraded_blocks: list[int] = []
        for block_id in sorted(self._blocks):
            record = self._blocks[block_id]
            newly_lost = tuple(
                allocation_id
                for allocation_id in record.allocation_ids
                if self.registry.get(allocation_id).resource_id in affected
            )
            if not newly_lost:
                continue
            degraded_blocks.append(block_id)
            alias_count = len(record.aliases)
            for allocation_index, allocation_id in enumerate(record.allocation_ids):
                allocation = self.registry.get(allocation_id)
                if allocation_id in newly_lost:
                    if allocation.state is not AllocationState.LOST:
                        raise RuntimeError("physical HBM failure did not lose allocation")
                    continue
                for pin_index in range(alias_count):
                    self.registry.unpin_source(
                        allocation_id,
                        timestamp_ns=timestamp_ns,
                        event_id=self._event_id(
                            operation,
                            f"failure-unpin:{block_id}:{allocation_index}:{pin_index}",
                        ),
                    )
                if AllocationRole.CACHE_REUSE in allocation.roles:
                    self.registry.remove_role(
                        allocation_id,
                        AllocationRole.CACHE_REUSE,
                        timestamp_ns=timestamp_ns,
                        event_id=self._event_id(
                            operation,
                            f"failure-remove-reuse:{block_id}:{allocation_index}",
                        ),
                    )
            record.aliases.clear()
            record.cache_hash = None
            record.logical_hash = None
            record.lost_allocation_ids = tuple(
                sorted(set(record.lost_allocation_ids) | set(newly_lost))
            )

        degraded_reservations: list[str] = []
        for request_id, records in sorted(self._recovery_reservations.items()):
            reservation_degraded = False
            for record in records:
                newly_lost = tuple(
                    allocation_id
                    for allocation_id in record.allocation_ids
                    if self.registry.get(allocation_id).resource_id in affected
                )
                if not newly_lost:
                    continue
                reservation_degraded = True
                for allocation_id in newly_lost:
                    if self.registry.get(allocation_id).state is not AllocationState.LOST:
                        raise RuntimeError(
                            "physical HBM failure did not lose a recovery reservation"
                        )
                record.lost_allocation_ids = tuple(
                    sorted(set(record.lost_allocation_ids) | set(newly_lost))
                )
            if reservation_degraded:
                degraded_reservations.append(request_id)

        self._failed_resource_ids.update(affected)
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_RESOURCES_FAILED",
            {
                "event_id": self._event_id(operation, "hbm-resources-failed"),
                "gpu_id": gpu_id,
                "failure_id": failure_id,
                "resource_ids": sorted(affected),
                "degraded_block_ids": degraded_blocks,
                "degraded_recovery_request_ids": degraded_reservations,
            },
        )
        self._operation_sequence += 1
        self.audit()

    def retain_alias(
        self,
        block_id: int,
        *,
        alias_id: str,
        logical_hash: str,
        cause: str = "vllm.logical-alias-retain",
    ) -> None:
        """Add a logical hash/reference overlay without another byte charge."""

        if block_id == 0:
            raise ValueError("the null block cannot carry a physical alias")
        if not alias_id or not logical_hash or not cause:
            raise ValueError("alias_id, logical_hash, and cause must be non-empty")
        self.audit()
        record = self._blocks.get(block_id)
        if record is None:
            raise ValueError(f"logical block has no physical allocation: {block_id}")
        if record.lost_allocation_ids:
            raise ValueError("degraded logical block cannot gain aliases")
        if alias_id in record.aliases:
            raise ValueError(f"duplicate alias_id: {alias_id}")
        if record.logical_hash is not None and record.logical_hash != logical_hash:
            raise ValueError("one physical block generation cannot carry two logical hashes")

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        first_alias = not record.aliases
        for index, allocation_id in enumerate(record.allocation_ids):
            if first_alias and record.cache_hash is None:
                self.registry.add_role(
                    allocation_id,
                    AllocationRole.CACHE_REUSE,
                    timestamp_ns=timestamp_ns,
                    event_id=self._event_id(operation, f"reuse-role:{index}"),
                )
            self.registry.pin_source(
                allocation_id,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"alias-pin:{index}"),
            )
        record.logical_hash = logical_hash
        record.aliases[alias_id] = cause
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_BLOCK_ALIAS_RETAINED",
            {
                "event_id": self._event_id(operation, "alias-retained"),
                "cause": cause,
                "block_id": block_id,
                "alias_id": alias_id,
                "logical_hash": logical_hash,
            },
        )
        self._operation_sequence += 1
        self.audit()

    def release_alias(
        self,
        block_id: int,
        *,
        alias_id: str,
        cause: str = "vllm.logical-alias-release",
    ) -> None:
        """Remove one overlay reference without freeing physical HBM."""

        if not alias_id or not cause:
            raise ValueError("alias_id and cause must be non-empty")
        self.audit()
        record = self._blocks.get(block_id)
        if record is None:
            raise ValueError(f"logical block has no physical allocation: {block_id}")
        if alias_id not in record.aliases:
            raise ValueError(f"unknown alias_id: {alias_id}")

        timestamp_ns = self._timestamp_ns()
        operation = self._operation_sequence
        last_alias = len(record.aliases) == 1
        for index, allocation_id in enumerate(record.allocation_ids):
            self.registry.unpin_source(
                allocation_id,
                timestamp_ns=timestamp_ns,
                event_id=self._event_id(operation, f"alias-unpin:{index}"),
            )
            if last_alias and record.cache_hash is None:
                self.registry.remove_role(
                    allocation_id,
                    AllocationRole.CACHE_REUSE,
                    timestamp_ns=timestamp_ns,
                    event_id=self._event_id(operation, f"remove-reuse-role:{index}"),
                )
        del record.aliases[alias_id]
        self._append_bridge_record(
            timestamp_ns,
            "VLLM_HBM_BLOCK_ALIAS_RELEASED",
            {
                "event_id": self._event_id(operation, "alias-released"),
                "cause": cause,
                "block_id": block_id,
                "alias_id": alias_id,
                "logical_hash": record.logical_hash,
            },
        )
        self._operation_sequence += 1
        self.audit()

    def allocation_ids(self, block_id: int) -> tuple[str, ...]:
        return self._blocks[block_id].allocation_ids

    def audit_scheduler_blocks(
        self,
        block_ref_counts: Mapping[int, int],
        cached_block_hashes: Mapping[int, str],
        reserved_block_ids: set[int],
    ) -> None:
        self.audit()
        actual_reserved_block_ids = {
            record.block_id
            for records in self._recovery_reservations.values()
            for record in records
        }
        if actual_reserved_block_ids != reserved_block_ids:
            raise RuntimeError("scheduler and physical recovery reservations disagree")
        if set(self._blocks) != set(block_ref_counts) | set(cached_block_hashes):
            raise RuntimeError("scheduler logical blocks and physical HBM allocations disagree")
        for block_id, record in self._blocks.items():
            if len(record.active_request_ids) != block_ref_counts.get(block_id, 0):
                raise RuntimeError("scheduler alias refcount and physical overlay disagree")
            if record.cache_hash != cached_block_hashes.get(block_id):
                raise RuntimeError("scheduler cache hash and physical residency disagree")

    def audit(self) -> None:
        self.registry.audit_resources(self.ledgers)
        reserved_block_ids: set[int] = set()
        for request_id, records in self._recovery_reservations.items():
            if not request_id or not records:
                raise RuntimeError("HBM recovery reservation identity is incomplete")
            for record in records:
                if record.request_id != request_id or record.block_id in reserved_block_ids:
                    raise RuntimeError("HBM recovery reservation ownership is ambiguous")
                if record.block_id in self._blocks:
                    raise RuntimeError("logical block is both recovery-reserved and active")
                reserved_block_ids.add(record.block_id)
                if len(record.allocation_ids) != len(self.bindings):
                    raise RuntimeError("recovery block does not cover every stage/rank GPU")
                for binding, allocation_id in zip(
                    self.bindings, record.allocation_ids, strict=True
                ):
                    allocation = self.registry.get(allocation_id)
                    if allocation.resource_id != binding.resource_id:
                        raise RuntimeError("recovery allocation resource differs from its binding")
                    layout = binding.layout
                    expected_geometry = (
                        layout.payload_bytes,
                        layout.requested_bytes,
                        layout.allocated_bytes,
                        layout.layout_padding_bytes,
                        layout.allocator_metadata_bytes,
                        layout.internal_fragmentation_bytes,
                        layout.allocator_alignment_bytes,
                    )
                    actual_geometry = (
                        allocation.payload_bytes,
                        allocation.requested_bytes,
                        allocation.allocated_bytes,
                        allocation.padding_bytes,
                        allocation.allocator_metadata_bytes,
                        allocation.internal_fragmentation_bytes,
                        allocation.alignment_bytes,
                    )
                    if actual_geometry != expected_geometry:
                        raise RuntimeError(
                            "recovery allocation geometry differs from stage/rank layout"
                        )
                    if allocation_id in record.lost_allocation_ids:
                        if (
                            allocation.state is not AllocationState.LOST
                            or allocation.owner_account != UNAVAILABLE_CAPACITY_ACCOUNT
                        ):
                            raise RuntimeError("lost recovery allocation is not unavailable")
                    elif (
                        allocation.state is not AllocationState.RESERVED
                        or allocation.owner_account != HBM_RECOVERY_RESERVED_ACCOUNT
                    ):
                        raise RuntimeError("healthy recovery allocation is not charged as RESERVED")
                    overlay = self.registry.overlay(allocation_id)
                    if allocation.roles or overlay.source_pin_count:
                        raise RuntimeError("recovery reservation retains roles or source pins")
                    if overlay.recovery_eligible:
                        raise RuntimeError("recovery destination is itself recovery eligible")
        for block_id, record in self._blocks.items():
            if block_id <= 0 or record.block_id != block_id:
                raise RuntimeError("null or mismatched logical block record")
            if any(not request_id for request_id in record.active_request_ids):
                raise RuntimeError("logical block has an empty active request ID")
            if (
                not record.active_request_ids
                and record.cache_hash is None
                and not record.lost_allocation_ids
            ):
                raise RuntimeError("healthy inactive block is not reusable")
            if len(record.allocation_ids) != len(self.bindings):
                raise RuntimeError("logical block does not cover every stage/rank GPU")
            for binding, allocation_id in zip(self.bindings, record.allocation_ids, strict=True):
                allocation = self.registry.get(allocation_id)
                layout = binding.layout
                if allocation.resource_id != binding.resource_id:
                    raise RuntimeError("allocation resource differs from its binding")
                expected_geometry = (
                    layout.payload_bytes,
                    layout.requested_bytes,
                    layout.allocated_bytes,
                    layout.layout_padding_bytes,
                    layout.allocator_metadata_bytes,
                    layout.internal_fragmentation_bytes,
                    layout.allocator_alignment_bytes,
                )
                actual_geometry = (
                    allocation.payload_bytes,
                    allocation.requested_bytes,
                    allocation.allocated_bytes,
                    allocation.padding_bytes,
                    allocation.allocator_metadata_bytes,
                    allocation.internal_fragmentation_bytes,
                    allocation.alignment_bytes,
                )
                if actual_geometry != expected_geometry:
                    raise RuntimeError("allocation geometry differs from stage/rank layout")
                allocation_lost = allocation_id in record.lost_allocation_ids
                if allocation_lost:
                    if allocation.state is not AllocationState.LOST:
                        raise RuntimeError("degraded logical block has a non-lost shard")
                    if allocation.owner_account != UNAVAILABLE_CAPACITY_ACCOUNT:
                        raise RuntimeError("lost logical shard is not unavailable")
                    overlay = self.registry.overlay(allocation_id)
                    if allocation.roles or overlay.source_pin_count:
                        raise RuntimeError("lost logical shard retains roles or pins")
                    if overlay.recovery_eligible:
                        raise RuntimeError("lost logical shard remains recovery eligible")
                    continue
                if allocation.state is not AllocationState.COMMITTED:
                    raise RuntimeError("resident logical block has a non-committed allocation")
                expected_account = (
                    HBM_KV_ACTIVE_ACCOUNT if record.active_request_ids else HBM_KV_INACTIVE_ACCOUNT
                )
                if allocation.owner_account != expected_account:
                    raise RuntimeError("resident logical block is charged to the wrong account")
                has_active_role = AllocationRole.ACTIVE_PRIMARY in allocation.roles
                if has_active_role != bool(record.active_request_ids):
                    raise RuntimeError("active-primary role differs from request refcount")
                has_reuse_role = AllocationRole.CACHE_REUSE in allocation.roles
                if has_reuse_role != bool(record.cache_hash or record.aliases):
                    raise RuntimeError("cache-reuse role differs from cache/alias overlay")
                if self.registry.overlay(allocation_id).source_pin_count != len(record.aliases):
                    raise RuntimeError("source-pin count differs from alias overlay")
            if record.lost_allocation_ids and record.aliases:
                raise RuntimeError("degraded logical block retains aliases")

    def snapshot_bytes(self) -> bytes:
        snapshot = {
            "bridge_id": self.bridge_id,
            "evidence_class": EVIDENCE_CLASS,
            "bindings": [
                {
                    "resource_id": binding.resource_id,
                    "layout": binding.layout.to_dict(),
                }
                for binding in self.bindings
            ],
            "blocks": [
                self._record_data(self._blocks[block_id]) for block_id in sorted(self._blocks)
            ],
            "recovery_reservations": {
                request_id: [self._record_data(record) for record in records]
                for request_id, records in sorted(self._recovery_reservations.items())
            },
            "last_generation": {
                str(block_id): generation
                for block_id, generation in sorted(self._last_generation.items())
            },
            "failed_resource_ids": sorted(self._failed_resource_ids),
        }
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()

    def _evictable_inactive_allocations(
        self,
        record: _LogicalBlockRecord,
    ) -> tuple[PhysicalAllocation, ...]:
        if (
            record.active_request_ids
            or record.cache_hash is None
            or record.aliases
            or record.lost_allocation_ids
        ):
            return ()
        allocations = tuple(
            self.registry.get(allocation_id) for allocation_id in record.allocation_ids
        )
        if any(
            allocation.state is not AllocationState.COMMITTED
            or allocation.owner_account != HBM_KV_INACTIVE_ACCOUNT
            or AllocationRole.ACTIVE_PRIMARY in allocation.roles
            or AllocationRole.CACHE_REUSE not in allocation.roles
            or self.registry.overlay(allocation.allocation_id).source_pin_count
            for allocation in allocations
        ):
            return ()
        return allocations

    def _unavailable_hbm_resource_ids(self) -> tuple[str, ...]:
        failed_resource_ids = set(self._failed_resource_ids)
        failed_resource_ids.update(
            resource_id
            for resource_id in self._allocated_bytes_per_resource
            if self.ledgers[resource_id].bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) > 0
        )
        return tuple(sorted(failed_resource_ids))

    def _build_allocations(
        self,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        timestamp_ns: int,
        owner_account: str = HBM_KV_RESERVED_ACCOUNT,
    ) -> tuple[list[_LogicalBlockRecord], list[PhysicalAllocation]]:
        records: list[_LogicalBlockRecord] = []
        allocations: list[PhysicalAllocation] = []
        for block_id in block_ids:
            generation = self._last_generation.get(block_id, -1) + 1
            object_id = f"{self.bridge_id}:logical-block:{block_id}:generation:{generation}"
            allocation_ids: list[str] = []
            for binding in self.bindings:
                layout = binding.layout
                allocation_id = f"{object_id}:pp:{layout.pp_stage}:tp:{layout.tensor_parallel_rank}"
                allocation_ids.append(allocation_id)
                allocations.append(
                    PhysicalAllocation(
                        allocation_id=allocation_id,
                        object_id=object_id,
                        replica_id=(
                            f"{object_id}:gpu:{binding.resource_id}:"
                            f"pp:{layout.pp_stage}:tp:{layout.tensor_parallel_rank}"
                        ),
                        resource_id=binding.resource_id,
                        owner_account=owner_account,
                        payload_bytes=layout.payload_bytes,
                        requested_bytes=layout.requested_bytes,
                        allocated_bytes=layout.allocated_bytes,
                        padding_bytes=layout.layout_padding_bytes,
                        allocator_metadata_bytes=layout.allocator_metadata_bytes,
                        internal_fragmentation_bytes=(layout.internal_fragmentation_bytes),
                        alignment_bytes=layout.allocator_alignment_bytes,
                        state=AllocationState.RESERVED,
                        created_at_ns=timestamp_ns,
                    )
                )
            records.append(
                _LogicalBlockRecord(
                    block_id=block_id,
                    generation=generation,
                    request_id=request_id,
                    object_id=object_id,
                    allocation_ids=tuple(allocation_ids),
                    active_request_ids={request_id},
                )
            )
        return records, allocations

    def _require_recovery_reservation(
        self,
        request_id: str,
        block_ids: tuple[int, ...],
    ) -> tuple[_LogicalBlockRecord, ...]:
        try:
            records = self._recovery_reservations[request_id]
        except KeyError as error:
            raise KeyError(f"request has no HBM recovery reservation: {request_id}") from error
        if tuple(record.block_id for record in records) != block_ids:
            raise ValueError("HBM recovery reservation block binding changed")
        return records

    @staticmethod
    def _allocation_delta(
        allocation: PhysicalAllocation,
        *,
        account_from: str,
        account_to: str,
    ) -> AllocationDelta:
        return AllocationDelta(
            resource_id=allocation.resource_id,
            account_from=account_from,
            account_to=account_to,
            delta_bytes=allocation.allocated_bytes,
            allocation_id=allocation.allocation_id,
            object_id=allocation.object_id,
            replica_id=allocation.replica_id,
        )

    @staticmethod
    def _ordinary_block_ids(block_ids: tuple[int, ...]) -> tuple[int, ...]:
        if any(type(block_id) is not int or block_id < 0 for block_id in block_ids):
            raise ValueError("block IDs must be non-negative integers")
        ordinary = tuple(block_id for block_id in block_ids if block_id != 0)
        if len(ordinary) != len(set(ordinary)):
            raise ValueError("block operation contains a duplicate block ID")
        return ordinary

    def _timestamp_ns(self) -> int:
        value = self._now_ns()
        if type(value) is not int or value < 0:
            raise ValueError("now_ns must return a non-negative integer")
        return value

    def _event_id(self, operation: int, suffix: str) -> str:
        return f"{self.bridge_id}:operation:{operation}:{suffix}"

    def _append_bridge_record(
        self, timestamp_ns: int, record_type: str, data: dict[str, Any]
    ) -> None:
        self.journal.append(timestamp_ns, record_type, data)

    @staticmethod
    def _record_data(record: _LogicalBlockRecord) -> dict[str, Any]:
        data = asdict(record)
        data["aliases"] = dict(sorted(record.aliases.items()))
        data["active_request_ids"] = sorted(record.active_request_ids)
        return data


def _object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _integer(value: Mapping[str, Any], key: str) -> int:
    result = value.get(key)
    if type(result) is not int:
        raise ValueError(f"{key} must be an integer")
    return result


def _string_tuple(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    result = value.get(key)
    if not isinstance(result, list) or not all(isinstance(item, str) and item for item in result):
        raise ValueError(f"{key} must be a non-empty string array")
    return tuple(result)


def _integer_tuple(value: Mapping[str, Any], key: str) -> tuple[int, ...]:
    result = value.get(key)
    if not isinstance(result, list) or not all(type(item) is int for item in result):
        raise ValueError(f"{key} must be an integer array")
    return tuple(result)
