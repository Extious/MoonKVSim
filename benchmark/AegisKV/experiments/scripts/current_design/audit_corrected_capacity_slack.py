#!/usr/bin/env python3
"""Corrected-run variant audit; record equality or differences without assuming a null."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    plan = read(out / "PLAN.json")
    parent = Path(plan["protocol"]["parent_campaign"])
    parent_plan = read(parent / "PLAN.json")
    source_hashes = {}
    for root in (out, parent):
        manifest = read(root / "MANIFEST.json")
        for name, expected in manifest["control_sha256"].items():
            assert digest(root / name) == expected, (root, name)
        source_hashes[str(root)] = {
            name: digest(root / name) for name in ("PLAN.json", "MANIFEST.json", "AUDIT.json")
        }
    assert plan["workload"] == parent_plan["workload"]
    assert plan["profile"] == parent_plan["profile"]
    for name in ("PRIORS.json", plan["profile"], plan["workload"]["path"]):
        assert digest(out / name) == digest(parent / name), name
    summaries, configs, summary_hashes, rows = {}, {}, {}, []
    for job in plan["jobs"]:
        directory = out / "runs" / job["id"]
        marker = read(directory / "COMPLETE.json")
        for name, expected in marker["artifact_sha256"].items():
            assert digest(directory / name) == expected, (job["id"], name)
        config = read(directory / "config.json")
        summary = read(directory / "summary.json")
        assert config == job["config"]
        assert summary["complete"] and summary["output_tokens_exact"]
        assert summary["terminal_allocations_zero"]
        assert summary["policy"] == job["policy"]
        assert summary["config_sha256"] == digest(directory / "config.json")
        assert config["slack_mode"] == ("zero" if job["variant"] == "aegiskv_no_slack" else "dag")
        key = (config["dram_bytes_per_host"] // 1024**3, job["variant"], job["fault"])
        summaries[key], configs[key] = summary, config
        summary_hashes[job["id"]] = digest(directory / "summary.json")
        metrics = summary["metrics"]
        checkpoint = metrics.get("checkpoint_bytes", 0)
        hot = metrics.get("hot_bytes", 0)
        canceled = metrics.get("canceled_copy_transferred_bytes", 0)
        rows.append(
            dict(
                capacity_GiB=key[0],
                variant=key[1],
                phase=key[2],
                policy=summary["policy"],
                slack_mode=config["slack_mode"],
                mean_wct_s=mean(row["wct_ns"] for row in summary["workflows"].values()) / 1e9,
                completed_checkpoint_bytes=checkpoint,
                completed_hot_bytes=hot,
                canceled_transferred_bytes=canceled,
                modeled_backup_transfer_bytes=checkpoint + hot + canceled,
                checkpoint_commits=metrics.get("checkpoint_commits", 0),
                dram_reselections=metrics.get("dram_reselections", 0),
                peak_host_dram_bytes=max(
                    v for k, v in summary["peak_bytes"].items() if k.startswith("dram:")
                ),
            )
        )
    assert len(rows) == 32
    variant_comparisons = []
    for capacity in (2, 4, 8, 256):
        for phase in ("F0", "F1"):
            current, zero = (capacity, "aegiskv", phase), (capacity, "aegiskv_no_slack", phase)
            assert {
                key for key in configs[current] if configs[current][key] != configs[zero][key]
            } == {"slack_mode"}
            variant_comparisons.append(
                dict(
                    capacity_GiB=capacity,
                    phase=phase,
                    all_workflow_records_equal=summaries[current]["workflows"]
                    == summaries[zero]["workflows"],
                    workflow_zero_minus_current_ns={
                        key: summaries[zero]["workflows"][key]["wct_ns"] - row["wct_ns"]
                        for key, row in summaries[current]["workflows"].items()
                    },
                    checkpoint_bytes_differ=summaries[current]["metrics"].get("checkpoint_bytes", 0)
                    != summaries[zero]["metrics"].get("checkpoint_bytes", 0),
                )
            )
    for policy in ("dram", "aegiskv"):
        for phase in ("F0", "F1"):
            previous = read(parent / "runs" / f"center-{policy}-{phase}" / "summary.json")
            current = summaries[256, policy, phase]
            for field in ("workflows", "metrics"):
                assert current[field] == previous[field]
    rows.sort(
        key=lambda row: (
            row["capacity_GiB"],
            row["phase"],
            ("dram", "all_dram", "aegiskv", "aegiskv_no_slack").index(row["variant"]),
        )
    )
    with (out / "variant-cost-results.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    audit = dict(
        passed=True,
        runs=len(rows),
        input_workload_profile_priors_equal_to_sensitivity=True,
        current_vs_zero_only_config_difference="slack_mode",
        all_workflow_completions_equal_current_vs_zero_for_F0_F1_at_all_capacities=all(
            row["all_workflow_records_equal"] for row in variant_comparisons
        ),
        variant_comparisons=variant_comparisons,
        zero_slack_traffic_and_checkpoint_counts_differ=all(
            row["checkpoint_bytes_differ"] for row in variant_comparisons
        ),
        center_default_dag_all_workflows_and_metrics_equal_to_prior_snapshot=True,
        no_population_CI=True,
        scope=(
            "zero mode affects both DRAM exposure and HBM gain Slack inputs; not O1-only isolation"
        ),
        audit_script_sha256=digest(Path(__file__)),
        source_hashes=source_hashes,
        summary_sha256=summary_hashes,
        outputs_sha256={"variant-cost-results.csv": digest(out / "variant-cost-results.csv")},
    )
    (out / "INDEPENDENT_VARIANT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({"passed": True, "runs": len(rows), "output_sha256": audit["outputs_sha256"]}))


if __name__ == "__main__":
    main()
