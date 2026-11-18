"""Read-only recheck of the preidentified 8B load0.9 fault1 routing adverse case."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(campaign):
    plan = read(campaign / "PLAN.json")
    manifest = read(campaign / "MANIFEST.json")
    runtime = campaign / "source_snapshot/python/moonkvsim/aegiskv/current/runtime.py"
    assert sha(runtime) == manifest["source_sha256"]["python/moonkvsim/aegiskv/current/runtime.py"]
    jobs = {j["id"]: j for j in plan["jobs"]}
    inputs, cases, healthy = {}, {}, {}
    for policy in ("dram", "aegiskv"):
        for fault, destination in (("F1-1", cases), ("F0", healthy)):
            identity = f"Qwen3-8B-load0.9-{policy}-{fault}"
            folder = campaign / "runs" / identity
            complete = read(folder / "COMPLETE.json")
            assert complete["summary_sha256"] == sha(folder / "summary.json")
            summary = read(folder / "summary.json")
            assert summary["complete"] and summary["output_tokens_exact"]
            assert read(folder / "config.json") == jobs[identity]["config"]
            assert read(folder / "failure.json") == jobs[identity]["failure"]
            destination[policy] = summary
            inputs[str((folder / "summary.json").relative_to(campaign))] = sha(
                folder / "summary.json"
            )
    dram, aegis = cases["dram"], cases["aegiskv"]
    assert dram["failure"] == aegis["failure"]
    assert healthy["dram"]["workflows"] == healthy["aegiskv"]["workflows"]
    target = dram["failure"]["agent"]
    target_workflow = target.split("/", 1)[0]
    changes = {
        wf: aegis["workflows"][wf]["wct_ns"] - value["wct_ns"]
        for wf, value in dram["workflows"].items()
    }
    affected = "8f0c326505148464"
    root_agent = affected + "/f81ca32572124425"
    boundary_agent = "7c6edfe35e844a5d/889e15bbdc2b6055"
    routing = {}
    for policy, summary in cases.items():
        request_map = {r["agent"]: r for r in summary["requests"]}
        assert len(request_map) == len(summary["requests"]), (
            "single-invocation routing reconstruction only"
        )
        fork_ns = request_map[root_agent]["finish_ns"]
        folder = campaign / "runs" / f"Qwen3-8B-load0.9-{policy}-F1-1"
        path = folder / "events.jsonl.gz"
        inputs[str(path.relative_to(campaign))] = sha(path)
        events = [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
        submits = [e for e in events if e["kind"] == "submit" and e["time_ns"] == fork_ns]
        assert submits, "no event evidence: cannot reconstruct tie-break ordering"
        assert all(e["agent"].startswith(affected + "/") for e in submits)
        failed_workers = set(summary["failure"]["workers"])
        config = jobs[f"Qwen3-8B-load0.9-{policy}-F1-1"]["config"]
        counts = {
            worker: 0 for worker in range(len(config["hosts"])) if worker not in failed_workers
        }
        assert fork_ns > summary["failure"]["time_ns"]
        for request in summary["requests"]:
            if request["submit_ns"] < fork_ns < request["finish_ns"]:
                counts[request["worker"]] += 1
        initial_counts = dict(counts)
        assignments = []
        for event in submits:
            assert event["local_prefix_tokens"] == 0
            assigned = min(counts, key=lambda worker: (counts[worker], worker))
            assert assigned == event["worker"] == request_map[event["agent"]]["worker"]
            assignments.append({"agent": event["agent"], "worker": assigned})
            counts[assigned] += 1
        children = [request_map[e["agent"]] for e in submits]
        join = request_map[affected + "/final"]
        assert max(r["finish_ns"] for r in children) == join["submit_ns"]
        recovery = next(r for r in summary["recoveries"] if r["agent"] == target)
        active_ids = {r["agent"] for r in summary["recoveries"]}
        displaced = sorted(
            {
                event["agent"]
                for event in events
                if event["kind"] == "submit"
                and event["worker"] in failed_workers
                and event["time_ns"]
                <= summary["failure"]["time_ns"]
                < request_map[event["agent"]]["finish_ns"]
                and event["agent"] not in active_ids
            }
        )
        routing[policy] = {
            "fork_ns": fork_ns,
            "initial_outstanding_counts": initial_counts,
            "event_order_reconstructed_assignments": assignments,
            "boundary_request": request_map[boundary_agent],
            "adverse_workflow": summary["workflows"][affected],
            "branches": children,
            "join": join,
            "active_co_victim_agent_ids": sorted(
                r["agent"] for r in summary["recoveries"] if r["agent"] != target
            ),
            "history_restore_agent_ids": sorted(
                r["agent"] for r in summary.get("history_restores", [])
            ),
            "displaced_queued_agent_ids": displaced,
            "failed_host_ids": sorted({config["hosts"][w] for w in failed_workers}),
            "scope": jobs[f"Qwen3-8B-load0.9-{policy}-F1-1"]["failure"]["scope"],
            "target_recovery": recovery,
        }
    return {
        "status": "PASS_OBSERVED_ROUTING_RECONSTRUCTION",
        "campaign": str(campaign),
        "runtime_sha256": sha(runtime),
        "simulations_executed": 0,
        "input_sha256": inputs,
        "script_sha256": sha(Path(__file__)),
        "failure": dram["failure"],
        "target_workflow": target_workflow,
        "target_aegis_minus_dram_ns": changes[target_workflow],
        "all_workflow_total_aegis_minus_dram_ns": sum(changes.values()),
        "workflow_differences_ns": changes,
        "improved": sum(v < 0 for v in changes.values()),
        "worsened": sum(v > 0 for v in changes.values()),
        "unchanged": sum(v == 0 for v in changes.values()),
        "original_adverse_workflow": affected,
        "original_adverse_workflow_difference_ns": changes[affected],
        "original_case_remains_adverse": sum(changes.values()) > 0 and changes[affected] > 0,
        "routing": routing,
        "limits": [
            "Count is queued plus busy; ordinary admission/queue duration "
            "is not separately logged.",
            "Event order and final-worker request intervals support "
            "this specific late post-fault fork.",
            "This is a retained descriptive model outcome, not production scheduler causality.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = check(args.campaign.resolve())
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "original_case_remains_adverse",
                    "target_aegis_minus_dram_ns",
                    "all_workflow_total_aegis_minus_dram_ns",
                    "original_adverse_workflow_difference_ns",
                )
            },
            indent=2,
        )
    )
