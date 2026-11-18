#!/usr/bin/env python3
"""Explain the fixed worst healthy task using accepted complete scheduler steps."""
from __future__ import annotations

import argparse
import json
from itertools import pairwise
from pathlib import Path

from simulation_paper_plotting import accepted_attempt

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.common.hash import sha256_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    analysis_files = [Path(__file__), Path(__file__).with_name("simulation_paper_plotting.py"),
                      root / "python/moonkvsim/aegiskv/paper_artifacts.py",
                      root / "python/moonkvsim/aegiskv/qwen3_8b_acceptance.py",
                      root / "python/moonkvsim/common/hash.py"]
    analysis_hashes = {str(path): file_sha256(path) for path in analysis_files}
    attempt = accepted_attempt(args.acceptance, {"FIGURE_2_A"})
    artifact_path = root / attempt["artifact"]["path"]
    artifact = json.loads(artifact_path.read_text())
    cases = [{**row, "seed": seed["seed"]} for seed in artifact["paired"]
             for row in seed["workflow_pairs"]]
    if len(cases) != 800:
        raise ValueError("healthy case selection requires all 800 paired task-runs")
    case = sorted(cases, key=lambda row: (
        -row["aegiskv_minus_mooncake_ns"], row["seed"], row["workflow_id"],
    ))[0]
    cell = next(row for row in artifact["cells"] if row["seed"] == case["seed"])
    source_root = root / attempt["gates"][1]["evidence"]["source_root"]
    binding = artifact["provenance"]["workload_binding"]
    workload = source_root / binding["declared_path"]
    if file_sha256(workload) != binding["sha256"]:
        raise ValueError("accepted workload changed")
    records = {}
    for line in workload.open():
        record = json.loads(line)
        records[record["span_id"]] = {key: record[key] for key in (
            "span_id", "workflow_id", "parent_span_ids", "prompt_tokens",
            "output_tokens", "tool_delay_ns")}
    inputs = {str(path.resolve()): file_sha256(path) for path in
              (args.acceptance, artifact_path, workload)}
    systems = {}
    workflow_id = case["workflow_id"]
    workflow_records = {key: record for key, record in records.items()
                        if record["workflow_id"] == workflow_id}
    for system in ("vanilla_mooncake_dram", "aegiskv_unified"):
        compact = cell["systems"][system]
        raw_binding = compact["raw_artifact"]
        path = artifact_path.parent / raw_binding["path"]
        if file_sha256(path) != raw_binding["sha256"]:
            raise ValueError("accepted complete raw execution changed")
        inputs[str(path.resolve())] = raw_binding["sha256"]
        with path.open() as stream:
            raw = json.load(stream)
        if sha256_json(raw["span_details"]) != compact["span_details_sha256"]:
            raise ValueError("accepted span intervals changed")
        all_spans = {span["span_id"]: span for span in raw["span_details"]}
        spans = {key: all_spans[key] for key in workflow_records}
        origin = min(span["released_ns"] for span in spans.values())
        end = max(span["completed_ns"] for span in spans.values())
        if end - origin != compact["workflow_wct_ns"][workflow_id]:
            raise ValueError("selected task WCT does not reconstruct")
        final = max(spans.values(), key=lambda span: (span["completed_ns"], span["span_id"]))
        final_id = final["span_id"]
        parent_end = max(spans[key]["completed_ns"]
                         for key in workflow_records[final_id]["parent_span_ids"])
        if final["released_ns"] != parent_end + workflow_records[final_id]["tool_delay_ns"]:
            raise ValueError("final call release does not follow its recorded parents")
        steps = []
        for step in raw["representative"]["continuous_batch_scheduler"]["steps"]:
            if not any(p["request_id"] == final_id for p in step["participants"]):
                continue
            shares = {}
            for participant in step["participants"]:
                span_id = participant["request_id"]
                record = records[span_id]
                weight = 1 if participant["num_computed_tokens_before"] < record[
                    "prompt_tokens"] else 8
                numerator = (all_spans[span_id]["base_duration_ns"]
                             * participant["num_scheduled_tokens"] * weight)
                denominator = record["prompt_tokens"] + (record["output_tokens"] - 1) * 8
                shares[span_id] = max(1, (numerator + denominator - 1) // denominator)
            duration = step["effective_end_ns"] - step["start_ns"]
            if (step["status"] != "COMPLETED"
                    or duration != step["duration"]["duration_ns"]
                    or duration != max(shares.values())):
                raise ValueError("selected scheduler step does not reconstruct the max-share model")
            steps.append({key: step[key] for key in (
                "step_id", "gpu_id", "start_ns", "effective_end_ns", "status",
                "is_mixed_phase", "participants")} | {
                    "duration_ns": duration, "participant_share_ns": shares})
        steps.sort(key=lambda step: step["start_ns"])
        if not steps or steps[-1]["effective_end_ns"] != final["completed_ns"]:
            raise ValueError("final scheduler steps do not terminate at the call completion")
        if any(a["effective_end_ns"] > b["start_ns"] for a, b in pairwise(steps)):
            raise ValueError("selected request participates in overlapping steps")
        output_indices = [p["output_index"] for step in steps for p in step["participants"]
                          if p["request_id"] == final_id and p["produces_output"]]
        if output_indices != list(range(workflow_records[final_id]["output_tokens"])):
            raise ValueError("selected scheduler steps lost or duplicated final-call output")
        service = sum(step["duration_ns"] for step in steps)
        span_end = steps[-1]["effective_end_ns"]
        first = steps[0]["start_ns"]
        summary = {
            "final_span_id": final_id, "step_count": len(steps),
            "before_final_release_ns": final["released_ns"] - origin,
            "final_release_to_completion_ns": final["completed_ns"] - final["released_ns"],
            "final_release_to_first_step_ns": first - final["released_ns"],
            "final_first_step_to_completion_ns": span_end - first,
            "participating_step_time_ns": service,
            "inter_step_gap_ns": span_end - first - service,
            "own_ideal_share_sum_ns": sum(step["participant_share_ns"][final_id] for step in steps),
            "mixed_step_count": sum(step["is_mixed_phase"] for step in steps),
            "mixed_step_time_ns": sum(step["duration_ns"] for step in steps
                                       if step["is_mixed_phase"]),
            "steps_with_larger_other_share": sum(
                step["duration_ns"] > step["participant_share_ns"][final_id] for step in steps),
        }
        systems[system] = {"origin_ns": origin, "wct_ns": end - origin,
                           "spans": spans, "summary": summary, "final_steps": steps,
                           "routes": [event for event in raw["representative"]["route_events"]
                                      if event["span_id"] in spans]}
        print(system, json.dumps(summary), flush=True)
        del raw, all_spans
    for name, digest in inputs.items():
        if file_sha256(Path(name)) != digest:
            raise ValueError("accepted input changed during case reconstruction")
    if any(file_sha256(Path(name)) != digest for name, digest in analysis_hashes.items()):
        raise ValueError("case analysis source changed during reconstruction")
    body = {"schema": "moonkvsim.simulation-paper-healthy-case.v1",
            "selection": ("largest Aegis-minus-Store WCT across all 800 task-runs; "
                          "seed and ID tie break"),
            "case": case, "systems": systems, "workflow": workflow_records,
            "input_sha256": inputs, "generator_sha256": file_sha256(Path(__file__)),
            "analysis_sha256": analysis_hashes,
            "physical_execution": False, "modeled_uncalibrated": True,
            "interpretation": ("descriptive diagnostic selected by adverse outcome; "
                               "no isolated causal attribution")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({**body, "fingerprint": sha256_json(body)}, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
