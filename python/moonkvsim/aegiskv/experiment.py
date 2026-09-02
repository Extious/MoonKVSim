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
import os
import resource
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from functools import partial
from typing import Any, Final, cast

from moonkvsim.aegiskv.continuous_batch_des import (
    AegisContinuousBatchDESDriver,
    ContinuousBatchRequestSpec,
    ObservedIdealTraceDurationProvider,
)
from moonkvsim.aegiskv.experiment_hbm_authority import ExperimentHBMAuthority
from moonkvsim.aegiskv.experiment_workload import (
    CONTEXT_BUCKETS,
    bucket_name_for,
)
from moonkvsim.aegiskv.hbm_quota_aimd import (
    AIMDDecision,
    AIMDParameters,
    AIMDTargetState,
    HBMQuotaAIMD,
)
from moonkvsim.aegiskv.ideal_trace_cpm import (
    compute_ideal_trace_cpm,
    compute_residual_ideal_trace_cpm,
)
from moonkvsim.aegiskv.lazy_refresh import RentalEntry
from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta,
    RecoveryHarmSnapshot,
    RecoveryTimeBreakdown,
    VictimSetHarmDelta,
    current_design_rental_value,
)
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.scheduler_step_bridge import (
    AegisSchedulerStep,
    AegisSchedulerStepBridge,
    ResidentPrimarySnapshot,
    SchedulerExecutionBinding,
    SchedulerStepCompletion,
)
from moonkvsim.aegiskv.slack_landlord import SlackLandlord
from moonkvsim.aegiskv.types import (
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.scheduler import (
    VLLM_SOURCE_COMMIT,
    ContinuousBatchScheduler,
)
from moonkvsim.predictor.schema import ForwardBoundary, PredictionProfile
from moonkvsim.predictor.vllm_adapter import VLLMSchedulerBatchAdapter
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.network import FlowContentionModel, FlowRateInterval
from moonkvsim.simulation.resource import ConcurrencyResource, RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_runtime import TransferRuntime
from moonkvsim.workload.causal_replay import CausalReleaseEngine
from moonkvsim.workload.causal_trace import (
    NormalizedSpanMetadata,
    load_normalized_trace_records,
)

SOURCE_BLOCK_TOKENS: Final = 64
KV_BYTES_PER_SOURCE_BLOCK: Final = 9_437_184
QWEN3_8B_MODEL_ID: Final = "Qwen/Qwen3-8B"
QWEN3_8B_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
QWEN3_8B_CONFIG_SHA256: Final = (
    "f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30"
)
QWEN3_8B_NATIVE_LAYOUT_FINGERPRINT: Final = (
    "a2652848f10c2902063dbdb33195c4b58804e9cbc3d867c5767037278f437973"
)
QWEN3_8B_YARN_128K_LAYOUT_FINGERPRINT: Final = (
    "42cff103674b5a857c1e6308247fbd006bf80ac444efd50a377c40ab4696a29e"
)
LOCKED_DP_COUNT: Final = 8
ALLOWED_DP_COUNTS: Final = (LOCKED_DP_COUNT,)
GIB: Final = 1024**3
A100_40GB_HBM_BYTES: Final = 40 * GIB
QWEN3_8B_MODEL_WEIGHTS_BYTES: Final = 16_381_470_720
RUNTIME_FIXED_RESERVE_WEIGHT_DIVISOR: Final = 8
RUNTIME_FIXED_RESERVE_ALIGNMENT_BYTES: Final = GIB
PEER_HBM_ALPHA_MIN: Final = Decimal("0")
PEER_HBM_ALPHA_MAX: Final = Decimal("0.5")
GPU_SKU: Final = "NVIDIA-A100-40GB"
INFERENCE_NODE_ID: Final = "node-inference-0"
INFERENCE_NUMA_NODE_ID: Final = "numa:node-inference-0:0"
TOPOLOGY: Final = "single_node"
FLOW_SLICE_POLICY_CHUNKS: Final = 8
AIMD_CONTROL_WINDOW_MIN_NS: Final = 1_000_000_000
HBM_MODEL_WEIGHTS_ACCOUNT: Final = "MODEL_WEIGHTS"
HBM_RUNTIME_FIXED_ACCOUNT: Final = "RUNTIME_FIXED"
HBM_RUNTIME_DYNAMIC_ACCOUNT: Final = "RUNTIME_DYNAMIC"
HBM_ACTIVE_PRIMARY_ACCOUNT: Final = "ACTIVE_PRIMARY_KV"
HBM_INACTIVE_REUSABLE_ACCOUNT: Final = "INACTIVE_REUSABLE_KV"
HBM_PEER_PROTECTION_ACCOUNT: Final = "PEER_PROTECTION_KV"
HBM_PEER_PENDING_ACCOUNT: Final = "PEER_PROTECTION_PENDING"
HBM_RECOVERY_RESERVED_ACCOUNT: Final = "RECOVERY_DEST_RESERVED"
HBM_FOREGROUND_STORE_RESERVED_ACCOUNT: Final = "FOREGROUND_STORE_RESTORE_RESERVED"
HBM_TRANSFER_STAGING_ACCOUNT: Final = "TRANSFER_STAGING"
HBM_FRAGMENTATION_ACCOUNT: Final = "ALLOCATOR_FRAGMENTATION"
HBM_UNATTRIBUTED_ACCOUNT: Final = "UNATTRIBUTED_RESERVE"
HOST_TRANSFER_STAGING_ACCOUNT: Final = "TRANSFER_STAGING"
AIMD_PARAMETERS: Final = AIMDParameters(
    minimum_fraction=Decimal("0"),
    maximum_fraction=Decimal("0.50"),
    multiplicative_decrease=Decimal("0.50"),
    additive_increase=Decimal("0.05"),
    stable_window_count=4,
)

_FAILURE_SCHEDULE_CACHE: dict[
    tuple[str, str, str, int, int | None, int, tuple[object, ...] | None, bool],
    dict[str, FailureSchedule],
] = {}


def derive_runtime_fixed_bytes_per_gpu(model_weights_bytes: int) -> int:
    """Derive the modeled non-weight HBM reserve from the model footprint.

    The E2 simulator has no physical vLLM/CUDA allocator observation.  It
    therefore reserves one eighth of the serialized model weight footprint,
    rounded up to a GiB boundary, for framework state and fixed workspaces.
    """

    if type(model_weights_bytes) is not int or model_weights_bytes <= 0:
        raise ValueError("model_weights_bytes must be a positive integer")
    unaligned = (
        model_weights_bytes + RUNTIME_FIXED_RESERVE_WEIGHT_DIVISOR - 1
    ) // RUNTIME_FIXED_RESERVE_WEIGHT_DIVISOR
    return (
        (unaligned + RUNTIME_FIXED_RESERVE_ALIGNMENT_BYTES - 1)
        // RUNTIME_FIXED_RESERVE_ALIGNMENT_BYTES
        * RUNTIME_FIXED_RESERVE_ALIGNMENT_BYTES
    )


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


def qwen3_8b_dp_only_contract() -> dict[str, Any]:
    """Return the immutable Qwen3-8B DP=8 single-node A100-40GB contract."""

    return {
        "scope_id": "qwen3-8b-dp8-a100-40gb-single-node-v1",
        "model": {
            "id": QWEN3_8B_MODEL_ID,
            "revision": QWEN3_8B_MODEL_REVISION,
            "config_sha256": QWEN3_8B_CONFIG_SHA256,
            "other_models_allowed": False,
        },
        "kv_layout": {
            "bytes_per_64_source_tokens": KV_BYTES_PER_SOURCE_BLOCK,
            "native_tp1_pp1_fingerprint": QWEN3_8B_NATIVE_LAYOUT_FINGERPRINT,
            "proposed_yarn_128k_tp1_pp1_fingerprint": (
                QWEN3_8B_YARN_128K_LAYOUT_FINGERPRINT
            ),
            "evidence": "source_derived_not_physically_calibrated",
        },
        "parallelism": {
            "data_parallel_size": LOCKED_DP_COUNT,
            "allowed_data_parallel_sizes": list(ALLOWED_DP_COUNTS),
            "data_parallel_sensitivity_allowed": False,
            "tensor_parallel_size": 1,
            "pipeline_parallel_size": 1,
            "tensor_parallel_sensitivity_allowed": False,
            "pipeline_parallel_sensitivity_allowed": False,
        },
        "hardware": {
            "gpu_sku": GPU_SKU,
            "gpu_count": LOCKED_DP_COUNT,
            "node_count": 1,
            "topology": TOPOLOGY,
            "physical_hbm_bytes_per_gpu": A100_40GB_HBM_BYTES,
            "evidence": "modeled_not_physically_calibrated",
        },
    }


def qwen3_8b_dp_deployment(dp_count: int) -> dict[str, Any]:
    """Bind one AegisKV cell to the locked Qwen3-8B DP=8 A100-40GB contract."""

    if dp_count != LOCKED_DP_COUNT:
        raise ValueError(
            f"Qwen3-8B experiments require dp_count={LOCKED_DP_COUNT}, got {dp_count}"
        )
    return qwen3_8b_dp_only_contract()


@dataclass(frozen=True, slots=True)
class SystemProfile:
    """Policy coverage; Peer replication coverage is independent of HBM alpha."""

    system_id: SystemId
    label: str
    peer_replication_fraction: Fraction
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
        for value in (self.peer_replication_fraction, self.store_fraction):
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
    dp_count: int = LOCKED_DP_COUNT
    store_node_count: int = 1
    physical_hbm_bytes_per_gpu: int = A100_40GB_HBM_BYTES
    peer_hbm_alpha: Decimal = Decimal("0.2")
    store_budget_bytes: int = 1_000_000_000_000
    peer_bandwidth_bytes_per_second: int = 25_000_000_000
    store_bandwidth_bytes_per_second: int = 25_000_000_000
    tcp_store_bandwidth_bytes_per_second: int = 8_000_000_000
    host_staging_bandwidth_bytes_per_second: int = 16_000_000_000
    host_staging_capacity_bytes_per_node: int = 32 * GIB
    store_transport: TransportKind = TransportKind.PCIE
    transfer_setup_ns: int = 250_000
    failure_detection_ns: int = 0
    reroute_ns: int = 1_000_000
    policy_chunk_tokens: int = 1_024
    failure_progress_per_mille: int = 600
    gpu_recovery_time_ns: int = 120_000_000_000

    def __post_init__(self) -> None:
        positive = (
            self.dp_count,
            self.store_node_count,
            self.physical_hbm_bytes_per_gpu,
            self.store_budget_bytes,
            self.peer_bandwidth_bytes_per_second,
            self.store_bandwidth_bytes_per_second,
            self.tcp_store_bandwidth_bytes_per_second,
            self.host_staging_bandwidth_bytes_per_second,
            self.host_staging_capacity_bytes_per_node,
            self.transfer_setup_ns,
            self.policy_chunk_tokens,
            self.gpu_recovery_time_ns,
        )
        if any(type(item) is not int or item <= 0 for item in positive):
            raise ValueError("modeled parameters must be positive integers")
        if self.dp_count not in ALLOWED_DP_COUNTS:
            raise ValueError(
                f"Qwen3-8B experiments require dp_count={LOCKED_DP_COUNT}"
            )
        if self.physical_hbm_bytes_per_gpu != A100_40GB_HBM_BYTES:
            raise ValueError(
                "Qwen3-8B experiments lock each GPU to modeled A100-40GB HBM "
                f"({A100_40GB_HBM_BYTES} bytes)"
            )
        if not isinstance(self.peer_hbm_alpha, Decimal) or not self.peer_hbm_alpha.is_finite():
            raise ValueError("peer_hbm_alpha must be a finite Decimal")
        if not PEER_HBM_ALPHA_MIN <= self.peer_hbm_alpha <= PEER_HBM_ALPHA_MAX:
            raise ValueError("peer_hbm_alpha must be in [0, 0.5]")
        if self.kv_capacity_bytes_per_gpu <= 0:
            raise ValueError("model weights and fixed runtime reserve exhaust physical HBM")
        if self.reroute_ns < 0:
            raise ValueError("reroute_ns must be non-negative")
        if self.failure_detection_ns < 0:
            raise ValueError("failure_detection_ns must be non-negative")
        if self.store_transport not in {
            TransportKind.PCIE,
            TransportKind.RDMA_GDR,
            TransportKind.RDMA_HOST_STAGED,
            TransportKind.TCP_HOST_STAGED,
        }:
            raise ValueError("Store transport must be a supported PCIe or network path")
        if (
            self.store_transport is TransportKind.PCIE
            and self.store_node_count != 1
        ):
            raise ValueError("PCIe Store transport requires one colocated Store node")
        if self.policy_chunk_tokens % SOURCE_BLOCK_TOKENS:
            raise ValueError("policy chunks must align to 64-token source blocks")
        if not 1 <= self.failure_progress_per_mille <= 999:
            raise ValueError("failure progress must be strictly within a request")

    @property
    def model_weights_bytes_per_gpu(self) -> int:
        """Exact TP=1 serialized weight bytes from the locked model index."""

        return QWEN3_8B_MODEL_WEIGHTS_BYTES

    @property
    def runtime_fixed_bytes_per_gpu(self) -> int:
        """Code-derived modeled reserve; it is not an engine input."""

        return derive_runtime_fixed_bytes_per_gpu(self.model_weights_bytes_per_gpu)

    @property
    def kv_capacity_bytes_per_gpu(self) -> int:
        """HBM left for primary/reusable/protection KV after fixed accounts."""

        return (
            self.physical_hbm_bytes_per_gpu
            - self.model_weights_bytes_per_gpu
            - self.runtime_fixed_bytes_per_gpu
        )

    @property
    def peer_hbm_quota_bytes_per_gpu(self) -> int:
        """Initial Peer-HBM protection quota: floor(alpha * KV-capable HBM)."""

        return int(self.peer_hbm_alpha * Decimal(self.kv_capacity_bytes_per_gpu))

    @property
    def peer_hbm_max_quota_bytes_per_gpu(self) -> int:
        """Maximum dynamic Peer-HBM quota under the alpha <= 0.5 contract."""

        return int(PEER_HBM_ALPHA_MAX * Decimal(self.kv_capacity_bytes_per_gpu))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_deployment": qwen3_8b_dp_deployment(self.dp_count),
            "dp_count": self.dp_count,
            "store_node_count": self.store_node_count,
            "gpu_sku": GPU_SKU,
            "topology": TOPOLOGY,
            "node_count": 1,
            "physical_hbm_bytes_per_gpu": self.physical_hbm_bytes_per_gpu,
            "model_weights_bytes_per_gpu": self.model_weights_bytes_per_gpu,
            "runtime_fixed_bytes_per_gpu": self.runtime_fixed_bytes_per_gpu,
            "kv_capacity_bytes_per_gpu": self.kv_capacity_bytes_per_gpu,
            "peer_hbm_alpha": float(self.peer_hbm_alpha),
            "peer_hbm_quota_bytes_per_gpu": self.peer_hbm_quota_bytes_per_gpu,
            "peer_hbm_max_quota_bytes_per_gpu": self.peer_hbm_max_quota_bytes_per_gpu,
            "store_budget_bytes": self.store_budget_bytes,
            "peer_bandwidth_bytes_per_second": self.peer_bandwidth_bytes_per_second,
            "store_bandwidth_bytes_per_second": self.store_bandwidth_bytes_per_second,
            "tcp_store_bandwidth_bytes_per_second": (
                self.tcp_store_bandwidth_bytes_per_second
            ),
            "host_staging_bandwidth_bytes_per_second": (
                self.host_staging_bandwidth_bytes_per_second
            ),
            "host_staging_capacity_bytes_per_node": (
                self.host_staging_capacity_bytes_per_node
            ),
            "store_transport": self.store_transport.value,
            "transfer_setup_ns": self.transfer_setup_ns,
            "failure_detection_ns": self.failure_detection_ns,
            "reroute_ns": self.reroute_ns,
            "policy_chunk_tokens": self.policy_chunk_tokens,
            "failure_progress_per_mille": self.failure_progress_per_mille,
            "gpu_recovery_time_ns": self.gpu_recovery_time_ns,
            "provenance": {
                "kv_bytes_per_64_tokens": {
                    "value": KV_BYTES_PER_SOURCE_BLOCK,
                    "source": "source_derived_qwen3_8b_tp1_pp1_kv_layout",
                },
                "peer_hbm_aimd": {
                    "parameters": AIMD_PARAMETERS.to_dict(),
                    "source": "patent_formula_with_explicit_modeled_e2_parameters",
                },
                "model_weights_bytes_per_gpu": {
                    "source": "locked_model_safetensors_index_total_size_tp1",
                    "value": self.model_weights_bytes_per_gpu,
                },
                "runtime_fixed_bytes_per_gpu": {
                    "source": "modeled_weight_fraction_rounded_to_gib_not_physically_observed",
                    "weight_divisor": RUNTIME_FIXED_RESERVE_WEIGHT_DIVISOR,
                    "alignment_bytes": RUNTIME_FIXED_RESERVE_ALIGNMENT_BYTES,
                    "value": self.runtime_fixed_bytes_per_gpu,
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
            "peer_replication_fraction": _fraction_dict(
                profile.peer_replication_fraction
            ),
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
class FailureEventSchedule:
    """One frozen logical failure intervention.

    ``target_gpu_id`` and ``reference_at_ns`` describe the route/timing seen by
    the schedule-selection oracle.  They are provenance only.  The runtime
    resolves the physical target from ``focus_span_id`` when that span actually
    starts compute in each variant.
    """

    failure_id: str
    event_index: int
    bucket: str
    seed: int
    focus_span_id: str
    target_gpu_id: str
    reference_at_ns: int
    target_workload_progress_per_mille: int
    reference_completed_workflow_count: int
    reference_workflow_count: int
    detection_delay_ns: int
    trigger_progress_per_mille: int
    gpu_recovery_time_ns: int | None = None
    selection_scope: str = (
        "variant_local_focus_span_gpu_at_shared_workload_target_after_prior_failures"
    )

    def __post_init__(self) -> None:
        if not self.failure_id or not self.focus_span_id or not self.target_gpu_id:
            raise ValueError("failure schedule identifiers must be non-empty")
        if type(self.event_index) is not int or self.event_index < 0:
            raise ValueError("failure event index must be non-negative")
        if self.bucket not in {item.name for item in CONTEXT_BUCKETS}:
            raise ValueError("failure schedule has an unknown context bucket")
        if self.seed < 0 or self.reference_at_ns < 0 or self.detection_delay_ns < 0:
            raise ValueError("failure schedule timestamps and seed are invalid")
        if not 1 <= self.target_workload_progress_per_mille <= 999:
            raise ValueError("target workload progress must be strictly inside a run")
        if not 0 <= self.reference_completed_workflow_count < self.reference_workflow_count:
            raise ValueError("reference completed-workflow progress is invalid")
        if not 1 <= self.trigger_progress_per_mille <= 999:
            raise ValueError("logical failure progress must be strictly inside a request")
        if self.gpu_recovery_time_ns is not None and self.gpu_recovery_time_ns <= 0:
            raise ValueError("GPU recovery time must be positive or null")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "event_index": self.event_index,
            "type": "GPU_FAILURE",
            "bucket": self.bucket,
            "seed": self.seed,
            "focus_span_id": self.focus_span_id,
            "target_gpu_id": self.target_gpu_id,
            "target_gpu_id_semantics": (
                "REFERENCE_ROUTE_PROVENANCE_NOT_RUNTIME_FAILURE_TARGET"
            ),
            "workload_position": {
                "kind": "COMPLETED_WORKFLOW_FRACTION_NEAREST_COMMON_ROUTE_SPAN",
                "target_progress_per_mille": self.target_workload_progress_per_mille,
                "reference_completed_workflow_count": (
                    self.reference_completed_workflow_count
                ),
                "reference_workflow_count": self.reference_workflow_count,
            },
            "trigger": {
                "kind": "FOCUS_SPAN_COMPUTE_PROGRESS",
                "progress_per_mille": self.trigger_progress_per_mille,
            },
            "reference_at_ns": self.reference_at_ns,
            "reference_at_ns_semantics": "recompute_only_oracle_provenance_not_cell_time",
            "detection_delay_ns": self.detection_delay_ns,
            "selection_scope": self.selection_scope,
            "repair_after_ns": self.gpu_recovery_time_ns,
            "parameter_source": "deterministic_focus_span_progress_global_des",
        }


@dataclass(frozen=True, slots=True)
class FailureSchedule:
    """All GPU failures injected into one independent workload run."""

    events: tuple[FailureEventSchedule, ...]
    selection_scope: str = "single_global_des_run_multiple_gpu_failure_events"

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("failure schedule must contain at least one event")
        if tuple(event.event_index for event in self.events) != tuple(
            range(len(self.events))
        ):
            raise ValueError("failure event indices must be contiguous and ordered")
        if len({event.failure_id for event in self.events}) != len(self.events):
            raise ValueError("failure event IDs must be unique")
        if len({event.focus_span_id for event in self.events}) != len(self.events):
            raise ValueError("failure focus spans must be distinct")
        if len({(event.bucket, event.seed) for event in self.events}) != 1:
            raise ValueError("failure events must share one bucket and seed")
        progresses = tuple(
            event.target_workload_progress_per_mille for event in self.events
        )
        if progresses != tuple(sorted(progresses)) or len(set(progresses)) != len(
            progresses
        ):
            raise ValueError("failure workload progress targets must be strictly increasing")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    @property
    def bucket(self) -> str:
        return self.events[0].bucket

    @property
    def seed(self) -> int:
        return self.events[0].seed

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "GPU_FAILURE",
            "failure_count": len(self.events),
            "selection_scope": self.selection_scope,
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True, slots=True)
class CellSpec:
    variant: ExperimentVariant
    context_bucket: str
    scenario: Scenario
    seed: int
    repetition: str
    failure_schedule: FailureSchedule | None = None
    workflow_concurrency: int | None = None
    oracle_fast_path: bool = False

    def __post_init__(self) -> None:
        if self.context_bucket not in {item.name for item in CONTEXT_BUCKETS}:
            raise ValueError("unknown context bucket")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.repetition not in {"A", "B"}:
            raise ValueError("repetition must be A or B")
        if (self.scenario is Scenario.GPU_FAILURE) != (self.failure_schedule is not None):
            raise ValueError("failure cells require exactly one frozen failure schedule")
        if self.failure_schedule is not None:
            if self.failure_schedule.seed != self.seed:
                raise ValueError("failure schedule seed must match the cell seed")
            if self.failure_schedule.bucket != self.context_bucket:
                raise ValueError("failure schedule bucket must match the cell bucket")
            parameters = self.variant.parameters
            for event in self.failure_schedule.events:
                if event.detection_delay_ns != parameters.failure_detection_ns:
                    raise ValueError(
                        "failure schedule detection delay must match variant parameters"
                    )
                if event.trigger_progress_per_mille != parameters.failure_progress_per_mille:
                    raise ValueError(
                        "failure schedule trigger progress must match variant parameters"
                    )
                if event.gpu_recovery_time_ns != parameters.gpu_recovery_time_ns:
                    raise ValueError(
                        "failure schedule recovery time must match variant parameters"
                    )
        if self.workflow_concurrency is not None and (
            type(self.workflow_concurrency) is not int or self.workflow_concurrency <= 0
        ):
            raise ValueError("workflow_concurrency must be a positive integer or null")
        if type(self.oracle_fast_path) is not bool:
            raise TypeError("oracle_fast_path must be bool")
        if self.oracle_fast_path and self.variant.suite != "failure_schedule_oracle":
            raise ValueError("oracle_fast_path is restricted to failure schedule oracles")

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
    global_system_template: bool = False


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
        # Route-selected inactive HBM is read-only and may be referenced by
        # several pending requests (for example, a shared system prompt).  A
        # per-key owner set prevents eviction until every admission boundary has
        # consumed or abandoned the hit without making the content invisible to
        # later lookups.
        self._pins_by_key: dict[str, set[str]] = {}
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
        self.last_reserve_outcome = "NOT_RUN"
        self.unavailable_bytes = 0
        self.lost_committed_bytes = 0
        self.failed = False
        self._repair_capacity_bytes: int | None = None
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
            _priority, sequence, key, version = self._heap[0]
            entry = self.entries.get(key)
            if (
                entry is None
                or entry.version != version
                or entry.inserted_sequence != sequence
            ):
                heapq.heappop(self._heap)
                continue
            return entry
        return None

    def _plan_victims(
        self,
        required_bytes: int,
        *,
        incoming_score: Fraction | None = None,
    ) -> tuple[list[_PoolEntry], str]:
        """Pop a deterministic victim plan from the indexed heap transactionally."""

        if required_bytes <= 0:
            return [], "OK"
        popped: list[tuple[Fraction, int, str, int]] = []
        selected: list[_PoolEntry] = []
        released = 0
        while released < required_bytes:
            candidate: tuple[tuple[Fraction, int, str, int], _PoolEntry] | None = None
            while self._heap:
                item = heapq.heappop(self._heap)
                _priority, sequence, key, version = item
                entry = self.entries.get(key)
                if (
                    entry is None
                    or entry.version != version
                    or entry.inserted_sequence != sequence
                ):
                    continue
                if key in self._pins_by_key:
                    popped.append(item)
                    continue
                candidate = (item, entry)
                break
            if candidate is None:
                for item in popped:
                    heapq.heappush(self._heap, item)
                return [], "INSUFFICIENT"
            item, victim = candidate
            popped.append(item)
            if (
                incoming_score is not None
                and self.eviction is EvictionKind.SLACK_LANDLORD_VALUE
                and incoming_score <= victim.base_score
            ):
                for restored in popped:
                    heapq.heappush(self._heap, restored)
                return [], "VALUE_BLOCKED"
            selected.append(victim)
            released += victim.chunk.bytes
        return selected, "OK"

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

    @property
    def evictable_bytes(self) -> int:
        """Committed bytes not held by a route-to-admission source pin."""

        return sum(
            entry.chunk.bytes
            for key, entry in self.entries.items()
            if key not in self._pins_by_key
        )

    @property
    def available_entry_keys(self) -> set[str]:
        """Committed content visible to a new lookup/admission decision."""

        return set(self.entries)

    @property
    def pinned_entry_count(self) -> int:
        return len(self._pins_by_key)

    @property
    def pinned_reference_count(self) -> int:
        return sum(len(owners) for owners in self._pins_by_key.values())

    @property
    def pinned_entry_keys(self) -> frozenset[str]:
        return frozenset(self._pins_by_key)

    @property
    def pinned_bytes(self) -> int:
        return sum(
            self.entries[key].chunk.bytes
            for key in self._pins_by_key
            if key in self.entries
        )

    def release_pin(self, pin_id: str) -> int:
        """Release every committed source pin owned by one pending request."""

        if not pin_id:
            raise ExperimentError("pool pin release requires a non-empty owner")
        keys = sorted(key for key, owners in self._pins_by_key.items() if pin_id in owners)
        released = sum(self.entries[key].chunk.bytes for key in keys)
        for key in keys:
            owners = self._pins_by_key[key]
            owners.remove(pin_id)
            if not owners:
                del self._pins_by_key[key]
        return released

    def pin_interval(
        self,
        chunks: Sequence[_Chunk],
        *,
        start_token: int,
        token_count: int,
        pin_id: str,
    ) -> None:
        """Pin one committed interval until zero-copy role activation.

        This is a logical read reference, not an additional capacity charge.
        Multiple pending requests may pin one immutable content key.
        """

        if self.failed:
            raise ExperimentError("failed pool cannot pin a committed interval")
        if not pin_id or start_token < 0 or token_count <= 0:
            raise ExperimentError("pool pin identity and interval are invalid")
        end_token = start_token + token_count
        selected: list[_PoolEntry] = []
        covered_tokens = 0
        for chunk in chunks:
            chunk_end = chunk.token_start + chunk.token_count
            if chunk_end <= start_token:
                continue
            if chunk.token_start >= end_token:
                break
            if chunk.token_start < start_token:
                raise ExperimentError("pinned interval starts inside a policy chunk")
            entry = self.entries.get(chunk.key)
            if entry is None:
                raise ExperimentError(
                    "pinned interval is not committed "
                    f"(pool={self.pool_id}, key={chunk.key}, present={entry is not None}, "
                    f"pin_owners={sorted(self._pins_by_key.get(chunk.key, ()))}, "
                    f"requester={pin_id})"
                )
            selected.append(entry)
            covered_tokens += min(chunk_end, end_token) - chunk.token_start
        if covered_tokens != token_count:
            raise ExperimentError("pinned interval is not fully resident")
        for entry in selected:
            self._pins_by_key.setdefault(entry.chunk.key, set()).add(pin_id)

    def pin_keys(self, keys: Sequence[str], *, pin_id: str) -> None:
        """Acquire a shared read lease over committed physical content keys."""

        if self.failed or not pin_id or not keys or len(set(keys)) != len(keys):
            raise ExperimentError("pool read-lease identity is invalid")
        missing = [key for key in keys if key not in self.entries]
        if missing:
            raise ExperimentError("pool read lease lost committed source content")
        for key in keys:
            self._pins_by_key.setdefault(key, set()).add(pin_id)

    def activate_prefix(
        self,
        chunks: Sequence[_Chunk],
        *,
        token_count: int,
        now_ns: int,
        cause: str,
        pin_id: str | None = None,
    ) -> int:
        """Remove a committed prefix for zero-copy role reclassification."""

        return self.activate_interval(
            chunks,
            start_token=0,
            token_count=token_count,
            now_ns=now_ns,
            cause=cause,
            pin_id=pin_id,
        )

    def activate_interval(
        self,
        chunks: Sequence[_Chunk],
        *,
        start_token: int,
        token_count: int,
        now_ns: int,
        cause: str,
        pin_id: str | None = None,
    ) -> int:
        """Atomically adopt one complete committed interval without eviction.

        The same physical bytes remain resident while ownership changes from
        an inactive cache/protection role to active recovery.  The caller must
        perform the matching capacity-ledger account move.  Intervals must be
        aligned to policy-chunk boundaries so recovery sources cannot overlap
        or silently split a chunk.
        """

        if self.failed:
            raise ExperimentError("failed pool cannot activate a committed prefix")
        if start_token < 0 or token_count < 0:
            raise ExperimentError("activated interval token bounds cannot be negative")
        if token_count == 0:
            return 0
        end_token = start_token + token_count
        selected: list[_PoolEntry] = []
        covered_tokens = 0
        for chunk in chunks:
            chunk_end = chunk.token_start + chunk.token_count
            if chunk_end <= start_token:
                continue
            if chunk.token_start >= end_token:
                break
            if chunk.token_start < start_token or (
                chunk_end > end_token and pin_id is None
            ):
                raise ExperimentError("activated interval split a policy chunk boundary")
            entry = self.entries.get(chunk.key)
            if entry is None:
                raise ExperimentError("activated interval is no longer committed")
            owners = self._pins_by_key.get(chunk.key, set())
            if (pin_id is None and owners) or (
                pin_id is not None and owners != {pin_id}
            ):
                raise ExperimentError("activated interval source pin diverged")
            selected.append(entry)
            covered_tokens += min(chunk_end, end_token) - chunk.token_start
        if covered_tokens != token_count:
            raise ExperimentError("activated interval is not fully resident")
        activated_bytes = sum(entry.chunk.bytes for entry in selected)
        self._advance(now_ns)
        for entry in selected:
            self._pins_by_key.pop(entry.chunk.key, None)
            del self.entries[entry.chunk.key]
            self.occupied_bytes -= entry.chunk.bytes
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
        return activated_bytes

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

    def set_capacity_exact(
        self,
        capacity_bytes: int,
        *,
        victim_keys: tuple[str, ...],
        proposed_rent: Fraction,
        now_ns: int,
        cause: str,
    ) -> None:
        """Mirror an exact formal quota-change plan without choosing victims."""

        if self.failed:
            raise ExperimentError("failed pool cannot accept a formal quota update")
        if not 0 <= capacity_bytes <= self.physical_capacity_bytes:
            raise ExperimentError("formal pool quota is outside physical capacity")
        if len(set(victim_keys)) != len(victim_keys):
            raise ExperimentError("formal quota victims must be unique")
        selected: list[_PoolEntry] = []
        for key in victim_keys:
            entry = self.entries.get(key)
            if entry is None:
                raise ExperimentError("formal quota victim is physically absent")
            selected.append(entry)
        resulting_bytes = (
            self.occupied_bytes
            + self.pending_bytes
            - sum(entry.chunk.bytes for entry in selected)
        )
        if resulting_bytes > capacity_bytes:
            raise ExperimentError("formal quota victims do not establish capacity")
        if proposed_rent < self.rent:
            raise ExperimentError("formal quota change cannot refund rent")
        self._advance(now_ns)
        for entry in selected:
            del self.entries[entry.chunk.key]
            self.occupied_bytes -= entry.chunk.bytes
            self.evicted_chunks += 1
        self.capacity_bytes = capacity_bytes
        self.rent = proposed_rent
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": self.occupied_bytes + self.pending_bytes,
                "committed_bytes": self.occupied_bytes,
                "pending_bytes": self.pending_bytes,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": self.unavailable_bytes,
                "cause": cause if not selected else f"{cause}:FORMAL_RECLAIM",
            }
        )

    def evict_at_least(self, required_bytes: int, *, now_ns: int, cause: str) -> int:
        """Evict complete resident chunks without permanently shrinking the quota."""

        if self.failed:
            raise ExperimentError("failed pool cannot evict resident chunks")
        if required_bytes <= 0:
            return 0
        selected, status = self._plan_victims(required_bytes)
        if status != "OK":
            raise ExperimentError("pool cannot evict enough committed bytes")
        released = sum(entry.chunk.bytes for entry in selected)
        self._advance(now_ns)
        for entry in selected:
            del self.entries[entry.chunk.key]
            self.occupied_bytes -= entry.chunk.bytes
            self.evicted_chunks += 1
            self.rent = max(self.rent, entry.base_score)
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
        return released

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
            selected, status = self._plan_victims(
                required,
                incoming_score=score,
            )
            if status == "VALUE_BLOCKED":
                self.bypassed_chunks += 1
                return False
            if status != "OK":
                self.bypassed_chunks += 1
                return False

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
        self.last_reserve_outcome = "EVALUATING"
        self._advance(now_ns)
        admitted_chunks: list[_Chunk] = []
        admitted_scores: list[Fraction] = []
        evicted = 0
        alias_count = 0
        rejected_count = 0
        quoted_rent = self.rent
        for chunk, quoted_score in zip(chunks, scores, strict=True):
            unit_priority = max(Fraction(0, 1), quoted_score - quoted_rent)
            score = self.rent + unit_priority
            existing = self.entries.get(chunk.key)
            if existing is not None:
                self.alias_hits += 1
                alias_count += 1
                existing.last_access_ns = now_ns
                existing.base_score = max(existing.base_score, score)
                self._push(existing)
                continue
            if chunk.key in self._pending_keys:
                self.bypassed_chunks += 1
                rejected_count += 1
                continue
            if chunk.bytes > self.capacity_bytes:
                self.bypassed_chunks += 1
                rejected_count += 1
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
                selected, status = self._plan_victims(
                    required,
                    incoming_score=score,
                )
                if status != "OK":
                    self.bypassed_chunks += 1
                    rejected_count += 1
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
            self.last_reserve_outcome = (
                "ALIAS_ONLY"
                if alias_count > 0 and rejected_count == 0
                else "REJECTED"
            )
            return None
        reservation = _PoolReservation(
            reservation_id=reservation_id,
            chunks=tuple(admitted_chunks),
            scores=tuple(admitted_scores),
            bytes=sum(item.bytes for item in admitted_chunks),
        )
        self.pending[reservation_id] = reservation
        self.last_reserve_outcome = "RESERVED"
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

    def reserve_exact(
        self,
        reservation_id: str,
        chunk: _Chunk,
        *,
        score: Fraction,
        victim_keys: tuple[str, ...],
        proposed_rent: Fraction,
        now_ns: int,
        cause: str,
    ) -> _PoolReservation:
        """Mirror one already-approved formal SlackLandlord transaction.

        This method contains no admission policy.  The caller supplies the exact
        request-safe victims and new rent from an epoch-checked formal preview;
        this pool remains the byte/time ledger and transfer destination owner.
        """

        if self.failed:
            raise ExperimentError("failed pool cannot mirror formal admission")
        if not reservation_id or reservation_id in self.pending:
            raise ExperimentError("formal pool reservation ID is empty or duplicated")
        if chunk.key in self.entries or chunk.key in self._pending_keys:
            raise ExperimentError("formal protection chunks cannot alias")
        if len(set(victim_keys)) != len(victim_keys):
            raise ExperimentError("formal victim keys must be unique")
        selected: list[_PoolEntry] = []
        for key in victim_keys:
            entry = self.entries.get(key)
            if entry is None:
                raise ExperimentError("formal victim is absent from the physical pool")
            selected.append(entry)
        free_after = (
            self.capacity_bytes
            - self.occupied_bytes
            - self.pending_bytes
            + sum(entry.chunk.bytes for entry in selected)
        )
        if free_after < chunk.bytes:
            raise ExperimentError("formal victim set does not establish byte capacity")
        if proposed_rent < self.rent:
            raise ExperimentError("formal admission cannot refund physical rent")

        self._advance(now_ns)
        for entry in selected:
            del self.entries[entry.chunk.key]
            self.occupied_bytes -= entry.chunk.bytes
            self.evicted_chunks += 1
        self.rent = proposed_rent
        self.pending_bytes += chunk.bytes
        self._pending_keys[chunk.key] = reservation_id
        reservation = _PoolReservation(
            reservation_id=reservation_id,
            chunks=(chunk,),
            scores=(score,),
            bytes=chunk.bytes,
        )
        self.pending[reservation_id] = reservation
        self.last_reserve_outcome = "FORMAL_RESERVED"
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
                "cause": f"{cause}:FORMAL_DESTINATION_RESERVED"
                + (":EVICTED" if selected else ""),
            }
        )
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
        self._pins_by_key.clear()
        self.occupied_bytes = 0
        self._repair_capacity_bytes = self.capacity_bytes
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

    def repair(self, *, now_ns: int, cause: str) -> None:
        """Return empty physical capacity to service after a fail-stop."""

        if not self.failed or self._repair_capacity_bytes is None:
            raise ExperimentError("pool repair requires one preceding failure")
        if self.entries or self.pending or self.occupied_bytes or self.pending_bytes:
            raise ExperimentError("failed pool retained data before repair")
        self._advance(now_ns)
        self.capacity_bytes = self._repair_capacity_bytes
        self.unavailable_bytes = 0
        self.failed = False
        self._repair_capacity_bytes = None
        self.timeline.append(
            {
                "timestamp_ns": now_ns,
                "occupied_bytes": 0,
                "committed_bytes": 0,
                "pending_bytes": 0,
                "capacity_bytes": self.capacity_bytes,
                "unavailable_bytes": 0,
                "cause": cause,
            }
        )

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


class _ComputeKind(StrEnum):
    NORMAL = "NORMAL"
    RECOVERY_PROMPT = "RECOVERY_PROMPT"
    RECOVERY_SILENT = "RECOVERY_SILENT"
    RECOVERY_DECODE = "RECOVERY_DECODE"


_RECOVERY_PHASE_ORDINAL: Final = {
    _ComputeKind.RECOVERY_PROMPT: 0,
    _ComputeKind.RECOVERY_SILENT: 1,
    _ComputeKind.RECOVERY_DECODE: 2,
}


@dataclass(slots=True)
class _ComputeBooking:
    span_id: str
    route_version: int
    gpu_id: str
    kind: _ComputeKind
    ready_ns: int
    duration_ns: int
    reservation_id: str
    start_ns: int
    end_ns: int
    generation: int
    start_handle: EventHandle
    completion_handle: EventHandle
    recovery_due_ns: int | None
    started: bool = False


@dataclass(frozen=True, slots=True)
class _ComputeSpec:
    span_id: str
    route_version: int
    gpu_id: str
    kind: _ComputeKind
    ready_ns: int
    duration_ns: int
    recovery_due_ns: int | None
    prior_start_ns: int
    prior_end_ns: int
    prior_reservation_id: str


def _compute_rebook_priority_key(
    spec: _ComputeSpec, *, now_ns: int
) -> tuple[int | str, ...]:
    """Order ready recovery by decayed ideal-CPM slack, then normal work.

    A request receives one recovery due time at failure.  Prompt recompute,
    silent replay, and remaining decode all consume the same slack budget
    instead of resetting it at each phase boundary.
    """

    if now_ns < 0:
        raise ValueError("compute rebook time must be non-negative")
    if spec.kind is _ComputeKind.NORMAL:
        return (
            1,
            spec.prior_start_ns,
            spec.prior_end_ns,
            spec.span_id,
            spec.route_version,
            spec.prior_reservation_id,
        )
    if spec.recovery_due_ns is None:
        raise ValueError("recovery compute requires an ideal-CPM due time")
    remaining_slack_ns = max(0, spec.recovery_due_ns - now_ns)
    return (
        0,
        remaining_slack_ns,
        spec.recovery_due_ns,
        spec.span_id,
        spec.route_version,
        _RECOVERY_PHASE_ORDINAL[spec.kind],
        spec.prior_reservation_id,
    )


@dataclass(slots=True)
class _SpanExecution:
    metadata: NormalizedSpanMetadata
    record: Mapping[str, Any]
    chunks: tuple[_Chunk, ...]
    status: _ExecutionStatus = _ExecutionStatus.PENDING
    route_version: int = 0
    gpu_id: str | None = None
    designated_peer_gpu_id: str | None = None
    failure_source_gpu_id: str | None = None
    released_ns: int | None = None
    compute_start_ns: int | None = None
    planned_complete_ns: int | None = None
    completed_ns: int | None = None
    completion_handle: EventHandle | None = None
    hbm_allocation_handle: EventHandle | None = None
    hbm_allocated_bytes: int = 0
    hbm_allocation_gpu_id: str | None = None
    hbm_recovery_reserved_bytes: int = 0
    hbm_foreground_store_reserved_bytes: int = 0
    hbm_foreground_store_target_gpu_id: str | None = None
    hbm_staging_bytes: int = 0
    reservation_id: str | None = None
    base_duration_ns: int = 0
    scheduled_duration_ns: int = 0
    reused_primary_tokens: int = 0
    reused_peer_tokens: int = 0
    reused_store_tokens: int = 0
    recovery_normal_hbm_local_tokens: int = 0
    restored_peer_tokens: int = 0
    restored_peer_local_tokens: int = 0
    restored_peer_d2d_tokens: int = 0
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
    continuous_protection_batch_states: dict[
        tuple[int, str, int, str], _ContinuousProtectionBatchState
    ] = field(default_factory=dict)


@dataclass(slots=True)
class _ContinuousProtectionBatchState:
    outstanding_parts: int = 1
    failed: bool = False
    committed: bool = False


@dataclass(frozen=True, slots=True)
class _ContinuousFailureStep:
    span_id: str
    route_version: int
    gpu_id: str
    scheduler_step_id: str
    start_ns: int
    end_ns: int
    num_computed_tokens_before: int
    num_computed_tokens_after: int


@dataclass(slots=True)
class _PendingPutStart:
    plan_id: str
    span_id: str
    path: str
    source_gpu_id: str
    target_gpu_id: str | None
    target_store_id: str | None
    chunks: tuple[_Chunk, ...]
    handle: EventHandle
    produced_ns: int
    continuous_batch_key: tuple[int, str, int, str] | None = None
    formal_alias_waiting: bool = False


@dataclass(slots=True)
class _PendingPut:
    transfer_id: str
    span_id: str
    path: str
    source_gpu_id: str
    target_gpu_id: str | None
    target_store_id: str | None
    chunks: tuple[_Chunk, ...]
    scores: tuple[Fraction, ...]
    task: TransferTask
    handle: EventHandle | None
    started: bool
    pool_reservation_ids: tuple[str, ...]
    bytes: int
    policy_candidate_count: int
    continuous_batch_key: tuple[int, str, int, str] | None = None
    formal_chunk_ids: tuple[str, ...] = ()
    formal_preview_audits: tuple[dict[str, object], ...] = ()
    formal_block_after_resolution: bool = False


@dataclass(frozen=True, slots=True)
class _FormalChunkMetadata:
    chunk_id: str
    span_id: str
    path: str
    pool_id: str
    physical_chunk: _Chunk
    global_sequence_index: int
    pool_sequence_index: int


class _LazyFormalLatestValues(Mapping[str, RentalValue]):
    """Compute exact lazy-refresh values only when SlackLandlord requests one."""

    def __init__(
        self,
        chunk_ids: tuple[str, ...],
        resolver: Callable[[str], RentalValue],
    ) -> None:
        self._chunk_ids = chunk_ids
        self._chunk_id_set = frozenset(chunk_ids)
        self._resolver = resolver
        self._cache: dict[str, RentalValue] = {}

    def __getitem__(self, chunk_id: str) -> RentalValue:
        if chunk_id not in self._chunk_id_set:
            raise KeyError(chunk_id)
        if chunk_id not in self._cache:
            self._cache[chunk_id] = self._resolver(chunk_id)
        return self._cache[chunk_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._chunk_ids)

    def __len__(self) -> int:
        return len(self._chunk_ids)


@dataclass(slots=True)
class _PendingRecoveryTransfer:
    transfer_id: str
    span_id: str
    source: str
    source_gpu_id: str
    target_gpu_id: str
    task: TransferTask
    handle: EventHandle
    bytes: int
    staging_bytes: int


@dataclass(slots=True)
class _PendingForegroundStoreTransfer:
    transfer_id: str
    span_id: str
    source_store_id: str
    target_gpu_id: str
    task: TransferTask
    handle: EventHandle | None
    bytes: int
    source_chunk_keys: tuple[str, ...]


@dataclass(slots=True)
class _ForegroundStoreRestoreGroup:
    span_id: str
    route_version: int
    target_gpu_id: str
    restored_tokens: int
    scheduled_duration_ns: int
    reserved_bytes: int
    transfer_ids: set[str]
    completed_transfer_ids: set[str] = field(default_factory=set)
    completion_handle: EventHandle | None = None
    adopted_bytes: int = 0


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
        workflow_concurrency: int | None,
        oracle_fast_path: bool = False,
    ) -> None:
        self.records = tuple(records)
        self.variant = variant
        self.context_bucket = context_bucket
        self.profile = variant.profile
        self.parameters = variant.parameters
        self.seed = seed
        self.failure_schedule = failure_schedule
        self._failure_schedule_by_id = (
            {}
            if failure_schedule is None
            else {event.failure_id: event for event in failure_schedule.events}
        )
        self._failure_schedule_by_focus_span = (
            {}
            if failure_schedule is None
            else {event.focus_span_id: event for event in failure_schedule.events}
        )
        self.workflow_concurrency = workflow_concurrency
        self.oracle_fast_path = oracle_fast_path
        self.des = GlobalDES()
        self.trace = load_normalized_trace_records(records)
        self.algorithm1_cpm = compute_ideal_trace_cpm(self.trace.spans)
        self.aimd_control_window_ns = max(
            AIMD_CONTROL_WINDOW_MIN_NS,
            _integer_median(
                list(self.algorithm1_cpm.workflow_makespan_ns.values())
            ),
        )
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
        self.store_segment_ids = tuple(
            f"store-{index}:segment-0"
            for index in range(self.parameters.store_node_count)
        )
        self.store_rate_ids = {
            segment_id: {
                "dram": f"store-{index}.dram-rate",
                "rdma_fabric": (
                    "store-fabric-rate"
                    if self.parameters.store_node_count == 1
                    else f"store-{index}.fabric-rate"
                ),
                "tcp_fabric": (
                    "store-tcp-fabric-rate"
                    if self.parameters.store_node_count == 1
                    else f"store-{index}.tcp-fabric-rate"
                ),
            }
            for index, segment_id in enumerate(self.store_segment_ids)
        }
        self.failed_gpu_ids: set[str] = set()
        hbm_initial_accounts = {
            HBM_MODEL_WEIGHTS_ACCOUNT: self.parameters.model_weights_bytes_per_gpu,
            HBM_RUNTIME_FIXED_ACCOUNT: self.parameters.runtime_fixed_bytes_per_gpu,
            HBM_RUNTIME_DYNAMIC_ACCOUNT: 0,
            HBM_ACTIVE_PRIMARY_ACCOUNT: 0,
            HBM_INACTIVE_REUSABLE_ACCOUNT: 0,
            HBM_PEER_PROTECTION_ACCOUNT: 0,
            HBM_PEER_PENDING_ACCOUNT: 0,
            HBM_RECOVERY_RESERVED_ACCOUNT: 0,
            HBM_FOREGROUND_STORE_RESERVED_ACCOUNT: 0,
            HBM_TRANSFER_STAGING_ACCOUNT: 0,
            HBM_FRAGMENTATION_ACCOUNT: 0,
            HBM_UNATTRIBUTED_ACCOUNT: 0,
            UNAVAILABLE_CAPACITY_ACCOUNT: 0,
        }
        self.hbm_ledgers = {
            gpu_id: CapacityLedger(
                resource_id=f"hbm:{gpu_id}",
                resource_kind=CapacityResourceKind.GPU_HBM,
                capacity_bytes=self.parameters.physical_hbm_bytes_per_gpu,
                initial_accounts=hbm_initial_accounts,
            )
            for gpu_id in self.gpu_ids
        }
        self.hbm_timelines = {
            gpu_id: [
                _capacity_ledger_snapshot(
                    ledger,
                    timestamp_ns=0,
                    cause="INITIAL_HBM_ACCOUNTS",
                )
            ]
            for gpu_id, ledger in sorted(self.hbm_ledgers.items())
        }
        self.host_staging_ledgers = {
            gpu_id: CapacityLedger(
                resource_id=f"host:{gpu_id}",
                resource_kind=CapacityResourceKind.HOST_DRAM,
                capacity_bytes=self.parameters.host_staging_capacity_bytes_per_node,
                initial_accounts={HOST_TRANSFER_STAGING_ACCOUNT: 0},
            )
            for gpu_id in self.gpu_ids
        }
        self.host_staging_timelines = {
            gpu_id: [
                _capacity_ledger_snapshot(
                    ledger,
                    timestamp_ns=0,
                    cause="INITIAL_HOST_DRAM_ACCOUNTS",
                )
            ]
            for gpu_id, ledger in sorted(self.host_staging_ledgers.items())
        }
        self.compute = {
            gpu_id: ConcurrencyResource(resource_id=f"{gpu_id}.compute", lanes=1)
            for gpu_id in self.gpu_ids
        }
        self._compute_bookings_by_span: dict[str, _ComputeBooking] = {}
        self._compute_booking_generations: defaultdict[str, int] = defaultdict(int)
        self.compute_rebook_events: list[dict[str, Any]] = []
        hbm_path_rate = float(
            max(
                self.parameters.peer_bandwidth_bytes_per_second,
                self.parameters.store_bandwidth_bytes_per_second,
            )
        )
        store_rate_resources: dict[str, RateResource] = {}
        for rate_ids in self.store_rate_ids.values():
            for key, resource_id in rate_ids.items():
                capacity = (
                    self.parameters.tcp_store_bandwidth_bytes_per_second
                    if key == "tcp_fabric"
                    else self.parameters.store_bandwidth_bytes_per_second
                )
                store_rate_resources.setdefault(
                    resource_id,
                    RateResource(
                        resource_id=resource_id,
                        capacity_bytes_per_second=float(capacity),
                    ),
                )
        self.transfer_rate_resources = {
            **{
                f"{gpu_id}.hbm-rate": RateResource(
                    resource_id=f"{gpu_id}.hbm-rate",
                    capacity_bytes_per_second=hbm_path_rate,
                )
                for gpu_id in self.gpu_ids
            },
            **{
                f"{gpu_id}.host-rate": RateResource(
                    resource_id=f"{gpu_id}.host-rate",
                    capacity_bytes_per_second=float(
                        self.parameters.host_staging_bandwidth_bytes_per_second
                    ),
                )
                for gpu_id in self.gpu_ids
            },
            "peer-fabric-rate": RateResource(
                resource_id="peer-fabric-rate",
                capacity_bytes_per_second=float(
                    self.parameters.peer_bandwidth_bytes_per_second
                ),
            ),
            **store_rate_resources,
        }
        self.flow_model = FlowContentionModel(
            [
                resource
                for _, resource in sorted(self.transfer_rate_resources.items())
            ]
        )
        self.transfer_runtime = TransferRuntime(
            controller=FlowDESController(des=self.des, model=self.flow_model)
        )
        initial_peer_quota = (
            self.parameters.peer_hbm_quota_bytes_per_gpu
            if self.profile.peer_replication_fraction > 0
            else 0
        )
        self.peer_pools = {
            gpu_id: _ModeledPool(
                pool_id=f"PEER_HBM:{gpu_id}",
                capacity_bytes=initial_peer_quota,
                physical_capacity_bytes=self.parameters.kv_capacity_bytes_per_gpu,
                eviction=self.profile.eviction,
                seed=seed,
            )
            for gpu_id in self.gpu_ids
        }
        normal_hbm_capacity = self.parameters.kv_capacity_bytes_per_gpu
        self.primary_pools = {
            gpu_id: _ModeledPool(
                pool_id=f"NORMAL_HBM:{gpu_id}",
                capacity_bytes=normal_hbm_capacity,
                physical_capacity_bytes=normal_hbm_capacity,
                eviction=EvictionKind.LRU,
                seed=seed,
            )
            for gpu_id in self.gpu_ids
        }
        base_store_capacity, extra_store_bytes = divmod(
            self.parameters.store_budget_bytes,
            self.parameters.store_node_count,
        )
        self.store_pools = {
            segment_id: _ModeledPool(
                pool_id=f"STORE_DRAM:{segment_id}",
                capacity_bytes=base_store_capacity + (index < extra_store_bytes),
                eviction=self.profile.eviction,
                seed=seed,
            )
            for index, segment_id in enumerate(self.store_segment_ids)
        }
        self.formal_landlords: dict[str, SlackLandlord] = {}
        if (
            self.profile.eviction is EvictionKind.SLACK_LANDLORD_VALUE
            and self.profile.unified_manager
        ):
            self.formal_landlords.update(
                {
                    pool.pool_id: SlackLandlord(
                        pool=PolicyPool.PEER_HBM,
                        capacity_bytes=pool.capacity_bytes,
                    )
                    for pool in self.peer_pools.values()
                }
            )
            self.formal_landlords.update(
                {
                    pool.pool_id: SlackLandlord(
                        pool=PolicyPool.STORE_DRAM,
                        capacity_bytes=pool.capacity_bytes,
                    )
                    for pool in self.store_pools.values()
                }
            )
        self._formal_chunk_metadata: dict[str, _FormalChunkMetadata] = {}
        self._formal_content_alias_locations: dict[
            tuple[str, str, int], tuple[str, str]
        ] = {}
        self._formal_request_ids_by_pool: defaultdict[str, set[str]] = defaultdict(set)
        self._formal_dirty_pool_ids: set[str] = set()
        self._formal_active_request_paths: set[tuple[str, str]] = set()
        self._formal_waiting_put_starts: defaultdict[
            tuple[str, str], list[_PendingPutStart]
        ] = defaultdict(list)
        self._formal_content_alias_waiters: defaultdict[
            tuple[str, str], list[_PendingPutStart]
        ] = defaultdict(list)
        self._formal_blocked_request_paths: set[tuple[str, str]] = set()
        self.formal_policy_events: list[dict[str, object]] = []
        self._published_slack: dict[str, SlackSignal] = {}
        self._published_slack_history: dict[str, list[SlackSignal]] = {}
        self.slack_update_events: list[dict[str, object]] = []
        self.aimd = HBMQuotaAIMD(AIMD_PARAMETERS)
        self.aimd_states = {
            gpu_id: AIMDTargetState(
                target_id=gpu_id,
                peer_hbm_capacity_bytes=self.parameters.kv_capacity_bytes_per_gpu,
                protection_fraction=self.parameters.peer_hbm_alpha,
            )
            for gpu_id in self.gpu_ids
            if self.profile.peer_replication_fraction > 0
        }
        self.aimd_events: list[dict[str, Any]] = []
        self._aimd_last_decisions: dict[str, AIMDDecision] = {}
        self._aimd_window_handles: dict[str, EventHandle] = {}
        self._aimd_pending_pressure = {
            gpu_id: False for gpu_id in self.aimd_states
        }
        self._aimd_pending_shortfall_bytes = {
            gpu_id: 0 for gpu_id in self.aimd_states
        }
        self._aimd_pending_pressure_active_requests = {
            gpu_id: 0 for gpu_id in self.aimd_states
        }
        self._aimd_pending_pressure_reasons: dict[str, set[str]] = {
            gpu_id: set() for gpu_id in self.aimd_states
        }
        self.hbm_pressure_observations: list[dict[str, Any]] = []
        self.scheduler_preemption_events: list[dict[str, Any]] = []
        self.route_events: list[dict[str, Any]] = []
        self.cache_aware_route_evaluations = 0
        self.cache_aware_route_changes = 0
        self.protection_path_bypasses: Counter[str] = Counter()
        self.protection_path_alias_noops: Counter[str] = Counter()
        self.continuous_batch_enabled = all(
            _exact_prompt_token_ids(record) is not None for record in self.records
        )
        self.continuous_hbm_authorities: dict[str, ExperimentHBMAuthority] = {}
        self.continuous_batch_driver: AegisContinuousBatchDESDriver | None = None
        self._continuous_duration_profile: PredictionProfile | None = None
        self._continuous_trace_provenance_sha256: str | None = None
        self._continuous_logical_block_capacity = 0
        if self.continuous_batch_enabled:
            prediction_profile = self._continuous_prediction_profile()
            self._continuous_duration_profile = prediction_profile
            self._continuous_trace_provenance_sha256 = sha256_json(
                {
                    "span_durations": [
                        [
                            span.metadata.span_id,
                            span.metadata.recorded_api_time_ns,
                            span.metadata.prompt_tokens,
                            span.metadata.output_tokens,
                        ]
                        for span in sorted(
                            self.executions.values(),
                            key=lambda item: item.metadata.stable_sort_key,
                        )
                    ]
                }
            )
            bridges: list[AegisSchedulerStepBridge] = []
            logical_pages_per_source_chunk = SOURCE_BLOCK_TOKENS // 16
            logical_block_capacity = (
                self.parameters.kv_capacity_bytes_per_gpu
                // KV_BYTES_PER_SOURCE_BLOCK
                * logical_pages_per_source_chunk
            )
            if logical_block_capacity <= 1:
                raise ExperimentError("continuous scheduler has no usable logical HBM pages")
            self._continuous_logical_block_capacity = logical_block_capacity
            for gpu_id in self.gpu_ids:
                authority = self._new_continuous_hbm_authority(gpu_id)
                self.continuous_hbm_authorities[gpu_id] = authority
                bridges.append(self._new_continuous_bridge(gpu_id, authority))
            self.continuous_batch_driver = AegisContinuousBatchDESDriver(
                des=self.des,
                bridges=tuple(bridges),
                register_failure_handler=False,
                on_before_admit=self._on_continuous_before_admit,
                on_after_admit=self._on_continuous_after_admit,
                on_admit_abort=self._on_continuous_admit_abort,
                on_step_started=self._on_continuous_step_started,
                on_step_completed=self._on_continuous_step_completed,
                on_maintenance_step=self._on_continuous_maintenance_step,
            )
        self.causal = CausalReleaseEngine(
            self.trace,
            self.des,
            on_release=self._on_release,
            workflow_concurrency=workflow_concurrency,
        )
        self.pending_put_starts: dict[str, _PendingPutStart] = {}
        self.pending_puts: dict[str, _PendingPut] = {}
        self.pending_recovery_transfers: dict[str, _PendingRecoveryTransfer] = {}
        self.recovery_transfer_ids_by_span: dict[str, set[str]] = {}
        self.pending_foreground_store_transfers: dict[
            str, _PendingForegroundStoreTransfer
        ] = {}
        self.foreground_store_restore_by_span: dict[
            str, _ForegroundStoreRestoreGroup
        ] = {}
        self.active_host_staging: dict[str, tuple[str, int]] = {}
        self.active_source_pins: dict[str, dict[str, Any]] = {}
        self.source_pin_acquire_count = 0
        self.host_staging_acquire_count = 0
        self.transfers: list[dict[str, Any]] = []
        self._transfer_by_id: dict[str, dict[str, Any]] = {}
        self._pending_transfer_ledger_ids: set[str] = set()
        self._terminal_transfer_ledger_ids: set[str] = set()
        self._dirty_terminal_transfer_ledger_ids: set[str] = set()
        self.failure_events: list[dict[str, Any]] = []
        self.recovery_events: list[dict[str, Any]] = []
        self.recovery_source_events: list[dict[str, Any]] = []
        self.foreground_store_events: list[dict[str, Any]] = []
        self._failure_event_handles: dict[str, EventHandle] = {}
        self._continuous_failure_active_steps: dict[
            str, _ContinuousFailureStep
        ] = {}
        self._continuous_failure_crossing_evidence: dict[
            str, dict[str, object]
        ] = {}
        self._failure_event_executed: set[str] = set()
        self._resolved_failure_targets: dict[str, str] = {}
        self._repair_event_executed: set[str] = set()
        self._event_sequence = 0
        self._completed_span_ids: set[str] = set()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.des.register_handler(EventKind.KV_BLOCK_ALLOCATE, self._on_hbm_primary_allocate)
        self.des.register_handler(
            EventKind.RESOURCE_RESERVE, self._on_recovery_compute_start
        )
        self.des.register_handler(EventKind.CONTROL_WINDOW, self._on_aimd_control_window)
        self.des.register_handler(EventKind.REQUEST_COMPLETE, self._on_request_complete)
        self.des.register_handler(EventKind.PUT_START, self._on_put_start)
        self.des.register_handler(EventKind.TRANSFER_START, self._on_transfer_start)
        self.des.register_handler(EventKind.PUT_COMMIT, self._on_put_commit)
        self.des.register_handler(
            EventKind.GET_START,
            self._on_foreground_store_get_start,
        )
        self.des.register_handler(
            EventKind.GET_COMPLETE,
            self._on_foreground_store_get_complete,
        )
        self.des.register_handler(EventKind.FAILURE_INJECT, self._on_failure_inject)
        self.des.register_handler(EventKind.FAILURE_DETECT, self._on_failure_detect)
        self.des.register_handler(EventKind.REPAIR_COMPLETE, self._on_repair_complete)
        self.des.register_handler(EventKind.RECOVERY_START, self._on_recovery_start)
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
            for schedule in self.failure_schedule.events:
                if schedule.focus_span_id not in self.executions:
                    raise ExperimentError(
                        "failure focus span is absent from the frozen workload"
                    )
        if self.profile.aimd_enabled:
            for gpu_id in sorted(self.aimd_states):
                self._schedule_next_aimd_control_window(
                    gpu_id,
                    at_ns=self.des.now_ns + self.aimd_control_window_ns,
                )
        self.causal.start()
        progress_text = os.environ.get("MOONKVSIM_PROGRESS_EVERY_EVENTS", "").strip()
        progress_every_events = int(progress_text) if progress_text else None
        if progress_every_events is not None and progress_every_events <= 0:
            raise ExperimentError("MOONKVSIM_PROGRESS_EVERY_EVENTS must be positive")
        progress_started = time.monotonic()
        last_progress_completed = len(self._completed_span_ids)
        stagnant_progress_windows = 0
        stagnant_limit_text = os.environ.get(
            "MOONKVSIM_MAX_STAGNANT_PROGRESS_WINDOWS", ""
        ).strip()
        stagnant_progress_limit = int(stagnant_limit_text) if stagnant_limit_text else None
        if stagnant_progress_limit is not None and stagnant_progress_limit <= 0:
            raise ExperimentError(
                "MOONKVSIM_MAX_STAGNANT_PROGRESS_WINDOWS must be positive"
            )

        def report_progress(des: GlobalDES, executed_events: int) -> None:
            nonlocal last_progress_completed, stagnant_progress_windows
            rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            completed = len(self._completed_span_ids)
            if completed == last_progress_completed:
                stagnant_progress_windows += 1
            else:
                stagnant_progress_windows = 0
                last_progress_completed = completed
            status_counts = Counter(item.status.value for item in self.executions.values())
            scheduler_queues = {
                gpu_id: {
                    "running": len(authority.active_request_ids),
                    "waiting": len(
                        self.continuous_batch_driver._targets[
                            gpu_id
                        ].bridge.scheduler.waiting_request_ids
                    )
                    if self.continuous_batch_driver is not None
                    else 0,
                }
                for gpu_id, authority in self.continuous_hbm_authorities.items()
            }
            scheduler_empty = all(
                item["running"] == 0 and item["waiting"] == 0
                for item in scheduler_queues.values()
            )
            live_execution_count = sum(
                status_counts.get(status.value, 0)
                for status in (
                    _ExecutionStatus.QUEUED,
                    _ExecutionStatus.RUNNING,
                    _ExecutionStatus.RECOVERING,
                    _ExecutionStatus.RESUMED,
                )
            )
            print(
                "[MoonKVSim progress] "
                f"events={executed_events} sim_ns={des.now_ns} "
                f"completed={completed}/{len(self.executions)} "
                f"pending={des.pending_count} journal={des.journal.record_count} "
                f"statuses={dict(sorted(status_counts.items()))} "
                f"scheduler_queues={scheduler_queues} "
                f"stagnant_windows={stagnant_progress_windows} "
                f"rss_mib={rss_kib / 1024:.1f} "
                f"wall_s={time.monotonic() - progress_started:.1f}",
                file=sys.stderr,
                flush=True,
            )
            if (
                stagnant_progress_limit is not None
                and stagnant_progress_windows >= stagnant_progress_limit
                and completed * 10 >= len(self.executions) * 9
            ):
                incomplete = {
                    item.metadata.span_id: {
                        "status": item.status.value,
                        "gpu_id": item.gpu_id,
                        "route_version": item.route_version,
                        "failure_at_ns": item.failure_at_ns,
                        "recovery_ready_ns": item.recovery_ready_ns,
                        "resume_decode_start_ns": item.resume_decode_start_ns,
                        "hbm_allocated_bytes": item.hbm_allocated_bytes,
                    }
                    for item in self.executions.values()
                    if item.metadata.span_id not in self._completed_span_ids
                }
                raise ExperimentError(
                    "continuous workload made no completion progress across "
                    f"{stagnant_progress_windows} progress windows: "
                    f"statuses={dict(sorted(status_counts.items()))}, "
                    f"scheduler_empty={scheduler_empty}, "
                    f"live_execution_count={live_execution_count}, "
                    f"scheduler_queues={scheduler_queues}, "
                    f"incomplete={incomplete}"
                )

        self.des.run(
            progress_every_events=progress_every_events,
            on_progress=report_progress if progress_every_events is not None else None,
        )
        continuous_batch_result: dict[str, object] | None = None
        if self.continuous_batch_enabled:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("continuous study lost its scheduler driver")
            driver_result = driver.run()
            if driver_result.finished_at_ns != self.des.now_ns:
                raise ExperimentError("continuous scheduler result lost the global clock")
            continuous_batch_result = driver_result.to_dict()
        if self.failure_schedule is not None:
            expected_failure_ids = set(self._failure_schedule_by_id)
            if set(self._failure_event_handles) != expected_failure_ids or (
                self._failure_event_executed != expected_failure_ids
            ):
                raise ExperimentError(
                    "logical failure triggers were not all scheduled and executed"
                )
            if set(self._resolved_failure_targets) != expected_failure_ids:
                raise ExperimentError("logical failures lost their runtime-resolved targets")
            expected_repair_ids = {
                schedule.failure_id
                for schedule in self.failure_schedule.events
                if schedule.gpu_recovery_time_ns is not None
            }
            if self._repair_event_executed != expected_repair_ids:
                raise ExperimentError("scheduled GPU repairs did not all execute")
        if len(self._completed_span_ids) != len(self.executions):
            missing = sorted(set(self.executions) - self._completed_span_ids)
            raise ExperimentError(f"study left spans incomplete: {missing[:5]}")
        if self.continuous_batch_driver is not None:
            for target_id, target in sorted(
                self.continuous_batch_driver._targets.items()
            ):
                try:
                    target.bridge.scheduler.audit()
                except Exception as error:
                    raise ExperimentError(
                        f"final continuous scheduler audit failed on {target_id}"
                    ) from error
        if (
            self._continuous_failure_active_steps
            or self._continuous_failure_crossing_evidence
        ):
            raise ExperimentError("study ended with unresolved continuous failure evidence")
        if self._compute_bookings_by_span:
            raise ExperimentError("study ended with live compute bookings")
        for execution in self.executions.values():
            self._formal_drop_waiting_suffixes(
                execution.metadata.span_id,
                reason="STUDY_END",
            )
        if (
            self.pending_put_starts
            or self.pending_puts
            or self._formal_active_request_paths
            or self._formal_waiting_put_starts
            or self._formal_content_alias_waiters
            or self.pending_recovery_transfers
            or self.recovery_transfer_ids_by_span
            or self.pending_foreground_store_transfers
            or self.foreground_store_restore_by_span
            or self.active_host_staging
            or self.active_source_pins
            or any(
                record.get("status") == "PENDING" for record in self.transfers
            )
        ):
            raise ExperimentError("study ended with a non-terminal transfer")
        self._validate_all_transfer_records()
        self.transfer_runtime.audit()
        if self.flow_model.flows or self.transfer_runtime.active_flow_ids:
            raise ExperimentError("study ended with an active fluid flow")
        if any(
            pool.pending or pool.pending_bytes
            for pool in (
                *self.primary_pools.values(),
                *self.peer_pools.values(),
                *self.store_pools.values(),
            )
        ):
            raise ExperimentError("study ended with a pending destination reservation")
        if any(
            pool.pinned_entry_count
            for pool in (*self.primary_pools.values(), *self.store_pools.values())
        ):
            raise ExperimentError("study ended with an unconsumed HBM/Store source pin")
        nonterminal_protection_batches = [
            (execution.metadata.span_id, key, state)
            for execution in self.executions.values()
            for key, state in execution.continuous_protection_batch_states.items()
            if not state.committed
            or state.failed
            or state.outstanding_parts != 0
        ]
        if nonterminal_protection_batches:
            raise ExperimentError(
                "study ended with a non-terminal continuous protection batch"
            )
        if any(landlord.pending_bytes for landlord in self.formal_landlords.values()):
            raise ExperimentError("study ended with a formal pending admission")
        end_ns = self.des.now_ns
        for pool in (*self.primary_pools.values(), *self.peer_pools.values()):
            pool.finalize(end_ns)
        for pool in self.store_pools.values():
            pool.finalize(end_ns)
        payload = self._payload(end_ns)
        representative = {
            "failure_events": self.failure_events,
            "recovery_events": self.recovery_events,
            "recovery_source_events": self.recovery_source_events,
            "foreground_store_events": self.foreground_store_events,
            "compute_rebook_events": self.compute_rebook_events,
            "transfers": self.transfers,
            "flow_rate_intervals": [
                _flow_interval_to_dict(item) for item in self.flow_model.intervals
            ],
            "gpu_hbm_timelines": {
                gpu_id: timeline
                for gpu_id, timeline in sorted(self.hbm_timelines.items())
            },
            "host_dram_timelines": {
                gpu_id: timeline
                for gpu_id, timeline in sorted(self.host_staging_timelines.items())
            },
            "peer_hbm_timeline": _aggregate_pool_timeline(self.peer_pools),
            "peer_hbm_timelines": {
                gpu_id: pool.timeline for gpu_id, pool in sorted(self.peer_pools.items())
            },
            "normal_hbm_timelines": {
                gpu_id: pool.timeline
                for gpu_id, pool in sorted(self.primary_pools.items())
            },
            "store_dram_timeline": _aggregate_pool_timeline(self.store_pools),
            "store_dram_timelines": {
                segment_id: pool.timeline
                for segment_id, pool in sorted(self.store_pools.items())
            },
            "aimd_events": self.aimd_events,
            "hbm_pressure_observations": self.hbm_pressure_observations,
            "scheduler_preemption_events": self.scheduler_preemption_events,
            "route_events": self.route_events,
            "algorithm1_cpm": {
                span_id: {
                    "agent_id": timing.agent_id,
                    "critical": timing.critical,
                    "duration_ns": timing.duration_ns,
                    "earliest_start_ns": timing.earliest_start_ns,
                    "earliest_finish_ns": timing.earliest_finish_ns,
                    "latest_start_ns": timing.latest_start_ns,
                    "latest_finish_ns": timing.latest_finish_ns,
                    "slack_ns": timing.slack_ns,
                    "workflow_id": timing.workflow_id,
                }
                for span_id, timing in sorted(self.algorithm1_cpm.timings.items())
            },
            "algorithm1_slack_updates": self.slack_update_events,
            "formal_algorithm2_events": self.formal_policy_events,
            "continuous_batch_scheduler": continuous_batch_result,
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
        expected_hbm_accounts = {
            HBM_MODEL_WEIGHTS_ACCOUNT,
            HBM_RUNTIME_FIXED_ACCOUNT,
            HBM_RUNTIME_DYNAMIC_ACCOUNT,
            HBM_ACTIVE_PRIMARY_ACCOUNT,
            HBM_INACTIVE_REUSABLE_ACCOUNT,
            HBM_PEER_PROTECTION_ACCOUNT,
            HBM_PEER_PENDING_ACCOUNT,
            HBM_RECOVERY_RESERVED_ACCOUNT,
            HBM_FOREGROUND_STORE_RESERVED_ACCOUNT,
            HBM_TRANSFER_STAGING_ACCOUNT,
            HBM_FRAGMENTATION_ACCOUNT,
            HBM_UNATTRIBUTED_ACCOUNT,
            FREE_ACCOUNT,
            UNAVAILABLE_CAPACITY_ACCOUNT,
        }
        for gpu_id, ledger in self.hbm_ledgers.items():
            accounts = ledger.accounts
            if set(accounts) != expected_hbm_accounts:
                raise ExperimentError(f"HBM account stack is incomplete on {gpu_id}")
            if sum(accounts.values()) != ledger.capacity_bytes:
                raise ExperimentError(f"HBM account stack does not conserve on {gpu_id}")
            if accounts[HBM_UNATTRIBUTED_ACCOUNT] != 0:
                raise ExperimentError(f"HBM unattributed reserve is nonzero on {gpu_id}")
            if gpu_id in self.failed_gpu_ids:
                if accounts[UNAVAILABLE_CAPACITY_ACCOUNT] != ledger.capacity_bytes:
                    raise ExperimentError(f"failed GPU HBM is not unavailable on {gpu_id}")
            else:
                if accounts[UNAVAILABLE_CAPACITY_ACCOUNT] != 0:
                    raise ExperimentError(f"healthy GPU HBM is unavailable on {gpu_id}")
                pool = self.peer_pools[gpu_id]
                if (
                    accounts[HBM_PEER_PROTECTION_ACCOUNT] != pool.occupied_bytes
                    or accounts[HBM_PEER_PENDING_ACCOUNT] != pool.pending_bytes
                ):
                    raise ExperimentError(f"Peer-HBM pool and ledger diverged on {gpu_id}")
                primary_pool = self.primary_pools[gpu_id]
                if accounts[HBM_INACTIVE_REUSABLE_ACCOUNT] != primary_pool.occupied_bytes:
                    raise ExperimentError(
                        f"normal HBM prefix pool and ledger diverged on {gpu_id}"
                    )
            active_primary = sum(
                item.hbm_allocated_bytes
                for item in self.executions.values()
                if item.hbm_allocation_gpu_id == gpu_id
            )
            recovery_reserved = sum(
                item.hbm_recovery_reserved_bytes
                for item in self.executions.values()
                if item.hbm_allocation_gpu_id == gpu_id
            )
            foreground_store_reserved = sum(
                item.hbm_foreground_store_reserved_bytes
                for item in self.executions.values()
                if item.hbm_foreground_store_target_gpu_id == gpu_id
            )
            staging = sum(
                item.hbm_staging_bytes
                for item in self.executions.values()
                if item.hbm_allocation_gpu_id == gpu_id
            )
            if accounts[HBM_ACTIVE_PRIMARY_ACCOUNT] != active_primary:
                owners = {
                    item.metadata.span_id: {
                        "bytes": item.hbm_allocated_bytes,
                        "status": item.status.value,
                        "gpu_id": item.gpu_id,
                    }
                    for item in self.executions.values()
                    if item.hbm_allocation_gpu_id == gpu_id
                    and item.hbm_allocated_bytes > 0
                }
                authority_bytes = self.continuous_hbm_authorities[
                    gpu_id
                ].active_physical_bytes
                raise ExperimentError(
                    "active primary-HBM ownership diverged on "
                    f"{gpu_id}: ledger={accounts[HBM_ACTIVE_PRIMARY_ACCOUNT]}, "
                    f"executions={active_primary}, authority={authority_bytes}, "
                    f"owners={owners}"
                )
            if accounts[HBM_RECOVERY_RESERVED_ACCOUNT] != recovery_reserved:
                raise ExperimentError(f"recovery reserve ownership diverged on {gpu_id}")
            if (
                accounts[HBM_FOREGROUND_STORE_RESERVED_ACCOUNT]
                != foreground_store_reserved
            ):
                raise ExperimentError(
                    f"foreground Store reserve ownership diverged on {gpu_id}"
                )
            if accounts[HBM_TRANSFER_STAGING_ACCOUNT] != staging:
                raise ExperimentError(f"transfer staging ownership diverged on {gpu_id}")
            if self.hbm_timelines[gpu_id][-1]["accounts"] != accounts:
                raise ExperimentError(f"HBM event-boundary timeline is stale on {gpu_id}")
        active_staging_by_resource: Counter[str] = Counter()
        for resource_id, staging_bytes in self.active_host_staging.values():
            active_staging_by_resource[resource_id] += staging_bytes
        for gpu_id, ledger in self.host_staging_ledgers.items():
            accounts = ledger.accounts
            if set(accounts) != {HOST_TRANSFER_STAGING_ACCOUNT, FREE_ACCOUNT}:
                raise ExperimentError(f"Host DRAM account stack is incomplete on {gpu_id}")
            if sum(accounts.values()) != ledger.capacity_bytes:
                raise ExperimentError(f"Host DRAM account stack does not conserve on {gpu_id}")
            if accounts[HOST_TRANSFER_STAGING_ACCOUNT] != active_staging_by_resource[
                ledger.resource_id
            ]:
                raise ExperimentError(f"Host staging ownership diverged on {gpu_id}")
            if self.host_staging_timelines[gpu_id][-1]["accounts"] != accounts:
                raise ExperimentError(
                    f"Host DRAM event-boundary timeline is stale on {gpu_id}"
                )
        active_transfer_ids = {
            transfer_id
            for transfer_id, pending in self.pending_puts.items()
            if pending.started and pending.task.status is TransferStatus.PENDING
        } | {
            transfer_id
            for transfer_id, pending in self.pending_recovery_transfers.items()
            if pending.task.status is TransferStatus.PENDING
        } | {
            transfer_id
            for transfer_id, pending in self.pending_foreground_store_transfers.items()
            if pending.task.status is TransferStatus.PENDING
        }
        if set(self.active_source_pins) != active_transfer_ids:
            raise ExperimentError("source pin ownership diverged from active transfers")
        if set(self.active_host_staging) - set(self.active_source_pins):
            raise ExperimentError("Host staging exists without a source pin")
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
        for gpu_id, pool in self.primary_pools.items():
            if pool.pending or pool.pending_bytes:
                raise ExperimentError(f"normal HBM prefix pool has pending bytes on {gpu_id}")
            if pool.occupied_bytes > pool.capacity_bytes:
                raise ExperimentError(f"normal HBM prefix pool exceeded quota on {gpu_id}")
            if gpu_id in self.failed_gpu_ids:
                if not pool.failed or pool.occupied_bytes != 0:
                    raise ExperimentError(
                        f"failed normal HBM prefix pool is inconsistent on {gpu_id}"
                    )
            elif pool.failed or pool.unavailable_bytes != 0:
                raise ExperimentError(
                    f"healthy normal HBM prefix pool is unavailable on {gpu_id}"
                )
        for segment_id, pool in self.store_pools.items():
            if pool.occupied_bytes + pool.pending_bytes > pool.capacity_bytes:
                raise ExperimentError(
                    f"Store DRAM capacity invariant failed on {segment_id}"
                )
        if sum(pool.capacity_bytes for pool in self.store_pools.values()) != (
            self.parameters.store_budget_bytes
        ):
            raise ExperimentError("Store DRAM partition lost total capacity")
        for pool in (*self.peer_pools.values(), *self.store_pools.values()):
            if sum(item.bytes for item in pool.pending.values()) != pool.pending_bytes:
                raise ExperimentError("pool pending reservation bytes diverged")
            if set(pool._pending_keys.values()) - set(pool.pending):
                raise ExperimentError("pool pending key references an unknown reservation")
            if self._formal_policy_enabled():
                landlord = self._formal_landlord_for_pool(pool)
                if (
                    landlord.committed_bytes != pool.occupied_bytes
                    or landlord.pending_bytes != pool.pending_bytes
                    or landlord.rent != pool.rent
                ):
                    raise ExperimentError(
                        "formal SlackLandlord and physical pool byte/rent state diverged: "
                        f"pool={pool.pool_id}, landlord_committed="
                        f"{landlord.committed_bytes}, physical_committed="
                        f"{pool.occupied_bytes}, landlord_pending={landlord.pending_bytes}, "
                        f"physical_pending={pool.pending_bytes}, landlord_rent="
                        f"{landlord.rent}, physical_rent={pool.rent}, now_ns="
                        f"{self.des.now_ns}, physical_last_cause="
                        f"{pool.timeline[-1]['cause']}"
                    )
                if landlord.available:
                    if landlord.capacity_bytes != pool.capacity_bytes or pool.failed:
                        raise ExperimentError(
                            "available formal and physical pool capacities diverged"
                        )
                elif not pool.failed:
                    raise ExperimentError(
                        "unavailable formal failure domain has a healthy physical pool"
                    )
                if pool.pool_id in self._formal_dirty_pool_ids:
                    committed_physical_keys = {
                        self._formal_chunk_metadata[entry.chunk_id].physical_chunk.key
                        for request_id in self._formal_request_ids_by_pool[pool.pool_id]
                        for entry in landlord.committed_entries(request_id)
                    }
                    if committed_physical_keys != set(pool.entries):
                        raise ExperimentError(
                            "formal committed identities and physical entries diverged"
                        )
        self._formal_dirty_pool_ids.clear()
        if len(self.transfers) != len(self._transfer_by_id):
            raise ExperimentError("transfer ledger index diverged from its journal view")
        if (
            len(self._pending_transfer_ledger_ids)
            + len(self._terminal_transfer_ledger_ids)
            != len(self._transfer_by_id)
            or self._pending_transfer_ledger_ids & self._terminal_transfer_ledger_ids
        ):
            raise ExperimentError("transfer ledger state index diverged")
        for transfer_id in sorted(
            self._pending_transfer_ledger_ids
            | self._dirty_terminal_transfer_ledger_ids
        ):
            self._validate_transfer_record(self._transfer_by_id[transfer_id])
        self._dirty_terminal_transfer_ledger_ids.clear()
        for span_id, booking in self._compute_bookings_by_span.items():
            execution = self.executions[span_id]
            reservation = self.compute[booking.gpu_id].reservation(
                booking.reservation_id
            )
            if (
                booking.span_id != span_id
                or booking.route_version != execution.route_version
                or booking.gpu_id != execution.gpu_id
                or booking.reservation_id != execution.reservation_id
                or booking.start_ns != execution.compute_start_ns
                or booking.end_ns != execution.planned_complete_ns
                or booking.completion_handle != execution.completion_handle
                or reservation is None
                or reservation.start_ns != booking.start_ns
                or reservation.end_ns != booking.end_ns
                or reservation.resource_id != f"{booking.gpu_id}.compute"
            ):
                raise ExperimentError("compute booking ownership diverged")
            if booking.started and booking.start_ns > self.des.now_ns:
                raise ExperimentError("future compute booking was marked started")
            if not booking.started and booking.start_ns < self.des.now_ns:
                raise ExperimentError("compute booking missed its start event")
            if booking.kind is _ComputeKind.NORMAL:
                if (
                    booking.recovery_due_ns is not None
                    or booking.start_handle != execution.hbm_allocation_handle
                ):
                    raise ExperimentError("normal compute booking metadata diverged")
            elif booking.recovery_due_ns is None:
                raise ExperimentError("recovery compute booking lost its due time")
        for execution in self.executions.values():
            if execution.external_output_emissions not in {0, execution.metadata.output_tokens}:
                raise ExperimentError("external output was duplicated or partially emitted")
            if (
                execution.gpu_id in self.failed_gpu_ids
                and execution.status is _ExecutionStatus.RUNNING
            ):
                raise ExperimentError("failed GPU retained a running request")
            if execution.recovery_ready_ns is not None:
                if (
                    execution.recovery_normal_hbm_local_tokens
                    + execution.restored_peer_tokens
                    + execution.restored_store_tokens
                    + execution.recompute_tokens
                    != execution.metadata.prompt_tokens
                ):
                    raise ExperimentError("recovery source intervals do not cover the prompt")
                if (
                    execution.restored_peer_local_tokens
                    + execution.restored_peer_d2d_tokens
                    != execution.restored_peer_tokens
                ):
                    raise ExperimentError("Peer-HBM recovery transport split diverged")
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

    def _continuous_prediction_profile(self) -> PredictionProfile:
        return PredictionProfile(
            provider_name=ObservedIdealTraceDurationProvider.PROVIDER_NAME,
            provider_version=ObservedIdealTraceDurationProvider.PROVIDER_VERSION,
            provider_source_revision=VLLM_SOURCE_COMMIT,
            database_mode="ideal_trace_observed_request_duration",
            database_sha256=sha256_json(
                {
                    "algorithm1": self.algorithm1_cpm.provenance(),
                    "span_ids": sorted(self.executions),
                }
            ),
            hardware_profile_id="a100-40gb-qwen3-8b-dp8-tp1-pp1",
            hardware_profile_fingerprint=QWEN3_8B_YARN_128K_LAYOUT_FINGERPRINT,
            model_id=QWEN3_8B_MODEL_ID,
            model_revision=QWEN3_8B_MODEL_REVISION,
            tensor_parallel_size=1,
            pipeline_parallel_size=1,
            forward_boundary=ForwardBoundary(includes_model_collectives=False),
        )

    def _new_continuous_hbm_authority(
        self, gpu_id: str
    ) -> ExperimentHBMAuthority:
        return ExperimentHBMAuthority(
            authority_id=f"experiment-primary:{gpu_id}",
            ledger=self.hbm_ledgers[gpu_id],
            journal=self.des.journal,
            now_ns=lambda: self.des.now_ns,
            logical_block_tokens=16,
            source_chunk_tokens=SOURCE_BLOCK_TOKENS,
            source_chunk_bytes=KV_BYTES_PER_SOURCE_BLOCK,
            active_account=HBM_ACTIVE_PRIMARY_ACCOUNT,
            inactive_account=HBM_INACTIVE_REUSABLE_ACCOUNT,
            recovery_reserved_account=HBM_RECOVERY_RESERVED_ACCOUNT,
            reclaim_free_bytes=partial(self._continuous_reclaim, gpu_id),
            on_commit=partial(self._record_continuous_hbm_commit, gpu_id),
        )

    def _new_continuous_bridge(
        self,
        gpu_id: str,
        authority: ExperimentHBMAuthority,
    ) -> AegisSchedulerStepBridge:
        prediction_profile = self._continuous_duration_profile
        trace_provenance_sha256 = self._continuous_trace_provenance_sha256
        if (
            prediction_profile is None
            or trace_provenance_sha256 is None
            or self._continuous_logical_block_capacity <= 1
        ):
            raise ExperimentError("continuous bridge factory lacks frozen evidence")
        provider = ObservedIdealTraceDurationProvider(
            prediction_profile=prediction_profile,
            trace_provenance_sha256=trace_provenance_sha256,
        )
        scheduler = ContinuousBatchScheduler(
            block_pool=BlockPool(
                self._continuous_logical_block_capacity + 1,
                enable_caching=False,
            ),
            block_size_tokens=16,
            max_num_scheduled_tokens=4096,
            # Workflow concurrency is not request concurrency: one released
            # workflow can fan out to several agent calls.  Physical HBM stays
            # the actual admission authority.
            max_num_running_requests=max(
                256,
                (self.workflow_concurrency or 16) * 8,
            ),
            block_lifecycle_observer=authority,
            # The experiment owns stronger cross-layer invariants and performs a
            # forced scheduler audit at the cell boundary. Re-auditing the whole
            # block pool before and after every scheduler mutation is quadratic
            # in long-context workloads and does not add distinct evidence.
            eager_audit=False,
        )
        return AegisSchedulerStepBridge(
            bridge_id=f"experiment-continuous:{gpu_id}",
            execution_binding=SchedulerExecutionBinding(
                target_id=gpu_id,
                gpu_id=gpu_id,
                failure_domain_id=f"{INFERENCE_NODE_ID}/{gpu_id}",
                kv_abi="vllm-v1-ordinary-full-attention",
                kv_layout_id="qwen3-8b-tp1-pp1-16-token-page",
                kv_layout_sha256=QWEN3_8B_YARN_128K_LAYOUT_FINGERPRINT,
            ),
            scheduler=scheduler,
            prediction_profile=prediction_profile,
            duration_provider=provider,
            adapter=VLLMSchedulerBatchAdapter(),
        )

    def _record_continuous_hbm_commit(self, gpu_id: str, cause: str) -> None:
        self.hbm_timelines[gpu_id].append(
            _capacity_ledger_snapshot(
                self.hbm_ledgers[gpu_id],
                timestamp_ns=self.des.now_ns,
                cause=f"CONTINUOUS_BATCH:{cause}",
            )
        )

    def _continuous_reclaim(self, gpu_id: str, required_bytes: int) -> bool:
        self._latch_aimd_foreground_pressure(
            gpu_id,
            required_bytes,
            reason="CONTINUOUS_BATCH_PRIMARY_HEADROOM_SHORTFALL",
            before_quota_decision=lambda: self._abort_pending_peer_puts_for_pressure(
                gpu_id,
                reason="CONTINUOUS_BATCH_PRIMARY_HEADROOM_SHORTFALL",
            ),
        )
        admitted = self._preempt_peer_puts_for_foreground_hbm(
            gpu_id,
            required_bytes,
        )
        if not admitted:
            self._latch_aimd_foreground_pressure(
                gpu_id,
                required_bytes,
                reason="CONTINUOUS_BATCH_ALLOCATION_OR_RECLAIM_STALL",
                force=True,
            )
        return admitted

    def _on_continuous_before_admit(
        self,
        target_gpu_id: str,
        spec: ContinuousBatchRequestSpec,
        route_version: int,
        _cause: str,
        restored_tokens: int,
    ) -> None:
        execution = self.executions[spec.request_id]
        if execution.route_version != route_version or execution.gpu_id != target_gpu_id:
            raise ExperimentError("continuous admission crossed route authority")
        if restored_tokens <= 0:
            return
        authority = self.continuous_hbm_authorities[target_gpu_id]
        if route_version > 0:
            expected_bytes = _tokens_to_allocated_bytes(restored_tokens)
            if execution.hbm_recovery_reserved_bytes != expected_bytes:
                raise ExperimentError(
                    "continuous restored prefix lost its physical recovery reservation"
                )

            def activate_reserved(source_chunk_count: int) -> int:
                return source_chunk_count * KV_BYTES_PER_SOURCE_BLOCK

            authority.bind_resident_interval(
                request_id=spec.request_id,
                start_token=0,
                token_count=restored_tokens,
                account=HBM_RECOVERY_RESERVED_ACCOUNT,
                activate=activate_reserved,
            )
            return
        foreground_group = self.foreground_store_restore_by_span.get(spec.request_id)
        if foreground_group is not None:
            if (
                foreground_group.route_version != route_version
                or foreground_group.target_gpu_id != target_gpu_id
                or foreground_group.completed_transfer_ids
                != foreground_group.transfer_ids
            ):
                raise ExperimentError(
                    "continuous foreground Store admission crossed restore ownership"
                )
            store_start_token = execution.reused_primary_tokens
            if store_start_token % SOURCE_BLOCK_TOKENS:
                raise ExperimentError(
                    "foreground Store suffix does not start on a source-chunk boundary"
                )
            store_tokens = _logical_page_aligned_prefix(
                min(
                    execution.reused_store_tokens,
                    max(0, restored_tokens - store_start_token),
                ),
                logical_page_tokens=16,
            )
            if store_tokens <= 0:
                raise ExperimentError(
                    "continuous foreground Store admission lost its restored suffix"
                )

            def activate_foreground_store(source_chunk_count: int) -> int:
                adopted_bytes = source_chunk_count * KV_BYTES_PER_SOURCE_BLOCK
                remaining_bytes = (
                    foreground_group.reserved_bytes - foreground_group.adopted_bytes
                )
                if adopted_bytes <= 0 or adopted_bytes > remaining_bytes:
                    raise ExperimentError(
                        "foreground Store adoption exceeded its destination reservation"
                    )
                if execution.hbm_foreground_store_reserved_bytes < adopted_bytes:
                    raise ExperimentError(
                        "foreground Store execution lost destination ownership"
                    )
                foreground_group.adopted_bytes += adopted_bytes
                execution.hbm_foreground_store_reserved_bytes -= adopted_bytes
                if foreground_group.adopted_bytes == foreground_group.reserved_bytes:
                    execution.hbm_foreground_store_target_gpu_id = None
                    del self.foreground_store_restore_by_span[spec.request_id]
                    self.foreground_store_events.append(
                        {
                            "timestamp_ns": self.des.now_ns,
                            "event": "FOREGROUND_STORE_RESTORE_ADOPTED",
                            "span_id": spec.request_id,
                            "target_gpu_id": target_gpu_id,
                            "restored_tokens": foreground_group.restored_tokens,
                            "adopted_bytes": foreground_group.adopted_bytes,
                        }
                    )
                return adopted_bytes

            authority.bind_resident_interval(
                request_id=spec.request_id,
                start_token=store_start_token,
                token_count=store_tokens,
                account=HBM_FOREGROUND_STORE_RESERVED_ACCOUNT,
                activate=activate_foreground_store,
            )
        normal_tokens = execution.reused_primary_tokens
        normal_tokens = _source_chunk_page_aligned_prefix(
            execution.chunks,
            min(normal_tokens, restored_tokens),
            logical_page_tokens=16,
        )
        if normal_tokens <= 0:
            return
        # Initial local-HBM hits use an immutable logical alias.  The simplified
        # experiment authority conservatively charges a complete ACTIVE copy for
        # the request while retaining the shared inactive cache master, rather
        # than destructively reclassifying bytes away from other concurrent
        # system-prompt readers.  This overcharges capacity but never invents
        # bandwidth or makes a second reader lose an otherwise valid HBM hit.
        self.primary_pools[target_gpu_id].release_pin(spec.request_id)

    def _sync_continuous_execution_hbm(self, target_gpu_id: str) -> None:
        authority = self.continuous_hbm_authorities[target_gpu_id]
        active_ids = set(authority.active_request_ids)
        for execution in self.executions.values():
            if execution.gpu_id != target_gpu_id or execution.status in {
                _ExecutionStatus.FENCED,
                _ExecutionStatus.COMPLETED,
            }:
                continue
            span_id = execution.metadata.span_id
            owned = authority.physical_bytes_for_request(span_id)
            execution.hbm_allocated_bytes = owned
            if owned:
                execution.hbm_allocation_gpu_id = target_gpu_id
            elif execution.hbm_recovery_reserved_bytes > 0:
                if execution.hbm_allocation_gpu_id != target_gpu_id:
                    raise ExperimentError(
                        "continuous recovery reservation lost its target ownership"
                    )
            else:
                execution.hbm_allocation_gpu_id = None
            if span_id not in active_ids and execution.status is _ExecutionStatus.RUNNING:
                execution.status = _ExecutionStatus.QUEUED

    def _on_continuous_after_admit(
        self,
        target_gpu_id: str,
        spec: ContinuousBatchRequestSpec,
        route_version: int,
        _cause: str,
        restored_tokens: int,
    ) -> None:
        execution = self.executions[spec.request_id]
        if execution.route_version != route_version:
            raise ExperimentError("continuous post-admission route is stale")
        if route_version > 0 and restored_tokens > 0:
            expected_bytes = _tokens_to_allocated_bytes(restored_tokens)
            if execution.hbm_recovery_reserved_bytes != expected_bytes:
                raise ExperimentError("continuous recovery reserve changed during admission")
            # ``admit_restored_request`` is capacity-safe connector admission:
            # the request can remain WAITING until scheduler page IDs become
            # available.  Keep the physical recovery reservation attributed to
            # the execution until the first scheduler step atomically adopts
            # it into ACTIVE primary ownership.
        self._sync_continuous_execution_hbm(target_gpu_id)

    def _on_continuous_admit_abort(
        self,
        target_gpu_id: str,
        spec: ContinuousBatchRequestSpec,
        route_version: int,
        _cause: str,
        restored_tokens: int,
    ) -> None:
        """Rollback physical pre-admission state after logical admission fails."""

        execution = self.executions[spec.request_id]
        if execution.route_version != route_version:
            raise ExperimentError("continuous admission rollback crossed route authority")
        self.continuous_hbm_authorities[
            target_gpu_id
        ].unbind_resident_intervals(spec.request_id)
        if spec.request_id in self.foreground_store_restore_by_span:
            if not self._abort_foreground_store_restore_group(
                spec.request_id,
                reason="FOREGROUND_STORE_SCHEDULER_ADMISSION_FAILED",
                unregister_pristine=True,
            ):
                raise ExperimentError(
                    "foreground Store admission rollback lost its restore group"
                )
        if route_version == 0 and restored_tokens > 0:
            self.primary_pools[target_gpu_id].release_pin(spec.request_id)

    def _on_continuous_step_started(
        self,
        target_gpu_id: str,
        step: AegisSchedulerStep,
        start_ns: int,
        planned_end_ns: int,
    ) -> None:
        if step.preempted_request_ids:
            self.scheduler_preemption_events.append(
                {
                    "timestamp_ns": start_ns,
                    "target_gpu_id": target_gpu_id,
                    "scheduler_step_id": step.step_id,
                    "preempted_request_ids": list(step.preempted_request_ids),
                    "preemption_details": [
                        dict(item) for item in step.preemption_details
                    ],
                    "has_forward": step.has_forward,
                    "participant_request_ids": [
                        participant.request_id for participant in step.participants
                    ],
                }
            )
            self._latch_aimd_foreground_pressure(
                target_gpu_id,
                0,
                reason="CONTINUOUS_BATCH_SCHEDULER_RECOMPUTE_PREEMPTION",
                force=True,
            )
        for participant in step.participants:
            execution = self.executions[participant.request_id]
            if execution.route_version != participant.route_version:
                raise ExperimentError("continuous scheduler participant route is stale")
            if execution.route_version > 0 and execution.hbm_recovery_reserved_bytes > 0:
                reserved_bytes = execution.hbm_recovery_reserved_bytes
                owned_bytes = self.continuous_hbm_authorities[
                    target_gpu_id
                ].physical_bytes_for_request(participant.request_id)
                if owned_bytes < reserved_bytes:
                    raise ExperimentError(
                        "continuous recovery prefix entered a scheduler step before "
                        "adopting its physical reservation"
                    )
                execution.hbm_recovery_reserved_bytes = 0
            execution.gpu_id = target_gpu_id
            if execution.compute_start_ns is None or participant.recompute:
                execution.compute_start_ns = start_ns
            execution.planned_complete_ns = planned_end_ns
            execution.status = (
                _ExecutionStatus.RESUMED
                if execution.route_version > 0
                else _ExecutionStatus.RUNNING
            )
            recovery_source_tokens = (
                execution.recovery_normal_hbm_local_tokens
                + execution.restored_peer_tokens
                + execution.restored_store_tokens
                + execution.recompute_tokens
            )
            if (
                execution.route_version > 0
                and recovery_source_tokens > 0
                and execution.prompt_recompute_start_ns is None
            ):
                execution.prompt_recompute_start_ns = start_ns
                self.recovery_events.append(
                    {
                        "timestamp_ns": start_ns,
                        "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                        "span_id": execution.metadata.span_id,
                        "route_version": execution.route_version,
                        "target_gpu_id": target_gpu_id,
                        "recompute_tokens": execution.recompute_tokens,
                        "scheduler_step_id": step.step_id,
                        "continuous_batch": True,
                    }
                )
            if execution.metadata.span_id in self._failure_schedule_by_focus_span:
                active_failure_step = _ContinuousFailureStep(
                    span_id=execution.metadata.span_id,
                    route_version=execution.route_version,
                    gpu_id=target_gpu_id,
                    scheduler_step_id=step.step_id,
                    start_ns=start_ns,
                    end_ns=planned_end_ns,
                    num_computed_tokens_before=(
                        participant.num_computed_tokens_before
                    ),
                    num_computed_tokens_after=participant.num_computed_tokens_after,
                )
                if execution.metadata.span_id in self._continuous_failure_active_steps:
                    raise ExperimentError(
                        "continuous failure focus entered overlapping scheduler steps"
                    )
                self._continuous_failure_active_steps[
                    execution.metadata.span_id
                ] = active_failure_step
                self._schedule_continuous_logical_failure_trigger(
                    execution,
                    step=active_failure_step,
                )
        self._sync_continuous_execution_hbm(target_gpu_id)

    def _on_continuous_maintenance_step(
        self,
        target_gpu_id: str,
        step: AegisSchedulerStep,
    ) -> None:
        """Publish scheduler-only preemption into the execution HBM mirror."""

        if step.has_forward or not step.preempted_request_ids:
            raise ExperimentError("continuous maintenance callback received a forward step")
        self.scheduler_preemption_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "target_gpu_id": target_gpu_id,
                "scheduler_step_id": step.step_id,
                "preempted_request_ids": list(step.preempted_request_ids),
                "preemption_details": [
                    dict(item) for item in step.preemption_details
                ],
                "has_forward": False,
                "participant_request_ids": [],
            }
        )
        self._latch_aimd_foreground_pressure(
            target_gpu_id,
            0,
            reason="CONTINUOUS_BATCH_SCHEDULER_RECOMPUTE_PREEMPTION",
            force=True,
        )
        self._sync_continuous_execution_hbm(target_gpu_id)

    def _on_continuous_step_completed(
        self,
        target_gpu_id: str,
        step: AegisSchedulerStep,
        completion: SchedulerStepCompletion,
        completed_ns: int,
        _after_retire: ResidentPrimarySnapshot,
    ) -> None:
        terminal = set(completion.terminal_output_request_ids)
        for participant in step.participants:
            execution = self.executions[participant.request_id]
            if execution.route_version != participant.route_version:
                raise ExperimentError("continuous completion crossed a route fence")
            failure_schedule = self._failure_schedule_by_focus_span.get(
                participant.request_id
            )
            active_failure_step = self._continuous_failure_active_steps.pop(
                participant.request_id,
                None,
            )
            if failure_schedule is not None and (
                active_failure_step is None
                or active_failure_step.scheduler_step_id != step.step_id
                or active_failure_step.route_version != participant.route_version
            ):
                raise ExperimentError(
                    "continuous failure focus lost its active scheduler-step evidence"
                )
            self._schedule_continuous_sealed_protection_puts(
                execution,
                source_gpu_id=target_gpu_id,
                computed_prompt_tokens=min(
                    execution.metadata.prompt_tokens,
                    participant.num_computed_tokens_after,
                ),
            )
            recovery_source_tokens = (
                execution.recovery_normal_hbm_local_tokens
                + execution.restored_peer_tokens
                + execution.restored_store_tokens
                + execution.recompute_tokens
            )
            if (
                execution.route_version > 0
                and recovery_source_tokens > 0
                and participant.produces_output
            ):
                if execution.prompt_recompute_complete_ns is None:
                    execution.prompt_recompute_complete_ns = completed_ns
                    self.recovery_events.append(
                        {
                            "timestamp_ns": completed_ns,
                            "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                            "span_id": execution.metadata.span_id,
                            "route_version": execution.route_version,
                            "target_gpu_id": target_gpu_id,
                            "recompute_tokens": execution.recompute_tokens,
                            "scheduler_step_id": step.step_id,
                            "continuous_batch": True,
                        }
                    )
                committed_before_failure = (
                    execution.committed_output_tokens_at_failure
                )
                replayed_position = (participant.output_index or 0) + 1
                if committed_before_failure > 0 and execution.silent_replay_start_ns is None:
                    execution.silent_replay_start_ns = completed_ns
                    self.recovery_events.append(
                        {
                            "timestamp_ns": completed_ns,
                            "event": "SILENT_REPLAY_START",
                            "span_id": execution.metadata.span_id,
                            "route_version": execution.route_version,
                            "target_gpu_id": target_gpu_id,
                            "replayed_output_tokens": committed_before_failure,
                            "externally_emitted_tokens": 0,
                            "scheduler_step_id": step.step_id,
                            "continuous_batch": True,
                        }
                    )
                if (
                    execution.recovery_ready_ns is None
                    and replayed_position >= committed_before_failure
                ):
                    if execution.silent_replay_start_ns is None:
                        execution.silent_replay_start_ns = completed_ns
                    execution.silent_replay_complete_ns = completed_ns
                    execution.recovery_ready_ns = completed_ns
                    execution.resume_decode_start_ns = completed_ns
                    self.recovery_events.append(
                        {
                            "timestamp_ns": completed_ns,
                            "event": "SILENT_REPLAY_COMPLETE",
                            "span_id": execution.metadata.span_id,
                            "route_version": execution.route_version,
                            "target_gpu_id": target_gpu_id,
                            "replayed_output_tokens": committed_before_failure,
                            "externally_emitted_tokens": 0,
                            "scheduler_step_id": step.step_id,
                            "continuous_batch": True,
                        }
                    )
            if participant.request_id not in terminal:
                continue
            if (
                failure_schedule is not None
                and failure_schedule.failure_id not in self._failure_event_executed
            ):
                failure_plan = self.failure_schedule
                if failure_plan is None:
                    raise ExperimentError("continuous failure focus lost its plan")
                prior_failure_ids = {
                    item.failure_id
                    for item in failure_plan.events[: failure_schedule.event_index]
                }
                if prior_failure_ids.issubset(self._failure_event_executed):
                    raise ExperimentError(
                        "continuous failure focus completed after its trigger became ready"
                    )
            primary_pool = self.primary_pools[target_gpu_id]
            for chunk in execution.chunks:
                primary_pool.insert(
                    chunk,
                    score=Fraction(completed_ns, 1),
                    now_ns=completed_ns,
                    cause="CONTINUOUS_BATCH_TERMINAL_ACTIVE_TO_INACTIVE",
                )
            self._sync_primary_hbm_ledger(
                target_gpu_id,
                cause="CONTINUOUS_BATCH_TERMINAL_ACTIVE_TO_INACTIVE",
            )
            execution.hbm_allocated_bytes = 0
            execution.hbm_allocation_gpu_id = None
            execution.status = _ExecutionStatus.COMPLETED
            execution.completed_ns = completed_ns
            execution.planned_complete_ns = completed_ns
            execution.external_output_emissions = execution.metadata.output_tokens
            self._completed_span_ids.add(participant.request_id)
            self.causal.mark_completed(participant.request_id)
            self._formal_drop_waiting_suffixes(
                participant.request_id,
                reason="REQUEST_COMPLETE",
            )
            self._update_residual_slack(
                execution.metadata.workflow_id,
                reason="REQUEST_COMPLETE",
                trigger_span_id=participant.request_id,
            )
            self.des.journal.append(
                completed_ns,
                "AEGIS_EXTERNAL_OUTPUT_COMMITTED",
                {
                    "span_id": participant.request_id,
                    "route_version": participant.route_version,
                    "output_tokens": execution.metadata.output_tokens,
                    "emission_count": 1,
                    "scheduler_step_id": step.step_id,
                },
            )
        self._sync_continuous_execution_hbm(target_gpu_id)
        if len(self._completed_span_ids) == len(self.executions):
            for gpu_id, handle in tuple(self._aimd_window_handles.items()):
                if not self.des.cancel(handle, reason="AIMD_WORKLOAD_COMPLETE"):
                    raise ExperimentError("final AIMD control window could not be canceled")
                del self._aimd_window_handles[gpu_id]

    def _schedule_continuous_sealed_protection_puts(
        self,
        execution: _SpanExecution,
        *,
        source_gpu_id: str,
        computed_prompt_tokens: int,
    ) -> None:
        paths = (
            ("PEER_HBM", self.profile.peer_replication_fraction),
            ("STORE_DRAM", self.profile.store_fraction),
        )
        for path, fraction in paths:
            candidate_count = _fraction_prefix_chunk_count(execution.chunks, fraction)
            if candidate_count == 0:
                continue
            target_gpu_id = (
                self._peer_target(
                    source_gpu_id=source_gpu_id,
                    span_id=execution.metadata.span_id,
                )
                if path == "PEER_HBM"
                else None
            )
            if path == "PEER_HBM" and target_gpu_id is None:
                self.protection_path_bypasses["PEER_HBM_NO_HEALTHY_TARGET"] += 1
                continue
            if target_gpu_id is not None:
                execution.designated_peer_gpu_id = target_gpu_id
            policy_ranges = _protection_batch_ranges(
                len(execution.chunks),
                candidate_count,
                global_prefix_chunk_count=_global_prefix_chunk_count(
                    execution.chunks[:candidate_count]
                ),
            )
            transport_ranges = _protection_transfer_batch_ranges(
                len(policy_ranges),
                global_prefix_candidate_count=_global_prefix_chunk_count(
                    execution.chunks[:candidate_count]
                ),
            )
            for batch_index, (candidate_begin, candidate_end) in enumerate(
                transport_ranges
            ):
                begin = policy_ranges[candidate_begin][0]
                end = policy_ranges[candidate_end - 1][1]
                sealed_tokens = (
                    execution.chunks[end - 1].token_start
                    + execution.chunks[end - 1].token_count
                )
                if sealed_tokens > computed_prompt_tokens:
                    continue
                if self._formal_policy_enabled():
                    chunks = tuple(
                        self._protection_chunk(
                            execution,
                            execution.chunks[policy_begin:policy_end],
                            path=path,
                        )
                        for policy_begin, policy_end in policy_ranges[
                            candidate_begin:candidate_end
                        ]
                    )
                else:
                    chunks = execution.chunks[begin:end]
                grouped: list[tuple[str | None, list[_Chunk]]] = []
                if path == "PEER_HBM":
                    grouped.append((None, list(chunks)))
                else:
                    for chunk in chunks:
                        chunk_store_id = self._store_segment_for_chunk(chunk)
                        if grouped and grouped[-1][0] == chunk_store_id:
                            grouped[-1][1].append(chunk)
                        else:
                            grouped.append((chunk_store_id, [chunk]))
                for group_target_store_id, group in grouped:
                    continuous_batch_key = (
                        execution.route_version,
                        path,
                        batch_index,
                        group_target_store_id or target_gpu_id or "peer",
                    )
                    if continuous_batch_key in (
                        execution.continuous_protection_batch_states
                    ):
                        continue
                    plan_id = self._next_id(
                        f"continuous-put:{path}:{execution.metadata.span_id}:"
                        f"batch-{batch_index}:{group_target_store_id or 'peer'}"
                    )
                    handle = self.des.schedule_at(
                        self.des.now_ns,
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
                        target_store_id=group_target_store_id,
                        chunks=tuple(group),
                        handle=handle,
                        produced_ns=self.des.now_ns,
                        continuous_batch_key=continuous_batch_key,
                    )
                    execution.continuous_protection_batch_states[
                        continuous_batch_key
                    ] = _ContinuousProtectionBatchState()

    def _split_continuous_protection_batch(
        self,
        *,
        span_id: str,
        batch_key: tuple[int, str, int, str] | None,
    ) -> None:
        """Add one independently terminal suffix to an in-flight group."""

        if batch_key is None:
            return
        state = self.executions[span_id].continuous_protection_batch_states.get(
            batch_key
        )
        if state is None or state.committed or state.outstanding_parts <= 0:
            raise ExperimentError(
                "continuous protection split lost its scheduled batch"
            )
        state.outstanding_parts += 1

    def _resolve_continuous_protection_batch(
        self,
        *,
        span_id: str,
        batch_key: tuple[int, str, int, str] | None,
        committed: bool,
    ) -> None:
        """Resolve one route-scoped protection group exactly once.

        Scheduling is not a durable protection result.  A canceled or bypassed
        group must be eligible for retry on a later scheduler step, while a
        physically committed group is permanently deduplicated for that route.
        """

        if batch_key is None:
            return
        execution = self.executions[span_id]
        states = execution.continuous_protection_batch_states
        state = states.get(batch_key)
        if state is None:
            if committed:
                raise ExperimentError(
                    "continuous protection commit lost its scheduled batch"
                )
            return
        if state.committed or state.outstanding_parts <= 0:
            raise ExperimentError(
                "continuous protection batch resolved from a non-scheduled state"
            )
        state.outstanding_parts -= 1
        state.failed = state.failed or not committed
        if state.outstanding_parts > 0:
            return
        if state.failed:
            del states[batch_key]
        else:
            state.committed = True

    def _on_release(self, metadata: NormalizedSpanMetadata, _des: GlobalDES) -> None:
        execution = self.executions[metadata.span_id]
        execution.released_ns = self.des.now_ns
        execution.base_duration_ns = max(1, metadata.recorded_api_time_ns)
        self._update_residual_slack(
            metadata.workflow_id,
            reason="REQUEST_RELEASE",
            trigger_span_id=metadata.span_id,
        )
        gpu_id = self._route_gpu(
            metadata.span_id,
            route_version=0,
            required_hbm_bytes=_tokens_to_allocated_bytes(metadata.prompt_tokens),
        )
        local = self._local_hbm_prefix_breakdown(
            gpu_id,
            execution,
            mutate_signals=True,
            include_active_primary=True,
        )
        local_prefix = local["local_hbm_union_prefix_tokens"]
        store_prefix = (
            self._store_lookup_prefix_tokens(
                (
                    self._protection_chunks(execution, path="STORE_DRAM")
                    if self._formal_policy_enabled()
                    else execution.chunks
                ),
                now_ns=self.des.now_ns,
                mutate_signals=True,
            )
            if self._reuse_visible("STORE_DRAM")
            else 0
        )
        route_event = self.route_events[-1]
        if route_event.get("span_id") != metadata.span_id:
            raise ExperimentError("cache-aware route decision was not recorded atomically")
        if self.continuous_batch_enabled:
            # Initial local-HBM hits may come from either a completed inactive
            # prefix or a sealed ACTIVE prefix shared by another request.  Peer
            # protection stays independent until explicit failure recovery.
            reusable_primary_tokens = _source_chunk_page_aligned_prefix(
                execution.chunks,
                local["normal_hbm_contribution_tokens"],
                logical_page_tokens=16,
            )
            reused = _source_chunk_page_aligned_prefix(
                execution.chunks,
                max(local["normal_hbm_contribution_tokens"], store_prefix),
                logical_page_tokens=16,
            )
            route_candidates = route_event.get("candidates")
            if not isinstance(route_candidates, Mapping):
                raise ExperimentError("continuous route candidates are malformed")
            selected_candidate = route_candidates.get(gpu_id)
            if not isinstance(selected_candidate, Mapping):
                raise ExperimentError("selected continuous route candidate is missing")
            if reusable_primary_tokens != int(
                selected_candidate["adoptable_normal_hbm_prefix_tokens"]
            ) or reused != int(selected_candidate["effective_prefix_tokens"]):
                raise ExperimentError(
                    "continuous route and admission reuse accounting diverged"
                )
            execution.reused_primary_tokens = min(
                reusable_primary_tokens,
                reused,
            )
            execution.reused_peer_tokens = 0
            execution.reused_store_tokens = max(
                0,
                reused - execution.reused_primary_tokens,
            )
            if (
                execution.reused_primary_tokens > 0
                and local["inactive_reusable_prefix_tokens"]
                >= execution.reused_primary_tokens
            ):
                self.primary_pools[gpu_id].pin_interval(
                    execution.chunks,
                    start_token=0,
                    token_count=execution.reused_primary_tokens,
                    pin_id=metadata.span_id,
                )
        else:
            execution.reused_primary_tokens = local[
                "normal_hbm_contribution_tokens"
            ]
            execution.reused_peer_tokens = local["peer_backup_contribution_tokens"]
            execution.reused_store_tokens = max(0, store_prefix - local_prefix)
            reused = max(local_prefix, store_prefix)
        duration = _duration_after_prefix_reuse(metadata, execution.base_duration_ns, reused)
        store_restore_ns = int(route_event["selected_store_restore_ns"])
        if self.continuous_batch_enabled and execution.reused_store_tokens > 0:
            self._start_foreground_store_restore(
                execution,
                gpu_id=gpu_id,
                duration_ns=duration,
                route_estimate_ns=store_restore_ns,
            )
        else:
            self._schedule_compute(
                execution,
                gpu_id=gpu_id,
                ready_ns=self.des.now_ns + store_restore_ns,
                duration_ns=duration,
            )

    def _continuous_request_spec(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        release_ns: int,
        restored_tokens: int,
    ) -> ContinuousBatchRequestSpec:
        prompt_token_ids = _exact_prompt_token_ids(execution.record)
        if prompt_token_ids is None:
            raise ExperimentError(
                "continuous scheduler requires exact frozen prompt token IDs"
            )
        return ContinuousBatchRequestSpec(
            request_id=execution.metadata.span_id,
            release_ns=release_ns,
            prompt_tokens=execution.metadata.prompt_tokens,
            max_output_tokens=execution.metadata.output_tokens,
            observed_ideal_duration_ns=execution.base_duration_ns,
            initial_target_id=gpu_id,
            max_model_len_tokens=131_072,
            prompt_token_ids=prompt_token_ids,
            initial_restored_tokens=restored_tokens,
            route_bound_before_admission=True,
        )

    def _start_foreground_store_restore(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        duration_ns: int,
        route_estimate_ns: int,
    ) -> None:
        """Start an initial Store hit as real shared fluid-flow work."""

        if not self.continuous_batch_enabled or execution.route_version != 0:
            raise ExperimentError("foreground Store restore requires initial continuous route")
        span_id = execution.metadata.span_id
        if span_id in self.foreground_store_restore_by_span:
            raise ExperimentError("foreground Store restore group already exists")
        driver = self.continuous_batch_driver
        if driver is None or execution.released_ns is None:
            raise ExperimentError("foreground Store restore lost scheduler/release evidence")
        restored_tokens = _logical_page_aligned_prefix(
            min(
                execution.metadata.prompt_tokens,
                execution.reused_primary_tokens + execution.reused_store_tokens,
            ),
            logical_page_tokens=16,
        )
        if execution.reused_store_tokens <= 0 or restored_tokens <= 0:
            raise ExperimentError("foreground Store restore has no Store suffix")
        layout = self._foreground_store_layout_by_segment(
            execution,
            start_token=execution.reused_primary_tokens,
            token_count=execution.reused_store_tokens,
        )
        reserved_bytes = sum(item[0] for item in layout.values())
        if reserved_bytes <= 0:
            raise ExperimentError("foreground Store restore has no allocated bytes")
        self._latch_aimd_foreground_pressure(
            gpu_id,
            reserved_bytes,
            reason="FOREGROUND_STORE_RESTORE_HEADROOM_SHORTFALL",
        )
        if not self._preempt_peer_puts_for_foreground_hbm(gpu_id, reserved_bytes):
            self._latch_aimd_foreground_pressure(
                gpu_id,
                reserved_bytes,
                reason="FOREGROUND_STORE_RESTORE_ALLOCATION_OR_RECLAIM_STALL",
                force=True,
            )
            raise ExperimentError("foreground Store restore cannot reserve destination HBM")
        self._commit_hbm_moves(
            gpu_id,
            [(FREE_ACCOUNT, HBM_FOREGROUND_STORE_RESERVED_ACCOUNT, reserved_bytes)],
            cause="FOREGROUND_STORE_RESTORE_DESTINATION_RESERVE",
        )
        execution.hbm_foreground_store_reserved_bytes = reserved_bytes
        execution.hbm_foreground_store_target_gpu_id = gpu_id
        execution.gpu_id = gpu_id
        execution.status = _ExecutionStatus.QUEUED
        execution.scheduled_duration_ns = max(1, duration_ns)
        group = _ForegroundStoreRestoreGroup(
            span_id=span_id,
            route_version=execution.route_version,
            target_gpu_id=gpu_id,
            restored_tokens=restored_tokens,
            scheduled_duration_ns=max(1, duration_ns),
            reserved_bytes=reserved_bytes,
            transfer_ids=set(),
        )
        self.foreground_store_restore_by_span[span_id] = group
        registered = False
        try:
            driver.register_suspended(
                self._continuous_request_spec(
                    execution,
                    gpu_id=gpu_id,
                    release_ns=execution.released_ns,
                    restored_tokens=restored_tokens,
                )
            )
            registered = True
            for source_store_id, (transfer_bytes, source_keys) in layout.items():
                transfer_id = self._next_id(
                    f"foreground-store:{source_store_id}:{span_id}"
                )
                source_pool = self.store_pools[source_store_id]
                transfer_start_ns = self.des.now_ns + self.parameters.transfer_setup_ns
                task = self._make_transfer_task(
                    transfer_id=transfer_id,
                    span_id=span_id,
                    source_id=source_store_id,
                    target_id=gpu_id,
                    cause="AEGIS_FOREGROUND_STORE_RESTORE",
                    route_version=execution.route_version,
                    ready_ns=transfer_start_ns,
                    total_bytes=transfer_bytes,
                )
                pending = _PendingForegroundStoreTransfer(
                    transfer_id=transfer_id,
                    span_id=span_id,
                    source_store_id=source_store_id,
                    target_gpu_id=gpu_id,
                    task=task,
                    handle=None,
                    bytes=transfer_bytes,
                    source_chunk_keys=source_keys,
                )
                self.pending_foreground_store_transfers[transfer_id] = pending
                group.transfer_ids.add(transfer_id)
                source_pool.pin_keys(source_keys, pin_id=transfer_id)
                pending.handle = self.des.schedule_at(
                    transfer_start_ns,
                    EventKind.GET_START,
                    event_id=f"foreground-get-start:{transfer_id}",
                    payload={"transfer_id": transfer_id, "span_id": span_id},
                )
                bandwidth = min(
                    self.transfer_rate_resources[resource_id].capacity_bytes_per_second
                    for resource_id in task.metadata.path.rate_resource_ids
                )
                initial_service_ns = math.ceil(
                    transfer_bytes * 1_000_000_000 / bandwidth
                )
                self._record_transfer(
                    _transfer_record(
                        transfer_id=transfer_id,
                        path="STORE_H2D",
                        cause="AEGIS_FOREGROUND_STORE_RESTORE",
                        start_ns=transfer_start_ns,
                        end_ns=transfer_start_ns + max(1, initial_service_ns),
                        bytes=transfer_bytes,
                        source_gpu_id=source_store_id,
                        target_gpu_id=gpu_id,
                        ready_ns=self.des.now_ns,
                        status="PENDING",
                        span_id=span_id,
                        flow_slice_count=len(task.slices),
                        policy_candidate_count=0,
                    )
                )
                self._transfer_by_id[transfer_id]["route_estimate_ns"] = route_estimate_ns
                self._bind_transfer_task_metadata(task)
        except Exception:
            self._abort_foreground_store_restore_group(
                span_id,
                reason="FOREGROUND_STORE_RESTORE_SETUP_FAILED",
                unregister_pristine=registered,
            )
            raise
        if not group.transfer_ids:
            raise ExperimentError("foreground Store restore created no segment transfers")

    def _on_foreground_store_get_start(
        self,
        event: ScheduledEvent,
        _des: GlobalDES,
    ) -> None:
        transfer_id = _required_str(event.payload, "transfer_id")
        pending = self.pending_foreground_store_transfers.get(transfer_id)
        if pending is None or pending.handle != EventHandle(event.event_id):
            raise ExperimentError("unknown or stale foreground Store GET start")
        group = self.foreground_store_restore_by_span.get(pending.span_id)
        execution = self.executions[pending.span_id]
        if (
            group is None
            or group.route_version != execution.route_version
            or group.target_gpu_id != pending.target_gpu_id
            or pending.target_gpu_id in self.failed_gpu_ids
            or pending.task.status is not TransferStatus.WAITING
        ):
            raise ExperimentError("foreground Store GET crossed route authority")
        pending.handle = None
        try:
            self._acquire_transfer_overlays(pending.task)
            self.transfer_runtime.start_task(
                pending.task,
                on_terminal=self._on_foreground_store_task_terminal,
            )
        except Exception:
            if transfer_id in self.active_source_pins:
                self._release_transfer_overlays(
                    pending.task,
                    reason="FOREGROUND_STORE_GET_START_FAILED",
                )
            self._abort_foreground_store_restore_group(
                pending.span_id,
                reason="FOREGROUND_STORE_GET_START_FAILED",
                unregister_pristine=True,
            )
            raise
        record = self._transfer_by_id[transfer_id]
        record["start_ns"] = self.des.now_ns
        predicted_end_ns = self._predicted_task_completion_ns(pending.task)
        record["planned_end_ns"] = predicted_end_ns
        record["end_ns"] = predicted_end_ns
        self.foreground_store_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "FOREGROUND_STORE_GET_START",
                "span_id": pending.span_id,
                "transfer_id": transfer_id,
                "source_store_id": pending.source_store_id,
                "target_gpu_id": pending.target_gpu_id,
                "bytes": pending.bytes,
            }
        )

    def _on_foreground_store_task_terminal(
        self,
        task: TransferTask,
        _des: GlobalDES,
    ) -> None:
        transfer_id = task.metadata.transfer_id
        pending = self.pending_foreground_store_transfers.get(transfer_id)
        if pending is None or pending.task is not task:
            raise ExperimentError("foreground Store terminal callback lost its owner")
        if task.status is TransferStatus.CANCELED:
            return
        if task.status is not TransferStatus.COMPLETED:
            raise ExperimentError("foreground Store GET reached unsupported terminal state")
        self._release_transfer_overlays(task, reason="FOREGROUND_STORE_GET_COMPLETED")
        self.store_pools[pending.source_store_id].release_pin(transfer_id)
        self._finish_fluid_service_record(transfer_id, task=task)
        self._commit_transfer(transfer_id)
        del self.pending_foreground_store_transfers[transfer_id]
        group = self.foreground_store_restore_by_span.get(pending.span_id)
        if group is None or transfer_id not in group.transfer_ids:
            raise ExperimentError("foreground Store GET group lost a transfer")
        group.completed_transfer_ids.add(transfer_id)
        self.foreground_store_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "FOREGROUND_STORE_GET_SEGMENT_COMPLETE",
                "span_id": pending.span_id,
                "transfer_id": transfer_id,
                "source_store_id": pending.source_store_id,
                "target_gpu_id": pending.target_gpu_id,
                "bytes": pending.bytes,
            }
        )
        if group.completed_transfer_ids == group.transfer_ids:
            group.completion_handle = self.des.schedule_at(
                self.des.now_ns,
                EventKind.GET_COMPLETE,
                event_id=f"foreground-get-complete:{pending.span_id}:{self.des.now_ns}",
                payload={"span_id": pending.span_id},
            )

    def _on_foreground_store_get_complete(
        self,
        event: ScheduledEvent,
        _des: GlobalDES,
    ) -> None:
        span_id = _required_str(event.payload, "span_id")
        group = self.foreground_store_restore_by_span.get(span_id)
        execution = self.executions[span_id]
        if (
            group is None
            or group.completion_handle != EventHandle(event.event_id)
            or group.completed_transfer_ids != group.transfer_ids
            or execution.route_version != group.route_version
            or execution.hbm_foreground_store_reserved_bytes != group.reserved_bytes
            or execution.hbm_foreground_store_target_gpu_id != group.target_gpu_id
            or group.target_gpu_id in self.failed_gpu_ids
        ):
            raise ExperimentError("foreground Store group completion is stale")
        group.completion_handle = None
        driver = self.continuous_batch_driver
        if driver is None:
            raise ExperimentError("foreground Store completion lost scheduler driver")
        driver.schedule_registered_initial_admission(
            request_id=span_id,
            target_id=group.target_gpu_id,
            ready_ns=self.des.now_ns,
            restored_tokens=group.restored_tokens,
        )
        self.foreground_store_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "FOREGROUND_STORE_RESTORE_COMPLETE",
                "span_id": span_id,
                "target_gpu_id": group.target_gpu_id,
                "restored_tokens": group.restored_tokens,
                "reserved_bytes": group.reserved_bytes,
                "segment_transfer_count": len(group.transfer_ids),
                "destination_account": HBM_FOREGROUND_STORE_RESERVED_ACCOUNT,
            }
        )

    def _abort_foreground_store_restore_group(
        self,
        span_id: str,
        *,
        reason: str,
        unregister_pristine: bool,
    ) -> bool:
        """Atomically abort one initial Store GET group and its destination."""

        group = self.foreground_store_restore_by_span.get(span_id)
        if group is None:
            return False
        if group.completion_handle is not None:
            if not self.des.cancel(group.completion_handle, reason=reason):
                raise ExperimentError("foreground Store completion was not cancellable")
            group.completion_handle = None
        for transfer_id in sorted(group.transfer_ids):
            pending = self.pending_foreground_store_transfers.get(transfer_id)
            if pending is None:
                if transfer_id not in group.completed_transfer_ids:
                    raise ExperimentError("foreground Store group lost a transfer owner")
                continue
            if pending.handle is not None:
                if not self.des.cancel(pending.handle, reason=reason):
                    raise ExperimentError("foreground Store GET start was not cancellable")
                pending.handle = None
            if pending.task.status is TransferStatus.PENDING:
                self.transfer_runtime.abort_task(transfer_id, reason=reason)
                self._release_transfer_overlays(pending.task, reason=reason)
            elif pending.task.status is TransferStatus.WAITING:
                pending.task.cancel_remaining(
                    timestamp_ns=self.des.now_ns,
                    reason=reason,
                )
            elif pending.task.status is not TransferStatus.CANCELED:
                raise ExperimentError("foreground Store abort found terminal live owner")
            self.store_pools[pending.source_store_id].release_pin(transfer_id)
            if transfer_id in self._transfer_by_id and self._transfer_by_id[transfer_id].get(
                "status"
            ) == "PENDING":
                self._abort_transfer_from_task(
                    transfer_id,
                    task=pending.task,
                    reason=reason,
                )
            del self.pending_foreground_store_transfers[transfer_id]
        execution = self.executions[span_id]
        remaining_reserved_bytes = group.reserved_bytes - group.adopted_bytes
        if execution.hbm_foreground_store_reserved_bytes != remaining_reserved_bytes:
            raise ExperimentError("foreground Store abort lost destination reserve")
        if remaining_reserved_bytes > 0 and group.target_gpu_id not in self.failed_gpu_ids:
            self._commit_hbm_moves(
                group.target_gpu_id,
                [
                    (
                        HBM_FOREGROUND_STORE_RESERVED_ACCOUNT,
                        FREE_ACCOUNT,
                        remaining_reserved_bytes,
                    )
                ],
                cause=reason,
            )
        execution.hbm_foreground_store_reserved_bytes = 0
        execution.hbm_foreground_store_target_gpu_id = None
        self.primary_pools[group.target_gpu_id].release_pin(span_id)
        del self.foreground_store_restore_by_span[span_id]
        if unregister_pristine:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("foreground Store abort lost scheduler driver")
            driver.unregister_pristine_suspended(span_id)
        self.foreground_store_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "FOREGROUND_STORE_RESTORE_ABORTED",
                "span_id": span_id,
                "target_gpu_id": group.target_gpu_id,
                "reason": reason,
                "completed_segment_count": len(group.completed_transfer_ids),
                "segment_transfer_count": len(group.transfer_ids),
            }
        )
        return True

    def _active_primary_chunk_keys(self, gpu_id: str) -> set[str]:
        keys: set[str] = set()
        for execution in self.executions.values():
            if (
                execution.hbm_allocation_gpu_id != gpu_id
                or execution.hbm_allocated_bytes <= 0
                or execution.status
                not in {
                    _ExecutionStatus.RUNNING,
                    _ExecutionStatus.RECOVERING,
                    _ExecutionStatus.RESUMED,
                }
                or execution.compute_start_ns is None
                or execution.planned_complete_ns is None
                or not execution.chunks
            ):
                continue
            duration_ns = max(
                1,
                execution.planned_complete_ns - execution.compute_start_ns,
            )
            elapsed_ns = max(0, self.des.now_ns - execution.compute_start_ns)
            sealed_count = min(
                len(execution.chunks),
                len(execution.chunks) * elapsed_ns // duration_ns,
            )
            keys.update(chunk.key for chunk in execution.chunks[:sealed_count])
        return keys

    def _local_hbm_prefix_breakdown(
        self,
        gpu_id: str,
        execution: _SpanExecution,
        *,
        mutate_signals: bool,
        include_active_primary: bool = True,
    ) -> dict[str, int]:
        """Return Conductor-style continuous-prefix hits for one DP rank."""

        chunks = execution.chunks
        primary_pool = self.primary_pools[gpu_id]
        active_keys = self._active_primary_chunk_keys(gpu_id)
        inactive_keys = primary_pool.available_entry_keys
        peer_pool = self.peer_pools[gpu_id]
        peer_keys = set(peer_pool.entries) if self._reuse_visible("PEER_HBM") else set()
        peer_chunks = self._protection_chunks(execution, path="PEER_HBM")

        def continuous_prefix(keys: set[str], candidates: Sequence[_Chunk]) -> int:
            tokens = 0
            for chunk in candidates:
                if chunk.key not in keys:
                    break
                tokens += chunk.token_count
            return tokens

        active_primary_prefix = (
            continuous_prefix(active_keys, chunks) if include_active_primary else 0
        )
        inactive_primary_prefix = continuous_prefix(inactive_keys, chunks)
        # One route source must cover the whole adopted prefix.  Do not stitch
        # disjoint ACTIVE and inactive cache fragments into a fictitious hit.
        normal_prefix = max(active_primary_prefix, inactive_primary_prefix)
        peer_prefix = continuous_prefix(peer_keys, peer_chunks)
        local_prefix = max(normal_prefix, peer_prefix)
        normal_contribution = normal_prefix
        peer_contribution = max(0, local_prefix - normal_prefix)
        if mutate_signals:
            for chunk in chunks:
                if chunk.token_start >= normal_prefix:
                    break
                if chunk.key in inactive_keys:
                    primary_pool.contains(chunk.key, now_ns=self.des.now_ns)
            peer_tokens = 0
            for chunk in peer_chunks:
                if peer_tokens >= peer_prefix:
                    break
                peer_pool.contains(chunk.key, now_ns=self.des.now_ns)
                peer_tokens += chunk.token_count

        return {
            "active_primary_prefix_tokens": active_primary_prefix,
            "inactive_reusable_prefix_tokens": inactive_primary_prefix,
            "normal_hbm_prefix_tokens": normal_prefix,
            "peer_backup_prefix_tokens": peer_prefix,
            "local_hbm_union_prefix_tokens": local_prefix,
            "normal_hbm_contribution_tokens": normal_contribution,
            "peer_backup_contribution_tokens": peer_contribution,
        }

    def _route_gpu(
        self,
        span_id: str,
        *,
        route_version: int,
        required_hbm_bytes: int = 0,
        recovery: bool = False,
        preferred_gpu_id: str | None = None,
    ) -> str:
        if required_hbm_bytes < 0:
            raise ValueError("required HBM bytes must be non-negative")
        healthy = tuple(
            gpu
            for gpu in self.gpu_ids
            if gpu not in self.failed_gpu_ids
            and self._foreground_reclaimable_hbm_bytes(gpu) >= required_hbm_bytes
        )
        if not healthy:
            raise ExperimentError("no healthy modeled GPU has enough reclaimable HBM")
        preferred_destination_id = (
            preferred_gpu_id if preferred_gpu_id in healthy else None
        )
        peer_source_gpu_id = (
            preferred_gpu_id
            if (
                recovery
                and preferred_gpu_id is not None
                and preferred_gpu_id not in self.failed_gpu_ids
            )
            else None
        )
        digest = hashlib.sha256(f"{self.seed}:{span_id}:{route_version}".encode()).digest()
        hashed = healthy[int.from_bytes(digest[:8], "big") % len(healthy)]
        execution = self.executions[span_id]
        chunks = execution.chunks
        scored_gpu_ids = set(healthy)
        if peer_source_gpu_id is not None:
            scored_gpu_ids.add(peer_source_gpu_id)
        local_scores = {
            gpu_id: self._local_hbm_prefix_breakdown(
                gpu_id,
                execution,
                mutate_signals=False,
                # Initial requests can read a sealed ACTIVE prefix through a
                # read-only local alias.  Recovery still uses only explicitly
                # reservable inactive/Peer/Store sources.
                include_active_primary=not recovery,
            )
            for gpu_id in scored_gpu_ids
        }
        store_prefix = (
            self._store_lookup_prefix_tokens(
                (
                    self._protection_chunks(execution, path="STORE_DRAM")
                    if self._formal_policy_enabled()
                    else chunks
                ),
                now_ns=self.des.now_ns,
                mutate_signals=False,
            )
            if self._reuse_visible("STORE_DRAM")
            else 0
        )
        remote_peer_prefix = 0
        if (
            recovery
            and peer_source_gpu_id is not None
            and self._reuse_visible("PEER_HBM")
        ):
            remote_peer_prefix = int(
                local_scores[peer_source_gpu_id]["peer_backup_prefix_tokens"]
            )
            if self.continuous_batch_enabled:
                remote_peer_prefix = _source_chunk_page_aligned_prefix(
                    self._protection_chunks(execution, path="PEER_HBM"),
                    remote_peer_prefix,
                    logical_page_tokens=16,
                )
        candidates: dict[str, dict[str, int | str]] = {}
        for gpu_id in healthy:
            local = local_scores[gpu_id]
            normal_prefix = local["normal_hbm_contribution_tokens"]
            peer_prefix = local["peer_backup_prefix_tokens"]
            candidate_store_prefix = store_prefix
            if self.continuous_batch_enabled:
                normal_prefix = _source_chunk_page_aligned_prefix(
                    chunks,
                    normal_prefix,
                    logical_page_tokens=16,
                )
                peer_prefix = (
                    _source_chunk_page_aligned_prefix(
                        self._protection_chunks(execution, path="PEER_HBM"),
                        peer_prefix,
                        logical_page_tokens=16,
                    )
                    if recovery
                    else 0
                )
                candidate_store_prefix = _source_chunk_page_aligned_prefix(
                    (
                        self._protection_chunks(execution, path="STORE_DRAM")
                        if self._formal_policy_enabled()
                        else chunks
                    ),
                    candidate_store_prefix,
                    logical_page_tokens=16,
                )
            local_prefix = max(normal_prefix, peer_prefix)
            remote_peer_for_gpu = (
                remote_peer_prefix
                if recovery and peer_source_gpu_id is not None
                else 0
            )
            covered_prefix = max(local_prefix, remote_peer_for_gpu)
            effective_prefix = max(covered_prefix, candidate_store_prefix)
            peer_d2d_bytes = 0
            peer_d2d_ns = 0
            if (
                recovery
                and peer_source_gpu_id is not None
                and gpu_id != peer_source_gpu_id
                and remote_peer_for_gpu > local_prefix
            ):
                peer_d2d_bytes = _prefix_bytes_between(
                    chunks,
                    local_prefix,
                    remote_peer_for_gpu,
                )
                peer_d2d_ns = _transfer_duration_ns(
                    peer_d2d_bytes,
                    self.parameters.peer_bandwidth_bytes_per_second,
                    self.parameters.transfer_setup_ns,
                )
            source = (
                "LOCAL_HBM_UNION"
                if local_prefix > 0
                and normal_prefix > 0
                and peer_prefix > normal_prefix
                and local_prefix >= max(candidate_store_prefix, remote_peer_for_gpu)
                else "NORMAL_HBM"
                if local_prefix > 0
                and normal_prefix > 0
                and normal_prefix >= peer_prefix
                and local_prefix >= max(candidate_store_prefix, remote_peer_for_gpu)
                else "PEER_HBM"
                if covered_prefix > 0
                and covered_prefix >= candidate_store_prefix
                and (
                    local_prefix >= candidate_store_prefix
                    or remote_peer_for_gpu >= candidate_store_prefix
                )
                else "STORE_DRAM"
                if candidate_store_prefix > covered_prefix
                else "NONE"
            )
            store_bytes = (
                _prefix_bytes_between(
                    chunks,
                    covered_prefix,
                    candidate_store_prefix,
                )
                if source == "STORE_DRAM"
                else 0
            )
            store_restore_ns = _transfer_duration_ns(
                store_bytes,
                self._store_restore_bandwidth_bytes_per_second(),
                self.parameters.transfer_setup_ns,
            )
            compute_duration_ns = _duration_after_prefix_reuse(
                execution.metadata,
                max(1, execution.base_duration_ns),
                effective_prefix,
            )
            ready_ns = self.des.now_ns + max(store_restore_ns, peer_d2d_ns)
            continuous_load: Mapping[str, int] | None = None
            if self.continuous_batch_enabled:
                driver = self.continuous_batch_driver
                if driver is None:
                    raise ExperimentError("continuous route lost its scheduler driver")
                continuous_load = driver.target_load_snapshot(gpu_id)
                compute_start_ns = max(
                    ready_ns,
                    continuous_load["estimated_available_ns"],
                )
            else:
                compute_start_ns = self.compute[gpu_id].earliest_start(
                    ready_ns=ready_ns,
                    duration_ns=compute_duration_ns,
                )
            candidates[gpu_id] = {
                **local,
                "raw_normal_hbm_prefix_tokens": local[
                    "normal_hbm_contribution_tokens"
                ],
                "raw_peer_prefix_tokens": local["peer_backup_prefix_tokens"],
                "raw_store_prefix_tokens": store_prefix,
                "adoptable_normal_hbm_prefix_tokens": normal_prefix,
                "adoptable_peer_prefix_tokens": peer_prefix,
                "remote_peer_d2d_prefix_tokens": remote_peer_for_gpu,
                "peer_prefix_tokens": max(peer_prefix, remote_peer_for_gpu),
                "store_prefix_tokens": candidate_store_prefix,
                "effective_prefix_tokens": effective_prefix,
                "cache_source": source,
                "peer_d2d_bytes": peer_d2d_bytes,
                "peer_d2d_ns": peer_d2d_ns,
                "store_restore_bytes": store_bytes,
                "store_restore_ns": store_restore_ns,
                "compute_ready_ns": ready_ns,
                "queue_wait_ns": compute_start_ns - ready_ns,
                "estimated_compute_ns": compute_duration_ns,
                "estimated_completion_ns": compute_start_ns + compute_duration_ns,
                "continuous_resident_request_count": (
                    0
                    if continuous_load is None
                    else continuous_load["resident_request_count"]
                ),
                "continuous_pending_admission_count": (
                    0
                    if continuous_load is None
                    else continuous_load["pending_admission_count"]
                ),
                "continuous_active_forward_remaining_ns": (
                    0
                    if continuous_load is None
                    else continuous_load["active_forward_remaining_ns"]
                ),
                "continuous_queued_tokens": (
                    0
                    if continuous_load is None
                    else continuous_load["queued_tokens"]
                ),
                "foreground_reclaimable_hbm_bytes": (
                    self._foreground_reclaimable_hbm_bytes(gpu_id)
                ),
            }
        selected = hashed
        if self.profile.cache_aware_routing:
            self.cache_aware_route_evaluations += 1
            def route_key(gpu_id: str) -> tuple[int, int, int, int, int, str]:
                candidate = candidates[gpu_id]
                if recovery:
                    return (
                        int(candidate["estimated_completion_ns"]),
                        int(candidate["continuous_queued_tokens"]),
                        0 if gpu_id == preferred_destination_id else 1,
                        -int(candidate["effective_prefix_tokens"]),
                        int(candidate["queue_wait_ns"]),
                        gpu_id,
                    )
                return (
                    int(candidate["continuous_queued_tokens"]),
                    int(candidate["estimated_completion_ns"]),
                    -int(candidate["effective_prefix_tokens"]),
                    int(candidate["queue_wait_ns"]),
                    0 if gpu_id == preferred_gpu_id else 1,
                    gpu_id,
                )

            selected = min(
                healthy,
                key=route_key,
            )
            if selected != hashed:
                self.cache_aware_route_changes += 1
        selected_candidate = candidates[selected]
        self.route_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "span_id": span_id,
                "route_version": route_version,
                "selected_gpu_id": selected,
                "hashed_gpu_id": hashed,
                "cache_aware": self.profile.cache_aware_routing,
                "recovery_route": recovery,
                "preferred_gpu_id": preferred_gpu_id,
                "router_owner": "external_router",
                "index_owner": "mooncake_conductor",
                "selection_objective": (
                    "minimum_estimated_completion_ns_with_remote_peer_d2d"
                    if preferred_gpu_id is not None
                    and self.profile.cache_aware_routing
                    else "minimum_estimated_completion_ns"
                    if self.profile.cache_aware_routing
                    else "route_bound_peer_target"
                    if preferred_gpu_id is not None
                    else "stable_hash"
                ),
                "required_hbm_bytes": required_hbm_bytes,
                "continuous_prefix_stop_rule": "first_missing_policy_chunk",
                "selected_cache_source": selected_candidate["cache_source"],
                "selected_effective_prefix_tokens": selected_candidate[
                    "effective_prefix_tokens"
                ],
                "selected_store_restore_bytes": selected_candidate[
                    "store_restore_bytes"
                ],
                "selected_store_restore_ns": selected_candidate["store_restore_ns"],
                "normal_hbm_prefix_tokens_by_gpu": {
                    gpu_id: local_scores[gpu_id]["normal_hbm_prefix_tokens"]
                    for gpu_id in sorted(local_scores)
                },
                "peer_prefix_tokens_by_gpu": {
                    gpu_id: local_scores[gpu_id]["peer_backup_prefix_tokens"]
                    for gpu_id in sorted(local_scores)
                },
                "local_hbm_union_prefix_tokens_by_gpu": {
                    gpu_id: local_scores[gpu_id]["local_hbm_union_prefix_tokens"]
                    for gpu_id in sorted(local_scores)
                },
                "store_prefix_tokens": store_prefix,
                "candidates": {
                    gpu_id: candidates[gpu_id] for gpu_id in sorted(candidates)
                },
            }
        )
        return selected

    def _foreground_reclaimable_hbm_bytes(self, gpu_id: str) -> int:
        ledger = self.hbm_ledgers[gpu_id]
        return sum(
            ledger.bytes_in(account)
            for account in (
                FREE_ACCOUNT,
                HBM_INACTIVE_REUSABLE_ACCOUNT,
                HBM_PEER_PROTECTION_ACCOUNT,
                HBM_PEER_PENDING_ACCOUNT,
            )
        )

    def _store_restore_bandwidth_bytes_per_second(self) -> int:
        if self.parameters.store_transport in {
            TransportKind.PCIE,
            TransportKind.RDMA_GDR,
        }:
            return self.parameters.store_bandwidth_bytes_per_second
        fabric = (
            self.parameters.tcp_store_bandwidth_bytes_per_second
            if self.parameters.store_transport is TransportKind.TCP_HOST_STAGED
            else self.parameters.store_bandwidth_bytes_per_second
        )
        return min(fabric, self.parameters.host_staging_bandwidth_bytes_per_second)

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

    def _store_segment_for_chunk(self, chunk: _Chunk) -> str:
        if len(self.store_segment_ids) == 1:
            return self.store_segment_ids[0]
        digest = hashlib.sha256(f"store-placement:{chunk.key}".encode()).digest()
        return self.store_segment_ids[
            int.from_bytes(digest[:8], "big") % len(self.store_segment_ids)
        ]

    def _store_lookup_prefix_tokens(
        self,
        chunks: Sequence[_Chunk],
        *,
        now_ns: int,
        mutate_signals: bool,
    ) -> int:
        tokens = 0
        for chunk in chunks:
            pool = self.store_pools[self._store_segment_for_chunk(chunk)]
            present = (
                pool.contains(chunk.key, now_ns=now_ns)
                if mutate_signals
                else chunk.key in pool.entries
            )
            if not present:
                break
            tokens += chunk.token_count
        return tokens

    def _store_recovery_bytes_by_segment(
        self,
        execution: _SpanExecution,
        *,
        start_token: int,
        token_count: int,
    ) -> dict[str, int]:
        if token_count <= 0:
            return {}
        end_token = start_token + token_count
        covered_tokens = 0
        result: Counter[str] = Counter()
        for chunk in self._protection_chunks(execution, path="STORE_DRAM"):
            chunk_end = chunk.token_start + chunk.token_count
            if chunk_end <= start_token or chunk.token_start >= end_token:
                continue
            if chunk.token_start < start_token or chunk_end > end_token:
                raise ExperimentError(
                    "Store recovery range split a policy chunk boundary"
                )
            segment_id = self._store_segment_for_chunk(chunk)
            result[segment_id] += chunk.bytes
            covered_tokens += chunk.token_count
        if covered_tokens != token_count:
            raise ExperimentError("Store recovery range lost continuous-prefix tokens")
        return dict(sorted(result.items()))

    def _foreground_store_layout_by_segment(
        self,
        execution: _SpanExecution,
        *,
        start_token: int,
        token_count: int,
    ) -> dict[str, tuple[int, tuple[str, ...]]]:
        """Return exact allocated source blocks and read leases per Store segment."""

        if token_count <= 0:
            return {}
        end_token = start_token + token_count
        bytes_by_segment: Counter[str] = Counter()
        keys_by_segment: defaultdict[str, list[str]] = defaultdict(list)
        for chunk in self._protection_chunks(execution, path="STORE_DRAM"):
            chunk_end = chunk.token_start + chunk.token_count
            overlap_start = max(start_token, chunk.token_start)
            overlap_end = min(end_token, chunk_end)
            if overlap_start >= overlap_end:
                continue
            source_blocks = (
                (overlap_end + SOURCE_BLOCK_TOKENS - 1) // SOURCE_BLOCK_TOKENS
                - overlap_start // SOURCE_BLOCK_TOKENS
            )
            if source_blocks <= 0:
                raise ExperimentError("foreground Store interval lost source blocks")
            segment_id = self._store_segment_for_chunk(chunk)
            bytes_by_segment[segment_id] += (
                source_blocks * KV_BYTES_PER_SOURCE_BLOCK
            )
            keys_by_segment[segment_id].append(chunk.key)
        expected_bytes = _prefix_bytes_between(
            execution.chunks,
            start_token,
            end_token,
        )
        if sum(bytes_by_segment.values()) != expected_bytes:
            raise ExperimentError(
                "foreground Store segment layout diverged from allocated prefix bytes"
            )
        return {
            segment_id: (
                bytes_by_segment[segment_id],
                tuple(dict.fromkeys(keys_by_segment[segment_id])),
            )
            for segment_id in sorted(bytes_by_segment)
        }

    def _peer_target(self, *, source_gpu_id: str, span_id: str) -> str:
        healthy = tuple(gpu for gpu in self.gpu_ids if gpu not in self.failed_gpu_ids)
        if not self.profile.anti_colocation:
            if source_gpu_id not in healthy:
                raise ExperimentError("negative-control Peer target source is not healthy")
            return source_gpu_id
        execution = self.executions[span_id]
        designated = execution.designated_peer_gpu_id
        if (
            designated is not None
            and designated in healthy
            and designated != source_gpu_id
        ):
            return designated
        candidates = tuple(gpu for gpu in healthy if gpu != source_gpu_id)
        if not candidates:
            raise ExperimentError("Peer-HBM protection requires a healthy anti-colocated GPU")

        def target_key(gpu_id: str) -> tuple[int, int, int, str]:
            pool = self.peer_pools[gpu_id]
            free_quota_bytes = max(
                0,
                pool.capacity_bytes - pool.occupied_bytes - pool.pending_bytes,
            )
            digest = hashlib.sha256(
                f"peer-target:{self.seed}:{span_id}:{gpu_id}".encode()
            ).digest()
            return (
                -free_quota_bytes,
                self._active_request_count(gpu_id),
                int.from_bytes(digest[:8], "big"),
                gpu_id,
            )

        return min(candidates, key=target_key)

    def _active_request_count(self, gpu_id: str) -> int:
        return sum(
            execution.gpu_id == gpu_id
            and execution.status
            in {
                _ExecutionStatus.QUEUED,
                _ExecutionStatus.RUNNING,
                _ExecutionStatus.RECOVERING,
                _ExecutionStatus.RESUMED,
            }
            for execution in self.executions.values()
        )

    def _resident_primary_request_count(self, gpu_id: str) -> int:
        """Count executions that physically own primary KV on one GPU."""

        return sum(
            execution.hbm_allocation_gpu_id == gpu_id
            and execution.hbm_allocated_bytes > 0
            for execution in self.executions.values()
        )

    def _latch_aimd_foreground_pressure(
        self,
        gpu_id: str,
        requested_bytes: int,
        *,
        reason: str,
        force: bool = False,
        before_quota_decision: Callable[[], None] | None = None,
    ) -> bool:
        """OR-latch a design-defined primary-headroom/stall observation."""

        if requested_bytes < 0:
            raise ExperimentError("AIMD pressure request cannot be negative")
        if not self.profile.aimd_enabled or gpu_id not in self._aimd_pending_pressure:
            return False
        ledger = self.hbm_ledgers[gpu_id]
        free_bytes = ledger.bytes_in(FREE_ACCOUNT)
        inactive_bytes = ledger.bytes_in(HBM_INACTIVE_REUSABLE_ACCOUNT)
        primary_headroom = free_bytes + inactive_bytes
        shortfall = max(0, requested_bytes - primary_headroom)
        if not force and shortfall == 0:
            return False
        audited_shortfall = max(1, shortfall) if force else shortfall
        resident_with_contender = self._resident_primary_request_count(gpu_id) + 1
        observation = {
            "timestamp_ns": self.des.now_ns,
            "target_gpu_id": gpu_id,
            "reason": reason,
            "requested_primary_bytes": requested_bytes,
            "free_bytes_before_reclaim": free_bytes,
            "inactive_reusable_bytes_before_reclaim": inactive_bytes,
            "primary_headroom_bytes_before_reclaim": primary_headroom,
            "headroom_shortfall_bytes": shortfall,
            "resident_primary_request_count_with_contender": resident_with_contender,
        }
        self.hbm_pressure_observations.append(observation)
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_PRIMARY_HBM_PRESSURE_OBSERVED",
            observation,
        )
        if before_quota_decision is not None:
            before_quota_decision()
        self._apply_peer_quota_decision(
            target_gpu_id=gpu_id,
            foreground_pressure=True,
            foreground_shortfall_bytes=audited_shortfall,
            pressure_active_request_count=resident_with_contender,
            pressure_reasons=(reason,),
            update_basis="IMMEDIATE_PRESSURE_EVENT",
        )
        return True

    def _apply_peer_quota_decision(
        self,
        *,
        target_gpu_id: str,
        foreground_pressure: bool = False,
        foreground_shortfall_bytes: int = 0,
        pressure_active_request_count: int = 0,
        pressure_reasons: Sequence[str] = (),
        update_basis: str = "FIXED_GLOBAL_DES_CONTROL_WINDOW",
    ) -> None:
        if not self.profile.aimd_enabled:
            return
        if foreground_shortfall_bytes < 0:
            raise ExperimentError("AIMD foreground shortfall cannot be negative")
        if not foreground_pressure and foreground_shortfall_bytes != 0:
            raise ExperimentError("stable AIMD update cannot report a foreground shortfall")
        if pressure_active_request_count < 0:
            raise ExperimentError("AIMD pressure active-request count cannot be negative")
        if not foreground_pressure and pressure_active_request_count != 0:
            raise ExperimentError("stable AIMD update cannot report pressure activity")
        if not foreground_pressure and pressure_reasons:
            raise ExperimentError("stable AIMD update cannot report pressure reasons")
        state = self.aimd_states[target_gpu_id]
        if state.last_update_ns is not None and self.des.now_ns < state.last_update_ns:
            raise ExperimentError("AIMD state advanced beyond the GlobalDES clock")
        if state.last_update_ns == self.des.now_ns:
            previous = self._aimd_last_decisions.get(target_gpu_id)
            if previous is None or previous.timestamp_ns != self.des.now_ns:
                raise ExperimentError("same-timestamp AIMD state lost its decision")
            matching_event_index = next(
                (
                    index
                    for index in range(len(self.aimd_events) - 1, -1, -1)
                    if self.aimd_events[index]["target_id"] == target_gpu_id
                    and self.aimd_events[index]["timestamp_ns"] == self.des.now_ns
                ),
                None,
            )
            if matching_event_index is None:
                raise ExperimentError("same-timestamp AIMD event is missing")
            if not foreground_pressure:
                return
            if previous.foreground_pressure:
                latest_event = self.aimd_events[matching_event_index]
                latest_event["foreground_shortfall_bytes"] = max(
                    int(latest_event["foreground_shortfall_bytes"]),
                    foreground_shortfall_bytes,
                )
                latest_event["pressure_active_request_count"] = max(
                    int(latest_event["pressure_active_request_count"]),
                    pressure_active_request_count,
                )
                latest_event["pressure_resident_primary_count"] = latest_event[
                    "pressure_active_request_count"
                ]
                latest_event["pressure_reasons"] = sorted(
                    set(map(str, latest_event["pressure_reasons"]))
                    | set(pressure_reasons)
                )
                latest_event["coalesced_pressure_observation_count"] = int(
                    latest_event.get("coalesced_pressure_observation_count", 1)
                ) + 1
                return
            if self.aimd_events[matching_event_index]["fingerprint"] != previous.fingerprint:
                raise ExperimentError("same-timestamp stable AIMD event cannot be replaced")
            self.aimd_events.pop(matching_event_index)
            state = previous.previous_state
            self.aimd_states[target_gpu_id] = state
        pool = self.peer_pools[target_gpu_id]
        free_hbm_bytes_before_update = self.hbm_ledgers[target_gpu_id].bytes_in(
            FREE_ACCOUNT
        )
        decision = self.aimd.update(
            state,
            foreground_pressure=foreground_pressure,
            current_protection_bytes=pool.occupied_bytes + pool.pending_bytes,
            timestamp_ns=self.des.now_ns,
        )
        self.aimd_states[target_gpu_id] = decision.next_state
        self._aimd_last_decisions[target_gpu_id] = decision
        if decision.quota_bytes < pool.pending_bytes:
            for transfer_id, pending in sorted(tuple(self.pending_puts.items())):
                if pending.path != "PEER_HBM" or pending.target_gpu_id != target_gpu_id:
                    continue
                self._cancel_pending_protection_service(
                    transfer_id,
                    pending,
                    reason="AIMD_FOREGROUND_PRESSURE",
                )
                self._abort_pending_put_reservations(
                    pending,
                    pool=pool,
                    cause="AIMD_FOREGROUND_PRESSURE",
                    block_formal_path=False,
                )
                self._abort_transfer_from_task(
                    transfer_id,
                    task=pending.task,
                    reason="AIMD_FOREGROUND_PRESSURE",
                )
                del self.pending_puts[transfer_id]
                self._resolve_continuous_protection_batch(
                    span_id=pending.span_id,
                    batch_key=pending.continuous_batch_key,
                    committed=False,
                )
                self.protection_path_bypasses["PEER_HBM_AIMD_PRESSURE"] += 1
                if decision.quota_bytes >= pool.pending_bytes:
                    break
            if decision.quota_bytes < pool.pending_bytes:
                raise ExperimentError("AIMD quota cannot reclaim pending Peer-HBM bytes")
        formal_lifecycle: dict[str, object] | None = None
        if self._formal_policy_enabled():
            landlord = self._formal_landlord_for_pool(pool)
            capacity_preview = landlord.preview_capacity_change(
                decision.quota_bytes,
                latest_values=self._formal_latest_values(landlord),
            )
            resolution = landlord.apply_capacity_change(
                capacity_preview,
                cause=f"AEGIS_AIMD_{decision.action.value}",
            )
            pool.set_capacity_exact(
                decision.quota_bytes,
                victim_keys=tuple(
                    self._formal_chunk_metadata[item.chunk_id].physical_chunk.key
                    for item in resolution.released_entries
                ),
                proposed_rent=resolution.rent_after,
                now_ns=self.des.now_ns,
                cause=f"AEGIS_AIMD_{decision.action.value}",
            )
            self._formal_dirty_pool_ids.add(pool.pool_id)
            formal_lifecycle = resolution.to_canonical_json()
        else:
            pool.set_capacity(
                decision.quota_bytes,
                now_ns=self.des.now_ns,
                cause=f"AEGIS_AIMD_{decision.action.value}",
            )
        self._sync_peer_hbm_ledger(
            target_gpu_id,
            cause=f"AEGIS_AIMD_{decision.action.value}",
        )
        self.aimd_events.append(
            {
                **decision.to_dict(),
                "control_window_ns": self.aimd_control_window_ns,
                "update_basis": update_basis,
                "active_request_count": self._active_request_count(target_gpu_id),
                "pressure_active_request_count": pressure_active_request_count,
                "pressure_resident_primary_count": pressure_active_request_count,
                "pressure_reasons": list(pressure_reasons),
                "foreground_shortfall_bytes": foreground_shortfall_bytes,
                "free_hbm_bytes_before_update": free_hbm_bytes_before_update,
                "formal_algorithm2_capacity_lifecycle": formal_lifecycle,
            }
        )

    def _schedule_next_aimd_control_window(
        self,
        gpu_id: str,
        *,
        at_ns: int,
    ) -> None:
        if gpu_id in self._aimd_window_handles:
            raise ExperimentError("AIMD target already has a scheduled control window")
        handle = self.des.schedule_at(
            at_ns,
            EventKind.CONTROL_WINDOW,
            event_id=self._next_id(f"aimd-control-window:{gpu_id}"),
            payload={"target_gpu_id": gpu_id},
        )
        self._aimd_window_handles[gpu_id] = handle

    def _on_aimd_control_window(
        self,
        event: ScheduledEvent,
        _des: GlobalDES,
    ) -> None:
        gpu_id = _required_str(event.payload, "target_gpu_id")
        handle = self._aimd_window_handles.pop(gpu_id, None)
        if handle != EventHandle(event.event_id):
            raise ExperimentError("unknown or stale AIMD control window")
        foreground_pressure = self._aimd_pending_pressure[gpu_id]
        foreground_shortfall_bytes = self._aimd_pending_shortfall_bytes[gpu_id]
        pressure_active_request_count = (
            self._aimd_pending_pressure_active_requests[gpu_id]
        )
        pressure_reasons = tuple(sorted(self._aimd_pending_pressure_reasons[gpu_id]))
        self._aimd_pending_pressure[gpu_id] = False
        self._aimd_pending_shortfall_bytes[gpu_id] = 0
        self._aimd_pending_pressure_active_requests[gpu_id] = 0
        self._aimd_pending_pressure_reasons[gpu_id].clear()
        if gpu_id not in self.failed_gpu_ids:
            self._apply_peer_quota_decision(
                target_gpu_id=gpu_id,
                foreground_pressure=foreground_pressure,
                foreground_shortfall_bytes=foreground_shortfall_bytes,
                pressure_active_request_count=pressure_active_request_count,
                pressure_reasons=pressure_reasons,
            )
        if len(self._completed_span_ids) != len(self.executions):
            self._schedule_next_aimd_control_window(
                gpu_id,
                at_ns=self.des.now_ns + self.aimd_control_window_ns,
            )

    def _commit_hbm_moves(
        self,
        gpu_id: str,
        moves: Sequence[tuple[str, str, int]],
        *,
        cause: str,
        transfer_id: str | None = None,
    ) -> None:
        nonzero = tuple(item for item in moves if item[2] > 0)
        if not nonzero:
            return
        ledger = self.hbm_ledgers[gpu_id]
        transaction_id = self._next_id(f"hbm-transaction:{gpu_id}:{cause}")
        try:
            ResourceTransaction(
                event_id=transaction_id,
                timestamp_ns=self.des.now_ns,
                cause=cause,
                allocation_deltas=[
                    AllocationDelta(
                        resource_id=ledger.resource_id,
                        account_from=account_from,
                        account_to=account_to,
                        delta_bytes=delta_bytes,
                        allocation_id=f"{transaction_id}:delta-{index}",
                        transfer_id=transfer_id,
                    )
                    for index, (account_from, account_to, delta_bytes) in enumerate(
                        nonzero
                    )
                ],
            ).commit({ledger.resource_id: ledger}, journal=self.des.journal)
        except (KeyError, ValueError, RuntimeError) as error:
            raise ExperimentError(
                f"HBM transaction failed on {gpu_id}: {cause}"
            ) from error
        self.hbm_timelines[gpu_id].append(
            _capacity_ledger_snapshot(
                ledger,
                timestamp_ns=self.des.now_ns,
                cause=cause,
            )
        )

    def _commit_host_staging_move(
        self,
        *,
        resource_id: str,
        account_from: str,
        account_to: str,
        delta_bytes: int,
        cause: str,
        transfer_id: str,
    ) -> None:
        if delta_bytes <= 0:
            raise ExperimentError("Host staging transaction must move positive bytes")
        try:
            gpu_id, ledger = next(
                (gpu_id, ledger)
                for gpu_id, ledger in self.host_staging_ledgers.items()
                if ledger.resource_id == resource_id
            )
        except StopIteration as error:
            raise ExperimentError(f"unknown Host staging resource: {resource_id}") from error
        transaction_id = self._next_id(f"host-transaction:{resource_id}:{cause}")
        try:
            ResourceTransaction(
                event_id=transaction_id,
                timestamp_ns=self.des.now_ns,
                cause=cause,
                allocation_deltas=[
                    AllocationDelta(
                        resource_id=resource_id,
                        account_from=account_from,
                        account_to=account_to,
                        delta_bytes=delta_bytes,
                        allocation_id=f"host-staging:{transfer_id}",
                        transfer_id=transfer_id,
                    )
                ],
            ).commit({resource_id: ledger}, journal=self.des.journal)
        except (KeyError, ValueError, RuntimeError) as error:
            raise ExperimentError(
                f"Host staging transaction failed on {resource_id}: {cause}"
            ) from error
        self.host_staging_timelines[gpu_id].append(
            _capacity_ledger_snapshot(
                ledger,
                timestamp_ns=self.des.now_ns,
                cause=cause,
            )
        )

    def _acquire_transfer_overlays(self, task: TransferTask) -> None:
        transfer_id = task.metadata.transfer_id
        if transfer_id in self.active_source_pins or transfer_id in self.active_host_staging:
            raise ExperimentError("transfer overlays were acquired twice")
        self.active_source_pins[transfer_id] = {
            "source_resource_id": task.metadata.source.resource_id,
            "object_id": task.metadata.object_id,
            "bytes": task.metadata.total_bytes,
            "acquired_ns": self.des.now_ns,
        }
        self.source_pin_acquire_count += 1
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_TRANSFER_SOURCE_PIN_ACQUIRED",
            {
                "transfer_id": transfer_id,
                **self.active_source_pins[transfer_id],
                "capacity_double_charge": False,
            },
        )
        staging_resource_ids = tuple(
            resource_id
            for resource_id in (
                task.metadata.path.source_host_staging_resource_id,
                task.metadata.path.destination_host_staging_resource_id,
            )
            if resource_id is not None
        )
        if not staging_resource_ids:
            return
        if len(staging_resource_ids) != 1:
            del self.active_source_pins[transfer_id]
            raise ExperimentError("Aegis E2 path requires exactly one Host staging resource")
        staging_bytes = max(item.length_bytes for item in task.slices)
        resource_id = staging_resource_ids[0]
        try:
            self._commit_host_staging_move(
                resource_id=resource_id,
                account_from=FREE_ACCOUNT,
                account_to=HOST_TRANSFER_STAGING_ACCOUNT,
                delta_bytes=staging_bytes,
                cause="AEGIS_HOST_STAGING_ACQUIRE",
                transfer_id=transfer_id,
            )
        except Exception:
            del self.active_source_pins[transfer_id]
            raise
        self.active_host_staging[transfer_id] = (resource_id, staging_bytes)
        self.host_staging_acquire_count += 1

    def _release_transfer_overlays(self, task: TransferTask, *, reason: str) -> None:
        transfer_id = task.metadata.transfer_id
        pin = self.active_source_pins.pop(transfer_id, None)
        if pin is None:
            raise ExperimentError("transfer source pin is missing at release")
        staging = self.active_host_staging.pop(transfer_id, None)
        if staging is not None:
            resource_id, staging_bytes = staging
            self._commit_host_staging_move(
                resource_id=resource_id,
                account_from=HOST_TRANSFER_STAGING_ACCOUNT,
                account_to=FREE_ACCOUNT,
                delta_bytes=staging_bytes,
                cause="AEGIS_HOST_STAGING_RELEASE",
                transfer_id=transfer_id,
            )
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_TRANSFER_SOURCE_PIN_RELEASED",
            {
                "transfer_id": transfer_id,
                **pin,
                "reason": reason,
                "capacity_double_charge": False,
            },
        )

    def _bind_transfer_task_metadata(self, task: TransferTask) -> None:
        record = self._transfer_by_id[task.metadata.transfer_id]
        record.update(
            {
                "transport": task.metadata.path.transport.value,
                "rate_resource_ids": list(task.metadata.path.rate_resource_ids),
                "source_host_staging_resource_id": (
                    task.metadata.path.source_host_staging_resource_id
                ),
                "destination_host_staging_resource_id": (
                    task.metadata.path.destination_host_staging_resource_id
                ),
                "source_pin_required": True,
            }
        )

    def _sync_primary_hbm_ledger(self, gpu_id: str, *, cause: str) -> None:
        if gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed GPU normal-HBM account cannot be synchronized")
        pool = self.primary_pools[gpu_id]
        ledger = self.hbm_ledgers[gpu_id]
        current_bytes = ledger.bytes_in(HBM_INACTIVE_REUSABLE_ACCOUNT)
        target_bytes = pool.occupied_bytes
        moves: list[tuple[str, str, int]] = []
        if current_bytes > target_bytes:
            moves.append(
                (
                    HBM_INACTIVE_REUSABLE_ACCOUNT,
                    FREE_ACCOUNT,
                    current_bytes - target_bytes,
                )
            )
        elif current_bytes < target_bytes:
            moves.append(
                (
                    FREE_ACCOUNT,
                    HBM_INACTIVE_REUSABLE_ACCOUNT,
                    target_bytes - current_bytes,
                )
            )
        self._commit_hbm_moves(gpu_id, moves, cause=cause)

    def _sync_peer_hbm_ledger(self, gpu_id: str, *, cause: str) -> None:
        if gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed GPU Peer-HBM account cannot be synchronized")
        pool = self.peer_pools[gpu_id]
        ledger = self.hbm_ledgers[gpu_id]
        desired = {
            HBM_PEER_PROTECTION_ACCOUNT: pool.occupied_bytes,
            HBM_PEER_PENDING_ACCOUNT: pool.pending_bytes,
        }
        moves: list[tuple[str, str, int]] = []
        for account, target_bytes in desired.items():
            current_bytes = ledger.bytes_in(account)
            if current_bytes > target_bytes:
                moves.append((account, FREE_ACCOUNT, current_bytes - target_bytes))
        for account, target_bytes in desired.items():
            current_bytes = ledger.bytes_in(account)
            if current_bytes < target_bytes:
                moves.append((FREE_ACCOUNT, account, target_bytes - current_bytes))
        self._commit_hbm_moves(gpu_id, moves, cause=cause)

    def _fail_hbm_ledger(self, gpu_id: str) -> None:
        ledger = self.hbm_ledgers[gpu_id]
        moves = [
            (account, UNAVAILABLE_CAPACITY_ACCOUNT, value)
            for account, value in ledger.accounts.items()
            if account != UNAVAILABLE_CAPACITY_ACCOUNT and value > 0
        ]
        self._commit_hbm_moves(
            gpu_id,
            moves,
            cause="GPU_FAILURE_ALL_HBM_UNAVAILABLE",
        )
        if ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) != ledger.capacity_bytes:
            raise ExperimentError("failed GPU HBM ledger is not fully unavailable")

    def _reclaim_hbm_free_bytes(self, gpu_id: str, allocated_bytes: int) -> bool:
        """Try to free modeled HBM without preempting in-flight transfers."""

        ledger = self.hbm_ledgers[gpu_id]
        shortfall = allocated_bytes - ledger.bytes_in(FREE_ACCOUNT)
        primary_pool = self.primary_pools[gpu_id]
        if shortfall > 0 and primary_pool.evictable_bytes > 0:
            primary_pool.evict_at_least(
                min(shortfall, primary_pool.evictable_bytes),
                now_ns=self.des.now_ns,
                cause="CONDUCTOR_NORMAL_GPU_BLOCK_REMOVED_FOR_FOREGROUND_PRESSURE",
            )
            self._sync_primary_hbm_ledger(
                gpu_id,
                cause="FOREGROUND_KV_RECLAIM_INACTIVE_PRIMARY",
            )
        shortfall = allocated_bytes - ledger.bytes_in(FREE_ACCOUNT)
        if shortfall <= 0:
            return True
        pool = self.peer_pools[gpu_id]
        current_peer_bytes = ledger.bytes_in(
            HBM_PEER_PROTECTION_ACCOUNT
        ) + ledger.bytes_in(HBM_PEER_PENDING_ACCOUNT)
        projected_free = (
            ledger.bytes_in(FREE_ACCOUNT)
            + current_peer_bytes
            - pool.occupied_bytes
            - pool.pending_bytes
        )
        bytes_to_free = min(
            max(0, allocated_bytes - projected_free),
            pool.occupied_bytes,
        )
        if bytes_to_free > 0:
            if self._formal_policy_enabled():
                self._formal_evict_committed_at_least(
                    pool,
                    bytes_to_free,
                    cause="FOREGROUND_KV_RECLAIM_PEER",
                )
            else:
                pool.evict_at_least(
                    bytes_to_free,
                    now_ns=self.des.now_ns,
                    cause="FOREGROUND_KV_RECLAIM_PEER",
                )
            projected_free = (
                ledger.bytes_in(FREE_ACCOUNT)
                + current_peer_bytes
                - pool.occupied_bytes
                - pool.pending_bytes
            )
        if projected_free < 0:
            return False
        self._sync_peer_hbm_ledger(
            gpu_id,
            cause="FOREGROUND_KV_RECLAIM_PEER",
        )
        return ledger.bytes_in(FREE_ACCOUNT) >= allocated_bytes

    def _admit_peer_pool_to_shared_hbm(self, gpu_id: str) -> bool:
        """Materialize a Peer pool reservation only if shared HBM can hold it."""

        ledger = self.hbm_ledgers[gpu_id]
        pool = self.peer_pools[gpu_id]
        current_peer_bytes = ledger.bytes_in(
            HBM_PEER_PROTECTION_ACCOUNT
        ) + ledger.bytes_in(HBM_PEER_PENDING_ACCOUNT)
        desired_peer_bytes = pool.occupied_bytes + pool.pending_bytes
        additional_bytes = max(0, desired_peer_bytes - current_peer_bytes)
        shortfall = additional_bytes - ledger.bytes_in(FREE_ACCOUNT)
        primary_pool = self.primary_pools[gpu_id]
        if shortfall > 0 and primary_pool.evictable_bytes > 0:
            primary_pool.evict_at_least(
                min(shortfall, primary_pool.evictable_bytes),
                now_ns=self.des.now_ns,
                cause="PEER_HBM_ADMISSION_RECLAIM_INACTIVE_PRIMARY",
            )
            self._sync_primary_hbm_ledger(
                gpu_id,
                cause="PEER_HBM_ADMISSION_RECLAIM_INACTIVE_PRIMARY",
            )
        current_peer_bytes = ledger.bytes_in(
            HBM_PEER_PROTECTION_ACCOUNT
        ) + ledger.bytes_in(HBM_PEER_PENDING_ACCOUNT)
        desired_peer_bytes = pool.occupied_bytes + pool.pending_bytes
        if (
            desired_peer_bytes - current_peer_bytes
            > ledger.bytes_in(FREE_ACCOUNT)
        ):
            return False
        self._sync_peer_hbm_ledger(
            gpu_id,
            cause="AEGIS_PEER_HBM_DESTINATION_RESERVE",
        )
        return True

    def _preempt_peer_puts_for_foreground_hbm(
        self,
        gpu_id: str,
        allocated_bytes: int,
    ) -> bool:
        """Abort destination Peer copies until foreground KV can be admitted."""

        if self._reclaim_hbm_free_bytes(gpu_id, allocated_bytes):
            return True
        for _released_bytes in self._abort_pending_peer_puts_for_pressure(
            gpu_id,
            reason="FOREGROUND_HBM_PRESSURE",
        ):
            ledger = self.hbm_ledgers[gpu_id]
            pool = self.peer_pools[gpu_id]
            current_peer_bytes = ledger.bytes_in(
                HBM_PEER_PROTECTION_ACCOUNT
            ) + ledger.bytes_in(HBM_PEER_PENDING_ACCOUNT)
            desired_peer_bytes = pool.occupied_bytes + pool.pending_bytes
            if (
                desired_peer_bytes - current_peer_bytes
                <= ledger.bytes_in(FREE_ACCOUNT)
                and self._reclaim_hbm_free_bytes(gpu_id, allocated_bytes)
            ):
                return True
        return False

    def _abort_pending_peer_puts_for_pressure(
        self,
        gpu_id: str,
        *,
        reason: str,
    ) -> tuple[int, ...]:
        """Abort target-local pending Peer PUTs and expose safe committed tails."""

        released: list[int] = []
        for transfer_id, pending in sorted(tuple(self.pending_puts.items())):
            if pending.path != "PEER_HBM" or pending.target_gpu_id != gpu_id:
                continue
            self._cancel_pending_protection_service(
                transfer_id,
                pending,
                reason=reason,
            )
            released_bytes = self._abort_pending_put_reservations(
                pending,
                pool=self.peer_pools[gpu_id],
                cause=reason,
                block_formal_path=False,
            )
            if released_bytes != pending.bytes:
                raise ExperimentError("preempted Peer-HBM reserve bytes diverged")
            self._abort_transfer_from_task(
                transfer_id,
                task=pending.task,
                reason=reason,
            )
            del self.pending_puts[transfer_id]
            self._resolve_continuous_protection_batch(
                span_id=pending.span_id,
                batch_key=pending.continuous_batch_key,
                committed=False,
            )
            self.protection_path_bypasses["PEER_HBM_FOREGROUND_HBM_PRESSURE"] += 1
            released.append(released_bytes)
        return tuple(released)

    def _booking_for_compute_event(
        self,
        event: ScheduledEvent,
        *,
        expected_kinds: set[_ComputeKind],
        completion: bool,
    ) -> _ComputeBooking:
        span_id = _required_str(event.payload, "span_id")
        booking = self._compute_bookings_by_span.get(span_id)
        if booking is None:
            raise ExperimentError("compute event has no live booking")
        try:
            event_kind = _ComputeKind(_required_str(event.payload, "compute_kind"))
        except ValueError as error:
            raise ExperimentError("compute event has an unknown booking kind") from error
        expected_handle = (
            booking.completion_handle if completion else booking.start_handle
        )
        if (
            event_kind not in expected_kinds
            or booking.kind is not event_kind
            or _required_int(event.payload, "compute_generation")
            != booking.generation
            or _required_str(event.payload, "reservation_id")
            != booking.reservation_id
            or _required_int(event.payload, "route_version")
            != booking.route_version
            or expected_handle != EventHandle(event.event_id)
        ):
            raise ExperimentError("stale compute booking event executed")
        return booking

    def _finish_compute_booking(
        self,
        event: ScheduledEvent,
        *,
        expected_kinds: set[_ComputeKind],
    ) -> _ComputeBooking:
        booking = self._booking_for_compute_event(
            event,
            expected_kinds=expected_kinds,
            completion=True,
        )
        if not booking.started or booking.end_ns != self.des.now_ns:
            raise ExperimentError("compute completion violated its booked interval")
        if self._compute_bookings_by_span.pop(booking.span_id, None) is not booking:
            raise ExperimentError("compute booking registry diverged at completion")
        return booking

    def _on_recovery_compute_start(
        self, event: ScheduledEvent, _des: GlobalDES
    ) -> None:
        booking = self._booking_for_compute_event(
            event,
            expected_kinds={
                _ComputeKind.RECOVERY_PROMPT,
                _ComputeKind.RECOVERY_SILENT,
                _ComputeKind.RECOVERY_DECODE,
            },
            completion=False,
        )
        if booking.started or booking.start_ns != self.des.now_ns:
            raise ExperimentError("recovery compute start violated its booked interval")
        booking.started = True
        execution = self.executions[booking.span_id]
        if booking.kind is _ComputeKind.RECOVERY_PROMPT:
            execution.prompt_recompute_start_ns = self.des.now_ns
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                    "span_id": booking.span_id,
                    "route_version": booking.route_version,
                    "target_gpu_id": booking.gpu_id,
                    "recompute_tokens": execution.recompute_tokens,
                    "duration_ns": booking.duration_ns,
                }
            )
        elif booking.kind is _ComputeKind.RECOVERY_SILENT:
            execution.silent_replay_start_ns = self.des.now_ns
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "SILENT_REPLAY_START",
                    "span_id": booking.span_id,
                    "route_version": booking.route_version,
                    "target_gpu_id": booking.gpu_id,
                    "replayed_output_tokens": (
                        execution.committed_output_tokens_at_failure
                    ),
                    "duration_ns": booking.duration_ns,
                    "externally_emitted_tokens": 0,
                }
            )
        else:
            execution.resume_decode_start_ns = self.des.now_ns
        self._schedule_logical_failure_trigger(
            execution,
            gpu_id=booking.gpu_id,
            compute_start_ns=booking.start_ns,
            compute_end_ns=booking.end_ns,
        )

    def _on_hbm_primary_allocate(
        self, event: ScheduledEvent, _des: GlobalDES
    ) -> None:
        span_id = _required_str(event.payload, "span_id")
        gpu_id = _required_str(event.payload, "gpu_id")
        execution = self.executions[span_id]
        booking = self._booking_for_compute_event(
            event,
            expected_kinds={_ComputeKind.NORMAL},
            completion=False,
        )
        if booking.started or booking.start_ns != self.des.now_ns:
            raise ExperimentError("normal compute start violated its booked interval")
        if execution.hbm_allocation_handle != EventHandle(event.event_id):
            raise ExperimentError("stale primary-HBM allocation event executed")
        if (
            _required_int(event.payload, "route_version") != execution.route_version
            or execution.gpu_id != gpu_id
            or gpu_id in self.failed_gpu_ids
            or execution.hbm_allocated_bytes != 0
        ):
            raise ExperimentError("primary-HBM allocation owner is invalid")
        allocated_bytes = _tokens_to_allocated_bytes(execution.metadata.prompt_tokens)
        self._latch_aimd_foreground_pressure(
            gpu_id,
            allocated_bytes,
            reason="PRIMARY_HEADROOM_SHORTFALL",
        )
        if not self._preempt_peer_puts_for_foreground_hbm(gpu_id, allocated_bytes):
            self._latch_aimd_foreground_pressure(
                gpu_id,
                allocated_bytes,
                reason="ALLOCATION_OR_RECLAIM_STALL",
                force=True,
            )
            raise ExperimentError(
                "foreground primary KV cannot fit after reclaiming reusable and Peer HBM"
            )
        self._commit_hbm_moves(
            gpu_id,
            [(FREE_ACCOUNT, HBM_ACTIVE_PRIMARY_ACCOUNT, allocated_bytes)],
            cause="REQUEST_PRIMARY_KV_ALLOCATE",
        )
        execution.hbm_allocated_bytes = allocated_bytes
        execution.hbm_allocation_gpu_id = gpu_id
        execution.status = _ExecutionStatus.RUNNING
        booking.started = True
        self._schedule_logical_failure_trigger(
            execution,
            gpu_id=gpu_id,
            compute_start_ns=booking.start_ns,
            compute_end_ns=booking.end_ns,
        )

    def _schedule_compute(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        ready_ns: int,
        duration_ns: int,
    ) -> None:
        if self.continuous_batch_enabled:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("continuous scheduler capability lost its driver")
            restored_tokens = _logical_page_aligned_prefix(
                min(
                    execution.metadata.prompt_tokens,
                    execution.reused_primary_tokens + execution.reused_store_tokens,
                ),
                logical_page_tokens=16,
            )
            execution.gpu_id = gpu_id
            execution.status = _ExecutionStatus.QUEUED
            execution.scheduled_duration_ns = max(1, duration_ns)
            driver.submit(
                self._continuous_request_spec(
                    execution,
                    gpu_id=gpu_id,
                    release_ns=(
                        execution.released_ns
                        if execution.released_ns is not None
                        else self.des.now_ns
                    ),
                    restored_tokens=restored_tokens,
                )
            )
            return
        self._install_normal_compute(
            execution,
            gpu_id=gpu_id,
            ready_ns=ready_ns,
            duration_ns=duration_ns,
        )

    def _next_compute_generation(self, span_id: str) -> int:
        self._compute_booking_generations[span_id] += 1
        return self._compute_booking_generations[span_id]

    def _install_normal_compute(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        ready_ns: int,
        duration_ns: int,
    ) -> _ComputeBooking:
        span_id = execution.metadata.span_id
        if span_id in self._compute_bookings_by_span:
            raise ExperimentError("span already owns a live compute booking")
        reservation_id = self._next_id(
            f"compute:{span_id}:r{execution.route_version}"
        )
        reserved_duration_ns = max(1, duration_ns)
        reservation = self.compute[gpu_id].reserve(
            ready_ns=max(self.des.now_ns, ready_ns),
            duration_ns=reserved_duration_ns,
            reservation_id=reservation_id,
            cause="MODEL_FORWARD_OR_RECOVERY_REPLAY",
        )
        generation = self._next_compute_generation(span_id)
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
        hbm_handle = self.des.schedule_at(
            reservation.start_ns,
            EventKind.KV_BLOCK_ALLOCATE,
            event_id=self._next_id(f"hbm-allocate:{span_id}"),
            payload={
                "span_id": span_id,
                "route_version": execution.route_version,
                "gpu_id": gpu_id,
                "compute_kind": _ComputeKind.NORMAL.value,
                "compute_generation": generation,
                "reservation_id": reservation.reservation_id,
            },
        )
        execution.hbm_allocation_handle = hbm_handle
        handle = self.des.schedule_at(
            reservation.end_ns,
            EventKind.REQUEST_COMPLETE,
            event_id=self._next_id(f"complete:{span_id}"),
            payload={
                "span_id": span_id,
                "route_version": execution.route_version,
                "gpu_id": gpu_id,
                "compute_kind": _ComputeKind.NORMAL.value,
                "compute_generation": generation,
                "reservation_id": reservation.reservation_id,
            },
        )
        execution.completion_handle = handle
        booking = _ComputeBooking(
            span_id=span_id,
            route_version=execution.route_version,
            gpu_id=gpu_id,
            kind=_ComputeKind.NORMAL,
            ready_ns=ready_ns,
            duration_ns=reserved_duration_ns,
            reservation_id=reservation.reservation_id,
            start_ns=reservation.start_ns,
            end_ns=reservation.end_ns,
            generation=generation,
            start_handle=hbm_handle,
            completion_handle=handle,
            recovery_due_ns=None,
        )
        self._compute_bookings_by_span[span_id] = booking
        self._schedule_protection_puts(
            execution,
            source_gpu_id=gpu_id,
            compute_start_ns=reservation.start_ns,
            compute_end_ns=reservation.end_ns,
        )
        return booking

    @staticmethod
    def _compute_spec_from_booking(booking: _ComputeBooking) -> _ComputeSpec:
        return _ComputeSpec(
            span_id=booking.span_id,
            route_version=booking.route_version,
            gpu_id=booking.gpu_id,
            kind=booking.kind,
            ready_ns=booking.ready_ns,
            duration_ns=booking.duration_ns,
            recovery_due_ns=booking.recovery_due_ns,
            prior_start_ns=booking.start_ns,
            prior_end_ns=booking.end_ns,
            prior_reservation_id=booking.reservation_id,
        )

    def _cancel_failure_trigger_for_compute_rebook(self, span_id: str) -> None:
        schedule = self._failure_schedule_by_focus_span.get(span_id)
        if schedule is None or schedule.failure_id in self._failure_event_executed:
            return
        handle = self._failure_event_handles.pop(schedule.failure_id, None)
        if handle is not None and not self.des.cancel(
            handle,
            reason="RECOVERY_COMPUTE_PRIORITY_REBOOK",
        ):
            raise ExperimentError("logical failure trigger could not be rebooked")

    def _cancel_compute_booking_for_rebook(
        self, booking: _ComputeBooking
    ) -> _ComputeSpec:
        now_ns = self.des.now_ns
        execution = self.executions[booking.span_id]
        if booking.started or booking.start_ns < now_ns:
            raise ExperimentError("started compute booking cannot be rebooked")
        if execution.route_version != booking.route_version:
            raise ExperimentError("compute booking route version diverged")
        reservation = self.compute[booking.gpu_id].reservation(
            booking.reservation_id
        )
        if (
            reservation is None
            or reservation.start_ns != booking.start_ns
            or reservation.end_ns != booking.end_ns
        ):
            raise ExperimentError("compute booking lost its resource reservation")
        if booking.kind is _ComputeKind.NORMAL:
            if execution.hbm_allocated_bytes != 0:
                raise ExperimentError("unstarted normal compute owns active HBM")
            object_id = f"span:{booking.span_id}"
            if any(
                pending.task.metadata.object_id == object_id
                for pending in self.pending_puts.values()
            ):
                raise ExperimentError("unstarted normal compute owns a protection transfer")
            for plan_id, plan in sorted(tuple(self.pending_put_starts.items())):
                if plan.span_id != booking.span_id:
                    continue
                if not self.des.cancel(
                    plan.handle,
                    reason="RECOVERY_COMPUTE_PRIORITY_REBOOK",
                ):
                    raise ExperimentError("protection PUT start could not be rebooked")
                del self.pending_put_starts[plan_id]
            self._cancel_failure_trigger_for_compute_rebook(booking.span_id)
            if execution.hbm_allocation_handle != booking.start_handle:
                raise ExperimentError("normal compute start-handle ownership diverged")
        if execution.completion_handle != booking.completion_handle:
            raise ExperimentError("compute completion-handle ownership diverged")
        if not self.des.cancel(
            booking.start_handle,
            reason="RECOVERY_COMPUTE_PRIORITY_REBOOK",
        ):
            raise ExperimentError("compute start handle could not be rebooked")
        if not self.des.cancel(
            booking.completion_handle,
            reason="RECOVERY_COMPUTE_PRIORITY_REBOOK",
        ):
            raise ExperimentError("compute completion handle could not be rebooked")
        if self.compute[booking.gpu_id].cancel(booking.reservation_id) is None:
            raise ExperimentError("compute reservation could not be rebooked")
        if self._compute_bookings_by_span.pop(booking.span_id, None) is not booking:
            raise ExperimentError("compute booking registry diverged during rebook")
        execution.reservation_id = None
        execution.completion_handle = None
        if booking.kind is _ComputeKind.NORMAL:
            execution.hbm_allocation_handle = None
        return self._compute_spec_from_booking(booking)

    def _install_recovery_compute(self, spec: _ComputeSpec) -> _ComputeBooking:
        if spec.kind is _ComputeKind.NORMAL or spec.recovery_due_ns is None:
            raise ExperimentError("recovery installer received a normal compute spec")
        execution = self.executions[spec.span_id]
        if spec.span_id in self._compute_bookings_by_span:
            raise ExperimentError("span already owns a live recovery compute booking")
        if execution.route_version != spec.route_version:
            raise ExperimentError("stale route attempted recovery compute booking")
        if spec.gpu_id in self.failed_gpu_ids:
            raise ExperimentError("recovery compute targeted a failed GPU")
        cause_by_kind = {
            _ComputeKind.RECOVERY_PROMPT: "AEGIS_RECOVERY_PROMPT_SUFFIX_RECOMPUTE",
            _ComputeKind.RECOVERY_SILENT: "AEGIS_RECOVERY_SILENT_REPLAY",
            _ComputeKind.RECOVERY_DECODE: "AEGIS_RECOVERY_REMAINING_DECODE",
        }
        completion_by_kind = {
            _ComputeKind.RECOVERY_PROMPT: EventKind.RECOVERY_RECOMPUTE_COMPLETE,
            _ComputeKind.RECOVERY_SILENT: EventKind.SILENT_REPLAY_COMPLETE,
            _ComputeKind.RECOVERY_DECODE: EventKind.REQUEST_COMPLETE,
        }
        reservation = self.compute[spec.gpu_id].reserve(
            ready_ns=max(self.des.now_ns, spec.ready_ns),
            duration_ns=spec.duration_ns,
            reservation_id=self._next_id(
                f"{spec.kind.value.lower()}:{spec.span_id}:r{spec.route_version}"
            ),
            cause=cause_by_kind[spec.kind],
        )
        generation = self._next_compute_generation(spec.span_id)
        common_payload = {
            "span_id": spec.span_id,
            "route_version": spec.route_version,
            "target_gpu_id": spec.gpu_id,
            "gpu_id": spec.gpu_id,
            "compute_kind": spec.kind.value,
            "compute_generation": generation,
            "reservation_id": reservation.reservation_id,
        }
        start_handle = self.des.schedule_at(
            reservation.start_ns,
            EventKind.RESOURCE_RESERVE,
            event_id=self._next_id(f"recovery-compute-start:{spec.span_id}"),
            payload=common_payload,
        )
        completion_handle = self.des.schedule_at(
            reservation.end_ns,
            completion_by_kind[spec.kind],
            event_id=self._next_id(f"recovery-compute-complete:{spec.span_id}"),
            payload=common_payload,
        )
        booking = _ComputeBooking(
            span_id=spec.span_id,
            route_version=spec.route_version,
            gpu_id=spec.gpu_id,
            kind=spec.kind,
            ready_ns=spec.ready_ns,
            duration_ns=spec.duration_ns,
            reservation_id=reservation.reservation_id,
            start_ns=reservation.start_ns,
            end_ns=reservation.end_ns,
            generation=generation,
            start_handle=start_handle,
            completion_handle=completion_handle,
            recovery_due_ns=spec.recovery_due_ns,
        )
        self._compute_bookings_by_span[spec.span_id] = booking
        execution.gpu_id = spec.gpu_id
        execution.compute_start_ns = reservation.start_ns
        execution.planned_complete_ns = reservation.end_ns
        execution.reservation_id = reservation.reservation_id
        execution.completion_handle = completion_handle
        execution.scheduled_duration_ns = spec.duration_ns
        if spec.kind is _ComputeKind.RECOVERY_PROMPT:
            execution.prompt_recompute_start_ns = reservation.start_ns
        elif spec.kind is _ComputeKind.RECOVERY_SILENT:
            execution.silent_replay_start_ns = reservation.start_ns
        else:
            execution.resume_decode_start_ns = reservation.start_ns
            execution.status = _ExecutionStatus.RESUMED
            for recovery_event in reversed(self.recovery_events):
                if (
                    recovery_event.get("event") == "RECOVERY_ATOMIC_ACTIVATION"
                    and recovery_event.get("span_id") == spec.span_id
                    and recovery_event.get("route_version") == spec.route_version
                ):
                    recovery_event["decode_start_ns"] = reservation.start_ns
                    break
        return booking

    def _install_compute_spec(self, spec: _ComputeSpec) -> _ComputeBooking:
        execution = self.executions[spec.span_id]
        if spec.kind is _ComputeKind.NORMAL:
            return self._install_normal_compute(
                execution,
                gpu_id=spec.gpu_id,
                ready_ns=max(self.des.now_ns, spec.ready_ns),
                duration_ns=spec.duration_ns,
            )
        return self._install_recovery_compute(spec)

    def _book_ready_recovery_compute(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        kind: _ComputeKind,
        duration_ns: int,
    ) -> _ComputeBooking:
        if kind is _ComputeKind.NORMAL or duration_ns <= 0:
            raise ExperimentError("recovery compute booking requires a positive phase")
        if execution.failure_at_ns is None:
            raise ExperimentError("recovery compute lacks a failure observation time")
        span_id = execution.metadata.span_id
        if span_id in self._compute_bookings_by_span:
            raise ExperimentError("recovery phase started with another live booking")
        now_ns = self.des.now_ns
        recovery_due_ns = (
            execution.failure_at_ns
            + self._remaining_ideal_slack_ns(
                execution,
                at_ns=execution.failure_at_ns,
            )
        )
        current_spec = _ComputeSpec(
            span_id=span_id,
            route_version=execution.route_version,
            gpu_id=gpu_id,
            kind=kind,
            ready_ns=now_ns,
            duration_ns=duration_ns,
            recovery_due_ns=recovery_due_ns,
            prior_start_ns=now_ns,
            prior_end_ns=now_ns + duration_ns,
            prior_reservation_id=f"new:{kind.value}:{span_id}",
        )
        victims = sorted(
            (
                booking
                for booking in self._compute_bookings_by_span.values()
                if booking.gpu_id == gpu_id
                and not booking.started
                and booking.start_ns >= now_ns
            ),
            key=lambda item: (item.start_ns, item.end_ns, item.reservation_id),
        )
        old_intervals = {
            booking.span_id: (booking.start_ns, booking.end_ns)
            for booking in victims
        }
        specs = [
            self._cancel_compute_booking_for_rebook(booking)
            for booking in victims
        ]
        specs.append(current_spec)
        ordered_specs = sorted(
            specs,
            key=lambda item: _compute_rebook_priority_key(item, now_ns=now_ns),
        )
        installed = [self._install_compute_spec(spec) for spec in ordered_specs]
        self._schedule_ready_future_failure_triggers()
        audit_entries = []
        for spec, booking in zip(ordered_specs, installed, strict=True):
            remaining_slack_ns = (
                None
                if spec.recovery_due_ns is None
                else max(0, spec.recovery_due_ns - now_ns)
            )
            audit_entries.append(
                {
                    "span_id": spec.span_id,
                    "route_version": spec.route_version,
                    "kind": spec.kind.value,
                    "priority_key": list(
                        _compute_rebook_priority_key(spec, now_ns=now_ns)
                    ),
                    "ideal_cpm_slack_ns": (
                        None
                        if spec.kind is _ComputeKind.NORMAL
                        else self.algorithm1_cpm.timing(spec.span_id).slack_ns
                    ),
                    "recovery_due_ns": spec.recovery_due_ns,
                    "remaining_slack_at_ready_ns": remaining_slack_ns,
                    "old_start_ns": old_intervals.get(spec.span_id, (None, None))[0],
                    "old_end_ns": old_intervals.get(spec.span_id, (None, None))[1],
                    "new_start_ns": booking.start_ns,
                    "new_end_ns": booking.end_ns,
                    "generation": booking.generation,
                }
            )
        audit = {
            "timestamp_ns": now_ns,
            "event": "RECOVERY_COMPUTE_PRIORITY_REBOOK",
            "trigger_span_id": span_id,
            "trigger_kind": kind.value,
            "target_gpu_id": gpu_id,
            "rebooked_normal_count": sum(
                spec.kind is _ComputeKind.NORMAL for spec in specs
            ),
            "ordered_bookings": audit_entries,
            "non_preemptive": True,
            "ready_recovery_order": "IDEAL_CPM_REMAINING_SLACK_DUE_TIME",
            "scheduler_extension": "RECOVERY_OVER_UNSTARTED_NORMAL_COMPUTE",
            "started_compute_preempted": False,
            "transfer_priority_changed": False,
        }
        self.compute_rebook_events.append(audit)
        self.des.journal.append(now_ns, "AEGIS_RECOVERY_COMPUTE_REBOOK", audit)
        return self._compute_bookings_by_span[span_id]

    def _schedule_continuous_logical_failure_trigger(
        self,
        execution: _SpanExecution,
        *,
        step: _ContinuousFailureStep,
        not_before_ns: int | None = None,
    ) -> None:
        """Resolve a failure at the first scheduler-visible token crossing."""

        schedule = self._failure_schedule_by_focus_span.get(execution.metadata.span_id)
        if schedule is None:
            return
        if schedule.failure_id in self._failure_event_executed:
            return
        if schedule.failure_id in self._failure_event_handles:
            return
        failure_plan = self.failure_schedule
        if failure_plan is None:
            raise ExperimentError("continuous failure trigger lost its containing plan")
        if (
            step.span_id != execution.metadata.span_id
            or step.route_version != execution.route_version
            or step.gpu_id != execution.gpu_id
            or step.gpu_id in self.failed_gpu_ids
            or step.start_ns >= step.end_ns
        ):
            raise ExperimentError("continuous failure step lost its live route authority")
        total_tokens = execution.metadata.prompt_tokens + execution.metadata.output_tokens
        if not (
            0
            <= step.num_computed_tokens_before
            < step.num_computed_tokens_after
            <= total_tokens
        ):
            raise ExperimentError("continuous failure step has invalid token progress")
        threshold_numerator = total_tokens * schedule.trigger_progress_per_mille
        threshold_denominator = 1_000
        before_numerator = step.num_computed_tokens_before * threshold_denominator
        after_numerator = step.num_computed_tokens_after * threshold_denominator
        crosses_in_step = before_numerator < threshold_numerator <= after_numerator
        crossing_evidence = self._continuous_failure_crossing_evidence.get(
            schedule.failure_id
        )
        if crosses_in_step and crossing_evidence is None:
            crossing_evidence = {
                "scheduler_step_id": step.scheduler_step_id,
                "route_version": step.route_version,
                "target_gpu_id": step.gpu_id,
                "step_start_ns": step.start_ns,
                "step_end_ns": step.end_ns,
                "num_computed_tokens_before": step.num_computed_tokens_before,
                "num_computed_tokens_after": step.num_computed_tokens_after,
            }
            self._continuous_failure_crossing_evidence[
                schedule.failure_id
            ] = crossing_evidence
        prior_failure_ids = {
            event.failure_id
            for event in failure_plan.events[: schedule.event_index]
        }
        if not prior_failure_ids.issubset(self._failure_event_executed):
            if crosses_in_step:
                self.des.journal.append(
                    self.des.now_ns,
                    "AEGIS_CONTINUOUS_FAILURE_THRESHOLD_DEFERRED",
                    {
                        "failure_id": schedule.failure_id,
                        "focus_span_id": schedule.focus_span_id,
                        "prior_failure_ids": sorted(prior_failure_ids),
                        "executed_prior_failure_ids": sorted(
                            prior_failure_ids & self._failure_event_executed
                        ),
                        **cast(dict[str, object], crossing_evidence),
                    },
                )
            return
        if crossing_evidence is None:
            if threshold_numerator > after_numerator:
                return
            crossing_evidence = {
                "scheduler_step_id": step.scheduler_step_id,
                "route_version": step.route_version,
                "target_gpu_id": step.gpu_id,
                "step_start_ns": step.start_ns,
                "step_end_ns": step.end_ns,
                "num_computed_tokens_before": step.num_computed_tokens_before,
                "num_computed_tokens_after": step.num_computed_tokens_after,
                "crossing_observed_after_order_gate": True,
            }
            self._continuous_failure_crossing_evidence[
                schedule.failure_id
            ] = crossing_evidence

        step_duration_ns = step.end_ns - step.start_ns
        crossing_is_current_step = (
            crossing_evidence.get("scheduler_step_id") == step.scheduler_step_id
            and crossing_evidence.get("route_version") == step.route_version
        )
        if crosses_in_step and crossing_is_current_step:
            interpolation_numerator = threshold_numerator - before_numerator
            interpolation_denominator = (
                step.num_computed_tokens_after - step.num_computed_tokens_before
            ) * threshold_denominator
            offset_ns = min(
                step_duration_ns - 1,
                step_duration_ns
                * interpolation_numerator
                // interpolation_denominator,
            )
            resolved_at_ns = step.start_ns + offset_ns
            resolution_mode = "FIRST_TOKEN_THRESHOLD_CROSSING"
        else:
            interpolation_numerator = 0
            interpolation_denominator = 1
            offset_ns = 0
            resolved_at_ns = step.start_ns
            resolution_mode = "ORDERED_DEFERRED_ACTIVE_STEP"
        ordered_lower_bound_ns = max(
            self.des.now_ns,
            step.start_ns if not_before_ns is None else not_before_ns,
        )
        if ordered_lower_bound_ns > resolved_at_ns:
            resolution_mode = "ORDERED_DEFERRED_ACTIVE_STEP"
        resolved_at_ns = max(resolved_at_ns, ordered_lower_bound_ns)
        if resolved_at_ns > step.end_ns:
            raise ExperimentError(
                "ordered continuous failure trigger missed its active scheduler step"
            )
        progress_evidence: dict[str, object] = {
            "kind": "CONTINUOUS_SCHEDULER_TOKEN_PROGRESS",
            "scheduler_step_id": step.scheduler_step_id,
            "route_version": step.route_version,
            "total_request_tokens": total_tokens,
            "prompt_tokens": execution.metadata.prompt_tokens,
            "output_tokens": execution.metadata.output_tokens,
            "num_computed_tokens_before": step.num_computed_tokens_before,
            "num_computed_tokens_after": step.num_computed_tokens_after,
            "trigger_progress_per_mille": schedule.trigger_progress_per_mille,
            "threshold_numerator": threshold_numerator,
            "threshold_denominator": threshold_denominator,
            "interpolation_numerator": interpolation_numerator,
            "interpolation_denominator": interpolation_denominator,
            "step_start_ns": step.start_ns,
            "step_end_ns": step.end_ns,
            "interpolated_offset_ns_floor": offset_ns,
            "resolved_at_ns": resolved_at_ns,
            "resolution_mode": resolution_mode,
            "rounding_policy": "FLOOR_NS_CLAMP_BEFORE_STEP_END",
            "first_crossing_evidence": crossing_evidence,
        }
        payload = schedule.to_dict()
        payload.update(
            {
                "reference_target_gpu_id": schedule.target_gpu_id,
                "target_gpu_id": step.gpu_id,
                "resolved_target_gpu_id": step.gpu_id,
                "resolved_at_ns": resolved_at_ns,
                "resolved_compute_start_ns": step.start_ns,
                "resolved_compute_end_ns": step.end_ns,
                "continuous_progress_evidence": progress_evidence,
            }
        )
        handle = self.des.schedule_at(
            resolved_at_ns,
            EventKind.FAILURE_INJECT,
            event_id=self._next_id(f"failure:{schedule.failure_id}"),
            payload=payload,
        )
        self._failure_event_handles[schedule.failure_id] = handle

    def _schedule_logical_failure_trigger(
        self,
        execution: _SpanExecution,
        *,
        gpu_id: str,
        compute_start_ns: int,
        compute_end_ns: int,
    ) -> None:
        """Resolve one event in the frozen multi-failure plan onto this cell."""

        schedule = self._failure_schedule_by_focus_span.get(execution.metadata.span_id)
        if schedule is None:
            return
        if schedule.failure_id in self._failure_event_executed:
            return
        if schedule.failure_id in self._failure_event_handles:
            return
        failure_plan = self.failure_schedule
        if failure_plan is None:
            raise ExperimentError("failure trigger lost its containing plan")
        prior_failure_ids = {
            event.failure_id
            for event in failure_plan.events[: schedule.event_index]
        }
        if not prior_failure_ids.issubset(self._failure_event_executed):
            return
        if execution.gpu_id != gpu_id or gpu_id in self.failed_gpu_ids:
            raise ExperimentError("logical failure focus has no live natural GPU route")
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
                "reference_target_gpu_id": schedule.target_gpu_id,
                "target_gpu_id": gpu_id,
                "resolved_target_gpu_id": gpu_id,
                "resolved_at_ns": resolved_at_ns,
                "resolved_compute_start_ns": compute_start_ns,
                "resolved_compute_end_ns": compute_end_ns,
            }
        )
        handle = self.des.schedule_at(
            resolved_at_ns,
            EventKind.FAILURE_INJECT,
            event_id=self._next_id(f"failure:{schedule.failure_id}"),
            payload=payload,
        )
        self._failure_event_handles[schedule.failure_id] = handle

    def _schedule_ready_future_failure_triggers(self) -> None:
        failure_plan = self.failure_schedule
        if failure_plan is None:
            return
        for schedule in self._failure_schedule_by_id.values():
            if (
                schedule.failure_id in self._failure_event_handles
                or schedule.failure_id in self._failure_event_executed
            ):
                continue
            execution = self.executions[schedule.focus_span_id]
            prior_failure_ids = {
                event.failure_id
                for event in failure_plan.events[: schedule.event_index]
            }
            if (
                prior_failure_ids.issubset(self._failure_event_executed)
                and execution.status is _ExecutionStatus.COMPLETED
            ):
                raise ExperimentError(
                    "future logical failure focus completed before its ordered trigger"
                )
            if self.continuous_batch_enabled:
                active_step = self._continuous_failure_active_steps.get(
                    schedule.focus_span_id
                )
                if active_step is not None:
                    self._schedule_continuous_logical_failure_trigger(
                        execution,
                        step=active_step,
                        not_before_ns=self.des.now_ns,
                    )
                continue
            if (
                execution.status
                not in {
                    _ExecutionStatus.RUNNING,
                    _ExecutionStatus.RECOVERING,
                    _ExecutionStatus.RESUMED,
                }
                or execution.gpu_id is None
                or execution.compute_start_ns is None
                or execution.planned_complete_ns is None
            ):
                continue
            self._schedule_logical_failure_trigger(
                execution,
                gpu_id=execution.gpu_id,
                compute_start_ns=execution.compute_start_ns,
                compute_end_ns=execution.planned_complete_ns,
            )

    def _cancel_future_failure_trigger_for_span(
        self,
        span_id: str,
        *,
        executing_failure_id: str,
    ) -> None:
        schedule = self._failure_schedule_by_focus_span.get(span_id)
        if (
            schedule is None
            or schedule.failure_id == executing_failure_id
            or schedule.failure_id in self._failure_event_executed
        ):
            return
        handle = self._failure_event_handles.pop(schedule.failure_id, None)
        if handle is not None and not self.des.cancel(
            handle,
            reason="PRIOR_GPU_FAILURE_REROUTED_FUTURE_FOCUS_SPAN",
        ):
            raise ExperimentError("future failure trigger could not be canceled for reroute")

    def _on_request_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        route_version = _required_int(event.payload, "route_version")
        if route_version != execution.route_version:
            raise ExperimentError("stale route attempted output completion")
        zero_duration_compute = bool(event.payload.get("zero_duration_compute", False))
        if zero_duration_compute:
            if (
                _required_str(event.payload, "compute_kind")
                != _ComputeKind.RECOVERY_DECODE.value
                or span_id in self._compute_bookings_by_span
                or execution.completion_handle != EventHandle(event.event_id)
            ):
                raise ExperimentError("zero-duration decode completion is invalid")
        else:
            self._finish_compute_booking(
                event,
                expected_kinds={
                    _ComputeKind.NORMAL,
                    _ComputeKind.RECOVERY_DECODE,
                },
            )
        if execution.status in {_ExecutionStatus.FENCED, _ExecutionStatus.COMPLETED}:
            raise ExperimentError("fenced or completed execution attempted output")
        gpu_id = execution.gpu_id
        if gpu_id is None:
            raise ExperimentError("request completion lacks a physical GPU")
        if gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed GPU attempted request completion")
        if (
            execution.hbm_allocated_bytes <= 0
            or execution.hbm_allocation_gpu_id != gpu_id
        ):
            raise ExperimentError("request completion lacks active primary-HBM ownership")
        self._commit_hbm_moves(
            gpu_id,
            [
                (
                    HBM_ACTIVE_PRIMARY_ACCOUNT,
                    FREE_ACCOUNT,
                    execution.hbm_allocated_bytes,
                )
            ],
            cause="REQUEST_PRIMARY_KV_RELEASE",
        )
        primary_pool = self.primary_pools[gpu_id]
        for chunk in execution.chunks:
            primary_pool.insert(
                chunk,
                score=Fraction(self.des.now_ns, 1),
                now_ns=self.des.now_ns,
                cause="CONDUCTOR_NORMAL_GPU_BLOCK_STORED",
            )
        self._sync_primary_hbm_ledger(
            gpu_id,
            cause="REQUEST_PRIMARY_KV_ACTIVE_TO_INACTIVE_REUSABLE",
        )
        execution.hbm_allocated_bytes = 0
        execution.hbm_allocation_gpu_id = None
        execution.status = _ExecutionStatus.COMPLETED
        execution.completed_ns = self.des.now_ns
        execution.reservation_id = None
        execution.completion_handle = None
        execution.external_output_emissions = execution.metadata.output_tokens
        self._completed_span_ids.add(span_id)
        self.causal.mark_completed(span_id)
        self._formal_drop_waiting_suffixes(span_id, reason="REQUEST_COMPLETE")
        self._update_residual_slack(
            execution.metadata.workflow_id,
            reason="REQUEST_COMPLETE",
            trigger_span_id=span_id,
        )
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
        if len(self._completed_span_ids) == len(self.executions):
            for target_gpu_id, handle in tuple(self._aimd_window_handles.items()):
                if not self.des.cancel(handle, reason="AIMD_WORKLOAD_COMPLETE"):
                    raise ExperimentError("final AIMD control window could not be canceled")
                del self._aimd_window_handles[target_gpu_id]

    def _formal_policy_enabled(self) -> bool:
        return bool(self.formal_landlords)

    def _protection_chunk(
        self,
        execution: _SpanExecution,
        chunks: Sequence[_Chunk],
        *,
        path: str,
    ) -> _Chunk:
        """Build one request-owned Algorithm-2 allocation unit per seal batch."""

        if path not in {"PEER_HBM", "STORE_DRAM"}:
            raise ExperimentError("unknown protection path")
        if not chunks:
            raise ExperimentError("protection allocation unit cannot be empty")
        first = chunks[0]
        return _Chunk(
            workflow_id=first.workflow_id,
            token_start=first.token_start,
            token_count=sum(chunk.token_count for chunk in chunks),
            bytes=sum(chunk.bytes for chunk in chunks),
            global_system_template=all(
                chunk.global_system_template for chunk in chunks
            ),
            key=sha256_json(
                {
                    "schema": "moonkvsim.aegiskv.content_addressed_protection_chunk.v1",
                    "path": path,
                    "token_start": first.token_start,
                    "content_keys": [chunk.key for chunk in chunks],
                }
            ),
        )

    def _protection_chunks(
        self,
        execution: _SpanExecution,
        *,
        path: str,
    ) -> tuple[_Chunk, ...]:
        if not self._formal_policy_enabled():
            return execution.chunks
        fraction = (
            self.profile.peer_replication_fraction
            if path == "PEER_HBM"
            else self.profile.store_fraction
        )
        candidate_count = _fraction_prefix_chunk_count(execution.chunks, fraction)
        return tuple(
            self._protection_chunk(
                execution,
                execution.chunks[begin:end],
                path=path,
            )
            for begin, end in _protection_batch_ranges(
                len(execution.chunks),
                candidate_count,
                global_prefix_chunk_count=_global_prefix_chunk_count(
                    execution.chunks[:candidate_count]
                ),
            )
        )

    def _formal_landlord_for_pool(self, pool: _ModeledPool) -> SlackLandlord:
        try:
            return self.formal_landlords[pool.pool_id]
        except KeyError as error:
            raise ExperimentError("formal pool has no SlackLandlord owner") from error

    def _formal_release_role_transition_suffixes(
        self,
        *,
        pool: _ModeledPool,
        activated_chunks: Sequence[_Chunk],
        cause: str,
    ) -> tuple[tuple[str, ...], int]:
        """Release request-safe suffixes containing reclassified physical chunks.

        A content alias may make the recovering request differ from the
        SlackLandlord request that owns the physical entry.  Role transition
        therefore resolves ownership by physical content key.  Since removing
        an interior/prefix entry would invalidate Algorithm 2's contiguous
        frontier, every owning request releases the complete suffix beginning
        at its earliest reclassified entry.  Additional suffix bytes are
        evicted from the physical pool, while the requested interval is moved
        to active recovery ownership by the caller.
        """

        landlord = self._formal_landlord_for_pool(pool)
        activated_keys = {chunk.key for chunk in activated_chunks}
        if not activated_keys:
            raise ExperimentError("formal role transition has no physical chunks")
        released_keys: set[str] = set()
        for request_id in sorted(self._formal_request_ids_by_pool[pool.pool_id]):
            entries = landlord.committed_entries(request_id)
            matching_indices = [
                index
                for index, entry in enumerate(entries)
                if self._formal_chunk_metadata[
                    entry.chunk_id
                ].physical_chunk.key
                in activated_keys
            ]
            if not matching_indices:
                continue
            suffix = entries[min(matching_indices) :]
            landlord.release_committed_suffix(
                request_id,
                tuple(entry.chunk_id for entry in suffix),
                cause=cause,
            )
            released_keys.update(
                self._formal_chunk_metadata[entry.chunk_id].physical_chunk.key
                for entry in suffix
            )
        if not activated_keys.issubset(released_keys):
            raise ExperimentError(
                "formal role transition could not resolve physical content ownership"
            )
        extra_keys = tuple(sorted(released_keys - activated_keys))
        extra_bytes = sum(pool.entries[key].chunk.bytes for key in extra_keys)
        self._formal_dirty_pool_ids.add(pool.pool_id)
        removed_keys = activated_keys | set(extra_keys)
        self._formal_content_alias_locations = {
            alias: location
            for alias, location in self._formal_content_alias_locations.items()
            if not (location[0] == pool.pool_id and location[1] in removed_keys)
        }
        return extra_keys, extra_bytes

    def _formal_present_global_indices(
        self,
        *,
        span_id: str,
        path: str,
        add_chunk_ids: frozenset[str] = frozenset(),
        remove_chunk_ids: frozenset[str] = frozenset(),
        remove_physical_keys: frozenset[str] = frozenset(),
        remove_physical_locations: frozenset[tuple[str, str]] = frozenset(),
    ) -> set[int]:
        present = {
            metadata.global_sequence_index
            for landlord in self.formal_landlords.values()
            for request_entry in landlord.committed_entries(span_id)
            if (metadata := self._formal_chunk_metadata[request_entry.chunk_id]).path
            == path
            and request_entry.chunk_id not in remove_chunk_ids
        }
        physical_pools = {
            pool.pool_id: pool
            for pool in (*self.peer_pools.values(), *self.store_pools.values())
        }
        present.update(
            global_index
            for (alias_span_id, alias_path, global_index), location in (
                self._formal_content_alias_locations.items()
            )
            if alias_span_id == span_id
            and alias_path == path
            and location not in remove_physical_locations
            and location[1] not in remove_physical_keys
            and location[0] in physical_pools
            and location[1] in physical_pools[location[0]].entries
        )
        for chunk_id in add_chunk_ids:
            metadata = self._formal_chunk_metadata[chunk_id]
            if metadata.span_id != span_id or metadata.path != path:
                raise ExperimentError("formal candidate belongs to another request path")
            present.add(metadata.global_sequence_index)
        return present

    def _formal_recovery_snapshot(
        self,
        *,
        span_id: str,
        path: str,
        pool: PolicyPool,
        add_chunk_ids: frozenset[str] = frozenset(),
        remove_chunk_ids: frozenset[str] = frozenset(),
        remove_physical_keys: frozenset[str] = frozenset(),
        remove_physical_locations: frozenset[tuple[str, str]] = frozenset(),
    ) -> RecoveryHarmSnapshot:
        execution = self.executions[span_id]
        completed = (
            execution.completed_ns is not None
            and execution.completed_ns <= self.des.now_ns
        )
        present = self._formal_present_global_indices(
            span_id=span_id,
            path=path,
            add_chunk_ids=add_chunk_ids,
            remove_chunk_ids=remove_chunk_ids,
            remove_physical_keys=remove_physical_keys,
            remove_physical_locations=remove_physical_locations,
        )
        prefix_count = 0
        while prefix_count in present:
            prefix_count += 1
        prefix = self._protection_chunks(execution, path=path)[:prefix_count]
        prefix_tokens = sum(chunk.token_count for chunk in prefix)
        prefix_bytes = sum(chunk.bytes for chunk in prefix)
        if completed or path == "PEER_HBM":
            load_ns = 0
        else:
            load_ns = _transfer_duration_ns(
                prefix_bytes,
                self._store_restore_bandwidth_bytes_per_second(),
                self.parameters.transfer_setup_ns,
            )
        weighted_total = max(
            1,
            execution.metadata.prompt_tokens + execution.metadata.output_tokens * 8,
        )
        prompt_recompute_ns = (
            0
            if completed
            else (
                execution.base_duration_ns
                * max(0, execution.metadata.prompt_tokens - prefix_tokens)
                // weighted_total
            )
        )
        committed_output_tokens = 0
        if (
            execution.compute_start_ns is not None
            and execution.planned_complete_ns is not None
            and self.des.now_ns > execution.compute_start_ns
        ):
            elapsed = min(
                self.des.now_ns - execution.compute_start_ns,
                execution.planned_complete_ns - execution.compute_start_ns,
            )
            duration = max(
                1,
                execution.planned_complete_ns - execution.compute_start_ns,
            )
            committed_output_tokens = min(
                execution.metadata.output_tokens,
                execution.metadata.output_tokens * elapsed // duration,
            )
        silent_replay_ns = (
            0
            if completed
            else execution.base_duration_ns
            * committed_output_tokens
            * 8
            // weighted_total
        )
        if execution.released_ns is None:
            raise ExperimentError("formal recovery harm lacks request release time")
        slack = self._published_slack_signal(span_id)
        return RecoveryHarmSnapshot(
            request_id=span_id,
            pool=pool,
            evaluated_at_ns=self.des.now_ns,
            slack=slack,
            recovery_time=RecoveryTimeBreakdown(
                load_ns=Fraction(load_ns, 1),
                prompt_suffix_recompute_ns=Fraction(prompt_recompute_ns, 1),
                silent_replay_ns=Fraction(silent_replay_ns, 1),
            ),
        )

    def _formal_candidate_value(
        self,
        metadata: _FormalChunkMetadata,
        *,
        landlord: SlackLandlord,
        resident: bool,
    ) -> tuple[RentalValue, AdmissionHarmDelta]:
        chunk_id = metadata.chunk_id
        prior_pending_chunk_ids = frozenset(
            pending_chunk_id
            for pending_chunk_id in landlord.pending_chunk_ids
            if (
                pending_metadata := self._formal_chunk_metadata[pending_chunk_id]
            ).span_id
            == metadata.span_id
            and pending_metadata.path == metadata.path
            and pending_metadata.pool_sequence_index < metadata.pool_sequence_index
        )
        before = self._formal_recovery_snapshot(
            span_id=metadata.span_id,
            path=metadata.path,
            pool=landlord.pool,
            add_chunk_ids=prior_pending_chunk_ids,
            remove_chunk_ids=frozenset({chunk_id}) if resident else frozenset(),
        )
        after = self._formal_recovery_snapshot(
            span_id=metadata.span_id,
            path=metadata.path,
            pool=landlord.pool,
            add_chunk_ids=(
                prior_pending_chunk_ids
                if resident
                else prior_pending_chunk_ids | frozenset({chunk_id})
            ),
        )
        gain = AdmissionHarmDelta(before=before, after=after)
        value = current_design_rental_value(
            candidate=SealedChunk(
                chunk_id=chunk_id,
                request_id=metadata.span_id,
                sequence_index=metadata.pool_sequence_index,
                allocated_bytes=metadata.physical_chunk.bytes,
            ),
            before=before,
            after=after,
            pool_rent=landlord.rent,
            frontier_version=max(1, self.des.now_ns),
        )
        return value, gain

    def _formal_latest_values(
        self,
        landlord: SlackLandlord,
    ) -> Mapping[str, RentalValue]:
        pool_id = next(
            pool_id
            for pool_id, candidate_landlord in self.formal_landlords.items()
            if candidate_landlord is landlord
        )
        request_ids = self._formal_request_ids_by_pool[pool_id]
        chunk_ids = tuple(
            entry.chunk_id
            for request_id in sorted(request_ids)
            for entry in landlord.committed_entries(request_id)
        )

        def resolve(chunk_id: str) -> RentalValue:
            value, _gain = self._formal_candidate_value(
                self._formal_chunk_metadata[chunk_id],
                landlord=landlord,
                resident=True,
            )
            return value

        return _LazyFormalLatestValues(chunk_ids, resolve)

    def _formal_alias_excluded_victim_ids(
        self,
        metadata: _FormalChunkMetadata,
        *,
        landlord: SlackLandlord,
    ) -> frozenset[str]:
        """Protect aliases and committed tails with an in-flight successor.

        A different request's pending transfer has already frozen the sequence
        index its completion must append.  Evicting that request's committed
        tail in the meantime would make the pending completion non-contiguous.
        Such entries are therefore ineligible victims until the path commits or
        aborts, in addition to the candidate's physical aliases.
        """

        candidate_locations = {
            location
            for (span_id, path, _global_index), location in (
                self._formal_content_alias_locations.items()
            )
            if span_id == metadata.span_id and path == metadata.path
        }
        pool_id = metadata.pool_id
        pending_request_ids = {
            span_id
            for span_id, path in self._formal_active_request_paths
            if path == metadata.path
        }
        physical_pools = {
            pool.pool_id: pool
            for pool in (*self.peer_pools.values(), *self.store_pools.values())
        }
        pinned_physical_keys = physical_pools[pool_id].pinned_entry_keys
        return frozenset(
            entry.chunk_id
            for request_id in self._formal_request_ids_by_pool[pool_id]
            for entry in landlord.committed_entries(request_id)
            if request_id in pending_request_ids
            or self._formal_chunk_metadata[entry.chunk_id].physical_chunk.key
            in pinned_physical_keys
            or (
                (
                    self._formal_chunk_metadata[entry.chunk_id].pool_id,
                    self._formal_chunk_metadata[entry.chunk_id].physical_chunk.key,
                )
                in candidate_locations
            )
        )

    def _formal_joint_loss(
        self,
        victims: tuple[RentalEntry, ...],
        *,
        path: str,
        pool: PolicyPool,
    ) -> VictimSetHarmDelta:
        victim_ids = frozenset(entry.chunk_id for entry in victims)
        victim_physical_keys = frozenset(
            self._formal_chunk_metadata[chunk_id].physical_chunk.key
            for chunk_id in victim_ids
        )
        victim_physical_locations = frozenset(
            (
                self._formal_chunk_metadata[chunk_id].pool_id,
                self._formal_chunk_metadata[chunk_id].physical_chunk.key,
            )
            for chunk_id in victim_ids
        )
        request_ids = sorted(
            {entry.request_id for entry in victims}
            | {
                alias_span_id
                for (alias_span_id, alias_path, _global_index), location in (
                    self._formal_content_alias_locations.items()
                )
                if alias_path == path and location in victim_physical_locations
            }
        )
        return VictimSetHarmDelta(
            before_by_request=tuple(
                self._formal_recovery_snapshot(
                    span_id=request_id,
                    path=path,
                    pool=pool,
                )
                for request_id in request_ids
            ),
            after_by_request=tuple(
                self._formal_recovery_snapshot(
                    span_id=request_id,
                    path=path,
                    pool=pool,
                    remove_chunk_ids=frozenset(
                        chunk_id
                        for chunk_id in victim_ids
                        if self._formal_chunk_metadata[chunk_id].span_id == request_id
                    ),
                    remove_physical_keys=victim_physical_keys,
                    remove_physical_locations=victim_physical_locations,
                )
                for request_id in request_ids
            ),
        )

    def _formal_contiguous_prefix_length(self, span_id: str, path: str) -> int:
        present = self._formal_present_global_indices(span_id=span_id, path=path)
        prefix_count = 0
        while prefix_count in present:
            prefix_count += 1
        return prefix_count

    def _formal_finish_request_path(
        self,
        span_id: str,
        path: str,
        *,
        block: bool,
        park_suffix: bool = False,
    ) -> None:
        if block and park_suffix:
            raise ExperimentError("formal path cannot be blocked and parked together")
        key = (span_id, path)
        self._formal_active_request_paths.discard(key)
        if park_suffix:
            self._formal_blocked_request_paths.discard(key)
            self.formal_policy_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "FORMAL_PREFIX_PARKED_FOR_RETRY",
                    "span_id": span_id,
                    "path": path,
                    "queued_suffix_count": len(
                        self._formal_waiting_put_starts.get(key, [])
                    ),
                }
            )
            return
        if block:
            self._formal_blocked_request_paths.add(key)
            queued = self._formal_waiting_put_starts.pop(key, [])
            for plan in queued:
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                self.protection_path_bypasses[f"{path}_FORMAL_PREFIX_BLOCKED"] += 1
                self.formal_policy_events.append(
                    {
                        "timestamp_ns": self.des.now_ns,
                        "event": "FORMAL_PREFIX_SUFFIX_BYPASS",
                        "span_id": span_id,
                        "path": path,
                        "plan_id": plan.plan_id,
                    }
                )
            return
        queue = self._formal_waiting_put_starts.get(key)
        if not queue:
            self._formal_waiting_put_starts.pop(key, None)
            return
        plan = queue.pop(0)
        if not queue:
            self._formal_waiting_put_starts.pop(key, None)
        plan.handle = self.des.schedule_at(
            self.des.now_ns,
            EventKind.PUT_START,
            event_id=f"resume:{plan.plan_id}:{self.des.now_ns}",
            payload={"plan_id": plan.plan_id, "path": plan.path},
        )
        self.pending_put_starts[plan.plan_id] = plan

    def _formal_drop_waiting_suffixes(self, span_id: str, *, reason: str) -> None:
        """Release parked suffix batches that can no longer extend a live frontier."""

        for path in ("PEER_HBM", "STORE_DRAM"):
            key = (span_id, path)
            queued = self._formal_waiting_put_starts.pop(key, [])
            for plan in queued:
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                self.formal_policy_events.append(
                    {
                        "timestamp_ns": self.des.now_ns,
                        "event": "FORMAL_PREFIX_DROPPED_AT_TERMINAL",
                        "span_id": span_id,
                        "path": path,
                        "plan_id": plan.plan_id,
                        "reason": reason,
                    }
                )

    def _formal_wake_content_alias_waiters(
        self,
        *,
        pool: _ModeledPool,
        physical_chunk_key: str,
    ) -> None:
        """Retry logical aliases after their shared physical write commits or aborts."""

        waiters = self._formal_content_alias_waiters.pop(
            (pool.pool_id, physical_chunk_key),
            [],
        )
        for plan in waiters:
            if plan.source_gpu_id in self.failed_gpu_ids:
                self.protection_path_bypasses[
                    f"{plan.path}_GPU_FAILURE_WHILE_ALIAS_PENDING"
                ] += 1
                self._formal_active_request_paths.discard((plan.span_id, plan.path))
                self._formal_blocked_request_paths.add((plan.span_id, plan.path))
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                continue
            plan.plan_id = self._next_id(
                f"put-start:{plan.path}:{plan.span_id}:alias-retry"
            )
            plan.handle = self.des.schedule_at(
                self.des.now_ns,
                EventKind.PUT_START,
                event_id=f"start:{plan.plan_id}",
                payload={"plan_id": plan.plan_id, "path": plan.path},
            )
            self.pending_put_starts[plan.plan_id] = plan
            self.formal_policy_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "FORMAL_CONTENT_ALIAS_RETRY",
                    "span_id": plan.span_id,
                    "path": plan.path,
                    "pool_id": pool.pool_id,
                    "physical_chunk_key": physical_chunk_key,
                }
            )

    def _formal_evict_committed_at_least(
        self,
        pool: _ModeledPool,
        required_bytes: int,
        *,
        cause: str,
    ) -> int:
        """Use a temporary formal contraction to expose only safe suffix tails."""

        if required_bytes <= 0:
            return 0
        landlord = self._formal_landlord_for_pool(pool)
        original_capacity = landlord.capacity_bytes
        temporary_capacity = max(
            landlord.pending_bytes,
            landlord.committed_bytes + landlord.pending_bytes - required_bytes,
        )
        preview = landlord.preview_capacity_change(
            temporary_capacity,
            latest_values=self._formal_latest_values(landlord),
        )
        contraction = landlord.apply_capacity_change(
            preview,
            cause=f"{cause}:TEMPORARY_CONTRACTION",
        )
        victim_keys = tuple(
            self._formal_chunk_metadata[item.chunk_id].physical_chunk.key
            for item in contraction.released_entries
        )
        pool.set_capacity_exact(
            temporary_capacity,
            victim_keys=victim_keys,
            proposed_rent=contraction.rent_after,
            now_ns=self.des.now_ns,
            cause=f"{cause}:TEMPORARY_CONTRACTION",
        )
        expansion = landlord.change_capacity(
            original_capacity,
            latest_values={},
            cause=f"{cause}:RESTORE_QUOTA",
        )
        pool.set_capacity_exact(
            original_capacity,
            victim_keys=(),
            proposed_rent=expansion.rent_after,
            now_ns=self.des.now_ns,
            cause=f"{cause}:RESTORE_QUOTA",
        )
        self._formal_dirty_pool_ids.add(pool.pool_id)
        return contraction.released_bytes

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
            ("PEER_HBM", self.profile.peer_replication_fraction),
            ("STORE_DRAM", self.profile.store_fraction),
        )
        for path, fraction in paths:
            candidate_count = _fraction_prefix_chunk_count(
                execution.chunks,
                fraction,
            )
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
            if target_gpu_id is not None:
                execution.designated_peer_gpu_id = target_gpu_id
            policy_ranges = _protection_batch_ranges(
                len(execution.chunks),
                candidate_count,
                global_prefix_chunk_count=_global_prefix_chunk_count(
                    execution.chunks[:candidate_count]
                ),
            )
            transport_ranges = _protection_transfer_batch_ranges(
                len(policy_ranges),
                global_prefix_candidate_count=_global_prefix_chunk_count(
                    execution.chunks[:candidate_count]
                ),
            )
            total_chunk_tokens = sum(chunk.token_count for chunk in execution.chunks)
            for batch_index, (candidate_begin, candidate_end) in enumerate(
                transport_ranges
            ):
                begin = policy_ranges[candidate_begin][0]
                end = policy_ranges[candidate_end - 1][1]
                if self._formal_policy_enabled():
                    chunks = tuple(
                        self._protection_chunk(
                            execution,
                            execution.chunks[policy_begin:policy_end],
                            path=path,
                        )
                        for policy_begin, policy_end in policy_ranges[
                            candidate_begin:candidate_end
                        ]
                    )
                else:
                    chunks = execution.chunks[begin:end]
                if not chunks:
                    continue
                sealed_prefix_tokens = (
                    execution.chunks[end - 1].token_start
                    + execution.chunks[end - 1].token_count
                )
                produced_ns = compute_start_ns + (
                    (compute_end_ns - compute_start_ns)
                    * sealed_prefix_tokens
                    // total_chunk_tokens
                )
                grouped_chunks: list[tuple[str | None, list[_Chunk]]] = []
                if path == "PEER_HBM":
                    grouped_chunks.append((None, list(chunks)))
                else:
                    for chunk in chunks:
                        chunk_store_id = self._store_segment_for_chunk(chunk)
                        if (
                            grouped_chunks
                            and grouped_chunks[-1][0] == chunk_store_id
                        ):
                            grouped_chunks[-1][1].append(chunk)
                        else:
                            grouped_chunks.append((chunk_store_id, [chunk]))
                for group_target_store_id, group in grouped_chunks:
                    group_chunks = tuple(group)
                    plan_id = self._next_id(
                        f"put-start:{path}:{execution.metadata.span_id}:"
                        f"batch-{batch_index}:{group_target_store_id or 'peer'}"
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
                        target_store_id=group_target_store_id,
                        chunks=group_chunks,
                        handle=handle,
                        produced_ns=produced_ns,
                    )

    def _make_transfer_task(
        self,
        *,
        transfer_id: str,
        span_id: str,
        source_id: str,
        target_id: str,
        cause: str,
        route_version: int,
        ready_ns: int,
        total_bytes: int,
    ) -> TransferTask:
        source_is_store = source_id in self.store_pools
        target_is_store = target_id in self.store_pools
        if source_is_store == target_is_store:
            if source_is_store:
                raise ExperimentError("Store-to-Store flow is outside the experiment scope")
            source = _experiment_gpu_location(source_id)
            target = _experiment_gpu_location(target_id)
            colocated = source_id == target_id
            path = TopologyPath(
                path_id=f"path:{transfer_id}",
                source_kind=MemoryKind.GPU_HBM,
                destination_kind=MemoryKind.GPU_HBM,
                transport=(
                    TransportKind.LOCAL_COPY if colocated else TransportKind.PCIE
                ),
                rate_resource_ids=(
                    (f"{source_id}.hbm-rate",)
                    if colocated
                    else (
                        f"{source_id}.hbm-rate",
                        "peer-fabric-rate",
                        f"{target_id}.hbm-rate",
                    )
                ),
                concurrency_resource_ids=(),
                source_endpoint=source.endpoint,
                destination_endpoint=target.endpoint,
                source_node_id=source.node_id,
                destination_node_id=target.node_id,
                source_numa_node_id=source.numa_node_id,
                destination_numa_node_id=target.numa_node_id,
                source_hca_id=None,
                destination_hca_id=None,
            )
            opcode = TransferOpcode.WRITE
        else:
            source = (
                _experiment_store_location(
                    source_id,
                    colocated_node_id=self._store_node_id(),
                    transport=self.parameters.store_transport,
                )
                if source_is_store
                else _experiment_gpu_location(source_id)
            )
            target = (
                _experiment_store_location(
                    target_id,
                    colocated_node_id=self._store_node_id(),
                    transport=self.parameters.store_transport,
                )
                if target_is_store
                else _experiment_gpu_location(target_id)
            )
            store_transport = self.parameters.store_transport
            staged = store_transport in {
                TransportKind.RDMA_HOST_STAGED,
                TransportKind.TCP_HOST_STAGED,
            }
            gpu_id = target_id if source_is_store else source_id
            store_segment_id = source_id if source_is_store else target_id
            store_rate_ids = self.store_rate_ids[store_segment_id]
            store_fabric_resource_id = (
                "peer-fabric-rate"
                if store_transport is TransportKind.PCIE
                else (
                    store_rate_ids["tcp_fabric"]
                    if store_transport is TransportKind.TCP_HOST_STAGED
                    else store_rate_ids["rdma_fabric"]
                )
            )
            store_rate_resources = (
                (
                    store_rate_ids["dram"],
                    store_fabric_resource_id,
                    *(
                        (f"{gpu_id}.host-rate",)
                        if staged
                        else ()
                    ),
                    f"{target_id}.hbm-rate",
                )
                if source_is_store
                else (
                    f"{source_id}.hbm-rate",
                    *(
                        (f"{gpu_id}.host-rate",)
                        if staged
                        else ()
                    ),
                    store_fabric_resource_id,
                    store_rate_ids["dram"],
                )
            )
            path = TopologyPath(
                path_id=f"path:{transfer_id}",
                source_kind=source.kind,
                destination_kind=target.kind,
                transport=store_transport,
                rate_resource_ids=store_rate_resources,
                concurrency_resource_ids=(),
                source_endpoint=source.endpoint,
                destination_endpoint=target.endpoint,
                source_node_id=source.node_id,
                destination_node_id=target.node_id,
                source_numa_node_id=source.numa_node_id,
                destination_numa_node_id=target.numa_node_id,
                source_hca_id=(
                    None
                    if store_transport is TransportKind.PCIE
                    else f"hca:{source.node_id}"
                ),
                destination_hca_id=(
                    None
                    if store_transport is TransportKind.PCIE
                    else f"hca:{target.node_id}"
                ),
                source_host_staging_resource_id=(
                    f"host:{source_id}" if staged and not source_is_store else None
                ),
                destination_host_staging_resource_id=(
                    f"host:{target_id}" if staged and source_is_store else None
                ),
            )
            opcode = TransferOpcode.READ if source_is_store else TransferOpcode.WRITE
        metadata = TransferMetadata(
            transfer_id=transfer_id,
            object_id=f"span:{span_id}",
            replica_id=f"replica:{transfer_id}",
            source=source,
            destination=target,
            opcode=opcode,
            total_bytes=total_bytes,
            cause=cause,
            route_version=route_version,
            ready_ns=ready_ns,
            path=path,
        )
        slice_size_bytes = _tokens_to_allocated_bytes(
            self.parameters.policy_chunk_tokens * FLOW_SLICE_POLICY_CHUNKS
        )
        return TransferTask.create(metadata, slice_size_bytes=slice_size_bytes)

    def _on_put_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        plan_id = _required_str(event.payload, "plan_id")
        plan = self.pending_put_starts.pop(plan_id, None)
        if plan is None:
            raise ExperimentError("unknown or canceled protection start executed")
        if plan.produced_ns != self.des.now_ns and not (
            self._formal_policy_enabled() and plan.produced_ns <= self.des.now_ns
        ):
            raise ExperimentError("protection start diverged from chunk seal time")
        formal_request_path = (plan.span_id, plan.path)
        if self._formal_policy_enabled():
            if formal_request_path in self._formal_blocked_request_paths:
                self.protection_path_bypasses[
                    f"{plan.path}_FORMAL_PREFIX_BLOCKED"
                ] += 1
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                return
            if (
                formal_request_path in self._formal_active_request_paths
                and not plan.formal_alias_waiting
            ):
                self._formal_waiting_put_starts[formal_request_path].append(plan)
                return
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
            pool = self.peer_pools[plan.target_gpu_id]
        else:
            if plan.target_store_id not in self.store_pools:
                raise ExperimentError("Store protection lost its physical segment")
            pool = self.store_pools[plan.target_store_id]
        execution = self.executions[plan.span_id]
        pool_reservations: list[_PoolReservation] = []
        formal_chunk_ids: list[str] = []
        formal_preview_audits: list[dict[str, object]] = []
        formal_block_after_resolution = False
        if self._formal_policy_enabled():
            landlord = self._formal_landlord_for_pool(pool)
            path_chunks = self._protection_chunks(execution, path=plan.path)
            path_ordinals = {
                (chunk.token_start, chunk.token_count, chunk.key): index
                for index, chunk in enumerate(path_chunks)
            }
            first_chunk = plan.chunks[0]
            first_global_index = path_ordinals.get(
                (
                    first_chunk.token_start,
                    first_chunk.token_count,
                    first_chunk.key,
                ),
                -1,
            )
            if first_global_index < 0:
                raise ExperimentError(
                    "formal protection chunk lost its source ordinal"
                )
            expected_global_index = self._formal_contiguous_prefix_length(
                plan.span_id,
                plan.path,
            )
            if first_global_index > expected_global_index:
                self._formal_waiting_put_starts[formal_request_path].append(plan)
                self.protection_path_bypasses[
                    f"{plan.path}_FORMAL_PREFIX_BLOCKED"
                ] += 1
                self.formal_policy_events.append(
                    {
                        "timestamp_ns": self.des.now_ns,
                        "event": "FORMAL_PREFIX_SUFFIX_QUEUED",
                        "span_id": plan.span_id,
                        "path": plan.path,
                        "plan_id": plan.plan_id,
                        "first_global_sequence_index": first_global_index,
                        "expected_global_sequence_index": expected_global_index,
                    }
                )
                return
            for candidate_offset, physical_chunk in enumerate(plan.chunks):
                global_sequence_index = path_ordinals.get(
                    (
                        physical_chunk.token_start,
                        physical_chunk.token_count,
                        physical_chunk.key,
                    ),
                    -1,
                )
                if global_sequence_index < 0:
                    raise ExperimentError(
                        "formal protection chunk lost its source ordinal"
                    )
                if physical_chunk.key in pool._pending_keys:
                    remaining = plan.chunks[candidate_offset:]
                    if pool_reservations:
                        self._split_continuous_protection_batch(
                            span_id=plan.span_id,
                            batch_key=plan.continuous_batch_key,
                        )
                        plan.chunks = remaining
                        plan.formal_alias_waiting = False
                        self._formal_waiting_put_starts[formal_request_path].append(
                            plan
                        )
                    else:
                        plan.chunks = remaining
                        plan.formal_alias_waiting = True
                        self._formal_active_request_paths.add(formal_request_path)
                        self._formal_content_alias_waiters[
                            (pool.pool_id, physical_chunk.key)
                        ].append(plan)
                    self.formal_policy_events.append(
                        {
                            "timestamp_ns": self.des.now_ns,
                            "event": "FORMAL_CONTENT_ALIAS_WAIT_PENDING",
                            "span_id": plan.span_id,
                            "path": plan.path,
                            "pool_id": pool.pool_id,
                            "global_sequence_index": global_sequence_index,
                            "physical_chunk_key": physical_chunk.key,
                        }
                    )
                    if not pool_reservations:
                        return
                    break
                if physical_chunk.key in pool.entries:
                    pool.contains(physical_chunk.key, now_ns=self.des.now_ns)
                    self._formal_content_alias_locations[
                        (plan.span_id, plan.path, global_sequence_index)
                    ] = (pool.pool_id, physical_chunk.key)
                    self.protection_path_alias_noops[plan.path] += 1
                    self.formal_policy_events.append(
                        {
                            "timestamp_ns": self.des.now_ns,
                            "event": "FORMAL_CONTENT_ALIAS_COMMITTED",
                            "span_id": plan.span_id,
                            "path": plan.path,
                            "pool_id": pool.pool_id,
                            "global_sequence_index": global_sequence_index,
                            "physical_chunk_key": physical_chunk.key,
                            "allocated_bytes": 0,
                            "transferred_bytes": 0,
                        }
                    )
                    continue
                pool_sequence_index = len(
                    landlord.committed_entries(execution.metadata.span_id)
                ) + len(formal_chunk_ids)
                formal_chunk_id = (
                    f"{pool.pool_id}:{execution.metadata.span_id}:"
                    f"{global_sequence_index}:{physical_chunk.key}:"
                    f"attempt:{transfer_id}:candidate-{candidate_offset}"
                )
                metadata = _FormalChunkMetadata(
                    chunk_id=formal_chunk_id,
                    span_id=execution.metadata.span_id,
                    path=plan.path,
                    pool_id=pool.pool_id,
                    physical_chunk=physical_chunk,
                    global_sequence_index=global_sequence_index,
                    pool_sequence_index=pool_sequence_index,
                )
                self._formal_chunk_metadata[formal_chunk_id] = metadata
                self._formal_request_ids_by_pool[pool.pool_id].add(
                    execution.metadata.span_id
                )
                candidate_value, candidate_gain = self._formal_candidate_value(
                    metadata,
                    landlord=landlord,
                    resident=False,
                )
                preview = landlord.preview(
                    candidate_value,
                    latest_values=self._formal_latest_values(landlord),
                    candidate_gain_evidence=candidate_gain,
                    joint_loss_provider=lambda victims: self._formal_joint_loss(
                        victims,
                        path=plan.path,
                        pool=landlord.pool,
                    ),
                    excluded_victim_chunk_ids=self._formal_alias_excluded_victim_ids(
                        metadata,
                        landlord=landlord,
                    ),
                )
                preview_audit = preview.to_canonical_json()
                self.formal_policy_events.append(
                    {
                        "timestamp_ns": self.des.now_ns,
                        "event": "FORMAL_ALGORITHM2_PREVIEW",
                        "span_id": plan.span_id,
                        "path": plan.path,
                        "pool_id": pool.pool_id,
                        "candidate_token_start": physical_chunk.token_start,
                        "candidate_token_count": physical_chunk.token_count,
                        "candidate_global_system_template": (
                            physical_chunk.global_system_template
                        ),
                        "engine_policy_chunk_tokens": (
                            self.parameters.policy_chunk_tokens
                        ),
                        "preview": preview_audit,
                    }
                )
                formal_pending = landlord.apply(preview)
                if formal_pending is None:
                    self.protection_path_bypasses[
                        f"{plan.path}_FORMAL_ADMISSION_{preview.bypass_reason}"
                    ] += 1
                    formal_block_after_resolution = True
                    for _blocked_chunk in plan.chunks[candidate_offset + 1 :]:
                        self.protection_path_bypasses[
                            f"{plan.path}_FORMAL_PREFIX_BLOCKED"
                        ] += 1
                    break
                reservation_id = (
                    f"{transfer_id}:candidate-{candidate_offset}"
                )
                victim_keys = tuple(
                    self._formal_chunk_metadata[item.chunk_id].physical_chunk.key
                    for item in preview.selected_victims
                )
                pool_reservations.append(
                    pool.reserve_exact(
                        reservation_id,
                        physical_chunk,
                        score=candidate_value.rental_key,
                        victim_keys=victim_keys,
                        proposed_rent=preview.proposed_rent,
                        now_ns=self.des.now_ns,
                        cause=f"AEGIS_{plan.path}_PROTECTION",
                    )
                )
                formal_chunk_ids.append(formal_chunk_id)
                formal_preview_audits.append(preview_audit)
                self._formal_dirty_pool_ids.add(pool.pool_id)
                self._formal_active_request_paths.add(formal_request_path)
            if not pool_reservations:
                self._formal_finish_request_path(
                    plan.span_id,
                    plan.path,
                    block=False,
                    park_suffix=formal_block_after_resolution,
                )
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=not formal_block_after_resolution,
                )
                return
        else:
            chunk_ordinals = {
                chunk.key: index for index, chunk in enumerate(execution.chunks)
            }
            scores = tuple(
                self._chunk_score(
                    execution,
                    chunk,
                    path=plan.path,
                    modeled_pool=pool,
                    sequence_index=chunk_ordinals[chunk.key],
                )
                for chunk in plan.chunks
            )
            pool_reservation = pool.reserve(
                transfer_id,
                plan.chunks,
                scores,
                now_ns=self.des.now_ns,
                cause=f"AEGIS_{plan.path}_PROTECTION",
            )
            if pool_reservation is not None:
                pool_reservations.append(pool_reservation)
        if (
            plan.path == "PEER_HBM"
            and plan.target_gpu_id is not None
            and pool_reservations
        ):
            admitted_to_shared_hbm = self._admit_peer_pool_to_shared_hbm(
                plan.target_gpu_id
            )
            if not admitted_to_shared_hbm:
                for reservation in reversed(pool_reservations):
                    pool.abort_reservation(
                        reservation.reservation_id,
                        now_ns=self.des.now_ns,
                        cause="PEER_HBM_SHARED_CAPACITY_PRESSURE",
                    )
                if formal_chunk_ids:
                    for formal_chunk_id in reversed(formal_chunk_ids):
                        self._formal_landlord_for_pool(pool).abort_pending(
                            formal_chunk_id
                        )
                    self._formal_finish_request_path(
                        plan.span_id,
                        plan.path,
                        block=False,
                        park_suffix=True,
                    )
                self._sync_peer_hbm_ledger(
                    plan.target_gpu_id,
                    cause="PEER_HBM_SHARED_CAPACITY_PRESSURE_ROLLBACK",
                )
                self.protection_path_bypasses[
                    "PEER_HBM_SHARED_CAPACITY_PRESSURE"
                ] += 1
                self.des.journal.append(
                    self.des.now_ns,
                    "AEGIS_PROTECTION_PATH_BYPASSED",
                    {
                        "path": plan.path,
                        "span_id": plan.span_id,
                        "source_gpu_id": plan.source_gpu_id,
                        "target_gpu_id": plan.target_gpu_id,
                        "reason": "SHARED_HBM_CAPACITY_PRESSURE",
                        "independent_path": True,
                        "store_path_affected": False,
                    },
                )
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                return
        if not pool_reservations:
            if pool.last_reserve_outcome == "ALIAS_ONLY":
                self.protection_path_alias_noops[plan.path] += 1
                self.des.journal.append(
                    self.des.now_ns,
                    "AEGIS_PROTECTION_ALIAS_NOOP",
                    {
                        "path": plan.path,
                        "span_id": plan.span_id,
                        "source_gpu_id": plan.source_gpu_id,
                        "reason": "COMMITTED_CONTENT_ALIAS_ALREADY_PRESENT",
                        "independent_path": True,
                    },
                )
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=True,
                )
                return
            self.protection_path_bypasses[f"{plan.path}_POOL_ADMISSION"] += 1
            self.des.journal.append(
                self.des.now_ns,
                "AEGIS_PROTECTION_PATH_BYPASSED",
                {
                    "path": plan.path,
                    "span_id": plan.span_id,
                    "source_gpu_id": plan.source_gpu_id,
                    "reason": "POOL_ADMISSION_REJECTED",
                    "independent_path": True,
                },
            )
            self._resolve_continuous_protection_batch(
                span_id=plan.span_id,
                batch_key=plan.continuous_batch_key,
                committed=False,
            )
            return
        admitted_chunks = tuple(
            chunk for reservation in pool_reservations for chunk in reservation.chunks
        )
        admitted_scores = tuple(
            score for reservation in pool_reservations for score in reservation.scores
        )
        transfer_bytes = sum(reservation.bytes for reservation in pool_reservations)
        cause = f"AEGIS_{plan.path}_PROTECTION"
        transfer_start_ns = self.des.now_ns + self.parameters.transfer_setup_ns
        task = self._make_transfer_task(
            transfer_id=transfer_id,
            span_id=plan.span_id,
            source_id=plan.source_gpu_id,
            target_id=(
                plan.target_gpu_id
                if plan.target_gpu_id is not None
                else cast(str, plan.target_store_id)
            ),
            cause=cause,
            route_version=self.executions[plan.span_id].route_version,
            ready_ns=transfer_start_ns,
            total_bytes=transfer_bytes,
        )
        start_handle = self.des.schedule_at(
            transfer_start_ns,
            EventKind.TRANSFER_START,
            event_id=f"flow-start:{transfer_id}",
            payload={"transfer_id": transfer_id},
        )
        self.pending_puts[transfer_id] = _PendingPut(
            transfer_id=transfer_id,
            span_id=plan.span_id,
            path=plan.path,
            source_gpu_id=plan.source_gpu_id,
            target_gpu_id=plan.target_gpu_id,
            target_store_id=plan.target_store_id,
            chunks=admitted_chunks,
            scores=admitted_scores,
            task=task,
            handle=start_handle,
            started=False,
            pool_reservation_ids=tuple(
                reservation.reservation_id for reservation in pool_reservations
            ),
            bytes=transfer_bytes,
            policy_candidate_count=len(admitted_chunks),
            continuous_batch_key=plan.continuous_batch_key,
            formal_chunk_ids=tuple(formal_chunk_ids),
            formal_preview_audits=tuple(formal_preview_audits),
            formal_block_after_resolution=formal_block_after_resolution,
        )
        bandwidth = min(
            self.transfer_rate_resources[resource_id].capacity_bytes_per_second
            for resource_id in task.metadata.path.rate_resource_ids
        )
        initial_service_ns = math.ceil(transfer_bytes * 1_000_000_000 / bandwidth)
        try:
            self._record_transfer(
                _transfer_record(
                    transfer_id=transfer_id,
                    path=(
                        "D2D_P2P" if plan.path == "PEER_HBM" else "SOURCE_D2H_STORE"
                    ),
                    cause=cause,
                    start_ns=transfer_start_ns,
                    end_ns=transfer_start_ns + max(1, initial_service_ns),
                    bytes=transfer_bytes,
                    source_gpu_id=plan.source_gpu_id,
                    target_gpu_id=(
                        plan.target_gpu_id
                        if plan.target_gpu_id is not None
                        else cast(str, plan.target_store_id)
                    ),
                    ready_ns=self.des.now_ns,
                    status="PENDING",
                    span_id=plan.span_id,
                    flow_slice_count=len(task.slices),
                    policy_candidate_count=len(admitted_chunks),
                )
            )
            self._bind_transfer_task_metadata(task)
        except Exception:
            self.des.cancel(start_handle, reason="TRANSFER_RECORD_CREATE_FAILED")
            del self.pending_puts[transfer_id]
            if transfer_id in self._transfer_by_id:
                task.cancel_remaining(
                    timestamp_ns=self.des.now_ns,
                    reason="TRANSFER_RECORD_CREATE_FAILED",
                )
                self._abort_transfer_from_task(
                    transfer_id,
                    task=task,
                    reason="TRANSFER_RECORD_CREATE_FAILED",
                )
            for reservation in reversed(pool_reservations):
                pool.abort_reservation(
                    reservation.reservation_id,
                    now_ns=self.des.now_ns,
                    cause="TRANSFER_RECORD_CREATE_FAILED",
                )
            for formal_chunk_id in reversed(formal_chunk_ids):
                self._formal_landlord_for_pool(pool).abort_pending(formal_chunk_id)
            if formal_chunk_ids:
                self._formal_finish_request_path(
                    plan.span_id,
                    plan.path,
                    block=False,
                    park_suffix=True,
                )
            self._resolve_continuous_protection_batch(
                span_id=plan.span_id,
                batch_key=plan.continuous_batch_key,
                committed=False,
            )
            if plan.path == "PEER_HBM" and plan.target_gpu_id is not None:
                self._sync_peer_hbm_ledger(
                    plan.target_gpu_id,
                    cause="AEGIS_PEER_HBM_RECORD_ROLLBACK",
                )
            raise

    def _on_transfer_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        transfer_id = _required_str(event.payload, "transfer_id")
        pending = self.pending_puts.get(transfer_id)
        if pending is None or pending.started or pending.handle != EventHandle(event.event_id):
            raise ExperimentError("unknown, duplicate, or stale protection flow start")
        if pending.source_gpu_id in self.failed_gpu_ids or (
            pending.target_gpu_id is not None
            and pending.target_gpu_id in self.failed_gpu_ids
        ):
            raise ExperimentError("failed GPU reached a protection flow start")
        pending.handle = None
        pending.started = True
        try:
            self._acquire_transfer_overlays(pending.task)
            self.transfer_runtime.start_task(
                pending.task,
                on_terminal=self._on_protection_task_terminal,
            )
        except Exception:
            if transfer_id in self.active_source_pins:
                self._release_transfer_overlays(
                    pending.task,
                    reason="FLOW_START_FAILED",
                )
            pool = (
                self.peer_pools[pending.target_gpu_id]
                if pending.target_gpu_id is not None
                else self.store_pools[cast(str, pending.target_store_id)]
            )
            self._abort_pending_put_reservations(
                pending,
                pool=pool,
                cause="FLOW_START_FAILED",
            )
            if pending.target_gpu_id is not None:
                self._sync_peer_hbm_ledger(
                    pending.target_gpu_id,
                    cause="AEGIS_PEER_HBM_FLOW_START_ROLLBACK",
                )
            self._abort_transfer_from_task(
                transfer_id,
                task=pending.task,
                reason="FLOW_START_FAILED",
            )
            del self.pending_puts[transfer_id]
            self._resolve_continuous_protection_batch(
                span_id=pending.span_id,
                batch_key=pending.continuous_batch_key,
                committed=False,
            )
            raise
        record = self._transfer_by_id[transfer_id]
        record["start_ns"] = self.des.now_ns
        predicted_end_ns = self._predicted_task_completion_ns(pending.task)
        record["planned_end_ns"] = predicted_end_ns
        record["end_ns"] = predicted_end_ns

    def _cancel_pending_protection_service(
        self,
        transfer_id: str,
        pending: _PendingPut,
        *,
        reason: str,
    ) -> None:
        """Fence WAITING, active, or service-complete/uncommitted PUT work."""

        if pending.handle is not None:
            if not self.des.cancel(pending.handle, reason=reason):
                raise ExperimentError("pending protection event could not be canceled")
            pending.handle = None
        if not pending.started:
            if pending.task.status is not TransferStatus.WAITING:
                raise ExperimentError("unstarted protection task left WAITING state")
            return
        if pending.task.status is TransferStatus.PENDING:
            self.transfer_runtime.abort_task(transfer_id, reason=reason)
            self._release_transfer_overlays(pending.task, reason=reason)
            return
        if pending.task.status is TransferStatus.COMPLETED:
            # Fluid service is complete, but PUT_COMMIT has not published the
            # destination reservation.  The bytes may be rolled back atomically.
            return
        raise ExperimentError("protection cancellation found an unsupported task state")

    def _abort_pending_put_reservations(
        self,
        pending: _PendingPut,
        *,
        pool: _ModeledPool,
        cause: str,
        block_formal_path: bool = True,
    ) -> int:
        """Rollback one physical batch and each independent policy admission."""

        released_bytes = 0
        for reservation_id in reversed(pending.pool_reservation_ids):
            released_bytes += pool.abort_reservation(
                reservation_id,
                now_ns=self.des.now_ns,
                cause=cause,
            ).bytes
        if pending.formal_chunk_ids:
            landlord = self._formal_landlord_for_pool(pool)
            for formal_chunk_id in reversed(pending.formal_chunk_ids):
                landlord.abort_pending(formal_chunk_id)
            first = self._formal_chunk_metadata[pending.formal_chunk_ids[0]]
            if block_formal_path:
                self._formal_finish_request_path(
                    first.span_id,
                    pending.path,
                    block=True,
                )
            else:
                request_path = (first.span_id, pending.path)
                self._formal_active_request_paths.discard(request_path)
                self._formal_blocked_request_paths.discard(request_path)
                queued = self._formal_waiting_put_starts.pop(request_path, [])
                for plan in queued:
                    self._resolve_continuous_protection_batch(
                        span_id=plan.span_id,
                        batch_key=plan.continuous_batch_key,
                        committed=False,
                    )
                self.formal_policy_events.append(
                    {
                        "timestamp_ns": self.des.now_ns,
                        "event": "FORMAL_PREFIX_TRANSIENT_ABORT",
                        "span_id": first.span_id,
                        "path": pending.path,
                        "cause": cause,
                        "queued_suffix_count": len(queued),
                    }
                )
            for chunk in pending.chunks:
                self._formal_wake_content_alias_waiters(
                    pool=pool,
                    physical_chunk_key=chunk.key,
                )
        return released_bytes

    def _on_protection_task_terminal(
        self, task: TransferTask, _des: GlobalDES
    ) -> None:
        transfer_id = task.metadata.transfer_id
        pending = self.pending_puts.get(transfer_id)
        if pending is None or pending.task is not task:
            raise ExperimentError("protection flow terminal callback lost its owner")
        if task.status is TransferStatus.COMPLETED:
            self._release_transfer_overlays(
                task,
                reason="FLOW_SERVICE_COMPLETED",
            )
            self._finish_fluid_service_record(transfer_id, task=task)
            pending.handle = self.des.schedule_at(
                self.des.now_ns,
                EventKind.PUT_COMMIT,
                event_id=f"commit:{transfer_id}",
                payload={"transfer_id": transfer_id, "path": pending.path},
            )
        elif task.status is not TransferStatus.CANCELED:
            raise ExperimentError("protection flow reached an unsupported terminal state")

    def _on_put_commit(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        transfer_id = _required_str(event.payload, "transfer_id")
        pending = self.pending_puts.pop(transfer_id, None)
        if pending is None:
            raise ExperimentError("unknown or canceled protection commit executed")
        if pending.task.status is not TransferStatus.COMPLETED:
            raise ExperimentError("protection commit preceded fluid task completion")
        if pending.handle != EventHandle(event.event_id):
            raise ExperimentError("protection commit handle diverged from its owner")
        if pending.source_gpu_id in self.failed_gpu_ids:
            raise ExperimentError("failed source attempted protection commit")
        if pending.path == "PEER_HBM":
            if pending.target_gpu_id is None:
                raise ExperimentError("Peer-HBM commit lost its physical target")
            if pending.target_gpu_id in self.failed_gpu_ids:
                raise ExperimentError("failed Peer-HBM target attempted protection commit")
            pool = self.peer_pools[pending.target_gpu_id]
        else:
            if pending.target_store_id not in self.store_pools:
                raise ExperimentError("Store commit lost its physical segment")
            pool = self.store_pools[pending.target_store_id]
        committed_reservations = tuple(
            pool.commit_reservation(
                reservation_id,
                now_ns=self.des.now_ns,
                cause=f"{pending.path}_COMMIT",
            )
            for reservation_id in pending.pool_reservation_ids
        )
        formal_resolutions: list[dict[str, object]] = []
        if pending.formal_chunk_ids:
            landlord = self._formal_landlord_for_pool(pool)
            for formal_chunk_id in pending.formal_chunk_ids:
                metadata = self._formal_chunk_metadata[formal_chunk_id]
                latest_value, _latest_gain = self._formal_candidate_value(
                    metadata,
                    landlord=landlord,
                    resident=False,
                )
                formal_resolutions.append(
                    landlord.complete_pending_value(
                        formal_chunk_id,
                        latest_value=latest_value,
                    ).to_canonical_json()
                )
            self._formal_dirty_pool_ids.add(pool.pool_id)
            first_metadata = self._formal_chunk_metadata[
                pending.formal_chunk_ids[0]
            ]
            self._formal_finish_request_path(
                first_metadata.span_id,
                pending.path,
                block=False,
                park_suffix=pending.formal_block_after_resolution,
            )
        if pending.path == "PEER_HBM" and pending.target_gpu_id is not None:
            self._sync_peer_hbm_ledger(
                pending.target_gpu_id,
                cause="AEGIS_PEER_HBM_PENDING_TO_COMMITTED",
            )
        if pending.formal_chunk_ids:
            for chunk in pending.chunks:
                self._formal_wake_content_alias_waiters(
                    pool=pool,
                    physical_chunk_key=chunk.key,
                )
        committed_bytes = sum(item.bytes for item in committed_reservations)
        if committed_bytes != pending.bytes:
            raise ExperimentError("pool commit bytes diverged from transfer bytes")
        self._commit_transfer(transfer_id)
        self._resolve_continuous_protection_batch(
            span_id=pending.span_id,
            batch_key=pending.continuous_batch_key,
            committed=not pending.formal_block_after_resolution,
        )
        admitted = sum(len(item.chunks) for item in committed_reservations)
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_PROTECTION_PATH_COMMITTED",
            {
                "transfer_id": transfer_id,
                "path": pending.path,
                "candidate_chunks": pending.policy_candidate_count,
                "admitted_chunks": admitted,
                "target_gpu_id": pending.target_gpu_id,
                "target_store_id": pending.target_store_id,
                "independent_path": True,
                "source_owned": True,
                "target_owned_destage": False,
                "formal_algorithm2_resolutions": formal_resolutions,
            },
        )

    @staticmethod
    def _reset_recovery_route_state(execution: _SpanExecution) -> None:
        """Discard recovery accounting owned by the request's previous route."""

        execution.recovery_normal_hbm_local_tokens = 0
        execution.restored_peer_tokens = 0
        execution.restored_peer_local_tokens = 0
        execution.restored_peer_d2d_tokens = 0
        execution.restored_store_tokens = 0
        execution.recompute_tokens = 0
        execution.recovery_ready_ns = None
        execution.prompt_recompute_start_ns = None
        execution.prompt_recompute_complete_ns = None
        execution.silent_replay_start_ns = None
        execution.silent_replay_complete_ns = None
        execution.resume_decode_start_ns = None

    def _on_failure_inject(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        failure_id = _required_str(event.payload, "failure_id")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu not in self.gpu_ids or target_gpu in self.failed_gpu_ids:
            raise ExperimentError("failure target is unknown or already failed")
        schedule = self._failure_schedule_by_id.get(failure_id)
        if schedule is None:
            raise ExperimentError("failure executed without a frozen schedule")
        if failure_id in self._failure_event_executed:
            raise ExperimentError("failure event executed more than once")
        failure_plan = self.failure_schedule
        if failure_plan is None:
            raise ExperimentError("failure event lost its containing plan")
        prior_ids = {
            prior.failure_id
            for prior in failure_plan.events[: schedule.event_index]
        }
        if not prior_ids.issubset(self._failure_event_executed):
            raise ExperimentError("failure events executed outside their frozen order")
        if _required_str(event.payload, "reference_target_gpu_id") != schedule.target_gpu_id:
            raise ExperimentError("failure event lost its reference-route provenance")
        if _required_str(event.payload, "resolved_target_gpu_id") != target_gpu:
            raise ExperimentError("failure payload resolved two different physical targets")
        focus_execution = self.executions[schedule.focus_span_id]
        if focus_execution.gpu_id != target_gpu:
            raise ExperimentError("resolved failure target is not the focus span's live route")
        if _required_int(event.payload, "resolved_at_ns") != self.des.now_ns:
            raise ExperimentError("resolved failure timestamp diverged from the DES event")
        continuous_progress_evidence = event.payload.get(
            "continuous_progress_evidence"
        )
        if self.continuous_batch_enabled and not isinstance(
            continuous_progress_evidence, dict
        ):
            raise ExperimentError(
                "continuous failure lacks scheduler token-progress evidence"
            )
        self._failure_event_executed.add(failure_id)
        self._resolved_failure_targets[failure_id] = target_gpu
        self._continuous_failure_active_steps.pop(schedule.focus_span_id, None)
        self._continuous_failure_crossing_evidence.pop(failure_id, None)
        self.failed_gpu_ids.add(target_gpu)
        impacted_active: list[str] = []
        impacted_queued: list[str] = []
        reroute_only_queued: list[str] = []
        if self.continuous_batch_enabled:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("continuous failure fence lost its driver")
            snapshot = driver.fence_for_external_gpu_failure(
                failure_id=failure_id,
                target_id=target_gpu,
                reason="GPU_FAILURE_ROUTE_FENCE",
            )
            for item in snapshot.requests:
                execution = self.executions[item.request_id]
                self._continuous_failure_active_steps.pop(item.request_id, None)
                self._reset_recovery_route_state(execution)
                self._cancel_future_failure_trigger_for_span(
                    item.request_id,
                    executing_failure_id=failure_id,
                )
                execution.completion_handle = None
                execution.hbm_allocation_handle = None
                execution.reservation_id = None
                execution.failure_at_ns = self.des.now_ns
                execution.failure_source_gpu_id = target_gpu
                execution.committed_output_tokens_at_failure = (
                    item.committed_output_tokens
                )
                execution.status = _ExecutionStatus.FENCED
                if item.queue_kind == "RUNNING":
                    impacted_active.append(item.request_id)
                else:
                    impacted_queued.append(item.request_id)
                    reroute_only_queued.append(item.request_id)
            for pending_admission in snapshot.pending_admissions:
                span_id = pending_admission.request_id
                execution = self.executions[span_id]
                if (
                    execution.gpu_id != target_gpu
                    or execution.route_version != pending_admission.route_version
                    or execution.status not in {
                    _ExecutionStatus.QUEUED,
                    _ExecutionStatus.RECOVERING,
                    }
                ):
                    raise ExperimentError(
                        "pending admission failure crossed execution route authority"
                    )
                self._continuous_failure_active_steps.pop(span_id, None)
                self._reset_recovery_route_state(execution)
                self._cancel_future_failure_trigger_for_span(
                    span_id,
                    executing_failure_id=failure_id,
                )
                execution.completion_handle = None
                execution.hbm_allocation_handle = None
                execution.reservation_id = None
                execution.failure_at_ns = self.des.now_ns
                execution.failure_source_gpu_id = target_gpu
                execution.committed_output_tokens_at_failure = (
                    pending_admission.router_committed_output_tokens
                )
                execution.status = _ExecutionStatus.FENCED
                impacted_queued.append(span_id)
                reroute_only_queued.append(span_id)
            foreground_store_impacted = sorted(
                span_id
                for span_id, group in self.foreground_store_restore_by_span.items()
                if group.target_gpu_id == target_gpu
            )
            for span_id in foreground_store_impacted:
                scheduler_handoff_fenced = (
                    span_id in impacted_active or span_id in impacted_queued
                )
                if not self._abort_foreground_store_restore_group(
                    span_id,
                    reason=f"GPU_FAILURE_FOREGROUND_STORE_RESTORE:{failure_id}",
                    unregister_pristine=False,
                ):
                    raise ExperimentError("foreground Store failure owner disappeared")
                if scheduler_handoff_fenced:
                    self.foreground_store_events.append(
                        {
                            "timestamp_ns": self.des.now_ns,
                            "event": "FOREGROUND_STORE_FAILURE_HANDOFF_FENCED",
                            "span_id": span_id,
                            "target_gpu_id": target_gpu,
                            "failure_id": failure_id,
                        }
                    )
                    continue
                execution = self.executions[span_id]
                execution.reused_primary_tokens = 0
                execution.reused_store_tokens = 0
                self._continuous_failure_active_steps.pop(span_id, None)
                self._reset_recovery_route_state(execution)
                self._cancel_future_failure_trigger_for_span(
                    span_id,
                    executing_failure_id=failure_id,
                )
                execution.failure_at_ns = self.des.now_ns
                execution.failure_source_gpu_id = target_gpu
                execution.committed_output_tokens_at_failure = 0
                execution.status = _ExecutionStatus.FENCED
                impacted_queued.append(span_id)
            recovery_impacted = self._abort_recovery_groups_for_gpu_failure(
                target_gpu,
                failure_id=failure_id,
            )
            for span_id in recovery_impacted:
                if span_id in impacted_active or span_id in impacted_queued:
                    raise ExperimentError(
                        "one request was owned by scheduler and recovery transfer together"
                    )
                execution = self.executions[span_id]
                if execution.completion_handle is not None:
                    if not self.des.cancel(
                        execution.completion_handle,
                        reason=f"GPU_FAILURE_RECOVERY_READY_FENCE:{failure_id}",
                    ):
                        raise ExperimentError(
                            "pending recovery materialization was not cancellable"
                        )
                    execution.completion_handle = None
                if (
                    execution.hbm_recovery_reserved_bytes > 0
                    and execution.hbm_allocation_gpu_id != target_gpu
                ):
                    recovery_target = execution.hbm_allocation_gpu_id
                    if recovery_target is None:
                        raise ExperimentError(
                            "healthy recovery destination reservation lost its GPU"
                        )
                    self.continuous_hbm_authorities[
                        recovery_target
                    ].trim_external_recovery_reservation(
                        request_id=span_id,
                        retained_bytes=0,
                        cause="GPU_FAILURE_ABORT_RECOVERY_DESTINATION_RESERVE",
                    )
                    execution.hbm_recovery_reserved_bytes = 0
                    execution.hbm_allocation_gpu_id = None
                self._continuous_failure_active_steps.pop(span_id, None)
                self._reset_recovery_route_state(execution)
                self._cancel_future_failure_trigger_for_span(
                    span_id,
                    executing_failure_id=failure_id,
                )
                execution.failure_at_ns = self.des.now_ns
                execution.failure_source_gpu_id = target_gpu
                execution.status = _ExecutionStatus.FENCED
                impacted_queued.append(span_id)
        for execution in self.executions.values():
            if self.continuous_batch_enabled:
                continue
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
            booking = self._compute_bookings_by_span.get(
                execution.metadata.span_id
            )
            if (
                booking is None
                or booking.kind is not _ComputeKind.NORMAL
                or booking.reservation_id != execution.reservation_id
                or booking.completion_handle != execution.completion_handle
            ):
                raise ExperimentError("failed route lost its normal compute booking")
            if not self.des.cancel(
                execution.completion_handle, reason="GPU_FAILURE_ROUTE_FENCE"
            ):
                raise ExperimentError("failed compute completion could not be fenced")
            self._cancel_future_failure_trigger_for_span(
                execution.metadata.span_id,
                executing_failure_id=failure_id,
            )
            if execution.hbm_allocated_bytes == 0:
                if execution.hbm_allocation_handle is None or not self.des.cancel(
                    execution.hbm_allocation_handle,
                    reason="GPU_FAILURE_BEFORE_PRIMARY_HBM_ALLOCATE",
                ):
                    raise ExperimentError(
                        "queued primary-HBM allocation could not be canceled"
                    )
            elif execution.hbm_allocation_gpu_id != target_gpu:
                raise ExperimentError("active primary-HBM owner diverged from failed GPU")
            if (
                self.compute[target_gpu].cancel_from(
                    execution.reservation_id,
                    timestamp_ns=self.des.now_ns,
                )
                is None
            ):
                raise ExperimentError("failed compute reservation could not be fenced")
            if (
                self._compute_bookings_by_span.pop(
                    execution.metadata.span_id, None
                )
                is not booking
            ):
                raise ExperimentError("failed compute booking registry diverged")
            self._reset_recovery_route_state(execution)
            execution.completion_handle = None
            execution.hbm_allocation_handle = None
            execution.reservation_id = None
            execution.failure_at_ns = self.des.now_ns
            execution.failure_source_gpu_id = target_gpu
            execution.status = _ExecutionStatus.FENCED
            if start_ns <= self.des.now_ns:
                impacted_active.append(execution.metadata.span_id)
            else:
                impacted_queued.append(execution.metadata.span_id)

        if schedule.focus_span_id not in impacted_active:
            raise ExperimentError("logical failure trigger did not hit its focus span")

        canceled_paths: list[str] = []
        canceled_before_start_paths: list[str] = []
        protection_reset_spans: set[str] = set()
        for request_path, queued_plans in tuple(
            self._formal_waiting_put_starts.items()
        ):
            retained: list[_PendingPutStart] = []
            for queued_plan in queued_plans:
                target_dependency = (
                    queued_plan.path == "PEER_HBM"
                    and queued_plan.target_gpu_id == target_gpu
                )
                if (
                    queued_plan.source_gpu_id == target_gpu
                    or target_dependency
                ):
                    protection_reset_spans.add(queued_plan.span_id)
                    self._resolve_continuous_protection_batch(
                        span_id=queued_plan.span_id,
                        batch_key=queued_plan.continuous_batch_key,
                        committed=False,
                    )
                    canceled_before_start_paths.append(queued_plan.path)
                    self.protection_path_bypasses[
                        f"{queued_plan.path}_GPU_FAILURE_BEFORE_START"
                    ] += 1
                    self._formal_blocked_request_paths.add(request_path)
                else:
                    retained.append(queued_plan)
            if retained:
                self._formal_waiting_put_starts[request_path] = retained
            else:
                self._formal_waiting_put_starts.pop(request_path, None)
        for alias_key, plans in tuple(self._formal_content_alias_waiters.items()):
            retained_aliases = []
            for plan in plans:
                target_dependency = (
                    plan.path == "PEER_HBM" and plan.target_gpu_id == target_gpu
                )
                if plan.source_gpu_id != target_gpu and not target_dependency:
                    retained_aliases.append(plan)
                    continue
                canceled_before_start_paths.append(plan.path)
                protection_reset_spans.add(plan.span_id)
                self._resolve_continuous_protection_batch(
                    span_id=plan.span_id,
                    batch_key=plan.continuous_batch_key,
                    committed=False,
                )
                self.protection_path_bypasses[
                    f"{plan.path}_GPU_FAILURE_WHILE_ALIAS_PENDING"
                ] += 1
                self._formal_active_request_paths.discard((plan.span_id, plan.path))
                self._formal_blocked_request_paths.add((plan.span_id, plan.path))
            if retained_aliases:
                self._formal_content_alias_waiters[alias_key] = retained_aliases
            else:
                self._formal_content_alias_waiters.pop(alias_key, None)
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
            protection_reset_spans.add(plan.span_id)
            self._resolve_continuous_protection_batch(
                span_id=plan.span_id,
                batch_key=plan.continuous_batch_key,
                committed=False,
            )
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
            self._cancel_pending_protection_service(
                transfer_id,
                pending,
                reason="GPU_FAILURE_SOURCE_OR_DESTINATION_DEPENDENCY",
            )
            destination_pool = (
                self.peer_pools[pending.target_gpu_id]
                if pending.target_gpu_id is not None
                else self.store_pools[cast(str, pending.target_store_id)]
            )
            released_bytes = self._abort_pending_put_reservations(
                pending,
                pool=destination_pool,
                cause="GPU_FAILURE_TRANSFER_ABORT",
            )
            if released_bytes != pending.bytes:
                raise ExperimentError("aborted destination reserve bytes diverged")
            if (
                pending.target_gpu_id is not None
                and pending.target_gpu_id not in self.failed_gpu_ids
            ):
                self._sync_peer_hbm_ledger(
                    pending.target_gpu_id,
                    cause="GPU_FAILURE_PEER_DESTINATION_ABORT",
                )
            self._abort_transfer_from_task(
                transfer_id,
                task=pending.task,
                reason="GPU_FAILURE_SOURCE_OR_DESTINATION_DEPENDENCY",
            )
            canceled_paths.append(pending.path)
            protection_reset_spans.add(pending.span_id)
            del self.pending_puts[transfer_id]
            self._resolve_continuous_protection_batch(
                span_id=pending.span_id,
                batch_key=pending.continuous_batch_key,
                committed=False,
            )

        # A failure ends the old physical route, not the logical request's
        # future protection eligibility.  Remove route-local formal serialization
        # state only after every dependent plan and transfer is fenced.
        protection_reset_spans.update(impacted_active)
        protection_reset_spans.update(impacted_queued)
        for span_id in protection_reset_spans:
            for path in ("PEER_HBM", "STORE_DRAM"):
                self._formal_active_request_paths.discard((span_id, path))
                self._formal_blocked_request_paths.discard((span_id, path))

        failed_peer_pool = self.peer_pools[target_gpu]
        if self._formal_policy_enabled():
            self._formal_landlord_for_pool(
                failed_peer_pool
            ).invalidate_failure_domain(cause="GPU_FAILURE_UNAVAILABLE_CAPACITY")
            self._formal_dirty_pool_ids.add(failed_peer_pool.pool_id)
        lost_peer_hbm_bytes = failed_peer_pool.fail(
            now_ns=self.des.now_ns,
            cause="GPU_FAILURE_UNAVAILABLE_CAPACITY",
        )
        failed_primary_pool = self.primary_pools[target_gpu]
        lost_normal_hbm_bytes = failed_primary_pool.fail(
            now_ns=self.des.now_ns,
            cause="GPU_FAILURE_NORMAL_HBM_INDEX_CLEARED",
        )
        self._fail_hbm_ledger(target_gpu)
        if self.continuous_batch_enabled:
            self.continuous_hbm_authorities[target_gpu].observe_external_failure()
        for execution in self.executions.values():
            if execution.hbm_allocation_gpu_id == target_gpu:
                execution.hbm_allocated_bytes = 0
                execution.hbm_recovery_reserved_bytes = 0
                execution.hbm_allocation_gpu_id = None

        logical_trigger: dict[str, object] = {
            "focus_span_id": schedule.focus_span_id,
            "progress_per_mille": schedule.trigger_progress_per_mille,
            "resolved_target_gpu_id": target_gpu,
            "resolved_at_ns": self.des.now_ns,
            "resolved_compute_start_ns": _required_int(
                event.payload, "resolved_compute_start_ns"
            ),
            "resolved_compute_end_ns": _required_int(
                event.payload, "resolved_compute_end_ns"
            ),
        }
        if continuous_progress_evidence is not None:
            logical_trigger["continuous_progress_evidence"] = (
                continuous_progress_evidence
            )
        failure_record = {
            "timestamp_ns": self.des.now_ns,
            "event": "FAILURE_INJECT",
            "failure_id": schedule.failure_id,
            "type": "GPU_FAILURE",
            "target_gpu_id": target_gpu,
            "reference_target_gpu_id": schedule.target_gpu_id,
            "impacted_active_span_ids": sorted(impacted_active),
            "impacted_queued_span_ids": sorted(impacted_queued),
            "canceled_source_dependent_paths": sorted(canceled_paths),
            "canceled_before_start_paths": sorted(canceled_before_start_paths),
            "peer_hbm_lost_committed_bytes": lost_peer_hbm_bytes,
            "peer_hbm_unavailable_bytes": failed_peer_pool.unavailable_bytes,
            "normal_hbm_lost_reusable_bytes": lost_normal_hbm_bytes,
            "store_dram_unavailable_bytes": 0,
            "repair_after_ns": schedule.gpu_recovery_time_ns,
            "repair_completed_at_ns": None,
            "logical_trigger": logical_trigger,
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
                "reroute_only_queued_span_ids": sorted(reroute_only_queued),
            },
        )
        if schedule.gpu_recovery_time_ns is not None:
            self.des.schedule_after(
                schedule.gpu_recovery_time_ns,
                EventKind.REPAIR_COMPLETE,
                event_id=f"repair:{schedule.failure_id}",
                payload={
                    "failure_id": schedule.failure_id,
                    "target_gpu_id": target_gpu,
                },
            )
        self._schedule_ready_future_failure_triggers()

    def _on_repair_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        failure_id = _required_str(event.payload, "failure_id")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        schedule = self._failure_schedule_by_id.get(failure_id)
        if (
            schedule is None
            or schedule.gpu_recovery_time_ns is None
            or failure_id != schedule.failure_id
            or target_gpu != self._resolved_failure_targets.get(failure_id)
        ):
            raise ExperimentError("GPU repair diverged from its runtime-resolved failure")
        if failure_id in self._repair_event_executed or target_gpu not in self.failed_gpu_ids:
            raise ExperimentError("GPU repair requires one currently failed target")

        self.peer_pools[target_gpu].repair(
            now_ns=self.des.now_ns,
            cause="GPU_REPAIR_PEER_HBM_EMPTY_REUSABLE",
        )
        if self._formal_policy_enabled():
            self._formal_landlord_for_pool(
                self.peer_pools[target_gpu]
            ).restore_failure_domain(
                cause="GPU_REPAIR_PEER_HBM_EMPTY_REUSABLE",
                capacity_bytes=self.peer_pools[target_gpu].capacity_bytes,
            )
        self.primary_pools[target_gpu].repair(
            now_ns=self.des.now_ns,
            cause="GPU_REPAIR_NORMAL_HBM_EMPTY_REUSABLE",
        )
        self.failed_gpu_ids.remove(target_gpu)
        ledger = self.hbm_ledgers[target_gpu]
        unavailable = ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT)
        fixed_bytes = (
            self.parameters.model_weights_bytes_per_gpu
            + self.parameters.runtime_fixed_bytes_per_gpu
        )
        if unavailable != ledger.capacity_bytes or fixed_bytes >= unavailable:
            raise ExperimentError("GPU repair cannot reconstruct the healthy HBM accounts")
        self._commit_hbm_moves(
            target_gpu,
            [
                (
                    UNAVAILABLE_CAPACITY_ACCOUNT,
                    HBM_MODEL_WEIGHTS_ACCOUNT,
                    self.parameters.model_weights_bytes_per_gpu,
                ),
                (
                    UNAVAILABLE_CAPACITY_ACCOUNT,
                    HBM_RUNTIME_FIXED_ACCOUNT,
                    self.parameters.runtime_fixed_bytes_per_gpu,
                ),
                (
                    UNAVAILABLE_CAPACITY_ACCOUNT,
                    FREE_ACCOUNT,
                    unavailable - fixed_bytes,
                ),
            ],
            cause="GPU_REPAIR_HBM_EMPTY_REUSABLE",
        )
        if self.continuous_batch_enabled:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("continuous GPU repair lost its driver")
            old_authority = self.continuous_hbm_authorities[target_gpu]
            if not old_authority.failed:
                raise ExperimentError("continuous GPU repair replaced a live authority")
            authority = self._new_continuous_hbm_authority(target_gpu)
            driver.replace_repaired_target(
                self._new_continuous_bridge(target_gpu, authority)
            )
            self.continuous_hbm_authorities[target_gpu] = authority
        matching = [
            record
            for record in self.failure_events
            if record.get("failure_id") == failure_id
        ]
        if len(matching) != 1 or matching[0].get("repair_completed_at_ns") is not None:
            raise ExperimentError("GPU repair lost its unique failure record")
        matching[0]["repair_completed_at_ns"] = self.des.now_ns
        repair_record = {
            "failure_id": failure_id,
            "target_gpu_id": target_gpu,
            "failure_at_ns": int(matching[0]["timestamp_ns"]),
            "repair_after_ns": schedule.gpu_recovery_time_ns,
            "repair_completed_at_ns": self.des.now_ns,
            "hbm_restored_empty": True,
            "gpu_reusable": True,
        }
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_GPU_REPAIR_COMPLETE",
            repair_record,
        )
        self._repair_event_executed.add(failure_id)

    def _record_transfer(self, record: dict[str, Any]) -> None:
        transfer_id = _required_str(record, "transfer_id")
        if transfer_id in self._transfer_by_id:
            raise ExperimentError("duplicate transfer ledger ID")
        status = record.get("status")
        if status not in {"PENDING", "COMMITTED", "ABORTED"}:
            raise ExperimentError("new transfer ledger record has an unknown state")
        self.transfers.append(record)
        self._transfer_by_id[transfer_id] = record
        if status == "PENDING":
            self._pending_transfer_ledger_ids.add(transfer_id)
        else:
            self._terminal_transfer_ledger_ids.add(transfer_id)
            self._dirty_terminal_transfer_ledger_ids.add(transfer_id)

    @staticmethod
    def _validate_transfer_record(record: Mapping[str, Any]) -> None:
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

    def _validate_all_transfer_records(self) -> None:
        if self._pending_transfer_ledger_ids:
            raise ExperimentError("full transfer audit found pending ledger records")
        if len(self._terminal_transfer_ledger_ids) != len(self.transfers):
            raise ExperimentError("full transfer audit state index is incomplete")
        for record in self.transfers:
            self._validate_transfer_record(record)

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
        if transfer_id not in self._pending_transfer_ledger_ids:
            raise ExperimentError("committed transfer is absent from pending ledger index")
        self._pending_transfer_ledger_ids.remove(transfer_id)
        self._terminal_transfer_ledger_ids.add(transfer_id)
        self._dirty_terminal_transfer_ledger_ids.add(transfer_id)

    def _finish_fluid_service_record(
        self,
        transfer_id: str,
        *,
        task: TransferTask,
    ) -> None:
        try:
            record = self._transfer_by_id[transfer_id]
        except KeyError as error:
            raise ExperimentError("completed flow lacks a transfer ledger record") from error
        if record.get("status") != "PENDING":
            raise ExperimentError("only a pending transfer can finish fluid service")
        if task.status is not TransferStatus.COMPLETED:
            raise ExperimentError("fluid service completion requires a completed task")
        record["end_ns"] = self.des.now_ns
        record["planned_end_ns"] = max(
            int(record["planned_end_ns"]), self.des.now_ns
        )
        record["resource_intervals"] = self._flow_resource_intervals(transfer_id)

    def _abort_transfer_from_task(
        self,
        transfer_id: str,
        *,
        task: TransferTask,
        reason: str,
    ) -> None:
        try:
            record = self._transfer_by_id[transfer_id]
        except KeyError as error:
            raise ExperimentError("aborted flow lacks a transfer ledger record") from error
        if record.get("status") != "PENDING":
            raise ExperimentError("only a pending transfer can abort")
        if task.metadata.transfer_id != transfer_id or task.status not in {
            TransferStatus.WAITING,
            TransferStatus.CANCELED,
            TransferStatus.COMPLETED,
        }:
            raise ExperimentError("aborted transfer task state diverged from its owner")
        submitted_bytes = int(record["bytes"])
        intervals = self._flow_intervals_for_transfer(transfer_id)
        transferred_bytes = min(
            submitted_bytes,
            max(
                0,
                math.floor(
                    math.fsum(item.transferred_bytes for item in intervals) + 1e-6
                ),
            ),
        )
        record["status"] = "ABORTED"
        if self.des.now_ns < int(record["start_ns"]):
            record["start_ns"] = self.des.now_ns
        record["end_ns"] = self.des.now_ns
        record["planned_end_ns"] = max(
            int(record["planned_end_ns"]), self.des.now_ns
        )
        record["terminal_ns"] = self.des.now_ns
        record["transferred_bytes"] = transferred_bytes
        record["aborted_bytes"] = submitted_bytes - transferred_bytes
        record["terminal_reason"] = reason
        record["resource_intervals"] = self._flow_resource_intervals(transfer_id)
        if transfer_id not in self._pending_transfer_ledger_ids:
            raise ExperimentError("aborted transfer is absent from pending ledger index")
        self._pending_transfer_ledger_ids.remove(transfer_id)
        self._terminal_transfer_ledger_ids.add(transfer_id)
        self._dirty_terminal_transfer_ledger_ids.add(transfer_id)
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

    def _predicted_task_completion_ns(self, task: TransferTask) -> int:
        completion_ns = self.des.now_ns
        active_count = 0
        for item in task.slices:
            flow_id = f"transfer-flow:{item.slice_id}"
            flow = self.flow_model.flows.get(flow_id)
            if flow is None:
                continue
            active_count += 1
            if flow.allocated_rate_bytes_per_second <= 0:
                raise ExperimentError("active transfer slice has no fluid rate")
            duration_ns = math.ceil(
                flow.remaining_bytes
                * 1_000_000_000
                / flow.allocated_rate_bytes_per_second
            )
            completion_ns = max(completion_ns, self.des.now_ns + max(1, duration_ns))
        if active_count == 0 and task.status is TransferStatus.PENDING:
            raise ExperimentError("pending task has no active slice flow")
        return completion_ns

    def _flow_intervals_for_transfer(
        self, transfer_id: str
    ) -> tuple[FlowRateInterval, ...]:
        return tuple(
            item for item in self.flow_model.intervals if item.transfer_id == transfer_id
        )

    def _flow_resource_intervals(self, transfer_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        intervals = self._flow_intervals_for_transfer(transfer_id)
        for interval_index, item in enumerate(intervals):
            for resource_index, resource_id in enumerate(item.path_resource_ids):
                result.append(
                    {
                        "reservation_id": (
                            f"{item.flow_id}:rate-{interval_index:06d}-"
                            f"resource-{resource_index:02d}"
                        ),
                        "resource_id": resource_id,
                        "lane": 0,
                        "start_ns": item.start_ns,
                        "planned_end_ns": item.end_ns,
                        "actual_end_ns": item.end_ns,
                        "cause": item.cause,
                        "flow_id": item.flow_id,
                        "slice_id": item.slice_id,
                        "allocated_rate_bytes_per_second": (
                            item.allocated_rate_bytes_per_second
                        ),
                        "transferred_bytes": item.transferred_bytes,
                    }
                )
        return result

    def _on_failure_detect(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        active_ids = _required_str_list(event.payload, "active_span_ids")
        queued_ids = _required_str_list(event.payload, "queued_span_ids")
        reroute_only_queued_ids = set(
            _required_str_list(event.payload, "reroute_only_queued_span_ids")
            if "reroute_only_queued_span_ids" in event.payload
            else ()
        )
        if not reroute_only_queued_ids.issubset(queued_ids):
            raise ExperimentError("reroute-only failure spans are not queued")
        for span_id in queued_ids:
            execution = self.executions[span_id]
            self._reset_recovery_route_state(execution)
            execution.route_version += 1
            target = self._route_gpu(
                span_id,
                route_version=execution.route_version,
                required_hbm_bytes=_tokens_to_allocated_bytes(
                    execution.metadata.prompt_tokens
                ),
            )
            if self.continuous_batch_enabled:
                driver = self.continuous_batch_driver
                if driver is None:
                    raise ExperimentError("continuous queued recovery lost its driver")
                execution.gpu_id = target
                execution.status = _ExecutionStatus.RECOVERING
                if span_id in reroute_only_queued_ids:
                    # A scheduler WAITING request owns no resident primary KV
                    # and has already been reset to its normal recompute
                    # frontier. Rerouting it after a GPU failure does not
                    # create another prompt loss, so do not attribute ordinary
                    # FCFS prompt work to failure recovery.
                    execution.recompute_tokens = 0
                else:
                    # A request fenced while its prior recovery was in flight
                    # loses that recovery attempt and must source the prompt
                    # again after the new failure.
                    execution.recompute_tokens = execution.metadata.prompt_tokens
                driver.resume_external_request(
                    request_id=span_id,
                    target_id=target,
                    route_version=execution.route_version,
                    ready_ns=self.des.now_ns + self.parameters.reroute_ns,
                    restored_tokens=0,
                )
            else:
                self._schedule_compute(
                    execution,
                    gpu_id=target,
                    ready_ns=self.des.now_ns + self.parameters.reroute_ns,
                    duration_ns=execution.scheduled_duration_ns,
                )
        for span_id in active_ids:
            self._plan_recovery(self.executions[span_id])

    def _plan_recovery(self, execution: _SpanExecution) -> None:
        if execution.failure_at_ns is None:
            raise ExperimentError("recovery lacks failure progress timestamps")
        if self.continuous_batch_enabled:
            # The failure fence already froze the exact scheduler-visible output
            # position for every resident request.  A request may be in the
            # scheduler RUNNING queue without ever having participated in a
            # forward step, so wall-clock progress and compute_start_ns are not
            # valid continuous-batch progress evidence.
            if not (
                0
                <= execution.committed_output_tokens_at_failure
                <= execution.metadata.output_tokens
            ):
                raise ExperimentError("continuous failure output snapshot is invalid")
        else:
            if execution.compute_start_ns is None:
                raise ExperimentError("recovery lacks failure progress timestamps")
            elapsed = max(0, execution.failure_at_ns - execution.compute_start_ns)
            duration = max(1, execution.scheduled_duration_ns)
            progress = min(Fraction(elapsed, duration), Fraction(1))
            execution.committed_output_tokens_at_failure = int(
                execution.metadata.output_tokens * progress
            )
        self._reset_recovery_route_state(execution)
        execution.route_version += 1
        recovery_reserve_bytes = _tokens_to_allocated_bytes(
            execution.metadata.prompt_tokens
        )
        designated_peer_gpu = execution.designated_peer_gpu_id
        peer_protection_chunks = self._protection_chunks(
            execution,
            path="PEER_HBM",
        )
        store_protection_chunks = self._protection_chunks(
            execution,
            path="STORE_DRAM",
        )
        route_bound_peer_prefix = 0
        if (
            designated_peer_gpu is not None
            and designated_peer_gpu not in self.failed_gpu_ids
            and self.profile.peer_replication_fraction > 0
        ):
            route_bound_peer_prefix = self.peer_pools[
                designated_peer_gpu
            ].peek_prefix_tokens(peer_protection_chunks)
        target_gpu = self._route_gpu(
            execution.metadata.span_id,
            route_version=execution.route_version,
            required_hbm_bytes=recovery_reserve_bytes,
            recovery=True,
            preferred_gpu_id=(
                designated_peer_gpu if route_bound_peer_prefix > 0 else None
            ),
        )
        execution.gpu_id = target_gpu
        execution.status = _ExecutionStatus.RECOVERING
        # Recovery may opportunistically adopt only target-local inactive
        # primary cache.  Active-primary keys are observations without a pin or
        # reference-counted ownership model, so they are deliberately excluded.
        normal_primary_tokens = min(
            self.primary_pools[target_gpu].lookup_prefix_tokens(
                execution.chunks,
                now_ns=self.des.now_ns,
            ),
            execution.metadata.prompt_tokens,
        )
        peer_source_gpu: str | None = None
        committed_peer_tokens = 0
        if route_bound_peer_prefix > 0 and designated_peer_gpu is not None:
            peer_source_gpu = designated_peer_gpu
            committed_peer_tokens = self.peer_pools[
                peer_source_gpu
            ].lookup_prefix_tokens(
                peer_protection_chunks,
                now_ns=self.des.now_ns,
            )
        committed_store_tokens = (
            self._store_lookup_prefix_tokens(
                store_protection_chunks,
                now_ns=self.des.now_ns,
                mutate_signals=True,
            )
            if self.profile.store_fraction > 0
            else 0
        )
        if self._formal_policy_enabled():
            boundary_sets = []
            if committed_peer_tokens > 0:
                boundary_sets.append(_chunk_interval_boundaries(peer_protection_chunks))
            if committed_store_tokens > 0:
                boundary_sets.append(_chunk_interval_boundaries(store_protection_chunks))
            if boundary_sets:
                common_boundaries = set.intersection(*boundary_sets)
                normal_primary_tokens = max(
                    (
                        boundary
                        for boundary in common_boundaries
                        if boundary <= normal_primary_tokens
                    ),
                    default=0,
                )
            store_start = max(normal_primary_tokens, committed_peer_tokens)
            if (
                committed_store_tokens > store_start
                and store_start
                not in _chunk_interval_boundaries(store_protection_chunks)
            ):
                committed_store_tokens = store_start
        (
            execution.recovery_normal_hbm_local_tokens,
            execution.restored_peer_tokens,
            execution.restored_store_tokens,
            execution.recompute_tokens,
        ) = _recovery_source_intervals(
            execution.metadata.prompt_tokens,
            normal_prefix_tokens=normal_primary_tokens,
            peer_prefix_tokens=committed_peer_tokens,
            store_prefix_tokens=committed_store_tokens,
        )
        restored_tokens = (
            execution.recovery_normal_hbm_local_tokens
            + execution.restored_peer_tokens
            + execution.restored_store_tokens
        )
        normal_activation_bytes = 0
        peer_activation_bytes = 0
        local_activation_bytes = 0
        if execution.recovery_normal_hbm_local_tokens > 0:
            normal_activation_bytes = self.primary_pools[target_gpu].activate_prefix(
                execution.chunks,
                token_count=execution.recovery_normal_hbm_local_tokens,
                now_ns=self.des.now_ns,
                cause="RECOVERY_NORMAL_HBM_LOCAL_ADOPTION",
            )
            self._commit_hbm_moves(
                target_gpu,
                [
                    (
                        HBM_INACTIVE_REUSABLE_ACCOUNT,
                        HBM_RECOVERY_RESERVED_ACCOUNT,
                        normal_activation_bytes,
                    )
                ],
                cause="RECOVERY_NORMAL_HBM_LOCAL_ADOPTION",
            )
            local_activation_bytes += normal_activation_bytes
            self.recovery_source_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "NORMAL_HBM_LOCAL_ADOPTION",
                    "span_id": execution.metadata.span_id,
                    "route_version": execution.route_version,
                    "target_gpu_id": target_gpu,
                    "token_count": execution.recovery_normal_hbm_local_tokens,
                    "activated_bytes": normal_activation_bytes,
                    "transferred_bytes": 0,
                    "protection_evidence": False,
                }
            )
        if execution.restored_peer_tokens > 0 and peer_source_gpu == target_gpu:
            peer_interval_start = execution.recovery_normal_hbm_local_tokens
            peer_interval_end = peer_interval_start + execution.restored_peer_tokens
            activated_peer_chunks = tuple(
                chunk
                for chunk in peer_protection_chunks
                if chunk.token_start >= peer_interval_start
                and chunk.token_start + chunk.token_count <= peer_interval_end
            )
            formal_extra_keys: tuple[str, ...] = ()
            formal_extra_bytes = 0
            if self._formal_policy_enabled():
                formal_extra_keys, formal_extra_bytes = (
                    self._formal_release_role_transition_suffixes(
                        pool=self.peer_pools[target_gpu],
                        activated_chunks=activated_peer_chunks,
                        cause="RECOVERY_PEER_HBM_ROLE_RECLASSIFY",
                    )
                )
            peer_activation_bytes = self.peer_pools[target_gpu].activate_interval(
                peer_protection_chunks,
                start_token=peer_interval_start,
                token_count=execution.restored_peer_tokens,
                now_ns=self.des.now_ns,
                cause="AEGIS_RECOVERY_PEER_HBM_LOCAL_RECLASSIFY",
            )
            if formal_extra_keys:
                self.peer_pools[target_gpu].set_capacity_exact(
                    self.peer_pools[target_gpu].capacity_bytes,
                    victim_keys=formal_extra_keys,
                    proposed_rent=self.peer_pools[target_gpu].rent,
                    now_ns=self.des.now_ns,
                    cause="RECOVERY_PEER_HBM_SUFFIX_SAFETY_RELEASE",
                )
            hbm_moves = [
                (
                    HBM_PEER_PROTECTION_ACCOUNT,
                    HBM_RECOVERY_RESERVED_ACCOUNT,
                    peer_activation_bytes,
                )
            ]
            if formal_extra_bytes:
                hbm_moves.append(
                    (
                        HBM_PEER_PROTECTION_ACCOUNT,
                        FREE_ACCOUNT,
                        formal_extra_bytes,
                    )
                )
            self._commit_hbm_moves(
                target_gpu,
                hbm_moves,
                cause="AEGIS_RECOVERY_PEER_HBM_LOCAL_RECLASSIFY",
            )
            local_activation_bytes += peer_activation_bytes
            execution.restored_peer_local_tokens = execution.restored_peer_tokens
            self.recovery_source_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "PEER_HBM_LOCAL_ACTIVATION",
                    "span_id": execution.metadata.span_id,
                    "route_version": execution.route_version,
                    "target_gpu_id": target_gpu,
                    "token_count": execution.restored_peer_local_tokens,
                    "activated_bytes": peer_activation_bytes,
                    "transferred_bytes": 0,
                    "protection_evidence": True,
                }
            )
        elif execution.restored_peer_tokens > 0:
            execution.restored_peer_d2d_tokens = execution.restored_peer_tokens
        missing_reserve_bytes = recovery_reserve_bytes - local_activation_bytes
        if missing_reserve_bytes < 0:
            raise ExperimentError("local Peer-HBM activation exceeded recovery reserve")
        self._latch_aimd_foreground_pressure(
            target_gpu,
            missing_reserve_bytes,
            reason="RECOVERY_DESTINATION_HEADROOM_SHORTFALL",
        )
        if not self._preempt_peer_puts_for_foreground_hbm(
            target_gpu,
            missing_reserve_bytes,
        ):
            self._latch_aimd_foreground_pressure(
                target_gpu,
                missing_reserve_bytes,
                reason="RECOVERY_DESTINATION_ALLOCATION_OR_RECLAIM_STALL",
                force=True,
            )
            raise ExperimentError(
                "recovery KV cannot fit after preserving its local Peer-HBM prefix"
            )
        self._commit_hbm_moves(
            target_gpu,
            [
                (
                    FREE_ACCOUNT,
                    HBM_RECOVERY_RESERVED_ACCOUNT,
                    missing_reserve_bytes,
                )
            ],
            cause="AEGIS_RECOVERY_DESTINATION_RESERVE_MISSING_SUFFIX",
        )
        execution.hbm_recovery_reserved_bytes = recovery_reserve_bytes
        execution.hbm_allocation_gpu_id = target_gpu
        if self.continuous_batch_enabled:
            self.continuous_hbm_authorities[
                target_gpu
            ].observe_external_recovery_reservation(
                request_id=execution.metadata.span_id,
                reserved_bytes=recovery_reserve_bytes,
            )

        ready_ns = self.des.now_ns + self.parameters.reroute_ns
        recovery_transfer_ids: set[str] = set()
        store_recovery_bytes = self._store_recovery_bytes_by_segment(
            execution,
            start_token=(
                execution.recovery_normal_hbm_local_tokens
                + execution.restored_peer_tokens
            ),
            token_count=execution.restored_store_tokens,
        )
        transfer_specs: list[tuple[str, str, int]] = []
        if execution.restored_peer_tokens > 0 and peer_source_gpu != target_gpu:
            if peer_source_gpu is None:
                raise ExperimentError("Peer-HBM recovery lost its committed source")
            transfer_specs.append(
                (
                    "PEER_HBM",
                    peer_source_gpu,
                    _prefix_bytes_between(
                        execution.chunks,
                        execution.recovery_normal_hbm_local_tokens,
                        execution.recovery_normal_hbm_local_tokens
                        + execution.restored_peer_tokens,
                    ),
                )
            )
        transfer_specs.extend(
            ("STORE_DRAM", segment_id, transfer_bytes)
            for segment_id, transfer_bytes in store_recovery_bytes.items()
        )
        for source, transfer_source, transfer_bytes in transfer_specs:
            transfer_id = self._next_id(
                f"recovery:{source}:{transfer_source}:{execution.metadata.span_id}"
            )
            cause = f"AEGIS_RECOVERY_{source}"
            transfer_start_ns = ready_ns + self.parameters.transfer_setup_ns
            task = self._make_transfer_task(
                transfer_id=transfer_id,
                span_id=execution.metadata.span_id,
                source_id=transfer_source,
                target_id=target_gpu,
                cause=cause,
                route_version=execution.route_version,
                ready_ns=transfer_start_ns,
                total_bytes=transfer_bytes,
            )
            start_handle = self.des.schedule_at(
                transfer_start_ns,
                EventKind.RECOVERY_START,
                event_id=f"flow-start:{transfer_id}",
                payload={"transfer_id": transfer_id},
            )
            self.pending_recovery_transfers[transfer_id] = _PendingRecoveryTransfer(
                transfer_id=transfer_id,
                span_id=execution.metadata.span_id,
                source=source,
                source_gpu_id=transfer_source,
                target_gpu_id=target_gpu,
                task=task,
                handle=start_handle,
                bytes=transfer_bytes,
                staging_bytes=max(item.length_bytes for item in task.slices),
            )
            recovery_transfer_ids.add(transfer_id)
            bandwidth = min(
                self.transfer_rate_resources[resource_id].capacity_bytes_per_second
                for resource_id in task.metadata.path.rate_resource_ids
            )
            initial_service_ns = math.ceil(
                transfer_bytes * 1_000_000_000 / bandwidth
            )
            self._record_transfer(
                _transfer_record(
                    transfer_id=transfer_id,
                    path="D2D_P2P" if source == "PEER_HBM" else "STORE_H2D",
                    cause=cause,
                    start_ns=transfer_start_ns,
                    end_ns=transfer_start_ns + max(1, initial_service_ns),
                    bytes=transfer_bytes,
                    source_gpu_id=transfer_source,
                    target_gpu_id=target_gpu,
                    ready_ns=ready_ns,
                    status="PENDING",
                    span_id=execution.metadata.span_id,
                    flow_slice_count=len(task.slices),
                )
            )
            self._bind_transfer_task_metadata(task)
        if recovery_transfer_ids:
            self.recovery_transfer_ids_by_span[execution.metadata.span_id] = (
                recovery_transfer_ids
            )
        else:
            self._schedule_recovery_materialized(execution, at_ns=ready_ns)
        self.recovery_events.append(
            {
                "timestamp_ns": self.des.now_ns,
                "event": "RECOVERY_PLAN",
                "span_id": execution.metadata.span_id,
                "route_version": execution.route_version,
                "target_gpu_id": target_gpu,
                "peer_source_gpu_id": peer_source_gpu,
                "store_source_segment_ids": sorted(store_recovery_bytes),
                "source_tokens": {
                    "NORMAL_HBM_LOCAL": execution.recovery_normal_hbm_local_tokens,
                    "PEER_HBM": execution.restored_peer_tokens,
                    "STORE_DRAM": execution.restored_store_tokens,
                    "RECOMPUTE": execution.recompute_tokens,
                },
                "effective_prefix_tokens": restored_tokens,
                "local_normal_adoption_bytes": normal_activation_bytes,
                "local_peer_activation_bytes": peer_activation_bytes,
                "new_recovery_reserve_bytes": missing_reserve_bytes,
                "continuous_prefix_only": True,
                "all_shards_required": True,
                "protection_sources_committed_only": True,
                "normal_hbm_is_opportunistic_not_protection": True,
                "in_flight_protection_estimate_used": False,
            }
        )

    def _on_recovery_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        transfer_id = _required_str(event.payload, "transfer_id")
        pending = self.pending_recovery_transfers.get(transfer_id)
        if pending is None or pending.handle != EventHandle(event.event_id):
            raise ExperimentError("unknown or stale recovery flow start")
        if pending.target_gpu_id in self.failed_gpu_ids or (
            pending.source != "STORE_DRAM"
            and pending.source_gpu_id in self.failed_gpu_ids
        ):
            raise ExperimentError("failed GPU reached a recovery flow start")
        execution = self.executions[pending.span_id]
        recovery_group = self.recovery_transfer_ids_by_span.get(pending.span_id)
        if recovery_group is None or transfer_id not in recovery_group:
            raise ExperimentError("recovery flow start lost its transfer group")
        if not recovery_group.issubset(self.pending_recovery_transfers):
            raise ExperimentError("recovery flow group lost a pending transfer")
        grouped_transfers = tuple(
            self.pending_recovery_transfers[item]
            for item in sorted(recovery_group)
        )
        if any(
            item.span_id != pending.span_id
            or item.target_gpu_id != pending.target_gpu_id
            or item.task.status
            not in {TransferStatus.WAITING, TransferStatus.PENDING}
            for item in grouped_transfers
        ):
            raise ExperimentError("recovery flow group destination ownership diverged")
        inbound_bytes = sum(item.bytes for item in grouped_transfers)
        ledger = self.hbm_ledgers[pending.target_gpu_id]
        if (
            execution.hbm_allocation_gpu_id != pending.target_gpu_id
            or execution.hbm_recovery_reserved_bytes <= 0
            or inbound_bytes > execution.hbm_recovery_reserved_bytes
            or ledger.bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT)
            < execution.hbm_recovery_reserved_bytes
        ):
            raise ExperimentError(
                "inbound recovery transfer lacks its reserved destination HBM"
            )
        destination_write = {
            "timestamp_ns": self.des.now_ns,
            "event": "RECOVERY_RESERVED_DESTINATION_WRITE_START",
            "transfer_id": transfer_id,
            "span_id": pending.span_id,
            "route_version": execution.route_version,
            "target_gpu_id": pending.target_gpu_id,
            "transfer_bytes": pending.bytes,
            "borrowed_destination_window_bytes": pending.staging_bytes,
            "recovery_reserved_bytes": execution.hbm_recovery_reserved_bytes,
            "additional_hbm_charge_bytes": 0,
        }
        self.recovery_events.append(destination_write)
        self.des.journal.append(
            self.des.now_ns,
            "AEGIS_RECOVERY_RESERVED_DESTINATION_WRITE_START",
            destination_write,
        )
        try:
            self._acquire_transfer_overlays(pending.task)
            self.transfer_runtime.start_task(
                pending.task,
                on_terminal=self._on_recovery_task_terminal,
            )
        except Exception:
            if transfer_id in self.active_source_pins:
                self._release_transfer_overlays(
                    pending.task,
                    reason="RECOVERY_FLOW_START_FAILED",
                )
            raise
        record = self._transfer_by_id[transfer_id]
        record["start_ns"] = self.des.now_ns
        predicted_end_ns = self._predicted_task_completion_ns(pending.task)
        record["planned_end_ns"] = predicted_end_ns
        record["end_ns"] = predicted_end_ns

    def _abort_recovery_groups_for_gpu_failure(
        self,
        failed_gpu_id: str,
        *,
        failure_id: str,
    ) -> tuple[str, ...]:
        """Cancel every atomic recovery group depending on one failed GPU."""

        impacted_spans = sorted(
            {
                pending.span_id
                for pending in self.pending_recovery_transfers.values()
                if pending.target_gpu_id == failed_gpu_id
                or (
                    pending.source != "STORE_DRAM"
                    and pending.source_gpu_id == failed_gpu_id
                )
            }
        )
        # A no-transfer recovery still owns a future materialization event and
        # destination reservation.  It is equally fenced when that target dies.
        impacted_spans.extend(
            sorted(
                execution.metadata.span_id
                for execution in self.executions.values()
                if execution.status is _ExecutionStatus.RECOVERING
                and execution.gpu_id == failed_gpu_id
                and execution.completion_handle is not None
                and execution.metadata.span_id not in impacted_spans
            )
        )
        for span_id in impacted_spans:
            transfer_ids = tuple(
                sorted(self.recovery_transfer_ids_by_span.get(span_id, ()))
            )
            for transfer_id in transfer_ids:
                pending = self.pending_recovery_transfers.get(transfer_id)
                if pending is None:
                    raise ExperimentError("recovery group lost a pending transfer")
                reason = f"GPU_FAILURE_RECOVERY_DEPENDENCY:{failure_id}"
                if pending.task.status is TransferStatus.WAITING:
                    if not self.des.cancel(pending.handle, reason=reason):
                        raise ExperimentError(
                            "waiting recovery transfer start was not cancellable"
                        )
                    pending.task.cancel_remaining(
                        timestamp_ns=self.des.now_ns,
                        reason=reason,
                    )
                    self._abort_transfer_from_task(
                        transfer_id,
                        task=pending.task,
                        reason=reason,
                    )
                    del self.pending_recovery_transfers[transfer_id]
                    remaining = self.recovery_transfer_ids_by_span[span_id]
                    remaining.remove(transfer_id)
                    if not remaining:
                        del self.recovery_transfer_ids_by_span[span_id]
                elif pending.task.status is TransferStatus.PENDING:
                    self.transfer_runtime.abort_task(transfer_id, reason=reason)
                else:
                    raise ExperimentError(
                        "recovery failure fence found a terminal transfer"
                    )
            if span_id in self.recovery_transfer_ids_by_span:
                raise ExperimentError("recovery failure fence left a live transfer group")
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "RECOVERY_PLAN_ABORTED_BY_GPU_FAILURE",
                    "span_id": span_id,
                    "failure_id": failure_id,
                    "failed_gpu_id": failed_gpu_id,
                    "transfer_ids": list(transfer_ids),
                    "replan_mode": "FULL_PROMPT_RECOMPUTE_AFTER_FAILURE_DETECT",
                }
            )
        return tuple(impacted_spans)

    def _on_recovery_task_terminal(
        self, task: TransferTask, _des: GlobalDES
    ) -> None:
        transfer_id = task.metadata.transfer_id
        pending = self.pending_recovery_transfers.pop(transfer_id, None)
        if pending is None or pending.task is not task:
            raise ExperimentError("recovery flow terminal callback lost its owner")
        if task.status is TransferStatus.CANCELED:
            self._release_transfer_overlays(
                task,
                reason="RECOVERY_FLOW_ABORTED",
            )
            self._abort_transfer_from_task(
                transfer_id,
                task=task,
                reason="GPU_FAILURE_RECOVERY_FLOW_ABORTED",
            )
            remaining = self.recovery_transfer_ids_by_span.get(pending.span_id)
            if remaining is None or transfer_id not in remaining:
                raise ExperimentError("aborted recovery group lost a transfer")
            remaining.remove(transfer_id)
            if not remaining:
                del self.recovery_transfer_ids_by_span[pending.span_id]
            return
        if task.status is not TransferStatus.COMPLETED:
            raise ExperimentError("recovery flow did not complete successfully")
        self._release_transfer_overlays(
            task,
            reason="RECOVERY_FLOW_SERVICE_COMPLETED",
        )
        self._finish_fluid_service_record(transfer_id, task=task)
        self._commit_transfer(transfer_id)
        remaining = self.recovery_transfer_ids_by_span.get(pending.span_id)
        if remaining is None or transfer_id not in remaining:
            raise ExperimentError("recovery flow group lost a transfer")
        remaining.remove(transfer_id)
        if not remaining:
            del self.recovery_transfer_ids_by_span[pending.span_id]
            self._schedule_recovery_materialized(
                self.executions[pending.span_id], at_ns=self.des.now_ns
            )

    def _schedule_recovery_materialized(
        self, execution: _SpanExecution, *, at_ns: int
    ) -> None:
        if execution.gpu_id is None:
            raise ExperimentError("recovery destination GPU is absent")
        if execution.completion_handle is not None:
            raise ExperimentError("recovery already owns a completion event")
        execution.completion_handle = self.des.schedule_at(
            at_ns,
            EventKind.RECOVERY_COMPLETE,
            event_id=self._next_id(f"recovery-ready:{execution.metadata.span_id}"),
            payload={
                "span_id": execution.metadata.span_id,
                "route_version": execution.route_version,
                "target_gpu_id": execution.gpu_id,
                "recovery_normal_hbm_local_tokens": (
                    execution.recovery_normal_hbm_local_tokens
                ),
                "restored_peer_tokens": execution.restored_peer_tokens,
                "restored_store_tokens": execution.restored_store_tokens,
                "recompute_tokens": execution.recompute_tokens,
            },
        )

    def _schedule_recovery_compute_phase(
        self,
        execution: _SpanExecution,
        *,
        target_gpu: str,
        kind: _ComputeKind,
        duration_ns: int,
    ) -> tuple[int, int]:
        if kind is _ComputeKind.NORMAL:
            raise ExperimentError("normal compute is not a recovery phase")
        if duration_ns > 0:
            booking = self._book_ready_recovery_compute(
                execution,
                gpu_id=target_gpu,
                kind=kind,
                duration_ns=duration_ns,
            )
            return booking.start_ns, booking.end_ns

        span_id = execution.metadata.span_id
        if span_id in self._compute_bookings_by_span:
            raise ExperimentError("zero-duration recovery overlaps a live booking")
        generation = self._next_compute_generation(span_id)
        completion_kind = {
            _ComputeKind.RECOVERY_PROMPT: EventKind.RECOVERY_RECOMPUTE_COMPLETE,
            _ComputeKind.RECOVERY_SILENT: EventKind.SILENT_REPLAY_COMPLETE,
            _ComputeKind.RECOVERY_DECODE: EventKind.REQUEST_COMPLETE,
        }[kind]
        payload = {
            "span_id": span_id,
            "route_version": execution.route_version,
            "target_gpu_id": target_gpu,
            "gpu_id": target_gpu,
            "compute_kind": kind.value,
            "compute_generation": generation,
            "reservation_id": f"zero-duration:{kind.value}:{span_id}:{generation}",
            "zero_duration_compute": True,
        }
        handle = self.des.schedule_at(
            self.des.now_ns,
            completion_kind,
            event_id=self._next_id(f"zero-duration-compute:{span_id}"),
            payload=payload,
        )
        execution.compute_start_ns = self.des.now_ns
        execution.planned_complete_ns = self.des.now_ns
        execution.reservation_id = None
        execution.completion_handle = handle
        execution.scheduled_duration_ns = 0
        if kind is _ComputeKind.RECOVERY_PROMPT:
            execution.prompt_recompute_start_ns = self.des.now_ns
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                    "span_id": span_id,
                    "route_version": execution.route_version,
                    "target_gpu_id": target_gpu,
                    "recompute_tokens": execution.recompute_tokens,
                    "duration_ns": 0,
                    "zero_duration_bypass": True,
                }
            )
        elif kind is _ComputeKind.RECOVERY_SILENT:
            execution.silent_replay_start_ns = self.des.now_ns
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "SILENT_REPLAY_START",
                    "span_id": span_id,
                    "route_version": execution.route_version,
                    "target_gpu_id": target_gpu,
                    "replayed_output_tokens": (
                        execution.committed_output_tokens_at_failure
                    ),
                    "duration_ns": 0,
                    "externally_emitted_tokens": 0,
                    "zero_duration_bypass": True,
                }
            )
        else:
            execution.resume_decode_start_ns = self.des.now_ns
            execution.status = _ExecutionStatus.RESUMED
        return self.des.now_ns, self.des.now_ns

    def _finish_recovery_compute_phase(
        self,
        event: ScheduledEvent,
        *,
        kind: _ComputeKind,
    ) -> None:
        if bool(event.payload.get("zero_duration_compute", False)):
            span_id = _required_str(event.payload, "span_id")
            execution = self.executions[span_id]
            if (
                _required_str(event.payload, "compute_kind") != kind.value
                or span_id in self._compute_bookings_by_span
                or execution.completion_handle != EventHandle(event.event_id)
            ):
                raise ExperimentError("zero-duration recovery completion is invalid")
            execution.completion_handle = None
            return
        self._finish_compute_booking(event, expected_kinds={kind})

    def _on_recovery_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        """Materialize restored KV, then recompute the missing prompt suffix.

        Recovery compute phases use separate resource reservations so their
        causal order is explicit on the single global DES clock:
        restore -> prompt recompute -> silent replay -> activate -> decode.
        """

        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if execution.completion_handle != EventHandle(event.event_id):
            raise ExperimentError("stale recovery materialization crossed its fence")
        execution.completion_handle = None
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale recovery plan reached materialization")
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu in self.failed_gpu_ids:
            raise ExperimentError("recovery selected a failed target")
        if execution.hbm_staging_bytes != 0:
            raise ExperimentError("recovery materialized with live transfer staging")
        restored_tokens = (
            execution.recovery_normal_hbm_local_tokens
            + execution.restored_peer_tokens
            + execution.restored_store_tokens
        )
        if self.continuous_batch_enabled:
            driver = self.continuous_batch_driver
            if driver is None:
                raise ExperimentError("continuous recovery lost its scheduler driver")
            restored_tokens = _logical_page_aligned_prefix(
                restored_tokens,
                logical_page_tokens=16,
            )
            normal_tokens = min(
                execution.recovery_normal_hbm_local_tokens,
                restored_tokens,
            )
            peer_tokens = min(
                execution.restored_peer_tokens,
                restored_tokens - normal_tokens,
            )
            store_tokens = min(
                execution.restored_store_tokens,
                restored_tokens - normal_tokens - peer_tokens,
            )
            execution.recovery_normal_hbm_local_tokens = normal_tokens
            execution.restored_peer_tokens = peer_tokens
            execution.restored_peer_local_tokens = min(
                execution.restored_peer_local_tokens,
                peer_tokens,
            )
            execution.restored_peer_d2d_tokens = (
                peer_tokens - execution.restored_peer_local_tokens
            )
            execution.restored_store_tokens = store_tokens
            execution.recompute_tokens = (
                execution.metadata.prompt_tokens - restored_tokens
            )
            restored_bytes = _tokens_to_allocated_bytes(restored_tokens)
            if restored_bytes > execution.hbm_recovery_reserved_bytes:
                raise ExperimentError(
                    "continuous restored prefix exceeds its physical reservation"
                )
            self.continuous_hbm_authorities[
                target_gpu
            ].trim_external_recovery_reservation(
                request_id=span_id,
                retained_bytes=restored_bytes,
                cause="CONTINUOUS_RECOVERY_RELEASE_RECOMPUTE_SUFFIX_RESERVE",
            )
            execution.hbm_recovery_reserved_bytes = restored_bytes
            execution.hbm_allocated_bytes = 0
            # The prefix is not ACTIVE yet, but its destination reservation is
            # still physically owned by this target while connector admission
            # waits for logical scheduler pages.
            execution.hbm_allocation_gpu_id = target_gpu
            execution.status = _ExecutionStatus.RECOVERING
            execution.gpu_id = target_gpu
            self.recovery_events.append(
                {
                    "timestamp_ns": self.des.now_ns,
                    "event": "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
                    "span_id": span_id,
                    "route_version": execution.route_version,
                    "target_gpu_id": target_gpu,
                    "restored_tokens": restored_tokens,
                    "restored_physical_bytes": restored_bytes,
                    "recompute_tokens": execution.recompute_tokens,
                    "silent_replay_tokens": (
                        execution.committed_output_tokens_at_failure
                    ),
                }
            )
            driver.resume_external_request(
                request_id=span_id,
                target_id=target_gpu,
                route_version=execution.route_version,
                ready_ns=self.des.now_ns,
                restored_tokens=restored_tokens,
            )
            return
        restored_bytes = min(
            execution.hbm_recovery_reserved_bytes,
            _tokens_to_allocated_bytes(restored_tokens) if restored_tokens > 0 else 0,
        )
        if restored_bytes > 0:
            self._commit_hbm_moves(
                target_gpu,
                [
                    (
                        HBM_RECOVERY_RESERVED_ACCOUNT,
                        HBM_ACTIVE_PRIMARY_ACCOUNT,
                        restored_bytes,
                    )
                ],
                cause="AEGIS_RECOVERY_RESTORED_KV_MATERIALIZE",
            )
            execution.hbm_recovery_reserved_bytes -= restored_bytes
            execution.hbm_allocated_bytes += restored_bytes
        execution.status = _ExecutionStatus.RECOVERING
        execution.gpu_id = target_gpu
        prompt_recompute_ns, _silent_ns, _remaining_decode_ns = (
            _post_failure_compute_durations(execution)
        )
        self._schedule_recovery_compute_phase(
            execution,
            target_gpu=target_gpu,
            kind=_ComputeKind.RECOVERY_PROMPT,
            duration_ns=prompt_recompute_ns,
        )

    def _on_recovery_recompute_complete(
        self, event: ScheduledEvent, _des: GlobalDES
    ) -> None:
        """Replay committed output only after the prompt block table is rebuilt."""

        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale route finished prompt suffix recompute")
        self._finish_recovery_compute_phase(
            event, kind=_ComputeKind.RECOVERY_PROMPT
        )
        target_gpu = _required_str(event.payload, "target_gpu_id")
        if target_gpu in self.failed_gpu_ids:
            raise ExperimentError("failed recovery target finished prompt recompute")
        if execution.hbm_recovery_reserved_bytes > 0:
            recomputed_bytes = execution.hbm_recovery_reserved_bytes
            self._commit_hbm_moves(
                target_gpu,
                [
                    (
                        HBM_RECOVERY_RESERVED_ACCOUNT,
                        HBM_ACTIVE_PRIMARY_ACCOUNT,
                        recomputed_bytes,
                    )
                ],
                cause="AEGIS_RECOVERY_RECOMPUTED_KV_MATERIALIZE",
            )
            execution.hbm_recovery_reserved_bytes = 0
            execution.hbm_allocated_bytes += recomputed_bytes
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
        self._schedule_recovery_compute_phase(
            execution,
            target_gpu=target_gpu,
            kind=_ComputeKind.RECOVERY_SILENT,
            duration_ns=silent_ns,
        )

    def _on_silent_replay_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        span_id = _required_str(event.payload, "span_id")
        execution = self.executions[span_id]
        if _required_int(event.payload, "route_version") != execution.route_version:
            raise ExperimentError("stale route finished silent replay")
        self._finish_recovery_compute_phase(
            event, kind=_ComputeKind.RECOVERY_SILENT
        )
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
        start_ns, _complete_ns = self._schedule_recovery_compute_phase(
            execution,
            target_gpu=target_gpu,
            kind=_ComputeKind.RECOVERY_DECODE,
            duration_ns=remaining_decode_ns,
        )
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

    def _residual_predicted_duration_ns(
        self,
        execution: _SpanExecution,
        *,
        at_ns: int,
    ) -> int:
        """Predicted remaining agent time for residual UpdateSlack.

        Not-yet-started nodes keep the full recorded duration.  Active nodes use
        remaining live compute on the GlobalDES clock, which is the same unit as
        ``recorded_api_time_ns`` after release.
        """

        metadata = execution.metadata
        if execution.completed_ns is not None:
            return 0
        if execution.released_ns is None or execution.compute_start_ns is None:
            return max(1, metadata.recorded_api_time_ns)
        if execution.planned_complete_ns is not None:
            return max(0, execution.planned_complete_ns - at_ns)
        return max(0, metadata.recorded_api_time_ns - (at_ns - execution.compute_start_ns))

    def _published_slack_signal(self, span_id: str) -> SlackSignal:
        published = self._published_slack.get(span_id)
        if published is not None:
            return published
        # Fail-closed: missing residual observation is treated as Valid=false.
        execution = self.executions[span_id]
        observed_at_ns = (
            execution.released_ns if execution.released_ns is not None else 0
        )
        return SlackSignal(
            slack_at_observation_ns=Fraction(0, 1),
            observed_at_ns=observed_at_ns,
            version=0,
        )

    def _slack_signal_at(self, span_id: str, at_ns: int) -> SlackSignal:
        history = self._published_slack_history.get(span_id, [])
        eligible = [signal for signal in history if signal.observed_at_ns <= at_ns]
        if eligible:
            return eligible[-1]
        return self._published_slack_signal(span_id)

    def _formal_retry_parked_suffixes_after_slack_update(
        self,
        span_ids: Sequence[str],
    ) -> None:
        if not self._formal_policy_enabled():
            return
        for span_id in span_ids:
            for path in ("PEER_HBM", "STORE_DRAM"):
                key = (span_id, path)
                if key in self._formal_blocked_request_paths:
                    continue
                if key in self._formal_active_request_paths:
                    continue
                if not self._formal_waiting_put_starts.get(key):
                    continue
                self._formal_finish_request_path(span_id, path, block=False)

    def _update_residual_slack(
        self,
        workflow_id: str,
        *,
        reason: str,
        trigger_span_id: str,
    ) -> None:
        """Algorithm 1 UpdateSlack on the causally visible residual DAG."""

        if self.profile.slack_weight <= 0:
            return
        now_ns = self.des.now_ns
        workflow_spans = [
            execution.metadata
            for execution in self.executions.values()
            if execution.metadata.workflow_id == workflow_id
        ]
        remaining: dict[str, int] = {}
        active: list[str] = []
        for metadata in workflow_spans:
            execution = self.executions[metadata.span_id]
            if execution.completed_ns is not None:
                continue
            remaining[metadata.span_id] = self._residual_predicted_duration_ns(
                execution,
                at_ns=now_ns,
            )
            if execution.released_ns is not None:
                active.append(metadata.span_id)
        if not remaining:
            return
        residual = compute_residual_ideal_trace_cpm(
            workflow_spans,
            remaining,
        )
        published: list[dict[str, object]] = []
        slack_decreased: list[str] = []
        for span_id in active:
            timing = residual.timing(span_id)
            previous = self._published_slack.get(span_id)
            previous_remaining_ns = (
                None if previous is None else int(previous.value_at(now_ns))
            )
            signal = SlackSignal(
                slack_at_observation_ns=Fraction(timing.slack_ns, 1),
                observed_at_ns=now_ns,
                version=1 if previous is None else previous.version + 1,
            )
            self._published_slack[span_id] = signal
            self._published_slack_history.setdefault(span_id, []).append(signal)
            if previous_remaining_ns is None or timing.slack_ns < previous_remaining_ns:
                slack_decreased.append(span_id)
            published.append(
                {
                    "span_id": span_id,
                    "residual_duration_ns": timing.duration_ns,
                    "slack_ns": timing.slack_ns,
                    "critical": timing.critical,
                    "version": signal.version,
                    "previous_slack_ns": (
                        None
                        if previous is None
                        else int(previous.slack_at_observation_ns)
                    ),
                }
            )
        event = {
            "timestamp_ns": now_ns,
            "event": "ALGORITHM1_RESIDUAL_SLACK_UPDATE",
            "workflow_id": workflow_id,
            "reason": reason,
            "trigger_span_id": trigger_span_id,
            "remaining_span_count": len(remaining),
            "active_frontier": active,
            "published": published,
            "residual_makespan_ns": residual.workflow_makespan_ns.get(workflow_id),
        }
        self.slack_update_events.append(event)
        self.des.journal.append(now_ns, "AEGIS_ALGORITHM1_RESIDUAL_SLACK_UPDATE", event)
        self._formal_retry_parked_suffixes_after_slack_update(slack_decreased)

    def _remaining_ideal_slack_ns(
        self,
        execution: _SpanExecution,
        *,
        at_ns: int,
    ) -> int:
        if execution.released_ns is None or at_ns < execution.released_ns:
            raise ExperimentError("remaining slack lacks a valid release observation")
        history = getattr(self, "_published_slack_history", {}).get(
            execution.metadata.span_id
        )
        if history:
            eligible = [
                signal for signal in history if signal.observed_at_ns <= at_ns
            ]
            if eligible:
                return int(eligible[-1].value_at(at_ns))
        published = getattr(self, "_published_slack", {}).get(execution.metadata.span_id)
        if published is not None and at_ns >= published.observed_at_ns:
            return int(published.value_at(at_ns))
        initial_slack_ns = self.algorithm1_cpm.timing(
            execution.metadata.span_id
        ).slack_ns
        return max(0, initial_slack_ns - (at_ns - execution.released_ns))

    def _chunk_score(
        self,
        execution: _SpanExecution,
        chunk: _Chunk,
        *,
        path: str,
        modeled_pool: _ModeledPool,
        sequence_index: int,
    ) -> Fraction:
        """Evaluate the patent J/W/Uhit/Ulru/G/P/H equations exactly."""

        metadata = execution.metadata
        if execution.released_ns is None:
            raise ExperimentError("sealed chunk lacks a slack release observation")
        pool = PolicyPool.PEER_HBM if path == "PEER_HBM" else PolicyPool.STORE_DRAM
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
        published_slack = (
            self._published_slack_signal(metadata.span_id)
            if recovery_value_enabled and self.profile.slack_weight > 0
            else None
        )
        slack_ns = (
            int(published_slack.slack_at_observation_ns)
            if published_slack is not None
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
                observed_at_ns=(
                    published_slack.observed_at_ns
                    if published_slack is not None
                    else execution.released_ns
                ),
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
        workflow_wct_by_id = {
            workflow_id: workflow_ends[workflow_id] - start_ns
            for workflow_id, start_ns in sorted(workflow_starts.items())
        }
        workflow_wct = list(workflow_wct_by_id.values())
        earliest = min(workflow_starts.values())
        workload_end_ns = max(workflow_ends.values())
        elapsed_ns = max(1, workload_end_ns - earliest)
        output_tokens = sum(item.metadata.output_tokens for item in completed)
        failure_active = sum(
            len(item["impacted_active_span_ids"]) for item in self.failure_events
        )
        failure_queued = sum(
            len(item["impacted_queued_span_ids"]) for item in self.failure_events
        )
        if self.failure_schedule is not None and failure_active == 0:
            raise ExperimentError("frozen failure did not hit an active request")
        if self.failure_schedule is not None and len(self.failure_events) != len(
            self.failure_schedule.events
        ):
            raise ExperimentError("not every frozen failure event was recorded")
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
        normal_hbm_by_gpu = {
            gpu_id: {
                "capacity_bytes": pool.capacity_bytes,
                "final_bytes": pool.occupied_bytes,
                "peak_bytes": pool.peak_bytes,
                "byte_ns": pool.byte_ns,
                "evicted_chunks": pool.evicted_chunks,
                "alias_hits": pool.alias_hits,
                "failed_unavailable": pool.failed,
                "lost_committed_bytes": pool.lost_committed_bytes,
                "valid": (
                    pool.occupied_bytes <= pool.capacity_bytes
                    and not pool.pending
                    and pool.pending_bytes == 0
                ),
            }
            for gpu_id, pool in sorted(self.primary_pools.items())
        }
        hbm_by_gpu = {
            gpu_id: _summarize_hbm_timeline(self.hbm_ledgers[gpu_id], timeline)
            for gpu_id, timeline in sorted(self.hbm_timelines.items())
        }
        host_dram_by_gpu = {
            gpu_id: _summarize_hbm_timeline(
                self.host_staging_ledgers[gpu_id], timeline
            )
            for gpu_id, timeline in sorted(self.host_staging_timelines.items())
        }
        store_timeline = _aggregate_pool_timeline(self.store_pools)
        store_peak_bytes = max(
            (int(point["occupied_bytes"]) for point in store_timeline),
            default=0,
        )
        store_by_segment = {
            segment_id: {
                "capacity_bytes": pool.capacity_bytes,
                "final_bytes": pool.occupied_bytes,
                "peak_bytes": pool.peak_bytes,
                "pending_peak_bytes": pool.pending_peak_bytes,
                "byte_ns": pool.byte_ns,
                "failed_unavailable": False,
                "valid": (
                    pool.occupied_bytes + pool.pending_bytes <= pool.capacity_bytes
                ),
            }
            for segment_id, pool in sorted(self.store_pools.items())
        }
        transfer_accounting = _aggregate_transfer_accounting(self.transfers)
        metrics = {
            "virtual_end_ns": end_ns,
            "workload_end_ns": workload_end_ns,
            "workflow_completion_time_ns": {
                "mean": _integer_mean(workflow_wct),
                "p95": _nearest_rank(workflow_wct, 95),
                "max": max(workflow_wct),
                "by_workflow_id": workflow_wct_by_id,
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
            "restored_peer_transport_tokens": {
                "local_activation": sum(
                    item.restored_peer_local_tokens for item in completed
                ),
                "d2d": sum(item.restored_peer_d2d_tokens for item in completed),
            },
            "failure_cache_reuse_tokens": {
                "normal_hbm_local": sum(
                    item.recovery_normal_hbm_local_tokens for item in completed
                ),
            },
            "failure_effective_prefix_tokens": {
                "total": sum(
                    item.recovery_normal_hbm_local_tokens
                    + item.restored_peer_tokens
                    + item.restored_store_tokens
                    for item in completed
                ),
            },
            "recompute_tokens_after_failure": sum(item.recompute_tokens for item in completed),
            "cache_reuse_tokens": {
                "normal_hbm": sum(item.reused_primary_tokens for item in completed),
                "peer_hbm": sum(item.reused_peer_tokens for item in completed),
                "store_dram": sum(item.reused_store_tokens for item in completed),
            },
            "recovery_latency_ns": {
                "count": len(recovery_latencies),
                "mean": _integer_mean(recovery_latencies),
                "p95": _nearest_rank(recovery_latencies, 95),
            },
            "gpu_capacity_recovery": {
                "fixed_time_ns": (
                    None
                    if self.failure_schedule is None
                    else self.failure_schedule.events[0].gpu_recovery_time_ns
                ),
                "scheduled_count": (
                    0
                    if self.failure_schedule is None
                    else sum(
                        event.gpu_recovery_time_ns is not None
                        for event in self.failure_schedule.events
                    )
                ),
                "completed_count": len(self._repair_event_executed),
            },
            "failure_impact": {
                "failure_event_count": len(self.failure_events),
                "active_requests": failure_active,
                "queued_requests": failure_queued,
                "failed_gpu_count": len(self.failed_gpu_ids),
            },
            "resource_cost": {
                "normal_hbm_byte_ns": sum(
                    pool.byte_ns for pool in self.primary_pools.values()
                ),
                "normal_hbm_by_gpu": normal_hbm_by_gpu,
                "peer_hbm_peak_bytes": peer_peak_bytes,
                "peer_hbm_byte_ns": sum(
                    pool.byte_ns for pool in self.peer_pools.values()
                ),
                "store_dram_peak_bytes": store_peak_bytes,
                "store_dram_byte_ns": sum(
                    pool.byte_ns for pool in self.store_pools.values()
                ),
                "peer_hbm_by_gpu": peer_by_gpu,
                "gpu_hbm_account_stack_by_gpu": hbm_by_gpu,
                "gpu_hbm_recovery_reserve_peak_bytes": max(
                    item["peak_account_bytes"][HBM_RECOVERY_RESERVED_ACCOUNT]
                    for item in hbm_by_gpu.values()
                ),
                "gpu_hbm_foreground_store_reserve_peak_bytes": max(
                    item["peak_account_bytes"][HBM_FOREGROUND_STORE_RESERVED_ACCOUNT]
                    for item in hbm_by_gpu.values()
                ),
                "gpu_hbm_foreground_store_reserve_final_bytes": sum(
                    item["final_accounts"][HBM_FOREGROUND_STORE_RESERVED_ACCOUNT]
                    for item in hbm_by_gpu.values()
                ),
                "gpu_hbm_staging_peak_bytes": max(
                    item["peak_account_bytes"][HBM_TRANSFER_STAGING_ACCOUNT]
                    for item in hbm_by_gpu.values()
                ),
                "host_dram_staging_by_gpu": host_dram_by_gpu,
                "host_dram_staging_peak_bytes": max(
                    item["peak_account_bytes"][HOST_TRANSFER_STAGING_ACCOUNT]
                    for item in host_dram_by_gpu.values()
                ),
                "host_staging_acquire_count": self.host_staging_acquire_count,
                "source_pin_acquire_count": self.source_pin_acquire_count,
                "source_pin_count_final": len(self.active_source_pins),
                "store_dram_by_segment": store_by_segment,
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
                "slack_signal_source": (
                    "IDEAL_TRACE_AGENT_DURATION_EXACT_DAG_CPM"
                    if self.profile.slack_weight > 0
                    else "DISABLED"
                ),
                "slack_signal_observation": (
                    "CAUSAL_REQUEST_OR_TOOL_RETURN_RESIDUAL_DAG"
                ),
                "slack_runtime_decay": (
                    "MAX_ZERO_PUBLISHED_RESIDUAL_SLACK_MINUS_GLOBAL_DES_ELAPSED"
                ),
                "slack_update_count": len(self.slack_update_events),
                "slack_update_algorithm": "residual_ideal_trace_exact_dag_cpm_v1",
                "protection_score_evaluation": (
                    "CHUNK_SEAL_PUT_START_WITH_CURRENT_POOL_RENT"
                ),
                "algorithm1": self.algorithm1_cpm.provenance(),
                "recovery_value_enabled": self.profile.recovery_weight > 0,
                "reuse_value_enabled": self.profile.reuse_weight > 0,
                "committed_reuse_visibility": {
                    "normal_hbm": True,
                    "peer_hbm": self._reuse_visible("PEER_HBM"),
                    "store_dram": self._reuse_visible("STORE_DRAM"),
                },
                "manager_mode": (
                    "CURRENT_DESIGN_TIER_LOCAL_RECOVERY_HARM_ONLY"
                    if self._formal_policy_enabled()
                    else "UNIFIED_ADDITIVE_REUSE_RECOVERY_VALUE"
                    if self.profile.unified_manager
                    else "TWO_INDEPENDENT_VALUE_BIDS_SHARED_DIRECTORY"
                ),
                "landlord_runtime": (
                    "FORMAL_SLACK_LANDLORD_CURRENT_DESIGN"
                    if self._formal_policy_enabled()
                    else "MODELED_POOL_BASELINE_POLICY"
                ),
                "formal_suffix_frontier_modeled": self._formal_policy_enabled(),
                "formal_joint_gain_loss_gate_modeled": (
                    self._formal_policy_enabled()
                ),
                "formal_joint_loss_interpretation": (
                    "RECOMPUTE_ONCE_PER_AFFECTED_REQUEST_FROM_TENTATIVE_VICTIM_SET"
                    if self._formal_policy_enabled()
                    else "NOT_APPLICABLE"
                ),
                "formal_algorithm2_event_count": len(self.formal_policy_events),
                "aimd_enabled": self.profile.aimd_enabled,
                "aimd_update_basis": (
                    "IMMEDIATE_PRESSURE_EVENT_AND_FIXED_STABLE_CONTROL_WINDOW"
                ),
                "aimd_quota_lifecycle_uses_formal_safe_tails": (
                    self._formal_policy_enabled()
                ),
                "aimd_pressure_signal": (
                    "PRIMARY_HEADROOM_SHORTFALL_OR_"
                    "ALLOCATION_RECLAIM_STALL_BEFORE_RECLAIM"
                ),
                "hbm_pressure_observation_count": len(self.hbm_pressure_observations),
                "aimd_control_window_ns": self.aimd_control_window_ns,
                "aimd_control_window_derivation": (
                    "max(1s,median_ideal_workflow_cpm_makespan)"
                ),
                "aimd_decision_count": len(self.aimd_events),
                "aimd_action_counts": dict(
                    sorted(Counter(str(item["action"]) for item in self.aimd_events).items())
                ),
                "cache_aware_routing_enabled": self.profile.cache_aware_routing,
                "cache_aware_route_evaluations": self.cache_aware_route_evaluations,
                "cache_aware_route_changes": self.cache_aware_route_changes,
                "anti_colocation_enabled": self.profile.anti_colocation,
                "compute_scheduler_model": (
                    "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP"
                    if self.continuous_batch_enabled
                    else "ONE_NONPREEMPTIVE_REQUEST_LANE_PER_GPU"
                ),
                "continuous_batch_residency_modeled": (
                    self.continuous_batch_enabled
                ),
                "continuous_batch_duration_evidence": (
                    "OBSERVED_IDEAL_TRACE_TOKEN_SHARE_UNCALIBRATED_MODEL"
                    if self.continuous_batch_enabled
                    else "NOT_WIRED"
                ),
                "continuous_local_hbm_reuse_mode": (
                    "READ_ONLY_SHARED_PREFIX_ALIAS_WITH_"
                    "CONSERVATIVE_PER_REQUEST_ACTIVE_CAPACITY_CHARGE"
                    if self.continuous_batch_enabled
                    else "NOT_WIRED"
                ),
                "continuous_local_hbm_alias_capacity_is_conservative": (
                    self.continuous_batch_enabled
                ),
                "workflow_concurrency_semantics": (
                    "CLOSED_LOOP_WORKFLOW_ADMISSION_AND_QUEUE_DEPTH"
                ),
                "protection_path_bypasses": dict(
                    sorted(self.protection_path_bypasses.items())
                ),
                "protection_path_alias_noops": dict(
                    sorted(self.protection_path_alias_noops.items())
                ),
            },
            "pool_audit": {
                "normal_hbm": {
                    "final_bytes": sum(
                        pool.occupied_bytes for pool in self.primary_pools.values()
                    ),
                    "evicted_chunks": sum(
                        pool.evicted_chunks for pool in self.primary_pools.values()
                    ),
                    "alias_hits": sum(
                        pool.alias_hits for pool in self.primary_pools.values()
                    ),
                    "pinned_entry_count_final": sum(
                        pool.pinned_entry_count for pool in self.primary_pools.values()
                    ),
                    "pinned_reference_count_final": sum(
                        pool.pinned_reference_count
                        for pool in self.primary_pools.values()
                    ),
                    "per_gpu": normal_hbm_by_gpu,
                    "valid": all(
                        bool(item["valid"]) for item in normal_hbm_by_gpu.values()
                    ),
                },
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
                    "capacity_bytes": sum(
                        pool.capacity_bytes for pool in self.store_pools.values()
                    ),
                    "final_bytes": sum(
                        pool.occupied_bytes for pool in self.store_pools.values()
                    ),
                    "evicted_chunks": sum(
                        pool.evicted_chunks for pool in self.store_pools.values()
                    ),
                    "bypassed_chunks": sum(
                        pool.bypassed_chunks for pool in self.store_pools.values()
                    ),
                    "dual_role_alias_no_double_charge_count": sum(
                        pool.alias_hits for pool in self.store_pools.values()
                    ),
                    "pending_peak_bytes": sum(
                        pool.pending_peak_bytes for pool in self.store_pools.values()
                    ),
                    "pinned_entry_count_final": sum(
                        pool.pinned_entry_count for pool in self.store_pools.values()
                    ),
                    "pinned_reference_count_final": sum(
                        pool.pinned_reference_count
                        for pool in self.store_pools.values()
                    ),
                    "per_segment": store_by_segment,
                    "valid": all(
                        bool(item["valid"]) for item in store_by_segment.values()
                    ),
                },
                "pending_destination_bytes_final": sum(
                    pool.pending_bytes
                    for pool in (
                        *self.primary_pools.values(),
                        *self.peer_pools.values(),
                        *self.store_pools.values(),
                    )
                ),
                "unattributed_reserve_bytes": sum(
                    pool.pending_bytes
                    for pool in (
                        *self.primary_pools.values(),
                        *self.peer_pools.values(),
                        *self.store_pools.values(),
                    )
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
            "model_deployment": qwen3_8b_dp_deployment(self.parameters.dp_count),
            "workflow_admission": {
                "mode": (
                    "observed_open_loop"
                    if self.workflow_concurrency is None
                    else "closed_loop_workflow_concurrency"
                ),
                "workflow_concurrency": self.workflow_concurrency,
            },
            "resource_model": {
                "normal_hbm_resources": list(sorted(self.primary_pools)),
                "peer_hbm_resources": list(sorted(self.peer_pools)),
                "store_dram_segments": list(self.store_segment_ids),
                "store_node_count": self.parameters.store_node_count,
                "host_dram_staging_resources": [
                    ledger.resource_id
                    for _, ledger in sorted(self.host_staging_ledgers.items())
                ],
                "store_transport": self.parameters.store_transport.value,
                "host_staging_capacity_transactions": True,
                "source_pin_overlay_without_double_charge": True,
                "communication_backend": "flow_contention",
                "fairness": "weighted_max_min_work_conserving",
                "flow_clock": "shared_global_des_now_ns",
                "foreground_store_restore_model": (
                    "destination_reserved_store_to_gpu_flow_with_shared_contention"
                ),
                "foreground_store_restore_account": (
                    HBM_FOREGROUND_STORE_RESERVED_ACCOUNT
                ),
                "slice_size_policy_chunks": FLOW_SLICE_POLICY_CHUNKS,
                "copy_engines": [
                    f"{gpu_id}.hbm-rate" for gpu_id in self.gpu_ids
                ],
                "fabric_resources": [
                    "peer-fabric-rate",
                    *sorted(
                        {
                            rate_ids[fabric_kind]
                            for rate_ids in self.store_rate_ids.values()
                            for fabric_kind in ("rdma_fabric", "tcp_fabric")
                        }
                    ),
                ],
                "rate_resources": {
                    resource_id: resource.capacity_bytes_per_second
                    for resource_id, resource in sorted(
                        self.transfer_rate_resources.items()
                    )
                },
                "gpu_sku": GPU_SKU,
                "topology": TOPOLOGY,
                "node_count": 1,
                "gpu_node_id": INFERENCE_NODE_ID,
                "gpu_hbm_capacity_bytes_per_gpu": (
                    self.parameters.physical_hbm_bytes_per_gpu
                ),
                "gpu_hbm_account_stack": sorted(
                    next(iter(self.hbm_ledgers.values())).accounts
                ),
                "gpu_hbm_event_boundary_snapshots": True,
                "cache_index": {
                    "owner": "simulated_mooncake_conductor",
                    "event_sources": [
                        "normal_inference_hbm",
                        "aegiskv_peer_protection_hbm",
                    ],
                    "query_scope": "per_dp_rank",
                    "prefix_rule": "first_missing_complete_policy_chunk",
                    "cross_role_token_coverage_deduplication": True,
                },
                "per_gpu_peer_hbm_quota_enforced": True,
                "failed_gpu_hbm_becomes_unavailable_not_free": True,
            },
            "recovery_model": {
                "committed_replica_only": True,
                "continuous_prefix_only": True,
                "in_flight_protection_estimate_used": False,
                "missing_suffix_recomputed": True,
                "ready_recovery_order": "IDEAL_CPM_REMAINING_SLACK_DUE_TIME",
                "scheduler_extension": "RECOVERY_OVER_UNSTARTED_NORMAL_COMPUTE",
                "compute_preemption": False,
                "transfer_priority_changed": False,
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
                "source_hash_scopes": sorted(
                    {
                        str(record.get("hash_id_scope", "within_workflow_only"))
                        for record in self.records
                    }
                ),
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
            "ideal_cpm_slack_ns": self.algorithm1_cpm.timing(
                execution.metadata.span_id
            ).slack_ns,
            "ideal_cpm_critical": self.algorithm1_cpm.timing(
                execution.metadata.span_id
            ).critical,
            "residual_cpm_slack_ns": (
                int(published.slack_at_observation_ns)
                if (published := self._published_slack.get(execution.metadata.span_id))
                is not None
                else None
            ),
            "residual_cpm_observed_at_ns": (
                published.observed_at_ns
                if published is not None
                else None
            ),
            "residual_cpm_version": (
                published.version if published is not None else None
            ),
            "reused_primary_tokens": execution.reused_primary_tokens,
            "reused_peer_tokens": execution.reused_peer_tokens,
            "reused_store_tokens": execution.reused_store_tokens,
            "recovery_normal_hbm_local_tokens": (
                execution.recovery_normal_hbm_local_tokens
            ),
            "restored_peer_tokens": execution.restored_peer_tokens,
            "restored_peer_local_tokens": execution.restored_peer_local_tokens,
            "restored_peer_d2d_tokens": execution.restored_peer_d2d_tokens,
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

    def _store_node_id(self) -> str | None:
        if self.parameters.store_node_count == 1:
            return INFERENCE_NODE_ID
        return None


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
        workflow_concurrency=spec.workflow_concurrency,
        oracle_fast_path=spec.oracle_fast_path,
    )
    return runtime.run()


def _failure_oracle_profile_fingerprint(profile: SystemProfile) -> str:
    """Return a stable identity for the exact policy exercised by an oracle."""

    return sha256_json(
        {
            "system_id": profile.system_id.value,
            "label": profile.label,
            "peer_replication_fraction": _fraction_dict(
                profile.peer_replication_fraction
            ),
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
        }
    )


def derive_failure_schedules(
    records: Sequence[Mapping[str, Any]],
    *,
    buckets: Sequence[str],
    seed: int,
    parameters: ModelParameters = DEFAULT_PARAMETERS,
    workflow_concurrency: int | None = None,
    failure_count: int = 2,
    compared_profiles: Sequence[SystemProfile] | None = None,
    enforce_all_events_in_bucket: bool = False,
) -> dict[str, FailureSchedule]:
    """Freeze an ordered multi-failure plan for one workload run per bucket.

    Absolute virtual timestamps are outcomes: cache reuse and policy change when
    the same span starts.  Freezing an absolute timestamp therefore either hits
    different requests or has no common active interval.  The matched input is
    instead the trace span and within-compute progress.  Event ``i`` targets workload
    completion fraction ``(i + 1) / (failure_count + 1)``.  Event zero is selected
    from an F0 no-failure oracle; event ``i`` is selected from a fresh partial-Fi
    oracle that executes every already-selected event.  A candidate must remain
    unaffected by those prior failures and its trigger must be strictly later than
    the last executed failure in every compared profile.  Thus deriving F8 executes
    F0 through F7 once per profile.  Physical routing after earlier failures is
    resolved only when the focus span actually starts compute in the oracle or
    measured cell; ``target_gpu_id`` and ``reference_at_ns`` are provenance only.
    """

    canonical_buckets = tuple(dict.fromkeys(buckets))
    valid_buckets = {item.name for item in CONTEXT_BUCKETS}
    if not canonical_buckets or any(item not in valid_buckets for item in canonical_buckets):
        raise ValueError("failure schedule buckets must be non-empty and known")
    progress_targets = failure_workload_progress_targets_per_mille(failure_count)

    canonical_profiles = tuple(
        dict.fromkeys(
            compared_profiles
            if compared_profiles is not None
            else (
                variant.profile
                for variant in (*core_variants(parameters), *ablation_variants(parameters))
            )
        )
    )
    if not canonical_profiles:
        raise ValueError("failure schedule comparison profiles must be non-empty")
    schedules: dict[str, FailureSchedule] = {}
    for bucket in canonical_buckets:
        selected_events: list[FailureEventSchedule] = []
        for event_index, target_progress in enumerate(progress_targets):
            partial_schedule = (
                None
                if not selected_events
                else FailureSchedule(
                    tuple(selected_events),
                    selection_scope=(
                        "causal_partial_failure_oracle_runtime_resolved_gpu"
                    ),
                )
            )
            scenario = (
                Scenario.NO_FAILURE
                if partial_schedule is None
                else Scenario.GPU_FAILURE
            )
            causal_oracles_list: list[StudyRunResult] = []
            for profile_index, profile in enumerate(canonical_profiles):
                profile_fingerprint = _failure_oracle_profile_fingerprint(profile)
                try:
                    result = run_study_cell(
                        records,
                        CellSpec(
                            variant=ExperimentVariant(
                                suite="failure_schedule_oracle",
                                variant_id=f"profile-{profile_index}",
                                profile=profile,
                                parameters=parameters,
                            ),
                            context_bucket=bucket,
                            scenario=scenario,
                            seed=seed,
                            repetition="A",
                            failure_schedule=partial_schedule,
                            workflow_concurrency=workflow_concurrency,
                            oracle_fast_path=True,
                        ),
                    )
                except Exception as error:
                    raise ExperimentError(
                        "failure schedule oracle failed "
                        f"(bucket={bucket}, seed={seed}, "
                        f"workflow_concurrency={workflow_concurrency}, "
                        f"event_index={event_index}, profile_index={profile_index}, "
                        f"system_id={profile.system_id.value}, "
                        f"eviction={profile.eviction.value}, "
                        f"profile_fingerprint={profile_fingerprint}, "
                        f"scenario={scenario.value}): {error}"
                    ) from error
                causal_oracles_list.append(result)
            causal_oracles = tuple(causal_oracles_list)
            details_by_oracle = tuple(
                {str(item["span_id"]): item for item in result.span_details}
                for result in causal_oracles
            )
            workflow_ends_by_oracle = tuple(
                _workflow_end_times(details.values()) for details in details_by_oracle
            )
            prior_failure_times: list[int] = []
            prior_impacted_span_ids: list[set[str]] = []
            for result in causal_oracles:
                raw_failure_events = result.representative.get("failure_events")
                if not isinstance(raw_failure_events, Sequence) or isinstance(
                    raw_failure_events, (str, bytes)
                ):
                    raise ExperimentError(
                        "failure oracle omitted its executed failure-event evidence"
                    )
                failure_events = tuple(raw_failure_events)
                if len(failure_events) != event_index:
                    raise ExperimentError(
                        "causal failure oracle did not execute every prior event"
                    )
                impacted: set[str] = set()
                latest_failure_ns = -1
                for planned, actual in zip(
                    selected_events, failure_events, strict=True
                ):
                    if not isinstance(actual, Mapping):
                        raise ExperimentError("failure oracle event evidence is malformed")
                    logical_trigger = actual.get("logical_trigger")
                    if (
                        actual.get("failure_id") != planned.failure_id
                        or not isinstance(logical_trigger, Mapping)
                        or logical_trigger.get("focus_span_id") != planned.focus_span_id
                    ):
                        raise ExperimentError(
                            "causal failure oracle diverged from the logical partial plan"
                        )
                    failure_ns = actual.get("timestamp_ns")
                    if type(failure_ns) is not int or failure_ns <= latest_failure_ns:
                        raise ExperimentError(
                            "causal failure oracle timestamps are not strictly ordered"
                        )
                    latest_failure_ns = failure_ns
                    for field_name in (
                        "impacted_active_span_ids",
                        "impacted_queued_span_ids",
                    ):
                        raw_ids = actual.get(field_name)
                        if not isinstance(raw_ids, Sequence) or isinstance(
                            raw_ids, (str, bytes)
                        ):
                            raise ExperimentError(
                                "failure oracle omitted impacted-span evidence"
                            )
                        if not all(isinstance(span_id, str) for span_id in raw_ids):
                            raise ExperimentError(
                                "failure oracle impacted-span evidence is malformed"
                            )
                        impacted.update(cast(Sequence[str], raw_ids))
                prior_failure_times.append(latest_failure_ns)
                prior_impacted_span_ids.append(impacted)
            ranked: list[
                tuple[
                    tuple[int, int, str],
                    Mapping[str, Any],
                    tuple[int, ...],
                    tuple[int, ...],
                ]
            ] = []
            rejection_counts: Counter[str] = Counter()
            selected_focus_ids = {event.focus_span_id for event in selected_events}
            for item in causal_oracles[0].span_details:
                span_id = str(item["span_id"])
                if (
                    (
                        (enforce_all_events_in_bucket or event_index == 0)
                        and item["context_bucket"] != bucket
                    )
                    or span_id in selected_focus_ids
                ):
                    rejection_counts["bucket_or_reused_focus"] += 1
                    continue
                if any(span_id not in details for details in details_by_oracle):
                    rejection_counts["missing_profile_span"] += 1
                    continue
                per_oracle = tuple(details[span_id] for details in details_by_oracle)
                if any(
                    span_id in impacted or detail.get("failure_at_ns") is not None
                    for detail, impacted in zip(
                        per_oracle,
                        prior_impacted_span_ids,
                        strict=True,
                    )
                ):
                    rejection_counts["affected_by_prior_failure"] += 1
                    continue
                gpu_ids = tuple(detail.get("gpu_id") for detail in per_oracle)
                if not all(isinstance(gpu_id, str) for gpu_id in gpu_ids):
                    rejection_counts["malformed_reference_route"] += 1
                    continue
                starts = tuple(detail.get("compute_start_ns") for detail in per_oracle)
                ends = tuple(detail.get("completed_ns") for detail in per_oracle)
                if not all(type(value) is int for value in (*starts, *ends)):
                    rejection_counts["malformed_interval"] += 1
                    continue
                canonical_starts = cast(tuple[int, ...], starts)
                canonical_ends = cast(tuple[int, ...], ends)
                trigger_times = tuple(
                    start
                    + (end - start) * parameters.failure_progress_per_mille // 1_000
                    for start, end in zip(
                        canonical_starts,
                        canonical_ends,
                        strict=True,
                    )
                )
                if any(
                    end <= start
                    or trigger_at <= prior_failure_at
                    for start, end, trigger_at, prior_failure_at in zip(
                        canonical_starts,
                        canonical_ends,
                        trigger_times,
                        prior_failure_times,
                        strict=True,
                    )
                ):
                    rejection_counts["non_monotonic_reference_trigger"] += 1
                    continue
                progresses = tuple(
                    _completed_workflow_progress_per_mille(workflow_ends, start)
                    for workflow_ends, start in zip(
                        workflow_ends_by_oracle,
                        canonical_starts,
                        strict=True,
                    )
                )
                distances = tuple(abs(value - target_progress) for value in progresses)
                ranked.append(
                    (
                        (
                            max(distances),
                            sum(distances),
                            hashlib.sha256(f"{seed}:{span_id}".encode()).hexdigest(),
                        ),
                        item,
                        progresses,
                        trigger_times,
                    )
                )
            if not ranked:
                raise ExperimentError(
                    f"failure oracle has no causally safe logical span for event "
                    f"{event_index} in bucket {bucket} seed {seed}; "
                    f"rejections={dict(sorted(rejection_counts.items()))}"
                )
            _, focus, progresses, trigger_times = min(
                ranked, key=lambda candidate: candidate[0]
            )
            focus_id = str(focus["span_id"])
            reference_focus = details_by_oracle[0][focus_id]
            gpu_id = reference_focus.get("gpu_id")
            start_ns = reference_focus.get("compute_start_ns")
            end_ns = reference_focus.get("completed_ns")
            if (
                not isinstance(gpu_id, str)
                or type(start_ns) is not int
                or type(end_ns) is not int
                or end_ns <= start_ns
            ):
                raise ExperimentError("failure oracle focus interval is malformed")
            workflow_ends = workflow_ends_by_oracle[0]
            selected_events.append(
                FailureEventSchedule(
                    failure_id=f"gpu-failure:{bucket}:seed-{seed}:event-{event_index}",
                    event_index=event_index,
                    bucket=bucket,
                    seed=seed,
                    focus_span_id=focus_id,
                    target_gpu_id=gpu_id,
                    reference_at_ns=start_ns
                    + (
                        (end_ns - start_ns)
                        * parameters.failure_progress_per_mille
                        // 1_000
                    ),
                    target_workload_progress_per_mille=target_progress,
                    reference_completed_workflow_count=sum(
                        completed_ns <= start_ns
                        for completed_ns in workflow_ends.values()
                    ),
                    reference_workflow_count=len(workflow_ends),
                    detection_delay_ns=parameters.failure_detection_ns,
                    trigger_progress_per_mille=parameters.failure_progress_per_mille,
                    gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
                    selection_scope=(
                        "strict_logical_focus_progress_and_context_bucket_"
                        "runtime_resolved_gpu"
                        if enforce_all_events_in_bucket
                        else "shared_logical_focus_at_workload_target_runtime_resolved_gpu"
                    ),
                )
            )
        schedules[bucket] = FailureSchedule(
            tuple(selected_events),
            selection_scope=(
                "causal_recursive_strict_logical_context_severity_runtime_resolved_gpu"
                if enforce_all_events_in_bucket
                else "causal_recursive_logical_failures_runtime_resolved_gpu"
            ),
        )
    return schedules


def derive_failure_schedule(
    records: Sequence[Mapping[str, Any]],
    *,
    bucket: str,
    seed: int,
    parameters: ModelParameters = DEFAULT_PARAMETERS,
    workflow_concurrency: int | None = None,
    failure_count: int = 2,
    compared_profiles: Sequence[SystemProfile] | None = None,
    enforce_all_events_in_bucket: bool = False,
) -> FailureSchedule:
    """Derive and cache one ordered failure plan for a bucket and profile set."""

    key = (
        sha256_json(records),
        sha256_json(parameters.to_dict()),
        bucket,
        seed,
        workflow_concurrency,
        failure_count,
        None if compared_profiles is None else tuple(compared_profiles),
        enforce_all_events_in_bucket,
    )
    schedules = _FAILURE_SCHEDULE_CACHE.get(key)
    if schedules is None:
        schedules = derive_failure_schedules(
            records,
            buckets=(bucket,),
            seed=seed,
            parameters=parameters,
            workflow_concurrency=workflow_concurrency,
            failure_count=failure_count,
            compared_profiles=compared_profiles,
            enforce_all_events_in_bucket=enforce_all_events_in_bucket,
        )
        _FAILURE_SCHEDULE_CACHE[key] = schedules
    try:
        return schedules[bucket]
    except KeyError as error:
        raise ValueError(f"unknown failure schedule bucket: {bucket}") from error


def project_failure_schedule_to_profile(
    records: Sequence[Mapping[str, Any]],
    *,
    reference: FailureSchedule,
    profile: SystemProfile,
    parameters: ModelParameters = DEFAULT_PARAMETERS,
    workflow_concurrency: int | None = None,
    seed: int,
) -> FailureSchedule:
    """Copy logical interventions without predicting profile-local routes.

    The retained reference GPU and timestamp are provenance.  The measured
    runtime resolves each event from its focus span's actual compute route, so
    projection performs no no-failure or recursive partial-failure oracle run.
    ``records``, ``profile``, and ``workflow_concurrency`` remain in the public
    signature for runner compatibility.
    """

    if not reference.events:
        raise ValueError("reference failure schedule must be non-empty")
    bucket = reference.events[0].bucket
    if any(event.bucket != bucket or event.seed != seed for event in reference.events):
        raise ValueError("reference failure schedule bucket or seed diverged")
    if any(
        event.detection_delay_ns != parameters.failure_detection_ns
        or event.trigger_progress_per_mille != parameters.failure_progress_per_mille
        or event.gpu_recovery_time_ns != parameters.gpu_recovery_time_ns
        for event in reference.events
    ):
        raise ValueError("reference failure schedule parameters diverged")
    _ = records, profile, workflow_concurrency
    selected = tuple(
        replace(
            event,
            selection_scope="shared_logical_focus_runtime_resolved_physical_gpu",
        )
        for event in reference.events
    )
    return FailureSchedule(
        selected,
        selection_scope="shared_logical_focus_runtime_resolved_physical_gpu",
    )


def _workflow_end_times(
    details: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for detail in details:
        workflow_id = _required_str(detail, "workflow_id")
        completed_ns = _required_int(detail, "completed_ns")
        result[workflow_id] = max(result.get(workflow_id, completed_ns), completed_ns)
    if not result:
        raise ExperimentError("failure oracle has no completed workflows")
    return result


def failure_workload_progress_targets_per_mille(
    failure_count: int,
) -> tuple[int, ...]:
    """Evenly space N failure events strictly inside one workload run."""

    if type(failure_count) is not int or failure_count <= 0:
        raise ValueError("failure_count must be a positive integer")
    denominator = failure_count + 1
    return tuple(
        (1_000 * event_number + denominator // 2) // denominator
        for event_number in range(1, failure_count + 1)
    )


def _completed_workflow_progress_per_mille(
    workflow_ends: Mapping[str, int],
    timestamp_ns: int,
) -> int:
    return (
        sum(completed_ns <= timestamp_ns for completed_ns in workflow_ends.values())
        * 1_000
        // len(workflow_ends)
    )


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
            replace(
                full,
                peer_replication_fraction=Fraction(1, 2),
                aimd_enabled=False,
            ),
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
        ("peer_hbm_alpha_percent", (0, 20, 50)),
        ("store_budget_gib", (32, 64, 128)),
        ("store_bandwidth_gbps", (12, 25, 50)),
        ("peer_fabric_bandwidth_gbps", (50, 100, 200)),
        ("failure_progress_percent", (10, 50, 90)),
        ("reroute_delay_ms", (0, 1, 5)),
        ("policy_chunk_tokens", (256, 1_024, 4_096)),
    )
    for dimension, values in dimensions:
        for value in values:
            updated = parameters
            if dimension == "peer_hbm_alpha_percent":
                updated = replace(parameters, peer_hbm_alpha=Decimal(value) / 100)
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
            elif dimension == "failure_progress_percent":
                updated = replace(parameters, failure_progress_per_mille=value * 10)
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


def transport_sensitivity_variants(
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> tuple[ExperimentVariant, ...]:
    """Return an isolated Store-path sweep without changing the v1 catalog."""

    full = SYSTEM_PROFILES[SystemId.AEGIS_UNIFIED]
    return tuple(
        ExperimentVariant(
            suite="transport_sensitivity",
            variant_id=f"store_transport={transport.value}",
            profile=full,
            parameters=replace(parameters, store_transport=transport),
            interpretation=(
                "modeled_store_transport_path_sensitivity_not_physical_bandwidth"
            ),
        )
        for transport in (
            TransportKind.RDMA_GDR,
            TransportKind.RDMA_HOST_STAGED,
            TransportKind.TCP_HOST_STAGED,
        )
    )


def store_node_sensitivity_variants(
    parameters: ModelParameters = DEFAULT_PARAMETERS,
) -> tuple[ExperimentVariant, ...]:
    """Hold total Store capacity fixed while varying physical Store nodes."""

    full = SYSTEM_PROFILES[SystemId.AEGIS_UNIFIED]
    return tuple(
        ExperimentVariant(
            suite="store_node_sensitivity",
            variant_id=f"store_node_count={node_count}",
            profile=full,
            parameters=replace(
                parameters,
                store_node_count=node_count,
                store_transport=TransportKind.RDMA_GDR,
            ),
            interpretation=(
                "modeled_store_node_count_with_fixed_total_store_capacity"
            ),
        )
        for node_count in (1, 2, 4)
    )


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
    raw_counts = record.get("source_hash_block_token_counts")
    if raw_counts is None:
        block_token_counts = [SOURCE_BLOCK_TOKENS] * len(raw_hashes)
    elif (
        isinstance(raw_counts, list)
        and len(raw_counts) == len(raw_hashes)
        and all(type(item) is int and 0 < item <= SOURCE_BLOCK_TOKENS for item in raw_counts)
    ):
        block_token_counts = list(raw_counts)
    else:
        raise ExperimentError("source hash block token counts are malformed")
    raw_scopes = record.get("source_hash_block_scopes")
    if raw_scopes is None:
        block_scopes = ["within_workflow"] * len(raw_hashes)
    elif (
        isinstance(raw_scopes, list)
        and len(raw_scopes) == len(raw_hashes)
        and all(
            item in {"global_system_template", "within_workflow"}
            for item in raw_scopes
        )
    ):
        block_scopes = list(raw_scopes)
    else:
        raise ExperimentError("source hash block scopes are malformed")
    blocks_per_chunk = parameters.policy_chunk_tokens // SOURCE_BLOCK_TOKENS
    result: list[_Chunk] = []
    workflow_id = str(record["workflow_id"])
    token_start = 0
    block_start = 0
    while block_start < len(raw_hashes):
        scope = block_scopes[block_start]
        block_end = min(len(raw_hashes), block_start + blocks_per_chunk)
        for index in range(block_start + 1, block_end):
            if block_scopes[index] != scope:
                block_end = index
                break
        hash_ids = raw_hashes[block_start:block_end]
        token_counts = block_token_counts[block_start:block_end]
        token_count = sum(token_counts)
        global_chunk = scope == "global_system_template"
        key = sha256_json(
            {
                "schema": "moonkvsim.aegiskv.policy_chunk.v2",
                "workflow_id": None if global_chunk else workflow_id,
                "source_block_start": block_start,
                "source_hash_ids": hash_ids,
                "source_hash_block_token_counts": token_counts,
                "source_hash_scope": (
                    "global_system_template" if global_chunk else "within_workflow"
                ),
            }
        )
        result.append(
            _Chunk(
                key=key,
                workflow_id=workflow_id,
                token_start=token_start,
                token_count=token_count,
                # HBM and protection transports move allocated KV source
                # blocks, including the unused tail of a partial final block.
                bytes=len(token_counts) * KV_BYTES_PER_SOURCE_BLOCK,
                global_system_template=global_chunk,
            )
        )
        token_start += token_count
        block_start = block_end
    return tuple(result)


def _duration_after_prefix_reuse(
    metadata: NormalizedSpanMetadata, base_duration_ns: int, reused_tokens: int
) -> int:
    prompt = metadata.prompt_tokens
    output_weighted = metadata.output_tokens * 8
    weighted_total = max(1, prompt + output_weighted)
    remaining = max(1, prompt - reused_tokens + output_weighted)
    return max(1, base_duration_ns * remaining // weighted_total)


def _recovery_source_intervals(
    prompt_tokens: int,
    *,
    normal_prefix_tokens: int,
    peer_prefix_tokens: int,
    store_prefix_tokens: int,
) -> tuple[int, int, int, int]:
    """Deduplicate continuous recovery prefixes into disjoint source intervals."""

    if prompt_tokens < 0 or min(
        normal_prefix_tokens,
        peer_prefix_tokens,
        store_prefix_tokens,
    ) < 0:
        raise ExperimentError("recovery prefix token counts cannot be negative")
    normal_end = min(normal_prefix_tokens, prompt_tokens)
    peer_end = min(peer_prefix_tokens, prompt_tokens)
    store_end = min(store_prefix_tokens, prompt_tokens)
    effective_end = max(normal_end, peer_end, store_end)
    normal = normal_end
    peer = max(0, min(peer_end, effective_end) - normal_end)
    store = max(0, effective_end - max(normal_end, peer_end))
    recompute = prompt_tokens - effective_end
    if normal + peer + store + recompute != prompt_tokens:
        raise ExperimentError("recovery source intervals do not conserve prompt tokens")
    return normal, peer, store, recompute


def _prefix_bytes_between(
    chunks: Sequence[_Chunk], start_token: int, end_token: int
) -> int:
    """Return allocated 64-token KV bytes overlapping a prefix interval."""

    if start_token < 0 or end_token < start_token:
        raise ExperimentError("prefix byte interval is invalid")
    if end_token == start_token:
        return 0
    if not chunks or end_token > chunks[-1].token_start + chunks[-1].token_count:
        raise ExperimentError("prefix byte interval exceeds resident source chunks")
    first_source_block = start_token // SOURCE_BLOCK_TOKENS
    source_block_count = (
        (end_token + SOURCE_BLOCK_TOKENS - 1) // SOURCE_BLOCK_TOKENS
        - first_source_block
    )
    return source_block_count * KV_BYTES_PER_SOURCE_BLOCK


def _chunk_interval_boundaries(chunks: Sequence[_Chunk]) -> set[int]:
    boundaries = {0}
    for chunk in chunks:
        boundaries.add(chunk.token_start)
        boundaries.add(chunk.token_start + chunk.token_count)
    return boundaries


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


def _exact_prompt_token_ids(record: Mapping[str, Any]) -> tuple[int, ...] | None:
    raw = record.get("messages_or_token_ids")
    if not isinstance(raw, Mapping) or raw.get("kind") != "token_ids":
        return None
    value = raw.get("value")
    if not isinstance(value, list) or not value or any(type(item) is not int for item in value):
        return None
    return tuple(cast(list[int], value))


def _logical_page_aligned_prefix(tokens: int, *, logical_page_tokens: int) -> int:
    if tokens <= 0:
        return 0
    return tokens // logical_page_tokens * logical_page_tokens


def _source_chunk_page_aligned_prefix(
    chunks: Sequence[_Chunk],
    available_tokens: int,
    *,
    logical_page_tokens: int,
) -> int:
    """Largest resident prefix ending on a scheduler logical-page boundary.

    Policy entries contain whole 64-token source allocations, except that the
    final allocation can have fewer valid tokens.  A scheduler may adopt all
    complete 16-token pages in that final allocation; the unused tail remains
    privately charged to the same physical source block.
    """

    resident_tokens = 0
    for chunk in chunks:
        end = chunk.token_start + chunk.token_count
        if end > available_tokens:
            # A prior page-alignment may end a few valid tokens before the
            # policy tail while still owning the same final 64-token physical
            # allocation.  Preserve that canonical prefix on repeated calls.
            if (
                chunk.token_start < available_tokens
                and (available_tokens + SOURCE_BLOCK_TOKENS - 1)
                // SOURCE_BLOCK_TOKENS
                == (end + SOURCE_BLOCK_TOKENS - 1) // SOURCE_BLOCK_TOKENS
            ):
                resident_tokens = available_tokens
            break
        if chunk.token_start != resident_tokens:
            raise ExperimentError("source chunk sequence is not contiguous")
        resident_tokens = end
    return resident_tokens // logical_page_tokens * logical_page_tokens


def _fraction_count(count: int, fraction: Fraction) -> int:
    """Round a positive fractional unit count upward."""

    if count <= 0 or fraction <= 0:
        return 0
    return min(
        count,
        (count * fraction.numerator + fraction.denominator - 1)
        // fraction.denominator,
    )


def _fraction_prefix_chunk_count(
    chunks: Sequence[_Chunk], fraction: Fraction
) -> int:
    """Cover a token fraction with the smallest complete chunk prefix."""

    if not chunks or fraction <= 0:
        return 0
    total_tokens = sum(chunk.token_count for chunk in chunks)
    target_tokens = _fraction_count(total_tokens, fraction)
    covered_tokens = 0
    for index, chunk in enumerate(chunks):
        covered_tokens += chunk.token_count
        if covered_tokens >= target_tokens:
            return index + 1
    raise ExperimentError("protection token fraction exceeded the chunk prefix")


def _protection_batch_ranges(
    total_chunk_count: int,
    candidate_count: int,
    *,
    global_prefix_chunk_count: int = 0,
) -> tuple[tuple[int, int], ...]:
    """Return one independently admitted policy chunk per sealed range.

    Algorithm 2 evaluates ``A/D/H_y`` and advances its prefix frontier at the
    engine policy-chunk granularity.  Adjacent admitted chunks may later share
    transport service, but combining them before preview would incorrectly let
    one low-value private chunk block all later independently eligible chunks.
    """

    if total_chunk_count < 0 or not 0 <= candidate_count <= total_chunk_count:
        raise ValueError("protection batch counts are inconsistent")
    if not 0 <= global_prefix_chunk_count <= candidate_count:
        raise ValueError("global prefix count is outside the protected prefix")
    if candidate_count == 0:
        return ()
    result = [(index, index + 1) for index in range(candidate_count)]
    if not result or result[0][0] != 0 or result[-1][1] != candidate_count:
        raise ExperimentError("protection batches lost the candidate prefix")
    return tuple(result)


def _protection_transfer_batch_ranges(
    candidate_count: int,
    *,
    global_prefix_candidate_count: int = 0,
) -> tuple[tuple[int, int], ...]:
    """Batch admitted policy units only at the physical transfer layer.

    Global system-template units remain singleton because their content aliases
    can be shared across workflows while a write is still pending.  Adjacent
    request-private candidates share one transfer task in groups of at most
    ``FLOW_SLICE_POLICY_CHUNKS``; each candidate still receives its own formal
    preview, apply, reservation, and commit/abort resolution.
    """

    if candidate_count < 0:
        raise ValueError("candidate count must be non-negative")
    if not 0 <= global_prefix_candidate_count <= candidate_count:
        raise ValueError("global prefix candidate count is outside the prefix")
    result = [
        (index, index + 1) for index in range(global_prefix_candidate_count)
    ]
    begin = global_prefix_candidate_count
    while begin < candidate_count:
        end = min(candidate_count, begin + FLOW_SLICE_POLICY_CHUNKS)
        result.append((begin, end))
        begin = end
    return tuple(result)


def _global_prefix_chunk_count(chunks: Sequence[_Chunk]) -> int:
    count = 0
    for chunk in chunks:
        if not chunk.global_system_template:
            break
        count += 1
    return count


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


def _experiment_gpu_location(gpu_id: str) -> MemoryLocation:
    if not gpu_id.startswith("gpu-"):
        raise ExperimentError("experiment GPU location requires a physical gpu-* ID")
    return MemoryLocation(
        resource_id=f"hbm:{gpu_id}",
        node_id=INFERENCE_NODE_ID,
        numa_node_id=INFERENCE_NUMA_NODE_ID,
        kind=MemoryKind.GPU_HBM,
        endpoint=f"gpu://{gpu_id}",
        gpu_id=gpu_id,
    )


def _experiment_store_location(
    segment_id: str,
    *,
    colocated_node_id: str | None = None,
    transport: TransportKind,
) -> MemoryLocation:
    if not segment_id.startswith("store-") or ":segment-" not in segment_id:
        raise ExperimentError("experiment Store location requires a store segment ID")
    node_id = colocated_node_id or f"node-{segment_id.split(':', 1)[0]}"
    endpoint_scheme = (
        "pcie"
        if transport is TransportKind.PCIE
        else "tcp"
        if transport is TransportKind.TCP_HOST_STAGED
        else "rdma"
    )
    return MemoryLocation(
        resource_id=segment_id,
        node_id=node_id,
        numa_node_id=f"numa:{node_id}:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint=f"{endpoint_scheme}://{segment_id.replace(':', '/')}",
    )


def _capacity_ledger_snapshot(
    ledger: CapacityLedger, *, timestamp_ns: int, cause: str
) -> dict[str, Any]:
    accounts = dict(sorted(ledger.accounts.items()))
    if sum(accounts.values()) != ledger.capacity_bytes:
        raise ExperimentError("capacity ledger snapshot does not conserve")
    return {
        "timestamp_ns": timestamp_ns,
        "resource_id": ledger.resource_id,
        "capacity_bytes": ledger.capacity_bytes,
        "accounts": accounts,
        "cause": cause,
    }


def _summarize_hbm_timeline(
    ledger: CapacityLedger, timeline: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    account_names = tuple(sorted(ledger.accounts))
    peak_account_bytes = {account: 0 for account in account_names}
    previous_timestamp = -1
    valid = bool(timeline)
    for snapshot in timeline:
        timestamp = snapshot.get("timestamp_ns")
        raw_accounts = snapshot.get("accounts")
        if (
            type(timestamp) is not int
            or timestamp < previous_timestamp
            or not isinstance(raw_accounts, Mapping)
            or set(raw_accounts) != set(account_names)
            or any(type(value) is not int or value < 0 for value in raw_accounts.values())
            or sum(cast(int, value) for value in raw_accounts.values())
            != ledger.capacity_bytes
        ):
            valid = False
            continue
        previous_timestamp = timestamp
        for account in account_names:
            peak_account_bytes[account] = max(
                peak_account_bytes[account], cast(int, raw_accounts[account])
            )
    return {
        "resource_id": ledger.resource_id,
        "capacity_bytes": ledger.capacity_bytes,
        "final_accounts": dict(sorted(ledger.accounts.items())),
        "peak_account_bytes": peak_account_bytes,
        "event_boundary_snapshot_count": len(timeline),
        "valid": valid,
    }


def _flow_interval_to_dict(item: FlowRateInterval) -> dict[str, Any]:
    return {
        "start_ns": item.start_ns,
        "end_ns": item.end_ns,
        "flow_id": item.flow_id,
        "transfer_id": item.transfer_id,
        "slice_id": item.slice_id,
        "cause": item.cause,
        "path_resource_ids": list(item.path_resource_ids),
        "payload_bytes": item.payload_bytes,
        "remaining_bytes_at_start": item.remaining_bytes_at_start,
        "allocated_rate_bytes_per_second": item.allocated_rate_bytes_per_second,
        "transferred_bytes": item.transferred_bytes,
        "remaining_bytes_at_end": item.remaining_bytes_at_end,
    }


def _integer_mean(values: Sequence[int]) -> int:
    return 0 if not values else sum(values) // len(values)


def _integer_median(values: Sequence[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered) / 100))
    return ordered[rank - 1]


def _interval_union_duration_ns(intervals: Sequence[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    start_ns, end_ns = ordered[0]
    if start_ns < 0 or end_ns < start_ns:
        raise ExperimentError("resource busy interval is malformed")
    total_ns = 0
    for next_start_ns, next_end_ns in ordered[1:]:
        if next_start_ns < 0 or next_end_ns < next_start_ns:
            raise ExperimentError("resource busy interval is malformed")
        if next_start_ns <= end_ns:
            end_ns = max(end_ns, next_end_ns)
        else:
            total_ns += end_ns - start_ns
            start_ns, end_ns = next_start_ns, next_end_ns
    return total_ns + end_ns - start_ns


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
    resource_busy_intervals: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(
        list
    )
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
            if busy_ns > 0:
                resource_busy_intervals[(cause, resource_id)].append(
                    (interval_start, actual_end)
                )
    for (cause, resource_id), intervals in sorted(resource_busy_intervals.items()):
        busy_ns = _interval_union_duration_ns(intervals)
        if resource_id.endswith(".hbm-rate"):
            copy_busy_ns[cause] += busy_ns
        elif resource_id.endswith("-fabric-rate"):
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
    span_id: str | None = None,
    flow_slice_count: int = 0,
    policy_candidate_count: int = 0,
) -> dict[str, Any]:
    if status not in {"PENDING", "COMMITTED"}:
        raise ValueError("new transfer record must be pending or committed")
    if end_ns < start_ns:
        raise ValueError("transfer end cannot precede start")
    if type(flow_slice_count) is not int or flow_slice_count < 0:
        raise ValueError("flow_slice_count must be a non-negative integer")
    if type(policy_candidate_count) is not int or policy_candidate_count < 0:
        raise ValueError("policy_candidate_count must be a non-negative integer")
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
        "communication_backend": (
            "local_activation" if path == "PEER_HBM_LOCAL_ACTIVATION" else "flow_contention"
        ),
        "flow_slice_count": flow_slice_count,
        "policy_candidate_count": policy_candidate_count,
        "resource_intervals": [],
    }
