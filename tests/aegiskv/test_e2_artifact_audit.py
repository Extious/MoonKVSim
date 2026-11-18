from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import moonkvsim.aegiskv.experiment_suite as suite
from moonkvsim.aegiskv.experiment import (
    CellSpec,
    FailureEventSchedule,
    FailureSchedule,
    ModelParameters,
    StudyRunResult,
    qwen3_8b_dp_deployment,
)
from moonkvsim.aegiskv.experiment_suite import (
    ImplementationBinding,
    WorkloadBinding,
    run_e2_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "benchmark/AegisKV/experiments/scripts/audit_aegiskv_e2_artifacts.py"


def _load_audit() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_aegiskv_e2_artifacts", AUDIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load AegisKV E2 artifact auditor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit()


@dataclass(frozen=True)
class Bundle:
    matrix: Path
    figures: Path


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(_canonical(value))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(isinstance(value, dict) for value in values)
    return values


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(_canonical(value) for value in values))


def _payload(spec: CellSpec) -> dict[str, Any]:
    return {
        "schema": "moonkvsim.aegiskv.study_run_payload.v1",
        "status": "PASS",
        "evidence": dict(AUDIT.PAYLOAD_EVIDENCE),
        "global_clock": {
            "kind": "single_global_virtual_clock",
            "time_unit": "ns",
            "wall_clock_or_sleep_used": False,
            "event_order": "timestamp_priority_stable_sequence",
        },
        "execution_scope": {
            "cpu_metadata_only": True,
            "slurm_used": False,
            "cuda_used": False,
            "network_io_used": False,
        },
        "model_deployment": qwen3_8b_dp_deployment(spec.variant.parameters.dp_count),
        "resource_model": {
            "peer_hbm_resources": ["gpu-0"],
            "store_dram_segments": ["store-0:segment-0"],
            "store_node_count": 1,
            "host_dram_staging_resources": ["gpu-0.host-staging"],
            "store_transport": "RDMA_GDR",
            "host_staging_capacity_transactions": True,
            "source_pin_overlay_without_double_charge": True,
            "communication_backend": "flow_contention",
            "fairness": "weighted_max_min_work_conserving",
            "flow_clock": "shared_global_des_now_ns",
            "slice_size_policy_chunks": 8,
            "copy_engines": ["copy-0"],
            "fabric_resources": ["fabric-0"],
            "rate_resources": {"fabric-0": 100.0},
            "gpu_sku": "NVIDIA-A100-40GB",
            "topology": "single_node",
            "node_count": 1,
            "gpu_node_id": "node-inference-0",
            "gpu_hbm_capacity_bytes_per_gpu": 40 * 1024**3,
            "gpu_hbm_account_stack": ["FREE"],
            "gpu_hbm_event_boundary_snapshots": True,
            "per_gpu_peer_hbm_quota_enforced": True,
            "failed_gpu_hbm_becomes_unavailable_not_free": True,
        },
        "recovery_model": {
            "committed_replica_only": True,
            "continuous_prefix_only": True,
            "in_flight_protection_estimate_used": False,
            "missing_suffix_recomputed": True,
            "phase_order": [
                "RESTORE_COMMITTED_PREFIX",
                "PROMPT_SUFFIX_RECOMPUTE",
                "SILENT_REPLAY_COMMITTED_OUTPUT",
                "ATOMIC_ACTIVATION",
                "REMAINING_DECODE",
            ],
        },
        "variant_fingerprint": spec.variant.fingerprint,
        "context_bucket": spec.context_bucket,
        "scenario": spec.scenario.value,
        "workload": {
            "span_count": 1,
            "workflow_count": 1,
            "source_hash_scope": "within_workflow_only",
            "no_truncation_or_padding": True,
        },
        "failure_schedule": (
            None if spec.failure_schedule is None else spec.failure_schedule.to_dict()
        ),
        "metrics": {
            "virtual_end_ns": 200,
            "workflow_completion_time_ns": {"mean": 100, "p95": 110},
            "goodput_output_tokens_per_second_milli": 1_000,
            "recovery_latency_ns": {"mean": 20},
            "restored_tokens": {"total": 30},
            "recompute_tokens_after_failure": 40,
            "resource_cost": {
                "peer_hbm_peak_bytes": 50,
                "store_dram_peak_bytes": 60,
                "network_byte_ns": {"FAKE_TRANSFER": 70},
                "copy_engine_busy_ns": {"FAKE_TRANSFER": 80},
                "transfer_state_counts": (
                    {"ABORTED": 1, "COMMITTED": 1}
                    if spec.failure_schedule is not None
                    else {"COMMITTED": 1}
                )
            },
        },
        "output_audit": {
            "expected_output_tokens": 1,
            "external_output_tokens": 1,
            "duplicate_or_missing_tokens": 0,
            "stale_route_output_count": 0,
        },
        "forbidden_semantics": {
            "hbm_to_dram_writeback_count": 0,
            "target_owned_destage_count": 0,
            "dram_prerequisite_for_hbm_count": 0,
            "cross_tier_abort_propagation_count": 0,
            "second_directory_count": 0,
            "ssd_nvme_event_count": 0,
        },
    }


