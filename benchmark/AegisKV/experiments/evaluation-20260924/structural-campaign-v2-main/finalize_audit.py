"""Bind already completed structural results and reviewed figures; never run DES."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str):
    return json.loads((ROOT / name).read_text())


def main() -> None:
    seal = read("PLAN_SEAL.json")
    assert seal["plan_sha256"] == digest(ROOT / "PLAN.json")
    assert seal["manifest_sha256"] == digest(ROOT / "MANIFEST.json")
    runs = read("RUNS.json")
    assert len(runs) == 135 == len(list((ROOT / "runs").glob("*/COMPLETE.json")))
    run_bindings = {}
    for run in runs:
        folder = ROOT / "runs" / run["id"]
        complete = json.loads((folder / "COMPLETE.json").read_text())
        assert complete == run
        assert digest(folder / "summary.json") == complete["summary_sha256"]
        run_bindings[run["id"]] = {
            "complete_sha256": digest(folder / "COMPLETE.json"),
            "summary_sha256": complete["summary_sha256"],
            "job_sha256": complete["job_sha256"],
        }
    events = read("TRACE_MECHANISM_AUDIT.json")
    assert events["all_passed"] and events["campaign_status"] == "COMPLETE"
    assert events["runs_audited"] == 135
    assert events["recovery_event_count"] == 108
    assert events["queued_history_restore_event_count"] == 279
    assert len(events["eos_full_restore_exposure_checks"]) == 258
    assert events["eos_before_full_restore_count"] == events["eos_canceled_prefetch_count"] == 0
    for name in ("INPUT_MATCH.json", "VERSION_COMPARISON.json", "figures/FIGURE_REVIEW.json"):
        assert read(name)["passed"]
    assert read("VALIDATION.json")["all_passed"]
    assert read("PHASE_AUDIT.json")["all_passed"]
    assert read("SUMMARY.json")["paired_workflow_rows"] == 720
    assert len(read("TRACE_AUDIT.json")) == 2
    source_paths = [
        "PLAN.json", "PLAN_SEAL.json", "MANIFEST.json", "IMPLEMENTATION_APPLICATION.json",
        "INPUT_MATCH.json", "RUNS.json", "VALIDATION.json", "PHASE_AUDIT.json",
        "TRACE_AUDIT.json", "TRACE_MECHANISM_AUDIT.json", "VERSION_COMPARISON.json",
        "raw-runs.csv", "paired-workflows.csv", "recovery-events.csv", "history-restores.csv",
        "PAPER_NUMBERS_V2.md", "paper-target-recovery-per-seed.csv",
        "reports/negative-case-attribution.json", "reports/negative-case-calls.csv",
        "reports/negative-case-workflows.csv", "figures/FIGURE_REVIEW.json",
        "figures/EXPORT_METADATA.json", "figures/wct-endpoints-per-run.csv",
        "figures/wct-endpoint-comparisons.csv", "figures/structural-target-wct.pdf",
        "figures/structural-all-workflow-wct.pdf", "figures/structural-recovery-breakdown.pdf",
        "README.md", "finalize_audit.py",
    ]
    result = {
        "status": "PASS", "campaign_status": "COMPLETE", "runs": 135,
        "paired_failure_runs": 90, "paired_workflow_deltas": 720,
        "active_recovery_events": 108, "separate_queued_history_restores": 279,
        "protected_eos_checks": 258, "eos_before_full_restore_count": 0,
        "eos_canceled_prefetch_count": 0, "prespecified_detailed_runs": 2,
        "runtime_version": read("INPUT_MATCH.json")["application_version"],
        "runtime_sha256": read("INPUT_MATCH.json")["runtime_sha256"],
        "input_match_passed": True,
        "figure_integer_endpoint_audit_and_final_size_review_passed": True,
        "analysis_recomputes_existing_results_only": True,
        "corrected_runs_replace_historical_samples": True,
        "scope": "Model/source/input/event/accounting/endpoint consistency, not physical calibration or numerical attention-kernel validation.",
        "boundaries": [
            "Constructed four-Agent DAGs and hand-declared priors; not natural task traces or prediction-accuracy validation.",
            "Long-decode selection has two synthetic four-block banks; K16 fits both; no insufficient-budget native hotspot-drift evidence.",
            "Target and within-run all-workflow mean are distinct endpoints; all seed points and adverse cases are retained.",
            "Ordinary requests omit admission times; call-latency differences cannot be labelled measured queue differences.",
            "Repeated calls submit immediately; actual tool/think gaps are absent.",
            "No continuous batching, physical GPU execution, measured controller overhead or calibrated compute/DMA interference.",
            "Historical 8/32/128 execution-scale results remain under v1 and are not current-semantic recovery evidence.",
        ],
        "artifact_sha256": {name: digest(ROOT / name) for name in source_paths},
        "run_bindings": run_bindings,
    }
    (ROOT / "FINAL_AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"run_bindings", "artifact_sha256", "boundaries"}}, indent=2))


if __name__ == "__main__":
    main()
