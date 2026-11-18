"""Strict Qwen3-32B DP8/TP4 AegisKV engine contract.

The contract is intentionally separate from the Qwen3-8B paper runner.  It
describes rank placement and recovery semantics, but does not bind the current
``experiment.py`` execution path.

KV state is sharded across the four TP ranks.  Recovery therefore means that
each rank loads or activates its own shard, followed by a TP-group readiness
barrier and a directory-generation install.  No mathematical all-reduce is
performed: summing, averaging, or otherwise reducing KV tensors would corrupt
the cache.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

SCHEMA_ID: Final = "moonkvsim.aegiskv.qwen3_32b_tp4_engine.v1"
MODEL_ID: Final = "Qwen/Qwen3-32B"
MODEL_REVISION: Final = "9216db5781bf21249d130ec9da846c4624c16137"
DEFAULT_CONFIG_RELATIVE_PATH: Final = Path(
    "benchmark/AegisKV/experiments/configs/engine/qwen3-32b-dp8-tp4-8node-a100-80gb.json"
)
SCHEMA_RELATIVE_PATH: Final = Path("schemas/aegiskv-qwen3-32b-tp4-engine.schema.json")
MODELED_MODEL_SAFETENSORS_TOTAL_BYTES: Final = 65_524_246_528
MODELED_STORE_DRAM_BYTES_PER_SEGMENT: Final = 1_000_000_000_000


class Qwen3TP4ConfigError(ValueError):
    """The strict Qwen3-32B TP4 contract failed closed."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    model_id: str
    revision: str
    dtype: str
    kv_dtype: str
    native_max_context_tokens: int
    max_context_tokens: int
    context_extension_provenance: str
    num_hidden_layers: int
    num_kv_heads: int
    head_dim: int
    kv_scalar_bytes: int
    kv_bytes_per_token_total: int
    kv_bytes_per_token_per_tp_rank: int
    kv_layout_status: str


@dataclass(frozen=True, slots=True)
class ParallelismConfig:
    data_parallel_size: int
    tensor_parallel_size: int
    pipeline_parallel_size: int
    world_size: int


@dataclass(frozen=True, slots=True)
class ClusterConfig:
    inference_node_count: int
    gpus_per_node: int
    gpu_count: int
    gpu_sku: str
    physical_hbm_bytes_per_gpu: int
    tp_group_placement: str
    intra_node_gpu_fabric: str


@dataclass(frozen=True, slots=True)
class RankHBMCapacityConfig:
    physical_hbm_bytes_per_rank: int
    model_weights_bytes_per_rank: int
    runtime_fixed_bytes_per_rank: int
    kv_capable_hbm_bytes_per_rank: int
    peer_hbm_dynamic_quota_upper_bound_bytes_per_rank: int
    peer_hbm_dynamic_quota_upper_bound_numerator: int
    peer_hbm_dynamic_quota_upper_bound_denominator: int
    peer_hbm_accounting_rule: str


@dataclass(frozen=True, slots=True)
class StoreDRAMSegmentConfig:
    segment_id: str
    node_id: str
    capacity_bytes: int


@dataclass(frozen=True, slots=True)
class StoreDRAMCapacityConfig:
    store_node_count: int
    total_capacity_bytes: int
    failure_domain_rule: str
    segments: tuple[StoreDRAMSegmentConfig, ...]

    @property
    def capacity_bytes_per_segment(self) -> int:
        """Return the uniform per-segment capacity guaranteed by validation."""

        return self.segments[0].capacity_bytes


@dataclass(frozen=True, slots=True)
class CapacityProvenanceConfig:
    physical_hbm_bytes_per_rank: str
    model_weights_bytes_per_rank: str
    runtime_fixed_bytes_per_rank: str
    kv_capable_hbm_bytes_per_rank: str
    peer_hbm_dynamic_quota_upper_bound_bytes_per_rank: str
    store_dram_capacity_bytes_per_segment: str


