#!/usr/bin/env python3
"""Bind non-estimand mechanism telemetry from the frozen SGLSim campaign.

The script copies the already-rendered reuse/recovery figure and records the
exact alpha, occupancy, reuse, residency, and restored-token aggregates used
by the paper.  It never launches the simulator or any serving runtime.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


PAPER_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ROOT = Path(
    "/home/comp/zhanzhao/sglsim/AegisKV/experiments/sglsim_large_scale_v2/"
    "results/campaign_v2/4a99c306e8f9/analysis-full"
)
FIGURE_MANIFEST = ANALYSIS_ROOT / "figures-polished/figure_manifest.json"
SOURCE_PDF = ANALYSIS_ROOT / "figures-polished/fig06_reuse_and_recovery.pdf"
SOURCE_PNG = ANALYSIS_ROOT / "figures-polished/fig06_reuse_and_recovery.png"
TRACE_DIAGNOSTICS = ANALYSIS_ROOT / "trace_workload_diagnostics.json"
SCENARIO_DIAGNOSTICS = ANALYSIS_ROOT / "scenario_diagnostics.json"
REUSE_BINS = ANALYSIS_ROOT / "active_source_probe_reuse_bins.csv"
OUTPUT_PDF = PAPER_ROOT / "figures/sim-fig06_reuse_and_recovery.pdf"
OUTPUT_PNG = PAPER_ROOT / "figures/sim-fig06_reuse_and_recovery.png"
MANIFEST = PAPER_ROOT / "figures/current-mechanism-supplement.manifest.json"

CENTRAL = (
    "qwen3_8b-c128-f5p952-g64-ctx0p016-net10p0-"
    "hbm4p0-dram64p0-e1p0"
)
RATE_ZERO = (
    "qwen3_8b-c128-f0p0-g64-ctx0p016-net10p0-"
    "hbm4p0-dram64p0-e1p0"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def scenario_map() -> dict[str, dict[str, object]]:
    payload = json.loads(SCENARIO_DIAGNOSTICS.read_text(encoding="utf-8"))
    return {str(row["scenario_id"]): row for row in payload["rows"]}


def row_metrics(row: dict[str, object]) -> dict[str, float]:
    return {
        "pressure_fraction_mean": float(row["pressure_fraction_mean"]),
        "effective_alpha_mean": float(row["effective_alpha_mean"]),
        "effective_alpha_zero_window_fraction": float(
            row["effective_alpha_zero_window_fraction"]
        ),
        "hbm_occupancy_mean_fraction": float(row["hbm_occupancy_mean_fraction"]),
        "dram_occupancy_mean_fraction": float(
            row["dram_occupancy_mean_fraction"]
        ),
        "copy_amplification_pooled": float(row["copy_amplification_pooled"]),
        "restored_token_fraction": 1.0
        - float(row["probe_recompute_fraction_pooled_tokens"]),
    }


def aggregate_reuse_bins() -> dict[str, dict[str, object]]:
    bins = ("none", "partial", "high", "near_complete")
    numeric = (
        "request_count_full_workload",
        "prompt_tokens_full_workload",
        "intended_residency_hbm_only_chunks",
        "intended_residency_dram_only_chunks",
        "intended_residency_hbm_and_dram_chunks",
        "intended_residency_bypass_chunks",
        "probe_restored_tokens",
        "probe_recomputed_tokens",
    )
    totals = {name: {key: 0.0 for key in numeric} for name in bins}
    with REUSE_BINS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["scenario_id"] != RATE_ZERO or row["policy"] != "aegiskv_alg111":
                continue
            name = row["input_reuse_bin"]
            if name not in totals:
                continue
            for key in numeric:
                totals[name][key] += float(row[key])

    request_total = sum(item["request_count_full_workload"] for item in totals.values())
    token_total = sum(item["prompt_tokens_full_workload"] for item in totals.values())
    result: dict[str, dict[str, object]] = {}
    for name in bins:
        item = totals[name]
        residency_keys = (
            "intended_residency_hbm_only_chunks",
            "intended_residency_dram_only_chunks",
            "intended_residency_hbm_and_dram_chunks",
            "intended_residency_bypass_chunks",
        )
        residency_total = sum(item[key] for key in residency_keys)
        recovery_total = item["probe_restored_tokens"] + item["probe_recomputed_tokens"]
        result[name] = {
            "request_fraction": item["request_count_full_workload"] / request_total,
            "prompt_token_fraction": item["prompt_tokens_full_workload"] / token_total,
            "residency_fraction": {
                key.removeprefix("intended_residency_").removesuffix("_chunks"):
                item[key] / residency_total
                for key in residency_keys
            },
            "restored_token_fraction": item["probe_restored_tokens"] / recovery_total,
        }
    return result


def metrics() -> dict[str, object]:
    rows = scenario_map()
    trace = json.loads(TRACE_DIAGNOSTICS.read_text(encoding="utf-8"))
    concurrency_ids = {
        "32": CENTRAL.replace("c128", "c32"),
        "64": CENTRAL.replace("c128", "c64"),
        "128": CENTRAL,
        "224": CENTRAL.replace("c128", "c224"),
    }
    cluster_ids = {
        "16": CENTRAL.replace("g64", "g16"),
        "32": CENTRAL.replace("g64", "g32"),
        "64": CENTRAL,
        "128": CENTRAL.replace("g64", "g128"),
    }
    network_ids = {
        "1": CENTRAL.replace("net10p0", "net1p0"),
        "10": CENTRAL,
        "20": CENTRAL.replace("net10p0", "net20p0"),
        "40": CENTRAL.replace("net10p0", "net40p0"),
    }
    special_ids = {
        "qwen3_8b_g16": cluster_ids["16"],
        "qwen3_32b_pp4_g64": CENTRAL.replace("qwen3_8b", "qwen3_32b"),
    }
    return {
        "global_reuse": {
            "input_reuse_fraction": float(trace["reuse"]["input_reuse_fraction"]),
            "input_reuse_tokens": int(trace["reuse"]["input_reuse_tokens"]),
            "request_fraction_with_reuse": float(
                trace["reuse"]["request_fraction_with_reuse"]
            ),
            "scope": trace["reuse_scope"],
        },
        "central": row_metrics(rows[CENTRAL]),
        "concurrency": {
            key: row_metrics(rows[scenario_id])
            for key, scenario_id in concurrency_ids.items()
        },
        "cluster_gpu_count": {
            key: row_metrics(rows[scenario_id])
            for key, scenario_id in cluster_ids.items()
        },
        "network_gb_s": {
            key: row_metrics(rows[scenario_id])
            for key, scenario_id in network_ids.items()
        },
        "zero_alpha_stress": {
            key: row_metrics(rows[scenario_id])
            for key, scenario_id in special_ids.items()
        },
        "rate_zero_reuse_bins": aggregate_reuse_bins(),
        "full_policy_scenario_count": len(rows),
        "hbm_only_admissions_across_scenarios": sum(
            int(row["admission_hbm_only_count"]) for row in rows.values()
        ),
        "dram_evictions_across_scenarios": sum(
            int(row["dram_eviction_count"]) for row in rows.values()
        ),
    }


def generate() -> int:
    source_manifest = json.loads(FIGURE_MANIFEST.read_text(encoding="utf-8"))
    for source in (SOURCE_PDF, SOURCE_PNG):
        record = source_manifest["files"][source.name]
        if sha256(source) != record["sha256"]:
            raise SystemExit(f"source figure hash mismatch: {source}")
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_PDF, OUTPUT_PDF)
    shutil.copyfile(SOURCE_PNG, OUTPUT_PNG)
    payload = {
        "schema": "aegiskv_current_mechanism_supplement_v1",
        "operation": "paper_only_binding_of_frozen_current_design_telemetry",
        "new_experiment": False,
        "workflow_completion_time_result": False,
        "estimand_b_result": False,
        "physical_result": False,
        "campaign_lineage": "4a99c306e8f9",
        "observed_run_count": 3110,
        "sources": [
            file_record(path)
            for path in (
                FIGURE_MANIFEST,
                SOURCE_PDF,
                SOURCE_PNG,
                TRACE_DIAGNOSTICS,
                SCENARIO_DIAGNOSTICS,
                REUSE_BINS,
            )
        ],
        "outputs": [file_record(OUTPUT_PDF), file_record(OUTPUT_PNG)],
        "metrics": metrics(),
        "evidence_boundary": (
            "Current-design SGLSim mechanism telemetry only: alpha, pressure, "
            "occupancy, reuse, intended residency, copy amplification, and "
            "conditioned restored-token coverage. Not WCT, physical serving, "
            "or an Estimand B performance claim."
        ),
    }
    MANIFEST.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "manifest": str(MANIFEST)}, indent=2))
    return 0


def verify() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema") != "aegiskv_current_mechanism_supplement_v1":
        raise SystemExit("unexpected current-mechanism manifest schema")
    for key in ("new_experiment", "workflow_completion_time_result", "estimand_b_result", "physical_result"):
        if payload.get(key) is not False:
            raise SystemExit(f"current-mechanism evidence boundary changed: {key}")
    checked = 0
    source_status = []
    for record in payload["sources"]:
        path = Path(record["path"])
        if not path.is_file():
            status = "missing"
        elif sha256(path) != record["sha256"]:
            status = "hash_mismatch"
        else:
            status = "verified"
        source_status.append({"path": str(path), "status": status})
    for record in payload["outputs"]:
        path = PAPER_ROOT / "figures" / Path(record["path"]).name
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise SystemExit(f"current-mechanism output hash mismatch: {path}")
        checked += 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "operation": "verify_current_mechanism_supplement",
                "checked_local_outputs": checked,
                "manifest_metrics_bound": True,
                "external_sources": source_status,
                "regeneration_ready": all(
                    item["status"] == "verified" for item in source_status
                ),
                "manifest": str(MANIFEST),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-package", action="store_true")
    args = parser.parse_args()
    return verify() if args.verify_package else generate()


if __name__ == "__main__":
    raise SystemExit(main())
