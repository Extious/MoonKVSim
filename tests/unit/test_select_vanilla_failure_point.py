from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "select_vanilla_failure_point.py"


def _load_script() -> Any:
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location("select_vanilla_failure_point", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_PATH.parent))


SELECTOR = _load_script()


def _record(timestamp_ns: int, record_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_ns": timestamp_ns,
        "journal_sequence": -1,
        "record_type": record_type,
        "data": data,
    }


def _fixture_records() -> list[dict[str, Any]]:
    span_id = "workflow:subagent:000184:000005"
    request_id = f"trace-request:{span_id}"
    get_id = f"trace-get:{span_id}:route-0:block-000000"
    event_id = "baseline-forward-batch:dp-1:0001"
    lease_id = f"gpu-compute:dp-1:{event_id}"
    allocation_id = "store-allocation-0"
    replica_id = "store-replica-0"
    records = [
        _record(
            10,
            "STORE_CLIENT_PUT_STARTED",
            {
                "put_id": "put-0",
                "object_id": "object-0",
                "replica_ids": [replica_id],
            },
        ),
        _record(
            10,
            "ALLOCATION_ADDED",
            {
                "allocation": {
                    "allocation_id": allocation_id,
                    "object_id": "object-0",
                    "replica_id": replica_id,
                    "resource_id": "store-dram-0",
                    "state": "PENDING",
                }
            },
        ),
        _record(
            20, "ALLOCATION_TRANSITION", {"allocation_id": allocation_id, "state": "COMMITTED"}
        ),
        _record(
            20,
            "ALLOCATION_RECOVERY_ELIGIBILITY",
            {"allocation_id": allocation_id, "eligible": False},
        ),
        _record(
            20,
            "STORE_CLIENT_PUT_COMMITTED",
            {"put_id": "put-0", "replica_ids": [replica_id]},
        ),
        _record(
            30,
            "TRACE_RUNNER_SPAN_ADMITTED",
            {
                "request_id": request_id,
                "span_id": span_id,
                "target_replica_id": "dp-1",
                "route_version": 0,
                "visible_committed_prefix_tokens": 64,
                "committed_prefix_lookup": {
                    "observed_committed_block_count": 1,
                    "mode": "full_hash_vector_from_block_zero_first_miss",
                    "normalized_parent_prefix_used_as_query_limit": False,
                },
            },
        ),
        _record(
            31,
            "STORE_CLIENT_GET_STARTED",
            {
                "get_id": get_id,
                "cause": "BASELINE_E2_SHARED_STORE_PREFIX_REUSE",
                "route_version": 0,
                "object_id": "object-0",
                "replica_id": replica_id,
                "source_allocation_ids": [allocation_id],
                "source_pins_held_until_terminal": True,
                "payload_bytes": 1024,
            },
        ),
        _record(31, "ALLOCATION_SOURCE_PINNED", {"allocation_id": allocation_id}),
        _record(
            40,
            "STORE_CLIENT_GET_COMPLETED",
            {"get_id": get_id, "replica_id": replica_id, "transferred_bytes": 1024},
        ),
        _record(40, "ALLOCATION_SOURCE_UNPINNED", {"allocation_id": allocation_id}),
        _record(
            40,
            "TRACE_RUNNER_REMOTE_PREFIX_READY",
            {
                "request_id": request_id,
                "restored_tokens": 64,
                "target_replica_id": "dp-1",
            },
        ),
        _record(
            50,
            "BASELINE_OUTPUT_ACTIVATED",
            {"request_id": request_id, "route_version": 0, "output_index": 0},
        ),
        _record(
            60,
            "BASELINE_FORWARD_BATCH_SCHEDULED",
            {
                "event_id": event_id,
                "replica_id": "dp-1",
                "completion_ns": 100,
                "participants": [
                    {
                        "request_id": request_id,
                        "target_id": "dp-1",
                        "route_version": 0,
                        "produces_output": True,
                        "output_index": 1,
                    }
                ],
            },
        ),
        _record(
            60,
            "TRACE_RUNNER_GPU_COMPUTE_LEASE_ACQUIRED",
            {
                "lease_id": lease_id,
                "replica_id": "dp-1",
                "capacity": 1,
                "request_ids": [request_id],
                "release_ns": 100,
            },
        ),
        _record(
            100,
            "BASELINE_FORWARD_BATCH_COMPLETED",
            {"event_id": event_id, "accepted": True, "fence_reason": None},
        ),
        _record(
            100,
            "TRACE_RUNNER_GPU_COMPUTE_LEASE_RELEASED",
            {
                "lease_id": lease_id,
                "outcome": "COMPLETED",
                "actual_release_ns": 100,
                "declared_release_ns": 100,
            },
        ),
        _record(110, "TRACE_RUNNER_SPAN_COMPLETED", {"request_id": request_id}),
    ]
    for sequence, record in enumerate(records):
        record["journal_sequence"] = sequence
    return records


