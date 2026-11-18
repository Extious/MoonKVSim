"""Fail-closed heterogeneous AegisKV recovery-prefix planner.

The planner is intentionally pure and consumes normalized directory candidates.
An integration adapter may construct those candidates from the single
``GlobalKVDirectory`` plus ``AllocationRegistry`` without creating a second
metadata authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from moonkvsim.common.hash import canonical_json_bytes, sha256_json


class RecoveryPlanningError(ValueError):
    """A recovery request or selected source violates the frozen contract."""


class RecoverySourceKind(StrEnum):
    PEER_HBM = "PEER_HBM"
    STORE_DRAM = "STORE_DRAM"
    RECOMPUTE = "RECOMPUTE"


def _canonical_ids(values: tuple[str, ...], label: str, *, allow_empty: bool = False) -> None:
    if not allow_empty and not values:
        raise RecoveryPlanningError(f"{label} must not be empty")
    if any(not value for value in values):
        raise RecoveryPlanningError(f"{label} must contain non-empty strings")
    if tuple(sorted(set(values))) != values:
        raise RecoveryPlanningError(f"{label} must be sorted and unique")


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise RecoveryPlanningError("enum-compatible value must resolve to a string")
    return raw


def _required_attr(value: object, name: str, expected_type: type[Any]) -> Any:
    try:
        result = getattr(value, name)
    except AttributeError as error:
        raise RecoveryPlanningError(f"required identity is missing {name}") from error
    if not isinstance(result, expected_type) or (expected_type is int and isinstance(result, bool)):
        raise RecoveryPlanningError(f"required identity {name} has the wrong type")
    return result


@dataclass(frozen=True, slots=True)
class RecoveryBlockRequirement:
    object_id: str
    tenant_id: str
    model_id: str
    model_revision: str
    kv_dtype: str
    kv_abi: str
    kv_layout: str
    tp_size: int
    pp_size: int
    block_size_tokens: int
    stable_block_hash: str
    token_start: int
    token_end: int
    shard_group_id: str

    def __post_init__(self) -> None:
        strings = (
            self.object_id,
            self.tenant_id,
            self.model_id,
            self.model_revision,
            self.kv_dtype,
            self.kv_abi,
            self.kv_layout,
            self.stable_block_hash,
            self.shard_group_id,
        )
        if any(not value for value in strings):
            raise RecoveryPlanningError("recovery block identifiers must be non-empty")
        if self.tp_size <= 0 or self.pp_size <= 0 or self.block_size_tokens <= 0:
            raise RecoveryPlanningError("TP, PP, and block size must be positive")
        if self.token_start < 0 or self.token_end <= self.token_start:
            raise RecoveryPlanningError("recovery block token interval is invalid")
        if self.token_end - self.token_start > self.block_size_tokens:
            raise RecoveryPlanningError("recovery interval exceeds its declared block size")

    @classmethod
    def from_identity(cls, identity: object) -> RecoveryBlockRequirement:
        return cls(
            object_id=_required_attr(identity, "object_id", str),
            tenant_id=_required_attr(identity, "tenant_id", str),
            model_id=_required_attr(identity, "model_id", str),
            model_revision=_required_attr(identity, "model_revision", str),
            kv_dtype=_required_attr(identity, "kv_dtype", str),
            kv_abi=_required_attr(identity, "kv_abi", str),
            kv_layout=_required_attr(identity, "kv_layout", str),
            tp_size=_required_attr(identity, "tp_size", int),
            pp_size=_required_attr(identity, "pp_size", int),
            block_size_tokens=_required_attr(identity, "block_size_tokens", int),
            stable_block_hash=_required_attr(identity, "stable_block_hash", str),
            token_start=_required_attr(identity, "token_start", int),
            token_end=_required_attr(identity, "token_end", int),
            shard_group_id=_required_attr(identity, "shard_id", str),
        )

    @property
    def compatibility_key(self) -> tuple[str | int, ...]:
        return (
            self.tenant_id,
            self.model_id,
            self.model_revision,
            self.kv_dtype,
            self.kv_abi,
            self.kv_layout,
            self.tp_size,
            self.pp_size,
            self.block_size_tokens,
            self.shard_group_id,
        )

    @property
    def token_count(self) -> int:
        return self.token_end - self.token_start

    @property
    def is_full_aligned_block(self) -> bool:
        return (
            self.token_start % self.block_size_tokens == 0
            and self.token_count == self.block_size_tokens
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "block_size_tokens": self.block_size_tokens,
            "compatibility_key": list(self.compatibility_key),
            "kv_abi": self.kv_abi,
            "kv_dtype": self.kv_dtype,
            "kv_layout": self.kv_layout,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "object_id": self.object_id,
            "pp_size": self.pp_size,
            "shard_group_id": self.shard_group_id,
            "stable_block_hash": self.stable_block_hash,
            "tenant_id": self.tenant_id,
            "token_end": self.token_end,
            "token_start": self.token_start,
            "tp_size": self.tp_size,
        }


@dataclass(frozen=True, slots=True)
class RecoveryShardCandidate:
    shard_id: str
    allocation_id: str
    resource_id: str
    resource_kind: str
    allocation_state: str
    recovery_eligible: bool
    object_id: str
    replica_id: str

    def __post_init__(self) -> None:
        strings = (
            self.shard_id,
            self.allocation_id,
            self.resource_id,
            _enum_value(self.resource_kind),
            _enum_value(self.allocation_state),
            self.object_id,
            self.replica_id,
        )
        if any(not value for value in strings):
            raise RecoveryPlanningError("recovery shard fields must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "allocation_id": self.allocation_id,
            "allocation_state": _enum_value(self.allocation_state),
            "object_id": self.object_id,
            "recovery_eligible": self.recovery_eligible,
            "replica_id": self.replica_id,
            "resource_id": self.resource_id,
            "resource_kind": _enum_value(self.resource_kind),
            "shard_id": self.shard_id,
        }


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    replica_id: str
    object_id: str
    source_kind: RecoverySourceKind
    location: str
    state: str
    visible: bool
    generation: int
    source_route_version: int
    source_route_authoritative: bool
    compatibility_key: tuple[str | int, ...]
    resident_target_id: str
    expected_shard_ids: tuple[str, ...]
    completed_shard_ids: tuple[str, ...]
    shards: tuple[RecoveryShardCandidate, ...]
    source_lineage_gpu_id: str | None = None

    def __post_init__(self) -> None:
        if not self.replica_id or not self.object_id or not self.resident_target_id:
            raise RecoveryPlanningError("recovery candidate identifiers must be non-empty")
        if self.source_kind is RecoverySourceKind.RECOMPUTE:
            raise RecoveryPlanningError("RECOMPUTE is not a directory replica candidate")
        if _enum_value(self.location) != self.source_kind.value:
            raise RecoveryPlanningError(
                "candidate source kind must match its authoritative directory location"
            )
        if self.generation < 0 or self.source_route_version < 0:
            raise RecoveryPlanningError(
                "candidate generation and route version must be non-negative"
            )
        if not self.compatibility_key or any(
            not isinstance(value, (str, int)) or isinstance(value, bool)
            for value in self.compatibility_key
        ):
            raise RecoveryPlanningError("candidate compatibility_key is invalid")
        _canonical_ids(self.expected_shard_ids, "candidate expected_shard_ids")
        _canonical_ids(
            self.completed_shard_ids,
            "candidate completed_shard_ids",
            allow_empty=True,
        )
        shard_ids = tuple(shard.shard_id for shard in self.shards)
        if tuple(sorted(set(shard_ids))) != shard_ids:
            raise RecoveryPlanningError("candidate shards must be sorted and unique")
        allocation_ids = tuple(shard.allocation_id for shard in self.shards)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise RecoveryPlanningError("candidate allocation bindings must be unique")
        if self.source_lineage_gpu_id is not None and not self.source_lineage_gpu_id:
            raise RecoveryPlanningError("source_lineage_gpu_id cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "compatibility_key": list(self.compatibility_key),
            "completed_shard_ids": list(self.completed_shard_ids),
            "expected_shard_ids": list(self.expected_shard_ids),
            "generation": self.generation,
            "location": _enum_value(self.location),
            "object_id": self.object_id,
            "replica_id": self.replica_id,
            "resident_target_id": self.resident_target_id,
            "shards": [shard.to_dict() for shard in self.shards],
            "source_kind": self.source_kind.value,
            "source_lineage_gpu_id": self.source_lineage_gpu_id,
            "source_route_authoritative": self.source_route_authoritative,
            "source_route_version": self.source_route_version,
            "state": _enum_value(self.state),
            "visible": self.visible,
        }


@dataclass(frozen=True, slots=True)
class RecoveryPlanningContext:
    request_id: str
    failure_id: str
    parent_route_version: int
    recovery_route_version: int
    source_target_id: str
    destination_target_id: str
    failed_target_ids: tuple[str, ...]
    failed_gpu_ids: tuple[str, ...]
    unavailable_resource_ids: tuple[str, ...]
    required_shard_ids: tuple[str, ...]
    timestamp_ns: int

    def __post_init__(self) -> None:
        identifiers = (
            self.request_id,
            self.failure_id,
            self.source_target_id,
            self.destination_target_id,
        )
        if any(not value for value in identifiers):
            raise RecoveryPlanningError("recovery context identifiers must be non-empty")
        if self.parent_route_version < 0:
            raise RecoveryPlanningError("parent route version must be non-negative")
        if self.recovery_route_version != self.parent_route_version + 1:
            raise RecoveryPlanningError("recovery route must be exactly parent route + 1")
        if self.timestamp_ns < 0:
            raise RecoveryPlanningError("timestamp_ns must be non-negative")
        _canonical_ids(self.failed_target_ids, "failed_target_ids")
        _canonical_ids(self.failed_gpu_ids, "failed_gpu_ids")
        _canonical_ids(self.unavailable_resource_ids, "unavailable_resource_ids")
        _canonical_ids(self.required_shard_ids, "required_shard_ids")
        if self.source_target_id not in self.failed_target_ids:
            raise RecoveryPlanningError("source target must be one of the failed targets")
        if self.destination_target_id in self.failed_target_ids:
            raise RecoveryPlanningError("destination target must be healthy")

    def to_dict(self) -> dict[str, object]:
        return {
            "destination_target_id": self.destination_target_id,
            "failed_gpu_ids": list(self.failed_gpu_ids),
            "failed_target_ids": list(self.failed_target_ids),
            "failure_id": self.failure_id,
            "parent_route_version": self.parent_route_version,
            "recovery_route_version": self.recovery_route_version,
            "request_id": self.request_id,
            "required_shard_ids": list(self.required_shard_ids),
            "source_target_id": self.source_target_id,
            "timestamp_ns": self.timestamp_ns,
            "unavailable_resource_ids": list(self.unavailable_resource_ids),
        }


@dataclass(frozen=True, slots=True)
class RecoveryBlockChoice:
    requirement: RecoveryBlockRequirement
    source_kind: RecoverySourceKind
    replica_id: str | None = None
    replica_generation: int | None = None
    source_route_version: int | None = None
    resident_target_id: str | None = None
    source_lineage_gpu_id: str | None = None
    shards: tuple[RecoveryShardCandidate, ...] = ()

    def __post_init__(self) -> None:
        source_fields = (
            self.replica_id,
            self.replica_generation,
            self.source_route_version,
            self.resident_target_id,
        )
        if self.source_kind is RecoverySourceKind.RECOMPUTE:
            if any(value is not None for value in source_fields) or self.shards:
                raise RecoveryPlanningError("RECOMPUTE blocks cannot bind a replica")
        elif any(value is None for value in source_fields) or not self.shards:
            raise RecoveryPlanningError("materialized blocks require a complete source binding")

    def to_dict(self) -> dict[str, object]:
        return {
            "replica_generation": self.replica_generation,
            "replica_id": self.replica_id,
            "requirement": self.requirement.to_dict(),
            "resident_target_id": self.resident_target_id,
            "shards": [shard.to_dict() for shard in self.shards],
            "source_kind": self.source_kind.value,
            "source_lineage_gpu_id": self.source_lineage_gpu_id,
            "source_route_version": self.source_route_version,
        }


@dataclass(frozen=True, slots=True)
class HeterogeneousRecoveryPlan:
    context: RecoveryPlanningContext
    source_preference: tuple[RecoverySourceKind, ...]
    blocks: tuple[RecoveryBlockChoice, ...]
    missing_suffix_start_block: int
    peer_hbm_tokens: int
    store_dram_tokens: int
    recompute_tokens: int

    def __post_init__(self) -> None:
        if not self.blocks:
            raise RecoveryPlanningError("recovery plan must contain at least one block")
        if not 0 <= self.missing_suffix_start_block <= len(self.blocks):
            raise RecoveryPlanningError("missing suffix start is outside the plan")
        expected_kinds = (
            RecoverySourceKind.PEER_HBM,
            RecoverySourceKind.STORE_DRAM,
        )
        if len(self.source_preference) != 2 or set(self.source_preference) != set(expected_kinds):
            raise RecoveryPlanningError("source preference must order Peer-HBM and Store-DRAM")
        for index, block in enumerate(self.blocks):
            should_recompute = index >= self.missing_suffix_start_block
            if should_recompute != (block.source_kind is RecoverySourceKind.RECOMPUTE):
                raise RecoveryPlanningError(
                    "recovery sources must form one prefix plus recompute suffix"
                )
        counts = {
            RecoverySourceKind.PEER_HBM: sum(
                block.requirement.token_count
                for block in self.blocks
                if block.source_kind is RecoverySourceKind.PEER_HBM
            ),
            RecoverySourceKind.STORE_DRAM: sum(
                block.requirement.token_count
                for block in self.blocks
                if block.source_kind is RecoverySourceKind.STORE_DRAM
            ),
            RecoverySourceKind.RECOMPUTE: sum(
                block.requirement.token_count
                for block in self.blocks
                if block.source_kind is RecoverySourceKind.RECOMPUTE
            ),
        }
        if (
            self.peer_hbm_tokens != counts[RecoverySourceKind.PEER_HBM]
            or self.store_dram_tokens != counts[RecoverySourceKind.STORE_DRAM]
            or self.recompute_tokens != counts[RecoverySourceKind.RECOMPUTE]
        ):
            raise RecoveryPlanningError("recovery token accounting does not match block choices")

    @property
    def restored_tokens(self) -> int:
        return self.peer_hbm_tokens + self.store_dram_tokens

    def canonical_fields(self) -> dict[str, object]:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "capacity_hold_contract": {
                "activation_requires_all_shards": True,
                "destination_hold_before_transfer": True,
                "source_pin_before_transfer": True,
            },
            "context": self.context.to_dict(),
            "missing_suffix_start_block": self.missing_suffix_start_block,
            "peer_hbm_tokens": self.peer_hbm_tokens,
            "planner_semantics": "CONTINUOUS_PREFIX_THEN_RECOMPUTE_SUFFIX",
            "recompute_tokens": self.recompute_tokens,
            "restored_tokens": self.restored_tokens,
            "source_preference": [kind.value for kind in self.source_preference],
            "store_dram_tokens": self.store_dram_tokens,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"


class AegisRecoveryPlanner:
    """Select full-shard Peer/Store sources until the first ineligible block."""

    def __init__(self, *, source_preference: tuple[RecoverySourceKind, ...]) -> None:
        expected = {RecoverySourceKind.PEER_HBM, RecoverySourceKind.STORE_DRAM}
        if len(source_preference) != 2 or set(source_preference) != expected:
            raise RecoveryPlanningError(
                "source_preference must explicitly order Peer-HBM and Store-DRAM"
            )
        self.source_preference = source_preference
        self._source_rank = {kind: rank for rank, kind in enumerate(source_preference)}

    def plan(
        self,
        required_blocks: Sequence[RecoveryBlockRequirement | object],
        *,
        candidates_by_object_id: Mapping[str, Sequence[RecoveryCandidate]],
        context: RecoveryPlanningContext,
    ) -> HeterogeneousRecoveryPlan:
        requirements = tuple(
            block
            if isinstance(block, RecoveryBlockRequirement)
            else RecoveryBlockRequirement.from_identity(block)
            for block in required_blocks
        )
        self._validate_requirements(requirements)
        choices: list[RecoveryBlockChoice] = []
        gap_found = False
        missing_suffix_start = len(requirements)
        seen_candidate_ids: set[str] = set()
        seen_allocation_ids: set[str] = set()

        for index, requirement in enumerate(requirements):
            if gap_found or not requirement.is_full_aligned_block:
                if not gap_found:
                    missing_suffix_start = index
                    gap_found = True
                choices.append(
                    RecoveryBlockChoice(
                        requirement=requirement,
                        source_kind=RecoverySourceKind.RECOMPUTE,
                    )
                )
                continue

            candidates = tuple(candidates_by_object_id.get(requirement.object_id, ()))
            ids = tuple(candidate.replica_id for candidate in candidates)
            if len(set(ids)) != len(ids):
                raise RecoveryPlanningError("one block contains duplicate replica candidates")
            eligible = tuple(
                candidate
                for candidate in candidates
                if self._eligible(candidate, requirement, context)
            )
            eligible = tuple(
                sorted(
                    eligible,
                    key=lambda candidate: (
                        self._source_rank[candidate.source_kind],
                        candidate.replica_id,
                        candidate.generation,
                    ),
                )
            )
            if not eligible:
                missing_suffix_start = index
                gap_found = True
                choices.append(
                    RecoveryBlockChoice(
                        requirement=requirement,
                        source_kind=RecoverySourceKind.RECOMPUTE,
                    )
                )
                continue
            selected = eligible[0]
            if selected.replica_id in seen_candidate_ids:
                raise RecoveryPlanningError("one physical replica cannot satisfy multiple blocks")
            seen_candidate_ids.add(selected.replica_id)
            selected_allocation_ids = {shard.allocation_id for shard in selected.shards}
            if seen_allocation_ids & selected_allocation_ids:
                raise RecoveryPlanningError(
                    "one physical allocation cannot satisfy multiple recovery blocks"
                )
            seen_allocation_ids.update(selected_allocation_ids)
            choices.append(self._choice(requirement, selected))

        peer_tokens = sum(
            choice.requirement.token_count
            for choice in choices
            if choice.source_kind is RecoverySourceKind.PEER_HBM
        )
        store_tokens = sum(
            choice.requirement.token_count
            for choice in choices
            if choice.source_kind is RecoverySourceKind.STORE_DRAM
        )
        recompute_tokens = sum(
            choice.requirement.token_count
            for choice in choices
            if choice.source_kind is RecoverySourceKind.RECOMPUTE
        )
        return HeterogeneousRecoveryPlan(
            context=context,
            source_preference=self.source_preference,
            blocks=tuple(choices),
            missing_suffix_start_block=missing_suffix_start,
            peer_hbm_tokens=peer_tokens,
            store_dram_tokens=store_tokens,
            recompute_tokens=recompute_tokens,
        )

    def validate_selected_sources(
        self,
        plan: HeterogeneousRecoveryPlan,
        *,
        candidates_by_object_id: Mapping[str, Sequence[RecoveryCandidate]],
        context: RecoveryPlanningContext,
    ) -> None:
        """Revalidate selected sources without changing choices due to new replicas."""

        if plan.context != context or plan.source_preference != self.source_preference:
            raise RecoveryPlanningError("recovery plan is bound to another route or selector")
        for block in plan.blocks[: plan.missing_suffix_start_block]:
            matching = tuple(
                candidate
                for candidate in candidates_by_object_id.get(block.requirement.object_id, ())
                if candidate.replica_id == block.replica_id
                and candidate.generation == block.replica_generation
            )
            if len(matching) != 1:
                raise RecoveryPlanningError("selected recovery replica changed or disappeared")
            candidate = matching[0]
            if not self._eligible(candidate, block.requirement, context):
                raise RecoveryPlanningError("selected recovery replica is no longer eligible")
            if self._choice(block.requirement, candidate) != block:
                raise RecoveryPlanningError("selected recovery source binding changed")

    @staticmethod
    def _validate_requirements(requirements: tuple[RecoveryBlockRequirement, ...]) -> None:
        if not requirements:
            raise RecoveryPlanningError("required recovery blocks must not be empty")
        if requirements[0].token_start != 0:
            raise RecoveryPlanningError("recovery blocks must start at token zero")
        compatibility_key = requirements[0].compatibility_key
        expected_start = 0
        object_ids: set[str] = set()
        for requirement in requirements:
            if requirement.compatibility_key != compatibility_key:
                raise RecoveryPlanningError("required blocks have incompatible ABI/layout/sharding")
            if requirement.token_start != expected_start:
                raise RecoveryPlanningError("required recovery blocks must be continuous")
            if requirement.object_id in object_ids:
                raise RecoveryPlanningError("required recovery object ids must be unique")
            object_ids.add(requirement.object_id)
            expected_start = requirement.token_end

    @staticmethod
    def _eligible(
        candidate: RecoveryCandidate,
        requirement: RecoveryBlockRequirement,
        context: RecoveryPlanningContext,
    ) -> bool:
        if (
            _enum_value(candidate.state) != "COMMITTED"
            or not candidate.visible
            or not candidate.source_route_authoritative
            or candidate.object_id != requirement.object_id
            or candidate.compatibility_key != requirement.compatibility_key
            or candidate.expected_shard_ids != context.required_shard_ids
            or candidate.completed_shard_ids != context.required_shard_ids
        ):
            return False
        if candidate.source_kind is RecoverySourceKind.PEER_HBM:
            if candidate.resident_target_id in context.failed_target_ids:
                return False
            expected_resource_kind = "GPU_HBM"
        else:
            expected_resource_kind = "STORE_DRAM"
        if tuple(shard.shard_id for shard in candidate.shards) != context.required_shard_ids:
            return False
        unavailable = frozenset(context.unavailable_resource_ids)
        for shard in candidate.shards:
            if (
                _enum_value(shard.allocation_state) != "COMMITTED"
                or not shard.recovery_eligible
                or shard.object_id != candidate.object_id
                or shard.replica_id != candidate.replica_id
                or _enum_value(shard.resource_kind) != expected_resource_kind
                or shard.resource_id in unavailable
            ):
                return False
        return True

    @staticmethod
    def _choice(
        requirement: RecoveryBlockRequirement,
        candidate: RecoveryCandidate,
    ) -> RecoveryBlockChoice:
        return RecoveryBlockChoice(
            requirement=requirement,
            source_kind=candidate.source_kind,
            replica_id=candidate.replica_id,
            replica_generation=candidate.generation,
            source_route_version=candidate.source_route_version,
            resident_target_id=candidate.resident_target_id,
            source_lineage_gpu_id=candidate.source_lineage_gpu_id,
            shards=candidate.shards,
        )
