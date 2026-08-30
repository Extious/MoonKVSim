from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from moonkvsim.config import (
    SchemaValidationError,
    load_schema,
    validate_deployment_config,
    validate_failure_config,
    validate_instance,
    validate_requests_config,
    validate_run_manifest,
    validate_trace_span,
)
from moonkvsim.config.validation import (
    _format_checker,
    _schema_errors,
    _schema_validation_instance,
    _schema_validator,
    _source_hash_ids_schema_supports_elision,
)


class _DictSubclass(dict[str, Any]):
    pass


class _ListSubclass(list[int]):
    pass


class _IntSubclass(int):
    pass


def _requests() -> dict[str, Any]:
    return {
        "schema": "moonkvsim.requests.v1",
        "seed": 1,
        "arrival": {
            "mode": "causal_trace_replay",
            "request_rate": None,
            "max_concurrency": None,
        },
        "workload": {
            "kind": "real_multi_agent_trace",
            "dataset": "semianalysisai/cc-traces-weka-062126",
            "raw_trace_path": "/data/raw.jsonl",
            "normalized_trace_path": "traces/normalized/weka.jsonl",
            "trace_sha256": "a" * 64,
            "normalizer_commit": "b" * 40,
            "closed_loop": True,
            "preserve_agent_dag": True,
            "preserve_recorded_tool_delay": True,
            "derive_prefix_sharing_from_source_hash_ids": True,
            "provenance": {
                "license": "Apache-2.0",
                "access_level": "unknown",
                "collection_interval": None,
                "build_timestamp": "2026-06-21T17:48:24Z",
                "content_availability": "source_hash_ids_only",
            },
        },
        "trace_token_count": {
            "mode": "source_hash_blocks_64",
            "source_block_size_tokens": 64,
            "hash_id_scope": "within_workflow_only",
        },
        "target_model_tokenizer": {
            "model_id": "Qwen/Qwen3-8B",
            "revision": "revision",
            "tokenizer_config_sha256": "c" * 64,
            "chat_template_sha256": None,
        },
        "context": {
            "max_model_len_tokens": 131072,
            "required_observed_context_buckets": [8192, 32768, 65536, 98304, 131072],
            "require_real_128k_samples": True,
            "overflow_policy": "fail",
            "truncation_policy": "forbid",
            "synthetic_padding": "forbid",
        },
    }


def _failure() -> dict[str, Any]:
    return {
        "schema": "moonkvsim.failure.v1",
        "enabled": True,
        "events": [
            {
                "failure_id": "f0",
                "type": "GPU_FAILURE",
                "at_s": 30.0,
                "target": {"node_id": "n0", "gpu_id": 0},
                "detection_delay_ms": 100,
                "repair_after_s": None,
                "semantics": "fail_stop_hbm_lost",
                "affected_resource_ids": ["gpu:n0:0"],
                "reroute": {
                    "rule": "healthy_dp_rank",
                    "on_no_healthy_target": "fail_request",
                },
            }
        ],
    }


def _deployment() -> dict[str, Any]:
    return {
        "schema": "moonkvsim.deployment.v1",
        "model": {
            "id": "Qwen/Qwen3-8B",
            "revision": "revision",
            "dtype": "bf16",
            "kv_dtype": "bf16",
            "config_sha256": "d" * 64,
            "kv_layout_path": "resolved/kv-layout.json",
        },
        "engine": {
            "kind": "vllm",
            "source_commit": "e" * 40,
            "dp_size": 2,
            "tp_size": 1,
            "pp_size": 1,
            "block_size": 16,
        },
        "memory": {
            "gpu_profiles": [],
            "host_dram_profiles": [],
            "allocation_alignment_bytes": 256,
            "allocator_granularity_bytes": 2097152,
            "account_fixed_runtime": True,
            "account_fragmentation": True,
        },
        "store": {
            "kind": "mooncake",
            "dram_segments": [],
            "eviction_policy": "baseline",
            "allocator": {
                "kind": "source_aligned",
                "granularity_bytes": None,
                "metadata_bytes_per_allocation": None,
            },
        },
        "network": {
            "protocol": "rdma",
            "gdr": True,
            "backend": "flow_contention",
            "slice_size_bytes": 65536,
            "bandwidth_allocator": "max_min_fair",
            "endpoint_pooling": True,
            "retry_count": 0,
            "registration": {
                "mode": "modeled_uncalibrated",
                "workers_per_context": 4,
            },
            "topology_matrix": "configs/topology/toy.json",
            "nodes": [],
            "nics": [],
            "links": [],
        },
        "predictor": {"kind": "aiconfigurator", "profile": "toy"},
        "policy": {"kind": "mooncake_default", "resource_accounting": "byte_exact"},
    }


