from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from moonkvsim.integration.vllm.differential import (
    GENERATOR_RELATIVE_PATH,
    GOLDEN_EVIDENCE_CLASS,
    GOLDEN_RELATIVE_PATH,
    SOURCE_LOCK_RELATIVE_PATH,
    VLLMDifferentialError,
    compare_moonkvsim_to_vllm_golden,
    load_vllm_scheduler_golden,
    repository_root,
)


def test_pinned_vllm_scheduler_block_golden_matches_moonkvsim_exactly() -> None:
    golden = load_vllm_scheduler_golden()

    report = compare_moonkvsim_to_vllm_golden(golden)

    assert report.scenario_names == (
        "continuous_chunked_prefill_decode_release_reuse",
        "kv_pressure_preempt_recompute",
        "prefix_cache_hit_refcount_inactive_and_lru_eviction",
    )
    assert report.operation_count == 21
    assert report.evidence_class == GOLDEN_EVIDENCE_CLASS
    assert len(report.golden_fingerprint) == 64
    assert golden["provenance"]["cpu_cache_spec_probe"] == {
        "block_size": 4,
        "class": "FullAttentionSpec",
        "dtype": "torch.float32",
        "head_size": 1,
        "head_size_v": 1,
        "num_kv_heads": 1,
        "page_size_bytes": 32,
    }

    pressure = golden["scenarios"][1]
    preempt = pressure["operations"][2]
    assert preempt["output"]["preempted_request_ids"] == ["tail"]
    assert preempt["output"]["releases"] == [
        {
            "request_id": "tail",
            "block_ids": [3, 2],
            "cause": "preempt_recompute",
        }
    ]
    [head] = preempt["output"]["rows"]
    assert head["new_block_ids"] == [3]

    resumed = pressure["operations"][4]["output"]["rows"][0]
    assert resumed["origin"] == "RESUMED"
    assert resumed["wire_group"] == "scheduled_new_reqs"
    assert resumed["recompute"] is True
    assert resumed["block_ids_after"] == [2, 3]

    prefix = golden["scenarios"][2]
    full_hit = prefix["operations"][3]["output"]["rows"][0]
    assert full_hit["num_local_cache_hit_tokens"] == 4
    assert full_hit["num_scheduled_tokens"] == 4
    assert len(full_hit["local_cache_hit_block_ids"]) == 1
    shared = prefix["operations"][5]["state_after"]["pool_blocks"]
    assert max(block["ref_count"] for block in shared) == 2
    inactive = prefix["operations"][7]["state_after"]
    assert len(inactive["free_block_ids"]) == 4
    assert any(
        block["cache_hash"] is not None and block["ref_count"] == 0
        for block in inactive["pool_blocks"]
    )

    connector = golden["connector_lifecycle"]
    assert connector["scheduler"]["full_prompt_lookup"] == [4, True]
    assert connector["scheduler"]["request_finished_delays_free"] is True
    assert connector["worker"] == {
        "metadata_bound_then_cleared": True,
        "receive_completion": ["load"],
        "send_after_transfer_completion": ["save"],
        "send_before_transfer_completion": [],
        "unexpected_send_completion": [],
    }


def test_differential_fails_closed_on_semantic_or_source_hash_drift() -> None:
    golden = load_vllm_scheduler_golden()
    semantic_drift = copy.deepcopy(golden)
    semantic_drift["scenarios"][0]["operations"][0]["output"]["num_scheduled_tokens"]["a"] = 5
    with pytest.raises(VLLMDifferentialError, match="conserve"):
        compare_moonkvsim_to_vllm_golden(semantic_drift)

    source_drift = copy.deepcopy(golden)
    source_drift["provenance"]["installed_vllm_file_sha256"]["vllm/v1/request.py"] = "0" * 64
    with pytest.raises(VLLMDifferentialError, match="source lock"):
        compare_moonkvsim_to_vllm_golden(source_drift)

    connector_source_drift = copy.deepcopy(golden)
    connector_source_drift["provenance"]["installed_store_connector_transitive_sha256"][
        "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/worker.py"
    ] = "0" * 64
    with pytest.raises(VLLMDifferentialError, match="transitive hashes"):
        compare_moonkvsim_to_vllm_golden(connector_source_drift)

    model_drift = copy.deepcopy(golden)
    model_drift["provenance"]["model"]["file_sha256"]["config.json"] = "0" * 64
    with pytest.raises(VLLMDifferentialError, match="model file hashes"):
        compare_moonkvsim_to_vllm_golden(model_drift)


def test_loader_rejects_noncanonical_golden_bytes(tmp_path: Path) -> None:
    golden = load_vllm_scheduler_golden()
    noncanonical = tmp_path / "golden.json"
    noncanonical.write_text(json.dumps(golden, indent=2), encoding="utf-8")

    with pytest.raises(VLLMDifferentialError, match="not canonical JSON"):
        load_vllm_scheduler_golden(noncanonical)


def test_unrelated_source_lock_readiness_update_does_not_break_scheduler_golden(
    tmp_path: Path,
) -> None:
    root = repository_root()
    copied_root = tmp_path / "checkout"
    copied_golden = copied_root / GOLDEN_RELATIVE_PATH
    copied_lock = copied_root / SOURCE_LOCK_RELATIVE_PATH
    copied_generator = copied_root / GENERATOR_RELATIVE_PATH
    copied_golden.parent.mkdir(parents=True)
    copied_lock.parent.mkdir(parents=True, exist_ok=True)
    copied_generator.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / GOLDEN_RELATIVE_PATH, copied_golden)
    shutil.copyfile(root / GENERATOR_RELATIVE_PATH, copied_generator)

    source_lock = json.loads((root / SOURCE_LOCK_RELATIVE_PATH).read_text(encoding="utf-8"))
    source_lock["readiness"]["status"] = "FUTURE_UNRELATED_EVIDENCE_UPDATE"
    copied_lock.write_text(json.dumps(source_lock, sort_keys=True), encoding="utf-8")

    golden = load_vllm_scheduler_golden(copied_golden, root=copied_root)
    report = compare_moonkvsim_to_vllm_golden(golden, root=copied_root)

    assert report.operation_count == 21


def test_generator_refuses_the_project_interpreter_without_silent_skip() -> None:
    root = repository_root()
    completed = subprocess.run(
        [sys.executable, str(root / GENERATOR_RELATIVE_PATH), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "wrong interpreter" in completed.stderr
