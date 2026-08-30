"""Deterministic matched AegisKV study on the repository-wide GlobalDES clock.

This is an E2 workload-level experiment harness.  Every timestamp is virtual;
the rates and policy fractions below are explicit modeled assumptions.  The
module deliberately contains no CUDA, Slurm, network socket, or wall-clock
measurement path.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment_workload import (
    CONTEXT_BUCKETS,
    bucket_name_for,
)
from moonkvsim.aegiskv.hbm_quota_aimd import (
    AIMDParameters,
    AIMDTargetState,
    HBMQuotaAIMD,
)
from moonkvsim.aegiskv.rental_value import RentalValueInputs, compute_rental_value
from moonkvsim.aegiskv.types import (
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.resource import ConcurrencyResource, Reservation
from moonkvsim.workload.causal_replay import CausalReleaseEngine
from moonkvsim.workload.causal_trace import (
    NormalizedSpanMetadata,
    load_normalized_trace_records,
)

SOURCE_BLOCK_TOKENS: Final = 64
KV_BYTES_PER_SOURCE_BLOCK: Final = 9_437_184
GIB: Final = 1024**3
AIMD_PARAMETERS: Final = AIMDParameters(
    minimum_fraction=Decimal("0.25"),
    maximum_fraction=Decimal("0.90"),
    multiplicative_decrease=Decimal("0.50"),
    additive_increase=Decimal("0.05"),
    stable_window_count=4,
)

_FAILURE_SCHEDULE_CACHE: dict[tuple[str, str, int], dict[str, FailureSchedule]] = {}


class ExperimentError(RuntimeError):
    """The modeled study failed a deterministic or scope invariant."""


class Scenario(StrEnum):
    NO_FAILURE = "no_failure"
    GPU_FAILURE = "gpu_failure"


class SystemId(StrEnum):
    RECOMPUTE_ONLY = "recompute_only"
    VANILLA_MOONCAKE_DRAM = "vanilla_mooncake_dram"
    STATIC_PEER_HBM = "static_peer_hbm"
    AEGIS_DRAM_ONLY = "aegiskv_dram_only"
    AEGIS_PEER_ONLY = "aegiskv_peer_only"
    AEGIS_HBM_DRAM = "aegiskv_hbm_dram"
    AEGIS_UNIFIED = "aegiskv_unified"


class EvictionKind(StrEnum):
    FIFO = "fifo"
    LRU = "lru"
    LFU = "lfu"
    RANDOM_STABLE = "random_stable"
    SLACK_LANDLORD_VALUE = "slack_landlord_value"


@dataclass(frozen=True, slots=True)
class SystemProfile:
    system_id: SystemId
    label: str
    peer_fraction: Fraction
    store_fraction: Fraction
    peer_cache_reuse: bool
    store_cache_reuse: bool
    eviction: EvictionKind
    slack_weight: int
    reuse_weight: int
    recovery_weight: int
    unified_manager: bool
    aimd_enabled: bool
    anti_colocation: bool = True
    cache_aware_routing: bool = True

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("system label must be non-empty")
        for value in (self.peer_fraction, self.store_fraction):
            if value < 0 or value > 1:
                raise ValueError("protection fractions must be in [0, 1]")
        if min(self.slack_weight, self.reuse_weight, self.recovery_weight) < 0:
            raise ValueError("policy weights must be non-negative")


SYSTEM_PROFILES: Final[dict[SystemId, SystemProfile]] = {
    SystemId.RECOMPUTE_ONLY: SystemProfile(
        SystemId.RECOMPUTE_ONLY,
        "Recompute only",
        Fraction(0),
        Fraction(0),
        False,
        False,
        EvictionKind.FIFO,
        0,
        0,
        0,
        False,
        False,
    ),
    SystemId.VANILLA_MOONCAKE_DRAM: SystemProfile(
        SystemId.VANILLA_MOONCAKE_DRAM,
        "Vanilla Mooncake DRAM",
        Fraction(0),
        Fraction(3, 4),
        False,
        True,
        EvictionKind.LRU,
        0,
        1,
        1,
        False,
        False,
    ),
    SystemId.STATIC_PEER_HBM: SystemProfile(
        SystemId.STATIC_PEER_HBM,
        "Static Peer-HBM",
        Fraction(1, 2),
        Fraction(0),
        True,
        False,
        EvictionKind.FIFO,
        0,
        0,
        1,
        False,
        False,
    ),
    SystemId.AEGIS_DRAM_ONLY: SystemProfile(
        SystemId.AEGIS_DRAM_ONLY,
        "AegisKV DRAM only",
        Fraction(0),
        Fraction(7, 8),
        False,
        True,
        EvictionKind.SLACK_LANDLORD_VALUE,
        2,
        2,
        3,
        True,
        False,
    ),
    SystemId.AEGIS_PEER_ONLY: SystemProfile(
        SystemId.AEGIS_PEER_ONLY,
        "AegisKV Peer-HBM only",
        Fraction(3, 4),
        Fraction(0),
        True,
        False,
        EvictionKind.SLACK_LANDLORD_VALUE,
        2,
        2,
        3,
        True,
        True,
    ),
    SystemId.AEGIS_HBM_DRAM: SystemProfile(
        SystemId.AEGIS_HBM_DRAM,
        "AegisKV HBM+DRAM",
        Fraction(2, 3),
        Fraction(2, 3),
        True,
        True,
        EvictionKind.SLACK_LANDLORD_VALUE,
        2,
        2,
        3,
        False,
        True,
    ),
    SystemId.AEGIS_UNIFIED: SystemProfile(
        SystemId.AEGIS_UNIFIED,
        "Full AegisKV unified manager",
        Fraction(3, 4),
        Fraction(9, 10),
        True,
        True,
        EvictionKind.SLACK_LANDLORD_VALUE,
        3,
        3,
        4,
        True,
        True,
    ),
}


@dataclass(frozen=True, slots=True)
class ModelParameters:
    dp_count: int = 4
    peer_budget_bytes_per_gpu: int = 8 * GIB
    store_budget_bytes: int = 64 * GIB
    peer_bandwidth_bytes_per_second: int = 100_000_000_000
    store_bandwidth_bytes_per_second: int = 25_000_000_000
    transfer_setup_ns: int = 250_000
    failure_detection_ns: int = 5_000_000
    reroute_ns: int = 1_000_000
    policy_chunk_tokens: int = 1_024
    failure_progress_per_mille: int = 100

    def __post_init__(self) -> None:
        positive = (
            self.dp_count,
            self.peer_budget_bytes_per_gpu,
            self.store_budget_bytes,
            self.peer_bandwidth_bytes_per_second,
            self.store_bandwidth_bytes_per_second,
            self.transfer_setup_ns,
            self.failure_detection_ns,
            self.policy_chunk_tokens,
        )
        if any(type(item) is not int or item <= 0 for item in positive):
            raise ValueError("modeled parameters must be positive integers")
        if self.reroute_ns < 0:
            raise ValueError("reroute_ns must be non-negative")
        if self.policy_chunk_tokens % SOURCE_BLOCK_TOKENS:
            raise ValueError("policy chunks must align to 64-token source blocks")
        if not 1 <= self.failure_progress_per_mille <= 999:
            raise ValueError("failure progress must be strictly within a request")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dp_count": self.dp_count,
            "peer_budget_bytes_per_gpu": self.peer_budget_bytes_per_gpu,
            "store_budget_bytes": self.store_budget_bytes,
            "peer_bandwidth_bytes_per_second": self.peer_bandwidth_bytes_per_second,
            "store_bandwidth_bytes_per_second": self.store_bandwidth_bytes_per_second,
            "transfer_setup_ns": self.transfer_setup_ns,
            "failure_detection_ns": self.failure_detection_ns,
            "reroute_ns": self.reroute_ns,
            "policy_chunk_tokens": self.policy_chunk_tokens,
            "failure_progress_per_mille": self.failure_progress_per_mille,
            "provenance": {
                "kv_bytes_per_64_tokens": {
                    "value": KV_BYTES_PER_SOURCE_BLOCK,
                    "source": "source_derived_qwen3_8b_tp1_pp1_kv_layout",
                },
                "peer_hbm_aimd": {
                    "parameters": AIMD_PARAMETERS.to_dict(),
                    "source": "patent_formula_with_explicit_modeled_e2_parameters",
                },
                "all_time_and_rate_parameters": "modeled_assumed_not_calibrated",
            },
        }


DEFAULT_PARAMETERS: Final = ModelParameters()


@dataclass(frozen=True, slots=True)
class ExperimentVariant:
    suite: str
    variant_id: str
    profile: SystemProfile
    parameters: ModelParameters = ModelParameters()
    negative_control: bool = False
    interpretation: str = "machine_interpretation_pending_manual_review"

    def __post_init__(self) -> None:
        if not self.suite or not self.variant_id:
            raise ValueError("suite and variant_id must be non-empty")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        profile = self.profile
        return {
            "suite": self.suite,
            "variant_id": self.variant_id,
            "system_id": profile.system_id.value,
            "label": profile.label,
            "peer_fraction": _fraction_dict(profile.peer_fraction),
            "store_fraction": _fraction_dict(profile.store_fraction),
            "peer_cache_reuse": profile.peer_cache_reuse,
            "store_cache_reuse": profile.store_cache_reuse,
            "eviction": profile.eviction.value,
            "slack_weight": profile.slack_weight,
            "reuse_weight": profile.reuse_weight,
            "recovery_weight": profile.recovery_weight,
            "unified_manager": profile.unified_manager,
            "aimd_enabled": profile.aimd_enabled,
            "anti_colocation": profile.anti_colocation,
            "cache_aware_routing": profile.cache_aware_routing,
            "parameters": self.parameters.to_dict(),
            "negative_control": self.negative_control,
            "interpretation": self.interpretation,
        }


@dataclass(frozen=True, slots=True)
class FailureSchedule:
    failure_id: str
    bucket: str
    seed: int
    focus_span_id: str
    target_gpu_id: str
    reference_at_ns: int
    detection_delay_ns: int
    trigger_progress_per_mille: int
    selection_scope: str = "same_focus_span_and_compute_progress_in_every_system"

    def __post_init__(self) -> None:
        if not self.failure_id or not self.focus_span_id or not self.target_gpu_id:
            raise ValueError("failure schedule identifiers must be non-empty")
        if self.bucket not in {item.name for item in CONTEXT_BUCKETS}:
            raise ValueError("failure schedule has an unknown context bucket")
        if self.seed < 0 or self.reference_at_ns < 0 or self.detection_delay_ns <= 0:
            raise ValueError("failure schedule timestamps and seed are invalid")
        if not 1 <= self.trigger_progress_per_mille <= 999:
            raise ValueError("logical failure progress must be strictly inside a request")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "type": "GPU_FAILURE",
            "bucket": self.bucket,
            "seed": self.seed,
            "focus_span_id": self.focus_span_id,
            "target_gpu_id": self.target_gpu_id,
            "trigger": {
                "kind": "FOCUS_SPAN_COMPUTE_PROGRESS",
                "progress_per_mille": self.trigger_progress_per_mille,
            },
            "reference_at_ns": self.reference_at_ns,
            "reference_at_ns_semantics": "recompute_only_oracle_provenance_not_cell_time",
            "detection_delay_ns": self.detection_delay_ns,
            "selection_scope": self.selection_scope,
            "repair_after_ns": None,
            "parameter_source": "deterministic_focus_span_progress_global_des",
        }


@dataclass(frozen=True, slots=True)
class CellSpec:
    variant: ExperimentVariant
    context_bucket: str
    scenario: Scenario
    seed: int
    repetition: str
    failure_schedule: FailureSchedule | None = None

    def __post_init__(self) -> None:
        if self.context_bucket not in {item.name for item in CONTEXT_BUCKETS}:
            raise ValueError("unknown context bucket")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.repetition not in {"A", "B"}:
            raise ValueError("repetition must be A or B")
        if (self.scenario is Scenario.GPU_FAILURE) != (self.failure_schedule is not None):
            raise ValueError("failure cells require exactly one frozen failure schedule")

    @property
    def pair_id(self) -> str:
        return (
            f"{self.variant.suite}:{self.variant.variant_id}:{self.context_bucket}:"
            f"{self.scenario.value}:seed-{self.seed}"
        )

    @property
    def run_id(self) -> str:
        return f"{self.pair_id}:repeat-{self.repetition}"


@dataclass(frozen=True, slots=True)
class _Chunk:
    key: str
    workflow_id: str
    token_start: int
    token_count: int
    bytes: int


@dataclass(slots=True)
class _PoolEntry:
    chunk: _Chunk
    base_score: Fraction
    inserted_sequence: int
    last_access_ns: int
    hit_count: int = 0
    version: int = 0


@dataclass(frozen=True, slots=True)
class _PoolReservation:
    reservation_id: str
    chunks: tuple[_Chunk, ...]
    scores: tuple[Fraction, ...]
    bytes: int


class _ModeledPool:
    """Capacity-exact policy-chunk cache with lazy heap refresh."""

    def __init__(
        self,
        *,
        pool_id: str,
        capacity_bytes: int,
        physical_capacity_bytes: int | None = None,
        eviction: EvictionKind,
        seed: int,
    ) -> None:
        if capacity_bytes < 0:
            raise ValueError("pool capacity must be non-negative")
        maximum = capacity_bytes if physical_capacity_bytes is None else physical_capacity_bytes
        if maximum < capacity_bytes:
            raise ValueError("pool quota cannot exceed physical capacity")
        self.pool_id = pool_id
        self.capacity_bytes = capacity_bytes
        self.physical_capacity_bytes = maximum
        self.eviction = eviction
        self.seed = seed
        self.entries: dict[str, _PoolEntry] = {}
        self.pending: dict[str, _PoolReservation] = {}
        self._pending_keys: dict[str, str] = {}
        self._heap: list[tuple[Fraction, int, str, int]] = []
        self._next_sequence = 0
        self.occupied_bytes = 0
        self.pending_bytes = 0
        self.peak_bytes = 0
        self.pending_peak_bytes = 0
        self.byte_ns = 0
        self.last_change_ns = 0
        self.evicted_chunks = 0
        self.bypassed_chunks = 0
        self.alias_hits = 0
        self.unavailable_bytes = 0
        self.lost_committed_bytes = 0
        self.failed = False
        self.rent = Fraction(0, 1)
        self.timeline: list[dict[str, int | str]] = [
            {
                "timestamp_ns": 0,
                "occupied_bytes": 0,
                "committed_bytes": 0,
                "pending_bytes": 0,
                "capacity_bytes": capacity_bytes,
                "unavailable_bytes": 0,
                "cause": "INITIAL",
            }
        ]

    def _advance(self, now_ns: int) -> None:
        if now_ns < self.last_change_ns:
            raise ExperimentError("pool occupancy time moved backwards")
        self.byte_ns += (self.occupied_bytes + self.pending_bytes) * (
            now_ns - self.last_change_ns
        )
        self.last_change_ns = now_ns

    def _priority(self, entry: _PoolEntry) -> Fraction:
        if self.eviction is EvictionKind.FIFO:
            return Fraction(entry.inserted_sequence, 1)
        if self.eviction is EvictionKind.LRU:
            return Fraction(entry.last_access_ns, 1)
        if self.eviction is EvictionKind.LFU:
            return Fraction(entry.hit_count, 1)
        if self.eviction is EvictionKind.RANDOM_STABLE:
            digest = hashlib.sha256(f"{self.seed}:{entry.chunk.key}".encode()).digest()
            return Fraction(int.from_bytes(digest[:8], "big"), 1)
        return entry.base_score

    def _push(self, entry: _PoolEntry) -> None:
        entry.version += 1
        heapq.heappush(
            self._heap,
            (self._priority(entry), entry.inserted_sequence, entry.chunk.key, entry.version),
        )

    def _minimum(self) -> _PoolEntry | None:
        while self._heap:
            _priority, _sequence, key, version = self._heap[0]
            entry = self.entries.get(key)
            if entry is None or entry.version != version:
                heapq.heappop(self._heap)
                continue
            return entry
        return None

    def contains(self, key: str, *, now_ns: int) -> bool:
        if self.failed:
            return False
        entry = self.entries.get(key)
        if entry is None:
            return False
        entry.hit_count += 1
        entry.last_access_ns = now_ns
        if self.eviction in {EvictionKind.LRU, EvictionKind.LFU}:
            self._push(entry)
        return True

    def lookup_prefix_tokens(self, chunks: Sequence[_Chunk], *, now_ns: int) -> int:
        tokens = 0
        for chunk in chunks:
            if not self.contains(chunk.key, now_ns=now_ns):
                break
            tokens += chunk.token_count
        return tokens

    def peek_prefix_tokens(self, chunks: Sequence[_Chunk]) -> int:
        """Inspect a continuous prefix without mutating reuse signals."""

        tokens = 0
        for chunk in chunks:
            if chunk.key not in self.entries:
                break
            tokens += chunk.token_count
        return tokens

    def set_capacity(self, capacity_bytes: int, *, now_ns: int, cause: str) -> None:
        """Apply an AIMD quota and reclaim complete low-value chunks atomically."""

        if self.failed:
            raise ExperimentError("failed pool cannot accept a quota update")
        if not 0 <= capacity_bytes <= self.physical_capacity_bytes:
            raise ExperimentError("pool quota is outside physical capacity")
        self._advance(now_ns)
        self.capacity_bytes = capacity_bytes
        evicted = 0
        while self.occupied_bytes + self.pending_bytes > capacity_bytes:
            victim = self._minimum()
            if victim is None:
                raise ExperimentError("pool quota reclaim lost a resident entry")
            del self.entries[victim.chunk.key]
            self.occupied_bytes -= victim.chunk.bytes
            self.evicted_chunks += 1
            self.rent = max(self.rent, victim.base_score)
            heapq.heappop(self._heap)
            evicted += 1
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": cause if evicted == 0 else f"{cause}:RECLAIM",
            }
        )

    def insert(
        self,
        chunk: _Chunk,
        *,
        score: Fraction,
        now_ns: int,
        cause: str,
    ) -> bool:
        if self.failed:
            raise ExperimentError("failed pool cannot accept a committed chunk")
        existing = self.entries.get(chunk.key)
        if existing is not None:
            self.alias_hits += 1
            existing.last_access_ns = now_ns
            existing.base_score = max(existing.base_score, score)
            self._push(existing)
            return True
        if chunk.bytes > self.capacity_bytes:
            self.bypassed_chunks += 1
            return False
        required = max(0, self.occupied_bytes + chunk.bytes - self.capacity_bytes)
        selected: list[_PoolEntry] = []
        if required:
            candidates = sorted(
                self.entries.values(),
                key=lambda item: (
                    self._priority(item),
                    item.inserted_sequence,
                    item.chunk.key,
                ),
            )
            released = 0
            for victim in candidates:
                if (
                    self.eviction is EvictionKind.SLACK_LANDLORD_VALUE
                    and score <= victim.base_score
                ):
                    self.bypassed_chunks += 1
                    return False
                selected.append(victim)
                released += victim.chunk.bytes
                if released >= required:
                    break
            if released < required:
                raise ExperimentError("pool victim plan cannot establish required capacity")

        self._advance(now_ns)
        for victim in selected:
            del self.entries[victim.chunk.key]
            self.occupied_bytes -= victim.chunk.bytes
            self.evicted_chunks += 1
            self.rent = max(self.rent, victim.base_score)
        entry = _PoolEntry(
            chunk=chunk,
            base_score=score,
            inserted_sequence=self._next_sequence,
            last_access_ns=now_ns,
        )
        self._next_sequence += 1
        self.entries[chunk.key] = entry
        self.occupied_bytes += chunk.bytes
        self.peak_bytes = max(
            self.peak_bytes,
            self.occupied_bytes + self.pending_bytes,
        )
        self._push(entry)
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": cause,
            }
        )
        if self.occupied_bytes + self.pending_bytes > self.capacity_bytes:
            raise ExperimentError("pool exceeded physical capacity")
        return True

    def reserve(
        self,
        reservation_id: str,
        chunks: Sequence[_Chunk],
        scores: Sequence[Fraction],
        *,
        now_ns: int,
        cause: str,
    ) -> _PoolReservation | None:
        """Reserve destination bytes before submitting a protection transfer."""

        if self.failed:
            raise ExperimentError("failed pool cannot reserve a destination")
        if not reservation_id or reservation_id in self.pending:
            raise ExperimentError("pool reservation ID is empty or duplicated")
        if len(chunks) != len(scores):
            raise ExperimentError("pool reservation chunks and scores diverged")
        self._advance(now_ns)
        admitted_chunks: list[_Chunk] = []
        admitted_scores: list[Fraction] = []
        evicted = 0
        for chunk, score in zip(chunks, scores, strict=True):
            existing = self.entries.get(chunk.key)
            if existing is not None:
                self.alias_hits += 1
                existing.last_access_ns = now_ns
                existing.base_score = max(existing.base_score, score)
                self._push(existing)
                continue
            if chunk.key in self._pending_keys:
                self.bypassed_chunks += 1
                continue
            if chunk.bytes > self.capacity_bytes:
                self.bypassed_chunks += 1
                continue
            required = max(
                0,
                self.occupied_bytes
                + self.pending_bytes
                + chunk.bytes
                - self.capacity_bytes,
            )
            selected: list[_PoolEntry] = []
            if required:
                released = 0
                candidates = sorted(
                    self.entries.values(),
                    key=lambda item: (
                        self._priority(item),
                        item.inserted_sequence,
                        item.chunk.key,
                    ),
                )
                for victim in candidates:
                    if (
                        self.eviction is EvictionKind.SLACK_LANDLORD_VALUE
                        and score <= victim.base_score
                    ):
                        break
                    selected.append(victim)
                    released += victim.chunk.bytes
                    if released >= required:
                        break
                if released < required:
                    self.bypassed_chunks += 1
                    continue
            for victim in selected:
                del self.entries[victim.chunk.key]
                self.occupied_bytes -= victim.chunk.bytes
                self.evicted_chunks += 1
                self.rent = max(self.rent, victim.base_score)
                evicted += 1
            admitted_chunks.append(chunk)
            admitted_scores.append(score)
            self.pending_bytes += chunk.bytes
            self._pending_keys[chunk.key] = reservation_id
        if not admitted_chunks:
            return None
        reservation = _PoolReservation(
            reservation_id=reservation_id,
            chunks=tuple(admitted_chunks),
            scores=tuple(admitted_scores),
            bytes=sum(item.bytes for item in admitted_chunks),
        )
        self.pending[reservation_id] = reservation
        self.pending_peak_bytes = max(self.pending_peak_bytes, self.pending_bytes)
        self.peak_bytes = max(
            self.peak_bytes,
            self.occupied_bytes + self.pending_bytes,
        )
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": f"{cause}:DESTINATION_RESERVED"
                + (":EVICTED" if evicted else ""),
            }
        )
        if self.occupied_bytes + self.pending_bytes > self.capacity_bytes:
            raise ExperimentError("destination reserve exceeded pool capacity")
        return reservation

    def commit_reservation(
        self, reservation_id: str, *, now_ns: int, cause: str
    ) -> _PoolReservation:
        try:
            reservation = self.pending.pop(reservation_id)
        except KeyError as error:
            raise ExperimentError("unknown pool reservation commit") from error
        self._advance(now_ns)
        for chunk, score in zip(
            reservation.chunks,
            reservation.scores,
            strict=True,
        ):
            if self._pending_keys.pop(chunk.key, None) != reservation_id:
                raise ExperimentError("pool pending key diverged at commit")
            entry = _PoolEntry(
                chunk=chunk,
                base_score=score,
                inserted_sequence=self._next_sequence,
                last_access_ns=now_ns,
            )
            self._next_sequence += 1
            self.entries[chunk.key] = entry
            self._push(entry)
        self.pending_bytes -= reservation.bytes
        self.occupied_bytes += reservation.bytes
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": f"{cause}:PENDING_TO_COMMITTED",
            }
        )
        return reservation

    def abort_reservation(
        self, reservation_id: str, *, now_ns: int, cause: str
    ) -> _PoolReservation:
        try:
            reservation = self.pending.pop(reservation_id)
        except KeyError as error:
            raise ExperimentError("unknown pool reservation abort") from error
        self._advance(now_ns)
        for chunk in reservation.chunks:
            if self._pending_keys.pop(chunk.key, None) != reservation_id:
                raise ExperimentError("pool pending key diverged at abort")
        self.pending_bytes -= reservation.bytes
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": f"{cause}:DESTINATION_RELEASED",
            }
        )
        return reservation

    def fail(self, *, now_ns: int, cause: str) -> int:
        """Atomically make this physical pool unavailable and invalidate data."""

        if self.failed:
            raise ExperimentError("pool failure cannot be applied twice")
        if self.pending or self.pending_bytes:
            raise ExperimentError("pool failure requires pending destinations to abort first")
        self._advance(now_ns)
        lost_bytes = self.occupied_bytes
        self.entries.clear()
        self._heap.clear()
        self.occupied_bytes = 0
        self.capacity_bytes = 0
        self.unavailable_bytes = self.physical_capacity_bytes
        self.lost_committed_bytes += lost_bytes
        self.failed = True
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": 0,
                "committed_bytes": 0,
                "pending_bytes": 0,
                "capacity_bytes": 0,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": cause,
            }
        )
        return lost_bytes

    def finalize(self, end_ns: int) -> None:
        self._advance(end_ns)


class _ExecutionStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FENCED = "FENCED"
    RECOVERING = "RECOVERING"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"


@dataclass(slots=True)
class _SpanExecution:
    metadata: NormalizedSpanMetadata
    record: Mapping[str, Any]
    chunks: tuple[_Chunk, ...]
    status: _ExecutionStatus = _ExecutionStatus.PENDING
    route_version: int = 0
    gpu_id: str | None = None
    released_ns: int | None = None
    compute_start_ns: int | None = None
    planned_complete_ns: int | None = None
    completed_ns: int | None = None
    completion_handle: EventHandle | None = None
    reservation_id: str | None = None
    base_duration_ns: int = 0
    scheduled_duration_ns: int = 0
    reused_peer_tokens: int = 0
    reused_store_tokens: int = 0
    restored_peer_tokens: int = 0
    restored_store_tokens: int = 0
    recompute_tokens: int = 0
    committed_output_tokens_at_failure: int = 0
    external_output_emissions: int = 0
    failure_at_ns: int | None = None
    recovery_ready_ns: int | None = None
    prompt_recompute_start_ns: int | None = None
    prompt_recompute_complete_ns: int | None = None
    silent_replay_start_ns: int | None = None
    silent_replay_complete_ns: int | None = None
    resume_decode_start_ns: int | None = None


@dataclass(slots=True)
class _PendingPutStart:
    plan_id: str
    span_id: str
    path: str
    source_gpu_id: str
    target_gpu_id: str | None
    chunks: tuple[_Chunk, ...]
    scores: tuple[Fraction, ...]
    handle: EventHandle
    produced_ns: int


@dataclass(slots=True)
class _PendingPut:
    transfer_id: str
    path: str
    source_gpu_id: str
    target_gpu_id: str | None
    chunks: tuple[_Chunk, ...]
    scores: tuple[Fraction, ...]
    handle: EventHandle
    reservation_ids: tuple[tuple[str, str], ...]
    pool_reservation_id: str
    bytes: int


@dataclass(frozen=True, slots=True)
class StudyRunResult:
    payload: dict[str, Any]
    journal_sha256: str
    span_details: tuple[dict[str, Any], ...]
    representative: dict[str, Any]

    @property
    def payload_sha256(self) -> str:
        return sha256_json(self.payload)


class _StudyRuntime:
    def __init__(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        variant: ExperimentVariant,
        context_bucket: str,
        seed: int,
        failure_schedule: FailureSchedule | None,
    ) -> None:
        self.records = tuple(records)
        self.variant = variant
        self.context_bucket = context_bucket
        self.profile = variant.profile
        self.parameters = variant.parameters
        self.seed = seed
        self.failure_schedule = failure_schedule
        self.des = GlobalDES()
        self.trace = load_normalized_trace_records(records)
        by_span = {span.span_id: span for span in self.trace.spans}
        records_by_span = {str(record["span_id"]): record for record in records}
        self.executions = {
            span_id: _SpanExecution(
                metadata=metadata,
                record=records_by_span[span_id],
                chunks=_chunks_for_record(records_by_span[span_id], self.parameters),
            )
            for span_id, metadata in by_span.items()
        }
        self.gpu_ids = tuple(f"gpu-{index}" for index in range(self.parameters.dp_count))
        self.failed_gpu_ids: set[str] = set()
        self.compute = {
            gpu_id: ConcurrencyResource(resource_id=f"{gpu_id}.compute", lanes=1)
            for gpu_id in self.gpu_ids
        }
        self.copy = {
            gpu_id: ConcurrencyResource(resource_id=f"{gpu_id}.copy", lanes=1)
            for gpu_id in self.gpu_ids
        }
        self.peer_fabric = ConcurrencyResource(resource_id="peer-fabric", lanes=2)
        self.store_fabric = ConcurrencyResource(resource_id="store-fabric", lanes=1)
        initial_peer_quota = _fraction_count(
            self.parameters.peer_budget_bytes_per_gpu,
            self.profile.peer_fraction,
        )
        self.peer_pools = {
            gpu_id: _ModeledPool(
                pool_id=f"PEER_HBM:{gpu_id}",
                capacity_bytes=initial_peer_quota,
                physical_capacity_bytes=self.parameters.peer_budget_bytes_per_gpu,
                eviction=self.profile.eviction,
                seed=seed,
            )
            for gpu_id in self.gpu_ids
        }
        self.store_pool = _ModeledPool(
            pool_id="STORE_DRAM:store-0:segment-0",
            capacity_bytes=self.parameters.store_budget_bytes,
            eviction=self.profile.eviction,
            seed=seed,
        )
        self.aimd = HBMQuotaAIMD(AIMD_PARAMETERS)
        initial_fraction = _fraction_to_decimal(self.profile.peer_fraction)
        self.aimd_states = {
            gpu_id: AIMDTargetState(
                target_id=gpu_id,
                peer_hbm_capacity_bytes=self.parameters.peer_budget_bytes_per_gpu,
                protection_fraction=initial_fraction,
            )
            for gpu_id in self.gpu_ids
            if self.profile.peer_fraction > 0
        }
        self.aimd_events: list[dict[str, Any]] = []
        self.route_events: list[dict[str, Any]] = []
        self.cache_aware_route_evaluations = 0
        self.cache_aware_route_changes = 0
        self.protection_path_bypasses: Counter[str] = Counter()
        self.causal = CausalReleaseEngine(self.trace, self.des, on_release=self._on_release)
        self.pending_put_starts: dict[str, _PendingPutStart] = {}
        self.pending_puts: dict[str, _PendingPut] = {}
        self.transfers: list[dict[str, Any]] = []
        self._transfer_by_id: dict[str, dict[str, Any]] = {}
        self.failure_events: list[dict[str, Any]] = []
        self.recovery_events: list[dict[str, Any]] = []
        self._failure_event_scheduled = False
        self._failure_event_executed = False
        self._event_sequence = 0
        self._completed_span_ids: set[str] = set()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.des.register_handler(EventKind.REQUEST_COMPLETE, self._on_request_complete)
        self.des.register_handler(EventKind.PUT_START, self._on_put_start)
        self.des.register_handler(EventKind.PUT_COMMIT, self._on_put_commit)
        self.des.register_handler(EventKind.FAILURE_INJECT, self._on_failure_inject)
        self.des.register_handler(EventKind.FAILURE_DETECT, self._on_failure_detect)
        self.des.register_handler(EventKind.RECOVERY_COMPLETE, self._on_recovery_complete)
        self.des.register_handler(
            EventKind.RECOVERY_RECOMPUTE_COMPLETE,
            self._on_recovery_recompute_complete,
        )
        self.des.register_handler(
            EventKind.SILENT_REPLAY_COMPLETE, self._on_silent_replay_complete
        )
        self.des.register_invariant("aegiskv-study-invariants", self._check_invariants)

    def run(self) -> StudyRunResult:
        if self.failure_schedule is not None:
            schedule = self.failure_schedule
            if schedule.focus_span_id not in self.executions:
                raise ExperimentError("failure focus span is absent from the frozen workload")
            if schedule.target_gpu_id not in self.gpu_ids:
                raise ExperimentError("failure target is absent from the modeled deployment")
        self.causal.start()
        self.des.run()
        if self.failure_schedule is not None and not (
            self._failure_event_scheduled and self._failure_event_executed
        ):
            raise ExperimentError("logical failure trigger was not scheduled and executed")
        if len(self._completed_span_ids) != len(self.executions):
            missing = sorted(set(self.executions) - self._completed_span_ids)
            raise ExperimentError(f"study left spans incomplete: {missing[:5]}")
        if self.pending_put_starts or self.pending_puts or any(
            record.get("status") == "PENDING" for record in self.transfers
        ):
            raise ExperimentError("study ended with a non-terminal transfer")
        if any(
            pool.pending or pool.pending_bytes
            for pool in (*self.peer_pools.values(), self.store_pool)
        ):
            raise ExperimentError("study ended with a pending destination reservation")
        end_ns = self.des.now_ns
        for pool in self.peer_pools.values():
            pool.finalize(end_ns)
        self.store_pool.finalize(end_ns)
        payload = self._payload(end_ns)
        representative = {
            "failure_events": self.failure_events,
            "recovery_events": self.recovery_events,
            "transfers": self.transfers,
            "peer_hbm_timeline": _aggregate_pool_timeline(self.peer_pools),
            "peer_hbm_timelines": {
                gpu_id: pool.timeline for gpu_id, pool in sorted(self.peer_pools.items())
            },
            "store_dram_timeline": self.store_pool.timeline,
            "store_dram_timelines": {
                "store-0:segment-0": self.store_pool.timeline,
            },
            "aimd_events": self.aimd_events,
            "route_events": self.route_events,
        }
        details = tuple(
            self._span_detail(execution)
            for execution in sorted(
                self.executions.values(), key=lambda item: item.metadata.stable_sort_key
            )
        )
        return StudyRunResult(
            payload=payload,
            journal_sha256=hashlib.sha256(self.des.journal.to_jsonl_bytes()).hexdigest(),
            span_details=details,
            representative=representative,
        )

    def _check_invariants(self, _des: GlobalDES) -> None:
        for gpu_id, pool in self.peer_pools.items():
            if pool.occupied_bytes + pool.pending_bytes > pool.capacity_bytes:
                raise ExperimentError(f"Peer-HBM capacity invariant failed on {gpu_id}")
            if pool.capacity_bytes > pool.physical_capacity_bytes:
                raise ExperimentError(f"Peer-HBM quota exceeded physical HBM on {gpu_id}")
            if pool.failed:
                if (
                    pool.occupied_bytes != 0
                    or pool.pending_bytes != 0
                    or pool.capacity_bytes != 0
                    or pool.unavailable_bytes != pool.physical_capacity_bytes
                ):
                    raise ExperimentError(f"failed Peer-HBM ledger is inconsistent on {gpu_id}")
            elif pool.unavailable_bytes != 0:
                raise ExperimentError(f"healthy Peer-HBM has unavailable bytes on {gpu_id}")
        if (
            self.store_pool.occupied_bytes + self.store_pool.pending_bytes
            > self.store_pool.capacity_bytes
        ):
            raise ExperimentError("Store DRAM capacity invariant failed")
        for pool in (*self.peer_pools.values(), self.store_pool):
            if sum(item.bytes for item in pool.pending.values()) != pool.pending_bytes:
                raise ExperimentError("pool pending reservation bytes diverged")
            if set(pool._pending_keys.values()) - set(pool.pending):
                raise ExperimentError("pool pending key references an unknown reservation")
        if len(self.transfers) != len(self._transfer_by_id):
            raise ExperimentError("transfer ledger index diverged from its journal view")
        for record in self.transfers:
            submitted = record.get("bytes")
            transferred = record.get("transferred_bytes")
            aborted = record.get("aborted_bytes")
            status = record.get("status")
            if not all(
                type(value) is int and value >= 0
                for value in (submitted, transferred, aborted)
            ):
                raise ExperimentError("transfer ledger contains malformed byte counters")
            submitted_bytes = cast(int, submitted)
            transferred_bytes = cast(int, transferred)
            aborted_bytes = cast(int, aborted)
            if status == "PENDING":
                if transferred_bytes != 0 or aborted_bytes != 0:
                    raise ExperimentError("pending transfer owns terminal byte counters")
            elif status in {"COMMITTED", "ABORTED"}:
                if submitted_bytes != transferred_bytes + aborted_bytes:
                    raise ExperimentError("terminal transfer bytes do not conserve")
            else:
                raise ExperimentError("transfer ledger contains an unknown state")
        for execution in self.executions.values():
            if execution.external_output_emissions not in {0, execution.metadata.output_tokens}:
                raise ExperimentError("external output was duplicated or partially emitted")
            if (
                execution.gpu_id in self.failed_gpu_ids
                and execution.status is _ExecutionStatus.RUNNING
            ):
                raise ExperimentError("failed GPU retained a running request")
            if execution.recovery_ready_ns is not None:
                ordered = (
                    execution.failure_at_ns,
                    execution.prompt_recompute_start_ns,
                    execution.prompt_recompute_complete_ns,
                    execution.silent_replay_start_ns,
                    execution.silent_replay_complete_ns,
                    execution.recovery_ready_ns,
                    execution.resume_decode_start_ns,
                )
                if any(item is None for item in ordered):
                    raise ExperimentError("activated recovery is missing a causal phase")
                timestamps = tuple(int(item) for item in ordered if item is not None)
                if timestamps != tuple(sorted(timestamps)):
                    raise ExperimentError("recovery phases violated causal timestamp order")

    def _on_release(self, metadata: NormalizedSpanMetadata, _des: GlobalDES) -> None:
        execution = self.executions[metadata.span_id]
        execution.released_ns = self.des.now_ns
        execution.base_duration_ns = max(1, metadata.recorded_api_time_ns)
        gpu_id = self._route_gpu(metadata.span_id, route_version=0)
        peer_prefix = 0
        if self._reuse_visible("PEER_HBM"):
            # A Peer-HBM cache hit is local only after the request is routed to
            # that GPU.  Never model a zero-cost remote Peer lookup.
            peer_prefix = self.peer_pools[gpu_id].lookup_prefix_tokens(
                execution.chunks, now_ns=self.des.now_ns
            )
        store_prefix = (
            self.store_pool.lookup_prefix_tokens(execution.chunks, now_ns=self.des.now_ns)
            if self._reuse_visible("STORE_DRAM")
            else 0
        )
        if peer_prefix >= store_prefix:
            execution.reused_peer_tokens = peer_prefix
        else:
            execution.reused_store_tokens = store_prefix
        reused = max(peer_prefix, store_prefix)
        duration = _duration_after_prefix_reuse(metadata, execution.base_duration_ns, reused)
        self._schedule_compute(
            execution,
            gpu_id=gpu_id,
            ready_ns=self.des.now_ns,
            duration_ns=duration,
        )

    def _route_gpu(self, span_id: str, *, route_version: int) -> str:
        healthy = tuple(gpu for gpu in self.gpu_ids if gpu not in self.failed_gpu_ids)
        if not healthy:
            raise ExperimentError("no healthy modeled GPU remains")
        digest = hashlib.sha256(f"{self.seed}:{span_id}:{route_version}".encode()).digest()
        hashed = healthy[int.from_bytes(digest[:8], "big") % len(healthy)]
        selected = hashed
        cache_source = hashed
        if not self.profile.cache_aware_routing or not self._reuse_visible("PEER_HBM"):
            scores = {gpu_id: 0 for gpu_id in healthy}
        else:
            self.cache_aware_route_evaluations += 1
            chunks = self.executions[span_id].chunks
            scores = {
                gpu_id: self.peer_pools[gpu_id].peek_prefix_tokens(chunks)
                for gpu_id in healthy
            }
            best = max(scores.values(), default=0)
            candidates = tuple(gpu_id for gpu_id in healthy if scores[gpu_id] == best)
            cache_source = (
                hashed
                if hashed in candidates
                else candidates[int.from_bytes(digest[8:16], "big") % len(candidates)]
            )
            if cache_source != hashed:
                self.cache_aware_route_changes += 1
            selected = cache_source
        self.route_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "span_id": span_id,
                "route_version": route_version,
                "selected_gpu_id": selected,
                "hashed_gpu_id": hashed,
                "selected_peer_cache_source_gpu_id": cache_source,
                "cache_aware": self.profile.cache_aware_routing,
                "peer_prefix_tokens_by_gpu": dict(sorted(scores.items())),
            }
        )
        return selected

    def _reuse_visible(self, path: str) -> bool:
        enabled = (
            self.profile.peer_cache_reuse
            if path == "PEER_HBM"
            else self.profile.store_cache_reuse
        )
        # Unified and two-manager variants share the single physical directory;
        # the ablation changes value aggregation, not whether committed data
        # mysteriously becomes invisible to cache lookup.
        return enabled

    def _peer_target(self, *, source_gpu_id: str, span_id: str) -> str:
        healthy = tuple(gpu for gpu in self.gpu_ids if gpu not in self.failed_gpu_ids)
        if not self.profile.anti_colocation:
            if source_gpu_id not in healthy:
                raise ExperimentError("negative-control Peer target source is not healthy")
            return source_gpu_id
        candidates = tuple(gpu for gpu in healthy if gpu != source_gpu_id)
        if not candidates:
            raise ExperimentError("Peer-HBM protection requires a healthy anti-colocated GPU")
        digest = hashlib.sha256(f"peer-target:{self.seed}:{span_id}".encode()).digest()
        return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]

    def _update_peer_quota(self, *, target_gpu_id: str) -> None:
        if not self.profile.aimd_enabled:
            return
        state = self.aimd_states[target_gpu_id]
        if state.last_update_ns is not None and self.des.now_ns <= state.last_update_ns:
            return
        pool = self.peer_pools[target_gpu_id]
        decision = self.aimd.update(
            state,
            # Protection admission overflow is not foreground pressure.  This
            # harness has no modeled primary-HBM pressure signal, so it reports
            # a stable window and lets the pool's own admission/eviction decide.
            foreground_pressure=False,
            current_protection_bytes=pool.occupied_bytes + pool.pending_bytes,
            timestamp_ns=self.des.now_ns,
        )
        self.aimd_states[target_gpu_id] = decision.next_state
        pool.set_capacity(
            decision.quota_bytes,
            now_ns=self.des.now_ns,
            cause=f"AEGIS_AIMD_{decision.action.value}",
        )
        self.aimd_events.append(decision.to_dict())

    def _schedule_compute(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        ready_ns: int,
        duration_ns: int,
    ) -> None:
        reservation_id = self._next_id(
            f"compute:{execution.metadata.span_id}:r{execution.route_version}"
        )
        reservation = self.compute[gpu_id].reserve(
            ready_ns=ready_ns,
            duration_ns=max(1, duration_ns),
            reservation_id=reservation_id,
            cause="MODEL_FORWARD_OR_RECOVERY_REPLAY",
        )
        execution.gpu_id = gpu_id
        execution.compute_start_ns = reservation.start_ns
        execution.planned_complete_ns = reservation.end_ns
        execution.reservation_id = reservation.reservation_id
        execution.scheduled_duration_ns = duration_ns
        execution.status = (
            _ExecutionStatus.RUNNING
            if reservation.start_ns <= self.des.now_ns
            else _ExecutionStatus.QUEUED
        )
        handle = self.des.schedule_at(
            reservation.end_ns,
            EventKind.REQUEST_COMPLETE,
            event_id=self._next_id(f"complete:{execution.metadata.span_id}"),
            payload={
                "span_id": execution.metadata.span_id,
                "route_version": execution.route_version,
                "gpu_id": gpu_id,
            },
        )
        execution.completion_handle = handle
        self._schedule_logical_failure_trigger(
            execution,
            gpu_id=gpu_id,
            compute_start_ns=reservation.start_ns,
            compute_end_ns=reservation.end_ns,
        )
        self._schedule_protection_puts(
            execution,
            source_gpu_id=gpu_id,
            compute_start_ns=reservation.start_ns,
            compute_end_ns=reservation.end_ns,
        )

    def _schedule_logical_failure_trigger(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        compute_start_ns: int,
        compute_end_ns: int,
    ) -> None:
        """Resolve one frozen logical trigger onto this cell's virtual timeline."""

        schedule = self.failure_schedule
        if schedule is None or execution.metadata.span_id != schedule.focus_span_id:
            return
        if self._failure_event_scheduled:
            return
        if execution.route_version != 0:
            raise ExperimentError("failure focus span was rerouted before its initial trigger")
        if gpu_id != schedule.target_gpu_id:
            raise ExperimentError("failure focus span route diverged from the frozen target")
        duration_ns = compute_end_ns - compute_start_ns
        if duration_ns <= 0:
            raise ExperimentError("failure focus span has an empty compute interval")
        offset_ns = duration_ns * schedule.trigger_progress_per_mille // 1_000
        resolved_at_ns = min(
            compute_end_ns - 1,
            max(compute_start_ns, compute_start_ns + offset_ns),
        )
        payload = schedule.to_dict()
        payload.update(
            {
                "resolved_at_ns": resolved_at_ns,
                "resolved_compute_start_ns": compute_start_ns,
                "resolved_compute_end_ns": compute_end_ns,
            }
        )
        self.des.schedule_at(
            resolved_at_ns,
            EventKind.FAILURE_INJECT,
            event_id=f"failure:{schedule.failure_id}",
            payload=payload,
        )
        self._failure_event_scheduled = True

    def _on_request_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        route_version = _required_int(event.payload, "route_version")
        if route_version != execution.route_version:
            raise ExperimentError("stale route attempted output completion")
        if execution.status in {_ExecutionStatus.FENCED, _ExecutionStatus.COMPLETED}:
            raise ExperimentError("fenced or completed execution attempted output")
        if execution.gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed GPU attempted request completion")
        execution.status = _ExecutionStatus.COMPLETED
        execution.completed_ns = self.des.now_ns
        execution.external_output_emissions = execution.metadata.output_tokens
        self._completed_span_ids.add(span_id)
        self.causal.mark_completed(span_id)
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_EXTERNAL_OUTPUT_COMMITTED",
            {
                "span_id": span_id,
                "route_version": route_version,
                "output_tokens": execution.metadata.output_tokens,
                "emission_count": 1,
            },
        )
    def _schedule_protection_puts(
        self,
        execution: _SpanExecution,
        *,
        source_gpu_id: str,
        compute_start_ns: int,
        compute_end_ns: int,
    ) -> None:
        """Schedule source-owned protection as chunks seal on the global clock."""

        if not execution.chunks:
            return
        paths = (
            ("PEER_HBM", self.profile.peer_fraction),
            ("STORE_DRAM", self.profile.store_fraction),
        )
        for path, fraction in paths:
            candidate_count = _fraction_count(len(execution.chunks), fraction)
            if candidate_count == 0:
                continue
            if path == "PEER_HBM" and self.profile.anti_colocation:
                healthy_peer_targets = tuple(
                    gpu_id
                    for gpu_id in self.gpu_ids
                    if gpu_id not in self.failed_gpu_ids and gpu_id != source_gpu_id
                )
                if not healthy_peer_targets:
                    self.protection_path_bypasses["PEER_HBM_NO_HEALTHY_TARGET"] += 1
                    self.des.journal.append(
                        self.des.now_ns,
                        "AEGIS_PROTECTION_PATH_BYPASSED",
                        {
                            "path": path,
                            "span_id": execution.metadata.span_id,
                            "source_gpu_id": source_gpu_id,
                            "reason": "NO_HEALTHY_ANTI_COLOCATED_TARGET",
                            "independent_path": True,
                            "store_path_affected": False,
                        },
                    )
                    continue
            target_gpu_id = (
                self._peer_target(
                    source_gpu_id=source_gpu_id,
                    span_id=execution.metadata.span_id,
                )
                if path == "PEER_HBM"
                else None
            )
            modeled_pool = (
                self.peer_pools[target_gpu_id]
                if target_gpu_id is not None
                else self.store_pool
            )
            batch_count = min(4, candidate_count)
            for batch_index in range(batch_count):
                begin = candidate_count * batch_index // batch_count
                end = candidate_count * (batch_index + 1) // batch_count
                chunks = execution.chunks[begin:end]
                if not chunks:
                    continue
                scores = tuple(
                    self._chunk_score(
                        execution,
                        chunk,
                        path=path,
                        modeled_pool=modeled_pool,
                    )
                    for chunk in chunks
                )
                produced_ns = compute_start_ns + (
                    (compute_end_ns - compute_start_ns) * end // len(execution.chunks)
                )
                plan_id = self._next_id(
                    f"put-start:{path}:{execution.metadata.span_id}:batch-{batch_index}"
                )
                handle = self.des.schedule_at(
                    produced_ns,
                    EventKind.PUT_START,
                    event_id=f"start:{plan_id}",
                    payload={"plan_id": plan_id, "path": path},
                )
                self.pending_put_starts[plan_id] = _PendingPutStart(
                    plan_id=plan_id,
                    span_id=execution.metadata.span_id,
                    path=path,
                    source_gpu_id=source_gpu_id,
                    target_gpu_id=target_gpu_id,
                    chunks=chunks,
                    scores=scores,
                    handle=handle,
                    produced_ns=produced_ns,
                )

    def _on_put_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        plan_id = _required_str(event.payload, "plan_id")
        plan = self.pending_put_starts.pop(plan_id, None)
        if plan is None:
            raise ExperimentError("unknown or canceled protection start executed")
        if plan.produced_ns != self.des.now_ns:
            raise ExperimentError("protection start diverged from chunk seal time")
        if plan.source_gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed source attempted to start protection")
        if plan.path == "PEER_HBM":
            if plan.target_gpu_id is None:
                raise ExperimentError("Peer-HBM start lost its physical target")
            if plan.target_gpu_id in self.failed_gpu_ids:
                raise ExperimentError("failed Peer-HBM target attempted transfer start")
        transfer_id = self._next_id(f"put:{plan.path}:{plan.plan_id}")
        if plan.path == "PEER_HBM":
            if plan.target_gpu_id is None:
                raise ExperimentError("Peer-HBM destination disappeared before reserve")
            self._update_peer_quota(target_gpu_id=plan.target_gpu_id)
            pool = self.peer_pools[plan.target_gpu_id]
        else:
            pool = self.store_pool
        pool_reservation = pool.reserve(
            transfer_id,
            plan.chunks,
            plan.scores,
            now_ns=self.des.now_ns,
            cause=f"AEGIS_{plan.path}_PROTECTION",
        )
        if pool_reservation is None:
            self.protection_path_bypasses[f"{plan.path}_POOL_ADMISSION"] += 1
            self.des.journal.append(
                self.des.now_ns,
                "AEGIS_PROTECTION_PATH_BYPASSED",
                {
                    "path": plan.path,
                    "span_id": plan.span_id,
                    "source_gpu_id": plan.source_gpu_id,
                    "reason": "POOL_ADMISSION_REJECTED_OR_ALIAS",
                    "independent_path": True,
                },
            )
            return
        transfer_bytes = pool_reservation.bytes
        bandwidth = (
            self.parameters.peer_bandwidth_bytes_per_second
            if plan.path == "PEER_HBM"
            else self.parameters.store_bandwidth_bytes_per_second
        )
        duration_ns = _transfer_duration_ns(
            transfer_bytes,
            bandwidth,
            self.parameters.transfer_setup_ns,
        )
        fabric = self.peer_fabric if plan.path == "PEER_HBM" else self.store_fabric
        resources = [self.copy[plan.source_gpu_id], fabric]
        if plan.target_gpu_id is not None and plan.target_gpu_id != plan.source_gpu_id:
            resources.append(self.copy[plan.target_gpu_id])
        try:
            reservations = _reserve_joint_concurrency(
                resources,
                ready_ns=self.des.now_ns,
                duration_ns=duration_ns,
                reservation_id_prefix=transfer_id,
                cause=f"AEGIS_{plan.path}_PROTECTION",
            )
        except Exception:
            pool.abort_reservation(
                pool_reservation.reservation_id,
                now_ns=self.des.now_ns,
                cause="TRANSFER_RESOURCE_RESERVE_FAILED",
            )
            raise
        end_ns = reservations[0].end_ns
        handle = self.des.schedule_at(
            end_ns,
            EventKind.PUT_COMMIT,
            event_id=f"commit:{transfer_id}",
            payload={"transfer_id": transfer_id, "path": plan.path},
        )
        self.pending_puts[transfer_id] = _PendingPut(
            transfer_id=transfer_id,
            path=plan.path,
            source_gpu_id=plan.source_gpu_id,
            target_gpu_id=plan.target_gpu_id,
            chunks=pool_reservation.chunks,
            scores=pool_reservation.scores,
            handle=handle,
            reservation_ids=tuple(
                (item.resource_id, item.reservation_id) for item in reservations
            ),
            pool_reservation_id=pool_reservation.reservation_id,
            bytes=transfer_bytes,
        )
        cause = f"AEGIS_{plan.path}_PROTECTION"
        self._record_transfer(
            _transfer_record(
                transfer_id=transfer_id,
                path=(
                    "D2D_P2P" if plan.path == "PEER_HBM" else "SOURCE_D2H_STORE"
                ),
                cause=cause,
                start_ns=reservations[0].start_ns,
                end_ns=end_ns,
                bytes=transfer_bytes,
                source_gpu_id=plan.source_gpu_id,
                target_gpu_id=(
                    plan.target_gpu_id
                    if plan.target_gpu_id is not None
                    else "store-0:segment-0"
                ),
                ready_ns=self.des.now_ns,
                status="PENDING",
                resource_reservations=reservations,
                span_id=plan.span_id,
            )
        )

    def _on_put_commit(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        transfer_id = _required_str(event.payload, "transfer_id")
        pending = self.pending_puts.pop(transfer_id, None)
        if pending is None:
            raise ExperimentError("unknown or canceled protection commit executed")
        if pending.source_gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed source attempted protection commit")
        if pending.path == "PEER_HBM":
            if pending.target_gpu_id is None:
                raise ExperimentError("Peer-HBM commit lost its physical target")
            if pending.target_gpu_id in self.failed_gpu_ids:
                raise ExperimentError("failed Peer-HBM target attempted protection commit")
            pool = self.peer_pools[pending.target_gpu_id]
        else:
            pool = self.store_pool
        committed = pool.commit_reservation(
            pending.pool_reservation_id,
            now_ns=self.des.now_ns,
            cause=f"{pending.path}_COMMIT",
        )
        if committed.bytes != pending.bytes:
            raise ExperimentError("pool commit bytes diverged from transfer bytes")
        self._commit_transfer(transfer_id)
        admitted = len(committed.chunks)
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_PROTECTION_PATH_COMMITTED",
            {
                "transfer_id": transfer_id,
                "path": pending.path,
                "candidate_chunks": len(pending.chunks),
                "admitted_chunks": admitted,
                "target_gpu_id": pending.target_gpu_id,
                "independent_path": True,
                "source_owned": True,
                "target_owned_destage": False,
            },
        )

    def _on_failure_inject(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu not in self.gpu_ids or target_gpu in self.failed_gpu_ids:
            raise ExperimentError("failure target is unknown or already failed")
        schedule = self.failure_schedule
        if schedule is None:
            raise ExperimentError("failure executed without a frozen schedule")
        if target_gpu != schedule.target_gpu_id:
            raise ExperimentError("resolved failure target diverged from its schedule")
        if _required_int(event.payload, "resolved_at_ns") != self.des.now_ns:
            raise ExperimentError("resolved failure timestamp diverged from the DES event")
        self._failure_event_executed = True
        self.failed_gpu_ids.add(target_gpu)
        impacted_active: list[str] = []
        impacted_queued: list[str] = []
        for execution in self.executions.values():
            if execution.gpu_id != target_gpu or execution.status not in {
                _ExecutionStatus.RUNNING,
                _ExecutionStatus.QUEUED,
            }:
                continue
            start_ns = execution.compute_start_ns
            if start_ns is None:
                raise ExperimentError("scheduled execution has no start time")
            if execution.completion_handle is None or execution.reservation_id is None:
                raise ExperimentError("scheduled execution lacks cancellation handles")
            self.des.cancel(execution.completion_handle, reason="GPU_FAILURE_ROUTE_FENCE")
            if (
                self.compute[target_gpu].cancel_from(
                    execution.reservation_id,
                    timestamp_ns=self.des.now_ns,
                )
                is None
            ):
                raise ExperimentError("failed compute reservation could not be fenced")
            execution.failure_at_ns = self.des.now_ns
            execution.status = _ExecutionStatus.FENCED
            if start_ns <= self.des.now_ns:
                impacted_active.append(execution.metadata.span_id)
            else:
                impacted_queued.append(execution.metadata.span_id)

        if schedule.focus_span_id not in impacted_active:
            raise ExperimentError("logical failure trigger did not hit its focus span")

        canceled_paths: list[str] = []
        canceled_before_start_paths: list[str] = []
        for plan_id, plan in tuple(self.pending_put_starts.items()):
            target_dependency = (
                plan.path == "PEER_HBM" and plan.target_gpu_id == target_gpu
            )
            if plan.source_gpu_id != target_gpu and not target_dependency:
                continue
            if not self.des.cancel(
                plan.handle,
                reason="GPU_FAILURE_BEFORE_TRANSFER_START",
            ):
                raise ExperimentError("pending protection start could not be canceled")
            canceled_before_start_paths.append(plan.path)
            self.protection_path_bypasses[
                f"{plan.path}_GPU_FAILURE_BEFORE_START"
            ] += 1
            del self.pending_put_starts[plan_id]
        for transfer_id, pending in tuple(self.pending_puts.items()):
            target_dependency = (
                pending.path == "PEER_HBM" and pending.target_gpu_id == target_gpu
            )
            if pending.source_gpu_id != target_gpu and not target_dependency:
                continue
            self.des.cancel(pending.handle, reason="GPU_FAILURE_SOURCE_PATH_DEPENDENCY")
            canceled_reservations = tuple(
                self._cancel_reservation(resource_id, reservation_id)
                for resource_id, reservation_id in pending.reservation_ids
            )
            destination_pool = (
                self.peer_pools[pending.target_gpu_id]
                if pending.target_gpu_id is not None
                else self.store_pool
            )
            released = destination_pool.abort_reservation(
                pending.pool_reservation_id,
                now_ns=self.des.now_ns,
                cause="GPU_FAILURE_TRANSFER_ABORT",
            )
            if released.bytes != pending.bytes:
                raise ExperimentError("aborted destination reserve bytes diverged")
            self._abort_transfer(
                transfer_id,
                reason="GPU_FAILURE_SOURCE_OR_DESTINATION_DEPENDENCY",
                reservations=canceled_reservations,
            )
            canceled_paths.append(pending.path)
            del self.pending_puts[transfer_id]

        failed_peer_pool = self.peer_pools[target_gpu]
        lost_peer_hbm_bytes = failed_peer_pool.fail(
            now_ns=self.des.now_ns,
            cause="GPU_FAILURE_UNAVAILABLE_CAPACITY",
        )

        failure_record = {
            "timestamp_ns": self.des.now_ns,
            "event": "FAILURE_INJECT",
            "type": "GPU_FAILURE",
            "target_gpu_id": target_gpu,
            "impacted_active_span_ids": sorted(impacted_active),
            "impacted_queued_span_ids": sorted(impacted_queued),
            "canceled_source_dependent_paths": sorted(canceled_paths),
            "canceled_before_start_paths": sorted(canceled_before_start_paths),
            "peer_hbm_lost_committed_bytes": lost_peer_hbm_bytes,
            "peer_hbm_unavailable_bytes": failed_peer_pool.unavailable_bytes,
            "store_dram_unavailable_bytes": 0,
            "repair_after_ns": None,
            "logical_trigger": {
                "focus_span_id": schedule.focus_span_id,
                "progress_per_mille": schedule.trigger_progress_per_mille,
                "resolved_at_ns": self.des.now_ns,
                "resolved_compute_start_ns": _required_int(
                    event.payload, "resolved_compute_start_ns"
                ),
                "resolved_compute_end_ns": _required_int(
                    event.payload, "resolved_compute_end_ns"
                ),
            },
        }
        self.failure_events.append(failure_record)
        self.des.journal.append(self.des.now_ns, "AEGIS_ROUTE_FENCE", failure_record)
        self.des.schedule_after(
            schedule.detection_delay_ns,
            EventKind.FAILURE_DETECT,
            event_id=f"detect:{schedule.failure_id}",
            payload={
                "failure_id": schedule.failure_id,
                "target_gpu_id": target_gpu,
                "active_span_ids": sorted(impacted_active),
                "queued_span_ids": sorted(impacted_queued),
            },
        )

    def _cancel_reservation(
        self, resource_id: str, reservation_id: str
    ) -> Reservation:
        resources: dict[str, ConcurrencyResource] = {
            resource.resource_id: resource for resource in self.copy.values()
        }
        resources[self.peer_fabric.resource_id] = self.peer_fabric
        resources[self.store_fabric.resource_id] = self.store_fabric
        resource = resources.get(resource_id)
        reservation = (
            None
            if resource is None
            else resource.cancel_from(reservation_id, timestamp_ns=self.des.now_ns)
        )
        if reservation is None:
            raise ExperimentError("pending transfer reservation could not be canceled")
        return reservation

    def _record_transfer(self, record: dict[str, Any]) -> None:
        transfer_id = _required_str(record, "transfer_id")
        if transfer_id in self._transfer_by_id:
            raise ExperimentError("duplicate transfer ledger ID")
        self.transfers.append(record)
        self._transfer_by_id[transfer_id] = record

    def _commit_transfer(self, transfer_id: str) -> None:
        try:
            record = self._transfer_by_id[transfer_id]
        except KeyError as error:
            raise ExperimentError("committed transfer lacks a ledger record") from error
        if record.get("status") != "PENDING":
            raise ExperimentError("only a pending transfer can commit")
        record["status"] = "COMMITTED"
        record["end_ns"] = self.des.now_ns
        record["terminal_ns"] = self.des.now_ns
        record["transferred_bytes"] = int(record["bytes"])
        record["aborted_bytes"] = 0
        record["terminal_reason"] = "ALL_REQUIRED_RESOURCES_COMPLETE"
        for interval in record["resource_intervals"]:
            interval["actual_end_ns"] = int(interval["planned_end_ns"])

    def _abort_transfer(
        self,
        transfer_id: str,
        *,
        reason: str,
        reservations: Sequence[Reservation],
    ) -> None:
        try:
            record = self._transfer_by_id[transfer_id]
        except KeyError as error:
            raise ExperimentError("aborted transfer lacks a ledger record") from error
        if record.get("status") != "PENDING":
            raise ExperimentError("only a pending transfer can abort")
        start_ns = int(record["start_ns"])
        planned_end_ns = int(record["planned_end_ns"])
        elapsed_ns = max(0, min(self.des.now_ns, planned_end_ns) - start_ns)
        planned_service_ns = max(1, planned_end_ns - start_ns)
        submitted_bytes = int(record["bytes"])
        transferred_bytes = submitted_bytes * elapsed_ns // planned_service_ns
        record["status"] = "ABORTED"
        record["end_ns"] = max(start_ns, self.des.now_ns)
        record["terminal_ns"] = self.des.now_ns
        record["transferred_bytes"] = transferred_bytes
        record["aborted_bytes"] = submitted_bytes - transferred_bytes
        record["terminal_reason"] = reason
        original_by_id = {item.reservation_id: item for item in reservations}
        for interval in record["resource_intervals"]:
            reservation_id = str(interval["reservation_id"])
            original = original_by_id.get(reservation_id)
            if original is None:
                raise ExperimentError("aborted transfer lost a resource reservation")
            interval["actual_end_ns"] = max(
                original.start_ns,
                min(self.des.now_ns, original.end_ns),
            )
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_TRANSFER_ABORTED",
            {
                "transfer_id": transfer_id,
                "reason": reason,
                "transferred_bytes": transferred_bytes,
                "aborted_bytes": submitted_bytes - transferred_bytes,
            },
        )

    def _on_failure_detect(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        active_ids = _required_str_list(event.payload, "active_span_ids")
        queued_ids = _required_str_list(event.payload, "queued_span_ids")
        for span_id in queued_ids:
            execution = self.executions[span_id]
            execution.route_version += 1
            target = self._route_gpu(span_id, route_version=execution.route_version)
            self._schedule_compute(
                execution,
                gpu_id=target,
                ready_ns=self.des.now_ns + self.parameters.reroute_ns,
                duration_ns=execution.scheduled_duration_ns,
            )
        for span_id in active_ids:
            self._plan_recovery(self.executions[span_id])

    def _plan_recovery(self, execution: _SpanExecution) -> None:
        if execution.failure_at_ns is None or execution.compute_start_ns is None:
            raise ExperimentError("recovery lacks failure progress timestamps")
        elapsed = max(0, execution.failure_at_ns - execution.compute_start_ns)
        duration = max(1, execution.scheduled_duration_ns)
        progress = min(Fraction(elapsed, duration), Fraction(1))
        execution.route_version += 1
        target_gpu = self._route_gpu(
            execution.metadata.span_id, route_version=execution.route_version
        )
        execution.gpu_id = target_gpu
        execution.status = _ExecutionStatus.RECOVERING

        peer_prefixes = {
            gpu_id: pool.peek_prefix_tokens(execution.chunks)
            for gpu_id, pool in self.peer_pools.items()
            if gpu_id not in self.failed_gpu_ids and self.profile.peer_fraction > 0
        }
        peer_source_gpu: str | None = None
        committed_peer_tokens = 0
        if peer_prefixes:
            committed_peer_tokens = max(peer_prefixes.values())
            if committed_peer_tokens > 0:
                candidates = tuple(
                    gpu_id
                    for gpu_id in sorted(peer_prefixes)
                    if peer_prefixes[gpu_id] == committed_peer_tokens
                )
                peer_source_gpu = (
                    target_gpu if target_gpu in candidates else candidates[0]
                )
                committed_peer_tokens = self.peer_pools[
                    peer_source_gpu
                ].lookup_prefix_tokens(execution.chunks, now_ns=self.des.now_ns)
        committed_store_tokens = (
            self.store_pool.lookup_prefix_tokens(execution.chunks, now_ns=self.des.now_ns)
            if self.profile.store_fraction > 0
            else 0
        )
        peer_tokens = min(committed_peer_tokens, execution.metadata.prompt_tokens)
        store_tokens = min(committed_store_tokens, execution.metadata.prompt_tokens)
        restored_tokens = max(peer_tokens, store_tokens)
        execution.restored_peer_tokens = min(peer_tokens, restored_tokens)
        execution.restored_store_tokens = max(0, restored_tokens - execution.restored_peer_tokens)
        execution.recompute_tokens = execution.metadata.prompt_tokens - restored_tokens
        execution.committed_output_tokens_at_failure = int(
            execution.metadata.output_tokens * progress
        )

        ready_ns = self.des.now_ns + self.parameters.reroute_ns
        recovery_end = ready_ns
        source_breakdown = (
            ("PEER_HBM", execution.restored_peer_tokens),
            ("STORE_DRAM", execution.restored_store_tokens),
        )
        for source, tokens in source_breakdown:
            if tokens <= 0:
                continue
            transfer_bytes = _tokens_to_allocated_bytes(tokens)
            if source == "PEER_HBM" and peer_source_gpu == target_gpu:
                cause = "AEGIS_RECOVERY_PEER_HBM_LOCAL_ACTIVATION"
                self._record_transfer(
                    _transfer_record(
                        transfer_id=self._next_id(
                            f"recovery-activation:{execution.metadata.span_id}"
                        ),
                        path="PEER_HBM_LOCAL_ACTIVATION",
                        cause=cause,
                        start_ns=ready_ns,
                        end_ns=ready_ns,
                        bytes=transfer_bytes,
                        source_gpu_id=target_gpu,
                        target_gpu_id=target_gpu,
                        ready_ns=ready_ns,
                        status="COMMITTED",
                        span_id=execution.metadata.span_id,
                    )
                )
                continue
            bandwidth = (
                self.parameters.peer_bandwidth_bytes_per_second
                if source == "PEER_HBM"
                else self.parameters.store_bandwidth_bytes_per_second
            )
            transfer_ns = _transfer_duration_ns(
                transfer_bytes,
                bandwidth,
                self.parameters.transfer_setup_ns,
            )
            fabric = self.peer_fabric if source == "PEER_HBM" else self.store_fabric
            resources = [self.copy[target_gpu], fabric]
            if source == "PEER_HBM":
                if peer_source_gpu is None:
                    raise ExperimentError("Peer-HBM recovery lost its committed source")
                if peer_source_gpu != target_gpu:
                    resources.append(self.copy[peer_source_gpu])
            transfer_id = self._next_id(
                f"recovery:{source}:{execution.metadata.span_id}"
            )
            reservations = _reserve_joint_concurrency(
                resources,
                ready_ns=ready_ns,
                duration_ns=transfer_ns,
                reservation_id_prefix=transfer_id,
                cause=f"AEGIS_RECOVERY_{source}",
            )
            transfer_end_ns = reservations[0].end_ns
            recovery_end = max(recovery_end, transfer_end_ns)
            cause = f"AEGIS_RECOVERY_{source}"
            transfer_source = "store-0:segment-0"
            if source == "PEER_HBM":
                assert peer_source_gpu is not None
                transfer_source = peer_source_gpu
            self._record_transfer(
                _transfer_record(
                    transfer_id=transfer_id,
                    path="D2D_P2P" if source == "PEER_HBM" else "STORE_H2D",
                    cause=cause,
                    start_ns=reservations[0].start_ns,
                    end_ns=transfer_end_ns,
                    bytes=transfer_bytes,
                    source_gpu_id=transfer_source,
                    target_gpu_id=target_gpu,
                    ready_ns=ready_ns,
                    status="COMMITTED",
                    resource_reservations=reservations,
                    span_id=execution.metadata.span_id,
                )
            )
            ready_ns = transfer_end_ns
        self.des.schedule_at(
            recovery_end,
            EventKind.RECOVERY_COMPLETE,
            event_id=self._next_id(f"recovery-ready:{execution.metadata.span_id}"),
            payload={
                "span_id": execution.metadata.span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "restored_peer_tokens": execution.restored_peer_tokens,
                "restored_store_tokens": execution.restored_store_tokens,
                "recompute_tokens": execution.recompute_tokens,
            },
        )
        self.recovery_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "RECOVERY_PLAN",
                "span_id": execution.metadata.span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "peer_source_gpu_id": peer_source_gpu,
                "source_tokens": {
                    "PEER_HBM": execution.restored_peer_tokens,
                    "STORE_DRAM": execution.restored_store_tokens,
                    "RECOMPUTE": execution.recompute_tokens,
                },
                "continuous_prefix_only": True,
                "all_shards_required": True,
                "committed_replica_only": True,
                "in_flight_protection_estimate_used": False,
            }
        )

    def _on_recovery_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        """Materialize restored KV, then recompute the missing prompt suffix.

        Recovery compute phases use separate resource reservations so their
        causal order is explicit on the single global DES clock:
        restore -> prompt recompute -> silent replay -> activate -> decode.
        """

        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale recovery plan reached materialization")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu in self.failed_gpu_ids:
            raise ExperimentError("recovery selected a failed target")
        execution.status = _ExecutionStatus.RECOVERING
        execution.gpu_id = target_gpu
        prompt_recompute_ns, _silent_ns, _remaining_decode_ns = (
            _post_failure_compute_durations(execution)
        )
        start_ns = self.des.now_ns
        complete_ns = start_ns
        reservation_id: str | None = None
        if prompt_recompute_ns > 0:
            reservation = self.compute[target_gpu].reserve(
                ready_ns=self.des.now_ns,
                duration_ns=prompt_recompute_ns,
                reservation_id=self._next_id(f"recovery-prompt-recompute:{span_id}"),
                cause="AEGIS_RECOVERY_PROMPT_SUFFIX_RECOMPUTE",
            )
            start_ns = reservation.start_ns
            complete_ns = reservation.end_ns
            reservation_id = reservation.reservation_id
        execution.prompt_recompute_start_ns = start_ns
        execution.compute_start_ns = start_ns
        execution.planned_complete_ns = complete_ns
        execution.reservation_id = reservation_id
        execution.scheduled_duration_ns = prompt_recompute_ns
        self.recovery_events.append(
            {
                "timestamp_ns": start_ns,
                "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "recompute_tokens": execution.recompute_tokens,
                "duration_ns": prompt_recompute_ns,
            }
        )
        self.des.schedule_at(
            complete_ns,
            EventKind.RECOVERY_RECOMPUTE_COMPLETE,
            event_id=self._next_id(f"prompt-recompute-complete:{span_id}"),
            payload={
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
            },
        )

    def _on_recovery_recompute_complete(
        self, event: ScheduledEvent, _des: GlobalDES
    ) -> None:
        """Replay committed output only after the prompt block table is rebuilt."""

        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale route finished prompt suffix recompute")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu in self.failed_gpu_ids:
            raise ExperimentError("failed recovery target finished prompt recompute")
        execution.prompt_recompute_complete_ns = self.des.now_ns
        self.recovery_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "recompute_tokens": execution.recompute_tokens,
            }
        )
        _prompt_recompute_ns, silent_ns, _remaining_decode_ns = (
            _post_failure_compute_durations(execution)
        )
        start_ns = self.des.now_ns
        complete_ns = start_ns
        reservation_id: str | None = None
        if silent_ns > 0:
            reservation = self.compute[target_gpu].reserve(
                ready_ns=self.des.now_ns,
                duration_ns=silent_ns,
                reservation_id=self._next_id(f"recovery-silent-replay:{span_id}"),
                cause="AEGIS_RECOVERY_SILENT_REPLAY",
            )
            start_ns = reservation.start_ns
            complete_ns = reservation.end_ns
            reservation_id = reservation.reservation_id
        execution.silent_replay_start_ns = start_ns
        execution.compute_start_ns = start_ns
        execution.planned_complete_ns = complete_ns
        execution.reservation_id = reservation_id
        execution.scheduled_duration_ns = silent_ns
        self.recovery_events.append(
            {
                "timestamp_ns": start_ns,
                "event": "SILENT_REPLAY_START",
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "replayed_output_tokens": execution.committed_output_tokens_at_failure,
                "duration_ns": silent_ns,
                "externally_emitted_tokens": 0,
            }
        )
        self.des.schedule_at(
            complete_ns,
            EventKind.SILENT_REPLAY_COMPLETE,
            event_id=self._next_id(f"silent-replay-complete:{span_id}"),
            payload={
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
            },
        )

    def _on_silent_replay_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale route finished silent replay")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu in self.failed_gpu_ids:
            raise ExperimentError("failed recovery target finished silent replay")
        execution.silent_replay_complete_ns = self.des.now_ns
        execution.recovery_ready_ns = self.des.now_ns
        self.recovery_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "SILENT_REPLAY_COMPLETE",
                "span_id": span_id,
                "route_version": execution.route_version,
                "externally_emitted_tokens": 0,
                "replayed_output_tokens": execution.committed_output_tokens_at_failure,
            }
        )
        _prompt_recompute_ns, _silent_ns, remaining_decode_ns = (
            _post_failure_compute_durations(execution)
        )
        start_ns = self.des.now_ns
        complete_ns = start_ns
        reservation_id: str | None = None
        if remaining_decode_ns > 0:
            reservation = self.compute[target_gpu].reserve(
                ready_ns=self.des.now_ns,
                duration_ns=remaining_decode_ns,
                reservation_id=self._next_id(f"recovery-resumed-decode:{span_id}"),
                cause="AEGIS_RECOVERY_REMAINING_DECODE",
            )
            start_ns = reservation.start_ns
            complete_ns = reservation.end_ns
            reservation_id = reservation.reservation_id
        execution.resume_decode_start_ns = start_ns
        execution.compute_start_ns = start_ns
        execution.planned_complete_ns = complete_ns
        execution.reservation_id = reservation_id
        execution.scheduled_duration_ns = remaining_decode_ns
        execution.status = _ExecutionStatus.RESUMED
        self.recovery_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "RECOVERY_ATOMIC_ACTIVATION",
                "span_id": span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "remaining_output_tokens": (
                    execution.metadata.output_tokens
                    - execution.committed_output_tokens_at_failure
                ),
                "decode_start_ns": start_ns,
            }
        )
        execution.completion_handle = self.des.schedule_at(
            complete_ns,
            EventKind.REQUEST_COMPLETE,
            event_id=self._next_id(f"recovered-complete:{span_id}"),
            payload={
                "span_id": span_id,
                "route_version": execution.route_version,
                "gpu_id": target_gpu,
            },
        )

    def _chunk_score(
        self,
        execution: _SpanExecution,
        chunk: _Chunk,
        *,
        path: str,
        modeled_pool: _ModeledPool,
    ) -> Fraction:
        """Evaluate the patent J/W/Uhit/Ulru/G/P/H equations exactly."""

        metadata = execution.metadata
        pool = PolicyPool.PEER_HBM if path == "PEER_HBM" else PolicyPool.STORE_DRAM
        sequence_index = chunk.token_start // self.parameters.policy_chunk_tokens
        candidate = SealedChunk(
            chunk_id=f"{pool.value}:{chunk.key}",
            request_id=metadata.span_id,
            sequence_index=sequence_index,
            allocated_bytes=chunk.bytes,
        )
        recovery_value_enabled = self.profile.recovery_weight > 0
        recovery_before = Fraction(
            execution.base_duration_ns
            * max(0, metadata.prompt_tokens - chunk.token_start),
            max(1, metadata.prompt_tokens),
        )
        recovery_after = (
            max(
                Fraction(0, 1),
                recovery_before
                - Fraction(
                    execution.base_duration_ns * chunk.token_count,
                    max(1, metadata.prompt_tokens),
                ),
            )
            if recovery_value_enabled
            else recovery_before
        )
        slack_ns = (
            max(0, metadata.observed_finish_ns - self.des.now_ns)
            if recovery_value_enabled and self.profile.slack_weight > 0
            else 0
        )
        hit_probability = Fraction(
            metadata.cached_prefix_tokens,
            max(1, metadata.prompt_tokens),
        )
        reuse_saving = Fraction(
            execution.base_duration_ns * chunk.token_count,
            max(1, metadata.prompt_tokens),
        )
        age_ns = max(0, self.des.now_ns - metadata.observed_submit_ns)
        lru_utility = Fraction(1_000_000_000, 1_000_000_000 + age_ns)
        versions = SignalVersions(
            slack=sequence_index,
            hit=sequence_index,
            lru=sequence_index,
            frontier=sequence_index,
        )
        signals = RentalSignals(
            slack=SlackSignal(
                slack_at_observation_ns=Fraction(slack_ns, 1),
                observed_at_ns=self.des.now_ns,
                version=versions.slack,
            ),
            hit_probability=hit_probability,
            reuse_saving=reuse_saving,
            lru_utility=lru_utility,
            last_access_ns=self.des.now_ns,
            versions=versions,
        )
        weights = RentalWeights(
            lambda_w=Fraction(max(1, self.profile.recovery_weight), 1),
            lambda_h=Fraction(self.profile.reuse_weight, 1),
            lambda_l=Fraction(1, 1),
        )
        def evaluate(
            after: Fraction,
            evaluation_weights: RentalWeights,
        ) -> Fraction:
            return compute_rental_value(
                RentalValueInputs(
                    candidate=candidate,
                    pool=pool,
                    signals=signals,
                    recovery_time_before=recovery_before,
                    recovery_time_after=after,
                    weights=evaluation_weights,
                    pool_rent=modeled_pool.rent,
                    now_ns=self.des.now_ns,
                )
            ).rental_key

        unified = evaluate(recovery_after, weights)
        if (
            self.profile.unified_manager
            or self.profile.eviction is not EvictionKind.SLACK_LANDLORD_VALUE
        ):
            return unified

        # The two-manager ablation keeps one directory and visible committed
        # replicas, but reuse and recovery managers bid independently.  It may
        # retain the larger bid; it cannot add the two utilities as Algorithm 1
        # does in unified mode.
        recovery_bid = evaluate(
            recovery_after,
            RentalWeights(
                lambda_w=Fraction(max(1, self.profile.recovery_weight), 1),
                lambda_h=Fraction(0, 1),
                lambda_l=Fraction(0, 1),
            ),
        )
        reuse_bid = evaluate(
            recovery_before,
            RentalWeights(
                lambda_w=Fraction(1, 1),
                lambda_h=Fraction(self.profile.reuse_weight, 1),
                lambda_l=Fraction(1, 1),
            ),
        )
        return max(recovery_bid, reuse_bid)

    def _payload(self, end_ns: int) -> dict[str, Any]:
        completed = tuple(self.executions.values())
        workflow_starts: dict[str, int] = {}
        workflow_ends: dict[str, int] = {}
        latencies: list[int] = []
        recovery_latencies: list[int] = []
        focus_latencies: list[int] = []
        target_bucket = self.context_bucket
        for execution in completed:
            if execution.released_ns is None or execution.completed_ns is None:
                raise ExperimentError("completed span lacks timing")
            workflow_id = execution.metadata.workflow_id
            workflow_starts[workflow_id] = min(
                workflow_starts.get(workflow_id, execution.released_ns), execution.released_ns
            )
            workflow_ends[workflow_id] = max(
                workflow_ends.get(workflow_id, execution.completed_ns), execution.completed_ns
            )
            latency = execution.completed_ns - execution.released_ns
            latencies.append(latency)
            if bucket_name_for(
                execution.metadata.prompt_tokens + execution.metadata.output_tokens
            ) == target_bucket:
                focus_latencies.append(latency)
            if execution.failure_at_ns is not None and execution.recovery_ready_ns is not None:
                recovery_latencies.append(execution.recovery_ready_ns - execution.failure_at_ns)
        workflow_wct = [
            workflow_ends[workflow_id] - start_ns
            for workflow_id, start_ns in sorted(workflow_starts.items())
        ]
        earliest = min(workflow_starts.values())
        elapsed_ns = max(1, end_ns - earliest)
        output_tokens = sum(item.metadata.output_tokens for item in completed)
        failure_active = sum(
            len(item["impacted_active_span_ids"]) for item in self.failure_events
        )
        failure_queued = sum(
            len(item["impacted_queued_span_ids"]) for item in self.failure_events
        )
        if self.failure_schedule is not None and failure_active == 0:
            raise ExperimentError("frozen failure did not hit an active request")
        peer_timeline = _aggregate_pool_timeline(self.peer_pools)
        peer_peak_bytes = max(
            (int(point["occupied_bytes"]) for point in peer_timeline),
            default=0,
        )
        peer_final_bytes = sum(pool.occupied_bytes for pool in self.peer_pools.values())
        peer_quota_bytes = sum(pool.capacity_bytes for pool in self.peer_pools.values())
        peer_physical_bytes = sum(
            pool.physical_capacity_bytes for pool in self.peer_pools.values()
        )
        peer_by_gpu = {
            gpu_id: {
                "physical_capacity_bytes": pool.physical_capacity_bytes,
                "quota_bytes": pool.capacity_bytes,
                "final_bytes": pool.occupied_bytes,
                "peak_bytes": pool.peak_bytes,
                "pending_peak_bytes": pool.pending_peak_bytes,
                "byte_ns": pool.byte_ns,
                "evicted_chunks": pool.evicted_chunks,
                "bypassed_chunks": pool.bypassed_chunks,
                "dual_role_alias_no_double_charge_count": pool.alias_hits,
                "failed_unavailable": pool.failed,
                "unavailable_bytes": pool.unavailable_bytes,
                "lost_committed_bytes": pool.lost_committed_bytes,
                "valid": (
                    pool.occupied_bytes + pool.pending_bytes
                    <= pool.capacity_bytes
                    <= pool.physical_capacity_bytes
                    and (
                        not pool.failed
                        or (
                            pool.occupied_bytes == 0
                            and pool.capacity_bytes == 0
                            and pool.unavailable_bytes == pool.physical_capacity_bytes
                        )
                    )
                ),
            }
            for gpu_id, pool in sorted(self.peer_pools.items())
        }
        transfer_accounting = _aggregate_transfer_accounting(self.transfers)
        metrics = {
            "virtual_end_ns": end_ns,
            "workflow_completion_time_ns": {
                "mean": _integer_mean(workflow_wct),
                "p95": _nearest_rank(workflow_wct, 95),
                "max": max(workflow_wct),
            },
            "request_latency_ns": {
                "mean": _integer_mean(latencies),
                "p95": _nearest_rank(latencies, 95),
                "focus_bucket_mean": _integer_mean(focus_latencies),
            },
            "goodput_output_tokens_per_second_milli": (
                output_tokens * 1_000_000_000 * 1_000 // elapsed_ns
            ),
            "restored_tokens": {
                "peer_hbm": sum(item.restored_peer_tokens for item in completed),
                "store_dram": sum(item.restored_store_tokens for item in completed),
                "total": sum(
                    item.restored_peer_tokens + item.restored_store_tokens
                    for item in completed
                ),
            },
            "recompute_tokens_after_failure": sum(item.recompute_tokens for item in completed),
            "cache_reuse_tokens": {
                "peer_hbm": sum(item.reused_peer_tokens for item in completed),
                "store_dram": sum(item.reused_store_tokens for item in completed),
            },
            "recovery_latency_ns": {
                "count": len(recovery_latencies),
                "mean": _integer_mean(recovery_latencies),
                "p95": _nearest_rank(recovery_latencies, 95),
            },
            "failure_impact": {
                "active_requests": failure_active,
                "queued_requests": failure_queued,
                "failed_gpu_count": len(self.failed_gpu_ids),
            },
            "resource_cost": {
                "peer_hbm_peak_bytes": peer_peak_bytes,
                "peer_hbm_byte_ns": sum(
                    pool.byte_ns for pool in self.peer_pools.values()
                ),
                "store_dram_peak_bytes": self.store_pool.peak_bytes,
                "store_dram_byte_ns": self.store_pool.byte_ns,
                "peer_hbm_by_gpu": peer_by_gpu,
                "store_dram_by_segment": {
                    "store-0:segment-0": {
                        "capacity_bytes": self.store_pool.capacity_bytes,
                        "final_bytes": self.store_pool.occupied_bytes,
                        "peak_bytes": self.store_pool.peak_bytes,
                        "pending_peak_bytes": self.store_pool.pending_peak_bytes,
                        "byte_ns": self.store_pool.byte_ns,
                        "failed_unavailable": False,
                    }
                },
                "network_byte_ns": transfer_accounting["network_byte_ns"],
                "copy_engine_busy_ns": transfer_accounting["copy_engine_busy_ns"],
                "fabric_busy_ns": transfer_accounting["fabric_busy_ns"],
                "cause_bytes": transfer_accounting["transferred_bytes_by_cause"],
                "submitted_bytes_by_cause": transfer_accounting[
                    "submitted_bytes_by_cause"
                ],
                "aborted_bytes_by_cause": transfer_accounting[
                    "aborted_bytes_by_cause"
                ],
                "queue_wait_ns_by_cause": transfer_accounting[
                    "queue_wait_ns_by_cause"
                ],
                "service_time_ns_by_cause": transfer_accounting[
                    "service_time_ns_by_cause"
                ],
                "transfer_state_counts": transfer_accounting["state_counts"],
                "transfer_byte_conservation_valid": transfer_accounting[
                    "byte_conservation_valid"
                ],
            },
            "policy_effects": {
                "slack_signal_enabled": self.profile.slack_weight > 0,
                "recovery_value_enabled": self.profile.recovery_weight > 0,
                "reuse_value_enabled": self.profile.reuse_weight > 0,
                "committed_reuse_visibility": {
                    "peer_hbm": self._reuse_visible("PEER_HBM"),
                    "store_dram": self._reuse_visible("STORE_DRAM"),
                },
                "manager_mode": (
                    "UNIFIED_ADDITIVE_REUSE_RECOVERY_VALUE"
                    if self.profile.unified_manager
                    else "TWO_INDEPENDENT_VALUE_BIDS_SHARED_DIRECTORY"
                ),
                "aimd_enabled": self.profile.aimd_enabled,
                "aimd_decision_count": len(self.aimd_events),
                "aimd_action_counts": dict(
                    sorted(Counter(str(item["action"]) for item in self.aimd_events).items())
                ),
                "cache_aware_routing_enabled": self.profile.cache_aware_routing,
                "cache_aware_route_evaluations": self.cache_aware_route_evaluations,
                "cache_aware_route_changes": self.cache_aware_route_changes,
                "anti_colocation_enabled": self.profile.anti_colocation,
                "protection_path_bypasses": dict(
                    sorted(self.protection_path_bypasses.items())
                ),
            },
            "pool_audit": {
                "peer_hbm": {
                    "physical_capacity_bytes": peer_physical_bytes,
                    "quota_bytes": peer_quota_bytes,
                    "final_bytes": peer_final_bytes,
                    "evicted_chunks": sum(
                        pool.evicted_chunks for pool in self.peer_pools.values()
                    ),
                    "bypassed_chunks": sum(
                        pool.bypassed_chunks for pool in self.peer_pools.values()
                    ),
                    "pending_peak_bytes_sum": sum(
                        pool.pending_peak_bytes for pool in self.peer_pools.values()
                    ),
                    "dual_role_alias_no_double_charge_count": sum(
                        pool.alias_hits for pool in self.peer_pools.values()
                    ),
                    "per_gpu": peer_by_gpu,
                    "valid": (
                        peer_final_bytes <= peer_quota_bytes <= peer_physical_bytes
                        and all(bool(item["valid"]) for item in peer_by_gpu.values())
                    ),
                },
                "store_dram": {
                    "capacity_bytes": self.store_pool.capacity_bytes,
                    "final_bytes": self.store_pool.occupied_bytes,
                    "evicted_chunks": self.store_pool.evicted_chunks,
                    "bypassed_chunks": self.store_pool.bypassed_chunks,
                    "dual_role_alias_no_double_charge_count": self.store_pool.alias_hits,
                    "pending_peak_bytes": self.store_pool.pending_peak_bytes,
                    "valid": (
                        self.store_pool.occupied_bytes + self.store_pool.pending_bytes
                        <= self.store_pool.capacity_bytes
                    ),
                },
                "pending_destination_bytes_final": sum(
                    pool.pending_bytes
                    for pool in (*self.peer_pools.values(), self.store_pool)
                ),
                "unattributed_reserve_bytes": sum(
                    pool.pending_bytes
                    for pool in (*self.peer_pools.values(), self.store_pool)
                    if not pool.pending
                ),
            },
        }
        return {
            "schema": "moonkvsim.aegiskv.study_run_payload.v1",
            "status": "PASS",
            "evidence": {
                "class": "E2",
                "scope": "modeled/preliminary",
                "calibration": "not_calibrated",
                "physical_execution": False,
                "physical_timing_claim_allowed": False,
                "formal_use_allowed": False,
                "paper_ready": False,
            },
            "global_clock": {
                "kind": "single_global_virtual_clock",
                "time_unit": "ns",
                "wall_clock_or_sleep_used": False,
                "event_order": "timestamp_priority_stable_sequence",
            },
            "execution_scope": {
                "cpu_metadata_only": True,
                "slurm_used": False,
                "cuda_used": False,
                "network_io_used": False,
            },
            "resource_model": {
                "peer_hbm_resources": list(sorted(self.peer_pools)),
                "store_dram_segments": ["store-0:segment-0"],
                "copy_engines": [item.resource_id for item in self.copy.values()],
                "fabric_resources": [
                    self.peer_fabric.resource_id,
                    self.store_fabric.resource_id,
                ],
                "per_gpu_peer_hbm_quota_enforced": True,
                "failed_gpu_hbm_becomes_unavailable_not_free": True,
            },
            "recovery_model": {
                "committed_replica_only": True,
                "continuous_prefix_only": True,
                "in_flight_protection_estimate_used": False,
                "missing_suffix_recomputed": True,
                "phase_order": [
                    "RESTORE_COMMITTED_PREFIX",
                    "PROMPT_SUFFIX_RECOMPUTE",
                    "SILENT_REPLAY_COMMITTED_OUTPUT",
                    "ATOMIC_ACTIVATION",
                    "REMAINING_DECODE",
                ],
            },
            "variant_fingerprint": self.variant.fingerprint,
            "context_bucket": self.context_bucket,
            "scenario": (
                Scenario.GPU_FAILURE.value
                if self.failure_schedule is not None
                else Scenario.NO_FAILURE.value
            ),
            "workload": {
                "span_count": len(completed),
                "workflow_count": len(workflow_starts),
                "source_hash_scope": "within_workflow_only",
                "no_truncation_or_padding": True,
            },
            "failure_schedule": (
                None if self.failure_schedule is None else self.failure_schedule.to_dict()
            ),
            "metrics": metrics,
            "output_audit": {
                "expected_output_tokens": output_tokens,
                "external_output_tokens": sum(
                    item.external_output_emissions for item in completed
                ),
                "duplicate_or_missing_tokens": 0,
                "stale_route_output_count": 0,
            },
            "forbidden_semantics": {
                "hbm_to_dram_writeback_count": 0,
                "target_owned_destage_count": 0,
                "dram_prerequisite_for_hbm_count": 0,
                "cross_tier_abort_propagation_count": 0,
                "second_directory_count": 0,
                "ssd_nvme_event_count": 0,
            },
        }

    def _span_detail(self, execution: _SpanExecution) -> dict[str, Any]:
        return {
            "span_id": execution.metadata.span_id,
            "workflow_id": execution.metadata.workflow_id,
            "context_bucket": bucket_name_for(
                execution.metadata.prompt_tokens + execution.metadata.output_tokens
            ),
            "gpu_id": execution.gpu_id,
            "route_version": execution.route_version,
            "released_ns": execution.released_ns,
            "compute_start_ns": execution.compute_start_ns,
            "completed_ns": execution.completed_ns,
            "base_duration_ns": execution.base_duration_ns,
            "reused_peer_tokens": execution.reused_peer_tokens,
            "reused_store_tokens": execution.reused_store_tokens,
            "restored_peer_tokens": execution.restored_peer_tokens,
            "restored_store_tokens": execution.restored_store_tokens,
            "recompute_tokens": execution.recompute_tokens,
            "failure_at_ns": execution.failure_at_ns,
            "recovery_ready_ns": execution.recovery_ready_ns,
            "prompt_recompute_start_ns": execution.prompt_recompute_start_ns,
            "prompt_recompute_complete_ns": execution.prompt_recompute_complete_ns,
            "silent_replay_start_ns": execution.silent_replay_start_ns,
            "silent_replay_complete_ns": execution.silent_replay_complete_ns,
            "resume_decode_start_ns": execution.resume_decode_start_ns,
            "output_tokens": execution.metadata.output_tokens,
            "external_output_emissions": execution.external_output_emissions,
        }

    def _next_id(self, suffix: str) -> str:
        value = f"study:{self._event_sequence:08d}:{suffix}"
        self._event_sequence += 1
        return value


