"""Match revised summaries to historical conditions without pooling versions."""

import csv
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / "structural-campaign-v1"


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


plan = read(OUT / "PLAN.json")
assert len(plan["jobs"]) == 135
raw = []
pairs = []
run_checks = []
sources = {}
for job in plan["jobs"]:
    before_path = OLD / "runs" / job["id"] / "summary.json"
    after_path = OUT / "runs" / job["id"] / "summary.json"
    before, after = read(before_path), read(after_path)
    assert (
        before["workload_sha256"] == after["workload_sha256"]
        and before["workflows"].keys() == after["workflows"].keys()
    )
    sources[str(before_path.relative_to(OUT.parent))] = sha(before_path)
    sources[str(after_path.relative_to(OUT.parent))] = sha(after_path)
    for wf in before["workflows"]:
        b = before["workflows"][wf]["wct_ns"]
        a = after["workflows"][wf]["wct_ns"]
        raw.append(
            dict(
                id=job["id"],
                scenario=job["scenario"],
                seed=job["seed"],
                policy=job["policy"],
                fault=job["fault"],
                workflow=wf,
                historical_wct_s=b / 1e9,
                revised_wct_s=a / 1e9,
                revised_minus_historical_wct_s=(a - b) / 1e9,
                exactly_equal_ns=a == b,
            )
        )
    if job["fault"] == "F0":
        continue
    f0old = read(OLD / "runs" / job["f0_id"] / "summary.json")
    f0new = read(OUT / "runs" / job["f0_id"] / "summary.json")
    for field in ("agent", "invocation", "logical_tokens", "total_tokens"):
        assert before["failure"][field] == after["failure"][field], (job["id"], field)
    run_checks.append(
        dict(
            id=job["id"],
            same_logical_target=True,
            historical_fault_ns=before["failure"]["time_ns"],
            revised_fault_ns=after["failure"]["time_ns"],
            failed_workers_equal=before["failure"]["workers"] == after["failure"]["workers"],
            active_victims_equal=sorted(r["agent"] for r in before["recoveries"])
            == sorted(r["agent"] for r in after["recoveries"]),
            historical_active_agents=";".join(sorted(r["agent"] for r in before["recoveries"])),
            revised_active_agents=";".join(sorted(r["agent"] for r in after["recoveries"])),
            revised_queued_history_agents=";".join(
                sorted(r["agent"] for r in after.get("history_restores", []))
            ),
        )
    )
    for wf in before["workflows"]:
        old_delta = before["workflows"][wf]["wct_ns"] - f0old["workflows"][wf]["wct_ns"]
        new_delta = after["workflows"][wf]["wct_ns"] - f0new["workflows"][wf]["wct_ns"]
        pairs.append(
            dict(
                id=job["id"],
                scenario=job["scenario"],
                seed=job["seed"],
                policy=job["policy"],
                fault=job["fault"],
                workflow=wf,
                target_workflow=wf == job["failure"]["agent"].split("/")[0],
                historical_paired_delta_s=old_delta / 1e9,
                revised_paired_delta_s=new_delta / 1e9,
                revised_minus_historical_paired_delta_s=(new_delta - old_delta) / 1e9,
                sign_changed=(old_delta > 0) - (old_delta < 0) != (new_delta > 0) - (new_delta < 0),
            )
        )
assert len(raw) == 1080 and len(pairs) == 720 and len(run_checks) == 90
write_csv(OUT / "version-workflow-wct.csv", raw)
write_csv(OUT / "version-paired-deltas.csv", pairs)
write_csv(OUT / "version-fault-identities.csv", run_checks)
healthy = [r for r in raw if r["fault"] == "F0"]
restart = [r for r in raw if r["policy"] == "none" and r["fault"] != "F0"]
result = dict(
    passed=True,
    versions_are_not_pooled=True,
    runs=135,
    matched_workflow_wct_rows=len(raw),
    paired_delta_rows=len(pairs),
    healthy_workflows=len(healthy),
    healthy_wct_changed_count=sum(not r["exactly_equal_ns"] for r in healthy),
    restart_failed_workflows=len(restart),
    restart_failed_wct_changed_count=sum(not r["exactly_equal_ns"] for r in restart),
    revised_negative_paired_deltas=sum(r["revised_paired_delta_s"] < 0 for r in pairs),
    historical_negative_paired_deltas=sum(r["historical_paired_delta_s"] < 0 for r in pairs),
    paired_delta_sign_changes=sum(r["sign_changed"] for r in pairs),
    changed_fault_wall_count=sum(
        r["historical_fault_ns"] != r["revised_fault_ns"] for r in run_checks
    ),
    changed_failed_worker_set_count=sum(not r["failed_workers_equal"] for r in run_checks),
    changed_active_victim_set_count=sum(not r["active_victims_equal"] for r in run_checks),
    revised_queued_history_records=sum(
        len(read(OUT / "runs" / job["id"] / "summary.json").get("history_restores", []))
        for job in plan["jobs"]
    ),
    source_sha256=sources,
    script_sha256=sha(Path(__file__)),
)
(OUT / "VERSION_COMPARISON.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, indent=2))
