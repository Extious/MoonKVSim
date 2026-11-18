"""Cross-document validation and deterministic resolved configuration output.

The three public configuration files are useful only when they describe the
same run.  JSON Schema validates each file in isolation; this module owns the
relationships between them and fails before the simulator creates evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.config.validation import (
    validate_deployment_config,
    validate_failure_config,
    validate_requests_config,
)

_RESOLVED_SCHEMA = "moonkvsim.resolved_config.v1"


class ConfigBundleError(ValueError):
    """The individually valid documents do not describe one unambiguous run."""


@dataclass(frozen=True, slots=True)
class ResolvedConfigBundle:
    """Validated, immutable inputs plus their canonical content hashes."""

    requests: Mapping[str, Any]
    failure: Mapping[str, Any]
    deployment: Mapping[str, Any]
    requests_sha256: str
    failure_sha256: str
    deployment_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _RESOLVED_SCHEMA,
            "config_hashes": {
                "requests": self.requests_sha256,
                "failure": self.failure_sha256,
                "deployment": self.deployment_sha256,
            },
            "requests": dict(self.requests),
            "failure": dict(self.failure),
            "deployment": dict(self.deployment),
            "evidence_boundary": {
                "class": "E1",
                "calibration_status": "not_inferred_from_configuration",
                "physical_validation_status": "not_inferred_from_configuration",
            },
        }

    @property
    def sha256(self) -> str:
        return sha256_json(self.to_dict())

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"

    def write(self, path: Path, *, overwrite: bool = False) -> None:
        """Publish canonical JSON without silently clobbering evidence."""

        if path.suffix != ".json":
            raise ConfigBundleError("resolved configuration path must end in .json")
        mode = "wb" if overwrite else "xb"
        with path.open(mode) as stream:
            stream.write(self.to_json_bytes())


def resolve_config_bundle(
    requests: Mapping[str, Any],
    failure: Mapping[str, Any],
    deployment: Mapping[str, Any],
    *,
    repository_root: Path | None = None,
    verify_kv_layout: bool = True,
    allow_incomplete_resources: bool = False,
) -> ResolvedConfigBundle:
    """Validate three documents and all frozen relationships between them."""

    validate_requests_config(requests)
    validate_failure_config(failure)
    validate_deployment_config(deployment)
    errors = _cross_document_errors(
        requests,
        failure,
        deployment,
        repository_root=repository_root,
        verify_kv_layout=verify_kv_layout,
        allow_incomplete_resources=allow_incomplete_resources,
    )
    if errors:
        raise ConfigBundleError("config bundle validation failed: " + "; ".join(errors))
    return ResolvedConfigBundle(
        requests=_json_clone(requests),
        failure=_json_clone(failure),
        deployment=_json_clone(deployment),
        requests_sha256=sha256_json(requests),
        failure_sha256=sha256_json(failure),
        deployment_sha256=sha256_json(deployment),
    )


def load_config_bundle(
    requests_path: Path,
    failure_path: Path,
    deployment_path: Path,
    *,
    repository_root: Path | None = None,
    verify_kv_layout: bool = True,
    allow_incomplete_resources: bool = False,
) -> ResolvedConfigBundle:
    """Load exactly three JSON objects, then resolve them as one run input."""

    return resolve_config_bundle(
        _load_json_object(requests_path),
        _load_json_object(failure_path),
        _load_json_object(deployment_path),
        repository_root=repository_root,
        verify_kv_layout=verify_kv_layout,
        allow_incomplete_resources=allow_incomplete_resources,
    )


def _cross_document_errors(
    requests: Mapping[str, Any],
    failure: Mapping[str, Any],
    deployment: Mapping[str, Any],
    *,
    repository_root: Path | None,
    verify_kv_layout: bool,
    allow_incomplete_resources: bool,
) -> list[str]:
    errors: list[str] = []
    request_model = cast(Mapping[str, Any], requests["target_model_tokenizer"])
    deployment_model = cast(Mapping[str, Any], deployment["model"])
    engine = cast(Mapping[str, Any], deployment["engine"])

    for field in ("id", "revision"):
        request_field = "model_id" if field == "id" else field
        if request_model[request_field] != deployment_model[field]:
            errors.append(
                f"target_model_tokenizer.{request_field} must equal deployment.model.{field}"
            )

    context = cast(Mapping[str, Any], requests["context"])
    gpu_profiles = cast(list[Mapping[str, Any]], deployment["memory"]["gpu_profiles"])
    store_segments = cast(list[Mapping[str, Any]], deployment["store"]["dram_segments"])
    network = cast(Mapping[str, Any], deployment["network"])
    resource_id_sequence = _all_resource_ids(deployment)
    resource_ids = set(resource_id_sequence)
    if len(resource_id_sequence) != len(resource_ids):
        errors.append("deployment resource_id values must be globally unique")
    errors.extend(_resource_topology_errors(deployment))

    required_gpu_count = cast(int, engine["dp_size"]) * cast(
        int, engine["tp_size"]
    ) * cast(int, engine["pp_size"])
    if gpu_profiles and len(gpu_profiles) < required_gpu_count:
        errors.append(
            "deployment has fewer GPU profiles than dp_size * tp_size * pp_size"
        )
    if not allow_incomplete_resources:
        if not gpu_profiles:
            errors.append("resolved runtime requires explicit per-GPU profiles")
        if not store_segments:
            errors.append("resolved runtime requires at least one Store DRAM segment")
        for field in ("nodes", "nics", "links"):
            if not cast(list[object], network[field]):
                errors.append(f"resolved runtime requires explicit network.{field}")

    known_gpu_targets = {
        (cast(str, profile["node_id"]), cast(int, profile["gpu_id"]))
        for profile in gpu_profiles
    }
    for index, event in enumerate(cast(list[Mapping[str, Any]], failure["events"])):
        target = cast(Mapping[str, Any], event["target"])
        target_key = (cast(str, target["node_id"]), cast(int, target["gpu_id"]))
        if gpu_profiles and target_key not in known_gpu_targets:
            errors.append(f"failure.events[{index}].target is not a configured GPU")
        unknown_affected = sorted(
            set(cast(list[str], event.get("affected_resource_ids", []))) - resource_ids
        )
        if resource_ids and unknown_affected:
            errors.append(
                f"failure.events[{index}].affected_resource_ids are unknown: "
                f"{unknown_affected}"
            )

    if verify_kv_layout:
        if repository_root is None:
            errors.append("repository_root is required when verify_kv_layout=true")
        else:
            errors.extend(
                _kv_layout_errors(
                    deployment_model,
                    engine,
                    context,
                    repository_root=repository_root,
                )
            )
    return errors


def _kv_layout_errors(
    model: Mapping[str, Any],
    engine: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    repository_root: Path,
) -> list[str]:
    raw_path = Path(cast(str, model["kv_layout_path"]))
    layout_path = raw_path if raw_path.is_absolute() else repository_root / raw_path
    try:
        layout = _load_json_object(layout_path)
    except ConfigBundleError as error:
        return [str(error)]
    errors: list[str] = []
    if layout.get("schema") != "moonkvsim.kv_layout.v1":
        errors.append("kv-layout schema must be moonkvsim.kv_layout.v1")
        return errors

    layout_model = layout.get("model")
    parallelism = layout.get("parallelism")
    layout_context = layout.get("context")
    sources = layout.get("sources")
    stage_layouts = layout.get("stage_rank_layouts")
    if not all(
        isinstance(item, Mapping)
        for item in (layout_model, parallelism, layout_context, sources)
    ) or not isinstance(stage_layouts, list):
        return ["kv-layout is missing model/parallelism/context/sources/stage_rank_layouts"]

    layout_model = cast(Mapping[str, Any], layout_model)
    parallelism = cast(Mapping[str, Any], parallelism)
    layout_context = cast(Mapping[str, Any], layout_context)
    sources = cast(Mapping[str, Any], sources)
    source_vllm = sources.get("vllm")
    checks = (
        (layout_model.get("id"), model["id"], "kv-layout model id"),
        (layout_model.get("revision"), model["revision"], "kv-layout model revision"),
        (layout_model.get("config_sha256"), model["config_sha256"], "kv-layout config hash"),
        (
            parallelism.get("tensor_parallel_size"),
            engine["tp_size"],
            "kv-layout tensor parallel size",
        ),
        (
            parallelism.get("pipeline_parallel_size"),
            engine["pp_size"],
            "kv-layout pipeline parallel size",
        ),
        (
            layout_context.get("max_model_len_tokens"),
            context["max_model_len_tokens"],
            "kv-layout maximum model length",
        ),
    )
    for actual, expected, label in checks:
        if actual != expected:
            errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")
    if not isinstance(source_vllm, Mapping) or source_vllm.get("commit") != engine[
        "source_commit"
    ]:
        errors.append("kv-layout vLLM commit must equal deployment.engine.source_commit")
    if len(stage_layouts) != cast(int, engine["tp_size"]) * cast(int, engine["pp_size"]):
        errors.append("kv-layout stage/rank count must equal tp_size * pp_size")
    for index, stage in enumerate(stage_layouts):
        if not isinstance(stage, Mapping):
            errors.append(f"kv-layout stage_rank_layouts[{index}] must be an object")
            continue
        block = stage.get("block")
        if not isinstance(block, Mapping) or block.get("block_size_tokens") != engine[
            "block_size"
        ]:
            errors.append(
                f"kv-layout stage_rank_layouts[{index}] block size must equal engine.block_size"
            )
    return errors


def _all_resource_ids(deployment: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[object] = []
    memory = cast(Mapping[str, Any], deployment["memory"])
    store = cast(Mapping[str, Any], deployment["store"])
    network = cast(Mapping[str, Any], deployment["network"])
    values.extend(cast(list[object], memory["gpu_profiles"]))
    values.extend(cast(list[object], memory["host_dram_profiles"]))
    values.extend(cast(list[object], store["dram_segments"]))
    values.extend(cast(list[object], network["nodes"]))
    values.extend(cast(list[object], network["nics"]))
    values.extend(cast(list[object], network["links"]))
    result: list[str] = []
    for value in values:
        if isinstance(value, Mapping) and isinstance(value.get("resource_id"), str):
            result.append(cast(str, value["resource_id"]))
        if isinstance(value, Mapping):
            for engine in cast(list[object], value.get("copy_engines", [])):
                if isinstance(engine, Mapping) and isinstance(
                    engine.get("resource_id"), str
                ):
                    result.append(cast(str, engine["resource_id"]))
            for queue_id in cast(list[object], value.get("queue_ids", [])):
                if isinstance(queue_id, str):
                    result.append(queue_id)
    return tuple(result)


def _resource_topology_errors(deployment: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    memory = cast(Mapping[str, Any], deployment["memory"])
    store = cast(Mapping[str, Any], deployment["store"])
    network = cast(Mapping[str, Any], deployment["network"])
    gpu_profiles = cast(list[Mapping[str, Any]], memory["gpu_profiles"])
    host_profiles = cast(list[Mapping[str, Any]], memory["host_dram_profiles"])
    store_segments = cast(list[Mapping[str, Any]], store["dram_segments"])
    nodes = cast(list[Mapping[str, Any]], network["nodes"])
    nics = cast(list[Mapping[str, Any]], network["nics"])
    links = cast(list[Mapping[str, Any]], network["links"])

    numa_by_node = {
        cast(str, node["resource_id"]): set(cast(list[str], node["numa_node_ids"]))
        for node in nodes
    }
    physical_gpu_keys: set[tuple[str, int]] = set()
    for index, profile in enumerate(gpu_profiles):
        node_id = cast(str, profile["node_id"])
        gpu_key = (node_id, cast(int, profile["gpu_id"]))
        if gpu_key in physical_gpu_keys:
            errors.append(f"memory.gpu_profiles[{index}] duplicates a physical GPU")
        physical_gpu_keys.add(gpu_key)
        if nodes and node_id not in numa_by_node:
            errors.append(f"memory.gpu_profiles[{index}].node_id is unknown")
        fixed = cast(int, profile["weights_bytes"]) + cast(
            int, profile["runtime_reserve_bytes"]
        )
        if fixed > cast(int, profile["hbm_capacity_bytes"]):
            errors.append(
                f"memory.gpu_profiles[{index}] weights plus runtime reserve exceed HBM"
            )

    for area, profiles in (
        ("memory.host_dram_profiles", host_profiles),
        ("store.dram_segments", store_segments),
    ):
        for index, profile in enumerate(profiles):
            node_id = cast(str, profile["node_id"])
            if nodes and node_id not in numa_by_node:
                errors.append(f"{area}[{index}].node_id is unknown")
            reserved = cast(int, profile["reserved_bytes"])
            staging = cast(int, profile.get("staging_pool_bytes", 0))
            if reserved + staging > cast(int, profile["capacity_bytes"]):
                errors.append(
                    f"{area}[{index}] fixed reserve plus staging pool exceed capacity"
                )

    queue_ids: set[str] = set()
    for index, nic in enumerate(nics):
        node_id = cast(str, nic["node_id"])
        numa_node_id = cast(str, nic["numa_node_id"])
        if nodes and node_id not in numa_by_node:
            errors.append(f"network.nics[{index}].node_id is unknown")
        elif nodes and numa_node_id not in numa_by_node[node_id]:
            errors.append(f"network.nics[{index}].numa_node_id is not on its node")
        queue_ids.update(cast(list[str], nic["queue_ids"]))

    endpoint_ids = {
        cast(str, item["resource_id"])
        for item in (*gpu_profiles, *host_profiles, *store_segments, *nodes, *nics)
    }
    for index, link in enumerate(links):
        for field in ("source_resource_id", "target_resource_id"):
            if endpoint_ids and cast(str, link[field]) not in endpoint_ids:
                errors.append(f"network.links[{index}].{field} is unknown")
        if queue_ids and cast(str, link["queue_id"]) not in queue_ids:
            errors.append(f"network.links[{index}].queue_id is unknown")
    return errors


def _json_clone(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(canonical_json_bytes(value)))


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigBundleError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigBundleError(f"{path}: top-level value must be an object")
    return value