def _run_manifest() -> dict[str, Any]:
    sha = "f" * 64
    bounds = [(0, 8192), (8192, 32768), (32768, 65536), (65536, 98304), (98304, 131072)]
    return {
        "schema": "moonkvsim.run_manifest.v1",
        "run_id": "run-toy",
        "config_hashes": {
            "requests": sha,
            "failure": sha,
            "deployment": sha,
            "resolved_config": sha,
        },
        "code": {"commit": "a" * 40, "dirty": False, "dirty_patch_sha256": None},
        "source_lock_sha256": sha,
        "predictor_database_sha256": sha,
        "trace": {
            "dataset": "weka",
            "raw_sha256": sha,
            "normalized_sha256": sha,
            "normalizer_sha256": sha,
            "workload_trace_sha256": sha,
            "provenance": {
                "license": "Apache-2.0",
                "access_level": "unknown",
                "collection_interval": None,
                "content_availability": "source_hash_ids_only",
                "evidence_class": "real_trace_shape_replay",
                "token_count_mode": "source_hash_blocks_64",
            },
        },
        "target_model": {
            "model_id": "Qwen/Qwen3-8B",
            "model_revision": "revision",
            "model_config_sha256": sha,
            "tokenizer_sha256": sha,
            "tokenizer_config_sha256": sha,
            "chat_template_sha256": None,
        },
        "coverage": {
            "workflow_count": 1,
            "span_count": 1,
            "sample_count": 1,
            "context_buckets": [
                {
                    "lower_exclusive": lower,
                    "upper_inclusive": upper,
                    "request_count": int(index == 0),
                    "workflow_count": int(index == 0),
                }
                for index, (lower, upper) in enumerate(bounds)
            ],
        },
        "integrity": {"synthetic": False, "truncated_count": 0, "overflow_count": 0},
        "seed": 1,
        "virtual_time": {"start_ns": 0, "end_ns": 1},
        "validation": {
            "evidence_class": "E2",
            "schema_validation": "pass",
            "trace_audit": "pass",
            "calibration_status": "not_required",
        },
        "result_completeness": {
            "status": "complete",
            "expected_artifacts": ["manifest.json"],
            "present_artifacts": ["manifest.json"],
            "missing_artifacts": [],
        },
    }


def _trace_span() -> dict[str, Any]:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "integration/fixtures/weka-real-shape-three-span.jsonl"
    )
    first_line = fixture.read_text(encoding="utf-8").splitlines()[0]
    document = json.loads(first_line)
    assert isinstance(document, dict)
    return document