def _fixture_config() -> dict[str, Any]:
    return {
        "deployment": {
            "gpus": [
                {"replica_id": "dp-0", "gpu_id": "gpu-0", "hbm_resource_id": "gpu-0.hbm"},
                {"replica_id": "dp-1", "gpu_id": "gpu-1", "hbm_resource_id": "gpu-1.hbm"},
            ]
        },
        "store": {"segment_id": "store-dram-0"},
    }


def _renumber(records: list[dict[str, Any]]) -> None:
    records.sort(key=lambda item: item["timestamp_ns"])
    for sequence, record in enumerate(records):
        record["journal_sequence"] = sequence


def test_selects_with_false_recovery_eligibility_overlay() -> None:
    selected = SELECTOR.select_failure_point(_fixture_records(), _fixture_config())

    assert selected["span_id"] == "workflow:subagent:000184:000005"
    assert selected["at_ns"] == 79
    assert selected["target"] == {
        "replica_id": "dp-1",
        "gpu_id": "gpu-1",
        "hbm_resource_id": "gpu-1.hbm",
    }
    [allocation] = selected["store_prefix"]["allocation_state_at_failure"]
    assert allocation["state"] == "COMMITTED"
    assert allocation["source_pin_count"] == 0
    assert allocation["terminal_transition_absent_before_failure"] is True
    assert "recovery_eligible" not in allocation
    [directory] = selected["store_prefix"]["directory_state_at_failure"]
    assert directory["visible"] is True
    assert directory["expected_shards_complete"] is True
    [binding] = selected["store_prefix"]["source_bindings"]
    assert binding["visibility_proof"] == (
        "successful_real_get_from_visible_committed_store_replica"
    )


@pytest.mark.parametrize("invalid_kind", ["terminal", "pinned", "no_publication"])
def test_store_source_point_in_time_gates_fail_closed(invalid_kind: str) -> None:
    records = _fixture_records()
    if invalid_kind == "terminal":
        records.append(
            _record(
                61,
                "ALLOCATION_TRANSITION",
                {"allocation_id": "store-allocation-0", "state": "RELEASED"},
            )
        )
    elif invalid_kind == "pinned":
        records.append(
            _record(61, "ALLOCATION_SOURCE_PINNED", {"allocation_id": "store-allocation-0"})
        )
    else:
        records = [
            record for record in records if record["record_type"] != "STORE_CLIENT_PUT_COMMITTED"
        ]
    _renumber(records)

    with pytest.raises(SELECTOR.NoSelectionError):
        SELECTOR.select_failure_point(records, _fixture_config())


@pytest.mark.parametrize("mismatch", ["replica", "bytes", "publication_order"])
def test_real_get_completion_and_publication_order_fail_closed(mismatch: str) -> None:
    records = _fixture_records()
    if mismatch == "publication_order":
        commit = next(
            record for record in records if record["record_type"] == "STORE_CLIENT_PUT_COMMITTED"
        )
        commit["timestamp_ns"] = 32
    else:
        completion = next(
            record for record in records if record["record_type"] == "STORE_CLIENT_GET_COMPLETED"
        )
        if mismatch == "replica":
            completion["data"]["replica_id"] = "different-store-replica"
        else:
            completion["data"]["transferred_bytes"] = 1023
    _renumber(records)

    with pytest.raises(SELECTOR.NoSelectionError):
        SELECTOR.select_failure_point(records, _fixture_config())


