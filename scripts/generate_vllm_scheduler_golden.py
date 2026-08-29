#!/usr/bin/env python3
"""Capture or check the pinned-vLLM CPU scheduler/block semantic golden.

This script must run with the separately installed vLLM interpreter recorded
below.  Before importing vLLM it hashes every installed semantic file recorded
in ``reference/source-lock.json`` and every locked Qwen3-8B metadata/tokenizer
file.  The scheduler construction is the minimal ordinary decoder-only CPU
helper from pinned ``tests/v1/core/utils.py`` adapted to the locked Qwen model
snapshot with ``skip_tokenizer_init=True``.

The result is E2 CPU semantics only: no model forward, CUDA allocation,
performance timing, calibration, or physical validation occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EXPECTED_INTERPRETER = Path("/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python")
EXPECTED_COMMIT = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
EXPECTED_VERSION = "1.2.2+aegiskv.sm89"
EXPECTED_MODEL_ID = "Qwen/Qwen3-8B"
EXPECTED_MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
SCHEMA = "moonkvsim.vllm-scheduler-golden.v1"
EVIDENCE_CLASS = "E2_cpu_semantics_only"
CLAIM_EXCLUSIONS = (
    "cuda",
    "model_execution",
    "performance",
    "physical_validation",
    "timing_calibration",
)
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
GENERATOR_RELATIVE_PATH = Path("scripts/generate_vllm_scheduler_golden.py")
DEFAULT_OUTPUT = Path("reference/goldens/vllm-v1.2.2-qwen3-8b-scheduler.json")
CONNECTOR_TRANSITIVE_SHA256 = {
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/data.py": (
        "acab2e80024c86d0f9a666e1125a7834559d5bba8bd1ac0848097a9843d5dc27"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py": (
        "c8bf83fb0a11666cd4936e0fdb3897af5ced5ac34f81d49087c8eb80afcff2ef"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/worker.py": (
        "dd5765efc936adac88a942773a2ed01fbe0652965906fa2bcedc4bca91ef4128"
    ),
}


class CaptureError(RuntimeError):
    """Raised on any source, environment, capture, or artifact drift."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the existing output is byte-identical to a fresh capture",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output when capturing (never implied by default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        pre_import = _verify_pre_import_environment(root)
        scenarios, runtime, connector_lifecycle = _capture_with_verified_vllm(pre_import)
        provenance = dict(pre_import["provenance"])
        provenance.update(runtime)
        document: dict[str, object] = {
            "schema": SCHEMA,
            "evidence_class": EVIDENCE_CLASS,
            "claim_exclusions": list(CLAIM_EXCLUSIONS),
            "provenance": provenance,
            "scenarios": scenarios,
            "connector_lifecycle": connector_lifecycle,
        }
        expected = _canonical_json_bytes(document)
        if args.check:
            if args.overwrite:
                raise CaptureError("--check and --overwrite are mutually exclusive")
            try:
                actual = output.read_bytes()
            except OSError as error:
                raise CaptureError(f"cannot read golden for --check: {error}") from error
            if actual != expected:
                raise CaptureError(f"{output} is not byte-identical to a fresh capture")
            status = "checked"
        else:
            if output.exists() and not args.overwrite:
                raise CaptureError(f"refusing to overwrite existing golden: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(expected)
            status = "generated"
    except (CaptureError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "evidence_class": EVIDENCE_CLASS,
                "output": str(output),
                "scenario_count": len(scenarios),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0


def _verify_pre_import_environment(root: Path) -> dict[str, Any]:
    if Path(sys.executable).resolve() != EXPECTED_INTERPRETER.resolve():
        raise CaptureError(
            "wrong interpreter; run with "
            f"{EXPECTED_INTERPRETER}, got {Path(sys.executable).resolve()}"
        )
    source_lock_path = root / SOURCE_LOCK_RELATIVE_PATH
    source_lock = _load_json_object(source_lock_path)
    repositories = _mapping(source_lock.get("repositories"), "repositories")
    vllm_lock = _mapping(repositories.get("vllm"), "repositories.vllm")
    if vllm_lock.get("commit") != EXPECTED_COMMIT:
        raise CaptureError("source lock vLLM commit drift")
    if vllm_lock.get("observed_generated_version") != EXPECTED_VERSION:
        raise CaptureError("source lock vLLM generated version drift")

    installed_root = Path(sysconfig.get_paths()["purelib"]).resolve()
    installed_vllm_root = (installed_root / "vllm").resolve()
    if not installed_vllm_root.is_dir():
        raise CaptureError(f"installed vLLM package is missing: {installed_vllm_root}")
    installed_hashes: dict[str, str] = {}
    locked_files = _list(vllm_lock.get("files"), "repositories.vllm.files")
    for raw_record in locked_files:
        record = _mapping(raw_record, "vLLM file record")
        relative = _relative_path(record.get("path"), "vLLM file path")
        if relative.parts[0] != "vllm":
            raise CaptureError(f"vLLM source-lock path escapes package: {relative}")
        expected_sha = _sha_string(record.get("sha256"), f"SHA for {relative}")
        installed_path = _inside(installed_root, relative)
        actual_sha = _sha256_file(installed_path)
        if actual_sha != expected_sha:
            raise CaptureError(
                f"installed vLLM semantic file hash drift: {relative}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        installed_hashes[relative.as_posix()] = actual_sha

    required_paths = {
        "vllm/v1/request.py",
        "vllm/v1/core/sched/scheduler.py",
        "vllm/v1/core/kv_cache_manager.py",
        "vllm/v1/core/block_pool.py",
        "vllm/v1/kv_cache_interface.py",
    }
    if not required_paths.issubset(installed_hashes):
        missing = sorted(required_paths.difference(installed_hashes))
        raise CaptureError(f"source lock omits required scheduler files: {missing}")

    connector_transitive_hashes: dict[str, str] = {}
    for relative_text, expected_sha in CONNECTOR_TRANSITIVE_SHA256.items():
        relative = Path(relative_text)
        actual_sha = _sha256_file(_inside(installed_root, relative))
        if actual_sha != expected_sha:
            raise CaptureError(
                f"installed Store connector transitive file hash drift: {relative}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        connector_transitive_hashes[relative_text] = actual_sha

    generated_files = _list(vllm_lock.get("generated_files"), "generated_files")
    version_record = next(
        (
            _mapping(item, "generated vLLM file")
            for item in generated_files
            if _mapping(item, "generated vLLM file").get("path") == "vllm/_version.py"
        ),
        None,
    )
    if version_record is None:
        raise CaptureError("source lock does not bind vllm/_version.py")
    version_sha = _sha_string(version_record.get("sha256"), "vllm/_version.py SHA")
    if _sha256_file(installed_root / "vllm/_version.py") != version_sha:
        raise CaptureError("installed vLLM generated version file hash drift")

    model_lock = _mapping(source_lock.get("model_tokenizer"), "model_tokenizer")
    if model_lock.get("model_id") != EXPECTED_MODEL_ID:
        raise CaptureError("source lock model ID drift")
    if model_lock.get("revision") != EXPECTED_MODEL_REVISION:
        raise CaptureError("source lock model revision drift")
    snapshot_path = Path(_string(model_lock.get("snapshot_path"), "snapshot_path")).resolve()
    if snapshot_path.name != EXPECTED_MODEL_REVISION or not snapshot_path.is_dir():
        raise CaptureError("locked Qwen snapshot path/revision is unavailable")
    model_hashes: dict[str, str] = {}
    for raw_record in _list(model_lock.get("files"), "model_tokenizer.files"):
        record = _mapping(raw_record, "model file record")
        relative = _relative_path(record.get("path"), "model file path")
        expected_sha = _sha_string(record.get("sha256"), f"model SHA for {relative}")
        # Hugging Face snapshots intentionally use symlinks into the cache's
        # content-addressed blob store. The relative path is already checked
        # against absolute/``..`` escape and the target bytes are hash locked.
        actual_sha = _sha256_file(snapshot_path / relative)
        if actual_sha != expected_sha:
            raise CaptureError(f"locked Qwen file hash drift: {relative}")
        model_hashes[relative.as_posix()] = actual_sha

    # These variables are set before the first vLLM/transformers import.  The
    # capture must use only the already hash-verified snapshot.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    # Pin vLLM's first-block NONE_HASH instead of accepting its random fallback.
    os.environ["PYTHONHASHSEED"] = "0"
    source_checkout = Path(_string(vllm_lock.get("repository"), "vLLM repository")).resolve()
    for entry in sys.path:
        if not entry:
            continue
        try:
            resolved_entry = Path(entry).resolve()
        except OSError:
            continue
        if resolved_entry == source_checkout or source_checkout in resolved_entry.parents:
            raise CaptureError("dirty/source vLLM checkout is present on sys.path")

    source_lock_sha = _sha256_file(source_lock_path)
    generator_path = root / GENERATOR_RELATIVE_PATH
    return {
        "installed_root": installed_root,
        "installed_vllm_root": installed_vllm_root,
        "snapshot_path": snapshot_path,
        "provenance": {
            "interpreter": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "vllm_source_commit": EXPECTED_COMMIT,
            "installed_vllm_root": str(installed_vllm_root),
            "installed_vllm_file_sha256": installed_hashes,
            "installed_store_connector_transitive_sha256": (connector_transitive_hashes),
            "installed_vllm_version_file_sha256": version_sha,
            "source_lock": {
                "path": SOURCE_LOCK_RELATIVE_PATH.as_posix(),
                "sha256": source_lock_sha,
            },
            "generator": {
                "path": GENERATOR_RELATIVE_PATH.as_posix(),
                "sha256": _sha256_file(generator_path),
                "helper_source": (
                    "pinned tests/v1/core/utils.py minimal create_scheduler/create_requests "
                    "construction"
                ),
            },
            "model": {
                "model_id": EXPECTED_MODEL_ID,
                "revision": EXPECTED_MODEL_REVISION,
                "snapshot_path": str(snapshot_path),
                "file_sha256": model_hashes,
                "skip_tokenizer_init": True,
                "model_forward_executed": False,
            },
        },
    }


def _capture_with_verified_vllm(
    verified: Mapping[str, Any],
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    # All installed semantic files and model metadata have been verified above.
    import torch
    import vllm
    from vllm.config import (
        CacheConfig,
        ModelConfig,
        ParallelConfig,
        SchedulerConfig,
        VllmConfig,
    )
    from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.connector import (
        MooncakeStoreConnector,
    )
    from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.data import (
        MooncakeStoreConnectorMetadata,
    )
    from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.scheduler import (
        MooncakeStoreScheduler,
    )
    from vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.worker import (
        MooncakeStoreWorker,
    )
    from vllm.sampling_params import SamplingParams
    from vllm.utils.hashing import sha256
    from vllm.v1.core.kv_cache_utils import (
        get_request_block_hasher,
        init_none_hash,
    )
    from vllm.v1.core.sched.output import NewRequestData, SchedulerOutput
    from vllm.v1.core.sched.scheduler import Scheduler
    from vllm.v1.kv_cache_interface import (
        FullAttentionSpec,
        KVCacheConfig,
        KVCacheGroupSpec,
    )
    from vllm.v1.outputs import ModelRunnerOutput
    from vllm.v1.request import Request, RequestStatus
    from vllm.v1.structured_output import StructuredOutputManager

    if vllm.__version__ != EXPECTED_VERSION:
        raise CaptureError(
            f"installed vLLM version drift: expected {EXPECTED_VERSION}, got {vllm.__version__}"
        )
    installed_root = Path(verified["installed_root"])
    expected_modules = {
        "vllm.v1.request": "vllm/v1/request.py",
        "vllm.v1.core.sched.scheduler": "vllm/v1/core/sched/scheduler.py",
        "vllm.v1.core.kv_cache_manager": "vllm/v1/core/kv_cache_manager.py",
        "vllm.v1.core.block_pool": "vllm/v1/core/block_pool.py",
        "vllm.v1.kv_cache_interface": "vllm/v1/kv_cache_interface.py",
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.connector": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/connector.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.data": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/data.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.scheduler": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.worker": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/worker.py"
        ),
    }
    imported_paths: dict[str, str] = {}
    for module_name, relative in expected_modules.items():
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise CaptureError(f"imported module has no file: {module_name}")
        actual = Path(module_file).resolve()
        expected = (installed_root / relative).resolve()
        if actual != expected:
            raise CaptureError(
                f"{module_name} imported outside verified installation: {actual} != {expected}"
            )
        imported_paths[module_name] = str(actual)

    snapshot_path = str(verified["snapshot_path"])
    init_none_hash(sha256)

    def make_scheduler(
        *, num_blocks: int, token_budget: int, enable_prefix_caching: bool = False
    ) -> Any:
        model_config = ModelConfig(
            model=snapshot_path,
            trust_remote_code=False,
            dtype="bfloat16",
            seed=42,
            skip_tokenizer_init=True,
            max_model_len=32,
        )
        scheduler_config = SchedulerConfig(
            max_num_seqs=2,
            max_num_batched_tokens=token_budget,
            max_model_len=32,
            enable_chunked_prefill=True,
            async_scheduling=False,
            is_encoder_decoder=model_config.is_encoder_decoder,
        )
        cache_config = CacheConfig(
            block_size=4,
            gpu_memory_utilization=0.9,
            cache_dtype="auto",
            enable_prefix_caching=enable_prefix_caching,
        )
        cache_config.num_gpu_blocks = num_blocks
        vllm_config = VllmConfig(
            scheduler_config=scheduler_config,
            model_config=model_config,
            cache_config=cache_config,
            parallel_config=ParallelConfig(),
        )
        kv_cache_config = KVCacheConfig(
            num_blocks=num_blocks,
            kv_cache_tensors=[],
            kv_cache_groups=[
                KVCacheGroupSpec(
                    ["layer"],
                    FullAttentionSpec(
                        block_size=4,
                        num_kv_heads=1,
                        head_size=1,
                        dtype=torch.float32,
                    ),
                )
            ],
        )
        return Scheduler(
            vllm_config=vllm_config,
            kv_cache_config=kv_cache_config,
            block_size=4,
            log_stats=True,
            structured_output_manager=StructuredOutputManager(vllm_config),
        )

    def make_request(
        request_id: str,
        prompt_tokens: int,
        *,
        token_ids: list[int] | None = None,
    ) -> Any:
        sampling_params = SamplingParams(max_tokens=8)
        sampling_params.update_from_generation_config({}, 50256)
        return Request(
            request_id=request_id,
            prompt_token_ids=token_ids or [1] * prompt_tokens,
            sampling_params=sampling_params,
            pooling_params=None,
            block_hasher=get_request_block_hasher(4, sha256),
        )

    def model_output(sampled_token_ids: Mapping[str, list[int]]) -> Any:
        request_ids = list(sampled_token_ids)
        return ModelRunnerOutput(
            req_ids=request_ids,
            req_id_to_index={request_id: index for index, request_id in enumerate(request_ids)},
            sampled_token_ids=[sampled_token_ids[request_id] for request_id in request_ids],
            logprobs=None,
            prompt_logprobs_dict={},
            pooler_output=[],
        )

    continuous = make_scheduler(num_blocks=5, token_budget=8)
    a = make_request("a", 6)
    b = make_request("b", 6)
    continuous_visible: dict[str, Any] = {"a": a, "b": b}
    continuous.add_request(a)
    continuous.add_request(b)
    continuous_operations: list[dict[str, object]] = []
    continuous_operations.append(
        _capture_vllm_schedule(continuous, continuous_visible, label="step1")
    )
    continuous_operations.append(
        _capture_vllm_model_output(
            continuous,
            continuous_visible,
            label="a_decode_token_b_prefill_no_sample",
            sampled_token_ids={"a": [7], "b": []},
            output_factory=model_output,
        )
    )
    continuous_operations.append(
        _capture_vllm_schedule(continuous, continuous_visible, label="step2")
    )
    continuous_operations.append(
        _capture_vllm_finish(
            continuous,
            continuous_visible,
            label="finish_a",
            request_id="a",
            finish_status=RequestStatus.FINISHED_STOPPED,
        )
    )
    c = make_request("c", 4)
    continuous_operations.append(
        _capture_vllm_add_request(
            continuous,
            continuous_visible,
            c,
            label="add_c",
        )
    )
    continuous_operations.append(
        _capture_vllm_schedule(continuous, continuous_visible, label="step3_reuse")
    )

    pressure = make_scheduler(num_blocks=4, token_budget=12)
    head = make_request("head", 4)
    tail = make_request("tail", 8)
    pressure_visible: dict[str, Any] = {"head": head, "tail": tail}
    pressure.add_request(head)
    pressure.add_request(tail)
    pressure_operations: list[dict[str, object]] = []
    pressure_operations.append(
        _capture_vllm_schedule(pressure, pressure_visible, label="step1_fill_kv")
    )
    pressure_operations.append(
        _capture_vllm_model_output(
            pressure,
            pressure_visible,
            label="head_decode_token_tail_prefill_no_sample",
            sampled_token_ids={"head": [9], "tail": []},
            output_factory=model_output,
        )
    )
    pressure_operations.append(
        _capture_vllm_schedule(pressure, pressure_visible, label="step2_preempt_tail")
    )
    pressure_operations.append(
        _capture_vllm_finish(
            pressure,
            pressure_visible,
            label="finish_head",
            request_id="head",
            finish_status=RequestStatus.FINISHED_STOPPED,
        )
    )
    pressure_operations.append(
        _capture_vllm_schedule(pressure, pressure_visible, label="step3_resume_recompute")
    )

    prefix = make_scheduler(
        num_blocks=5,
        token_budget=8,
        enable_prefix_caching=True,
    )
    owner = make_request("owner", 8, token_ids=list(range(1, 9)))
    prefix_visible: dict[str, Any] = {"owner": owner}
    prefix.add_request(owner)
    prefix_operations: list[dict[str, object]] = []
    prefix_operations.append(
        _capture_vllm_schedule(prefix, prefix_visible, label="owner_populates_cache")
    )
    prefix_operations.append(
        _capture_vllm_finish(
            prefix,
            prefix_visible,
            label="finish_owner_inactive_residency",
            request_id="owner",
            finish_status=RequestStatus.FINISHED_STOPPED,
        )
    )
    follower = make_request("follower", 8, token_ids=list(range(1, 9)))
    prefix_operations.append(
        _capture_vllm_add_request(prefix, prefix_visible, follower, label="add_follower")
    )
    prefix_operations.append(
        _capture_vllm_schedule(prefix, prefix_visible, label="full_prompt_hit_recompute_tail")
    )
    sharer = make_request("sharer", 5, token_ids=[1, 2, 3, 4, 99])
    prefix_operations.append(
        _capture_vllm_add_request(prefix, prefix_visible, sharer, label="add_active_sharer")
    )
    prefix_operations.append(
        _capture_vllm_schedule(prefix, prefix_visible, label="active_refcount_share")
    )
    prefix_operations.append(
        _capture_vllm_finish(
            prefix,
            prefix_visible,
            label="finish_follower_shared_ref_survives",
            request_id="follower",
            finish_status=RequestStatus.FINISHED_STOPPED,
        )
    )
    prefix_operations.append(
        _capture_vllm_finish(
            prefix,
            prefix_visible,
            label="finish_sharer_all_inactive",
            request_id="sharer",
            finish_status=RequestStatus.FINISHED_STOPPED,
        )
    )
    replacement = make_request("replacement", 8, token_ids=list(range(90, 98)))
    prefix_operations.append(
        _capture_vllm_add_request(prefix, prefix_visible, replacement, label="add_replacement")
    )
    prefix_operations.append(
        _capture_vllm_schedule(prefix, prefix_visible, label="lru_cached_pages_evicted")
    )

    scenarios: list[dict[str, object]] = [
        {
            "name": "continuous_chunked_prefill_decode_release_reuse",
            "config": _scenario_config(num_blocks=5, token_budget=8),
            "operations": continuous_operations,
        },
        {
            "name": "kv_pressure_preempt_recompute",
            "config": _scenario_config(num_blocks=4, token_budget=12),
            "operations": pressure_operations,
        },
        {
            "name": "prefix_cache_hit_refcount_inactive_and_lru_eviction",
            "config": _scenario_config(
                num_blocks=5,
                token_budget=8,
                enable_prefix_caching=True,
            ),
            "operations": prefix_operations,
        },
    ]
    cache_spec_probe = FullAttentionSpec(
        block_size=4,
        num_kv_heads=1,
        head_size=1,
        dtype=torch.float32,
    )
    runtime: dict[str, object] = {
        "vllm_version": vllm.__version__,
        "imported_module_paths": imported_paths,
        "torch_version": torch.__version__,
        "device_execution": "none_cpu_scheduler_only",
        "cpu_cache_spec_probe": {
            "class": type(cache_spec_probe).__name__,
            "block_size": cache_spec_probe.block_size,
            "num_kv_heads": cache_spec_probe.num_kv_heads,
            "head_size": cache_spec_probe.head_size,
            "head_size_v": cache_spec_probe.head_size_v,
            "dtype": str(cache_spec_probe.dtype),
            "page_size_bytes": cache_spec_probe.page_size_bytes,
        },
    }
    connector_lifecycle = _capture_store_connector_lifecycle(
        make_request=make_request,
        store_scheduler_type=MooncakeStoreScheduler,
        store_worker_type=MooncakeStoreWorker,
        store_connector_type=MooncakeStoreConnector,
        metadata_type=MooncakeStoreConnectorMetadata,
        new_request_data_type=NewRequestData,
        scheduler_output_type=SchedulerOutput,
    )
    return scenarios, runtime, connector_lifecycle


def _capture_store_connector_lifecycle(
    *,
    make_request: Any,
    store_scheduler_type: Any,
    store_worker_type: Any,
    store_connector_type: Any,
    metadata_type: Any,
    new_request_data_type: Any,
    scheduler_output_type: Any,
) -> dict[str, object]:
    """Capture pinned Store scheduler/worker contracts without CUDA or I/O."""

    class LookupClient:
        def __init__(self, matched_tokens: int) -> None:
            self.matched_tokens = matched_tokens

        def lookup(self, _token_len: int, _block_hashes: object) -> int:
            return self.matched_tokens

    class Blocks:
        def get_block_ids(self) -> tuple[list[int], ...]:
            return ([1, 2],)

    def make_store_scheduler(matched_tokens: int) -> Any:
        scheduler = store_scheduler_type.__new__(store_scheduler_type)
        scheduler.kv_role = "kv_both"
        scheduler.load_async = True
        scheduler.client = LookupClient(matched_tokens)
        scheduler.pcp_size = 1
        scheduler.dcp_size = 1
        scheduler.original_block_size = 4
        scheduler._block_size = 4
        scheduler._hash_block_size = 4
        scheduler.load_specs = {}
        scheduler._request_trackers = {}
        scheduler._preempted_req_ids = set()
        scheduler._unfinished_requests = {}
        scheduler._unfinished_request_ids = set()
        return scheduler

    def new_output(request: Any, scheduled_tokens: int) -> Any:
        output = scheduler_output_type.make_empty()
        output.scheduled_new_reqs = [new_request_data_type.from_request(request, ([1, 2],))]
        output.num_scheduled_tokens = {request.request_id: scheduled_tokens}
        output.total_num_scheduled_tokens = scheduled_tokens
        return output

    load_request = make_request("load", 8, token_ids=list(range(1, 9)))
    load_scheduler = make_store_scheduler(8)
    load_match = load_scheduler.get_num_new_matched_tokens(load_request, 0)
    load_scheduler.update_state_after_alloc(load_request, Blocks(), load_match[0])
    load_request.num_computed_tokens = load_match[0]
    load_meta = load_scheduler.build_connector_meta(new_output(load_request, 4))

    save_request = make_request("save", 8, token_ids=list(range(1, 9)))
    save_scheduler = make_store_scheduler(0)
    save_match = save_scheduler.get_num_new_matched_tokens(save_request, 0)
    save_scheduler.update_state_after_alloc(save_request, Blocks(), save_match[0])
    save_meta = save_scheduler.build_connector_meta(new_output(save_request, 8))
    delay_free, _ = save_scheduler.request_finished(save_request, ([1, 2],))

    facade = store_connector_type.__new__(store_connector_type)
    facade._connector_metadata = None
    facade.bind_connector_metadata(load_meta)
    metadata_bound = facade._get_connector_metadata() is load_meta
    facade.clear_connector_metadata()
    metadata_cleared = facade._connector_metadata is None

    class SendThread:
        def __init__(self) -> None:
            self.stored_requests = {"save": 1}

        def delete_finished_stored_request(self, request_id: str) -> None:
            self.stored_requests.pop(request_id, None)

    send_worker = store_worker_type.__new__(store_worker_type)
    send_worker.kv_send_thread = SendThread()
    send_worker.finished_store_req = set()
    empty_meta = metadata_type(set(), set())
    sending_before = send_worker._get_and_clear_finished_sending({"save"}, empty_meta)
    send_worker.kv_send_thread.stored_requests["save"] = 0
    sending_after = send_worker._get_and_clear_finished_sending(set(), empty_meta)

    class RecvThread:
        def get_and_clear_finished_requests(self) -> set[str]:
            return {"load"}

    recv_worker = store_worker_type.__new__(store_worker_type)
    recv_worker.kv_role = "kv_consumer"
    recv_worker.load_async = True
    recv_worker.kv_recv_thread = RecvThread()
    recv_worker.tp_rank = 0
    done_sending, done_receiving = recv_worker.get_finished(set(), empty_meta)

    return {
        "name": "store_scheduler_worker_metadata_completion",
        "scheduler": {
            "full_prompt_lookup": [load_match[0], load_match[1]],
            "miss_lookup": [save_match[0], save_match[1]],
            "load_metadata": _normalize_store_metadata(load_meta),
            "save_metadata": _normalize_store_metadata(save_meta),
            "request_finished_delays_free": delay_free,
        },
        "worker": {
            "metadata_bound_then_cleared": metadata_bound and metadata_cleared,
            "send_before_transfer_completion": sorted(sending_before),
            "send_after_transfer_completion": sorted(sending_after),
            "receive_completion": sorted(done_receiving),
            "unexpected_send_completion": sorted(done_sending),
        },
    }


def _normalize_store_metadata(metadata: Any) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for request in metadata.requests:
        load_spec = request.load_spec
        rows.append(
            {
                "request_id": request.req_id,
                "token_len": request.token_len_chunk,
                "block_ids": [list(group) for group in request.block_ids],
                "block_hashes": [block_hash.hex() for block_hash in request.block_hashes],
                "can_save": bool(request.can_save),
                "load_spec": (
                    {
                        "local_cached_tokens": load_spec.vllm_cached_tokens,
                        "store_cached_tokens": load_spec.kvpool_cached_tokens,
                        "can_load": load_spec.can_load,
                    }
                    if load_spec is not None
                    else None
                ),
                "is_last_chunk": bool(request.is_last_chunk),
                "token_ids": list(request.token_ids or []),
            }
        )
    return {
        "requests": rows,
        "unfinished_request_ids": sorted(metadata.unfinished_request_ids),
        "preempted_request_ids": sorted(metadata.preempted_req_ids),
    }


def _capture_vllm_schedule(
    scheduler: Any,
    visible: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, object]:
    before = _vllm_state(scheduler, visible)
    output = scheduler.schedule()
    scheduler._moonkvsim_previous_output = output
    after = _vllm_state(scheduler, visible)
    return {
        "operation": "schedule",
        "label": label,
        "state_before": before,
        "output": _normalize_vllm_output(output, before=before, after=after),
        "state_after": after,
    }


def _capture_vllm_model_output(
    scheduler: Any,
    visible: Mapping[str, Any],
    *,
    label: str,
    sampled_token_ids: Mapping[str, list[int]],
    output_factory: Any,
) -> dict[str, object]:
    before = _vllm_state(scheduler, visible)
    # The ordinary synchronous scheduler consumes the complete preceding
    # scheduled request set. Prefill-only requests intentionally have no sample.
    previous_output = getattr(scheduler, "_moonkvsim_previous_output", None)
    if previous_output is None:
        raise CaptureError("capture lost the preceding scheduler output")
    scheduler.update_from_output(previous_output, output_factory(sampled_token_ids))
    after = _vllm_state(scheduler, visible)
    return {
        "operation": "model_output",
        "label": label,
        "sampled_token_ids": {key: list(value) for key, value in sampled_token_ids.items()},
        "state_before": before,
        "state_after": after,
    }


def _capture_vllm_finish(
    scheduler: Any,
    visible: Mapping[str, Any],
    *,
    label: str,
    request_id: str,
    finish_status: Any,
) -> dict[str, object]:
    before = _vllm_state(scheduler, visible)
    before_blocks = _state_blocks(before, request_id)
    scheduler.finish_requests(request_id, finish_status)
    after = _vllm_state(scheduler, visible)
    return {
        "operation": "finish",
        "label": label,
        "request_id": request_id,
        "finish_status": "FINISHED_STOPPED",
        "released_block_ids": list(reversed(before_blocks)),
        "state_before": before,
        "state_after": after,
    }


def _capture_vllm_add_request(
    scheduler: Any,
    visible: dict[str, Any],
    request: Any,
    *,
    label: str,
) -> dict[str, object]:
    before = _vllm_state(scheduler, visible)
    scheduler.add_request(request)
    visible[request.request_id] = request
    after = _vllm_state(scheduler, visible)
    return {
        "operation": "add_request",
        "label": label,
        "request": {
            "request_id": request.request_id,
            "prompt_tokens": request.num_prompt_tokens,
            "max_output_tokens": request.max_tokens,
            "arrival_ns": 0,
        },
        "state_before": before,
        "state_after": after,
    }


def _vllm_state(scheduler: Any, visible: Mapping[str, Any]) -> dict[str, object]:
    requests: list[dict[str, object]] = []
    for request in visible.values():
        block_ids: list[int] = []
        if request.request_id in scheduler.requests:
            groups = scheduler.kv_cache_manager.get_block_ids(request.request_id)
            if len(groups) != 1:
                raise CaptureError("golden scenarios require one KV cache group")
            block_ids = list(groups[0])
        requests.append(
            {
                "request_id": request.request_id,
                "status": request.status.name,
                "prompt_tokens": request.num_prompt_tokens,
                "num_tokens": request.num_tokens,
                "num_computed_tokens": request.num_computed_tokens,
                "num_output_tokens": request.num_output_tokens,
                "num_preemptions": request.num_preemptions,
                "block_ids": block_ids,
            }
        )
    return {
        "running_request_ids": [request.request_id for request in scheduler.running],
        "waiting_request_ids": [request.request_id for request in scheduler.waiting],
        "free_block_ids": _vllm_free_block_ids(scheduler),
        "pool_blocks": [
            {
                "block_id": block.block_id,
                "ref_count": block.ref_cnt,
                "cache_hash": (
                    bytes(block.block_hash[:-4]).hex() if block.block_hash is not None else None
                ),
                "group_id": (
                    int.from_bytes(block.block_hash[-4:], "big")
                    if block.block_hash is not None
                    else None
                ),
            }
            for block in scheduler.kv_cache_manager.block_pool.blocks
        ],
        "requests": requests,
    }


def _vllm_free_block_ids(scheduler: Any) -> list[int]:
    queue = scheduler.kv_cache_manager.block_pool.free_block_queue
    block = queue.fake_free_list_head.next_free_block
    result: list[int] = []
    traversed = 0
    while block is not queue.fake_free_list_tail:
        if block is None:
            raise CaptureError("vLLM free block queue terminated without fake tail")
        if block.block_id == 0:
            raise CaptureError("vLLM null block entered free queue")
        result.append(block.block_id)
        block = block.next_free_block
        traversed += 1
        if traversed > scheduler.kv_cache_manager.block_pool.num_gpu_blocks:
            raise CaptureError("vLLM free block queue has a cycle")
    if len(result) != queue.num_free_blocks:
        raise CaptureError("vLLM free block queue count drift")
    return result


def _normalize_vllm_output(
    output: Any,
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    # Store the exact output for the next synchronous update_from_output call.
    # Scheduler is not directly available here, so the caller attaches it just
    # after this function through the output owner hook below.
    order = list(output.num_scheduled_tokens)
    new_ids = [item.req_id for item in output.scheduled_new_reqs]
    cached_ids = list(output.scheduled_cached_reqs.req_ids)
    if len(new_ids) != len(set(new_ids)) or len(cached_ids) != len(set(cached_ids)):
        raise CaptureError("vLLM output contains duplicate request IDs")
    if set(new_ids).intersection(cached_ids) or set(order) != set(new_ids + cached_ids):
        raise CaptureError("vLLM output wire groups do not cover scheduled order")
    new_index = {request_id: index for index, request_id in enumerate(new_ids)}
    cached_index = {request_id: index for index, request_id in enumerate(cached_ids)}
    rows: list[dict[str, object]] = []
    for order_index, request_id in enumerate(order):
        before_request = _state_request(before, request_id)
        after_request = _state_request(after, request_id)
        before_status = before_request["status"]
        if before_status == "WAITING":
            origin = "NEW"
        elif before_status == "PREEMPTED":
            origin = "RESUMED"
        elif before_status == "RUNNING":
            origin = "RUNNING"
        else:
            raise CaptureError(f"cannot derive semantic scheduling origin from {before_status}")
        wire_group = "scheduled_new_reqs" if request_id in new_index else "scheduled_cached_reqs"
        expected_wire_group = (
            "scheduled_new_reqs" if origin in {"NEW", "RESUMED"} else "scheduled_cached_reqs"
        )
        if wire_group != expected_wire_group:
            raise CaptureError(
                f"vLLM wire group/origin drift for {request_id}: {wire_group}/{origin}"
            )
        group_index = (
            new_index[request_id]
            if wire_group == "scheduled_new_reqs"
            else cached_index[request_id]
        )
        computed_before = _integer(before_request["num_computed_tokens"], "computed before")
        computed_after = _integer(after_request["num_computed_tokens"], "computed after")
        prompt_tokens = _integer(before_request["prompt_tokens"], "prompt tokens")
        num_tokens_before = _integer(before_request["num_tokens"], "num tokens before")
        scheduled_tokens = _integer(output.num_scheduled_tokens[request_id], "scheduled tokens")
        before_blocks = _int_list(before_request["block_ids"], "blocks before")
        after_blocks = _int_list(after_request["block_ids"], "blocks after")
        appended_blocks = after_blocks[len(before_blocks) :]
        if after_blocks[: len(before_blocks)] != before_blocks:
            raise CaptureError(f"scheduled request block table is not append-only: {request_id}")
        local_hit_tokens = computed_after - computed_before - scheduled_tokens
        if local_hit_tokens < 0 or local_hit_tokens % 4:
            raise CaptureError(
                "local prefix hit tokens do not align with the block geometry: "
                f"request={request_id}, before={computed_before}, after={computed_after}, "
                f"scheduled={scheduled_tokens}, appended={appended_blocks}"
            )
        num_local_hit_blocks = local_hit_tokens // 4
        if num_local_hit_blocks > len(appended_blocks):
            raise CaptureError("local prefix hit exceeds the appended request block table")
        # vLLM appends cached prefix blocks before newly allocated suffix
        # blocks. `new_block_ids_to_zero` is conditional physical zeroing
        # metadata, not an allocation-origin signal, so it cannot classify
        # ordinary allocations when zeroing is disabled.
        local_hit_blocks = appended_blocks[:num_local_hit_blocks]
        new_blocks = appended_blocks[num_local_hit_blocks:]
        computed_before_execution = computed_before + local_hit_tokens
        rows.append(
            {
                "request_id": request_id,
                "order_index": order_index,
                "origin": origin,
                "wire_group": wire_group,
                "wire_group_index": group_index,
                "phase": ("PREFILL" if computed_before_execution < prompt_tokens else "DECODE"),
                "num_scheduled_tokens": scheduled_tokens,
                "num_computed_tokens_before": computed_before,
                "num_local_cache_hit_tokens": local_hit_tokens,
                "num_computed_tokens_before_execution": computed_before_execution,
                "num_computed_tokens_after": computed_after,
                "block_ids_before": before_blocks,
                "local_cache_hit_block_ids": local_hit_blocks,
                "new_block_ids": new_blocks,
                "block_ids_after": after_blocks,
                "chunked": scheduled_tokens < num_tokens_before - computed_before,
                "recompute": origin == "RESUMED",
            }
        )
    preempted = sorted(output.preempted_req_ids or ())
    normalized = {
        "order": order,
        "rows": rows,
        "num_scheduled_tokens": dict(output.num_scheduled_tokens),
        "total_num_scheduled_tokens": output.total_num_scheduled_tokens,
        "token_budget_remaining": (
            _scenario_budget_for_state(before) - output.total_num_scheduled_tokens
        ),
        "preempted_request_ids": preempted,
        "releases": [
            {
                "request_id": request_id,
                "block_ids": list(reversed(_state_blocks(before, request_id))),
                "cause": "preempt_recompute",
            }
            for request_id in preempted
        ],
    }
    _audit_schedule(normalized, before=before, after=after)
    return normalized


def _scenario_budget_for_state(state: Mapping[str, object]) -> int:
    request_ids = {
        _mapping(item, "state request").get("request_id")
        for item in _list(state.get("requests"), "state.requests")
    }
    return 12 if request_ids == {"head", "tail"} else 8


def _scenario_config(
    *,
    num_blocks: int,
    token_budget: int,
    enable_prefix_caching: bool = False,
) -> dict[str, object]:
    return {
        "block_size_tokens": 4,
        "num_blocks_including_null": num_blocks,
        "num_usable_blocks": num_blocks - 1,
        "null_block_id": 0,
        "max_num_batched_tokens": token_budget,
        "max_num_running_requests": 2,
        "max_model_len_tokens": 32,
        "enable_chunked_prefill": True,
        "enable_prefix_caching": enable_prefix_caching,
        "async_scheduling": False,
        "policy": "fcfs",
    }


def _state_request(state: Mapping[str, object], request_id: str) -> Mapping[str, Any]:
    for raw_request in _list(state.get("requests"), "state.requests"):
        request = _mapping(raw_request, "state request")
        if request.get("request_id") == request_id:
            return request
    raise CaptureError(f"state is missing request: {request_id}")


def _state_blocks(state: Mapping[str, object], request_id: str) -> list[int]:
    return _int_list(_state_request(state, request_id).get("block_ids"), "request blocks")


def _audit_schedule(
    output: Mapping[str, object],
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    order = _list(output.get("order"), "output.order")
    rows = _list(output.get("rows"), "output.rows")
    if [_mapping(row, "schedule row").get("request_id") for row in rows] != order:
        raise CaptureError("schedule rows do not preserve num_scheduled_tokens order")
    counts = _mapping(output.get("num_scheduled_tokens"), "num_scheduled_tokens")
    if list(counts) != order:
        raise CaptureError("num_scheduled_tokens insertion order drift")
    total = _integer(output.get("total_num_scheduled_tokens"), "scheduled total")
    if total != sum(_integer(value, "scheduled count") for value in counts.values()):
        raise CaptureError("scheduled token total does not conserve")
    if 0 in _int_list(before.get("free_block_ids"), "before free blocks"):
        raise CaptureError("null block is free before schedule")
    if 0 in _int_list(after.get("free_block_ids"), "after free blocks"):
        raise CaptureError("null block is free after schedule")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError(f"cannot load JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CaptureError(f"JSON root must be an object: {path}")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CaptureError(f"{name} must be a string-keyed object")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise CaptureError(f"{name} must be a list")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{name} must be a non-empty string")
    return value


def _sha_string(value: object, name: str) -> str:
    text = _string(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise CaptureError(f"{name} must be a lowercase SHA-256")
    return text


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureError(f"{name} must be an integer")
    return value


def _int_list(value: object, name: str) -> list[int]:
    values = _list(value, name)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        raise CaptureError(f"{name} must contain integers")
    return values


def _relative_path(value: object, name: str) -> Path:
    relative = Path(_string(value, name))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise CaptureError(f"{name} must be a safe relative path")
    return relative


def _inside(root: Path, relative: Path) -> Path:
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise CaptureError(f"path escapes expected root: {relative}")
    return resolved


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as source:
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError as error:
        raise CaptureError(f"cannot hash {path}: {error}") from error


def _canonical_json_bytes(document: Mapping[str, object]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


if __name__ == "__main__":
    raise SystemExit(main())
