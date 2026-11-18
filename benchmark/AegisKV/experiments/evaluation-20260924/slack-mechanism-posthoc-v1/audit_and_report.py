"""Independent standard-library audit of the frozen post-hoc diagnostic."""

import csv
import gzip
import hashlib
import json
from itertools import pairwise
from pathlib import Path

OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def lines(path):
    return [json.loads(line) for line in gzip.decompress(path.read_bytes()).decode().splitlines()]


def dump(path, value):
    path.write_bytes(canonical(value))


def csv_write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row))
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    plan, manifest = read(OUT / "PLAN.json"), read(OUT / "MANIFEST.json")
    for name, expected in read(OUT / "SEAL.json").items():
        assert sha(OUT / name) == expected
    for name, expected in manifest["source_sha256"].items():
        assert sha(OUT / "source_snapshot" / name) == expected
    assert sha(OUT / plan["profile"]) == plan["profile_sha256"]
    payload = gzip.decompress((OUT / plan["workload"]).read_bytes())
    assert hashlib.sha256(payload).hexdigest() == plan["workload_sha256"]
    workload = json.loads(payload)
    assert [
        (a["name"], len(a["calls"][0]["prompt"]), len(a["calls"][0]["output"]), a["prior_ns"])
        for a in workload
    ] == [
        ("root", 512, 16, 5 * 10**9),
        ("a_critical", 1024, 8192, 120 * 10**9),
        ("b_expensive", 8192, 2048, 40 * 10**9),
        ("join", 512, 16, 5 * 10**9),
    ]
    assert all(
        len(a["calls"]) == 1
        and a["calls"][0]["output_limit_tokens"] == 16384
        and len(a["calls"][0]["prompt"]) + 16384 <= 40960
        for a in workload
    )
    results, frames, hashes, resources, endpoint_rows = {}, {}, {}, [], []
    for job in plan["jobs"]:
        path = OUT / "runs" / job["id"]
        complete, result, config = (
            read(path / "COMPLETE.json"),
            read(path / "summary.json"),
            read(path / "config.json"),
        )
        assert complete["job_sha256"] == hashlib.sha256(canonical(job)).hexdigest()
        assert complete["plan_sha256"] == sha(OUT / "PLAN.json") and complete[
            "manifest_sha256"
        ] == sha(OUT / "MANIFEST.json")
        assert complete["workload_sha256"] == result["workload_sha256"] == plan["workload_sha256"]
        assert complete["profile_sha256"] == plan["profile_sha256"]
        for name, expected in complete["artifacts_sha256"].items():
            assert sha(path / name) == expected
        assert config == job["config"] and read(path / "failure.json") == job["failure"]
        assert result["config_sha256"] == sha(path / "config.json")
        assert result["policy"] == job["policy"] and result["predictor"] == "prior_predictor"
        assert (
            result["complete"]
            and result["output_tokens_exact"]
            and result["terminal_allocations_zero"]
            and not result["oracle_reservation_count"]
        )
        assert config["hbm_cap_bytes"] == config["initial_quota_bytes"] == 0
        assert (
            result["metrics"].get("hot_bytes", 0) == result["metrics"]["replica_hbm_byte_ns"] == 0
        )
        observations = lines(path / "state-transitions.jsonl.gz")
        integrals = sum(
            sum(
                config["dram_bytes_per_host"] - ledger["FREE"]
                for ledger in a["dram_accounts"].values()
            )
            * (b["time_ns"] - a["time_ns"])
            for a, b in pairwise(observations)
        )
        assert integrals == result["metrics"]["replica_dram_byte_ns"]
        for frame in observations:
            for ledger in frame["dram_accounts"].values():
                assert (
                    min(ledger.values()) >= 0
                    and sum(ledger.values()) == config["dram_bytes_per_host"]
                )
        for host in (0, 1):
            maximum = max(
                config["dram_bytes_per_host"] - f["dram_accounts"][f"dram:{host}"]["FREE"]
                for f in observations
            )
            assert maximum == result["peak_bytes"][f"dram:{host}"]
        hashes[job["id"]] = sha(path / "summary.json")
        results[job["id"]], frames[job["id"]] = result, observations
        resources.append(
            dict(
                id=job["id"],
                budget_GiB=job["budget_bytes"] / 2**30,
                variant=job["variant"],
                fault=job["failure"] is not None,
                wct_s=result["workflows"]["wf0"]["wct_ns"] / 1e9,
                completed_checkpoint_bytes=result["metrics"].get("checkpoint_bytes", 0),
                completed_hot_bytes=result["metrics"].get("hot_bytes", 0),
                canceled_transferred_bytes=result["metrics"].get(
                    "canceled_copy_transferred_bytes", 0
                ),
                replica_dram_byte_ns=integrals,
                replica_dram_GiB_s=integrals / 2**30 / 1e9,
                max_single_host_dram_bytes=max(
                    result["peak_bytes"]["dram:0"], result["peak_bytes"]["dram:1"]
                ),
                aggregate_peak_dram_bytes=result["peak_bytes"]["replica_dram"],
            )
        )
        if job["failure"]:
            state = read(path / "fault-state.json")
            before, scores = state["frame"], state["offline_scores"]
            assert before["time_ns"] == result["failure"]["time_ns"] and not before["fault_fired"]
            critical, expensive = (
                before["states"]["wf0/a_critical"],
                before["states"]["wf0/b_expensive"],
            )
            assert (
                critical["worker"],
                expensive["worker"],
                critical["peer"],
                expensive["peer"],
            ) == (0, 1, 2, 2)
            assert (critical["computed"], expensive["computed"]) == (1536, 8608)
            assert (
                result["failure"]["workers"] == [0] and result["failure"]["logical_tokens"] == 1536
            )
            assert [r["agent"] for r in result["recoveries"]] == ["wf0/a_critical"]
            assert not scores["fallback_workflows"]
            # At this snapshot the unfinished graph is two sibling branches + join.
            # Same submission time and fixed 120/40 second estimates imply 80 s Slack.
            tracker = before["tracker"]
            assert (
                tracker["wf0/a_critical"]["submitted_ns"]
                == tracker["wf0/b_expensive"]["submitted_ns"]
            )
            assert (
                tracker["wf0/a_critical"]["remaining_ns"]
                - tracker["wf0/b_expensive"]["remaining_ns"]
                == 80 * 10**9
            )
            assert scores["agents"]["wf0/a_critical"]["guarded_dag_slack_ns"] == 0
            assert scores["agents"]["wf0/b_expensive"]["guarded_dag_slack_ns"] == 80 * 10**9
            for key, value in scores["agents"].items():
                q = before["states"][key]["computed"] // 256 * 256
                cp_bytes = (
                    q * config["layers"] * config["kv_bytes_per_token_per_layer_rank"]
                    + ((q + 63) // 64) * config["layers"] * 24
                )
                assert value["computed_checkpoint_candidate_bytes"] == cp_bytes
                expected_slack = (
                    value["guarded_dag_slack_ns"] if config["slack_mode"] == "dag" else 0
                )
                assert value["effective_slack_ns"] == expected_slack
                assert value["exposure_ns"] == max(
                    0, value["full_reconstruction_ns"] - expected_slack
                )
            recovery = result["recoveries"][0]
            assert recovery["retry_worker"] == 2 and recovery["queue_ns"] == 0
            assert recovery["latency_ns"] == sum(
                recovery[k] for k in ("detection_ns", "queue_ns", "service_ns")
            )
            calls = {r["agent"]: r for r in result["requests"]}
            assert calls["wf0/a_critical"]["finish_ns"] > calls["wf0/b_expensive"]["finish_ns"]
            assert calls["wf0/join"]["submit_ns"] == calls["wf0/a_critical"]["finish_ns"]
            endpoint_rows.append(
                dict(
                    id=job["id"],
                    budget_GiB=job["budget_bytes"] / 2**30,
                    variant=job["variant"],
                    fault_time_s=before["time_ns"] / 1e9,
                    critical_guarded_slack_s=0,
                    expensive_guarded_slack_s=80,
                    critical_exposure_ms=scores["agents"]["wf0/a_critical"]["exposure_ns"] / 1e6,
                    expensive_exposure_ms=scores["agents"]["wf0/b_expensive"]["exposure_ns"] / 1e6,
                    critical_checkpoint_tokens=recovery["checkpoint_tokens"],
                    detection_ms=recovery["detection_ns"] / 1e6,
                    retry_queue_ms=recovery["queue_ns"] / 1e6,
                    service_ms=recovery["service_ns"] / 1e6,
                    f1_wct_s=result["workflows"]["wf0"]["wct_ns"] / 1e9,
                    f0_wct_s=results[job["f0_id"]]["workflows"]["wf0"]["wct_ns"] / 1e9,
                    delta_wct_ms=(
                        result["workflows"]["wf0"]["wct_ns"]
                        - results[job["f0_id"]]["workflows"]["wf0"]["wct_ns"]
                    )
                    / 1e6,
                )
            )
    assert len(results) == 10 and len(endpoint_rows) == 5
    assert len({row["fault_time_s"] for row in endpoint_rows}) == 1
    assert len({row["wct_s"] for row in resources if not row["fault"]}) == 1
    retirement = []
    fault_wall_ns = results["restart-F1"]["failure"]["time_ns"]
    for identity, observations in frames.items():
        for before, after in pairwise(observations):
            if after["fault_fired"] or after["time_ns"] > fault_wall_ns:
                break
            if (
                before["states"]["wf0/a_critical"]["checkpoint_identity"] is not None
                and after["states"]["wf0/a_critical"]["checkpoint_identity"] is None
            ):
                retirement.append(
                    dict(id=identity, time_ns=after["time_ns"], before=before, after=after)
                )
    assert {r["id"] for r in retirement} == {"dram1342177280-zero-F0", "dram1342177280-zero-F1"}
    validation = read(OUT / "OBSERVATION_TRANSPARENCY.json")
    base = OUT / "validation/restart-F1-base-runtime"
    observed = OUT / "runs/restart-F1"
    assert (base / "summary.json").read_bytes() == (observed / "summary.json").read_bytes()
    assert (
        sha(base / "summary.json")
        == validation["base_summary_sha256"]
        == validation["observed_summary_sha256"]
    )
    for name in ("events.jsonl.gz", "flows.jsonl.gz"):
        assert gzip.decompress((base / name).read_bytes()) == gzip.decompress(
            (observed / name).read_bytes()
        )
    assert not gzip.decompress((base / "flows.jsonl.gz").read_bytes())
    nonempty = read(OUT / "NONEMPTY_OBSERVATION_TRANSPARENCY.json")
    second_base = OUT / "validation/tight-dag-F1-base-runtime"
    second_observed = OUT / "runs/dram1342177280-dag-F1"
    assert (second_base / "summary.json").read_bytes() == (
        second_observed / "summary.json"
    ).read_bytes()
    assert (
        sha(second_base / "summary.json")
        == nonempty["base_summary_sha256"]
        == nonempty["observed_summary_sha256"]
    )
    for name in ("events.jsonl.gz", "flows.jsonl.gz"):
        payload = gzip.decompress((second_base / name).read_bytes())
        assert payload and payload == gzip.decompress((second_observed / name).read_bytes())
        assert (
            hashlib.sha256(payload).hexdigest() == nonempty["traces"][name]["decompressed_sha256"]
        )
    csv_write(OUT / "endpoint-results.csv", endpoint_rows)
    csv_write(OUT / "resource-results.csv", resources)
    dump(OUT / "RETIREMENT_WITNESS.json", retirement)
    dump(
        OUT / "INDEPENDENT_AUDIT.json",
        dict(
            passed=True,
            experiment_runs=10,
            validation_runs=2,
            paired_workflows=5,
            all_sources_inputs_jobs_and_artifacts_bound=True,
            observed_dram_byte_time_and_peak_exact_for_all_10=True,
            capacity_metadata_verified=True,
            same_fault_wall_identity_worker_and_no_covictims=True,
            critical_branch_gates_join_all_F1=True,
            observer_base_summary_and_events_flows_identical=True,
            summary_sha256=hashes,
            source_sha256={
                n: sha(OUT / n)
                for n in (
                    "PLAN.json",
                    "PROTOCOL.md",
                    "MANIFEST.json",
                    "SEAL.json",
                    "OBSERVATION_TRANSPARENCY.json",
                    "NONEMPTY_OBSERVATION_TRANSPARENCY.json",
                    "VALIDATION_EXTENSION.md",
                )
            },
            audit_script_sha256=sha(Path(__file__)),
            outputs_sha256={
                n: sha(OUT / n)
                for n in ("endpoint-results.csv", "resource-results.csv", "RETIREMENT_WITNESS.json")
            },
        ),
    )
    table = [
        "| DRAM budget | Variant | CP at fault | F0 WCT (s) | F1 WCT (s) | Paired delta (ms) |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for r in endpoint_rows:
        table.append(
            f"| {r['budget_GiB']:g} GiB | {r['variant']} | {r['critical_checkpoint_tokens']} | {r['f0_wct_s']:.9f} | {r['f1_wct_s']:.9f} | {r['delta_wct_ms']:.6f} |"
        )
    (OUT / "RESULTS.md").write_text(
        "# Post-hoc constructed Slack mechanism diagnostic\n\nAll ten frozen experimental runs and five F1/F0 workflow pairs completed. Two extra uninstrumented executions validate observation transparency and are excluded from the experimental sample count. The independent audit verifies frozen sources/inputs, whole-result bindings, capacity, and all ten DRAM byte-time integrals and per-host peaks from observer ledgers. Restart F1 has byte-identical summaries/events but empty flow logs. The additional tight-DAG-DRAM F1 control has byte-identical summaries, 1,387 event records and 158 nonempty flow records (61,240 decompressed bytes). These two controls establish equality for their fixed inputs, not all possible workloads; neither observed formal run was replaced or repeated.\n\n"
        + "\n".join(table)
        + "\n\nAt 1.25 GiB, DAG Slack retains the critical branch's 1,280-token checkpoint; zero Slack retains the expensive branch's 8,448-token checkpoint and loses critical protection. The workflow penalty differs by **110.748459 ms**. At 4 GiB both modes protect critical and have the same penalty; Restart matches tight zero Slack. All healthy WCTs are 99.155361841 s. These are one fixed constructed instance, not a confidence interval or production workload estimate.\n\nThe exact failure boundary matches across all five failed conditions: 6.255890594 s, critical invocation 0, logical token 1,536, worker 0, and no collateral victim. Both branches started at 0.226705019 s on workers 0/1 and use worker 2 (host 1) as their peer. Their computed frontiers are 1,536/8,608. Raw guarded Slack is 0/80 s; modeled reconstruction costs are 133.793720/851.408365 ms. DAG exposure therefore excludes the expensive noncritical branch, whereas zero Slack orders it before critical.\n\nThis is an observed retirement, not merely failure to admit. In tight zero Slack at 1.028336003 s, critical's existing CP1024 is removed when expensive reaches 8,192 computed tokens. Expensive's CP7936 plus pending append consumes 1,208,177,280 B; retaining critical's 151,008,768 B too would exceed the 1,342,177,280 B host budget. RETIREMENT_WITNESS.json preserves both sides of this transition. At the fault, expensive's complete CP8448 occupies 1,245,822,336 B and leaves 96,354,944 B, insufficient for critical's committed CP1280 (188,760,960 B). The DAG variant instead holds that critical checkpoint on the same peer.\n\nBoth variants retry critical on worker 2 with exactly zero recorded retry queue; detection is 1 ms. Admitted recovery service is 34.703782 ms with CP1280 versus 145.452241 ms without a checkpoint. Critical remains the join's gating parent, and the join's invocation latency is unchanged. Thus the matched WCT difference has a recorded protection/recovery/dependency chain, without inferring an ordinary request queue from latency.\n\nresource-results.csv retains all ten checkpoint/cancellation bytes, modeled DRAM byte-time and peaks. The initial 1.125 GiB proposal was corrected before any simulation because the pinned model has 36 layers and metadata pushes even CP8192 over that budget; the pre-execution protocol records the correction. No outcome-based tuning or rerun occurred.\n\nThis diagnostic was designed after the 32-run capacity/zero-Slack study produced equal WCTs. It establishes a constructed mechanism operating region with manual role priors, HBM disabled, fixed logical token 1,536 (not the primary 80% rule), and zero modeled DMA interference. It neither supersedes that null result nor validates natural Agent workloads, semantic prediction accuracy, general effect size, or physical hardware overhead.\n"
    )
    print("independently audited 10 experiment runs + 2 transparency validations")


if __name__ == "__main__":
    main()