def _fake_run(_records: object, spec: CellSpec) -> StudyRunResult:
    failure = spec.failure_schedule is not None
    failure_events: list[dict[str, Any]] = []
    recovery_events: list[dict[str, Any]] = []
    peer_hbm_timelines: dict[str, list[dict[str, int]]] = {}
    if spec.failure_schedule is not None:
        for event_schedule in spec.failure_schedule.events:
            failure_at_ns = 100 + 100 * event_schedule.event_index
            repair_completed_at_ns = (
                None
                if event_schedule.gpu_recovery_time_ns is None
                else failure_at_ns + event_schedule.gpu_recovery_time_ns
            )
            failure_events.append(
                {
                    "failure_id": event_schedule.failure_id,
                    "timestamp_ns": failure_at_ns,
                    "target_gpu_id": event_schedule.target_gpu_id,
                    "impacted_active_span_ids": [event_schedule.focus_span_id],
                    "impacted_queued_span_ids": [],
                    "repair_completed_at_ns": repair_completed_at_ns,
                    "logical_trigger": {
                        "focus_span_id": event_schedule.focus_span_id,
                        "progress_per_mille": event_schedule.trigger_progress_per_mille,
                        "resolved_at_ns": failure_at_ns,
                    },
                }
            )
            for offset, name in (
                (5, "RECOVERY_PLAN"),
                (10, "PROMPT_SUFFIX_RECOMPUTE_START"),
                (20, "PROMPT_SUFFIX_RECOMPUTE_COMPLETE"),
                (20, "SILENT_REPLAY_START"),
                (30, "SILENT_REPLAY_COMPLETE"),
                (30, "RECOVERY_ATOMIC_ACTIVATION"),
            ):
                recovery_events.append(
                    {
                        "timestamp_ns": failure_at_ns + offset,
                        "event": name,
                        "span_id": event_schedule.focus_span_id,
                    }
                )
            peer_hbm_timelines[event_schedule.target_gpu_id] = [
                {
                    "occupied_bytes": 0,
                    "committed_bytes": 0,
                    "pending_bytes": 0,
                    "unavailable_bytes": 0,
                },
                {
                    "occupied_bytes": 10,
                    "committed_bytes": 0,
                    "pending_bytes": 10,
                    "unavailable_bytes": 0,
                },
                {
                    "occupied_bytes": 0,
                    "committed_bytes": 0,
                    "pending_bytes": 0,
                    "unavailable_bytes": 100,
                },
                *(
                    [
                        {
                            "occupied_bytes": 0,
                            "committed_bytes": 0,
                            "pending_bytes": 0,
                            "unavailable_bytes": 0,
                        }
                    ]
                    if repair_completed_at_ns is not None
                    else []
                ),
            ]
    representative = (
        {
            "failure_events": failure_events,
            "recovery_events": recovery_events,
            "transfers": [
                {
                    "transfer_id": "transfer-committed",
                    "span_id": "span-0",
                    "status": "COMMITTED",
                    "bytes": 10,
                    "transferred_bytes": 10,
                    "aborted_bytes": 0,
                    "start_ns": 10,
                    "end_ns": 20,
                    "planned_end_ns": 20,
                    "terminal_ns": 20,
                    "resource_intervals": [
                        {"start_ns": 10, "actual_end_ns": 20, "planned_end_ns": 20}
                    ],
                },
                {
                    "transfer_id": "transfer-aborted",
                    "span_id": "span-0",
                    "status": "ABORTED",
                    "bytes": 10,
                    "transferred_bytes": 4,
                    "aborted_bytes": 6,
                    "start_ns": 90,
                    "end_ns": 100,
                    "planned_end_ns": 110,
                    "terminal_ns": 100,
                    "resource_intervals": [
                        {"start_ns": 90, "actual_end_ns": 100, "planned_end_ns": 110}
                    ],
                },
            ],
            "peer_hbm_timelines": peer_hbm_timelines,
            "store_dram_timelines": {
                "store-0:segment-0": [
                    {"occupied_bytes": 0, "committed_bytes": 0, "pending_bytes": 0},
                    {"occupied_bytes": 10, "committed_bytes": 0, "pending_bytes": 10},
                    {"occupied_bytes": 10, "committed_bytes": 10, "pending_bytes": 0},
                ]
            },
        }
        if failure
        else {}
    )
    return StudyRunResult(
        payload=_payload(spec),
        journal_sha256=hashlib.sha256(spec.pair_id.encode()).hexdigest(),
        span_details=({"span_id": "span-0"},) if failure else (),
        representative=representative,
    )