@dataclass(frozen=True, slots=True)
class CapacityConfig:
    status: str
    rank_hbm: RankHBMCapacityConfig
    store_dram: StoreDRAMCapacityConfig
    provenance: CapacityProvenanceConfig


@dataclass(frozen=True, slots=True)
class PlacementConfig:
    linear_rank_formula: str
    node_formula: str
    local_gpu_formula: str
    peer_target_dp_by_source_dp: tuple[int, ...]
    peer_mapping_rule: str
    peer_failure_domain_rule: str


@dataclass(frozen=True, slots=True)
class ProtectionPathConfig:
    tier: str
    source: str
    ownership: str
    admission: str
    shard_granularity: str
    writes_per_logical_chunk: int
    commit_rule: str
    cross_tier_copy_allowed: bool


@dataclass(frozen=True, slots=True)
class ProtectionConfig:
    peer_hbm: ProtectionPathConfig
    store_dram: ProtectionPathConfig
    store_depends_on_peer_hbm: bool
    peer_hbm_depends_on_store: bool
    same_source_production_buffer: bool


@dataclass(frozen=True, slots=True)
class CollectiveConfig:
    kind: str
    scope: str
    payload: str
    mathematical_reduction: bool
    all_reduce: bool
    logical_reassembly: str


@dataclass(frozen=True, slots=True)
class RecoveryPathConfig:
    source_tier: str
    rank_load: str
    completion_rule: str
    collective: CollectiveConfig


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    peer_hbm: RecoveryPathConfig
    store_dram: RecoveryPathConfig
    cross_layout_conversion_allowed: bool


@dataclass(frozen=True, slots=True)
class Algorithm3Config:
    """Modeled AIMD parameters for each Router-designated Peer-HBM target."""

    control_window_ns: int
    minimum_fraction: str
    maximum_fraction: str
    initial_fraction: str
    multiplicative_decrease: str
    additive_increase: str
    stable_window_count: int
    pressure_source: str
    controller_scope: str
    provenance: str


@dataclass(frozen=True, slots=True)
class TransferCostConfig:
    transport: str
    effective_bandwidth_bytes_per_second: int
    setup_ns: int


@dataclass(frozen=True, slots=True)
class CollectiveCostConfig:
    transport: str
    fixed_overhead_ns: int
    data_reduction_bytes: int


@dataclass(frozen=True, slots=True)
class ModeledCostsConfig:
    intra_node_nvlink: TransferCostConfig
    cross_node_peer_hbm: TransferCostConfig
    store_dram: TransferCostConfig
    tp_collective_sync: CollectiveCostConfig


@dataclass(frozen=True, slots=True)
class EvidenceConfig:
    timing_and_bandwidth: str
    capacity: str
    calibrated: bool
    physical_measurement_completed: bool
    allowed_claim: str


@dataclass(frozen=True, slots=True)
class RankPlacement:
    dp_rank: int
    tp_rank: int
    pp_rank: int
    linear_rank: int
    node_id: str
    local_gpu_id: int
    resource_id: str


@dataclass(frozen=True, slots=True)
class PeerShardBackup:
    source: RankPlacement
    target: RankPlacement


