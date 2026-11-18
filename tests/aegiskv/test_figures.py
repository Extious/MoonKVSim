from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.aegiskv.experiment_suite import DEFAULT_SEEDS, EXPECTED_VARIANT_IDS
from moonkvsim.aegiskv.figures import (
    EVIDENCE_FOOTER,
    ExistingFigureError,
    FigureInputError,
    generate_e2_figures,
)
from moonkvsim.common.hash import sha256_json


def _payload(*, bucket: str, scenario: str, ordinal: int, seed: int) -> dict[str, Any]:
    failed = scenario == "gpu_failure"
    peer_peak = 1_000 + ordinal * 10
    store_peak = 2_000 + ordinal * 20
    return {
        "schema": "moonkvsim.aegiskv.study_run_payload.v1",
        "status": "PASS",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "physical_timing_claim_allowed": False,
            "formal_use_allowed": False,
            "paper_ready": False,
        },
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
        "resource_model": {
            "peer_hbm_resources": [],
            "store_dram_segments": [],
            "copy_engines": [],
            "fabric_resources": [],
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
        "workload": {"no_truncation_or_padding": True},
        "context_bucket": bucket,
        "scenario": scenario,
        "failure_schedule": (
            {
                "failure_id": "failure-1",
                "type": "GPU_FAILURE",
                "bucket": bucket,
                "seed": seed,
                "focus_span_id": "span-8k",
                "target_gpu_id": "gpu-0",
                "at_ns": 100,
                "detection_delay_ns": 0,
                "selection_scope": "same_context_bucket_active_in_every_core_system",
                "repair_after_ns": None,
                "parameter_source": "deterministic_core_interval_intersection_global_des",
            }
            if failed
            else None
        ),
        "output_audit": {
            "expected_output_tokens": 10,
            "external_output_tokens": 10,
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
        "metrics": {
            "virtual_end_ns": 1_000 + ordinal,
            "workflow_completion_time_ns": {
                "mean": 500_000 + ordinal * 1_000,
                "p95": 600_000 + ordinal * 1_000,
                "max": 700_000 + ordinal * 1_000,
            },
            "goodput_output_tokens_per_second_milli": 50_000 + ordinal * 100,
            "restored_tokens": {
                "peer_hbm": 30 if failed else 0,
                "store_dram": 20 if failed else 0,
                "total": 50 if failed else 0,
            },
            "recompute_tokens_after_failure": 10 if failed else 0,
            "recovery_latency_ns": {
                "count": 1 if failed else 0,
                "mean": 40 + ordinal if failed else 0,
                "p95": 40 + ordinal if failed else 0,
            },
            "resource_cost": {
                "peer_hbm_peak_bytes": peer_peak,
                "peer_hbm_byte_ns": peer_peak * 500,
                "store_dram_peak_bytes": store_peak,
                "store_dram_byte_ns": store_peak * 400,
                "peer_hbm_by_gpu": {
                    "gpu-0": {
                        "peak_bytes": peer_peak * 3 // 5,
                        "byte_ns": peer_peak * 300,
                    },
                    "gpu-1": {
                        "peak_bytes": peer_peak * 2 // 5,
                        "byte_ns": peer_peak * 200,
                    },
                },
                "store_dram_by_segment": {
                    "store-0:segment-0": {
                        "peak_bytes": store_peak,
                        "byte_ns": store_peak * 400,
                    }
                },
                "network_byte_ns": {"AEGIS_TRANSFER": 700 + ordinal},
                "copy_engine_busy_ns": {"AEGIS_TRANSFER": 90 + ordinal},
                "cause_bytes": {"AEGIS_TRANSFER": 80 + ordinal},
            },
        },
    }


def _row(
    *,
    run_id: str,
    suite: str,
    variant_id: str,
    bucket: str,
    scenario: str,
    ordinal: int,
    repetition: str,
    seed: int = 7,
) -> dict[str, Any]:
    payload = _payload(bucket=bucket, scenario=scenario, ordinal=ordinal, seed=seed)
    dp_count = 8
    peer_hbm_alpha_percent = (
        int(variant_id.split("=", 1)[1])
        if variant_id.startswith("peer_hbm_alpha_percent=")
        else 20
    )
    store_budget_gib = (
        int(variant_id.split("=", 1)[1]) if variant_id.startswith("store_budget_gib=") else 64
    )
    store_bandwidth_gbps = (
        int(variant_id.split("=", 1)[1]) if variant_id.startswith("store_bandwidth_gbps=") else 25
    )
    peer_bandwidth_gbps = (
        int(variant_id.split("=", 1)[1])
        if variant_id.startswith("peer_fabric_bandwidth_gbps=")
        else 100
    )
    reroute_delay_ms = (
        int(variant_id.split("=", 1)[1]) if variant_id.startswith("reroute_delay_ms=") else 1
    )
    parameters = {
        "dp_count": dp_count,
        "physical_hbm_bytes_per_gpu": 40 * 1024**3,
        "peer_hbm_alpha": peer_hbm_alpha_percent / 100,
        "store_budget_bytes": store_budget_gib * 1024**3,
        "peer_bandwidth_bytes_per_second": peer_bandwidth_gbps * 1_000_000_000,
        "store_bandwidth_bytes_per_second": store_bandwidth_gbps * 1_000_000_000,
        "failure_detection_ns": 0,
        "reroute_ns": reroute_delay_ms * 1_000_000,
    }
    variant_config = {
        "suite": suite,
        "variant_id": variant_id,
        "parameters": parameters,
    }
    variant_fingerprint = sha256_json(variant_config)
    parameters_fingerprint = sha256_json(parameters)
    failure_schedule_fingerprint = (
        sha256_json(payload["failure_schedule"])
        if scenario == "gpu_failure"
        else sha256_json({"scenario": "no_failure", "failure_schedule": None})
    )
    failure_binding_fingerprint = (
        sha256_json(
            {
                "parameters_fingerprint": parameters_fingerprint,
                "failure_schedule_fingerprint": failure_schedule_fingerprint,
            }
        )
        if scenario == "gpu_failure"
        else failure_schedule_fingerprint
    )
    matched_input = {
        "implementation_fingerprint": "d" * 64,
        "workload_fingerprint": "b" * 64,
        "protocol_fingerprint": "e" * 64,
        "variant_fingerprint": variant_fingerprint,
        "parameters_fingerprint": parameters_fingerprint,
        "context_bucket": bucket,
        "scenario": scenario,
        "seed": seed,
        "failure_schedule_fingerprint": failure_schedule_fingerprint,
        "failure_binding_fingerprint": failure_binding_fingerprint,
    }
    matched_input_fingerprint = sha256_json(matched_input)
    payload["variant_fingerprint"] = variant_fingerprint
    return {
        "schema": "moonkvsim.aegiskv.e2_matrix_suite.v1.result_row",
        "status": "PASS",
        "run_id": run_id,
        "pair_id": run_id.rsplit(":repeat-", 1)[0],
        "suite": suite,
        "variant_id": variant_id,
        "context_bucket": bucket,
        "scenario": scenario,
        "seed": seed,
        "repetition": repetition,
        "fresh_global_des_instance": True,
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "physical_timing_claim_allowed": False,
            "formal_use_allowed": False,
            "paper_ready": False,
            "slurm_used": False,
        },
        "result_payload_sha256": sha256_json(payload),
        "journal_sha256": f"{ordinal + 1:064x}",
        "bindings": {
            **matched_input,
            "workload_sha256": "a" * 64,
            "matched_input_fingerprint": matched_input_fingerprint,
            "cell_fingerprint": sha256_json(
                {
                    "matched_input_fingerprint": matched_input_fingerprint,
                    "repetition": repetition,
                }
            ),
            "implementation_commit": "1" * 40,
        },
        "variant_config": variant_config,
        "payload": payload,
    }


