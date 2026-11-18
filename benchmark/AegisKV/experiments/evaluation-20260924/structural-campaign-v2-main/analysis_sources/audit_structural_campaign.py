"""Postprocess frozen summaries and two retained traces without changing runs."""

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

OUT = None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main(main_only=False):
    plan = json.loads((OUT / "PLAN.json").read_text())
    manifest = json.loads((OUT / "MANIFEST.json").read_text())
    profile = json.loads((OUT / plan["profile"]).read_text())
    application_path = OUT / "IMPLEMENTATION_APPLICATION.json"
    application = json.loads(application_path.read_text()) if application_path.exists() else None
    if application:
        assert application["status"] == "PASS" and application["freeze_ready"]
        for name, expected in application["source_sha256"].items():
            if name.startswith("python/"):
                assert sha(OUT / "source_snapshot" / name) == expected
    assert sha(OUT / plan["profile"]) == plan["profile_sha256"]
    planned = 135 if plan.get("matrix_scope") == "main-only" else 143
    assert len(plan["jobs"]) == len({job["id"] for job in plan["jobs"]}) == planned
    if "matrix_scope" in plan:
        seal = json.loads((OUT / "PLAN_SEAL.json").read_text())
        assert sha(OUT / "PLAN.json") == seal["plan_sha256"]
        assert sha(OUT / "MANIFEST.json") == seal["manifest_sha256"]
    for name, expected in manifest["source_sha256"].items():
        assert sha(OUT / "source_snapshot" / name) == expected
    for workload in plan["workloads"].values():
        payload = gzip.decompress((OUT / workload["path"]).read_bytes())
        assert hashlib.sha256(payload).hexdigest() == workload["sha256"]
        agents = json.loads(payload)
        for agent in agents:
            for call in agent["calls"]:
                assert call["model"] == profile["model"]
                assert len(call["output"]) <= call["output_limit_tokens"] == 16384
                assert len(call["prompt"]) + call["output_limit_tokens"] <= 40960
    recovery_rows, trace_checks, phase_checks, hashes, bindings = [], [], [], {}, []
    history_rows = []
    paired_rows = []
    eos_restore_checks = []
    for job in plan["jobs"]:
        if main_only and job["workflows"] != 8:
            continue
        base = OUT / "runs" / job["id"]
        summary = base / "summary.json"
        result = json.loads(summary.read_text())
        if application:
            assert result["design_version"] == application["design_version"]
        complete = json.loads((base / "COMPLETE.json").read_text())
        if "matrix_scope" in plan:
            assert (
                complete["job_sha256"]
                == hashlib.sha256(
                    (
                        json.dumps(
                            job, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2
                        )
                        + "\n"
                    ).encode()
                ).hexdigest()
            )
        assert sha(summary) == complete["summary_sha256"]
        assert sha(base / "config.json") == complete["config_sha256"]
        assert result["config_sha256"] == complete["config_sha256"]
        assert json.loads((base / "config.json").read_text()) == job["config"]
        assert json.loads((base / "failure.json").read_text()) == job["failure"]
        assert result["policy"] == job["policy"]
        assert result["predictor"] == "prior_predictor"
        assert result["duration_profile"] == "GridDurationProfile"
        assert result["workload_sha256"] == plan["workloads"][job["workload_id"]]["sha256"]
        provider = job["demand_provider"]
        assert result["attention_demand_provider"] == (
            provider["name"] if provider else job["config"]["attention"]
        )
        assert len(result["workflows"]) == job["workflows"]
        assert result["detailed_event_and_flow_logs_retained"] == job["retain_detailed_logs"]
        assert result["complete"] and result["terminal_allocations_zero"]
        assert result["output_tokens_exact"] and not result["oracle_reservation_count"]
        assert (result["failure"] is None) == (job["failure"] is None)
        bindings.append(dict(id=job["id"], config_failure_policy_workload_provider_bound=True))
        hashes[str(summary.relative_to(OUT))] = sha(summary)
        descriptor = job["failure_descriptor"]
        active_agents = {row["agent"] for row in result["recoveries"]}
        history_agents = {row["agent"] for row in result.get("history_restores", [])}
        assert active_agents.isdisjoint(history_agents)
        if descriptor:
            fault = result["failure"]
            assert fault["agent"] == descriptor["agent"]
            assert fault["invocation"] == descriptor["invocation"]
            assert fault["logical_tokens"] == descriptor["logical_trigger_tokens"]
            actual_phase = (
                "prefill" if fault["logical_tokens"] < descriptor["prompt_tokens"] else "decode"
            )
            assert actual_phase == descriptor["phase"]
            victims = sorted({row["agent"].split("/")[0] for row in result["recoveries"]})
            normal = json.loads((OUT / "runs" / job["f0_id"] / "summary.json").read_text())
            assert normal["config_sha256"] == result["config_sha256"]
            assert normal["workload_sha256"] == result["workload_sha256"]
            assert normal["workflows"].keys() == result["workflows"].keys()
            for workflow in normal["workflows"]:
                healthy = normal["workflows"][workflow]["wct_ns"] / 1e9
                failed = result["workflows"][workflow]["wct_ns"] / 1e9
                paired_rows.append(
                    {
                        **{
                            key: job[key]
                            for key in ("scenario", "workflows", "seed", "policy", "fault")
                        },
                        "id": job["id"],
                        "workflow": workflow,
                        "target_workflow": workflow == fault["agent"].split("/")[0],
                        "interrupted_workflow": workflow in victims,
                        "f0_wct_s": healthy,
                        "f1_wct_s": failed,
                        "delta_wct_s": failed - healthy,
                        "relative_delta": (failed - healthy) / healthy,
                    }
                )
            phase_checks.append(
                dict(
                    id=job["id"],
                    agent=fault["agent"],
                    invocation=fault["invocation"],
                    requested_phase=descriptor["phase"],
                    actual_phase=actual_phase,
                    logical_trigger_tokens=fault["logical_tokens"],
                    total_progress=descriptor["progress"],
                    failed_workers=fault["workers"],
                    failed_hosts=sorted(
                        {job["config"]["hosts"][worker] for worker in fault["workers"]}
                    ),
                    interrupted_workflows=victims,
                    interrupted_agents=sorted({row["agent"] for row in result["recoveries"]}),
                    queued_history_agents=sorted(history_agents),
                )
            )
        for category, recovery in [
            *(("active", row) for row in result["recoveries"]),
            *(("queued_history", row) for row in result.get("history_restores", [])),
        ]:
            assert recovery["latency_ns"] == (
                recovery["detection_ns"] + recovery["queue_ns"] + recovery["service_ns"]
            )
            if category == "queued_history":
                assert recovery["kind"] == "queued_history"
                assert recovery["invocation"] > 0 and recovery["durable_tokens"] > 0
                assert recovery["source_worker"] in result["failure"]["workers"]
                assert recovery["retry_worker"] not in result["failure"]["workers"]
                assert (
                    recovery["rebuild_tokens"]
                    == recovery["durable_tokens"] - recovery["checkpoint_tokens"]
                )
            if recovery["checkpoint_tokens"]:
                matching = [
                    row
                    for row in result["requests"]
                    if (row["agent"], row["invocation"])
                    == (recovery["agent"], recovery["invocation"])
                ]
                assert len(matching) == 1
                restore_done = recovery.get("restore_done_ns")
                eos_cancel = recovery.get("restore_canceled_at_eos_ns")
                assert (restore_done is None) != (eos_cancel is None)
                if eos_cancel is not None:
                    assert eos_cancel == matching[0]["finish_ns"]
                eos_restore_checks.append(
                    dict(
                        id=job["id"],
                        category=category,
                        agent=recovery["agent"],
                        invocation=recovery["invocation"],
                        restore_done_ns=restore_done,
                        restore_canceled_at_eos_ns=eos_cancel,
                        request_finish_ns=matching[0]["finish_ns"],
                        full_restore_after_eos=restore_done is not None
                        and restore_done > matching[0]["finish_ns"],
                    )
                )
            destination = recovery_rows if category == "active" else history_rows
            destination.append(
                {
                    **{
                        key: job[key]
                        for key in ("id", "scenario", "workflows", "seed", "policy", "fault")
                    },
                    "primary_target_agent": recovery["agent"] == job["failure"]["agent"],
                    "primary_target_workflow": recovery["agent"].split("/")[0]
                    == job["failure"]["agent"].split("/")[0],
                    **recovery,
                }
            )
        if job["retain_detailed_logs"]:
            with gzip.open(base / "events.jsonl.gz", "rt") as stream:
                events = [json.loads(line) for line in stream]
            commits = [row for row in events if row["kind"] == "checkpoint_commit"]
            updates = [row for row in events if row["kind"] == "topk_update"]

            def identity(row):
                return row["agent"], row["time_ns"], row["frontier"]

            assert Counter(map(identity, commits)) == Counter(map(identity, updates))
            assert len(commits) == result["metrics"]["checkpoint_commits"]
            assert all(row["tp_acks"] == job["config"]["tp"] for row in commits)
            assert all(row["frontier"] % job["config"]["checkpoint_tokens"] == 0 for row in updates)
            assert all(row["layers"] == job["config"]["depth"] for row in updates)
            trace_checks.append(
                dict(
                    id=job["id"],
                    checkpoint_only_topk_updates=True,
                    checkpoint_commits=len(commits),
                    topk_updates=len(updates),
                    all_checkpoint_frontiers_are_z_multiples=True,
                    all_tp_shards_acknowledged=True,
                    all_updates_use_configured_layer_depth=True,
                    query_block_count_updates=result["metrics"]["count_query_block_updates"],
                    event_count=len(events),
                    source_sha256=sha(base / "events.jsonl.gz"),
                )
            )
    columns = list(dict.fromkeys(key for row in recovery_rows for key in row))
    prefix = "main-" if main_only else ""
    audit_prefix = "MAIN_" if main_only else ""
    with (OUT / f"{prefix}recovery-events.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(recovery_rows)
    with (OUT / f"{prefix}history-restores.csv").open("w", newline="") as stream:
        fields = list(dict.fromkeys(key for row in history_rows for key in row)) or [
            "id",
            "agent",
            "kind",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(history_rows)
    if main_only:
        with (OUT / "main-paired-workflows.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(paired_rows[0]))
            writer.writeheader()
            writer.writerows(paired_rows)
    write_json(
        OUT / f"{audit_prefix}TRACE_MECHANISM_AUDIT.json",
        dict(
            all_passed=True,
            runs_audited=len(bindings),
            paired_failure_runs=len(phase_checks),
            campaign_status="PARTIAL" if main_only and planned == 143 else "COMPLETE",
            scope_description="complete 135-run main matrix only"
            if main_only
            else f"all {planned} frozen runs",
            trace_checks=trace_checks,
            recovery_event_count=len(recovery_rows),
            queued_history_restore_event_count=len(history_rows),
            active_victims_and_queued_histories_disjoint=True,
            recovery_time_decomposition_exact=True,
            eos_full_restore_exposure_checks=eos_restore_checks,
            eos_before_full_restore_count=sum(
                row["full_restore_after_eos"] for row in eos_restore_checks
            ),
            eos_canceled_prefetch_count=sum(
                row["restore_canceled_at_eos_ns"] is not None for row in eos_restore_checks
            ),
            source_sha256=hashes,
            audit_script_sha256=sha(Path(__file__)),
            plan_sha256=sha(OUT / "PLAN.json"),
            manifest_sha256=sha(OUT / "MANIFEST.json"),
            profile_sha256=sha(OUT / plan["profile"]),
            implementation_application_sha256=sha(application_path) if application else None,
            source_snapshot_hashes_all_verified=True,
            all_workloads_hashes_and_declared_caps_verified=True,
            run_bindings=bindings,
            seal_scope="independent post-execution binding audit, not a claimed pre-run seal",
            scope="event/accounting consistency in a simulator, not numerical kernel validation",
        ),
    )
    write_json(
        OUT / f"{audit_prefix}PHASE_AUDIT.json",
        dict(
            all_passed=True,
            rows=phase_checks,
            limits=(
                "same total-token trigger across policies; prefill versus decode "
                "use different total-progress points"
            ),
        ),
    )
    print(f"audited {len(phase_checks)} failures and {len(trace_checks)} full traces")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--main-only", action="store_true")
    args = parser.parse_args()
    OUT = args.out.resolve()
    main(args.main_only)