def _fake_schedule(
    _records: object,
    *,
    bucket: str,
    seed: int,
    parameters: ModelParameters,
    failure_count: int = 2,
    workflow_concurrency: int | None = None,
    compared_profiles: object = None,
) -> FailureSchedule:
    del workflow_concurrency, compared_profiles
    return FailureSchedule(
        tuple(
            FailureEventSchedule(
                failure_id=f"failure:{bucket}:{seed}:event-{event_index}",
                event_index=event_index,
                bucket=bucket,
                seed=seed,
                focus_span_id=f"span-{event_index}",
                target_gpu_id=f"gpu-{event_index}",
                reference_at_ns=100 + seed + event_index,
                target_workload_progress_per_mille=(
                    1_000 * (event_index + 1) + (failure_count + 1) // 2
                )
                // (failure_count + 1),
                reference_completed_workflow_count=event_index + 1,
                reference_workflow_count=failure_count + 1,
                detection_delay_ns=parameters.failure_detection_ns,
                trigger_progress_per_mille=parameters.failure_progress_per_mille,
                gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
            )
            for event_index in range(failure_count)
        )
    )


def _implementation() -> ImplementationBinding:
    return ImplementationBinding(commit="a" * 40, tree="b" * 40, worktree_clean=True)


def _workload() -> WorkloadBinding:
    return WorkloadBinding(
        declared_path="benchmark/AegisKV/experiments/workloads/frozen.jsonl",
        sha256="c" * 64,
        record_count=1,
        semantic_fingerprint="d" * 64,
        manifest_sha256="e" * 64,
        manifest_schema="moonkvsim.aegiskv.experiment_workload_manifest.v1",
    )


def _figure_inputs(matrix_dir: Path) -> dict[str, Any]:
    return {
        "matrix_results": {
            "file": "results.jsonl",
            "sha256": _sha256((matrix_dir / "results.jsonl").read_bytes()),
        },
        "matrix_manifest": {
            "file": "manifest.json",
            "sha256": _sha256((matrix_dir / "manifest.json").read_bytes()),
        },
        "representative_run": {
            "file": "representative-run.json",
            "sha256": _sha256((matrix_dir / "representative-run.json").read_bytes()),
        },
    }


