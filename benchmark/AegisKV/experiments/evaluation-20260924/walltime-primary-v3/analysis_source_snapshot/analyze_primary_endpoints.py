#!/usr/bin/env python3
"""Recompute co-primary endpoints by failure identity from sealed raw summaries."""

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(root):
    plan = read(root / "PLAN.json")
    assert len(plan["jobs"]) == 180
    assert read(root / "AUDIT.json")["status"] == "PASS"
    summaries, sources, workloads = {}, {}, {}
    for job in plan["jobs"]:
        path = root / "runs" / job["id"] / "summary.json"
        expected = read(path.parent / "COMPLETE.json")["summary_sha256"]
        assert sha(path) == expected
        summaries[job["id"]] = read(path)
        sources[str(path.relative_to(root))] = expected
    for name, descriptor in plan["workloads"].items():
        path = root / descriptor["path"]
        assert sha(path) == descriptor["sha256"]
        data = gzip.decompress(path.read_bytes())
        assert hashlib.sha256(data).hexdigest() == descriptor["content_sha256"]
        workloads[name] = json.loads(data)
    rows = []
    for job in plan["jobs"]:
        failure = job["failure"]
        if failure is None:
            continue
        failed, healthy = summaries[job["id"]], summaries[job["f0_id"]]
        workflow, name = failure["agent"].split("/", 1)
        agents = [a for a in workloads[job["workload"]] if a["workflow"] == workflow]
        target = next(a for a in agents if a["name"] == name)
        inv = target["calls"][failure["invocation"]]
        is_sink = not any(name in a["predecessors"] for a in agents)
        recovery = [
            r
            for r in failed["recoveries"]
            if (r["agent"], r["invocation"]) == (failure["agent"], failure["invocation"])
        ]
        assert len(recovery) == 1
        recovery = recovery[0]
        assert healthy["workflows"].keys() == failed["workflows"].keys()
        assert recovery["latency_ns"] == sum(
            recovery[key] for key in ("detection_ns", "queue_ns", "service_ns")
        )
        rho = plan["workloads"][job["workload"]]["offered_load_proxy"]
        workers = len(job["config"]["hosts"])
        lost = len(failed["failure"]["workers"])
        rows.append(
            dict(
                run_id=job["id"],
                model=job["model"],
                nominal_load=rho,
                policy=job["policy"],
                fault_index=job["fault_index"],
                target_agent=failure["agent"],
                target_invocation=failure["invocation"],
                target_role=target["role"],
                target_dag_position="sink" if is_sink else "non-sink",
                fault_phase="prefill"
                if failed["failure"]["logical_tokens"] <= len(inv["prompt"])
                else "decode",
                fault_logical_tokens=failed["failure"]["logical_tokens"],
                target_prompt_tokens=len(inv["prompt"]),
                target_output_tokens=len(inv["output"]),
                target_f0_wct_ns=healthy["workflows"][workflow]["wct_ns"],
                target_f1_wct_ns=failed["workflows"][workflow]["wct_ns"],
                target_delta_wct_ns=failed["workflows"][workflow]["wct_ns"]
                - healthy["workflows"][workflow]["wct_ns"],
                all_workflow_mean_delta_ns=mean(
                    failed["workflows"][w]["wct_ns"] - healthy["workflows"][w]["wct_ns"]
                    for w in healthy["workflows"]
                ),
                detection_ns=recovery["detection_ns"],
                retry_queue_ns=recovery["queue_ns"],
                recovery_service_ns=recovery["service_ns"],
                failure_to_first_new_token_ns=recovery["latency_ns"],
                checkpoint_tokens=recovery["checkpoint_tokens"],
                replay_tokens=recovery["rebuild_tokens"],
                failed_workers=lost,
                surviving_workers=workers - lost,
                postfailure_nominal_load_proxy=rho * workers / (workers - lost),
            )
        )
    assert len(rows) == 150
    groups = defaultdict(list)
    for row in rows:
        for stratum in ("all-five-fixed-identities", row["target_dag_position"]):
            groups[row["model"], row["nominal_load"], row["policy"], stratum].append(row)
    aggregates = []
    for (model, rho, policy, stratum), values in sorted(groups.items()):
        aggregates.append(
            dict(
                model=model,
                nominal_load=rho,
                policy=policy,
                stratum=stratum,
                fixed_identities=len(values),
                target_mean_delta_s=mean(v["target_delta_wct_ns"] for v in values) / 1e9,
                target_min_delta_s=min(v["target_delta_wct_ns"] for v in values) / 1e9,
                target_max_delta_s=max(v["target_delta_wct_ns"] for v in values) / 1e9,
                cohort_mean_delta_s=mean(v["all_workflow_mean_delta_ns"] for v in values) / 1e9,
                first_new_mean_s=mean(v["failure_to_first_new_token_ns"] for v in values) / 1e9,
                retry_queue_mean_s=mean(v["retry_queue_ns"] for v in values) / 1e9,
                recovery_service_mean_s=mean(v["recovery_service_ns"] for v in values) / 1e9,
            )
        )
    out = root / "endpoints"
    out.mkdir(exist_ok=True)
    write_csv(out / "per-identity.csv", rows)
    write_csv(out / "stratified-summary.csv", aggregates)
    record = dict(
        status="PASS",
        source_summary_count=len(sources),
        fault_rows=len(rows),
        source_sha256={"PLAN.json": sha(root / "PLAN.json"), **sources},
        analysis_sha256=sha(Path(__file__)),
        output_sha256={p.name: sha(p) for p in out.glob("*.csv")},
        runtime_versions=sorted({s["design_version"] for s in summaries.values()}),
        sampling=(
            "five fixed identities; dependent workflows and reused own-policy F0; descriptive only"
        ),
        postfailure_load=(
            "arrival-generation proxy after permanent worker loss, not measured utilization"
        ),
        semantic_scope=(
            "the source runtime version recorded here; "
            "accounting validation is not algorithmic conformance"
        ),
    )
    (out / "PROVENANCE.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: record[k]
                for k in ("status", "source_summary_count", "fault_rows", "runtime_versions")
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    analyze(parser.parse_args().campaign.resolve())
