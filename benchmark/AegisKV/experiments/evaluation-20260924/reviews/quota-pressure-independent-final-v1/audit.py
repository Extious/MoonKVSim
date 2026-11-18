#!/usr/bin/env python3
"""Independent final O3 arithmetic from sealed artifacts; no simulator imports."""

from __future__ import annotations

import csv
import gzip
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parents[1] / "quota-pressure-postreview-v1"
ROOT = OUT.parents[5]
EXPECTED_FINAL = "a095d6ea57f70cd52cb37f08e548eb93727df370a4c5a20699d4afeaf63113e0"
EXPECTED_ACCOUNTING = "29ced822617d3dab286dbddee1606a9a66830fa2a1af41ae0e8206d81659b877"
EXPECTED_MODEL = "e6e2e9d3f96a75bd9df911f37c8ca751e54f41d421997eb4f74f550111e04368"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def object_sha(value):
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    assert sha(SOURCE / "FINAL_AUDIT.json") == EXPECTED_FINAL
    assert sha(SOURCE / "INDEPENDENT_ACCOUNTING_AUDIT.json") == EXPECTED_ACCOUNTING
    final = read(SOURCE / "FINAL_AUDIT.json")
    assert final["status"] == "COMPLETE" and final["formal_runs"] == 72
    for relative, digest in final["artifact_sha256"].items():
        assert sha(SOURCE / relative) == digest, relative
    plan, manifest = read(SOURCE / "PLAN.json"), read(SOURCE / "MANIFEST.json")
    for name, digest in manifest["source_sha256"].items():
        assert sha(SOURCE / "source_snapshot" / name) == digest
    for name, digest in manifest["control_sha256"].items():
        assert sha(SOURCE / name) == digest
    for name, digest in plan["protocol"]["source_inputs_sha256"].items():
        assert sha(ROOT / name) == digest
    assert sha(SOURCE / plan["predictor"]) == EXPECTED_MODEL == manifest["predictor_sha256"]
    model = read(SOURCE / plan["predictor"])
    assert model["slack_guard_ns"] == 910471105
    raw_workload = gzip.decompress((SOURCE / plan["workload"]["path"]).read_bytes())
    assert hashlib.sha256(raw_workload).hexdigest() == plan["workload"]["content_sha256"]
    agents = json.loads(raw_workload)
    original = SOURCE.parent / "sensitivity-campaign-v2-corrected"
    original_plan = read(original / "PLAN.json")
    old_agents = json.loads(
        gzip.decompress((original / original_plan["workload"]["path"]).read_bytes())
    )
    assert len(agents) == len(old_agents) == 52
    assert len({a["workflow"] for a in agents}) == 4
    assert all(len(a["calls"]) == 1 for a in agents)
    assert not {a["workflow"] for a in agents} & set(model["regressor"]["training_workflows"])
    for before, after in zip(old_agents, agents, strict=True):
        assert {k: v for k, v in before.items() if k != "prior_ns"} == {
            k: v for k, v in after.items() if k != "prior_ns"
        }
        assert after["prior_ns"] == model["role_priors_ns"].get(
            after["role"], model["role_priors_ns"]["__all__"]
        )

    jobs = plan["jobs"]
    assert len(jobs) == len({j["id"] for j in jobs}) == 72
    assert {(j["margin_MiB"], j["dma"], j["variant"], j["fault"]) for j in jobs} == set(
        itertools.product(
            (0, 32, 128),
            (0.0, 0.005),
            ("none", "dram", "fixed32", "fixed128", "fixed4096", "adaptive"),
            ("F0", "F1"),
        )
    )
    target_workflow = plan["protocol"]["failure"]["agent"].split("/")[0]
    summaries, run_rows, timings, decreases = {}, [], [], []
    for job in jobs:
        folder = SOURCE / "runs" / job["id"]
        marker, summary = read(folder / "COMPLETE.json"), read(folder / "summary.json")
        required = {
            "job_sha256": object_sha(job),
            "plan_sha256": sha(SOURCE / "PLAN.json"),
            "manifest_sha256": sha(SOURCE / "MANIFEST.json"),
            "profile_sha256": sha(SOURCE / plan["profile"]),
            "predictor_sha256": EXPECTED_MODEL,
            "workload_sha256": plan["workload"]["sha256"],
        }
        assert marker["status"] == "COMPLETE" and marker["id"] == job["id"]
        assert all(marker[k] == v for k, v in required.items())
        for name, digest in marker["artifact_sha256"].items():
            assert sha(folder / name) == digest
        assert read(folder / "config.json") == job["config"]
        assert read(folder / "failure.json") == job["failure"]
        assert job["config"]["slack_guard_ns"] == model["slack_guard_ns"]
        assert summary["predictor"] == "hashed-text-agent-submission-to-completion-v1"
        assert summary["config_sha256"] == object_sha(job["config"])
        assert summary["workload_sha256"] == plan["workload"]["content_sha256"]
        assert summary["design_version"] == manifest["design_version"]
        assert summary["policy"] == job["policy"]
        assert summary["complete"] and summary["terminal_allocations_zero"]
        assert summary["output_tokens_exact"] and summary["oracle_reservation_count"] == 0
        assert len(summary["workflows"]) == 4 and len(summary["requests"]) == 52
        controls = lines(folder / "controls.jsonl.gz")
        admissions = lines(folder / "admissions.jsonl.gz")
        events = lines(folder / "events.jsonl.gz")
        pressure_controls = [r for r in controls if r["before"]["pressure"]]
        pressure_admissions = [r for r in admissions if r["pressure_after"]]
        denied = sum(not r["successful"] for r in admissions)
        assert denied == summary["metrics"].get("foreground_admission_waits", 0)
        assert denied == 0
        native_decreases = [
            e for e in events if e["kind"] == "quota" and e["pressure"] and e["after"] < e["before"]
        ]
        if job["variant"] == "adaptive":
            for event in native_decreases:
                decreases.append({"id": job["id"], **event})
                assert job["margin_MiB"] == 32 and job["fault"] == "F0"
                assert event["before"] == 32 * 1024**2
                assert event["after"] == 24 * 1024**2
                assert event["after"] == event["before"] * job["config"]["decrease"]
                match = [
                    r
                    for r in pressure_controls
                    if r["time_ns"] == event["time_ns"]
                    and r["worker"] == event["worker"]
                    and r["rank"] == event["rank"]
                ]
                assert len(match) == 1
                assert match[0]["before"]["quota"] == event["before"]
                assert match[0]["after"]["quota"] == event["after"]
        finish = summary["workflows"][target_workflow]["finish_ns"]
        if pressure_controls or pressure_admissions:
            assert pressure_controls and pressure_admissions
            assert job["fault"] == "F0"
            first_control = min(r["time_ns"] for r in pressure_controls)
            first_admission = min(r["time_ns"] for r in pressure_admissions)
            assert first_control > finish and first_admission > finish
            timings.append(
                dict(
                    id=job["id"],
                    target_workflow=target_workflow,
                    target_finish_ns=finish,
                    first_pressure_control_ns=first_control,
                    first_sticky_pressure_admission_observed_ns=first_admission,
                    control_after_target_ns=first_control - finish,
                    admission_observation_after_target_ns=first_admission - finish,
                )
            )
        run_rows.append(
            dict(
                id=job["id"],
                condition=job["condition"],
                margin_MiB=job["margin_MiB"],
                dma=job["dma"],
                variant=job["variant"],
                fault=job["fault"],
                pressure_control_windows=len(pressure_controls),
                sticky_flag_after_attempt_observations=len(pressure_admissions),
                capacity_denied_admission_attempts=denied,
                native_pressure_decrease_events=len(native_decreases),
            )
        )
        summaries[job["id"]] = summary

    pairs, workflow_pairs = [], []
    conditions = sorted({j["condition"] for j in jobs})
    for condition, fault, fixed in itertools.product(
        conditions, ("F0", "F1"), ("fixed128", "fixed4096")
    ):
        adaptive_id, fixed_id = f"{condition}-adaptive-{fault}", f"{condition}-{fixed}-{fault}"
        a, b = summaries[adaptive_id]["workflows"], summaries[fixed_id]["workflows"]
        assert a == b
        pairs.append(
            dict(
                condition=condition,
                fault=fault,
                fixed=fixed,
                adaptive_id=adaptive_id,
                fixed_id=fixed_id,
                workflow_count=len(a),
                entire_endpoint_dictionary_equal=True,
            )
        )
        for workflow in sorted(a):
            for k in ("start_ns", "finish_ns", "wct_ns"):
                assert a[workflow][k] == b[workflow][k]
            workflow_pairs.append(
                dict(
                    condition=condition,
                    fault=fault,
                    fixed=fixed,
                    workflow=workflow,
                    **a[workflow],
                    adaptive_minus_fixed_wct_ns=0,
                    entire_workflow_record_equal=True,
                )
            )
    assert len(pairs) == 24 and len(workflow_pairs) == 96
    pressure_by_fault = Counter(r["fault"] for r in run_rows if r["pressure_control_windows"])
    assert pressure_by_fault == Counter({"F0": 12}) and len(timings) == 12
    assert len(decreases) == 2

    validation = SOURCE / "validation/observer-transparency"
    record = read(validation / "COMPLETE.json")
    official = SOURCE / "runs" / record["id"]
    marker = read(official / "COMPLETE.json")
    assert record["status"] == "PASS" and not record["counts_as_experimental_sample"]
    for k in (
        "id",
        "job_sha256",
        "plan_sha256",
        "manifest_sha256",
        "profile_sha256",
        "predictor_sha256",
        "workload_sha256",
    ):
        assert record[k] == marker[k]
    transparent = {}
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        a, b = (validation / name).read_bytes(), (official / name).read_bytes()
        if name.endswith(".gz"):
            a, b = gzip.decompress(a), gzip.decompress(b)
        assert a == b and a
        expected = dict(equal=True, decompressed_sha256=hashlib.sha256(a).hexdigest(), bytes=len(a))
        assert record["checks"][name] == expected
        transparent[name] = {**expected, "lines": len(a.splitlines())}
    assert transparent["flows.jsonl.gz"]["lines"] == 61559

    # Compare independently calculated counts/endpoints with the sealed secondary report.
    previous = read(SOURCE / "INDEPENDENT_ACCOUNTING_AUDIT.json")
    assert previous["pressure_flag_runs_by_fault"] == {"F0": 12, "F1": 0}
    assert previous["admission_wait_runs"] == 0
    assert len(previous["adaptive_fixed_workflow_endpoint_comparisons"]) == len(pairs)
    for relative, digest in final["artifact_sha256"].items():
        assert sha(SOURCE / relative) == digest
    write_csv("run-counts.csv", run_rows)
    write_csv("adaptive-fixed-pairs.csv", pairs)
    write_csv("adaptive-fixed-workflows.csv", workflow_pairs)
    write_csv("pressure-timing.csv", timings)
    write_json("ADAPTIVE_DECREASES.json", decreases)
    write_json("OBSERVER_BYTE_COMPARISON.json", transparent)
    write_json(
        "REVIEW.json",
        {
            "status": "PASS",
            "substantive_errors": [],
            "source": str(SOURCE),
            "source_final_audit_sha256": EXPECTED_FINAL,
            "source_accounting_audit_sha256": EXPECTED_ACCOUNTING,
            "rehashed_sealed_files_before_and_after": len(final["artifact_sha256"]),
            "formal_runs": 72,
            "F0_runs": 36,
            "F1_runs": 36,
            "pressure_F0_runs": 12,
            "pressure_F1_runs": 0,
            "capacity_denied_admission_runs": 0,
            "native_adaptive_nonzero_pressure_decreases": 2,
            "decrease_MiB": [32, 24],
            "all_observed_pressure_after_target_workflow_finish": True,
            "adaptive_fixed_exact_endpoint_pairs": 24,
            "exact_workflow_pairs": 96,
            "fixed_comparators": ["fixed128", "fixed4096"],
            "separate_observer_validation_runs": 1,
            "observer_flow_lines": 61559,
            "predictor_sha256": EXPECTED_MODEL,
            "predictor_name": "hashed-text-agent-submission-to-completion-v1",
            "slack_guard_ns": 910471105,
            "role_priors_verified_agents": 52,
            "original_input_changes_only_prior_ns": True,
            "complete_single_invocation_agents": 52,
            "input_workflows": 4,
            "training_workflows_disjoint": True,
            "statistics": (
                "Four dependent workflows, one fixed logical fault identity. "
                "72 parameter/policy/fault conditions and 24 reused-run comparison "
                "pairs are not independent repetitions."
            ),
            "pressure_semantics": (
                "Control-entry worker/rank flags; admission values are sticky-after-attempt "
                "observations, not new trigger counts. TP=1 here. "
                "No static low ceiling is counted as pressure."
            ),
            "interpretation": (
                "Retained null adaptive/fixed endpoint result. Healthy pressure occurs "
                "after target completion; no F1 pressure, capacity-denied admission, "
                "or adaptive recovery advantage under pressure is established."
            ),
            "scope": (
                "Bounded independent direct-artifact arithmetic and binding cross-check; "
                "does not rerun DES, native kernels, or the full ledger integration "
                "already audited separately."
            ),
            "new_DES_runs": 0,
            "original_package_modified": False,
            "auditor_sha256": sha(Path(__file__)),
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "formal_runs": 72,
                "pressure_F0": 12,
                "pressure_F1": 0,
                "denied": 0,
                "equal_run_pairs": 24,
                "equal_workflow_pairs": 96,
                "adaptive_decreases": 2,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