@dataclass(frozen=True, slots=True)
class Qwen3TP4EngineConfig:
    schema: str
    model: ModelConfig
    parallelism: ParallelismConfig
    cluster: ClusterConfig
    capacity: CapacityConfig
    placement: PlacementConfig
    protection: ProtectionConfig
    recovery: RecoveryConfig
    algorithm3: Algorithm3Config
    modeled_costs: ModeledCostsConfig
    evidence: EvidenceConfig

    @property
    def rank_placements(self) -> tuple[RankPlacement, ...]:
        """Expand the frozen DP-major rank formulas into all 32 GPU ranks."""

        ranks: list[RankPlacement] = []
        tp_size = self.parallelism.tensor_parallel_size
        for dp_rank in range(self.parallelism.data_parallel_size):
            for tp_rank in range(tp_size):
                linear_rank = dp_rank * tp_size + tp_rank
                node_id = f"node-{dp_rank}"
                ranks.append(
                    RankPlacement(
                        dp_rank=dp_rank,
                        tp_rank=tp_rank,
                        pp_rank=0,
                        linear_rank=linear_rank,
                        node_id=node_id,
                        local_gpu_id=tp_rank,
                        resource_id=f"gpu:{node_id}:{tp_rank}",
                    )
                )
        return tuple(ranks)

    @property
    def peer_shard_backups(self) -> tuple[PeerShardBackup, ...]:
        """Return one failure-domain-separated Peer-HBM copy per TP shard."""

        by_rank = {(rank.dp_rank, rank.tp_rank): rank for rank in self.rank_placements}
        backups: list[PeerShardBackup] = []
        for source_dp, target_dp in enumerate(self.placement.peer_target_dp_by_source_dp):
            for tp_rank in range(self.parallelism.tensor_parallel_size):
                backups.append(
                    PeerShardBackup(
                        source=by_rank[(source_dp, tp_rank)],
                        target=by_rank[(target_dp, tp_rank)],
                    )
                )
        return tuple(backups)


def repository_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").is_file() and (parent / "python/moonkvsim").is_dir():
            return parent
    raise Qwen3TP4ConfigError("cannot locate the MoonKVSim repository root")


def default_qwen3_32b_tp4_config_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / DEFAULT_CONFIG_RELATIVE_PATH