def _fixture_bundle(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    ordinal = 0
    for suite, variants in EXPECTED_VARIANT_IDS.items():
        for variant_id in variants:
            for bucket in ("8k", "32k", "64k", "96k", "128k"):
                for scenario in ("no_failure", "gpu_failure"):
                    for seed in DEFAULT_SEEDS:
                        for repetition in ("A", "B"):
                            rows.append(
                                _row(
                                    run_id=(
                                        f"{suite}:{variant_id}:{bucket}:{scenario}:"
                                        f"seed-{seed}:repeat-{repetition}"
                                    ),
                                    suite=suite,
                                    variant_id=variant_id,
                                    bucket=bucket,
                                    scenario=scenario,
                                    ordinal=ordinal,
                                    repetition=repetition,
                                    seed=seed,
                                )
                            )
                        ordinal += 1
    results_path = root / "results.jsonl"
    results_bytes = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
            "utf-8"
        )
        for row in rows
    )
    results_path.write_bytes(results_bytes)
    results_sha256 = hashlib.sha256(results_bytes).hexdigest()
    manifest: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.e2_matrix_suite.v1.manifest",
        "status": "PASS",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "physical_timing_claim_allowed": False,
            "formal_use_allowed": False,
            "paper_ready": False,
            "slurm_used": False,
        },
        "artifact_hashes": {
            "provenance.json": {"sha256": "c" * 64},
            "results.jsonl": {
                "sha256": results_sha256,
                "size_bytes": len(results_bytes),
            },
        },
        "result_count": len(rows),
        "pair_count": len(rows) // 2,
        "result_bindings": [
            {
                "run_id": row["run_id"],
                "payload_sha256": row["result_payload_sha256"],
                "journal_sha256": row["journal_sha256"],
            }
            for row in rows
        ],
        "workload": {
            "context_bucket_counts": dict(
                zip(("8k", "32k", "64k", "96k", "128k"), (4, 5, 53, 35, 20), strict=True)
            )
        },
    }
    representative_row = next(
        row
        for row in rows
        if row["suite"] == "core"
        and row["variant_id"] == "aegiskv_unified"
        and row["context_bucket"] == "128k"
        and row["scenario"] == "gpu_failure"
        and row["seed"] == 0
        and row["repetition"] == "A"
    )
    representative = {
        "schema": "moonkvsim.aegiskv.e2_matrix_suite.v1.representative_run",
        "status": "PASS",
        "run_id": representative_row["run_id"],
        "payload_sha256": representative_row["result_payload_sha256"],
        "journal_sha256": representative_row["journal_sha256"],
        "evidence": representative_row["evidence"],
        "bindings": representative_row["bindings"],
        "variant_config": representative_row["variant_config"],
        "payload": representative_row["payload"],
        "representative": {
            "failure_events": [
                {
                    "timestamp_ns": 100,
                    "event": "FAILURE_INJECT",
                    "target_gpu_id": "gpu-0",
                    "impacted_active_span_ids": ["span-8k"],
                    "impacted_queued_span_ids": [],
                }
            ],
            "recovery_events": [
                {
                    "timestamp_ns": 110,
                    "event": "RECOVERY_PLAN",
                    "span_id": "span-8k",
                    "source_tokens": {"PEER_HBM": 30, "STORE_DRAM": 20, "RECOMPUTE": 10},
                },
                {
                    "timestamp_ns": 135,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                    "span_id": "span-8k",
                },
                {
                    "timestamp_ns": 140,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                    "span_id": "span-8k",
                },
                {
                    "timestamp_ns": 140,
                    "event": "SILENT_REPLAY_START",
                    "span_id": "span-8k",
                },
                {
                    "timestamp_ns": 150,
                    "event": "SILENT_REPLAY_COMPLETE",
                    "span_id": "span-8k",
                },
                {
                    "timestamp_ns": 150,
                    "event": "RECOVERY_ATOMIC_ACTIVATION",
                    "span_id": "span-8k",
                },
            ],
            "transfers": [
                {
                    "transfer_id": "transfer-peer-1",
                    "path": "D2D_P2P",
                    "cause": "AEGIS_PEER_HBM_PROTECTION",
                    "start_ns": 10,
                    "end_ns": 40,
                    "bytes": 1000,
                    "source": "gpu-0",
                },
                {
                    "transfer_id": "transfer-store-1",
                    "path": "SOURCE_D2H_STORE",
                    "cause": "AEGIS_STORE_DRAM_PROTECTION",
                    "start_ns": 42,
                    "end_ns": 90,
                    "bytes": 2000,
                    "source": "gpu-0",
                },
                {
                    "transfer_id": "recovery-store-span-8k",
                    "path": "STORE_H2D",
                    "cause": "AEGIS_RECOVERY_STORE_DRAM",
                    "start_ns": 115,
                    "end_ns": 135,
                    "bytes": 500,
                    "source": "store-0:segment-0",
                },
            ],
            "peer_hbm_timeline": [
                {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
                {"timestamp_ns": 40, "occupied_bytes": 1000, "cause": "PUT_COMMIT"},
                {"timestamp_ns": 100, "occupied_bytes": 500, "cause": "GPU_FAILURE"},
            ],
            "peer_hbm_timelines": {
                "gpu-0": [
                    {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
                    {"timestamp_ns": 40, "occupied_bytes": 600, "cause": "PUT_COMMIT"},
                ],
                "gpu-1": [
                    {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
                    {"timestamp_ns": 50, "occupied_bytes": 400, "cause": "PUT_COMMIT"},
                ],
            },
            "store_dram_timeline": [
                {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
                {"timestamp_ns": 90, "occupied_bytes": 2000, "cause": "PUT_COMMIT"},
            ],
            "store_dram_timelines": {
                "store-0:segment-0": [
                    {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
                    {"timestamp_ns": 90, "occupied_bytes": 2000, "cause": "PUT_COMMIT"},
                ]
            },
        },
        "span_details": [
            {
                "span_id": f"span-{bucket}",
                "context_bucket": bucket,
                "compute_start_ns": 135 if bucket == "8k" else 0,
                "completed_ns": 180 if bucket == "8k" else 90,
            }
            for bucket in ("8k", "32k", "64k", "96k", "128k")
        ],
    }
    representative_path = root / "representative-run.json"
    representative_bytes = (
        json.dumps(representative, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    representative_path.write_bytes(representative_bytes)
    manifest["artifact_hashes"]["representative-run.json"] = {
        "sha256": hashlib.sha256(representative_bytes).hexdigest(),
        "size_bytes": len(representative_bytes),
    }
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return results_path, manifest_path, representative_path


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _rewrite_representative_and_relock(
    representative_path: Path,
    manifest_path: Path,
    representative: dict[str, Any],
) -> None:
    representative_bytes = _canonical_bytes(representative)
    representative_path.write_bytes(representative_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_hashes"]["representative-run.json"] = {
        "sha256": hashlib.sha256(representative_bytes).hexdigest(),
        "size_bytes": len(representative_bytes),
    }
    manifest.pop("fingerprint")
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_path.write_bytes(_canonical_bytes(manifest))


def test_complete_set_is_deterministic_valid_xml_and_provenance_bound(tmp_path: Path) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = generate_e2_figures(
        results_path=results,
        manifest_path=manifest,
        representative_path=representative,
        output_dir=first_dir,
    )
    second = generate_e2_figures(
        results_path=results,
        manifest_path=manifest,
        representative_path=representative,
        output_dir=second_dir,
    )
    assert {artifact.figure_id for artifact in first.artifacts} == {
        *(f"F{index}" for index in range(1, 12)),
        "F12",
        "F13",
        "F14",
        "F15",
    }
    first_files = {path.name: path.read_bytes() for path in first_dir.iterdir()}
    second_files = {path.name: path.read_bytes() for path in second_dir.iterdir()}
    assert first_files == second_files
    assert first.results_sha256 == second.results_sha256
    set_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert set_manifest["required_svg_figure_ids"] == [
        *(f"F{index}" for index in range(1, 12)),
        "F13",
        "F14",
        "F15",
    ]
    assert set_manifest["excluded_figure_ids"] == ["F12"]
    assert set_manifest["generated_artifact_count"] == 29
    assert len(set_manifest["figures"]) == 14
    assert all(_manifest_entry_hashes_match(first_dir, entry) for entry in set_manifest["figures"])
    for json_path in first_dir.glob("*.json"):
        value = json.loads(json_path.read_text(encoding="utf-8"))
        assert json_path.read_bytes() == (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    svg_paths = sorted(first_dir.glob("*.svg"))
    assert len(svg_paths) == 14
    renderer_source_sha256 = hashlib.sha256(
        Path(generate_e2_figures.__code__.co_filename).read_bytes()
    ).hexdigest()
    for svg_path in svg_paths:
        root = ET.parse(svg_path).getroot()
        svg_text = svg_path.read_text(encoding="utf-8")
        assert EVIDENCE_FOOTER in svg_text
        groups = [element for element in root.iter() if "data-point-id" in element.attrib]
        assert groups
        assert all(_element_has_binding(element) for element in groups)
        sidecar_path = svg_path.with_suffix(".provenance.json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["figure_id"].startswith("F")
        assert sidecar["evidence"]["paper_ready"] is False
        assert sidecar["point_bindings"]
        assert sidecar["svg"]["sha256"] == hashlib.sha256(svg_path.read_bytes()).hexdigest()
        assert f"renderer_source_sha256={renderer_source_sha256}" in sidecar["notes"]
        assert all(
            binding["run_id"] and len(binding["result_hash"]) == 64
            for binding in sidecar["point_bindings"]
        )

    f2_sidecar = json.loads(
        next(first_dir.glob("f2-*.provenance.json")).read_text(encoding="utf-8")
    )
    f2_events = {
        (binding["coordinates"]["event"], binding["coordinates"]["timestamp_ns"])
        for binding in f2_sidecar["point_bindings"]
    }
    assert ("execution/data-path fence (immediate)", 100) in f2_events
    assert ("detection (schedule-derived)", 100) in f2_events
    assert ("reroute / recovery plan", 110) in f2_events
    assert ("aggregate recovery transfer start", 115) in f2_events
    assert ("aggregate recovery transfer end", 135) in f2_events
    assert ("prompt suffix recompute start", 135) in f2_events
    assert ("prompt suffix recompute complete", 140) in f2_events
    assert ("silent replay start", 140) in f2_events
    assert ("silent replay complete", 150) in f2_events
    assert ("atomic activation / resume", 150) in f2_events
    assert ("affected requests complete", 180) not in f2_events
    assert "atomic activation / resume" in {event for event, _timestamp in f2_events}
    assert {
        "execution_data_path_fence_is_immediate_at_failure_in_current_runtime",
        "transfer_markers_are_aggregate_D2D_P2P_and_STORE_H2D_bounds_not_per_span_load",
        "representative_transfer_records_lack_span_id_so_no_single_span_causal_chain_is_claimed",
        "explicit_resume_event_present",
        "prompt_suffix_recompute_precedes_silent_replay_on_the_global_clock",
    }.issubset(f2_sidecar["notes"])

    f1_svg = next(first_dir.glob("f1-*.svg")).read_text(encoding="utf-8")
    f1_sidecar = json.loads(
        next(first_dir.glob("f1-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert "Design schematic only; not runtime-component execution proof" in f1_svg
    assert f1_sidecar["notes"][0] == "design_schematic_not_runtime_component_execution_proof"

    f3_svg = next(first_dir.glob("f3-*.svg")).read_text(encoding="utf-8")
    f3_sidecar = json.loads(
        next(first_dir.glob("f3-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert "Peer protection committed/pending occupancy" in f3_svg
    assert f3_sidecar["notes"][0].startswith("peer_protection_pool_only_excludes_")

    f4_svg = next(first_dir.glob("f4-*.svg")).read_text(encoding="utf-8")
    f4_sidecar = json.loads(
        next(first_dir.glob("f4-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert "Store committed and pending destination occupancy" in f4_svg
    assert f4_sidecar["notes"][0].startswith("store_pool_tracks_committed_and_pending_")

    f5_sidecar = json.loads(
        next(first_dir.glob("f5-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert f5_sidecar["notes"][0].startswith("terminal_transfer_rows_conserve_")

    f7_sidecar = json.loads(
        next(first_dir.glob("f7-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert f7_sidecar["notes"][0].startswith("ecdf_samples_are_per_run_recovery_means_")

    f13_sidecar = json.loads(
        next(first_dir.glob("f13-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert "staging_peak_unavailable_in_canonical_E2_payload" in f13_sidecar["notes"]

    f14_sidecar = json.loads(
        next(first_dir.glob("f14-*.provenance.json")).read_text(encoding="utf-8")
    )
    assert all(
        binding["coordinates"]["p95_available"] is False
        for binding in f14_sidecar["point_bindings"]
    )

    f15_svg = next(first_dir.glob("f15-*.svg")).read_text(encoding="utf-8")
    f15_sidecar = json.loads(
        next(first_dir.glob("f15-*.provenance.json")).read_text(encoding="utf-8")
    )
    representative_run_id = json.loads(representative.read_text(encoding="utf-8"))["run_id"]
    assert "not target-tokenizer-equivalent" in f15_svg
    assert {
        "source_hash_blocks_64_are_not_target_tokenizer_equivalent_token_ids",
        "counts_are_derived_only_from_representative_span_details_and_bind_the_representative_row",
        (
            "workload_manifest_sha256_not_directly_available;matrix_manifest_declared_"
            "suite_provenance_hash_recorded_but_not_resolved"
        ),
    }.issubset(f15_sidecar["notes"])
    assert all(
        binding["coordinates"]["target_tokenizer_equivalence"] is False
        and binding["coordinates"]["matrix_manifest_declared_suite_provenance_sha256"] == "c" * 64
        and binding["coordinates"]["count_source"] == "representative.span_details"
        and binding["run_id"] == representative_run_id
        for binding in f15_sidecar["point_bindings"]
    )


def _element_has_binding(element: ET.Element) -> bool:
    return bool(element.attrib["data-run-id"]) and len(element.attrib["data-result-hash"]) == 64


def _manifest_entry_hashes_match(root: Path, entry: dict[str, Any]) -> bool:
    return all(
        hashlib.sha256((root / entry[kind]["file"]).read_bytes()).hexdigest()
        == entry[kind]["sha256"]
        for kind in ("svg", "provenance")
    )


def test_f12_is_exclusion_only_and_existing_targets_fail_closed(tmp_path: Path) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    output = tmp_path / "figures"
    generate_e2_figures(
        results_path=results,
        manifest_path=manifest,
        representative_path=representative,
        output_dir=output,
    )
    assert not list(output.glob("f12-*.svg"))
    exclusion = json.loads(
        (output / "f12-simulator-accuracy.excluded.json").read_text(encoding="utf-8")
    )
    assert exclusion["status"] == "EXCLUDED"
    assert exclusion["svg_generated"] is False
    assert exclusion["paper_ready"] is False
    assert exclusion["evidence"]["formal_use_allowed"] is False
    with pytest.raises(ExistingFigureError, match="refusing to overwrite"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=output,
        )


def test_incomplete_matrix_is_rejected_before_drawing(tmp_path: Path) -> None:
    results, manifest_path, representative = _fixture_bundle(tmp_path / "inputs")
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    removed = rows.pop()
    results_bytes = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(
            "utf-8"
        )
        for row in rows
    )
    results.write_bytes(results_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_hashes"]["results.jsonl"]["sha256"] = hashlib.sha256(
        results_bytes
    ).hexdigest()
    manifest["artifact_hashes"]["results.jsonl"]["size_bytes"] = len(results_bytes)
    manifest["result_count"] = len(rows)
    manifest["result_bindings"] = [
        binding for binding in manifest["result_bindings"] if binding["run_id"] != removed["run_id"]
    ]
    manifest["fingerprint"] = sha256_json(
        {key: value for key, value in manifest.items() if key != "fingerprint"}
    )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(FigureInputError, match="missing an exact A/B pair"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest_path,
            representative_path=representative,
            output_dir=tmp_path / "figures",
        )
    assert not (tmp_path / "figures").exists()


def test_representative_content_is_hash_locked_before_rendering(tmp_path: Path) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    document = json.loads(representative.read_text(encoding="utf-8"))
    document["span_details"][0]["completed_ns"] += 1
    representative.write_bytes(_canonical_bytes(document))
    output = tmp_path / "figures"
    with pytest.raises(FigureInputError, match=r"representative-run\.json SHA-256 mismatch"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=output,
        )
    assert not output.exists()


def test_nested_decoy_hash_cannot_bypass_exact_results_artifact_binding(
    tmp_path: Path,
) -> None:
    results, manifest_path, representative = _fixture_bundle(tmp_path / "inputs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = manifest["artifact_hashes"]["results.jsonl"]
    manifest["artifact_hashes"]["results.jsonl"] = {
        "sha256": "0" * 64,
        "size_bytes": actual["size_bytes"],
    }
    manifest["decoy"] = {"results.jsonl": actual}
    manifest.pop("fingerprint")
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_path.write_bytes(_canonical_bytes(manifest))
    with pytest.raises(FigureInputError, match=r"results\.jsonl SHA-256 mismatch"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest_path,
            representative_path=representative,
            output_dir=tmp_path / "figures",
        )


@pytest.mark.parametrize("mutation", ["cuda_scope", "forbidden_semantics"])
def test_non_e2_execution_or_forbidden_semantics_are_rejected_before_manifest_use(
    tmp_path: Path,
    mutation: str,
) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    row = rows[0]
    if mutation == "cuda_scope":
        row["payload"]["execution_scope"]["cuda_used"] = True
        expected = "execution_scope.cuda_used"
    else:
        row["payload"]["forbidden_semantics"]["target_owned_destage_count"] = 1
        expected = "forbidden semantics"
    row["result_payload_sha256"] = sha256_json(row["payload"])
    results.write_bytes(b"".join(_canonical_bytes(item) for item in rows))
    with pytest.raises(FigureInputError, match=expected):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=tmp_path / "figures",
        )


@pytest.mark.parametrize(
    ("binding_field", "expected"),
    [
        ("parameters_fingerprint", "parameters fingerprint drift"),
        ("failure_schedule_fingerprint", "failure schedule fingerprint drift"),
    ],
)
def test_locally_derivable_binding_fingerprint_drift_is_rejected(
    tmp_path: Path,
    binding_field: str,
    expected: str,
) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    rows[0]["bindings"][binding_field] = "0" * 64
    results.write_bytes(b"".join(_canonical_bytes(item) for item in rows))
    with pytest.raises(FigureInputError, match=expected):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=tmp_path / "figures",
        )


@pytest.mark.parametrize("mutation", ["fractional_transfer", "nonmonotonic_pool"])
def test_fractional_or_nonmonotonic_representative_events_are_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    results, manifest, representative_path = _fixture_bundle(tmp_path / "inputs")
    representative = json.loads(representative_path.read_text(encoding="utf-8"))
    if mutation == "fractional_transfer":
        representative["representative"]["transfers"][0]["start_ns"] = 1.5
        expected = "expected non-negative integer"
    else:
        representative["representative"]["peer_hbm_timelines"]["gpu-0"] = [
            {"timestamp_ns": 40, "occupied_bytes": 600, "cause": "PUT_COMMIT"},
            {"timestamp_ns": 0, "occupied_bytes": 0, "cause": "INITIAL"},
        ]
        expected = "timestamps must be non-decreasing"
    _rewrite_representative_and_relock(representative_path, manifest, representative)
    with pytest.raises(FigureInputError, match=expected):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative_path,
            output_dir=tmp_path / "figures",
        )


def test_overwrite_rejects_unexpected_f12_svg_and_preserves_it(tmp_path: Path) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    output = tmp_path / "figures"
    output.mkdir()
    forbidden = output / "f12-simulator-accuracy.svg"
    forbidden.write_text("sentinel", encoding="utf-8")
    with pytest.raises(ExistingFigureError, match="unexpected or non-regular"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=output,
            overwrite=True,
        )
    assert forbidden.read_text(encoding="utf-8") == "sentinel"


def test_failed_directory_swap_rolls_back_previous_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, manifest, representative = _fixture_bundle(tmp_path / "inputs")
    output = tmp_path / "figures"
    generate_e2_figures(
        results_path=results,
        manifest_path=manifest,
        representative_path=representative,
        output_dir=output,
    )
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    original_replace = os.replace
    call_count = 0

    def fail_promotion(source: Path, target: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("injected promotion failure")
        original_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_promotion)
    with pytest.raises(FigureInputError, match="cannot publish figure bundle"):
        generate_e2_figures(
            results_path=results,
            manifest_path=manifest,
            representative_path=representative,
            output_dir=output,
            overwrite=True,
        )
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert after == before
    assert not list(tmp_path.glob(".figures.staging-*"))
    assert not list(tmp_path.glob(".figures.backup-*"))
