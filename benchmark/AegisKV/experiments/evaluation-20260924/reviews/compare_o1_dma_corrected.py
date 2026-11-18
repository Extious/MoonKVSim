#!/usr/bin/env python3
"""Compare completed O1/DMA audits; never run or alter experiment outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_audit(directory):
    path = directory / "AUDIT.json"
    data = json.loads(path.read_text())
    assert data["status"] == "PASS"
    assert data["primary_runs_verified"] == 180
    assert data["sensitivity_runs_verified"] == 126
    assert data["input_files_unchanged_during_audit"]
    for name, digest in data["output_sha256"].items():
        assert sha(directory / name) == digest, (directory, name)
    return data


def indexed(rows, keys):
    result = {tuple(row[k] for k in keys): row for row in rows}
    assert len(result) == len(rows)
    return result


def compare_rows(old, new, keys):
    left, right = indexed(old, keys), indexed(new, keys)
    assert left.keys() == right.keys(), keys
    changes = []
    for identity in sorted(left):
        before, after = left[identity], right[identity]
        assert before.keys() == after.keys()
        fields = {}
        for name in before:
            if before[name] != after[name]:
                value = {"v1": before[name], "v2": after[name]}
                if type(before[name]) in (int, float) and type(after[name]) in (int, float):
                    value["v2_minus_v1"] = after[name] - before[name]
                fields[name] = value
        changes.append({"identity": dict(zip(keys, identity, strict=True)), "changes": fields})
    return changes


def main():
    old_dir = HERE / "o1-dma-historical-v1-audit"
    new_dir = HERE / "o1-dma-corrected-v2-audit"
    old, new = read_audit(old_dir), read_audit(new_dir)
    assert all("causal-domain" in v for v in new["design_versions"].values())
    groups = {
        "healthy_dram_comparisons": ("workload",),
        "detailed_fallback": ("run_id",),
        "dma_scenarios": ("condition", "policy", "metric"),
    }
    differences = {
        name: compare_rows(old[name], new[name], keys) for name, keys in groups.items()
    }
    exception_changes = compare_rows(
        old["primary_dram_all_dram_nonidentical_workflows"],
        new["primary_dram_all_dram_nonidentical_workflows"],
        ("workload", "fault_index", "workflow"),
    )
    report = {
        "status": "PASS",
        "old_versions": old["design_versions"],
        "corrected_versions": new["design_versions"],
        "comparison": differences,
        "all_dram_workflow_exception_changes": exception_changes,
        "old_all_dram_workflow_exceptions": old[
            "primary_dram_all_dram_nonidentical_workflows"
        ],
        "corrected_all_dram_workflow_exceptions": new[
            "primary_dram_all_dram_nonidentical_workflows"
        ],
        "binding_sha256": {
            str(old_dir / "AUDIT.json"): sha(old_dir / "AUDIT.json"),
            str(new_dir / "AUDIT.json"): sha(new_dir / "AUDIT.json"),
            str(Path(__file__)): sha(Path(__file__)),
        },
        "scope": "Matched historical/corrected versions, not added independent samples.",
    }
    lines = [
        "# Corrected primary O1/DMA numbers and historical comparison",
        "",
        "PASS: both version-bound audits cover all 180 primary and 126 sensitivity runs; "
        "their exported CSV hashes were rechecked. No simulation executed.",
        "",
        "## Healthy DRAM versus All-DRAM",
        "",
        "| Workload | DRAM fallback observations | Checkpoint-only saving | "
        "All transferred backup saving |",
        "|---|---:|---:|---:|",
    ]
    for row in new["healthy_dram_comparisons"]:
        lines.append(
            f"| {row['workload']} | {row['dram_fallback_observations']} | "
            f"{row['completed_checkpoint_saving_pct']:.6f}% | "
            f"{row['all_transferred_backup_saving_pct']:.6f}% |"
        )
    lines += [
        "",
        "The summary counter sums fallback workflows over rebalance evaluations. "
        "It has no exported total-evaluation denominator and is not a percentage, "
        "a unique-event count, or a continuous-time share. All-DRAM bypasses the "
        "tolerance threshold while retaining Slack-derived ranking and finite capacity. "
        "All transferred backup includes completed checkpoint/hot copies and already "
        "transferred bytes from canceled copies. Negative savings remain visible.",
        "",
        "## Logged AegisKV F1 control windows",
        "",
    ]
    for row in new["detailed_fallback"]:
        lines.append(
            f"- `{row['run_id']}`: {row['fallback_samples']} / "
            f"{row['active_workflow_control_window_samples']} unfinished workflow/control-window "
            f"observations ({100 * row['fallback_sample_share']:.6f}%). "
            f"All {row['all_sampled_agent_slacks_reconstructed_exactly']} recorded Agent Slack "
            f"values independently reconstruct exactly. Causes: `{row['reason_sample_counts']}`."
        )
    lines += [
        "",
        "These fractions apply only to the two logged AegisKV failure conditions at "
        "load 0.65, not healthy DRAM or other load cells. Workflow/window observations "
        "are not independent samples. Prediction age includes queue residence since "
        "submission; zero Slack can also be legitimate critical-path or guard clipping.",
        "",
        "## Changes from historical v1",
        "",
    ]
    for name, rows in differences.items():
        changed = [r for r in rows if r["changes"]]
        lines.append(f"- `{name}`: {len(changed)} / {len(rows)} records changed.")
    advantage_deltas = sorted({
        round(r["changes"]["incremental_fault_advantage_s"]["v2_minus_v1"] * 1e6, 6)
        for r in differences["dma_scenarios"]
        if "incremental_fault_advantage_s" in r["changes"]
    })
    lines += [
        "",
        f"The DMA incremental fault-advantage changes are {advantage_deltas} microseconds "
        "per matched objective. Healthy cost fields do not change. Full-precision "
        "changes, including all eight nonzero-slowdown break-even adjustments, remain "
        "in `V1_V2_COMPARISON.json`; no negative or infeasible results are removed.",
        "",
        "Full workflow exceptions, including positive and negative All-DRAM versus "
        "DRAM differences, remain in `V1_V2_COMPARISON.json` and the audit's same-ID CSV. "
        "Equal cohort means do not imply equal workflow outcomes.",
        "",
        "| Workflow | Fault index | All-DRAM minus DRAM (ms) | "
        "Corrected minus old DRAM WCT (µs) | Corrected minus old All-DRAM WCT (µs) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row, change in zip(
        new["primary_dram_all_dram_nonidentical_workflows"], exception_changes, strict=True
    ):
        assert row["workflow"] == change["identity"]["workflow"]
        fields = change["changes"]
        dram_delta = fields.get("dram_wct_ns", {}).get("v2_minus_v1", 0)
        all_dram_delta = fields.get("all_dram_wct_ns", {}).get("v2_minus_v1", 0)
        lines.append(
            f"| {row['workflow']} | {row['fault_index']} | "
            f"{row['all_dram_minus_dram_ns'] / 1e6:+.6f} | "
            f"{dram_delta / 1000:+.6f} | {all_dram_delta / 1000:+.6f} |"
        )
    lines += [
        "",
        "For DMA, use separate target-only and cohort-total objectives: H is healthy "
        "policy cost over Restart; D is the difference in each policy's F1-minus-own-F0 "
        "increment. Only the hypothetical binary mixture of this exact F1 and its F0 "
        "has advantage pD-H. Infeasible p*>1 is retained; this is not an empirical "
        "failure rate. The corrected auxiliary numeric sheet retains the healthy "
        "slowdown cost alongside recovery increments.",
        "",
    ]
    (new_dir / "V1_V2_COMPARISON.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    (new_dir / "PAPER_O1_NUMBERS_V2.md").write_text("\n".join(lines))
    print("PASS: corrected O1/DMA paper numbers and version comparison written")


if __name__ == "__main__":
    main()