def _write_figures(matrix_dir: Path, figure_dir: Path) -> None:
    figure_dir.mkdir()
    row = _read_jsonl(matrix_dir / "results.jsonl")[0]
    inputs = _figure_inputs(matrix_dir)
    entries: list[dict[str, Any]] = []
    for figure_id, stem in AUDIT.FIGURE_STEMS.items():
        point_id = f"{figure_id}-point-0"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            f"<text>{AUDIT.EVIDENCE_FOOTER}</text>"
            f'<g data-point-id="{point_id}" data-run-id="{row["run_id"]}" '
            f'data-result-hash="{row["payload_sha256"]}" />'
            "</svg>"
        ).encode()
        svg_name = f"{stem}.svg"
        provenance_name = f"{stem}.provenance.json"
        (figure_dir / svg_name).write_bytes(svg)
        provenance = {
            "schema": "moonkvsim.aegiskv.figure_provenance.v1",
            "figure_id": figure_id,
            "title": f"Figure {figure_id}",
            "generator": AUDIT.GENERATOR,
            "svg": {"file": svg_name, "sha256": _sha256(svg)},
            "inputs": inputs,
            "evidence": dict(AUDIT.FIGURE_EVIDENCE),
            "point_bindings": [
                {
                    "point_id": point_id,
                    "run_id": row["run_id"],
                    "result_hash": row["payload_sha256"],
                    "result_hash_kind": "payload_sha256",
                    "coordinates": {"x": 1, "y": 2},
                }
            ],
            "notes": [],
        }
        provenance_bytes = _canonical(provenance)
        (figure_dir / provenance_name).write_bytes(provenance_bytes)
        entries.append(
            {
                "figure_id": figure_id,
                "svg": {"file": svg_name, "sha256": _sha256(svg)},
                "provenance": {
                    "file": provenance_name,
                    "sha256": _sha256(provenance_bytes),
                },
                "point_count": 1,
            }
        )
    exclusion = {
        "schema": "moonkvsim.aegiskv.figure_exclusion.v1",
        "figure_id": "F12",
        "status": "EXCLUDED",
        "svg_generated": False,
        "reason": "simulator accuracy requires observed-vs-predicted E3/E4 evidence",
        "required_evidence": [
            "E3 modeled_with_physical_calibration",
            "E4 physical_baseline",
        ],
        "current_evidence": ("E2 modeled/preliminary; not calibrated; no physical experiment"),
        "evidence": dict(AUDIT.FIGURE_EVIDENCE),
        "paper_ready": False,
        "inputs": inputs,
    }
    exclusion_bytes = _canonical(exclusion)
    (figure_dir / AUDIT.F12_FILE).write_bytes(exclusion_bytes)
    manifest = {
        "schema": "moonkvsim.aegiskv.figure_set_manifest.v1",
        "status": "PASS",
        "generator": AUDIT.GENERATOR,
        "canonical_json": True,
        "evidence": dict(AUDIT.FIGURE_EVIDENCE),
        "evidence_footer": AUDIT.EVIDENCE_FOOTER,
        "inputs": inputs,
        "required_svg_figure_ids": list(AUDIT.REQUIRED_FIGURE_IDS),
        "excluded_figure_ids": ["F12"],
        "figures": entries,
        "exclusions": [
            {
                "figure_id": "F12",
                "file": AUDIT.F12_FILE,
                "sha256": _sha256(exclusion_bytes),
                "svg_generated": False,
            }
        ],
        "generated_artifact_count": 29,
        "point_binding_contract": {
            "required_fields": [
                "point_id",
                "run_id",
                "result_hash",
                "result_hash_kind",
                "coordinates",
            ],
            "result_hash_kind": "payload_sha256",
            "same_bindings_embedded_in_svg_data_attributes": True,
        },
        "paper_ready": False,
    }
    _write_json(figure_dir / "manifest.json", manifest)


