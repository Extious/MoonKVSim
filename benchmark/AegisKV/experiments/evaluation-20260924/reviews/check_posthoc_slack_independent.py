"""Read existing artifacts; never instantiate a runtime or execute a simulation."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "slack-mechanism-posthoc-v1"


def read(path):
    return json.loads(path.read_text())


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def lines(path):
    return [json.loads(x) for x in gzip.decompress(path.read_bytes()).splitlines()]


def main():
    plan, manifest, seal = (read(OUT / n) for n in ("PLAN.json", "MANIFEST.json", "SEAL.json"))
    for name, digest in seal.items():
        assert sha(OUT / name) == digest, name
    for name, digest in manifest["source_sha256"].items():
        assert sha(OUT / "source_snapshot" / name) == digest, name
    assert manifest["plan_sha256"] == sha(OUT / "PLAN.json")
    assert plan["protocol_sha256"] == sha(OUT / "PROTOCOL.md")
    assert sha(OUT / plan["profile"]) == plan["profile_sha256"]
    assert sha(OUT / plan["workload"]) == plan["workload_compressed_sha256"]
    workload_bytes = gzip.decompress((OUT / plan["workload"]).read_bytes())
    assert hashlib.sha256(workload_bytes).hexdigest() == plan["workload_sha256"]
    snapshot = OUT / "source_snapshot/python"
    sys.path.insert(0, str(snapshot))
    model = importlib.import_module("moonkvsim.aegiskv.current.model")
    tracker_module = importlib.import_module("moonkvsim.aegiskv.current.tracker")
    profile_module = importlib.import_module("moonkvsim.aegiskv.evaluation_profile")
    for module in (model, tracker_module, profile_module):
        assert Path(module.__file__).is_relative_to(snapshot)
    agents = tuple(
        model.Agent(
            **{
                **a,
                "predecessors": tuple(a["predecessors"]),
                "calls": tuple(
                    model.Invocation(
                        **{**c, "prompt": tuple(c["prompt"]), "output": tuple(c["output"])}
                    )
                    for c in a["calls"]
                ),
            }
        )
        for a in json.loads(workload_bytes)
    )
    by_key = {a.key: a for a in agents}
    assert len(agents) == 4
    assert all(len(a.calls) == 1 and a.calls[0].output_limit_tokens == 16384 for a in agents)
    jobs = plan["jobs"]
    assert len(jobs) == len({j["id"] for j in jobs}) == 10
    baseline = jobs[0]["config"]
    for j in jobs:
        diff = {k for k in baseline if j["config"][k] != baseline[k]}
        assert diff <= {"slack_mode", "dram_bytes_per_host"}
        assert j["config"]["hbm_cap_bytes"] == j["config"]["initial_quota_bytes"] == 0
        assert j["config"]["compute_dma_slowdown"] == 0
        assert j["policy"] == ("none" if j["variant"] == "restart" else "dram")
    c = model.Config(**{**baseline, "hosts": tuple(baseline["hosts"])})
    capacity = []
    for row in plan["capacity_arithmetic"]:
        n = row["frontier"]
        complete = (
            n * c.layers * c.kv_bytes_per_token_per_layer_rank
            + ((n + c.block_tokens - 1) // c.block_tokens) * c.layers * 24
        )
        append = c.prefix_bytes(c.checkpoint_tokens) + c.layers * c.metadata_layer_bytes(
            n + c.checkpoint_tokens
        )
        assert complete == c.checkpoint_bytes(n) == row["complete_bytes"]
        assert append == row["next_append_bytes"]
        assert complete + append == row["committed_plus_pending_bytes"] < plan["tight_budget_bytes"]
        capacity.append(row)
    assert c.checkpoint_bytes(8192) > plan["rejected_before_execution_budget_bytes"]
    assert c.checkpoint_bytes(1280) + c.checkpoint_bytes(8448) > plan["tight_budget_bytes"]
    seal_time = (OUT / "SEAL.json").stat().st_mtime_ns
    first_config_time = min(
        (OUT / "runs" / j["id"] / "config.json").stat().st_mtime_ns for j in jobs
    )
    assert max((OUT / n).stat().st_mtime_ns for n in seal) <= seal_time < first_config_time
    summaries, transitions, pairs, resources, hashes = {}, {}, [], [], {}
    for job in jobs:
        folder = OUT / "runs" / job["id"]
        result, complete = read(folder / "summary.json"), read(folder / "COMPLETE.json")
        assert complete["id"] == job["id"]
        for key, expected in {
            "plan_sha256": sha(OUT / "PLAN.json"),
            "manifest_sha256": sha(OUT / "MANIFEST.json"),
            "job_sha256": value_sha(job),
            "profile_sha256": plan["profile_sha256"],
            "workload_sha256": plan["workload_sha256"],
        }.items():
            assert complete[key] == expected
        for name, digest in complete["artifacts_sha256"].items():
            assert sha(folder / name) == digest, (job["id"], name)
        assert read(folder / "config.json") == job["config"]
        assert read(folder / "failure.json") == job["failure"]
        assert result["config_sha256"] == sha(folder / "config.json")
        assert result["workload_sha256"] == plan["workload_sha256"]
        assert result["policy"] == job["policy"]
        assert (
            result["predictor"] == "prior_predictor"
            and result["duration_profile"] == "GridDurationProfile"
        )
        assert (
            result["complete"]
            and result["output_tokens_exact"]
            and result["terminal_allocations_zero"]
        )
        assert (
            result["oracle_reservation_count"] == 0
            and result["detailed_event_and_flow_logs_retained"]
        )
        assert result["metrics"]["emitted_tokens"] == sum(len(a.calls[0].output) for a in agents)
        assert (
            result["metrics"]["replica_hbm_byte_ns"]
            == result["metrics"].get("hot_copy_bytes", 0)
            == 0
        )
        rows = lines(folder / "state-transitions.jsonl.gz")
        budget = job["config"]["dram_bytes_per_host"]
        area = 0
        for frame in rows:
            for ledger in frame["dram_accounts"].values():
                assert all(v >= 0 for v in ledger.values()) and sum(ledger.values()) == budget
        for left, right in pairwise(rows):
            assert right["time_ns"] >= left["time_ns"]
            area += sum(budget - ledger["FREE"] for ledger in left["dram_accounts"].values()) * (
                right["time_ns"] - left["time_ns"]
            )
        assert area == result["metrics"]["replica_dram_byte_ns"]
        peaks = {
            h: max(budget - r["dram_accounts"][h]["FREE"] for r in rows)
            for h in ("dram:0", "dram:1")
        }
        assert all(result["peak_bytes"][h] == n <= budget for h, n in peaks.items())
        resources.append(dict(id=job["id"], byte_ns=area, per_host_peaks=peaks))
        summaries[job["id"]], transitions[job["id"]] = result, rows
        hashes[job["id"]] = sha(folder / "summary.json")
    for job in jobs:
        result = summaries[job["id"]]
        if not job["failure"]:
            assert (
                result["failure"] is None
                and read(OUT / "runs" / job["id"] / "fault-state.json") is None
            )
            continue
        config = model.Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
        recorded = read(OUT / "runs" / job["id"] / "fault-state.json")
        frame = recorded["frame"]
        frame_before_hash = value_sha(frame)
        tracker = tracker_module.Tracker(agents, config)
        tracker.states = {k: tracker_module.Estimate(**v) for k, v in frame["tracker"].items()}
        raw = tracker.slack(frame["time_ns"])
        profile = profile_module.GridDurationProfile(OUT / plan["profile"])
        recalculated = {}
        for key, state in frame["states"].items():
            full = profile(config, by_key[key].calls[0], 0, state["durable"], "prefill")
            effective = raw[key] if config.slack_mode == "dag" else 0
            recalculated[key] = dict(
                guarded_dag_slack_ns=raw[key],
                effective_slack_ns=effective,
                full_reconstruction_ns=full,
                exposure_ns=max(0, full - effective),
                computed_checkpoint_candidate_bytes=config.checkpoint_bytes(
                    state["computed"] // config.checkpoint_tokens * config.checkpoint_tokens
                )
                * config.tp,
            )
        assert value_sha(frame) == frame_before_hash
        assert {
            "agents": recalculated,
            "fallback_workflows": sorted(tracker.fallback_workflows),
        } == recorded["offline_scores"]
        assert not tracker.fallback_workflows
        assert raw["wf0/a_critical"] == 0 and raw["wf0/b_expensive"] == 80 * 10**9
        assert (
            not frame["fault_fired"]
            and frame["time_ns"] == result["failure"]["time_ns"] == 6255890594
        )
        assert result["failure"] == dict(
            agent="wf0/a_critical",
            invocation=0,
            logical_tokens=1536,
            time_ns=6255890594,
            total_tokens=9216,
            workers=[0],
        )
        states = frame["states"]
        assert (states["wf0/a_critical"]["worker"], states["wf0/b_expensive"]["worker"]) == (0, 1)
        assert (states["wf0/a_critical"]["peer"], states["wf0/b_expensive"]["peer"]) == (2, 2)
        assert (states["wf0/a_critical"]["computed"], states["wf0/b_expensive"]["computed"]) == (
            1536,
            8608,
        )
        interrupted = sorted({r["agent"] for r in result["recoveries"]})
        assert interrupted == ["wf0/a_critical"]
        assert all(not q for q in frame["queues"].values())
        recovery = result["recoveries"][0]
        assert recovery["retry_worker"] == 2 and recovery["queue_ns"] == 0
        assert (
            recovery["latency_ns"]
            == recovery["detection_ns"] + recovery["queue_ns"] + recovery["service_ns"]
        )
        calls = {r["agent"]: r for r in result["requests"]}
        assert calls["wf0/a_critical"]["finish_ns"] > calls["wf0/b_expensive"]["finish_ns"]
        assert calls["wf0/join"]["submit_ns"] == calls["wf0/a_critical"]["finish_ns"]
        f0 = summaries[job["f0_id"]]
        assert (
            f0["config_sha256"] == result["config_sha256"]
            and f0["workload_sha256"] == result["workload_sha256"]
        )
        assert calls["wf0/join"]["latency_ns"] == next(
            r["latency_ns"] for r in f0["requests"] if r["agent"] == "wf0/join"
        )
        pairs.append(
            dict(
                id=job["id"],
                delta_wct_ns=result["workflows"]["wf0"]["wct_ns"]
                - f0["workflows"]["wf0"]["wct_ns"],
                recovery=recovery,
                failed_workers=[0],
                worker_host_ids=[0],
                lost_dram_host_ids=[],
                co_victim_agent_ids=[],
                displaced_queued_agent_ids=[],
                scores=recalculated,
                checkpoints=frame["checkpoints"],
            )
        )
    deltas = {p["id"]: p["delta_wct_ns"] for p in pairs}
    assert deltas == {
        "dram1342177280-dag-F1": 24045264,
        "dram1342177280-zero-F1": 134793723,
        "dram4294967296-dag-F1": 24045264,
        "dram4294967296-zero-F1": 24045264,
        "restart-F1": 134793723,
    }
    assert (
        len({r["workflows"]["wf0"]["wct_ns"] for k, r in summaries.items() if k.endswith("F0")})
        == 1
    )
    retirement = []
    for identity, rows in transitions.items():
        for before, after in pairwise(rows):
            if after["time_ns"] > 6255890594 or after["fault_fired"]:
                break
            cp_id = before["states"]["wf0/a_critical"]["checkpoint_identity"]
            if (
                cp_id is not None
                and after["states"]["wf0/a_critical"]["checkpoint_identity"] is None
            ):
                cp = next(cp for cp in before["checkpoints"] if cp["identity"] == cp_id)
                assert cp["frontier"] == 1024 and cp["allocated_bytes"] == 151008768
                b = next(cp for cp in after["checkpoints"] if cp["key"] == "wf0/b_expensive")
                assert after["time_ns"] == 1028336003 and b["frontier"] == 7936 and b["pending"]
                assert b["allocated_bytes"] == 1208177280
                assert b["allocated_bytes"] + cp["allocated_bytes"] > 1342177280
                retirement.append(
                    dict(
                        id=identity,
                        time_ns=after["time_ns"],
                        retired_checkpoint_frontier=1024,
                        critical_bytes=cp["allocated_bytes"],
                        expensive_committed_plus_pending_bytes=b["allocated_bytes"],
                        capacity_excess_if_both_retained_bytes=b["allocated_bytes"]
                        + cp["allocated_bytes"]
                        - 1342177280,
                    )
                )
    assert {r["id"] for r in retirement} == {"dram1342177280-zero-F0", "dram1342177280-zero-F1"}
    observed, base = OUT / "runs/restart-F1", OUT / "validation/restart-F1-base-runtime"
    trace_hashes = {}
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        a, b = (observed / name).read_bytes(), (base / name).read_bytes()
        if name.endswith(".gz"):
            a, b = gzip.decompress(a), gzip.decompress(b)
        assert a == b
        trace_hashes[name] = hashlib.sha256(a).hexdigest()
    # Preserve and independently verify the prior 32-run null comparison.
    prior = HERE.parent / "capacity-slack-ablation-v1"
    prior_plan = read(prior / "PLAN.json")
    assert len(prior_plan["jobs"]) == 32
    prior_audit = read(prior / "INDEPENDENT_VARIANT_AUDIT.json")
    for identity, digest in prior_audit["summary_sha256"].items():
        assert sha(prior / "runs" / identity / "summary.json") == digest
    null_pairs = []
    for budget in (2, 4, 8, 256):
        for fault in (0, 1):
            a = read(prior / "runs" / f"dram-{budget}GiB-aegiskv-F{fault}" / "summary.json")
            b = read(
                prior / "runs" / f"dram-{budget}GiB-aegiskv_no_slack-F{fault}" / "summary.json"
            )
            assert a["workflows"] == b["workflows"]
            null_pairs.append(
                dict(
                    budget_GiB=budget,
                    fault=fault,
                    workflows=len(a["workflows"]),
                    exact_equality=True,
                )
            )
    report = dict(
        status="PASS_WITH_DOCUMENTATION_LIMITS",
        simulations_executed=0,
        source_files_verified=len(manifest["source_sha256"]),
        experimental_runs=10,
        paired_conditions=5,
        independent_workflow_instances=1,
        observer_validation_executions=1,
        source_and_artifact_binding_verified=True,
        config_differences_only=["slack_mode", "dram_bytes_per_host"],
        offline_scores_all_five_fault_entries_equal=True,
        copied_frame_unmodified=True,
        capacity_arithmetic=capacity,
        chronology=dict(
            seal_mtime_utc=datetime.fromtimestamp(seal_time / 1e9, UTC).isoformat(),
            first_run_config_mtime_utc=datetime.fromtimestamp(
                first_config_time / 1e9, UTC
            ).isoformat(),
            seal_precedes_first_run_seconds=(first_config_time - seal_time) / 1e9,
            evidence=(
                "Frozen prepare/run control flow and local filesystem timestamps; "
                "not externally attested or proof that no unrecorded exploratory run existed."
            ),
        ),
        observation_transparency=dict(
            scope="one Restart F1 validation plus static observer purity review",
            equal_decompressed_sha256=trace_hashes,
            restart_control_flow_records=len(lines(base / "flows.jsonl.gz")),
            journals_expected_to_differ=True,
        ),
        pairs=pairs,
        retirement=retirement,
        dram_resources=resources,
        prior_null_comparisons=null_pairs,
        documentation_findings=[
            dict(
                priority="P2",
                file="MANIFEST.json",
                field="timing",
                actual=manifest["timing"],
                correction=(
                    "GridDurationProfile pinned AIC HYBRID shape grid plus shared weighted "
                    "max-min byte flows; frozen manifest text is stale. Preserve sealed file "
                    "and add TIMING_METADATA_ERRATUM.json as an explanatory annotation."
                ),
            )
        ],
        limits=[
            "Constructed post-hoc manual-prior mechanism example; "
            "does not replace prior 32-run null.",
            "One fixed workflow/fault and dependent conditions, "
            "no population CI or predictor accuracy claim.",
            "FCFS batch-1 model, HBM replicas disabled, no DMA compute slowdown, "
            "not measured hardware overhead.",
            "Output checks validate recorded token replay/counts, "
            "not newly generated semantic answers.",
            "Observer empirical transparency is verified for Restart F1, "
            "not five independent matched observer/base pairs. Restart flow traces are empty; "
            "their equality is not a nonempty checkpoint/DMA trace validation.",
        ],
        artifact_sha256={
            n: sha(OUT / n)
            for n in (
                "PLAN.json",
                "PROTOCOL.md",
                "MANIFEST.json",
                "SEAL.json",
                "OBSERVATION_TRANSPARENCY.json",
            )
        },
        summary_sha256=hashes,
        prior_null_audit_sha256=sha(prior / "INDEPENDENT_VARIANT_AUDIT.json"),
        audit_script_sha256=sha(Path(__file__)),
    )
    (HERE / "POSTHOC_SLACK_INDEPENDENT_REVIEW.json").write_bytes(encoded(report))
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "experimental_runs",
                    "paired_conditions",
                    "source_files_verified",
                    "offline_scores_all_five_fault_entries_equal",
                    "simulations_executed",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