def _fresh_multi_agent_schema_errors(instance: dict[str, Any]) -> tuple[str, ...]:
    validator = Draft202012Validator(
        load_schema("multi-agent-trace"),
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    return tuple(
        (
            "$"
            if not error.absolute_path
            else "$." + ".".join(str(part) for part in error.absolute_path)
        )
        + f": {error.message}"
        for error in errors
    )


@pytest.mark.parametrize(
    "schema_name",
    [
        "requests",
        "failure",
        "deployment",
        "multi-agent-trace",
        "predictor-held-out-residual-report",
        "predictor-profile-selection",
        "predictor-residual-thresholds",
        "run-manifest",
    ],
)
def test_schemas_are_valid_draft_2020_12(schema_name: str) -> None:
    schema = load_schema(schema_name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_schema_validator_cache_uses_canonical_identity_and_one_format_checker() -> None:
    canonical = _schema_validator("failure")

    assert canonical is _schema_validator("failure.schema.json")
    assert canonical is _schema_validator("moonkvsim.failure.v1")
    assert canonical.format_checker is _format_checker()
    assert _schema_validator("requests").format_checker is canonical.format_checker


def test_cached_validator_reuse_preserves_error_order_and_has_no_state_leak() -> None:
    invalid = _failure()
    invalid["extra"] = True
    invalid["events"][0]["ignored_typo"] = True
    invalid["events"][0]["at_s"] = -1
    expected = (
        "$: Additional properties are not allowed ('extra' was unexpected)",
        "$.events.0: Additional properties are not allowed ('ignored_typo' was unexpected)",
        "$.events.0.at_s: -1 is less than the minimum of 0",
    )

    for _ in range(2):
        with pytest.raises(SchemaValidationError) as captured:
            validate_failure_config(invalid)
        assert captured.value.messages == expected
        validate_failure_config(_failure())


def test_source_hash_ids_fast_path_schema_assumption_is_exact() -> None:
    schema = load_schema("multi-agent-trace")
    assert _source_hash_ids_schema_supports_elision(schema)

    for keyword, value in (
        ("minItems", 1),
        ("uniqueItems", True),
        ("contains", {"const": 0}),
    ):
        changed = copy.deepcopy(schema)
        changed["properties"]["source_hash_ids"][keyword] = value
        assert not _source_hash_ids_schema_supports_elision(changed)

    root_constraint = copy.deepcopy(schema)
    root_constraint["allOf"] = [
        {"properties": {"source_hash_ids": {"minItems": 1}}}
    ]
    assert not _source_hash_ids_schema_supports_elision(root_constraint)

    unrelated_change = copy.deepcopy(schema)
    unrelated_change["description"] = "schema drift must disable the reviewed fast path"
    assert not _source_hash_ids_schema_supports_elision(unrelated_change)


def test_source_hash_ids_fast_path_does_not_mutate_or_replace_original_values() -> None:
    span = _trace_span()
    original = copy.deepcopy(span)
    hash_ids = span["source_hash_ids"]

    validation_instance = _schema_validation_instance(span, "multi-agent-trace")

    assert validation_instance is not span
    assert validation_instance["source_hash_ids"] == []
    assert span == original
    assert span["source_hash_ids"] is hash_ids
    validate_trace_span(span)


def test_source_hash_ids_fast_path_falls_back_for_container_subclasses() -> None:
    dict_subclass = _DictSubclass(_trace_span())
    assert _schema_validation_instance(dict_subclass, "multi-agent-trace") is dict_subclass

    span = _trace_span()
    hash_ids = _ListSubclass([0, 1])
    span["source_hash_ids"] = hash_ids
    assert _schema_validation_instance(span, "multi-agent-trace") is span


def test_source_hash_ids_fast_path_semantics_use_the_original_list() -> None:
    span = _trace_span()
    span["source_hash_ids"] = [11, 12]
    span["prompt_tokens"] = 64
    span["total_model_tokens"] = span["prompt_tokens"] + span["output_tokens"]

    assert _schema_errors(span, "multi-agent-trace") == []
    with pytest.raises(
        SchemaValidationError,
        match=r"prompt_tokens: must equal len\(source_hash_ids\)",
    ):
        validate_trace_span(span)


@pytest.mark.parametrize(
    "source_hash_ids",
    [
        [],
        [0],
        [0, 1, 2**128],
        [_IntSubclass(1)],
        _ListSubclass([0, 1]),
        [True],
        [False],
        [-1],
        [0.0],
        [1.0],
        [-1.0],
        [1.5],
        ["1"],
        [None],
        [{}],
        (0, 1),
        None,
        "not-an-array",
    ],
)
def test_source_hash_ids_fast_path_matches_a_fresh_validator(
    source_hash_ids: Any,
) -> None:
    span = _trace_span()
    span["source_hash_ids"] = source_hash_ids
    span["unexpected"] = True

    assert tuple(_schema_errors(span, "multi-agent-trace")) == (
        _fresh_multi_agent_schema_errors(span)
    )


def test_source_hash_ids_missing_field_matches_a_fresh_validator() -> None:
    span = _trace_span()
    del span["source_hash_ids"]

    assert tuple(_schema_errors(span, "multi-agent-trace")) == (
        _fresh_multi_agent_schema_errors(span)
    )


def test_valid_configs_and_manifest_pass() -> None:
    validate_requests_config(_requests())
    validate_failure_config(_failure())
    validate_deployment_config(_deployment())
    validate_run_manifest(_run_manifest())


def test_incomplete_run_manifest_requires_a_named_missing_artifact() -> None:
    manifest = _run_manifest()
    manifest["result_completeness"]["status"] = "incomplete"

    with pytest.raises(SchemaValidationError, match="requires at least one missing"):
        validate_run_manifest(manifest)


@pytest.mark.parametrize(
    "mode",
    ["source_default", "modeled_uncalibrated", "calibrated"],
)
def test_registration_timing_evidence_mode_is_explicit(mode: str) -> None:
    deployment = _deployment()
    deployment["network"]["registration"]["mode"] = mode
    validate_deployment_config(deployment)

    deployment["network"]["registration"]["mode"] = "measured_but_unclassified"
    with pytest.raises(SchemaValidationError, match="not one of"):
        validate_deployment_config(deployment)


def test_host_and_store_dram_locations_are_not_conflated() -> None:
    valid = _deployment()
    valid["memory"]["host_dram_profiles"] = [
        {
            "resource_id": "host:n0:dram",
            "node_id": "n0",
            "location": "HOST_DRAM",
            "capacity_bytes": 1_000_000,
            "reserved_bytes": 1_000,
            "alignment_bytes": 64,
            "allocator_granularity_bytes": 64,
            "staging_pool_bytes": 100_000,
            "read_lanes": 1,
            "write_lanes": 1,
            "parameter_sources": [],
        }
    ]
    validate_deployment_config(valid)

    invalid = copy.deepcopy(valid)
    invalid["memory"]["host_dram_profiles"][0]["location"] = "STORE_DRAM"
    with pytest.raises(SchemaValidationError, match="HOST_DRAM"):
        validate_deployment_config(invalid)


@pytest.mark.parametrize(
    ("schema_name", "document", "container"),
    [
        ("requests", _requests(), "arrival"),
        ("failure", _failure(), "events"),
        ("deployment", _deployment(), "store"),
        ("run-manifest", _run_manifest(), "trace"),
    ],
)
def test_unknown_nested_fields_fail_closed(
    schema_name: str, document: dict[str, Any], container: str
) -> None:
    invalid = copy.deepcopy(document)
    target: Any = invalid[container]
    if isinstance(target, list):
        target = target[0]
    target["ignored_typo"] = True
    with pytest.raises(SchemaValidationError, match="Additional properties"):
        validate_instance(invalid, schema_name)


@pytest.mark.parametrize("failure_type", ["NODE_FAILURE", "NIC_FAILURE", "GPU_DEGRADED"])
def test_failure_schema_only_accepts_gpu_failure(failure_type: str) -> None:
    invalid = _failure()
    invalid["events"][0]["type"] = failure_type
    with pytest.raises(SchemaValidationError, match="GPU_FAILURE"):
        validate_failure_config(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ssd_segments", []),
        ("nvme_segments", []),
        ("local_disk", "/dev/nvme0n1"),
        ("persistence", True),
    ],
)
def test_deployment_rejects_persistent_store_fields(field: str, value: Any) -> None:
    invalid = _deployment()
    invalid["store"][field] = value
    with pytest.raises(SchemaValidationError):
        validate_deployment_config(invalid)


@pytest.mark.parametrize("value", ["SSD", "NVMe-oF", "LOCAL_DISK", "STORE_SSD"])
def test_deployment_rejects_persistent_store_values_even_in_known_fields(value: str) -> None:
    invalid = _deployment()
    invalid["predictor"]["profile"] = value
    with pytest.raises(SchemaValidationError, match="forbidden persistent-storage value"):
        validate_deployment_config(invalid)


def test_all_schema_files_are_json_objects() -> None:
    schema_dir = Path(__file__).resolve().parents[3] / "schemas"
    for path in sorted(schema_dir.glob("*.schema.json")):
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