@pytest.fixture
def bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Bundle:
    monkeypatch.setattr(suite, "derive_failure_schedule", _fake_schedule)
    monkeypatch.setattr(suite, "run_study_cell", _fake_run)
    config_source = tmp_path / "config-source"
    config_source.mkdir()
    _write_json(
        config_source / "requests.json",
        {
            "schema": "moonkvsim.aegiskv.requests.v1",
            "workload": {
                "frozen_artifact": {
                    "sha256": "c" * 64,
                    "record_count": 1,
                    "semantic_fingerprint": "d" * 64,
                }
            },
        },
    )
    _write_json(
        config_source / "failure.json",
        {
            "schema": "moonkvsim.aegiskv.failure.v1",
            "allowed_types": ["GPU_FAILURE"],
            "type": "GPU_FAILURE",
            "repair": {"enabled": False},
        },
    )
    _write_json(
        config_source / "engine.json",
        {
            "schema": "moonkvsim.aegiskv.engine.v1",
            "scope_id": "qwen3-8b-dp8-a100-40gb-single-node-v1",
            "parallelism": {
                "data_parallel_size": 8,
                "allowed_data_parallel_sizes": [8],
                "tensor_parallel_size": 1,
                "pipeline_parallel_size": 1,
            },
            "hardware": {"physical_hbm_bytes_per_gpu": 40 * 1024**3},
        },
    )
    matrix_dir = tmp_path / "matrix"
    run_e2_matrix(
        ({"record": "fake"},),
        workload=_workload(),
        implementation=_implementation(),
        output_dir=matrix_dir,
        selection="all",
        seeds=(0,),
        jobs=1,
        config_snapshot_dir=config_source,
    )
    figure_dir = tmp_path / "figures"
    _write_figures(matrix_dir, figure_dir)
    return Bundle(matrix_dir, figure_dir)


