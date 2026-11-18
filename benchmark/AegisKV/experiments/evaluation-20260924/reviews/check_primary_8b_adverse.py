"""Read-only exact arithmetic and routing reconstruction for a retained adverse case."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    base = Path(__file__).resolve().parent
    campaign = base.parent / "formal-core-v1"
    plan, manifest = (read(campaign / name) for name in ("PLAN.json", "MANIFEST.json"))
    hashes = {"PLAN.json": sha(campaign / "PLAN.json")}
    for name, expected in manifest["control_sha256"].items():
        assert sha(campaign / name) == expected
    results = {}
    for job in plan["jobs"]:
        if job["model"] != "Qwen3-8B":
            continue
        directory = campaign / "runs" / job["id"]
        summary, complete = (read(directory / name) for name in ("summary.json", "COMPLETE.json"))
        assert complete["summary_sha256"] == sha(directory / "summary.json")
        assert complete["job_sha256"] == hashlib.sha256(encoded(job)).hexdigest()
        assert read(directory / "config.json") == job["config"]
        assert read(directory / "failure.json") == job["failure"]
        assert summary["config_sha256"] == sha(directory / "config.json")
        assert summary["workload_sha256"] == plan["workloads"][job["workload"]]["content_sha256"]
        assert summary["complete"] and summary["policy"] == job["policy"]
        assert summary["oracle_reservation_count"] == 0
        hashes[str((directory / "summary.json").relative_to(campaign))] = complete["summary_sha256"]
        results[job["id"]] = summary

    def result(load, policy, fault):
        return results[f"Qwen3-8B-load{load}-{policy}-{fault}"]

    case = {policy: result("0.9", policy, "F1-1") for policy in ("dram", "aegiskv")}
    dram, aegis = case.values()
    assert dram["failure"] == aegis["failure"]
    assert result("0.9", "dram", "F0")["workflows"] == result("0.9", "aegiskv", "F0")[
        "workflows"
    ]
    workflow_changes = {
        key: aegis["workflows"][key]["wct_ns"] - row["wct_ns"]
        for key, row in dram["workflows"].items()
    }
    affected = "8f0c326505148464"
    fork_time = 116_107_340_965
    routing = {}
    for policy, summary in case.items():
        directory = campaign / "runs" / f"Qwen3-8B-load0.9-{policy}-F1-1"
        path = directory / "events.jsonl.gz"
        hashes[str(path.relative_to(campaign))] = sha(path)
        events = [json.loads(row) for row in gzip.decompress(path.read_bytes()).splitlines()]
        request_map = {r["agent"]: r for r in summary["requests"]}
        counts = {worker: 0 for worker in range(1, 8)}
        for request in summary["requests"]:
            if request["submit_ns"] < fork_time < request["finish_ns"]:
                counts[request["worker"]] += 1
        initial = counts.copy()
        assignments = []
        for event in events:
            if event["kind"] == "submit" and event["time_ns"] == fork_time:
                assert event["local_prefix_tokens"] == 0
                selected = min(counts, key=lambda worker: (counts[worker], worker))
                assert selected == event["worker"]
                assignments.append(dict(agent=event["agent"], worker=selected))
                counts[selected] += 1
        failed_time, target = summary["failure"]["time_ns"], summary["failure"]["agent"]
        queued = [
            event["agent"]
            for event in events
            if event["kind"] == "submit"
            and event["time_ns"] <= failed_time
            and event["worker"] == 0
            and request_map[event["agent"]]["finish_ns"] > failed_time
            and event["agent"] != target
        ]
        routing[policy] = dict(
            outstanding_requests_before_fork=initial,
            reconstructed_assignments=assignments,
            active_co_victim_agents=[
                r["agent"] for r in summary["recoveries"] if r["agent"] != target
            ],
            queued_displaced_agents=queued,
            boundary_request=request_map["7c6edfe35e844a5d/889e15bbdc2b6055"],
            adverse_workflow=summary["workflows"][affected],
            adverse_requests=[
                r for r in summary["requests"] if r["agent"].startswith(affected + "/")
            ],
            recovery=summary["recoveries"],
        )
    matched = []
    for load in ("0.3", "0.65", "0.9"):
        for fault in ("F0", *(f"F1-{i}" for i in range(5))):
            first, second = (result(load, policy, fault) for policy in ("static_hbm", "aegiskv"))
            equality = {
                field: first[field] == second[field]
                for field in ("workflows", "requests", "recoveries")
            }
            assert all(equality.values())
            matched.append(dict(load=load, fault=fault, identical=equality))
    load65 = {}
    for policy in ("none", "all_dram", "dram", "static_hbm", "aegiskv"):
        healthy = mean(r["wct_ns"] for r in result("0.65", policy, "F0")["workflows"].values())
        failed = [
            mean(r["wct_ns"] for r in result("0.65", policy, f"F1-{i}")["workflows"].values())
            for i in range(5)
        ]
        load65[policy] = dict(
            healthy_mean_ns=healthy,
            scenario_workflow_means_ns=failed,
            mean_failed_wct_ns=mean(failed),
            mean_paired_penalty_ns=mean(failed) - healthy,
        )
    output = dict(
        evidence="read-only frozen summaries/events; no new simulation or queue-wait estimate",
        validated_8b_runs=len(results),
        failure=dram["failure"],
        fork_time_ns=fork_time,
        workflow_changes_ns=workflow_changes,
        total_wct_change_ns=sum(workflow_changes.values()),
        improved_workflows=sum(value < 0 for value in workflow_changes.values()),
        worsened_workflows=sum(value > 0 for value in workflow_changes.values()),
        unchanged_workflows=sum(value == 0 for value in workflow_changes.values()),
        routing=routing,
        static_aegis_equality=matched,
        load065=load65,
        input_sha256=hashes,
        source_sha256=sha(Path(__file__)),
    )
    (base / "PRIMARY_8B_ADVERSE.json").write_bytes(encoded(output))
    print(
        "validated runs",
        len(results),
        "all-workflow total change s",
        sum(workflow_changes.values()) / 1e9,
    )
    print("same static/Aegis completion records", len(matched), "conditions")


if __name__ == "__main__":
    main()
