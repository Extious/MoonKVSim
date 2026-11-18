from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    Qwen3TP4ConfigError,
    default_qwen3_32b_tp4_config_path,
    load_qwen3_32b_tp4_engine_config,
)

ROOT = Path(__file__).resolve().parents[2]


def _document() -> dict[str, Any]:
    document = json.loads(default_qwen3_32b_tp4_config_path(ROOT).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "engine.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_default_contract_locks_qwen3_32b_dp8_tp4_cluster() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)

    assert config.model.model_id == "Qwen/Qwen3-32B"
    assert config.model.revision == "9216db5781bf21249d130ec9da846c4624c16137"
    assert config.model.native_max_context_tokens == 40_960
    assert config.model.max_context_tokens == 131_072
    assert config.model.context_extension_provenance == (
        "proposed_yarn_128k_modeled_not_runtime_validated"
    )
    assert config.model.kv_layout_status == (
        "proposed_yarn_128k_modeled_runtime_validation_pending"
    )
    assert config.parallelism.data_parallel_size == 8
    assert config.parallelism.tensor_parallel_size == 4
    assert config.parallelism.pipeline_parallel_size == 1
    assert config.parallelism.world_size == 32
    assert config.cluster.inference_node_count == 8
    assert config.cluster.gpus_per_node == 4
    assert config.cluster.gpu_count == 32
    assert config.cluster.gpu_sku == "NVIDIA-A100-SXM4-80GB"
    assert config.cluster.physical_hbm_bytes_per_gpu == 80 * 1024**3
    assert config.cluster.intra_node_gpu_fabric == "NVLINK"


def test_capacity_contract_conserves_each_rank_hbm_without_double_counting_peer() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    capacity = config.capacity
    rank = capacity.rank_hbm

    assert capacity.status == "modeled_uncalibrated"
    assert rank.physical_hbm_bytes_per_rank == 80 * 1024**3
    assert rank.model_weights_bytes_per_rank == 65_524_246_528 // 4
    assert rank.runtime_fixed_bytes_per_rank == 2 * 1024**3
    assert rank.kv_capable_hbm_bytes_per_rank == 67_370_800_640
    assert (
        rank.model_weights_bytes_per_rank
        + rank.runtime_fixed_bytes_per_rank
        + rank.kv_capable_hbm_bytes_per_rank
        == rank.physical_hbm_bytes_per_rank
    )
    assert rank.peer_hbm_dynamic_quota_upper_bound_numerator == 1
    assert rank.peer_hbm_dynamic_quota_upper_bound_denominator == 2
    assert (
        rank.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank * 2
        == rank.kv_capable_hbm_bytes_per_rank
    )
    assert rank.peer_hbm_accounting_rule == (
        "peer_hbm_dynamic_quota_is_reclaimable_subquota_of_kv_capable_hbm_not_additive"
    )


def test_store_dram_capacity_is_one_dedicated_l3_segment() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    store = config.capacity.store_dram

    assert store.store_node_count == 1
    assert store.total_capacity_bytes == 1_000_000_000_000
    assert store.failure_domain_rule == "outside_all_inference_node_failure_domains"
    assert len(store.segments) == 1
    assert store.segments[0].segment_id == "store-0:segment-0"
    assert store.segments[0].node_id == "store-0"
    assert store.capacity_bytes_per_segment == 1_000_000_000_000
    assert store.total_capacity_bytes == sum(segment.capacity_bytes for segment in store.segments)


def test_every_capacity_value_is_provenance_bound_and_uncalibrated() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    provenance = config.capacity.provenance

    assert config.evidence.capacity == "modeled_uncalibrated"
    assert "runtime_allocatable_bytes_unobserved" in provenance.physical_hbm_bytes_per_rank
    assert "safetensors_index_total_size_65524246528" in (provenance.model_weights_bytes_per_rank)
    assert "not_physically_observed" in provenance.runtime_fixed_bytes_per_rank
    assert "shared_by_primary_reusable_and_peer_hbm" in (provenance.kv_capable_hbm_bytes_per_rank)
    assert "not_selected_from_result_trends" in (
        provenance.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
    )
    assert "not_inventory_or_runtime_observation" in (
        provenance.store_dram_capacity_bytes_per_segment
    )


def test_algorithm3_parameters_are_explicit_target_local_and_uncalibrated() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    algorithm3 = config.algorithm3

    assert algorithm3.control_window_ns == 100_000
    assert (
        algorithm3.minimum_fraction,
        algorithm3.initial_fraction,
        algorithm3.maximum_fraction,
    ) == ("0", "0.50", "0.50")
    assert algorithm3.multiplicative_decrease == "0.50"
    assert algorithm3.additive_increase == "0.05"
    assert algorithm3.stable_window_count == 4
    assert algorithm3.pressure_source == (
        "explicit_schedule_signal_with_global_des_physical_snapshot"
    )
    assert algorithm3.controller_scope == "one_state_per_peer_target_dp_rank"
    assert algorithm3.provenance == "modeled_uncalibrated_not_selected_from_result_trends"


def test_rank_expansion_places_each_tp_group_inside_one_node() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    ranks = config.rank_placements

    assert len(ranks) == 32
    assert {rank.linear_rank for rank in ranks} == set(range(32))
    assert len({rank.resource_id for rank in ranks}) == 32
    for dp_rank in range(8):
        group = [rank for rank in ranks if rank.dp_rank == dp_rank]
        assert {rank.node_id for rank in group} == {f"node-{dp_rank}"}
        assert {rank.tp_rank for rank in group} == {0, 1, 2, 3}
        assert {rank.local_gpu_id for rank in group} == {0, 1, 2, 3}


def test_peer_hbm_has_one_rank_preserving_cross_node_copy_per_shard() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    backups = config.peer_shard_backups

    assert len(backups) == 32
    assert len({(backup.source.dp_rank, backup.source.tp_rank) for backup in backups}) == 32
    assert len({(backup.target.dp_rank, backup.target.tp_rank) for backup in backups}) == 32
    assert all(backup.source.tp_rank == backup.target.tp_rank for backup in backups)
    assert all(backup.source.node_id != backup.target.node_id for backup in backups)


def test_peer_and_store_paths_are_independent_and_commit_complete_chunks() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    protection = config.protection

    assert protection.peer_hbm.admission == "independent"
    assert protection.store_dram.admission == "independent"
    assert protection.peer_hbm.source == "PRIMARY_HBM_PRODUCTION_BUFFER"
    assert protection.store_dram.source == "PRIMARY_HBM_PRODUCTION_BUFFER"
    assert protection.peer_hbm.writes_per_logical_chunk == 4
    assert protection.store_dram.writes_per_logical_chunk == 4
    assert protection.peer_hbm.commit_rule == "all_tp_shard_writes_ack"
    assert protection.store_dram.commit_rule == "all_tp_shard_writes_ack"
    assert protection.store_depends_on_peer_hbm is False
    assert protection.peer_hbm_depends_on_store is False
    assert protection.peer_hbm.cross_tier_copy_allowed is False
    assert protection.store_dram.cross_tier_copy_allowed is False


def test_recovery_is_per_rank_load_then_barrier_not_mathematical_all_reduce() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)

    assert config.recovery.peer_hbm.rank_load == ("activate_same_tp_rank_peer_hbm_shard")
    assert config.recovery.store_dram.rank_load == (
        "load_same_tp_rank_store_dram_shard_to_primary_hbm"
    )
    for path in (config.recovery.peer_hbm, config.recovery.store_dram):
        assert path.completion_rule == ("all_four_rank_loads_complete_then_collective_sync")
        assert path.collective.kind == "TP_BARRIER"
        assert path.collective.payload == "readiness_and_block_table_metadata_only"
        assert path.collective.mathematical_reduction is False
        assert path.collective.all_reduce is False
        assert path.collective.logical_reassembly == (
            "install_directory_generation_after_all_rank_shards_ready"
        )
    assert config.modeled_costs.tp_collective_sync.data_reduction_bytes == 0