def _refresh_manifest(matrix_dir: Path) -> None:
    manifest_path = matrix_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    unhashed = dict(manifest)
    unhashed.pop("fingerprint", None)
    manifest["fingerprint"] = _sha256(
        json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    _write_json(manifest_path, manifest)


def _refresh_matrix_artifact(matrix_dir: Path, name: str) -> None:
    path = matrix_dir / name
    manifest = _read_json(matrix_dir / "manifest.json")
    manifest["artifact_hashes"][name] = {
        "sha256": _sha256(path.read_bytes()),
        "size_bytes": path.stat().st_size,
    }
    _write_json(matrix_dir / "manifest.json", manifest)
    _refresh_manifest(matrix_dir)


def _sync_result_bindings(matrix_dir: Path, rows: list[dict[str, Any]]) -> None:
    manifest = _read_json(matrix_dir / "manifest.json")
    manifest["result_bindings"] = [
        {
            "run_id": row["run_id"],
            "payload_sha256": row["payload_sha256"],
            "journal_sha256": row["journal_sha256"],
            "cell_fingerprint": row["bindings"]["cell_fingerprint"],
        }
        for row in rows
    ]
    _write_json(matrix_dir / "manifest.json", manifest)


def _refresh_document(matrix_dir: Path, name: str, manifest_field: str) -> None:
    path = matrix_dir / name
    document = _read_json(path)
    unhashed = dict(document)
    unhashed.pop("fingerprint", None)
    document["fingerprint"] = _sha256(
        json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    _write_json(path, document)
    manifest = _read_json(matrix_dir / "manifest.json")
    manifest[manifest_field] = document["fingerprint"]
    _write_json(matrix_dir / "manifest.json", manifest)
    _refresh_matrix_artifact(matrix_dir, name)


def _refresh_figure_artifact(figure_dir: Path, figure_id: str, kind: str) -> None:
    manifest_path = figure_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    entry = next(item for item in manifest["figures"] if item["figure_id"] == figure_id)
    name = entry[kind]["file"]
    entry[kind]["sha256"] = _sha256((figure_dir / name).read_bytes())
    _write_json(manifest_path, manifest)


def _assert_fail(bundle: Bundle, fragment: str) -> None:
    report = AUDIT.audit_artifacts(bundle.matrix, bundle.figures)
    assert report["status"] == "FAIL"
    assert fragment in report["errors"][0]
    assert report["physical_execution"] is False
    assert report["slurm_used"] is False


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_complete_bundle_passes_and_cli_emits_canonical_json(
    bundle: Bundle,
    capsys: pytest.CaptureFixture[str],
) -> None:
    matrix_before = _tree_hashes(bundle.matrix)
    figures_before = _tree_hashes(bundle.figures)
    report = AUDIT.audit_artifacts(bundle.matrix, bundle.figures)
    assert report["status"] == "PASS"
    assert report["matrix"]["artifact_count"] == 8
    assert report["matrix"]["result_count"] == 800
    assert report["matrix"]["pair_count"] == 400
    assert report["matrix"]["config_snapshot_binding"] == "manifest_bound"
    assert report["figures"]["required_svg_count"] == 14
    assert report["figures"]["excluded_figure_ids"] == ["F12"]
    assert report["evidence"]["class"] == "E2"
    assert report["evidence"]["physical_execution"] is False
    assert (
        AUDIT.main(["--matrix-dir", str(bundle.matrix), "--figure-dir", str(bundle.figures)]) == 0
    )
    stdout = capsys.readouterr().out.encode("utf-8")
    assert stdout == _canonical(json.loads(stdout))
    assert _tree_hashes(bundle.matrix) == matrix_before
    assert _tree_hashes(bundle.figures) == figures_before


def test_matrix_auditor_accepts_compact_failure_v2_snapshot(bundle: Bundle) -> None:
    path = bundle.matrix / "configs/failure.json"
    _write_json(
        path,
        {
            "schema": "moonkvsim.aegiskv.failure.v2",
            "type": "GPU_FAILURE",
            "conditioned_progress_per_mille": 100,
            "per_gpu_mttf_hours": 100_000,
            "gpu_recovery_time_hours": 0.88,
            "detection_delay_ms": 5,
        },
    )
    manifest = _read_json(bundle.matrix / "manifest.json")
    manifest["config_snapshot"]["files"]["failure.json"] = {
        "sha256": _sha256(path.read_bytes()),
        "size_bytes": path.stat().st_size,
    }
    _write_json(bundle.matrix / "manifest.json", manifest)
    _refresh_manifest(bundle.matrix)

    state = AUDIT._validate_matrix(bundle.matrix)
    assert state.config_snapshot_binding == "manifest_bound"


def test_matrix_auditor_accepts_minimal_engine_v2_snapshot(bundle: Bundle) -> None:
    path = bundle.matrix / "configs/engine.json"
    _write_json(
        path,
        _read_json(ROOT / "benchmark/AegisKV/experiments/configs/engine.json"),
    )
    rows = tuple(_read_jsonl(bundle.matrix / "results.jsonl"))
    provenance = _read_json(bundle.matrix / "provenance.json")
    protocol = _read_json(bundle.matrix / "protocol.json")
    scope = AUDIT._scope_for_contract(
        provenance["model_deployment_contract"],
        protocol,
    )
    AUDIT._validate_snapshot_configs(bundle.matrix, scope, rows, provenance)


def test_cli_failure_is_canonical_and_creates_no_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        AUDIT.main(
            [
                "--matrix-dir",
                str(tmp_path / "missing-matrix"),
                "--figure-dir",
                str(tmp_path / "missing-figures"),
            ]
        )
        == 1
    )
    stdout = capsys.readouterr().out.encode("utf-8")
    report = json.loads(stdout)
    assert report["status"] == "FAIL"
    assert stdout == _canonical(report)
    assert list(tmp_path.iterdir()) == []


def test_rejects_artifact_hash_tampering(bundle: Bundle) -> None:
    with (bundle.matrix / "results.jsonl").open("ab") as stream:
        stream.write(b" ")
    _assert_fail(bundle, "size")


def test_rejects_noncanonical_results_even_if_manifest_is_rehashed(bundle: Bundle) -> None:
    path = bundle.matrix / "results.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    lines[0] = json.dumps(first, sort_keys=True)  # deliberately non-canonical spaces
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _refresh_matrix_artifact(bundle.matrix, "results.jsonl")
    _assert_fail(bundle, "not canonical")


def test_rejects_duplicate_json_key(bundle: Bundle) -> None:
    manifest_path = bundle.matrix / "manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        text.replace('"status":"PASS"', '"status":"PASS","status":"PASS"', 1), encoding="utf-8"
    )
    _assert_fail(bundle, "duplicate JSON key")