def run_study_cell(
    records: Sequence[Mapping[str, Any]],
    spec: CellSpec,
) -> StudyRunResult:
    """Run one independent matched cell on a fresh GlobalDES instance."""

    runtime = _StudyRuntime(
        records=records,
        variant=spec.variant,
        context_bucket=spec.context_bucket,
        seed=spec.seed,
        failure_schedule=spec.failure_schedule,
    )
    return runtime.run()


def derive_failure_schedules(
    records: Sequence[Mapping[str, Any]],
    *,
    buckets: Sequence[str],
    seed: int,
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> dict[str, FailureSchedule]:
    """Freeze common focus/GPU/progress triggers for multiple trace buckets.

    Absolute virtual timestamps are outcomes: cache reuse and policy change when
    the same span starts.  Freezing an absolute timestamp therefore either hits
    different requests or has no common active interval.  The matched input is
    instead the same trace span, initial physical GPU route, and within-compute
    progress.  Each fresh cell resolves that logical trigger on its own global
    clock; ``reference_at_ns`` is provenance from the recompute-only oracle.
    All requested buckets share one set of no-failure oracle runs.
    """

    canonical_buckets = tuple(dict.fromkeys(buckets))
    valid_buckets = {item.name for item in CONTEXT_BUCKETS}
    if not canonical_buckets or any(item not in valid_buckets for item in canonical_buckets):
        raise ValueError("failure schedule buckets must be non-empty and known")

    compared_profiles = tuple(
        dict.fromkeys(
            variant.profile
            for variant in (*core_variants(parameters), *ablation_variants(parameters))
        )
    )
    oracle_results = tuple(
        run_study_cell(
            records,
            CellSpec(
                variant=ExperimentVariant(
                    suite="failure_schedule_oracle",
                    variant_id=f"profile-{index}",
                    profile=profile,
                    parameters=parameters,
                ),
                context_bucket=canonical_buckets[0],
                scenario=Scenario.NO_FAILURE,
                seed=seed,
                repetition="A",
            ),
        )
        for index, profile in enumerate(compared_profiles)
    )
    details_by_oracle = tuple(
        {str(item["span_id"]): item for item in result.span_details}
        for result in oracle_results
    )
    schedules: dict[str, FailureSchedule] = {}
    for bucket in canonical_buckets:
        candidates = [
            item
            for item in oracle_results[0].span_details
            if item["context_bucket"] == bucket
            and len(
                {
                    details[str(item["span_id"])]["gpu_id"]
                    for details in details_by_oracle
                }
            )
            == 1
        ]
        if not candidates:
            raise ExperimentError(
                f"failure oracle has no common-route span in bucket {bucket} seed {seed}"
            )
        candidates.sort(
            key=lambda item: hashlib.sha256(
                f"{seed}:{item['span_id']}".encode()
            ).hexdigest()
        )
        focus = candidates[0]
        gpu_id = focus.get("gpu_id")
        start_ns = focus.get("compute_start_ns")
        end_ns = focus.get("completed_ns")
        if (
            not isinstance(gpu_id, str)
            or type(start_ns) is not int
            or type(end_ns) is not int
            or end_ns <= start_ns
        ):
            raise ExperimentError("failure oracle focus interval is malformed")
        reference_at_ns = start_ns + (
            (end_ns - start_ns) * parameters.failure_progress_per_mille // 1_000
        )
        schedules[bucket] = FailureSchedule(
            failure_id=f"gpu-failure:{bucket}:seed-{seed}",
            bucket=bucket,
            seed=seed,
            focus_span_id=str(focus["span_id"]),
            target_gpu_id=gpu_id,
            reference_at_ns=reference_at_ns,
            detection_delay_ns=parameters.failure_detection_ns,
            trigger_progress_per_mille=parameters.failure_progress_per_mille,
        )
    return schedules


def derive_failure_schedule(
    records: Sequence[Mapping[str, Any]],
    *,
    bucket: str,
    seed: int,
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> FailureSchedule:
    """Return one bucket while reusing the same oracle set for sibling buckets."""

    key = (sha256_json(records), sha256_json(parameters.to_dict()), seed)
    schedules = _FAILURE_SCHEDULE_CACHE.get(key)
    if schedules is None:
        schedules = derive_failure_schedules(
            records,
            buckets=tuple(item.name for item in CONTEXT_BUCKETS),
            seed=seed,
            parameters=parameters,
        )
        _FAILURE_SCHEDULE_CACHE[key] = schedules
    try:
        return schedules[bucket]
    except KeyError as error:
        raise ValueError(f"unknown failure schedule bucket: {bucket}") from error


def core_variants(
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> tuple[ExperimentVariant, ...]:
    return tuple(
        ExperimentVariant(
            suite="core",
            variant_id=system_id.value,
            profile=SYSTEM_PROFILES[system_id],
            parameters=parameters,
        )
        for system_id in SystemId
    )


def ablation_variants(
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> tuple[ExperimentVariant, ...]:
    full = SYSTEM_PROFILES[SystemId.AEGIS_UNIFIED]
    variants = (
        ("full", full, False),
        ("no_slack", replace(full, slack_weight=0), False),
        ("no_reuse_value", replace(full, reuse_weight=0), False),
        ("no_recovery_value", replace(full, recovery_weight=0), False),
        ("two_managers", replace(full, unified_manager=False), False),
        ("no_aimd", replace(full, aimd_enabled=False), False),
        (
            "static_hbm_quota",
            replace(full, peer_fraction=Fraction(1, 2), aimd_enabled=False),
            False,
        ),
        ("random_eviction", replace(full, eviction=EvictionKind.RANDOM_STABLE), False),
        ("lru_eviction", replace(full, eviction=EvictionKind.LRU), False),
        ("lfu_eviction", replace(full, eviction=EvictionKind.LFU), False),
        ("no_anti_colocation", replace(full, anti_colocation=False), True),
        ("no_cache_aware_routing", replace(full, cache_aware_routing=False), False),
    )
    return tuple(
        ExperimentVariant(
            suite="ablation",
            variant_id=variant_id,
            profile=profile,
            parameters=parameters,
            negative_control=negative,
        )
        for variant_id, profile, negative in variants
    )


def sensitivity_variants(
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> tuple[ExperimentVariant, ...]:
    full = SYSTEM_PROFILES[SystemId.AEGIS_UNIFIED]
    variants: list[ExperimentVariant] = []
    dimensions: tuple[tuple[str, tuple[int, ...]], ...] = (
        ("peer_budget_gib", (4, 8, 12)),
        ("store_budget_gib", (32, 64, 128)),
        ("store_bandwidth_gbps", (12, 25, 50)),
        ("peer_fabric_bandwidth_gbps", (50, 100, 200)),
        ("dp_count", (2, 4, 8)),
        ("failure_progress_percent", (10, 50, 90)),
        ("detection_delay_ms", (1, 5, 20)),
        ("reroute_delay_ms", (0, 1, 5)),
        ("policy_chunk_tokens", (256, 1_024, 4_096)),
    )
    for dimension, values in dimensions:
        for value in values:
            updated = parameters
            if dimension == "peer_budget_gib":
                updated = replace(parameters, peer_budget_bytes_per_gpu=value * GIB)
            elif dimension == "store_budget_gib":
                updated = replace(parameters, store_budget_bytes=value * GIB)
            elif dimension == "store_bandwidth_gbps":
                updated = replace(
                    parameters, store_bandwidth_bytes_per_second=value * 1_000_000_000
                )
            elif dimension == "peer_fabric_bandwidth_gbps":
                updated = replace(
                    parameters, peer_bandwidth_bytes_per_second=value * 1_000_000_000
                )
            elif dimension == "dp_count":
                updated = replace(parameters, dp_count=value)
            elif dimension == "failure_progress_percent":
                updated = replace(parameters, failure_progress_per_mille=value * 10)
            elif dimension == "detection_delay_ms":
                updated = replace(parameters, failure_detection_ns=value * 1_000_000)
            elif dimension == "reroute_delay_ms":
                updated = replace(parameters, reroute_ns=value * 1_000_000)
            elif dimension == "policy_chunk_tokens":
                updated = replace(parameters, policy_chunk_tokens=value)
            variants.append(
                ExperimentVariant(
                    suite="sensitivity",
                    variant_id=f"{dimension}={value}",
                    profile=full,
                    parameters=updated,
                )
            )
    return tuple(variants)


def _common_active_ranges(
    oracle_details: Sequence[Mapping[str, Mapping[str, Any]]],
    *,
    bucket: str | None,
) -> list[tuple[str, int, int]]:
    """Intersect per-system unions of active intervals for each physical GPU."""

    gpu_ids = sorted(
        {
            str(item["gpu_id"])
            for details in oracle_details
            for item in details.values()
            if isinstance(item.get("gpu_id"), str)
        }
    )
    common: list[tuple[str, int, int]] = []
    for gpu_id in gpu_ids:
        intersection: list[tuple[int, int]] | None = None
        for details in oracle_details:
            intervals: list[tuple[int, int]] = []
            for item in details.values():
                if item.get("gpu_id") != gpu_id:
                    continue
                if bucket is not None and item.get("context_bucket") != bucket:
                    continue
                start = item.get("compute_start_ns")
                end = item.get("completed_ns")
                if type(start) is int and type(end) is int and end > start:
                    intervals.append((start, end))
            merged = _merge_ranges(intervals)
            intersection = (
                merged
                if intersection is None
                else _intersect_ranges(intersection, merged)
            )
            if not intersection:
                break
        common.extend((gpu_id, start, end) for start, end in (intersection or []))
    return common


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _intersect_ranges(
    left: Sequence[tuple[int, int]], right: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        start = max(left[left_index][0], right[right_index][0])
        end = min(left[left_index][1], right[right_index][1])
        if end > start:
            result.append((start, end))
        if left[left_index][1] <= right[right_index][1]:
            left_index += 1
        else:
            right_index += 1
    return result


def _chunks_for_record(
    record: Mapping[str, Any], parameters: ModelParameters
) -> tuple[_Chunk, ...]:
    raw_hashes = record.get("source_hash_ids")
    if not isinstance(raw_hashes, list) or not all(type(item) is int for item in raw_hashes):
        raise ExperimentError("source hash IDs are missing or malformed")
    blocks_per_chunk = parameters.policy_chunk_tokens // SOURCE_BLOCK_TOKENS
    result: list[_Chunk] = []
    workflow_id = str(record["workflow_id"])
    for block_start in range(0, len(raw_hashes), blocks_per_chunk):
        hash_ids = raw_hashes[block_start : block_start + blocks_per_chunk]
        token_count = len(hash_ids) * SOURCE_BLOCK_TOKENS
        key = sha256_json(
            {
                "schema": "moonkvsim.aegiskv.policy_chunk.v1",
                "workflow_id": workflow_id,
                "source_block_start": block_start,
                "source_hash_ids": hash_ids,
                "source_hash_scope": "within_workflow_only",
            }
        )
        result.append(
            _Chunk(
                key=key,
                workflow_id=workflow_id,
                token_start=block_start * SOURCE_BLOCK_TOKENS,
                token_count=token_count,
                bytes=len(hash_ids) * KV_BYTES_PER_SOURCE_BLOCK,
            )
        )
    return tuple(result)


def _duration_after_prefix_reuse(
    metadata: NormalizedSpanMetadata, base_duration_ns: int, reused_tokens: int
) -> int:
    prompt = metadata.prompt_tokens
    output_weighted = metadata.output_tokens * 8
    weighted_total = max(1, prompt + output_weighted)
    remaining = max(1, prompt - reused_tokens + output_weighted)
    return max(1, base_duration_ns * remaining // weighted_total)


def _post_failure_compute_durations(execution: _SpanExecution) -> tuple[int, int, int]:
    metadata = execution.metadata
    weighted_total = max(1, metadata.prompt_tokens + metadata.output_tokens * 8)
    prompt_recompute_weight = execution.recompute_tokens
    silent_weight = execution.committed_output_tokens_at_failure * 8
    remaining_output = metadata.output_tokens - execution.committed_output_tokens_at_failure
    remaining_decode_weight = remaining_output * 8
    prompt_recompute_ns = (
        execution.base_duration_ns * prompt_recompute_weight // weighted_total
    )
    silent_ns = execution.base_duration_ns * silent_weight // weighted_total
    remaining_decode_ns = (
        execution.base_duration_ns * remaining_decode_weight // weighted_total
    )
    return prompt_recompute_ns, silent_ns, remaining_decode_ns


def _transfer_duration_ns(bytes_count: int, bandwidth: int, setup_ns: int) -> int:
    if bytes_count <= 0:
        return 0
    return setup_ns + math.ceil(bytes_count * 1_000_000_000 / bandwidth)


def _tokens_to_allocated_bytes(tokens: int) -> int:
    blocks = (tokens + SOURCE_BLOCK_TOKENS - 1) // SOURCE_BLOCK_TOKENS
    return blocks * KV_BYTES_PER_SOURCE_BLOCK


def _fraction_count(count: int, fraction: Fraction) -> int:
    return count * fraction.numerator // fraction.denominator


def _fraction_dict(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction_to_decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def _aggregate_pool_timeline(
    pools: Mapping[str, _ModeledPool],
) -> list[dict[str, int | str]]:
    """Project per-resource event boundaries onto one aggregate occupancy curve."""

    events: list[tuple[int, str, int, Mapping[str, int | str]]] = []
    for pool_id, pool in sorted(pools.items()):
        for sequence, point in enumerate(pool.timeline):
            timestamp = point.get("timestamp_ns")
            if type(timestamp) is not int:
                raise ExperimentError("pool timeline timestamp is malformed")
            events.append((timestamp, pool_id, sequence, point))
    occupied = {pool_id: 0 for pool_id in pools}
    quotas = {pool_id: pool.capacity_bytes for pool_id, pool in pools.items()}
    result: list[dict[str, int | str]] = []
    index = 0
    ordered = sorted(events, key=lambda item: (item[0], item[1], item[2]))
    while index < len(ordered):
        timestamp = ordered[index][0]
        causes: list[str] = []
        while index < len(ordered) and ordered[index][0] == timestamp:
            _timestamp, pool_id, _sequence, event_point = ordered[index]
            value = event_point.get("occupied_bytes")
            capacity = event_point.get("capacity_bytes")
            cause = event_point.get("cause")
            if type(value) is not int or type(capacity) is not int or not isinstance(cause, str):
                raise ExperimentError("pool timeline event is malformed")
            occupied[pool_id] = value
            quotas[pool_id] = capacity
            causes.append(f"{pool_id}:{cause}")
            index += 1
        result.append(
            {
                "timestamp_ns": timestamp,
                "occupied_bytes": sum(occupied.values()),
                "capacity_bytes": sum(quotas.values()),
                "cause": "|".join(causes),
            }
        )
    return result


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ExperimentError(f"event payload {key} must be a non-empty string")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise ExperimentError(f"event payload {key} must be an integer")
    return value


def _required_str_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ExperimentError(f"event payload {key} must be a string array")
    return value


def _integer_mean(values: Sequence[int]) -> int:
    return 0 if not values else sum(values) // len(values)


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered) / 100))
    return ordered[rank - 1]


def _aggregate_transfer_accounting(
    transfers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive resource/cause totals only from terminal transfer ledger rows."""

    submitted: Counter[str] = Counter()
    transferred: Counter[str] = Counter()
    aborted: Counter[str] = Counter()
    network_byte_ns: Counter[str] = Counter()
    copy_busy_ns: Counter[str] = Counter()
    fabric_busy_ns: Counter[str] = Counter()
    queue_wait_ns: Counter[str] = Counter()
    service_time_ns: Counter[str] = Counter()
    states: Counter[str] = Counter()
    valid = True
    for record in transfers:
        cause = str(record.get("cause", ""))
        status = str(record.get("status", ""))
        size = record.get("bytes")
        moved = record.get("transferred_bytes")
        dropped = record.get("aborted_bytes")
        ready_ns = record.get("ready_ns")
        start_ns = record.get("start_ns")
        end_ns = record.get("end_ns")
        if (
            not cause
            or status not in {"COMMITTED", "ABORTED"}
            or not all(
                type(value) is int and value >= 0
                for value in (size, moved, dropped, ready_ns, start_ns, end_ns)
            )
        ):
            raise ExperimentError("terminal transfer accounting row is malformed")
        size_bytes = cast(int, size)
        moved_bytes = cast(int, moved)
        dropped_bytes = cast(int, dropped)
        ready_timestamp = cast(int, ready_ns)
        start_timestamp = cast(int, start_ns)
        end_timestamp = cast(int, end_ns)
        if (
            ready_timestamp > start_timestamp
            or end_timestamp < start_timestamp
            or size_bytes != moved_bytes + dropped_bytes
        ):
            valid = False
        submitted[cause] += size_bytes
        transferred[cause] += moved_bytes
        aborted[cause] += dropped_bytes
        states[status] += 1
        queue_wait_ns[cause] += max(0, start_timestamp - ready_timestamp)
        service_ns = max(0, end_timestamp - start_timestamp)
        service_time_ns[cause] += service_ns
        if record.get("path") != "PEER_HBM_LOCAL_ACTIVATION":
            network_byte_ns[cause] += moved_bytes * service_ns
        raw_intervals = record.get("resource_intervals")
        if not isinstance(raw_intervals, list):
            raise ExperimentError("transfer resource intervals are malformed")
        for interval in raw_intervals:
            if not isinstance(interval, Mapping):
                raise ExperimentError("transfer resource interval is malformed")
            resource_id = interval.get("resource_id")
            interval_start = interval.get("start_ns")
            actual_end = interval.get("actual_end_ns")
            if (
                not isinstance(resource_id, str)
                or type(interval_start) is not int
                or type(actual_end) is not int
                or actual_end < interval_start
            ):
                raise ExperimentError("terminal resource interval is malformed")
            busy_ns = actual_end - interval_start
            if resource_id.endswith(".copy"):
                copy_busy_ns[cause] += busy_ns
            elif resource_id.endswith("-fabric"):
                fabric_busy_ns[cause] += busy_ns
    return {
        "submitted_bytes_by_cause": dict(sorted(submitted.items())),
        "transferred_bytes_by_cause": dict(sorted(transferred.items())),
        "aborted_bytes_by_cause": dict(sorted(aborted.items())),
        "network_byte_ns": dict(sorted(network_byte_ns.items())),
        "copy_engine_busy_ns": dict(sorted(copy_busy_ns.items())),
        "fabric_busy_ns": dict(sorted(fabric_busy_ns.items())),
        "queue_wait_ns_by_cause": dict(sorted(queue_wait_ns.items())),
        "service_time_ns_by_cause": dict(sorted(service_time_ns.items())),
        "state_counts": dict(sorted(states.items())),
        "byte_conservation_valid": valid,
    }


def _reserve_joint_concurrency(
    resources: Sequence[ConcurrencyResource],
    *,
    ready_ns: int,
    duration_ns: int,
    reservation_id_prefix: str,
    cause: str,
) -> tuple[Reservation, ...]:
    """Reserve one common interval across every end-to-end path resource."""

    if not resources or len({item.resource_id for item in resources}) != len(resources):
        raise ExperimentError("joint transfer resources must be non-empty and unique")
    candidate_ns = ready_ns
    while True:
        starts = tuple(
            resource.earliest_start(ready_ns=candidate_ns, duration_ns=duration_ns)
            for resource in resources
        )
        next_candidate_ns = max(starts)
        if next_candidate_ns == candidate_ns and all(
            start_ns == candidate_ns for start_ns in starts
        ):
            break
        candidate_ns = next_candidate_ns
    reservations = tuple(
        resource.reserve(
            ready_ns=candidate_ns,
            duration_ns=duration_ns,
            reservation_id=f"{reservation_id_prefix}:resource-{index}",
            cause=cause,
        )
        for index, resource in enumerate(resources)
    )
    if any(
        item.start_ns != candidate_ns or item.end_ns != candidate_ns + duration_ns
        for item in reservations
    ):
        raise ExperimentError("joint transfer reservation lost interval alignment")
    return reservations


def _transfer_record(
    *,
    transfer_id: str,
    path: str,
    cause: str,
    start_ns: int,
    end_ns: int,
    bytes: int,
    source_gpu_id: str,
    target_gpu_id: str,
    ready_ns: int | None = None,
    status: str = "COMMITTED",
    resource_reservations: Sequence[Reservation] = (),
    span_id: str | None = None,
) -> dict[str, Any]:
    if status not in {"PENDING", "COMMITTED"}:
        raise ValueError("new transfer record must be pending or committed")
    if end_ns < start_ns:
        raise ValueError("transfer end cannot precede start")
    resolved_ready_ns = start_ns if ready_ns is None else ready_ns
    if resolved_ready_ns > start_ns:
        raise ValueError("transfer ready time cannot follow service start")
    committed = status == "COMMITTED"
    return {
        "transfer_id": transfer_id,
        "span_id": span_id,
        "path": path,
        "cause": cause,
        "status": status,
        "ready_ns": resolved_ready_ns,
        "start_ns": start_ns,
        "planned_end_ns": end_ns,
        "end_ns": end_ns,
        "terminal_ns": end_ns if committed else None,
        "bytes": bytes,
        "transferred_bytes": bytes if committed else 0,
        "aborted_bytes": 0,
        "terminal_reason": "ALL_REQUIRED_RESOURCES_COMPLETE" if committed else None,
        "source": source_gpu_id,
        "target": target_gpu_id,
        "resource_intervals": [
            {
                "reservation_id": reservation.reservation_id,
                "resource_id": reservation.resource_id,
                "lane": reservation.lane,
                "start_ns": reservation.start_ns,
                "planned_end_ns": reservation.end_ns,
                "actual_end_ns": reservation.end_ns if committed else None,
                "cause": reservation.cause,
            }
            for reservation in resource_reservations
        ],
    }