def test_failure_replay_requires_an_alternate_physical_gpu() -> None:
    config = _fixture_config()
    config["deployment"]["gpus"][0]["gpu_id"] = "gpu-1"

    with pytest.raises(SELECTOR.NoSelectionError):
        SELECTOR.select_failure_point(_fixture_records(), config)


@pytest.mark.parametrize("length", [40, 64])
def test_complete_git_object_id_lengths(length: int) -> None:
    assert SELECTOR._GIT_OBJECT_RE.fullmatch("a" * length) is not None


@pytest.mark.parametrize("length", [39, 41, 63, 65])
def test_incomplete_git_object_id_lengths_are_rejected(length: int) -> None:
    assert SELECTOR._GIT_OBJECT_RE.fullmatch("a" * length) is None


def test_selection_fingerprint_is_canonical_and_tamper_evident() -> None:
    document = {"schema": SELECTOR.SELECTION_SCHEMA, "selection": {"at_ns": 79}}
    fingerprint = SELECTOR._selection_fingerprint(document)
    reordered = {"selection": {"at_ns": 79}, "schema": SELECTOR.SELECTION_SCHEMA}

    assert SELECTOR._selection_fingerprint(reordered) == fingerprint
    reordered["selection"]["at_ns"] = 80
    assert SELECTOR._selection_fingerprint(reordered) != fingerprint


def test_interval_subtraction_does_not_duplicate_left_segment() -> None:
    assert SELECTOR._subtract_intervals([(10, 30)], [(20, 25)]) == [(10, 19), (26, 30)]


def test_materialize_replaces_only_failure_and_refuses_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    scripts_dir = repository_root / "scripts"
    config_dir = repository_root / "configs"
    scripts_dir.mkdir(parents=True)
    config_dir.mkdir()
    base_path = config_dir / "base.json"
    base_document = {
        "name": "unchanged",
        "predictor": {"hardware_profile_fingerprint": "hardware-0"},
        "failure": {"enabled": False, "reason": "base"},
    }
    base_path.write_text(json.dumps(base_document), encoding="utf-8")
    monkeypatch.setattr(SELECTOR, "__file__", str(scripts_dir / SCRIPT_PATH.name))

    def fake_load(path: Path) -> SimpleNamespace:
        document = json.loads(path.read_text(encoding="utf-8"))
        return SimpleNamespace(
            document=document,
            failure_enabled=bool(document["failure"]["enabled"]),
        )

    def fake_resolve(config: SimpleNamespace) -> tuple[SimpleNamespace, ...]:
        [event] = config.document["failure"]["events"]
        return (
            SimpleNamespace(
                failure_id=event["failure_id"],
                at_ns=event["at_ns"],
                gpu_id=event["target"]["gpu_id"],
            ),
        )

    monkeypatch.setattr(SELECTOR, "load_harness_config", fake_load)
    monkeypatch.setattr(SELECTOR, "resolve_failure_specs", fake_resolve)
    raw_base = base_path.read_bytes()
    selection = {
        "at_ns": 79,
        "target": {
            "replica_id": "dp-1",
            "gpu_id": "gpu-1",
            "hbm_resource_id": "gpu-1.hbm",
        },
    }
    failure = SELECTOR._failure_document(selection)
    evidence = {
        "selection_fingerprint": "0" * 64,
        "selection": selection,
        "input": {
            "base_config_path": "configs/base.json",
            "base_config_sha256": SELECTOR._sha256_bytes(raw_base),
        },
        "materialization": {
            "json_pointer_replaced": "/failure",
            "failure": failure,
            "hardware_profile_fingerprint": "hardware-0",
        },
    }
    output = config_dir / "failure.json"

    tampered = copy.deepcopy(evidence)
    tampered["materialization"]["failure"]["events"][0]["at_ns"] = 80
    with pytest.raises(SELECTOR.SelectionError, match="canonical selected failure"):
        SELECTOR.materialize_config(tampered, base_path, output)
    wrong_hardware = copy.deepcopy(evidence)
    wrong_hardware["materialization"]["hardware_profile_fingerprint"] = "hardware-other"
    with pytest.raises(SELECTOR.SelectionError, match="hardware fingerprint"):
        SELECTOR.materialize_config(wrong_hardware, base_path, output)

    result = SELECTOR.materialize_config(evidence, base_path, output)

    materialized = json.loads(output.read_text(encoding="utf-8"))
    assert materialized["name"] == base_document["name"]
    assert materialized["failure"] == failure
    assert result["changed_json_pointers"] == ["/failure"]
    with pytest.raises(SELECTOR.SelectionError, match="already exists"):
        SELECTOR.materialize_config(evidence, base_path, output)