@cache
def _validator() -> Draft202012Validator:
    schema_path = repository_root() / SCHEMA_RELATIVE_PATH
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load schema {schema_path}: {error}") from error
    if not isinstance(schema, dict):
        raise RuntimeError(f"schema {schema_path} is not a JSON object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise RuntimeError(f"invalid schema {schema_path}: {error.message}") from error
    return Draft202012Validator(schema)


def _json_path(parts: list[object]) -> str:
    if not parts:
        return "$"
    return "$." + ".".join(str(part) for part in parts)


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise Qwen3TP4ConfigError(f"config symlinks are forbidden: {path}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise Qwen3TP4ConfigError(f"duplicate JSON key in {path}: {key}")
            document[key] = value
        return document

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except Qwen3TP4ConfigError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise Qwen3TP4ConfigError(f"cannot load {path}: {error}") from error
    if not isinstance(document, dict):
        raise Qwen3TP4ConfigError(f"{path} must contain a JSON object")
    return document


def _mapping(document: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = document[key]
    assert isinstance(value, dict)
    return value


def _protection_path(document: Mapping[str, Any]) -> ProtectionPathConfig:
    return ProtectionPathConfig(
        tier=document["tier"],
        source=document["source"],
        ownership=document["ownership"],
        admission=document["admission"],
        shard_granularity=document["shard_granularity"],
        writes_per_logical_chunk=document["writes_per_logical_chunk"],
        commit_rule=document["commit_rule"],
        cross_tier_copy_allowed=document["cross_tier_copy_allowed"],
    )


def _collective(document: Mapping[str, Any]) -> CollectiveConfig:
    return CollectiveConfig(
        kind=document["kind"],
        scope=document["scope"],
        payload=document["payload"],
        mathematical_reduction=document["mathematical_reduction"],
        all_reduce=document["all_reduce"],
        logical_reassembly=document["logical_reassembly"],
    )


def _recovery_path(document: Mapping[str, Any]) -> RecoveryPathConfig:
    return RecoveryPathConfig(
        source_tier=document["source_tier"],
        rank_load=document["rank_load"],
        completion_rule=document["completion_rule"],
        collective=_collective(_mapping(document, "collective")),
    )


def _transfer_cost(document: Mapping[str, Any]) -> TransferCostConfig:
    return TransferCostConfig(
        transport=document["transport"],
        effective_bandwidth_bytes_per_second=document["effective_bandwidth_bytes_per_second"],
        setup_ns=document["setup_ns"],
    )


def _capacity(document: Mapping[str, Any]) -> CapacityConfig:
    rank_hbm = _mapping(document, "rank_hbm")
    store_dram = _mapping(document, "store_dram")
    provenance = _mapping(document, "provenance")
    raw_segments = store_dram["segments"]
    assert isinstance(raw_segments, list)
    return CapacityConfig(
        status=document["status"],
        rank_hbm=RankHBMCapacityConfig(
            physical_hbm_bytes_per_rank=rank_hbm["physical_hbm_bytes_per_rank"],
            model_weights_bytes_per_rank=rank_hbm["model_weights_bytes_per_rank"],
            runtime_fixed_bytes_per_rank=rank_hbm["runtime_fixed_bytes_per_rank"],
            kv_capable_hbm_bytes_per_rank=rank_hbm["kv_capable_hbm_bytes_per_rank"],
            peer_hbm_dynamic_quota_upper_bound_bytes_per_rank=rank_hbm[
                "peer_hbm_dynamic_quota_upper_bound_bytes_per_rank"
            ],
            peer_hbm_dynamic_quota_upper_bound_numerator=rank_hbm[
                "peer_hbm_dynamic_quota_upper_bound_numerator"
            ],
            peer_hbm_dynamic_quota_upper_bound_denominator=rank_hbm[
                "peer_hbm_dynamic_quota_upper_bound_denominator"
            ],
            peer_hbm_accounting_rule=rank_hbm["peer_hbm_accounting_rule"],
        ),
        store_dram=StoreDRAMCapacityConfig(
            store_node_count=store_dram["store_node_count"],
            total_capacity_bytes=store_dram["total_capacity_bytes"],
            failure_domain_rule=store_dram["failure_domain_rule"],
            segments=tuple(
                StoreDRAMSegmentConfig(
                    segment_id=segment["segment_id"],
                    node_id=segment["node_id"],
                    capacity_bytes=segment["capacity_bytes"],
                )
                for segment in raw_segments
            ),
        ),
        provenance=CapacityProvenanceConfig(
            physical_hbm_bytes_per_rank=provenance["physical_hbm_bytes_per_rank"],
            model_weights_bytes_per_rank=provenance["model_weights_bytes_per_rank"],
            runtime_fixed_bytes_per_rank=provenance["runtime_fixed_bytes_per_rank"],
            kv_capable_hbm_bytes_per_rank=provenance["kv_capable_hbm_bytes_per_rank"],
            peer_hbm_dynamic_quota_upper_bound_bytes_per_rank=provenance[
                "peer_hbm_dynamic_quota_upper_bound_bytes_per_rank"
            ],
            store_dram_capacity_bytes_per_segment=provenance[
                "store_dram_capacity_bytes_per_segment"
            ],
        ),
    )


def _build_config(document: Mapping[str, Any]) -> Qwen3TP4EngineConfig:
    model = _mapping(document, "model")
    parallelism = _mapping(document, "parallelism")
    cluster = _mapping(document, "cluster")
    capacity = _mapping(document, "capacity")
    placement = _mapping(document, "placement")
    protection = _mapping(document, "protection")
    recovery = _mapping(document, "recovery")
    algorithm3 = _mapping(document, "algorithm3")
    costs = _mapping(document, "modeled_costs")
    evidence = _mapping(document, "evidence")
    collective_cost = _mapping(costs, "tp_collective_sync")

    config = Qwen3TP4EngineConfig(
        schema=document["schema"],
        model=ModelConfig(
            model_id=model["id"],
            revision=model["revision"],
            dtype=model["dtype"],
            kv_dtype=model["kv_dtype"],
            native_max_context_tokens=model["native_max_context_tokens"],
            max_context_tokens=model["max_context_tokens"],
            context_extension_provenance=model["context_extension_provenance"],
            num_hidden_layers=model["num_hidden_layers"],
            num_kv_heads=model["num_kv_heads"],
            head_dim=model["head_dim"],
            kv_scalar_bytes=model["kv_scalar_bytes"],
            kv_bytes_per_token_total=model["kv_bytes_per_token_total"],
            kv_bytes_per_token_per_tp_rank=model["kv_bytes_per_token_per_tp_rank"],
            kv_layout_status=model["kv_layout_status"],
        ),
        parallelism=ParallelismConfig(
            data_parallel_size=parallelism["data_parallel_size"],
            tensor_parallel_size=parallelism["tensor_parallel_size"],
            pipeline_parallel_size=parallelism["pipeline_parallel_size"],
            world_size=parallelism["world_size"],
        ),
        cluster=ClusterConfig(
            inference_node_count=cluster["inference_node_count"],
            gpus_per_node=cluster["gpus_per_node"],
            gpu_count=cluster["gpu_count"],
            gpu_sku=cluster["gpu_sku"],
            physical_hbm_bytes_per_gpu=cluster["physical_hbm_bytes_per_gpu"],
            tp_group_placement=cluster["tp_group_placement"],
            intra_node_gpu_fabric=cluster["intra_node_gpu_fabric"],
        ),
        capacity=_capacity(capacity),
        placement=PlacementConfig(
            linear_rank_formula=placement["linear_rank_formula"],
            node_formula=placement["node_formula"],
            local_gpu_formula=placement["local_gpu_formula"],
            peer_target_dp_by_source_dp=tuple(placement["peer_target_dp_by_source_dp"]),
            peer_mapping_rule=placement["peer_mapping_rule"],
            peer_failure_domain_rule=placement["peer_failure_domain_rule"],
        ),
        protection=ProtectionConfig(
            peer_hbm=_protection_path(_mapping(protection, "peer_hbm")),
            store_dram=_protection_path(_mapping(protection, "store_dram")),
            store_depends_on_peer_hbm=protection["store_depends_on_peer_hbm"],
            peer_hbm_depends_on_store=protection["peer_hbm_depends_on_store"],
            same_source_production_buffer=protection["same_source_production_buffer"],
        ),
        recovery=RecoveryConfig(
            peer_hbm=_recovery_path(_mapping(recovery, "peer_hbm")),
            store_dram=_recovery_path(_mapping(recovery, "store_dram")),
            cross_layout_conversion_allowed=recovery["cross_layout_conversion_allowed"],
        ),
        algorithm3=Algorithm3Config(
            control_window_ns=algorithm3["control_window_ns"],
            minimum_fraction=algorithm3["minimum_fraction"],
            maximum_fraction=algorithm3["maximum_fraction"],
            initial_fraction=algorithm3["initial_fraction"],
            multiplicative_decrease=algorithm3["multiplicative_decrease"],
            additive_increase=algorithm3["additive_increase"],
            stable_window_count=algorithm3["stable_window_count"],
            pressure_source=algorithm3["pressure_source"],
            controller_scope=algorithm3["controller_scope"],
            provenance=algorithm3["provenance"],
        ),
        modeled_costs=ModeledCostsConfig(
            intra_node_nvlink=_transfer_cost(_mapping(costs, "intra_node_nvlink")),
            cross_node_peer_hbm=_transfer_cost(_mapping(costs, "cross_node_peer_hbm")),
            store_dram=_transfer_cost(_mapping(costs, "store_dram")),
            tp_collective_sync=CollectiveCostConfig(
                transport=collective_cost["transport"],
                fixed_overhead_ns=collective_cost["fixed_overhead_ns"],
                data_reduction_bytes=collective_cost["data_reduction_bytes"],
            ),
        ),
        evidence=EvidenceConfig(
            timing_and_bandwidth=evidence["timing_and_bandwidth"],
            capacity=evidence["capacity"],
            calibrated=evidence["calibrated"],
            physical_measurement_completed=evidence["physical_measurement_completed"],
            allowed_claim=evidence["allowed_claim"],
        ),
    )
    _validate_semantics(config)
    return config


def _validate_semantics(config: Qwen3TP4EngineConfig) -> None:
    parallel = config.parallelism
    cluster = config.cluster
    model = config.model
    capacity = config.capacity
    algorithm3 = config.algorithm3

    expected_world_size = (
        parallel.data_parallel_size
        * parallel.tensor_parallel_size
        * parallel.pipeline_parallel_size
    )
    if parallel.world_size != expected_world_size:
        raise Qwen3TP4ConfigError("parallelism.world_size does not equal DP*TP*PP")
    if cluster.gpu_count != expected_world_size:
        raise Qwen3TP4ConfigError("cluster.gpu_count does not equal DP*TP*PP")
    if cluster.inference_node_count * cluster.gpus_per_node != cluster.gpu_count:
        raise Qwen3TP4ConfigError("cluster node/GPU geometry is inconsistent")
    if (
        cluster.inference_node_count != parallel.data_parallel_size
        or cluster.gpus_per_node != parallel.tensor_parallel_size
    ):
        raise Qwen3TP4ConfigError(
            "one_dp_replica_per_node requires node_count=DP and GPUs_per_node=TP"
        )

    rank_hbm = capacity.rank_hbm
    if capacity.status != "modeled_uncalibrated":
        raise Qwen3TP4ConfigError("capacity values must remain modeled and uncalibrated")
    if rank_hbm.physical_hbm_bytes_per_rank != cluster.physical_hbm_bytes_per_gpu:
        raise Qwen3TP4ConfigError("per-rank HBM capacity drifts from the cluster GPU contract")
    if (
        rank_hbm.model_weights_bytes_per_rank * parallel.tensor_parallel_size
        != MODELED_MODEL_SAFETENSORS_TOTAL_BYTES
    ):
        raise Qwen3TP4ConfigError(
            "per-rank model weights do not reconstruct the locked safetensors total_size"
        )
    if (
        rank_hbm.model_weights_bytes_per_rank
        + rank_hbm.runtime_fixed_bytes_per_rank
        + rank_hbm.kv_capable_hbm_bytes_per_rank
        != rank_hbm.physical_hbm_bytes_per_rank
    ):
        raise Qwen3TP4ConfigError("per-rank fixed and KV-capable HBM accounts do not conserve HBM")
    if (
        rank_hbm.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
        * rank_hbm.peer_hbm_dynamic_quota_upper_bound_denominator
        != rank_hbm.kv_capable_hbm_bytes_per_rank
        * rank_hbm.peer_hbm_dynamic_quota_upper_bound_numerator
    ):
        raise Qwen3TP4ConfigError("Peer-HBM dynamic quota upper bound arithmetic drift")
    if (
        rank_hbm.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
        > rank_hbm.kv_capable_hbm_bytes_per_rank
    ):
        raise Qwen3TP4ConfigError("Peer-HBM dynamic quota exceeds KV-capable rank HBM")
    if rank_hbm.peer_hbm_accounting_rule != (
        "peer_hbm_dynamic_quota_is_reclaimable_subquota_of_kv_capable_hbm_not_additive"
    ):
        raise Qwen3TP4ConfigError("Peer-HBM quota must not add physical HBM capacity")

    try:
        minimum = Decimal(algorithm3.minimum_fraction)
        maximum = Decimal(algorithm3.maximum_fraction)
        initial = Decimal(algorithm3.initial_fraction)
        multiplicative = Decimal(algorithm3.multiplicative_decrease)
        additive = Decimal(algorithm3.additive_increase)
    except InvalidOperation as error:
        raise Qwen3TP4ConfigError("Algorithm 3 fractions must be exact decimals") from error
    if not Decimal(0) <= minimum <= initial <= maximum <= Decimal(1):
        raise Qwen3TP4ConfigError("Algorithm 3 fractions must satisfy 0 <= min <= initial <= max")
    if not Decimal(0) < multiplicative < Decimal(1) or additive <= 0:
        raise Qwen3TP4ConfigError("Algorithm 3 AIMD factors are invalid")
    if algorithm3.control_window_ns <= 0 or algorithm3.stable_window_count <= 0:
        raise Qwen3TP4ConfigError("Algorithm 3 window and stability count must be positive")
    if int(maximum * rank_hbm.kv_capable_hbm_bytes_per_rank) != (
        rank_hbm.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
    ):
        raise Qwen3TP4ConfigError("Algorithm 3 alpha_max drifts from the Peer-HBM quota cap")
    if algorithm3.pressure_source != ("explicit_schedule_signal_with_global_des_physical_snapshot"):
        raise Qwen3TP4ConfigError(
            "Algorithm 3 pressure must bind a schedule signal to a GlobalDES snapshot"
        )
    if algorithm3.controller_scope != "one_state_per_peer_target_dp_rank":
        raise Qwen3TP4ConfigError("Algorithm 3 controller must remain target-local")
    if algorithm3.provenance != "modeled_uncalibrated_not_selected_from_result_trends":
        raise Qwen3TP4ConfigError("Algorithm 3 parameters must retain modeled provenance")

    store = capacity.store_dram
    if store.store_node_count != 1 or len(store.segments) != 1:
        raise Qwen3TP4ConfigError("Store DRAM must declare one dedicated node and segment")
    if len({segment.segment_id for segment in store.segments}) != len(store.segments):
        raise Qwen3TP4ConfigError("Store DRAM segment IDs must be unique")
    if store.segments[0].node_id != "store-0" or store.segments[0].segment_id != (
        "store-0:segment-0"
    ):
        raise Qwen3TP4ConfigError("Store DRAM segment identity must remain topology-bound")
    if store.failure_domain_rule != "outside_all_inference_node_failure_domains":
        raise Qwen3TP4ConfigError("Store DRAM must remain outside inference failure domains")
    if any(
        segment.capacity_bytes != MODELED_STORE_DRAM_BYTES_PER_SEGMENT for segment in store.segments
    ):
        raise Qwen3TP4ConfigError("Store DRAM per-segment capacity drift")
    if sum(segment.capacity_bytes for segment in store.segments) != store.total_capacity_bytes:
        raise Qwen3TP4ConfigError("Store DRAM segment capacities do not conserve total capacity")

    expected_total_kv = (
        2 * model.num_hidden_layers * model.num_kv_heads * model.head_dim * model.kv_scalar_bytes
    )
    if model.kv_bytes_per_token_total != expected_total_kv:
        raise Qwen3TP4ConfigError("model total KV bytes/token arithmetic drift")
    if (
        model.native_max_context_tokens != 40_960
        or model.max_context_tokens != 131_072
        or model.context_extension_provenance != "proposed_yarn_128k_modeled_not_runtime_validated"
        or model.kv_layout_status != "proposed_yarn_128k_modeled_runtime_validation_pending"
    ):
        raise Qwen3TP4ConfigError("Qwen3-32B proposed YaRN 128K context contract drift")
    if model.num_kv_heads % parallel.tensor_parallel_size:
        raise Qwen3TP4ConfigError("KV heads do not shard evenly across TP ranks")
    if (
        model.kv_bytes_per_token_per_tp_rank * parallel.tensor_parallel_size
        != model.kv_bytes_per_token_total
    ):
        raise Qwen3TP4ConfigError("per-rank KV bytes do not reconstruct the logical KV")

    peer_map = config.placement.peer_target_dp_by_source_dp
    if len(peer_map) != parallel.data_parallel_size or set(peer_map) != set(
        range(parallel.data_parallel_size)
    ):
        raise Qwen3TP4ConfigError("Peer-HBM target map must be a DP-rank permutation")
    if any(source_dp == target_dp for source_dp, target_dp in enumerate(peer_map)):
        raise Qwen3TP4ConfigError(
            "Peer-HBM target must be in a different inference-node failure domain"
        )

    paths = (config.protection.peer_hbm, config.protection.store_dram)
    if {path.tier for path in paths} != {"PEER_HBM", "STORE_DRAM"}:
        raise Qwen3TP4ConfigError("protection paths must cover Peer HBM and Store DRAM")
    if any(path.writes_per_logical_chunk != parallel.tensor_parallel_size for path in paths):
        raise Qwen3TP4ConfigError("each tier must write one shard per TP rank")
    if (
        config.protection.store_depends_on_peer_hbm
        or config.protection.peer_hbm_depends_on_store
        or any(path.cross_tier_copy_allowed for path in paths)
    ):
        raise Qwen3TP4ConfigError("Peer HBM and Store DRAM must remain independent")

    for name, path in (
        ("peer_hbm", config.recovery.peer_hbm),
        ("store_dram", config.recovery.store_dram),
    ):
        collective = path.collective
        if collective.kind != "TP_BARRIER":
            raise Qwen3TP4ConfigError(f"recovery.{name} must use a TP readiness barrier")
        if collective.mathematical_reduction or collective.all_reduce:
            raise Qwen3TP4ConfigError(
                f"recovery.{name} must not mathematically all-reduce KV shards"
            )
    if config.modeled_costs.tp_collective_sync.data_reduction_bytes != 0:
        raise Qwen3TP4ConfigError("TP recovery synchronization cannot reduce KV bytes")

    if (
        config.evidence.timing_and_bandwidth != "modeled_uncalibrated"
        or config.evidence.capacity != "modeled_uncalibrated"
        or config.evidence.calibrated
        or config.evidence.physical_measurement_completed
        or config.evidence.allowed_claim != "simulation_only"
    ):
        raise Qwen3TP4ConfigError(
            "all capacity/timing/bandwidth values must remain modeled and uncalibrated"
        )

    ranks = config.rank_placements
    if len(ranks) != expected_world_size or len({rank.resource_id for rank in ranks}) != len(ranks):
        raise Qwen3TP4ConfigError("expanded rank placement is not one-to-one")
    backups = config.peer_shard_backups
    if len(backups) != expected_world_size:
        raise Qwen3TP4ConfigError("Peer-HBM mapping must contain one copy per TP shard")
    if any(
        item.source.tp_rank != item.target.tp_rank or item.source.node_id == item.target.node_id
        for item in backups
    ):
        raise Qwen3TP4ConfigError("Peer-HBM shard mapping violates rank or failure domain")


def load_qwen3_32b_tp4_engine_config(
    path: Path | None = None,
    *,
    root: Path | None = None,
) -> Qwen3TP4EngineConfig:
    """Load, schema-check, and semantically validate the TP4 engine contract."""

    config_path = path or default_qwen3_32b_tp4_config_path(root)
    document = _load_json_object(config_path)
    errors = sorted(
        _validator().iter_errors(document),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        detail = "; ".join(
            f"{_json_path(list(error.absolute_path))}: {error.message}" for error in errors
        )
        raise Qwen3TP4ConfigError(f"schema validation failed: {detail}")
    return _build_config(document)


__all__ = [
    "Algorithm3Config",
    "CapacityConfig",
    "CapacityProvenanceConfig",
    "ClusterConfig",
    "CollectiveConfig",
    "CollectiveCostConfig",
    "EvidenceConfig",
    "ModelConfig",
    "ModeledCostsConfig",
    "ParallelismConfig",
    "PeerShardBackup",
    "PlacementConfig",
    "ProtectionConfig",
    "ProtectionPathConfig",
    "Qwen3TP4ConfigError",
    "Qwen3TP4EngineConfig",
    "RankHBMCapacityConfig",
    "RankPlacement",
    "RecoveryConfig",
    "RecoveryPathConfig",
    "StoreDRAMCapacityConfig",
    "StoreDRAMSegmentConfig",
    "TransferCostConfig",
    "default_qwen3_32b_tp4_config_path",
    "load_qwen3_32b_tp4_engine_config",
]
