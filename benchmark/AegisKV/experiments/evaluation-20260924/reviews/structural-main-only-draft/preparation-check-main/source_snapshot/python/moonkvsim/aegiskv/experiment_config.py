"""Load the three-layer AegisKV experiment configs.

``requests.json``, ``failure.json``, and ``engine.json`` live under
``benchmark/AegisKV/experiments/configs``.  They are the paper-facing inputs
for the AegisKV study; the MoonKVSim library maps them onto
``ModelParameters`` and the frozen workload paths.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.experiment import (
    A100_40GB_HBM_BYTES,
    ALLOWED_DP_COUNTS,
    GPU_SKU,
    LOCKED_DP_COUNT,
    PEER_HBM_ALPHA_MAX,
    PEER_HBM_ALPHA_MIN,
    QWEN3_8B_CONFIG_SHA256,
    QWEN3_8B_MODEL_ID,
    QWEN3_8B_MODEL_REVISION,
    QWEN3_8B_MODEL_WEIGHTS_BYTES,
    ModelParameters,
)
from moonkvsim.config import SchemaValidationError, validate_instance
from moonkvsim.store.transfer_engine import TransportKind

REQUESTS_SCHEMA: Final = "moonkvsim.aegiskv.requests.v2"
FAILURE_SCHEMA: Final = "moonkvsim.aegiskv.failure.v5"
ENGINE_SCHEMA: Final = "moonkvsim.aegiskv.engine.v2"
LAYER_FILES: Final = ("requests.json", "failure.json", "engine.json")
ALLOWED_CONFIG_ENTRIES: Final = (*LAYER_FILES, "requests.md", "engine", "failure")
ALLOWED_FAILURE_TYPE: Final = "GPU_FAILURE"
FANOUTQA_STATUS: Final = "selected_public_dataset_pending_workload_build"
FANOUTQA_READY_STATUS: Final = "ready_frozen_fanoutqa_workload"
FANOUTQA_DATASET_NAME: Final = "FanOutQA"
FANOUTQA_SPLIT: Final = "dev"
FANOUTQA_SOURCE_REVISION: Final = "989f4c40d9deea1ecb0897d7a17a9c0fe20d5c33"
FANOUTQA_SOURCE_SHA256: Final = (
    "b62a9797732c716e6b17ba4086f277d154d747ce2fa01614cb76a3372e7fb88c"
)
FANOUTQA_TASK_COUNT: Final = 310
FANOUTQA_MINIMUM_TASK_COUNT_FOR_ECDF: Final = 160
FANOUTQA_OVERFLOW_POLICY: Final = "split_evidence_if_below_minimum"
NS_PER_MINUTE: Final = 60_000_000_000
YARN_LAYOUT_FINGERPRINT: Final = (
    "42cff103674b5a857c1e6308247fbd006bf80ac444efd50a377c40ab4696a29e"
)
ENGINE_STORE_CAPACITY_BYTES: Final = 1_000_000_000_000
ENGINE_PCIE_EFFECTIVE_BANDWIDTH_BYTES_PER_SECOND: Final = 25_000_000_000


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
    extra = sorted(
        path.name for path in directory.iterdir() if path.name not in ALLOWED_CONFIG_ENTRIES
    )
    if extra:
        raise ExperimentConfigError(
            "experiments/configs may only contain the three JSON layers and audited docs; "
            f"unexpected files: {extra}"
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
    _validate_requests(requests)
    try:
        validate_instance(failure, FAILURE_SCHEMA)
    except SchemaValidationError as error:
        raise ExperimentConfigError(str(error)) from error
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
    values = requests.get("seeds")
    if not isinstance(values, list) or not values:
        raise ExperimentConfigError("requests.seeds must be a non-empty array")
    seeds: list[int] = []
    for index, value in enumerate(values):
        if type(value) is not int or value < 0:
            raise ExperimentConfigError(
                f"requests.seeds[{index}] must be a non-negative integer"
            )
        seeds.append(value)
    if len(set(seeds)) != len(seeds):
        raise ExperimentConfigError("requests.seed.matrix_seeds must be unique")
    return tuple(seeds)


def workflow_concurrency(requests: Mapping[str, Any]) -> int:
    """Return the closed-loop number of simultaneously admitted workflows."""

    replay = _mapping(requests.get("replay"), "requests.replay")
    return _positive_int(
        replay.get("workflow_concurrency"),
        "requests.replay.workflow_concurrency",
    )


def workload_paths(
    requests: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> tuple[Path, Path]:
    if requests.get("status") == FANOUTQA_STATUS:
        raise ExperimentConfigError(
            "FanOutQA source is public, but its derived Qwen3-8B workload is not frozen; "
            "experiment run blocked"
        )
    artifact = _mapping(requests.get("dataset"), "requests.dataset").get("frozen_artifact")
    frozen = _mapping(artifact, "requests.dataset.frozen_artifact")
    path = resolve_repo_path(_string(frozen.get("path"), "frozen_artifact.path"), root)
    manifest = resolve_repo_path(
        _string(frozen.get("manifest_path"), "frozen_artifact.manifest_path"),
        root,
    )
    return path, manifest


def _expect(value: object, expected: object, location: str) -> None:
    if value != expected or type(value) is not type(expected):
        raise ExperimentConfigError(f"{location} must be {expected!r}")


def _validate_requests(requests: Mapping[str, Any]) -> None:
    _expect_keys(
        requests,
        {"schema", "status", "seeds", "dataset", "replay", "context"},
        "requests",
    )
    matrix_seeds(requests)
    workflow_concurrency(requests)
    status = requests.get("status")
    if status not in {FANOUTQA_STATUS, FANOUTQA_READY_STATUS}:
        raise ExperimentConfigError(
            f"requests.status must be {FANOUTQA_STATUS!r} or "
            f"{FANOUTQA_READY_STATUS!r}"
        )
    dataset = _mapping(requests.get("dataset"), "requests.dataset")
    dataset_fields = {"name", "split", "source_revision", "source_sha256"}
    if status == FANOUTQA_READY_STATUS:
        dataset_fields.add("frozen_artifact")
    _expect_keys(dataset, dataset_fields, "requests.dataset")
    for field, expected in (
        ("name", FANOUTQA_DATASET_NAME),
        ("split", FANOUTQA_SPLIT),
        ("source_revision", FANOUTQA_SOURCE_REVISION),
        ("source_sha256", FANOUTQA_SOURCE_SHA256),
    ):
        _expect(dataset.get(field), expected, f"requests.dataset.{field}")
    frozen_task_count: int | None = None
    if status == FANOUTQA_STATUS:
        if "frozen_artifact" in dataset:
            raise ExperimentConfigError(
                "pending FanOutQA requests must not declare a frozen_artifact"
            )
    else:
        frozen = _mapping(
            dataset.get("frozen_artifact"),
            "requests.dataset.frozen_artifact",
        )
        for field in ("path", "manifest_path", "normalizer_version"):
            _string(frozen.get(field), f"requests.dataset.frozen_artifact.{field}")
        for field in ("sha256", "manifest_sha256"):
            value = _string(frozen.get(field), f"requests.dataset.frozen_artifact.{field}")
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ExperimentConfigError(
                    f"requests.dataset.frozen_artifact.{field} must be lowercase SHA-256"
                )
        frozen_task_count = _positive_int(
            frozen.get("task_count"),
            "requests.dataset.frozen_artifact.task_count",
        )
        if frozen_task_count > FANOUTQA_TASK_COUNT:
            raise ExperimentConfigError(
                "frozen FanOutQA task_count cannot exceed the dev split"
            )
    replay = _mapping(requests.get("replay"), "requests.replay")
    _expect_keys(replay, {"workflow_concurrency"}, "requests.replay")
    context = _mapping(requests.get("context"), "requests.context")
    _expect_keys(
        context,
        {
            "max_model_len_tokens",
            "minimum_task_count_for_ecdf",
            "overflow_policy",
        },
        "requests.context",
    )
    _expect(context.get("max_model_len_tokens"), 131_072, "context.max_model_len_tokens")
    _expect(
        context.get("overflow_policy"),
        FANOUTQA_OVERFLOW_POLICY,
        "context.overflow_policy",
    )
    minimum_tasks = _positive_int(
        context.get("minimum_task_count_for_ecdf"),
        "requests.context.minimum_task_count_for_ecdf",
    )
    if minimum_tasks < FANOUTQA_MINIMUM_TASK_COUNT_FOR_ECDF:
        raise ExperimentConfigError(
            "requests.context.minimum_task_count_for_ecdf must be at least "
            f"{FANOUTQA_MINIMUM_TASK_COUNT_FOR_ECDF}"
        )
    if minimum_tasks > FANOUTQA_TASK_COUNT:
        raise ExperimentConfigError(
            "requests.context.minimum_task_count_for_ecdf cannot exceed the FanOutQA dev split"
        )
    if frozen_task_count is not None and frozen_task_count < minimum_tasks:
        raise ExperimentConfigError(
            "requests.dataset.frozen_artifact.task_count is below "
            "requests.context.minimum_task_count_for_ecdf"
        )


def _validate_engine(engine: Mapping[str, Any], root: Path) -> None:
    _expect_keys(
        engine,
        {
            "schema",
            "model",
            "parallelism",
            "hardware",
            "memory",
            "store",
            "network",
            "control",
        },
        "engine",
    )
    model = _mapping(engine.get("model"), "engine.model")
    _expect_keys(model, {"id", "revision", "kv_layout_path"}, "engine.model")
    for field, expected in (
        ("id", QWEN3_8B_MODEL_ID),
        ("revision", QWEN3_8B_MODEL_REVISION),
    ):
        _expect(model.get(field), expected, f"engine.model.{field}")
    layout_path = resolve_repo_path(
        _string(model.get("kv_layout_path"), "engine.model.kv_layout_path"),
        root,
    )
    layout = load_json_object(layout_path)
    _expect(layout.get("fingerprint"), YARN_LAYOUT_FINGERPRINT, "kv_layout fingerprint")
    layout_model = _mapping(layout.get("model"), "kv_layout.model")
    for field, expected in (
        ("id", QWEN3_8B_MODEL_ID),
        ("revision", QWEN3_8B_MODEL_REVISION),
        ("config_sha256", QWEN3_8B_CONFIG_SHA256),
    ):
        _expect(layout_model.get(field), expected, f"kv_layout.model.{field}")
    _expect(
        layout_model.get("weights_bytes"),
        QWEN3_8B_MODEL_WEIGHTS_BYTES,
        "kv_layout.model.weights_bytes",
    )
    stage_layouts = layout.get("stage_rank_layouts")
    if not isinstance(stage_layouts, list) or len(stage_layouts) != 1:
        raise ExperimentConfigError("kv_layout.stage_rank_layouts must contain TP1/PP1")
    block = _mapping(stage_layouts[0], "kv_layout.stage_rank_layouts[0]").get("block")
    block = _mapping(block, "kv_layout.stage_rank_layouts[0].block")
    block_tokens = _positive_int(block.get("block_size_tokens"), "kv_layout block tokens")
    block_bytes = _positive_int(block.get("allocated_bytes"), "kv_layout block bytes")
    if 64 % block_tokens or block_bytes * (64 // block_tokens) != 9_437_184:
        raise ExperimentConfigError("kv_layout must allocate 9,437,184 bytes per 64 tokens")

    parallelism = _mapping(engine.get("parallelism"), "engine.parallelism")
    _expect_keys(
        parallelism,
        {"data_parallel_size", "tensor_parallel_size", "pipeline_parallel_size"},
        "engine.parallelism",
    )
    _expect(parallelism.get("data_parallel_size"), LOCKED_DP_COUNT, "data_parallel_size")
    _expect(parallelism.get("tensor_parallel_size"), 1, "tensor_parallel_size")
    _expect(parallelism.get("pipeline_parallel_size"), 1, "pipeline_parallel_size")

    hardware = _mapping(engine.get("hardware"), "engine.hardware")
    _expect_keys(
        hardware,
        {"gpu_sku", "gpu_count", "node_count", "physical_hbm_bytes_per_gpu"},
        "engine.hardware",
    )
    hardware_expectations: tuple[tuple[str, object], ...] = (
        ("gpu_sku", GPU_SKU),
        ("gpu_count", LOCKED_DP_COUNT),
        ("node_count", 1),
        ("physical_hbm_bytes_per_gpu", A100_40GB_HBM_BYTES),
    )
    for hardware_field, expected_value in hardware_expectations:
        _expect(
            hardware.get(hardware_field),
            expected_value,
            f"engine.hardware.{hardware_field}",
        )

    memory = _mapping(engine.get("memory"), "engine.memory")
    _expect_keys(memory, {"peer_hbm_alpha"}, "engine.memory")
    _peer_hbm_alpha(memory.get("peer_hbm_alpha"), "engine.memory.peer_hbm_alpha")

    store = _mapping(engine.get("store"), "engine.store")
    _expect_keys(
        store,
        {"kind", "capacity_bytes", "colocated_with_inference"},
        "engine.store",
    )
    _expect(store.get("kind"), "mooncake_dram", "engine.store.kind")
    _expect(
        store.get("capacity_bytes"),
        ENGINE_STORE_CAPACITY_BYTES,
        "engine.store.capacity_bytes",
    )
    _expect(store.get("colocated_with_inference"), True, "engine.store.colocated")

    network = _mapping(engine.get("network"), "engine.network")
    _expect_keys(
        network,
        {"transport", "effective_bandwidth_bytes_per_second", "transfer_setup_ns"},
        "engine.network",
    )
    _expect(network.get("transport"), "PCIE", "engine.network.transport")
    _expect(
        network.get("effective_bandwidth_bytes_per_second"),
        ENGINE_PCIE_EFFECTIVE_BANDWIDTH_BYTES_PER_SECOND,
        "engine.network.effective_bandwidth_bytes_per_second",
    )
    _positive_int(network.get("transfer_setup_ns"), "engine.network.transfer_setup_ns")

    control = _mapping(engine.get("control"), "engine.control")
    _expect_keys(control, {"reroute_ns", "policy_chunk_tokens"} |
                 ({"runtime_semantics"} if "runtime_semantics" in control else set()),
                 "engine.control")
    _non_negative_int(control.get("reroute_ns"), "engine.control.reroute_ns")
    _positive_int(
        control.get("policy_chunk_tokens"),
        "engine.control.policy_chunk_tokens",
    )


def model_parameters_from_engine(
    engine: Mapping[str, Any],
    *,
    failure_progress_per_mille: int,
    gpu_recovery_time_ns: int,
) -> ModelParameters:
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
    if hardware.get("gpu_count") != dp_count:
        raise ExperimentConfigError("engine.hardware.gpu_count must equal DP size for TP=PP=1")
    if hardware.get("node_count") != 1:
        raise ExperimentConfigError("engine.hardware.node_count must be 1 for local PCIe")
    hbm = _positive_int(
        hardware.get("physical_hbm_bytes_per_gpu"),
        "hardware.physical_hbm_bytes_per_gpu",
    )
    if hbm != A100_40GB_HBM_BYTES:
        raise ExperimentConfigError("engine hardware locks modeled A100-40GB HBM")
    transport_name = _string(network.get("transport"), "network.transport")
    try:
        transport = TransportKind(transport_name)
    except ValueError as error:
        raise ExperimentConfigError(
            f"unsupported transport: {transport_name}"
        ) from error
    store = _mapping(engine.get("store"), "engine.store")
    if store.get("kind") != "mooncake_dram" or store.get("colocated_with_inference") is not True:
        raise ExperimentConfigError("engine Store must be colocated Mooncake DRAM")
    pcie_bandwidth = _positive_int(
        network.get("effective_bandwidth_bytes_per_second"),
        "network.effective_bandwidth_bytes_per_second",
    )
    return ModelParameters(
        runtime_semantics=str(control.get("runtime_semantics", "legacy_v3")),
        dp_count=dp_count,
        store_node_count=1,
        physical_hbm_bytes_per_gpu=hbm,
        peer_hbm_alpha=_peer_hbm_alpha(
            memory.get("peer_hbm_alpha"),
            "memory.peer_hbm_alpha",
        ),
        store_budget_bytes=_positive_int(
            store.get("capacity_bytes"),
            "store.capacity_bytes",
        ),
        peer_bandwidth_bytes_per_second=pcie_bandwidth,
        store_bandwidth_bytes_per_second=pcie_bandwidth,
        store_transport=transport,
        transfer_setup_ns=_positive_int(
            network.get("transfer_setup_ns"),
            "network.transfer_setup_ns",
        ),
        failure_detection_ns=0,
        reroute_ns=_non_negative_int(control.get("reroute_ns"), "control.reroute_ns"),
        policy_chunk_tokens=_positive_int(
            control.get("policy_chunk_tokens"),
            "control.policy_chunk_tokens",
        ),
        failure_progress_per_mille=_positive_int(
            failure_progress_per_mille,
            "failure.injection_progress_percent",
        ),
        gpu_recovery_time_ns=_positive_int(
            gpu_recovery_time_ns,
            "failure.gpu_recovery_time_minutes",
        ),
    )


def model_parameters_from_configs(configs: ExperimentLayerConfigs) -> ModelParameters:
    progress_percent = _positive_int(
        configs.failure.get("injection_progress_percent"),
        "failure.injection_progress_percent",
    )
    recovery_minutes = gpu_recovery_time_minutes(configs.failure)
    return model_parameters_from_engine(
        configs.engine,
        failure_progress_per_mille=progress_percent * 10,
        gpu_recovery_time_ns=recovery_minutes * NS_PER_MINUTE,
    )


def gpu_recovery_time_minutes(failure: Mapping[str, Any]) -> int:
    """Return fixed failure-to-reusable time for the failed GPU capacity."""

    return _positive_int(
        failure.get("gpu_recovery_time_minutes"),
        "failure.gpu_recovery_time_minutes",
    )


def failure_count(failure: Mapping[str, Any]) -> int:
    """Return the number of GPU failures in each failure-scenario workload run."""

    return _positive_int(
        failure.get("failure_count"),
        "failure.failure_count",
    )


def snapshot_experiment_configs(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    for name in LAYER_FILES:
        source = source_dir / name
        if source.is_symlink() or not source.is_file():
            raise ExperimentConfigError(f"cannot snapshot missing {source}")
        shutil.copy2(source, destination_dir / name)


def _validate_failure(failure: Mapping[str, Any]) -> None:
    if failure.get("type") != ALLOWED_FAILURE_TYPE:
        raise ExperimentConfigError("this experiment release only supports GPU_FAILURE")
    progress_percent = _positive_int(
        failure.get("injection_progress_percent"),
        "failure.injection_progress_percent",
    )
    if progress_percent >= 100:
        raise ExperimentConfigError("failure.injection_progress_percent must be between 1 and 99")
    failure_count(failure)
    gpu_recovery_time_minutes(failure)


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExperimentConfigError(f"{location} must be an object")
    return value


def _expect_keys(
    value: Mapping[str, Any],
    expected: set[str],
    location: str,
) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ExperimentConfigError(
            f"{location} fields must be exactly {sorted(expected)}; "
            f"missing={missing}, extra={extra}"
        )


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


def _peer_hbm_alpha(value: object, location: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentConfigError(f"{location} must be a JSON number in [0, 0.5]")
    try:
        alpha = Decimal(str(value))
    except InvalidOperation as error:
        raise ExperimentConfigError(
            f"{location} must be a JSON number in [0, 0.5]"
        ) from error
    if not alpha.is_finite() or not PEER_HBM_ALPHA_MIN <= alpha <= PEER_HBM_ALPHA_MAX:
        raise ExperimentConfigError(f"{location} must be in [0, 0.5]")
    return alpha