def test_rejects_nan_in_canonical_input(bundle: Bundle) -> None:
    manifest = _read_json(bundle.figures / "manifest.json")
    manifest.pop("generated_artifact_count")
    text = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    text = text[:-1] + ',"generated_artifact_count":NaN}\n'
    (bundle.figures / "manifest.json").write_text(text, encoding="utf-8")
    _assert_fail(bundle, "non-finite JSON number")


def test_rejects_matrix_path_escape(bundle: Bundle) -> None:
    manifest = _read_json(bundle.matrix / "manifest.json")
    manifest["artifact_hashes"]["../results.jsonl"] = manifest["artifact_hashes"].pop(
        "results.jsonl"
    )
    _write_json(bundle.matrix / "manifest.json", manifest)
    _refresh_manifest(bundle.matrix)
    _assert_fail(bundle, "artifact_hashes files")


def test_rejects_payload_and_result_binding_tampering(bundle: Bundle) -> None:
    results_path = bundle.matrix / "results.jsonl"
    rows = _read_jsonl(results_path)
    rows[0]["payload"]["execution_scope"]["cuda_used"] = True
    _write_jsonl(results_path, rows)
    _refresh_matrix_artifact(bundle.matrix, "results.jsonl")
    _assert_fail(bundle, "execution_scope")


def test_rejects_model_deployment_scope_drift_after_outer_hash_is_rebound(
    bundle: Bundle,
) -> None:
    results_path = bundle.matrix / "results.jsonl"
    rows = _read_jsonl(results_path)
    rows[0]["model_deployment"]["model"]["id"] = "Other/Model"
    _write_jsonl(results_path, rows)
    _refresh_matrix_artifact(bundle.matrix, "results.jsonl")
    _assert_fail(bundle, "model_deployment")


def test_rejects_duplicate_run_id_after_outer_hashes_are_rebound(bundle: Bundle) -> None:
    results_path = bundle.matrix / "results.jsonl"
    rows = _read_jsonl(results_path)
    rows[1] = dict(rows[0])
    _write_jsonl(results_path, rows)
    _sync_result_bindings(bundle.matrix, rows)
    _refresh_matrix_artifact(bundle.matrix, "results.jsonl")
    _assert_fail(bundle, "unique")


def test_rejects_manifest_cell_fingerprint_rebinding(bundle: Bundle) -> None:
    manifest_path = bundle.matrix / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["result_bindings"][0]["cell_fingerprint"] = "f" * 64
    _write_json(manifest_path, manifest)
    _refresh_manifest(bundle.matrix)
    _assert_fail(bundle, "result_bindings")


def test_rejects_ab_pair_mismatch_after_outer_hashes_are_rebound(bundle: Bundle) -> None:
    results_path = bundle.matrix / "results.jsonl"
    rows = _read_jsonl(results_path)
    rows[1]["journal_sha256"] = "f" * 64
    _write_jsonl(results_path, rows)
    _sync_result_bindings(bundle.matrix, rows)
    _refresh_matrix_artifact(bundle.matrix, "results.jsonl")
    _assert_fail(bundle, "A/B exactness")


