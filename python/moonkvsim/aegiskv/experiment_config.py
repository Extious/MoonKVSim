"""Load the three-layer AegisKV experiment configs.

``requests.json``, ``failure.json``, and ``engine.json`` live under
``benchmark/AegisKV/experiments/configs``.  They are the paper-facing inputs
for the AegisKV study; the MoonKVSim library maps them onto
``ModelParameters`` and the frozen workload paths.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.experiment import (
    A100_40GB_HBM_BYTES,
    ALLOWED_DP_COUNTS,
    GPU_SKU,
    LOCKED_DP_COUNT,
    QWEN3_8B_CONFIG_SHA256,
    QWEN3_8B_MODEL_ID,
    QWEN3_8B_MODEL_REVISION,
    TOPOLOGY,
    ModelParameters,
)
from moonkvsim.store.transfer_engine import TransportKind

REQUESTS_SCHEMA: Final = "moonkvsim.aegiskv.requests.v1"
FAILURE_SCHEMA: Final = "moonkvsim.aegiskv.failure.v1"
ENGINE_SCHEMA: Final = "moonkvsim.aegiskv.engine.v1"
LAYER_FILES: Final = ("requests.json", "failure.json", "engine.json")
ALLOWED_FAILURE_TYPE: Final = "GPU_FAILURE"
CURRENT_SCOPE_ID: Final = "qwen3-8b-dp8-a100-40gb-single-node-v1"
NATIVE_LAYOUT_FINGERPRINT: Final = (
    "616330f7a5e168edfad90d6e53dc8b754ef3f4c78925e80a49516e4f3f3d8d4f"
)
YARN_LAYOUT_FINGERPRINT: Final = (
    "d9863189bf94c967e18d4926ecb1fc88cc26e7dcb1553eb69972afaff7dc7d4d"
)
EXPECTED_CONTEXT_BUCKETS: Final = ("8k", "32k", "64k", "96k", "128k")


class ExperimentConfigError(ValueError):
    """The three-layer experiment config failed a fail-closed check."""


def repository_root(start: Path | None = None) -> Path:
    """Locate the MoonKVSim repository root from any nested path."""

    here = (start or Path(__file__)).resolve()
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").is_file() and (parent / "python/moonkvsim").is_dir():
            return parent
    raise ExperimentConfigError("cannot locate the MoonKVSim repository root")


def default_config_dir(root: Path | None = None) -> Path:
    return (root or repository_root()) / "benchmark/AegisKV/experiments/configs"


def resolve_repo_path(relative: str | Path, root: Path | None = None) -> Path:
    path = Path(relative)
    repository = (root or repository_root()).resolve()
    resolved = path.resolve() if path.is_absolute() else (repository / path).resolve()
    try:
        resolved.relative_to(repository)
    except ValueError as error:
        raise ExperimentConfigError(f"repository path escapes the checkout: {path}") from error
    return resolved


@dataclass(frozen=True, slots=True)
class ExperimentLayerConfigs:
    directory: Path
    requests: dict[str, Any]
    failure: dict[str, Any]
    engine: dict[str, Any]

    @property
    def requests_path(self) -> Path:
        return self.directory / "requests.json"

    @property
    def failure_path(self) -> Path:
        return self.directory / "failure.json"

    @property
    def engine_path(self) -> Path:
        return self.directory / "engine.json"


def load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ExperimentConfigError(f"JSON config symlinks are forbidden: {path}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ExperimentConfigError(f"duplicate JSON key in {path}: {key}")
            document[key] = value
        return document

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentConfigError(f"cannot load {path}: {error}") from error
    if not isinstance(document, dict):
        raise ExperimentConfigError(f"{path} must be a JSON object")
    return document


def load_experiment_configs(
    config_dir: Path | None = None,
    *,
    root: Path | None = None,
) -> ExperimentLayerConfigs:
    directory = (config_dir or default_config_dir(root)).resolve()
    if not directory.is_dir():
        raise ExperimentConfigError(f"experiment config directory is missing: {directory}")
    extra = sorted(path.name for path in directory.iterdir() if path.name not in LAYER_FILES)
    if extra:
        raise ExperimentConfigError(
            "experiments/configs may only contain requests.json, failure.json, "
            f"and engine.json; unexpected files: {extra}"
        )
    requests = load_json_object(directory / "requests.json")
    failure = load_json_object(directory / "failure.json")
    engine = load_json_object(directory / "engine.json")
    if requests.get("schema") != REQUESTS_SCHEMA:
        raise ExperimentConfigError(f"requests.json schema must be {REQUESTS_SCHEMA}")
    if failure.get("schema") != FAILURE_SCHEMA:
        raise ExperimentConfigError(f"failure.json schema must be {FAILURE_SCHEMA}")
    if engine.get("schema") != ENGINE_SCHEMA:
        raise ExperimentConfigError(f"engine.json schema must be {ENGINE_SCHEMA}")
    repository = (root or repository_root()).resolve()
    _validate_requests(requests, repository)
    _validate_failure(failure)
    _validate_engine(engine, repository)
    configs = ExperimentLayerConfigs(
        directory=directory,
        requests=requests,
        failure=failure,
        engine=engine,
    )
    model_parameters_from_configs(configs)
    return configs


def matrix_seeds(requests: Mapping[str, Any]) -> tuple[int, ...]:
    seed = _mapping(requests.get("seed"), "requests.seed")
    values = seed.get("matrix_seeds")
    if not isinstance(values, list) or not values:
        raise ExperimentConfigError("requests.seed.matrix_seeds must be a non-empty array")
    seeds: list[int] = []
    for index, value in enumerate(values):
        if type(value) is not int or value < 0:
            raise ExperimentConfigError(
                f"requests.seed.matrix_seeds[{index}] must be a non-negative integer"
            )
        seeds.append(value)
    if len(set(seeds)) != len(seeds):
        raise ExperimentConfigError("requests.seed.matrix_seeds must be unique")
    return tuple(seeds)


def workload_paths(
    requests: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> tuple[Path, Path]:
    artifact = _mapping(requests.get("workload"), "requests.workload").get("frozen_artifact")
    frozen = _mapping(artifact, "requests.workload.frozen_artifact")
    path = resolve_repo_path(_string(frozen.get("path"), "frozen_artifact.path"), root)
    manifest = resolve_repo_path(
        _string(frozen.get("manifest_path"), "frozen_artifact.manifest_path"),
        root,
    )
    return path, manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ExperimentConfigError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _expect(value: object, expected: object, location: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise ExperimentConfigError(f"{location} must be {expected!r}")


def _validate_requests(requests: Mapping[str, Any], root: Path) -> None:
    matrix_seeds(requests)
    arrival = _mapping(requests.get("arrival"), "requests.arrival")
    for field, expected in (
        ("mode", "causal_trace_replay"),
        ("request_rate", None),
        ("max_concurrency", None),
        ("closed_loop", True),
        ("preserve_agent_dag", True),
        ("preserve_recorded_tool_delay", True),
    ):
        _expect(arrival.get(field), expected, f"requests.arrival.{field}")
    workload = _mapping(requests.get("workload"), "requests.workload")
    for field, expected in (
        ("kind", "real_multi_agent_trace"),
        ("dataset", "semianalysisai/cc-traces-weka-062126"),
        ("token_count_mode", "source_hash_blocks_64"),
        ("derive_prefix_sharing_from_source_hash_ids", True),
    ):
        _expect(workload.get(field), expected, f"requests.workload.{field}")
    source = _mapping(workload.get("source"), "requests.workload.source")
    _expect(source.get("target_tokenizer_equivalence"), False, "requests.workload.source")
    selection = _mapping(workload.get("selection"), "requests.workload.selection")
    _expect(selection.get("kind"), "complete_workflows_frozen_by_id", "selection.kind")
    for field in (
        "no_truncation",
        "no_padding",
        "no_synthesis",
        "no_span_slicing",
        "no_cross_workflow_concatenation",
    ):
        _expect(selection.get(field), True, f"requests.workload.selection.{field}")
    trace_tokens = _mapping(requests.get("trace_token_count"), "requests.trace_token_count")
    _expect(trace_tokens.get("mode"), "source_hash_blocks_64", "trace_token_count.mode")
    _expect(trace_tokens.get("source_block_size_tokens"), 64, "trace_token_count block size")
    _expect(trace_tokens.get("hash_id_scope"), "within_workflow_only", "hash_id_scope")
    _expect(
        trace_tokens.get("target_tokenizer_equivalence"),
        False,
        "trace_token_count.target_tokenizer_equivalence",
    )
    context = _mapping(requests.get("context"), "requests.context")
    _expect(context.get("max_model_len_tokens"), 131_072, "context.max_model_len_tokens")
    _expect(
        context.get("required_observed_context_buckets"),
        list(EXPECTED_CONTEXT_BUCKETS),
        "context.required_observed_context_buckets",
    )
    for field, expected in (
        ("require_real_128k_samples", True),
        ("overflow_policy", "fail"),
        ("truncation_policy", "forbid"),
        ("synthetic_padding", "forbid"),
    ):
        _expect(context.get(field), expected, f"requests.context.{field}")
    frozen = _mapping(workload.get("frozen_artifact"), "requests.workload.frozen_artifact")
    workload_path, manifest_path = workload_paths(requests, root=root)
    if not workload_path.is_file() or not manifest_path.is_file():
        raise ExperimentConfigError("requests frozen workload and manifest must exist")
    declared_sha = _string(frozen.get("sha256"), "frozen_artifact.sha256")
    if _sha256_file(workload_path) != declared_sha:
        raise ExperimentConfigError("requests frozen workload SHA-256 drifted")
    manifest = load_json_object(manifest_path)
    artifact = _mapping(manifest.get("artifact"), "workload manifest.artifact")
    for field in ("sha256", "record_count", "semantic_fingerprint"):
        if frozen.get(field) != artifact.get(field):
            raise ExperimentConfigError(f"requests frozen_artifact.{field} drifted")
    audit = _mapping(
        _mapping(manifest.get("selection"), "workload manifest.selection").get("audit"),
        "workload manifest.selection.audit",
    )
    if selection.get("workflow_ids") != audit.get("workflow_ids"):
        raise ExperimentConfigError("requests workflow_ids differ from the frozen manifest")
    bucket_counts = _mapping(audit.get("context_bucket_counts"), "context_bucket_counts")
    if any(
        type(bucket_counts.get(bucket)) is not int or int(bucket_counts[bucket]) <= 0
        for bucket in EXPECTED_CONTEXT_BUCKETS
    ):
        raise ExperimentConfigError("frozen workload lacks a required context bucket")


def _validate_engine(engine: Mapping[str, Any], root: Path) -> None:
    _expect(engine.get("scope_id"), CURRENT_SCOPE_ID, "engine.scope_id")
    model = _mapping(engine.get("model"), "engine.model")
    for field, expected in (
        ("id", QWEN3_8B_MODEL_ID),
        ("revision", QWEN3_8B_MODEL_REVISION),
        ("config_sha256", QWEN3_8B_CONFIG_SHA256),
        ("dtype", "bf16"),
        ("kv_dtype", "bf16"),
    ):
        _expect(model.get(field), expected, f"engine.model.{field}")
    layout = _mapping(model.get("kv_layout"), "engine.model.kv_layout")
    _expect(layout.get("bytes_per_64_source_tokens"), 9_437_184, "kv_layout byte size")
    for field, fingerprint in (
        ("native_path", NATIVE_LAYOUT_FINGERPRINT),
        ("proposed_yarn_128k_path", YARN_LAYOUT_FINGERPRINT),
    ):
        path = resolve_repo_path(_string(layout.get(field), f"kv_layout.{field}"), root)
        document = load_json_object(path)
        _expect(document.get("fingerprint"), fingerprint, f"kv_layout.{field} fingerprint")
        layout_model = _mapping(document.get("model"), f"kv_layout.{field}.model")
        _expect(layout_model.get("id"), QWEN3_8B_MODEL_ID, f"kv_layout.{field}.model.id")
        _expect(
            layout_model.get("revision"),
            QWEN3_8B_MODEL_REVISION,
            f"kv_layout.{field}.model.revision",
        )
    parallelism = _mapping(engine.get("parallelism"), "engine.parallelism")
    _expect(parallelism.get("data_parallel_size"), LOCKED_DP_COUNT, "data_parallel_size")
    _expect(
        parallelism.get("allowed_data_parallel_sizes"),
        list(ALLOWED_DP_COUNTS),
        "allowed_data_parallel_sizes",
    )
    _expect(parallelism.get("tensor_parallel_size"), 1, "tensor_parallel_size")
    _expect(parallelism.get("pipeline_parallel_size"), 1, "pipeline_parallel_size")
    hardware = _mapping(engine.get("hardware"), "engine.hardware")
    hardware_expectations: tuple[tuple[str, object], ...] = (
        ("gpu_sku", GPU_SKU),
        ("gpu_count", LOCKED_DP_COUNT),
        ("node_count", 1),
        ("topology", TOPOLOGY),
        ("inference_node_id", "node-inference-0"),
        ("physical_hbm_bytes_per_gpu", A100_40GB_HBM_BYTES),
    )
    for hardware_field, expected_value in hardware_expectations:
        _expect(
            hardware.get(hardware_field),
            expected_value,
            f"engine.hardware.{hardware_field}",
        )
    store = _mapping(engine.get("store"), "engine.store")
    _expect(store.get("kind"), "mooncake_dram", "engine.store.kind")
    _expect(store.get("node_count"), 1, "engine.store.node_count")
    _expect(store.get("colocated_with_inference"), True, "engine.store.colocated")
    predictor = _mapping(engine.get("predictor"), "engine.predictor")
    _expect(predictor.get("kind"), "aiconfigurator", "engine.predictor.kind")
    _expect(
        predictor.get("status"),
        "unsupported_for_target_profile",
        "engine.predictor.status",
    )
    _expect(predictor.get("formal_use_allowed"), False, "engine.predictor.formal_use_allowed")
    thresholds = resolve_repo_path(
        _string(predictor.get("residual_thresholds_path"), "residual_thresholds_path"),
        root,
    )
    if not thresholds.is_file():
        raise ExperimentConfigError("engine predictor residual thresholds are missing")
    _expect(
        engine.get("evidence"),
        {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "paper_ready": False,
        },
        "engine.evidence",
    )


def model_parameters_from_engine(engine: Mapping[str, Any]) -> ModelParameters:
    parallelism = _mapping(engine.get("parallelism"), "engine.parallelism")
    hardware = _mapping(engine.get("hardware"), "engine.hardware")
    memory = _mapping(engine.get("memory"), "engine.memory")
    network = _mapping(engine.get("network"), "engine.network")
    control = _mapping(engine.get("control"), "engine.control")
    model = _mapping(engine.get("model"), "engine.model")
    if model.get("id") != QWEN3_8B_MODEL_ID:
        raise ExperimentConfigError(f"engine.model.id must be {QWEN3_8B_MODEL_ID}")
    if model.get("revision") != QWEN3_8B_MODEL_REVISION:
        raise ExperimentConfigError("engine.model.revision must match the locked Qwen3-8B revision")
    if model.get("config_sha256") != QWEN3_8B_CONFIG_SHA256:
        raise ExperimentConfigError("engine.model.config_sha256 does not match the locked model")
    dp_count = _positive_int(
        parallelism.get("data_parallel_size"),
        "parallelism.data_parallel_size",
    )
    if dp_count not in ALLOWED_DP_COUNTS:
        raise ExperimentConfigError(
            f"engine parallelism locks dp_count={LOCKED_DP_COUNT}, got {dp_count}"
        )
    if (
        parallelism.get("tensor_parallel_size") != 1
        or parallelism.get("pipeline_parallel_size") != 1
    ):
        raise ExperimentConfigError("engine parallelism locks TP=1 and PP=1")
    if hardware.get("gpu_sku") != GPU_SKU:
        raise ExperimentConfigError(f"engine.hardware.gpu_sku must be {GPU_SKU}")
    if hardware.get("topology") != TOPOLOGY:
        raise ExperimentConfigError(f"engine.hardware.topology must be {TOPOLOGY}")
    hbm = _positive_int(
        hardware.get("physical_hbm_bytes_per_gpu"),
        "hardware.physical_hbm_bytes_per_gpu",
    )
    if hbm != A100_40GB_HBM_BYTES:
        raise ExperimentConfigError("engine hardware locks modeled A100-40GB HBM")
    transport_name = _string(network.get("store_transport"), "network.store_transport")
    try:
        transport = TransportKind(transport_name)
    except ValueError as error:
        raise ExperimentConfigError(
            f"unsupported store_transport: {transport_name}"
        ) from error
    store = _mapping(engine.get("store"), "engine.store")
    return ModelParameters(
        dp_count=dp_count,
        store_node_count=_positive_int(store.get("node_count"), "store.node_count"),
        physical_hbm_bytes_per_gpu=hbm,
        model_weights_bytes_per_gpu=_positive_int(
            memory.get("model_weights_bytes_per_gpu"),
            "memory.model_weights_bytes_per_gpu",
        ),
        runtime_fixed_bytes_per_gpu=_positive_int(
            memory.get("runtime_fixed_bytes_per_gpu"),
            "memory.runtime_fixed_bytes_per_gpu",
        ),
        peer_budget_bytes_per_gpu=_positive_int(
            memory.get("peer_budget_bytes_per_gpu"),
            "memory.peer_budget_bytes_per_gpu",
        ),
        store_budget_bytes=_positive_int(
            memory.get("store_budget_bytes"),
            "memory.store_budget_bytes",
        ),
        peer_bandwidth_bytes_per_second=_positive_int(
            network.get("peer_bandwidth_bytes_per_second"),
            "network.peer_bandwidth_bytes_per_second",
        ),
        store_bandwidth_bytes_per_second=_positive_int(
            network.get("store_bandwidth_bytes_per_second"),
            "network.store_bandwidth_bytes_per_second",
        ),
        tcp_store_bandwidth_bytes_per_second=_positive_int(
            network.get("tcp_store_bandwidth_bytes_per_second"),
            "network.tcp_store_bandwidth_bytes_per_second",
        ),
        host_staging_bandwidth_bytes_per_second=_positive_int(
            network.get("host_staging_bandwidth_bytes_per_second"),
            "network.host_staging_bandwidth_bytes_per_second",
        ),
        host_staging_capacity_bytes_per_node=_positive_int(
            memory.get("host_staging_capacity_bytes_per_node"),
            "memory.host_staging_capacity_bytes_per_node",
        ),
        store_transport=transport,
        transfer_setup_ns=_positive_int(
            network.get("transfer_setup_ns"),
            "network.transfer_setup_ns",
        ),
        failure_detection_ns=_positive_int(
            control.get("failure_detection_ns"),
            "control.failure_detection_ns",
        ),
        reroute_ns=_non_negative_int(control.get("reroute_ns"), "control.reroute_ns"),
        policy_chunk_tokens=_positive_int(
            control.get("policy_chunk_tokens"),
            "control.policy_chunk_tokens",
        ),
        failure_progress_per_mille=_positive_int(
            control.get("failure_progress_per_mille"),
            "control.failure_progress_per_mille",
        ),
    )


def model_parameters_from_configs(configs: ExperimentLayerConfigs) -> ModelParameters:
    parameters = model_parameters_from_engine(configs.engine)
    control = _mapping(configs.failure.get("control"), "failure.control")
    detection = _positive_int(
        configs.failure.get("detection_delay_ns"),
        "failure.detection_delay_ns",
    )
    reroute = _non_negative_int(
        configs.failure.get("reroute_delay_ns"),
        "failure.reroute_delay_ns",
    )
    progress = _positive_int(
        control.get("progress_per_mille"),
        "failure.control.progress_per_mille",
    )
    if detection != parameters.failure_detection_ns:
        raise ExperimentConfigError("failure.detection_delay_ns must match engine.control")
    if reroute != parameters.reroute_ns:
        raise ExperimentConfigError("failure.reroute_delay_ns must match engine.control")
    if progress != parameters.failure_progress_per_mille:
        raise ExperimentConfigError(
            "failure.control.progress_per_mille must match engine.control"
        )
    return parameters


def snapshot_experiment_configs(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    for name in LAYER_FILES:
        source = source_dir / name
        if source.is_symlink() or not source.is_file():
            raise ExperimentConfigError(f"cannot snapshot missing {source}")
        shutil.copy2(source, destination_dir / name)


def _validate_failure(failure: Mapping[str, Any]) -> None:
    _expect(failure.get("enabled"), True, "failure.enabled")
    allowed = failure.get("allowed_types")
    if allowed != [ALLOWED_FAILURE_TYPE]:
        raise ExperimentConfigError("failure.allowed_types must be exactly [GPU_FAILURE]")
    if failure.get("type") != ALLOWED_FAILURE_TYPE:
        raise ExperimentConfigError("this experiment release only supports GPU_FAILURE")
    if failure.get("semantics") != "fail_stop_hbm_lost":
        raise ExperimentConfigError("GPU_FAILURE must be fail_stop_hbm_lost")
    repair = _mapping(failure.get("repair"), "failure.repair")
    if repair.get("enabled") is not False:
        raise ExperimentConfigError("first-release GPU_FAILURE does not repair")
    _expect(repair.get("repair_after_s"), None, "failure.repair.repair_after_s")
    control = _mapping(failure.get("control"), "failure.control")
    if control.get("mode") != "focus_span_compute_progress":
        raise ExperimentConfigError(
            "failure control must be focus_span_compute_progress"
        )
    _positive_int(control.get("progress_per_mille"), "failure.control.progress_per_mille")
    _expect(
        control.get("selection_scope"),
        "same_focus_span_and_compute_progress_in_every_system",
        "failure.control.selection_scope",
    )
    frequency = _mapping(control.get("frequency"), "failure.control.frequency")
    _expect(
        frequency.get("kind"),
        "one_gpu_failure_per_gpu_failure_cell",
        "failure.control.frequency.kind",
    )
    _expect(
        frequency.get("scenarios"),
        ["no_failure", "gpu_failure"],
        "failure.control.frequency.scenarios",
    )
    target = _mapping(failure.get("target"), "failure.target")
    _expect(target.get("resolution"), "deterministic_focus_span_gpu", "failure.target")
    _expect(target.get("topology"), TOPOLOGY, "failure.target.topology")
    _expect(target.get("gpu_sku"), GPU_SKU, "failure.target.gpu_sku")
    effects = _mapping(failure.get("effects"), "failure.effects")
    for field in (
        "compute_unavailable",
        "copy_engines_unavailable",
        "hbm_lost",
        "committed_store_dram_remains_usable",
    ):
        _expect(effects.get(field), True, f"failure.effects.{field}")


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExperimentConfigError(f"{location} must be an object")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExperimentConfigError(f"{location} must be a non-empty string")
    return value


def _positive_int(value: object, location: str) -> int:
    if type(value) is not int or value <= 0:
        raise ExperimentConfigError(f"{location} must be a positive integer")
    return value


def _non_negative_int(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise ExperimentConfigError(f"{location} must be a non-negative integer")
    return value
