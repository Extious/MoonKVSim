"""Cross-check published endpoint tables against request and recovery timestamps.

Never imports the analysis/plotting scripts or executes a simulator. Supports a
partial campaign while marking absent endpoint tables and incomplete runs.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from math import ceil, isclose
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def workflow_intervals(summary):
    intervals = defaultdict(list)
    for request in summary["requests"]:
        intervals[request["agent"].split("/", 1)[0]].append(request)
    result = {}
    for workflow, requests in intervals.items():
        begin = min(r["submit_ns"] for r in requests)
        end = max(r["finish_ns"] for r in requests)
        result[workflow] = end - begin
        assert summary["workflows"][workflow] == {
            "start_ns": begin,
            "finish_ns": end,
            "wct_ns": end - begin,
        }
    return result


def audit(campaign):
    plan = read(campaign / "PLAN.json")
    sources = {"PLAN.json": sha(campaign / "PLAN.json")}
    workloads = {}
    for identity, spec in plan["workloads"].items():
        path = campaign / spec["path"]
        assert sha(path) == spec["sha256"]
        raw = gzip.decompress(path.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == spec["content_sha256"]
        workloads[identity] = json.loads(raw)
        sources[spec["path"]] = sha(path)
    summaries, intervals = {}, {}
    pending = []
    for job in plan["jobs"]:
        directory = campaign / "runs" / job["id"]
        if not (directory / "COMPLETE.json").exists():
            pending.append(job["id"])
            continue
        complete = read(directory / "COMPLETE.json")
        assert complete["summary_sha256"] == sha(directory / "summary.json")
        summary = read(directory / "summary.json")
        assert summary["complete"] and summary["output_tokens_exact"]
        summaries[job["id"]] = summary
        intervals[job["id"]] = workflow_intervals(summary)
        sources[str((directory / "summary.json").relative_to(campaign))] = sha(
            directory / "summary.json"
        )
    rows, identity_groups = {}, defaultdict(set)
    for job in plan["jobs"]:
        if not job["failure"] or job["id"] not in summaries or job["f0_id"] not in summaries:
            continue
        s = summaries[job["id"]]
        event = s["failure"]
        assert event["agent"] == job["failure"]["agent"]
        assert event["invocation"] == job["failure"]["invocation"]
        agent_id, invocation = event["agent"], event["invocation"]
        workflow, name = agent_id.split("/", 1)
        specs = {a["name"]: a for a in workloads[job["workload"]] if a["workflow"] == workflow}
        call = specs[name]["calls"][invocation]
        total = len(call["prompt"]) + len(call["output"])
        assert event["logical_tokens"] == ceil(total * job["failure"]["progress"])
        successors = sorted(a["name"] for a in specs.values() if name in a["predecessors"])
        recovery = next(
            r for r in s["recoveries"] if (r["agent"], r["invocation"]) == (agent_id, invocation)
        )
        assert (
            sum((r["agent"], r["invocation"]) == (agent_id, invocation) for r in s["recoveries"])
            == 1
        )
        assert all(
            (r["agent"], r["invocation"]) != (agent_id, invocation)
            for r in s.get("history_restores", [])
        )
        first_new = recovery["first_new_token_ns"]
        fail_time = event["time_ns"]
        assert recovery["failure_ns"] == fail_time
        latency = first_new - fail_time
        detection = recovery["retry_enqueued_ns"] - fail_time
        queue = recovery["admitted_ns"] - recovery["retry_enqueued_ns"]
        service = first_new - recovery["admitted_ns"]
        assert latency == recovery["latency_ns"] == detection + queue + service
        assert (detection, queue, service) == tuple(
            recovery[k] for k in ("detection_ns", "queue_ns", "service_ns")
        )
        request = next(
            r for r in s["requests"] if (r["agent"], r["invocation"]) == (agent_id, invocation)
        )
        assert fail_time <= first_new <= request["finish_ns"]
        a, b = intervals[job["id"]], intervals[job["f0_id"]]
        assert a.keys() == b.keys()
        rho = plan["workloads"][job["workload"]]["offered_load_proxy"]
        workers = len(job["config"]["hosts"])
        remaining = workers - len(event["workers"])
        expected = {
            "run_id": job["id"],
            "model": job["model"],
            "nominal_load": rho,
            "policy": job["policy"],
            "fault_index": job["fault_index"],
            "target_agent": agent_id,
            "target_invocation": invocation,
            "target_role": specs[name]["role"],
            "target_dag_position": "non-sink" if successors else "sink",
            "fault_phase": "prefill"
            if event["logical_tokens"] <= len(call["prompt"])
            else "decode",
            "fault_logical_tokens": event["logical_tokens"],
            "target_prompt_tokens": len(call["prompt"]),
            "target_output_tokens": len(call["output"]),
            "target_f0_wct_ns": b[workflow],
            "target_f1_wct_ns": a[workflow],
            "target_delta_wct_ns": a[workflow] - b[workflow],
            "all_workflow_mean_delta_ns": float(Fraction(sum(a[w] - b[w] for w in a), len(a))),
            "detection_ns": detection,
            "retry_queue_ns": queue,
            "recovery_service_ns": service,
            "failure_to_first_new_token_ns": latency,
            "checkpoint_tokens": recovery["checkpoint_tokens"],
            "replay_tokens": recovery["rebuild_tokens"],
            "failed_workers": workers - remaining,
            "surviving_workers": remaining,
            "postfailure_nominal_load_proxy": rho / (remaining / workers),
        }
        identity_groups[job["fault_index"]].add(
            (agent_id, invocation, expected["target_dag_position"])
        )
        rows[job["id"]] = {
            "expected": expected,
            "target_successor_ids": successors,
            "failure_ns": fail_time,
            "first_new_token_ns": first_new,
            "eos_ns": request["finish_ns"],
            "restore_done_ns": recovery.get("restore_done_ns"),
            "active_recovery_count": len(s["recoveries"]),
            "queued_history_restore_count": len(s.get("history_restores", [])),
        }
    for values in identity_groups.values():
        assert len(values) == 1, (
            "fault ordinal does not name the same target across policies/loads/models"
        )
    endpoint_path = campaign / "endpoints/per-identity.csv"
    table_verified = endpoint_path.exists()
    aggregate_count = 0
    if table_verified:
        assert not pending and len(rows) == 150
        published = {r["run_id"]: r for r in csv_rows(endpoint_path)}
        assert published.keys() == rows.keys()
        for identity, row in rows.items():
            actual, expected = published[identity], row["expected"]
            assert actual.keys() == expected.keys()
            for key, value in expected.items():
                if isinstance(value, float):
                    assert isclose(float(actual[key]), value, rel_tol=1e-12, abs_tol=1e-5)
                else:
                    assert actual[key] == str(value), (identity, key, actual[key], value)
        aggregates = csv_rows(campaign / "endpoints/stratified-summary.csv")
        assert len(aggregates) == 90
        for aggregate in aggregates:
            selected = [
                r["expected"]
                for r in rows.values()
                if r["expected"]["model"] == aggregate["model"]
                and r["expected"]["policy"] == aggregate["policy"]
                and r["expected"]["nominal_load"] == float(aggregate["nominal_load"])
                and (
                    aggregate["stratum"] == "all-five-fixed-identities"
                    or r["expected"]["target_dag_position"] == aggregate["stratum"]
                )
            ]
            count = len(selected)
            assert count == int(aggregate["fixed_identities"])
            columns = {
                "target_mean_delta_s": ("target_delta_wct_ns", "mean"),
                "target_min_delta_s": ("target_delta_wct_ns", "min"),
                "target_max_delta_s": ("target_delta_wct_ns", "max"),
                "cohort_mean_delta_s": ("all_workflow_mean_delta_ns", "mean"),
                "first_new_mean_s": ("failure_to_first_new_token_ns", "mean"),
                "retry_queue_mean_s": ("retry_queue_ns", "mean"),
                "recovery_service_mean_s": ("recovery_service_ns", "mean"),
            }
            for key, (source, operation) in columns.items():
                values = [r[source] for r in selected]
                value = {"mean": sum(values) / count, "min": min(values), "max": max(values)}[
                    operation
                ] / 1e9
                assert isclose(float(aggregate[key]), value, rel_tol=1e-12, abs_tol=1e-12)
            aggregate_count += 1
        provenance = read(campaign / "endpoints/PROVENANCE.json")
        for relative, digest in provenance["source_sha256"].items():
            assert sha(campaign / relative) == digest
        for name, digest in provenance["output_sha256"].items():
            assert sha(campaign / "endpoints" / name) == digest
    return {
        "status": "PASS" if not pending and table_verified else "PARTIAL",
        "campaign": str(campaign),
        "checked_utc": datetime.now(UTC).isoformat(),
        "simulations_executed": 0,
        "source_sha256": sources,
        "script_sha256": sha(Path(__file__)),
        "completed_runs": len(summaries),
        "pending_run_ids": pending,
        "fault_rows_checked": len(rows),
        "published_table_verified": table_verified,
        "stratum_rows_checked": aggregate_count,
        "identities": {str(i): [list(v) for v in values] for i, values in identity_groups.items()},
        "rows": rows,
        "limits": [
            "WCT is recomputed from all request timestamps; "
            "first-new latency is checked from event timestamps.",
            "Sink classification is structural successor absence; it does not prove critical path.",
            "Five fixed failure identities reuse own-policy F0 and are not independent repeats.",
            "This validates endpoint arithmetic, not model accuracy or native answer quality.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.campaign.resolve())
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "completed_runs",
                    "fault_rows_checked",
                    "published_table_verified",
                    "stratum_rows_checked",
                )
            },
            indent=2,
        )
    )