def test_kv_geometry_is_sharded_evenly_across_tp_ranks() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)

    assert config.model.kv_bytes_per_token_total == (2 * 64 * 8 * 128 * 2)
    assert config.model.kv_bytes_per_token_per_tp_rank == 65_536
    assert (
        config.model.kv_bytes_per_token_per_tp_rank * config.parallelism.tensor_parallel_size
        == config.model.kv_bytes_per_token_total
    )


def test_all_timing_and_bandwidth_values_are_explicitly_uncalibrated() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)

    assert config.evidence.timing_and_bandwidth == "modeled_uncalibrated"
    assert config.evidence.capacity == "modeled_uncalibrated"
    assert config.evidence.calibrated is False
    assert config.evidence.physical_measurement_completed is False
    assert config.evidence.allowed_claim == "simulation_only"
    assert config.modeled_costs.intra_node_nvlink.effective_bandwidth_bytes_per_second > 0
    assert config.modeled_costs.cross_node_peer_hbm.effective_bandwidth_bytes_per_second > 0
    assert config.modeled_costs.store_dram.effective_bandwidth_bytes_per_second > 0


def test_schema_rejects_unknown_fields(tmp_path: Path) -> None:
    document = _document()
    document["cluster"]["marketing_bandwidth"] = "not-a-contract-field"

    with pytest.raises(Qwen3TP4ConfigError, match="Additional properties"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_semantics_reject_peer_targets_in_source_failure_domain(
    tmp_path: Path,
) -> None:
    document = _document()
    document["placement"]["peer_target_dp_by_source_dp"] = [0, 2, 1, 4, 3, 6, 7, 5]

    with pytest.raises(Qwen3TP4ConfigError, match="different inference-node"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


@pytest.mark.parametrize(
    ("field", "value"),
    [("all_reduce", True), ("mathematical_reduction", True)],
)
def test_schema_rejects_mathematical_reduction_of_kv_shards(
    tmp_path: Path,
    field: str,
    value: bool,
) -> None:
    document = _document()
    document["recovery"]["peer_hbm"]["collective"][field] = value

    with pytest.raises(Qwen3TP4ConfigError, match="False was expected"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_schema_rejects_store_dependency_on_peer_hbm(tmp_path: Path) -> None:
    document = copy.deepcopy(_document())
    document["protection"]["store_depends_on_peer_hbm"] = True

    with pytest.raises(Qwen3TP4ConfigError, match="False was expected"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_schema_rejects_capacity_drift(tmp_path: Path) -> None:
    document = _document()
    document["capacity"]["rank_hbm"]["kv_capable_hbm_bytes_per_rank"] += 1

    with pytest.raises(Qwen3TP4ConfigError, match="67370800640 was expected"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_schema_rejects_native_context_masquerading_as_128k(tmp_path: Path) -> None:
    document = _document()
    document["model"]["max_context_tokens"] = 40_960

    with pytest.raises(Qwen3TP4ConfigError, match="131072 was expected"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_schema_rejects_missing_capacity_provenance(tmp_path: Path) -> None:
    document = _document()
    del document["capacity"]["provenance"]["store_dram_capacity_bytes_per_segment"]

    with pytest.raises(
        Qwen3TP4ConfigError,
        match=r"store_dram_capacity_bytes_per_segment.*required property",
    ):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_schema_rejects_store_dram_inside_inference_failure_domain(
    tmp_path: Path,
) -> None:
    document = _document()
    document["capacity"]["store_dram"]["segments"][0]["node_id"] = "node-0"

    with pytest.raises(Qwen3TP4ConfigError, match=r"store-0.*expected"):
        load_qwen3_32b_tp4_engine_config(_write(tmp_path, document))


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema":"moonkvsim.aegiskv.qwen3_32b_tp4_engine.v1","schema":"duplicate"}',
        encoding="utf-8",
    )

    with pytest.raises(Qwen3TP4ConfigError, match="duplicate JSON key"):
        load_qwen3_32b_tp4_engine_config(path)