@pytest.mark.parametrize(
    ("name", "manifest_field", "mutation", "fragment"),
    (
        (
            "completeness.json",
            "completeness_fingerprint",
            lambda document: document.__setitem__("silent_fallback_count", 1),
            "silent_fallback_count",
        ),
        (
            "protocol.json",
            "protocol_fingerprint",
            lambda document: document.__setitem__("physical_or_slurm_path", True),
            "physical_or_slurm_path",
        ),
        (
            "provenance.json",
            "provenance_fingerprint",
            lambda document: document["execution"].__setitem__(
                "physical_components_executed", True
            ),
            "physical_components_executed",
        ),
        (
            "statistics.json",
            "statistics_fingerprint",
            lambda document: document["sampling_contract"].__setitem__(
                "included_repetition", "B"
            ),
            "statistics.json exact recomputation",
        ),
    ),
)
def test_rejects_semantic_documents_after_all_hashes_are_recomputed(
    bundle: Bundle,
    name: str,
    manifest_field: str,
    mutation: Any,
    fragment: str,
) -> None:
    path = bundle.matrix / name
    document = _read_json(path)
    mutation(document)
    _write_json(path, document)
    _refresh_document(bundle.matrix, name, manifest_field)
    _assert_fail(bundle, fragment)


def test_rejects_representative_drift_after_outer_hash_is_recomputed(bundle: Bundle) -> None:
    path = bundle.matrix / "representative-run.json"
    document = _read_json(path)
    document["payload_sha256"] = "f" * 64
    _write_json(path, document)
    _refresh_matrix_artifact(bundle.matrix, "representative-run.json")
    _assert_fail(bundle, "representative.payload_sha256")


def test_rejects_svg_tampering(bundle: Bundle) -> None:
    path = bundle.figures / "f1-system-architecture.svg"
    path.write_bytes(path.read_bytes() + b" ")
    _assert_fail(bundle, "SVG SHA-256")


def test_rejects_figure_input_and_point_binding_drift(bundle: Bundle) -> None:
    path = bundle.figures / "f1-system-architecture.provenance.json"
    provenance = _read_json(path)
    provenance["inputs"]["matrix_results"]["sha256"] = "f" * 64
    _write_json(path, provenance)
    _refresh_figure_artifact(bundle.figures, "F1", "provenance")
    _assert_fail(bundle, "provenance.inputs")


def test_rejects_point_binding_drift_after_provenance_is_rehashed(bundle: Bundle) -> None:
    path = bundle.figures / "f1-system-architecture.provenance.json"
    provenance = _read_json(path)
    provenance["point_bindings"][0]["result_hash"] = "f" * 64
    _write_json(path, provenance)
    _refresh_figure_artifact(bundle.figures, "F1", "provenance")
    _assert_fail(bundle, "result_hash")


def test_rejects_f12_svg_extra_figure_id_and_path_escape(bundle: Bundle) -> None:
    (bundle.figures / "f12-simulator-accuracy.svg").write_text("<svg />", encoding="utf-8")
    _assert_fail(bundle, "directory entries")


def test_rejects_missing_figure_and_extra_f16(bundle: Bundle) -> None:
    (bundle.figures / "f15-trace-coverage.svg").unlink()
    (bundle.figures / "f16-overclaim.svg").write_text("<svg />", encoding="utf-8")
    _assert_fail(bundle, "directory entries")


def test_rejects_figure_manifest_path_escape(bundle: Bundle) -> None:
    manifest_path = bundle.figures / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["figures"][0]["svg"]["file"] = "../f1-system-architecture.svg"
    _write_json(manifest_path, manifest)
    _assert_fail(bundle, "SVG file")


def test_rejects_f12_overclaim_after_hash_is_recomputed(bundle: Bundle) -> None:
    exclusion_path = bundle.figures / AUDIT.F12_FILE
    exclusion = _read_json(exclusion_path)
    exclusion["svg_generated"] = True
    _write_json(exclusion_path, exclusion)
    manifest_path = bundle.figures / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["exclusions"][0]["sha256"] = _sha256(exclusion_path.read_bytes())
    _write_json(manifest_path, manifest)
    _assert_fail(bundle, "F12 exclusion.svg_generated")
