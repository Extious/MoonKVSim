#!/usr/bin/env python3
"""Derive complete-batch makespan from accepted primary span intervals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulation_paper_plotting import accepted_attempt

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.aegiskv.paper_study_reconstruction import reconstruct_workflow_metrics
from moonkvsim.aegiskv.qwen3_8b_acceptance import load_json_strict
from moonkvsim.aegiskv.qwen3_8b_failure_campaign import _load_document, _run, _t_interval
from moonkvsim.common.hash import sha256_json

STORE = "vanilla_mooncake_dram"
AEGIS = "aegiskv_unified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    analysis_files = [
        Path(__file__), Path(__file__).with_name("simulation_paper_plotting.py"),
        *(root / "python/moonkvsim/aegiskv" / name for name in (
            "paper_study_reconstruction.py", "qwen3_8b_failure_campaign.py",
            "qwen3_8b_acceptance.py", "paper_artifacts.py")),
        root / "python/moonkvsim/common/hash.py",
    ]
    analysis_hashes = {str(path): file_sha256(path) for path in analysis_files}
    attempt = accepted_attempt(args.acceptance_manifest, {"FIGURE_3_A"})
    campaign_path = root / attempt["artifact"]["path"]
    campaign = load_json_strict(campaign_path)
    source_root = root / attempt["gates"][1]["evidence"].get("source_root", ".")
    workload_binding = campaign["binding"]["workload_binding"]
    workload = source_root / workload_binding["declared_path"]
    if file_sha256(workload) != workload_binding["sha256"]:
        raise ValueError("accepted workload changed")
    with workload.open() as stream:
        records = {record["span_id"]: record for line in stream
                   if (record := json.loads(line))}
    seeds = campaign["seeds"]
    if [row["seed"] for row in seeds] != list(range(5)):
        raise ValueError("requires five canonical ordered seeds")
    audited_rows = attempt["gates"][4]["evidence"]["complete_raw_reconstruction"]
    audited = {(row["seed"], row["scenario"], row["system"]): row
               for row in audited_rows}
    expected = {(seed, scenario, system) for seed in range(5)
                for scenario in ("no_failure", "gpu_failure") for system in (STORE, AEGIS)}
    if set(audited) != expected or len(audited_rows) != 20:
        raise ValueError("primary audit does not cover exactly the complete paired population")
    rows = []
    inputs = {str(args.acceptance_manifest.resolve()): file_sha256(args.acceptance_manifest),
              str(campaign_path): file_sha256(campaign_path),
              str(workload): file_sha256(workload)}
    for seed_row in seeds:
        seed = seed_row["seed"]
        artifact = seed_row["artifact"]
        path = root / artifact["path"]
        if file_sha256(path) != artifact["sha256"]:
            raise ValueError("accepted compact source changed")
        inputs[str(path)] = artifact["sha256"]
        document = _load_document(path)
        makespans, bindings = {}, []
        for scenario in ("no_failure", "gpu_failure"):
            makespans[scenario] = {}
            for system in (STORE, AEGIS):
                run = _run(document, system, scenario)
                raw_sha = run["raw_evidence"]["sha256"]
                if raw_sha != audited[seed, scenario, system]["raw_sha256"]:
                    raise ValueError("compact source is not bound to the accepted complete raw run")
                if sha256_json(run["span_details"]) != run["span_details_sha256"]:
                    raise ValueError("accepted complete span intervals changed")
                _, end_ns = reconstruct_workflow_metrics(run, records)
                if min(span["released_ns"] for span in run["span_details"]) != 0:
                    raise ValueError("batch did not begin at virtual time zero")
                makespans[scenario][system] = end_ns
                bindings.append({"scenario": scenario, "system": system,
                                 "raw_sha256": raw_sha,
                                 "span_details_sha256": run["span_details_sha256"]})
        f0, f1 = makespans["no_failure"], makespans["gpu_failure"]
        f0_delta = f0[AEGIS] - f0[STORE]
        f1_delta = f1[AEGIS] - f1[STORE]
        rows.append({"seed": seed, "makespan_ns": makespans, "raw_bindings": bindings,
                     "f0_policy_difference_ns": f0_delta,
                     "f1_policy_difference_ns": f1_delta,
                     "failure_penalty_difference_ns": f1_delta - f0_delta,
                     "f1_policy_difference_pct": 100 * f1_delta / f1[STORE]})
        if file_sha256(path) != artifact["sha256"]:
            raise ValueError("compact source changed during reconstruction")
        print(f"reconstructed seed {seed}", flush=True)
    for name, digest in inputs.items():
        if file_sha256(Path(name)) != digest:
            raise ValueError("accepted input changed during reconstruction")
    if any(file_sha256(Path(path)) != digest for path, digest in analysis_hashes.items()):
        raise ValueError("analysis implementation changed during reconstruction")
    inference = {metric: _t_interval([row[metric] for row in rows]) for metric in (
        "f0_policy_difference_ns", "f1_policy_difference_ns",
        "failure_penalty_difference_ns", "f1_policy_difference_pct")}
    body = {
        "schema": "moonkvsim.simulation-paper-primary-makespan.v1",
        "derivation": "maximum completion time of all 1304 spans; first release verified zero",
        "evidence_basis": (
            "complete compact span intervals, verified equal to full raw by accepted G5; "
            "rechecked frozen workload population, WCT, output counts, and declared workload end"),
        "rows": rows, "inference": inference, "input_sha256": inputs,
        "analysis_sha256": analysis_hashes,
        "generator_sha256": file_sha256(Path(__file__)),
        "effect": "(Aegis F1 - Aegis F0) - (Store-only F1 - Store-only F0)",
        "sign": "negative differences favor AegisKV",
        "physical_execution": False, "modeled_uncalibrated": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**body, "fingerprint": sha256_json(body)}, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
