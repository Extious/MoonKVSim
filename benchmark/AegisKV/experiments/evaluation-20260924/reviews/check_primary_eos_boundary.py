"""Read-only sufficient-condition check for EOS safety of the frozen dense primary."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    campaign = (args.campaign or base.parent / "formal-core-v1").resolve()
    output = args.output or base / "PRIMARY_EOS_BOUNDARY_CHECK.json"
    plan, manifest = (read(campaign / name) for name in ("PLAN.json", "MANIFEST.json"))
    hashes, violations, pending, checks = {}, [], [], []
    complete_count = no_checkpoint_count = healthy_count = 0
    per_model = Counter()

    def require(condition, message):
        if not condition:
            violations.append(message)

    for name in ("PLAN.json", "MANIFEST.json", "PRIORS.json"):
        hashes[name] = sha(campaign / name)
    for name, expected in manifest["control_sha256"].items():
        require(sha(campaign / name) == expected, f"control hash mismatch: {name}")
    for name, expected in manifest["source_sha256"].items():
        path = campaign / "source_snapshot" / name
        require(path.exists() and sha(path) == expected, f"frozen source hash mismatch: {name}")
    for name, expected in manifest["profile_sha256"].items():
        hashes[name] = sha(campaign / name)
        require(hashes[name] == expected, f"profile hash mismatch: {name}")
    for name, specification in plan["workloads"].items():
        hashes[specification["path"]] = sha(campaign / specification["path"])
        require(hashes[specification["path"]] == specification["sha256"], f"workload hash: {name}")

    for job in plan["jobs"]:
        directory = campaign / "runs" / job["id"]
        if not (directory / "COMPLETE.json").exists():
            pending.append(job["id"])
            continue
        complete_count += 1
        complete, summary = (read(directory / name) for name in ("COMPLETE.json", "summary.json"))
        for name in ("COMPLETE.json", "summary.json", "config.json", "failure.json"):
            hashes[str((directory / name).relative_to(campaign))] = sha(directory / name)
        require(
            complete["summary_sha256"] == sha(directory / "summary.json"),
            job["id"] + ": summary hash",
        )
        require(
            complete["job_sha256"] == hashlib.sha256(encoded(job)).hexdigest(),
            job["id"] + ": job hash",
        )
        require(
            complete["profile_sha256"]
            == manifest["profile_sha256"][f"profiles/{job['model']}.json"]
            and complete["priors_sha256"] == hashes["PRIORS.json"]
            and complete["workload_sha256"] == plan["workloads"][job["workload"]]["sha256"],
            job["id"] + ": profile/prior/workload binding",
        )
        require(read(directory / "config.json") == job["config"], job["id"] + ": config")
        require(
            read(directory / "failure.json") == job["failure"],
            job["id"] + ": failure specification",
        )
        require(
            summary["config_sha256"] == sha(directory / "config.json"), job["id"] + ": config hash"
        )
        require(
            summary["complete"] and summary["policy"] == job["policy"],
            job["id"] + ": complete/policy",
        )
        require(
            summary["design_version"] == manifest["design_version"]
            and summary["workload_sha256"]
            == plan["workloads"][job["workload"]]["content_sha256"],
            job["id"] + ": version/workload content",
        )
        require(summary["oracle_reservation_count"] == 0, job["id"] + ": oracle reservation")
        require(job["config"]["attention"] == "dense", job["id"] + ": config is not dense")
        require(
            summary["attention_demand_provider"] == "dense", job["id"] + ": provider is not dense"
        )
        if job["failure"] is None:
            healthy_count += 1
        requests = {(row["agent"], row["invocation"]): row for row in summary["requests"]}
        for recovery in summary["recoveries"]:
            if not recovery["checkpoint_tokens"]:
                no_checkpoint_count += 1
                continue
            per_model[job["model"]] += 1
            key = recovery["agent"], recovery["invocation"]
            first, restore = recovery.get("first_new_token_ns"), recovery.get("restore_done_ns")
            request = requests[key]
            valid = (
                first is not None
                and restore is not None
                and restore <= first <= request["finish_ns"]
                and request["output_tokens"] > 0
            )
            require(valid, f"{job['id']}: restore-before-first-new condition fails for {key}")
            checks.append(
                dict(
                    id=job["id"],
                    model=job["model"],
                    policy=job["policy"],
                    agent=key[0],
                    invocation=key[1],
                    checkpoint_tokens=recovery["checkpoint_tokens"],
                    restore_done_ns=restore,
                    first_new_token_ns=first,
                    request_finish_ns=request["finish_ns"],
                    margin_ns=first - restore
                    if first is not None and restore is not None
                    else None,
                    sufficient_condition_passes=valid,
                )
            )
    result = dict(
        status="FAIL" if violations else "PARTIAL" if pending else "PASS",
        evidence="read-only sealed summaries of the original frozen dense primary; no reruns",
        scope=(
            "Full checkpoint restore finishes by first newly emitted token. Accepted EOS "
            "cannot precede that token, so old EOS-waits-for-restore code is unexposed. "
            "This is a sufficient EOS-boundary check, not general equivalence of source versions."
        ),
        created_utc=datetime.now(UTC).isoformat(),
        campaign=str(campaign),
        design_version=manifest["design_version"],
        expected_runs=len(plan["jobs"]),
        complete_runs=complete_count,
        healthy_runs=healthy_count,
        pending_run_ids=pending,
        checkpoint_recoveries=len(checks),
        checkpoint_recoveries_per_model=dict(per_model),
        no_checkpoint_recoveries=no_checkpoint_count,
        all_available_checkpoint_recoveries_pass=all(
            r["sufficient_condition_passes"] for r in checks
        ),
        min_restore_to_first_new_margin_ns=min(
            (r["margin_ns"] for r in checks if r["margin_ns"] is not None), default=None
        ),
        checks=checks,
        violations=violations,
        input_sha256=hashes,
        source_sha256=sha(Path(__file__)),
    )
    output.write_bytes(encoded(result))
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "complete_runs",
                    "expected_runs",
                    "checkpoint_recoveries",
                    "checkpoint_recoveries_per_model",
                    "no_checkpoint_recoveries",
                    "min_restore_to_first_new_margin_ns",
                    "violations",
                )
            },
            indent=2,
        )
    )
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
