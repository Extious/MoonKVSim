from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.config import ConfigBundleError, resolve_config_bundle

_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
_VLLM_COMMIT = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
_MODEL_CONFIG_SHA256 = "f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30"


def _documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    requests = {
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
            "normalized_trace_path": "/data/normalized.jsonl",
            "trace_sha256": "a" * 64,
            "normalizer_commit": "b" * 40,
            "closed_loop": True,
            "preserve_agent_dag": True,
            "preserve_recorded_tool_delay": True,
            "derive_prefix_sharing_from_source_hash_ids": True,
            "provenance": {
                "license": "Apache-2.0",
                "access_level": "public",
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
            "revision": _REVISION,
            "tokenizer_config_sha256": (
                "d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101"
            ),
            "chat_template_sha256": (
                "a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8"
            ),
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
    failure = {
        "schema": "moonkvsim.failure.v1",
        "enabled": False,
        "events": [],
    }
    deployment = {
        "schema": "moonkvsim.deployment.v1",
        "model": {
            "id": "Qwen/Qwen3-8B",
            "revision": _REVISION,
            "dtype": "bf16",
            "kv_dtype": "bf16",
            "config_sha256": _MODEL_CONFIG_SHA256,
            "kv_layout_path": (
                "configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json"
            ),
        },
        "engine": {
            "kind": "vllm",
            "source_commit": _VLLM_COMMIT,
            "dp_size": 1,
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
        "predictor": {"kind": "aiconfigurator", "profile": "unresolved"},
        "policy": {"kind": "mooncake_default", "resource_accounting": "byte_exact"},
    }
    return requests, failure, deployment


def _populate_runtime_resources(deployment: dict[str, Any]) -> None:
    deployment["memory"]["gpu_profiles"] = [
        {
            "resource_id": "gpu:n0:0",
            "node_id": "n0",
            "gpu_id": 0,
            "location": "PRIMARY_HBM",
            "hbm_capacity_bytes": 24_000_000_000,
            "weights_bytes": 16_000_000_000,
            "runtime_reserve_bytes": 1_000_000_000,
            "block_allocator": {
                "kind": "vllm_block_manager",
                "alignment_bytes": 256,
                "granularity_bytes": 2359296,
            },
            "copy_engines": [
                {
                    "resource_id": "copy:n0:0",
                    "direction": "BIDIRECTIONAL",
                    "max_concurrency": 1,
                }
            ],
            "bandwidth_profile": {
                "profile_id": "toy-gpu",
                "source": "assumed",
                "artifact_path": None,
                "sha256": None,
            },
            "parameter_sources": [],
        }
    ]
    deployment["store"]["dram_segments"] = [
        {
            "resource_id": "store:s0:segment0",
            "node_id": "s0",
            "location": "STORE_DRAM",
            "capacity_bytes": 64_000_000_000,
            "reserved_bytes": 0,
            "read_lanes": 1,
            "write_lanes": 1,
            "parameter_sources": [],
        }
    ]
    deployment["network"]["nodes"] = [
        {"resource_id": "n0", "numa_node_ids": ["numa:n0:0"]},
        {"resource_id": "s0", "numa_node_ids": ["numa:s0:0"]},
    ]
    deployment["network"]["nics"] = [
        {
            "resource_id": "nic:n0:0",
            "node_id": "n0",
            "numa_node_id": "numa:n0:0",
            "ports": 1,
            "queue_ids": ["queue:n0:0"],
        },
        {
            "resource_id": "nic:s0:0",
            "node_id": "s0",
            "numa_node_id": "numa:s0:0",
            "ports": 1,
            "queue_ids": ["queue:s0:0"],
        },
    ]
    deployment["network"]["links"] = [
        {
            "resource_id": "link:n0-to-s0",
            "source_resource_id": "gpu:n0:0",
            "target_resource_id": "store:s0:segment0",
            "direction": "FORWARD",
            "bandwidth_bytes_per_s": 1_000_000_000.0,
            "latency_ns": 1_000,
            "shared_domain_id": "fabric:toy",
            "duplex": "full",
            "queue_id": "queue:n0:0",
            "parameter_sources": [],
        }
    ]


def test_bundle_is_deterministic_and_no_clobber(tmp_path: Path) -> None:
    requests, failure, deployment = _documents()
    first = resolve_config_bundle(
        requests,
        failure,
        deployment,
        repository_root=_ROOT,
        allow_incomplete_resources=True,
    )
    second = resolve_config_bundle(
        copy.deepcopy(requests),
        copy.deepcopy(failure),
        copy.deepcopy(deployment),
        repository_root=_ROOT,
        allow_incomplete_resources=True,
    )
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.sha256 == second.sha256

    target = tmp_path / "resolved-config.json"
    first.write(target)
    assert target.read_bytes() == first.to_json_bytes()
    with pytest.raises(FileExistsError):
        first.write(target)


@pytest.mark.parametrize(
    ("location", "replacement", "message"),
    [
        ("request_model", "other-model", "model_id must equal"),
        ("deployment_revision", "other-revision", "revision must equal"),
        ("engine_commit", "f" * 40, "vLLM commit"),
        ("block_size", 32, "block size"),
    ],
)
def test_bundle_rejects_cross_document_drift(
    location: str,
    replacement: object,
    message: str,
) -> None:
    requests, failure, deployment = _documents()
    if location == "request_model":
        requests["target_model_tokenizer"]["model_id"] = replacement
    elif location == "deployment_revision":
        deployment["model"]["revision"] = replacement
    elif location == "engine_commit":
        deployment["engine"]["source_commit"] = replacement
    else:
        deployment["engine"]["block_size"] = replacement
    with pytest.raises(ConfigBundleError, match=message):
        resolve_config_bundle(
            requests,
            failure,
            deployment,
            repository_root=_ROOT,
            allow_incomplete_resources=True,
        )


def test_bundle_requires_explicit_repository_root_for_layout_verification() -> None:
    requests, failure, deployment = _documents()
    with pytest.raises(ConfigBundleError, match="repository_root"):
        resolve_config_bundle(
            requests,
            failure,
            deployment,
            allow_incomplete_resources=True,
        )


def test_runtime_bundle_rejects_schema_only_empty_resources() -> None:
    requests, failure, deployment = _documents()
    with pytest.raises(ConfigBundleError, match="per-GPU profiles"):
        resolve_config_bundle(
            requests,
            failure,
            deployment,
            repository_root=_ROOT,
        )


def test_runtime_bundle_accepts_explicit_source_labeled_resource_graph() -> None:
    requests, failure, deployment = _documents()
    _populate_runtime_resources(deployment)
    bundle = resolve_config_bundle(
        requests,
        failure,
        deployment,
        repository_root=_ROOT,
    )
    assert bundle.deployment_sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown_link_endpoint", "source_resource_id is unknown"),
        ("unknown_numa", "numa_node_id is not on its node"),
        ("hbm_overcommit", "exceed HBM"),
    ],
)
def test_runtime_bundle_rejects_inconsistent_resource_graph(
    mutation: str,
    message: str,
) -> None:
    requests, failure, deployment = _documents()
    _populate_runtime_resources(deployment)
    if mutation == "unknown_link_endpoint":
        deployment["network"]["links"][0]["source_resource_id"] = "missing"
    elif mutation == "unknown_numa":
        deployment["network"]["nics"][0]["numa_node_id"] = "numa:missing"
    else:
        deployment["memory"]["gpu_profiles"][0]["weights_bytes"] = 24_000_000_001
    with pytest.raises(ConfigBundleError, match=message):
        resolve_config_bundle(
            requests,
            failure,
            deployment,
            repository_root=_ROOT,
        )