def _source_gate_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any], Path]:
    repository_root = tmp_path / "repository"
    script = repository_root / "scripts" / "select_vanilla_failure_point.py"
    semantic = repository_root / "python" / "moonkvsim" / "semantic.py"
    script.parent.mkdir(parents=True)
    semantic.parent.mkdir(parents=True)
    script.write_bytes(b"selector")
    semantic.write_bytes(b"semantic")
    monkeypatch.setattr(SELECTOR, "__file__", str(script))

    current_head = "b" * 40
    current_tree = "c" * 40

    def fake_git(_root: Path, *args: str) -> bytes:
        if args[0] == "status":
            return b""
        if args == ("rev-parse", "HEAD"):
            return f"{current_head}\n".encode()
        if args == ("rev-parse", "HEAD^{tree}"):
            return f"{current_tree}\n".encode()
        if args[0] == "ls-files":
            return f"{args[-1]}\n".encode()
        raise AssertionError(args)

    monkeypatch.setattr(SELECTOR, "_git_output", fake_git)
    files = [
        {
            "path": "python/moonkvsim/semantic.py",
            "scope": "repository",
            "roles": ["python/moonkvsim-source"],
            "size_bytes": len(semantic.read_bytes()),
            "sha256": SELECTOR._sha256_bytes(semantic.read_bytes()),
        }
    ]
    evidence = {
        "selection_tool": {
            "git_head_commit": current_head,
            "git_head_tree": current_tree,
            "script_path": "scripts/select_vanilla_failure_point.py",
            "script_size_bytes": len(script.read_bytes()),
            "script_sha256": SELECTOR._sha256_bytes(script.read_bytes()),
        },
        "input": {
            # The diagnostic commit may predate the committed selector tool.
            "git_head_commit": "a" * 40,
            "artifact_sha256": {"run-audit.json": "0" * 64},
            "semantic_sources": {
                "files": files,
                "file_count": len(files),
                "aggregate_sha256": SELECTOR._sha256_bytes(SELECTOR.canonical_json_bytes(files)),
            },
        },
    }
    return repository_root, evidence, semantic


def test_clean_source_gate_allows_diagnostic_head_drift_when_tool_and_sources_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root, evidence, _semantic = _source_gate_fixture(tmp_path, monkeypatch)

    current = SELECTOR._require_clean_semantic_sources(repository_root, evidence)

    assert current["git_head_commit"] == "b" * 40
    assert evidence["input"]["git_head_commit"] == "a" * 40


@pytest.mark.parametrize("drift", ["hash", "size", "type", "symlink", "path"])
def test_clean_source_gate_rejects_every_semantic_source_drift(
    drift: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root, evidence, semantic = _source_gate_fixture(tmp_path, monkeypatch)
    if drift == "hash":
        semantic.write_bytes(b"semantiX")
    elif drift == "size":
        semantic.write_bytes(b"semantic-long")
    elif drift == "type":
        semantic.unlink()
        semantic.mkdir()
    elif drift == "symlink":
        semantic.unlink()
        target = semantic.parent / "other.py"
        target.write_bytes(b"semantic")
        semantic.symlink_to(target)
    else:
        [item] = evidence["input"]["semantic_sources"]["files"]
        item["path"] = "../semantic.py"
        evidence["input"]["semantic_sources"]["aggregate_sha256"] = SELECTOR._sha256_bytes(
            SELECTOR.canonical_json_bytes([item])
        )

    with pytest.raises(SELECTOR.SelectionError):
        SELECTOR._require_clean_semantic_sources(repository_root, evidence)
