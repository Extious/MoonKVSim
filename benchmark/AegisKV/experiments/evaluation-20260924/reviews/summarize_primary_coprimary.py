"""Produce a six-row descriptive latency table from a completed independent audit."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


def mean_ns(rows, field):
    return Fraction(sum(row[field] for row in rows), len(rows))


def summarize(audit_path, out):
    report = json.loads(audit_path.read_text())
    assert report["status"] == "PASS" and report["fault_rows_checked"] == 150
    campaign = Path(report["campaign"])
    for relative, digest in report["source_sha256"].items():
        assert hashlib.sha256((campaign / relative).read_bytes()).hexdigest() == digest
    by_cell = defaultdict(lambda: defaultdict(list))
    for row in report["rows"].values():
        value = row["expected"]
        by_cell[value["model"], value["nominal_load"]][value["policy"]].append(value)
    table, decompositions, strata, per_identity = [], [], [], []
    for (model, load), policies in sorted(by_cell.items()):
        for policy, rows in policies.items():
            assert len(rows) == 5
            total = mean_ns(rows, "failure_to_first_new_token_ns")
            queue = mean_ns(rows, "retry_queue_ns")
            service = mean_ns(rows, "recovery_service_ns")
            detect = mean_ns(rows, "detection_ns")
            assert total == queue + service + detect
            decompositions.append(
                {
                    "model": model,
                    "load": load,
                    "policy": policy,
                    "mean_total_s": float(total / 10**9),
                    "mean_detection_s": float(detect / 10**9),
                    "mean_queue_s": float(queue / 10**9),
                    "mean_service_s": float(service / 10**9),
                    "queue_fraction_of_mean_total": float(queue / total),
                    "service_fraction_of_mean_total": float(service / total),
                    "scenario_queue_fraction_range": [
                        min(r["retry_queue_ns"] / r["failure_to_first_new_token_ns"] for r in rows),
                        max(r["retry_queue_ns"] / r["failure_to_first_new_token_ns"] for r in rows),
                    ],
                    "scenario_total_s": [
                        r["failure_to_first_new_token_ns"] / 10**9
                        for r in sorted(rows, key=lambda r: r["fault_index"])
                    ],
                }
            )
        table.append(
            {
                "model": model,
                "nominal_load": load,
                "fixed_identities": 5,
                "restart_mean_failure_to_first_new_s": float(
                    mean_ns(policies["none"], "failure_to_first_new_token_ns") / 10**9
                ),
                "dram_mean_failure_to_first_new_s": float(
                    mean_ns(policies["dram"], "failure_to_first_new_token_ns") / 10**9
                ),
                "aegis_minus_dram_mean_ms": float(
                    (
                        mean_ns(policies["aegiskv"], "failure_to_first_new_token_ns")
                        - mean_ns(policies["dram"], "failure_to_first_new_token_ns")
                    )
                    / 10**6
                ),
            }
        )
        for stratum in ("sink", "non-sink"):
            selected = {
                p: [r for r in rows if r["target_dag_position"] == stratum]
                for p, rows in policies.items()
            }
            n = len(selected["none"])
            assert n == (3 if stratum == "sink" else 2)
            strata.append(
                {
                    "model": model,
                    "load": load,
                    "stratum": stratum,
                    "identities": n,
                    "policy_mean_target_delta_s": {
                        p: float(mean_ns(rs, "target_delta_wct_ns") / 10**9)
                        for p, rs in selected.items()
                    },
                    "policy_mean_failure_to_first_new_s": {
                        p: float(mean_ns(rs, "failure_to_first_new_token_ns") / 10**9)
                        for p, rs in selected.items()
                    },
                    "dram_minus_restart_target_delta_s": float(
                        (
                            mean_ns(selected["dram"], "target_delta_wct_ns")
                            - mean_ns(selected["none"], "target_delta_wct_ns")
                        )
                        / 10**9
                    ),
                    "aegis_minus_dram_target_delta_ms": float(
                        (
                            mean_ns(selected["aegiskv"], "target_delta_wct_ns")
                            - mean_ns(selected["dram"], "target_delta_wct_ns")
                        )
                        / 10**6
                    ),
                    "dram_minus_restart_first_new_s": float(
                        (
                            mean_ns(selected["dram"], "failure_to_first_new_token_ns")
                            - mean_ns(selected["none"], "failure_to_first_new_token_ns")
                        )
                        / 10**9
                    ),
                }
            )
        for identity in range(5):
            selected = {
                p: next(r for r in rows if r["fault_index"] == identity)
                for p, rows in policies.items()
            }
            per_identity.append(
                {
                    "model": model,
                    "load": load,
                    "identity": identity,
                    "target_agent": selected["none"]["target_agent"],
                    "stratum": selected["none"]["target_dag_position"],
                    "policy_target_delta_ns": {
                        p: r["target_delta_wct_ns"] for p, r in selected.items()
                    },
                    "policy_first_new_ns": {
                        p: r["failure_to_first_new_token_ns"] for p, r in selected.items()
                    },
                    "dram_minus_restart_target_delta_ns": selected["dram"]["target_delta_wct_ns"]
                    - selected["none"]["target_delta_wct_ns"],
                    "aegis_minus_dram_first_new_ns": selected["aegiskv"][
                        "failure_to_first_new_token_ns"
                    ]
                    - selected["dram"]["failure_to_first_new_token_ns"],
                }
            )
    assert len(table) == 6 and len(decompositions) == 30 and len(strata) == 12
    for row in table:
        row["hbm_gain_dram_minus_aegis_ms"] = -row["aegis_minus_dram_mean_ms"]
    table.sort(key=lambda r: ({"Qwen3-8B": 0, "Qwen3-32B": 1}[r["model"]], r["nominal_load"]))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "agent-latency-six-rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    evidence = {
        "status": "PASS",
        "campaign": str(campaign),
        "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sampling": "Descriptive means of five fixed identities, not independent trials or a CI.",
        "sign": (
            "HBM gain = DRAM minus Aegis: positive is shorter failure-to-first-new latency. "
            "CSV also retains Aegis minus DRAM with the opposite sign."
        ),
        "table": table,
        "decompositions": decompositions,
        "strata": strata,
        "per_identity_all_signs_preserved": per_identity,
    }
    evidence["decomposition_ranges_across_six_cells"] = {}
    for policy in ("none", "dram", "aegiskv"):
        selected = [r for r in decompositions if r["policy"] == policy]
        evidence["decomposition_ranges_across_six_cells"][policy] = {
            key: [min(r[key] for r in selected), max(r[key] for r in selected)]
            for key in (
                "mean_queue_s",
                "mean_service_s",
                "queue_fraction_of_mean_total",
                "service_fraction_of_mean_total",
            )
        }
    evidence["sink_nonsink_opposite_target_sign_cells"] = []
    evidence["workflow_agent_endpoint_opposite_sign_strata"] = []
    for model, load in sorted(by_cell):
        selected = [r for r in strata if (r["model"], r["load"]) == (model, load)]
        if (
            selected[0]["dram_minus_restart_target_delta_s"]
            * selected[1]["dram_minus_restart_target_delta_s"]
            < 0
        ):
            evidence["sink_nonsink_opposite_target_sign_cells"].append(selected)
    for row in strata:
        if row["dram_minus_restart_target_delta_s"] * row["dram_minus_restart_first_new_s"] < 0:
            evidence["workflow_agent_endpoint_opposite_sign_strata"].append(row)
    text = [
        "# Agent failure-to-first-new-output latency",
        "",
        "Descriptive means over the same five fixed failure identities. Total includes "
        "detection, retry queue and service. HBM gain is DRAM minus AegisKV; positive is better.",
        "",
        "| Model | Nominal load | Restart total (s) | DRAM total (s) | HBM gain (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in table:
        text.append(
            f"| {row['model']} | {row['nominal_load']} | "
            f"{row['restart_mean_failure_to_first_new_s']:.6f} | "
            f"{row['dram_mean_failure_to_first_new_s']:.6f} | "
            f"{row['hbm_gain_dram_minus_aegis_ms']:.6f} |"
        )
    text += [
        "",
        "All exact per-identity integers, queue/service decomposition and sink/non-sink "
        "comparisons (including adverse cases) are in AGENT_LATENCY_EVIDENCE.json. "
        "These are simulation outputs; displayed precision is not hardware accuracy.",
    ]
    text += ["", "## Queue and service shares", ""]
    for policy, values in evidence["decomposition_ranges_across_six_cells"].items():
        q, s = values["queue_fraction_of_mean_total"], values["service_fraction_of_mean_total"]
        text.append(
            f"- {policy}: queue {q[0]:.3%} to {q[1]:.3%}; "
            f"service {s[0]:.3%} to {s[1]:.3%} of each cell's mean total."
        )
    text += [
        "",
        "These ranges compare six cell means, not per-request maxima or CIs.",
        "",
        "## Stratified signs",
        "",
        "DRAM minus Restart; negative means the DRAM endpoint is smaller.",
        "",
        "| Model | Load | Stratum | n fixed IDs | Target Workflow delta difference (s) | "
        "Failure-to-first-new difference (s) |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in strata:
        text.append(
            f"| {row['model']} | {row['load']} | {row['stratum']} | "
            f"{row['identities']} | {row['dram_minus_restart_target_delta_s']:.6f} | "
            f"{row['dram_minus_restart_first_new_s']:.6f} |"
        )
    (out / "AGENT_LATENCY_TABLE.md").write_text("\n".join(text) + "\n")
    latex = [
        "% Frozen campaign: " + campaign.name,
        "% Six descriptive means; exact values and negative differences remain in JSON/CSV.",
        r"\begin{table}[t]",
        r"\centering",
        r"\setlength{\tabcolsep}{3pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\caption{Mean failure-to-first-new-token latency over five fixed fault "
        r"identities. HBM gain is DRAM minus AegisKV; positive is better. "
        r"Descriptive means; no confidence intervals.}",
        r"\label{tab:agent-failure-latency}",
        r"\begin{tabular}{@{}lrrrr@{}}",
        r"\hline",
        r"Model & $\rho$ & Restart & DRAM & HBM gain \\",
        r" & & (s) & (s) & (ms) \\",
        r"\hline",
    ]
    for row in table:
        latex.append(
            f"{row['model']} & {row['nominal_load']:g} & "
            f"{row['restart_mean_failure_to_first_new_s']:.3f} & "
            f"{row['dram_mean_failure_to_first_new_s']:.3f} & "
            f"{row['hbm_gain_dram_minus_aegis_ms']:.3f} " + r"\\"
        )
    latex += [r"\hline", r"\end{tabular}", r"\end{table}", ""]
    (out / "agent-latency-single-column.tex").write_text("\n".join(latex))
    evidence["output_sha256"] = {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
        for name in (
            "agent-latency-six-rows.csv",
            "AGENT_LATENCY_TABLE.md",
            "agent-latency-single-column.tex",
        )
    }
    (out / "AGENT_LATENCY_EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.audit.resolve(), args.out.resolve())
