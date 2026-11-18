"""Audit frozen profile campaigns and publish descriptive, paired simulation data.

Run with --campaign PATH. PASS requires every planned run and every strict
identity/evidence gate. Older schemas and unfinished campaigns remain PARTIAL;
actual contradictions are FAIL. Summary-only runs are never described as
independently audited flow or ledger replays.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from math import ceil, isfinite
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[5]


class AuditViolation(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise AuditViolation(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def object_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def jsonlines(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def quantile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values):
    values = [v for v in values if v is not None]
    if not values:
        return dict(n=0)
    return dict(
        n=len(values),
        mean=mean(values),
        p50=quantile(values, 0.5),
        p95=quantile(values, 0.95),
        p99=quantile(values, 0.99),
        min=min(values),
        max=max(values),
    )


def write_json(path, value):
    Path(path).write_bytes(encoded(value))


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resource_capacity(resource, config):
    if resource == "fabric" or resource.startswith("nic:"):
        return config["network_bytes_per_second"]
    for prefix, key in (
        ("dram-bw:", "dram_bytes_per_second"),
        ("h2d:", "h2d_bytes_per_second"),
        ("d2h:", "d2h_bytes_per_second"),
    ):
        if resource.startswith(prefix):
            return config[key]
    raise AuditViolation(f"unrecognized flow resource: {resource}")


def audit_flows(path, config, metrics):
    changes = defaultdict(lambda: defaultdict(float))
    physical_bytes = 0.0
    count = 0
    for row in jsonlines(path):
        start, end = row["start_ns"], row["end_ns"]
        check(end >= start, "negative flow interval")
        transferred, rate = row["transferred_bytes"], row["allocated_rate_bytes_per_second"]
        check(isfinite(transferred) and transferred >= 0, "invalid flow transferred bytes")
        check(isfinite(rate) and rate >= 0, "invalid flow rate")
        resources = row["path_resource_ids"]
        check(resources and len(set(resources)) == len(resources), "invalid flow resource path")
        remaining_start, remaining_end = (
            row["remaining_bytes_at_start"],
            row["remaining_bytes_at_end"],
        )
        check(
            0 <= remaining_end <= remaining_start <= row["payload_bytes"],
            "flow remaining bytes outside payload bounds",
        )
        tolerance = max(1e-5, row["payload_bytes"] * 1e-12)
        check(
            abs(remaining_start - remaining_end - transferred) <= tolerance,
            "flow interval remaining/transfer bytes do not reconcile",
        )
        service = rate * (end - start) / 1e9
        check(
            abs(transferred - min(service, remaining_start)) <= tolerance
            and service - transferred <= rate / 1e9 + tolerance,
            "flow interval service differs from its allocated rate",
        )
        physical_bytes += transferred
        count += 1
        for resource in resources:
            changes[resource][start] += rate
            changes[resource][end] -= rate
    accounted = sum(metrics.get(f"{kind}_bytes", 0) for kind in ("checkpoint", "hot", "restore"))
    accounted += metrics.get("canceled_copy_transferred_bytes", 0)
    residual = physical_bytes - accounted
    check(abs(residual) < 1, f"physical transfer bytes do not reconcile: {residual}")
    utilization = {}
    for resource, timeline in changes.items():
        rate = peak = 0.0
        cap = resource_capacity(resource, config)
        for _, delta in sorted(timeline.items()):
            rate += delta
            check(-cap * 1e-7 <= rate <= cap * (1 + 1e-7), f"flow capacity exceeded: {resource}")
            peak = max(peak, rate / cap)
        check(abs(rate) <= cap * 1e-7, f"flow rate did not drain: {resource}")
        utilization[resource] = peak
    return dict(
        independent_flow_audit=True,
        interval_count=count,
        transfer_byte_residual=residual,
        per_resource_peak_utilization=utilization,
    )


def workload_metadata(path, expected):
    check(sha(path) == expected["sha256"], "compressed workload hash mismatch")
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    check(
        hashlib.sha256(payload).hexdigest() == expected["content_sha256"],
        "workload content hash mismatch",
    )
    agents = json.loads(payload)
    requests, releases, legacy = {}, {}, 0
    for agent in agents:
        workflow = agent["workflow"]
        releases[workflow] = min(releases.get(workflow, agent["release_ns"]), agent["release_ns"])
        for index, invocation in enumerate(agent["calls"]):
            key = agent["workflow"] + "/" + agent["name"], index
            check(key not in requests, "duplicate workload invocation identity")
            output = len(invocation["output"])
            limit = invocation.get("output_limit_tokens")
            legacy += limit is None
            check(limit is None or (type(limit) is int and limit >= output), "invalid output limit")
            requests[key] = dict(
                output=output,
                prompt=len(invocation["prompt"]),
                total=len(invocation["prompt"]) + output,
                model=invocation["model"],
                layout=invocation["layout"],
            )
    check(len(releases) == expected["workflows"], "workload workflow count mismatch")
    check(len(agents) == expected["agents"], "workload Agent count mismatch")
    return dict(
        requests=requests,
        releases=releases,
        legacy_reservations=legacy,
        expected_output=sum(r["output"] for r in requests.values()),
    )


def audit_events(path, detailed, config, summary):
    previous = -1
    commits, updates, quotas = [], [], []
    for event in jsonlines(path):
        check(event["time_ns"] >= previous, "events are not time ordered")
        previous = event["time_ns"]
        if event["kind"] in {"checkpoint_commit", "topk_update"}:
            key = event["time_ns"], event["agent"], event["frontier"]
            (commits if event["kind"] == "checkpoint_commit" else updates).append(key)
        elif event["kind"] == "quota":
            quotas.append(event)
        elif event["kind"] == "policy_sample":
            gain = max(
                0,
                max(0, event["dram_recovery_estimate_ns"] - event["slack_ns"])
                - max(0, event["hbm_recovery_estimate_ns"] - event["slack_ns"]),
            )
            check(event["hbm_gain_ns"] == gain, "recorded HBM gain differs from equation")
    if detailed:
        check(updates == commits, "Top-K updates do not coincide with checkpoint commits")
    check(
        summary["metrics"].get("topk_layer_reranks", 0) == len(commits) * config["depth"],
        "checkpoint-only first-L re-ranking count mismatch",
    )
    return dict(
        quota_logged_rank_increase_events=sum(q["after"] > q["before"] for q in quotas),
        quota_logged_rank_decrease_events=sum(q["after"] < q["before"] for q in quotas),
        quota_logged_pressure_events=sum(bool(q["pressure"]) for q in quotas),
        quota_logged_max_bytes=max([config["initial_quota_bytes"]] + [q["after"] for q in quotas]),
        checkpoint_logged_commits=len(commits),
    )


def audit_run(base, job, workload, metadata, profiles, priors_sha, strict):
    folder = base / "runs" / job["id"]
    result = read(folder / "summary.json")
    config, failure = read(folder / "config.json"), read(folder / "failure.json")
    marker = read(folder / "COMPLETE.json")
    profile_sha = profiles[f"profiles/{job['model']}.json"]
    check(config == job["config"], "run config differs from PLAN")
    check(failure == job["failure"], "run failure differs from PLAN")
    check(
        marker.get("id") == job["id"] and marker.get("complete") is True,
        "completion marker identity/status mismatch",
    )
    check(marker["summary_sha256"] == sha(folder / "summary.json"), "summary hash mismatch")
    missing = []
    if strict:
        for name, value in dict(
            job_sha256=object_sha(job),
            priors_sha256=priors_sha,
            profile_sha256=profile_sha,
            workload_sha256=workload["sha256"],
        ).items():
            check(marker.get(name) == value, f"completion marker {name} mismatch")
    else:
        missing.append("legacy completion marker lacks complete plan/priors/profile binding")
    for name in ("complete", "terminal_allocations_zero", "output_tokens_exact"):
        check(result.get(name) is True, f"runtime acceptance failed: {name}")
    check(result["policy"] == job["policy"], "summary policy mismatch")
    check(
        result.get("duration_profile") == "GridDurationProfile",
        "profile campaign did not execute its grid duration provider",
    )
    check(result["config_sha256"] == sha(folder / "config.json"), "summary config hash mismatch")
    check(result["workload_sha256"] == workload["content_sha256"], "summary workload mismatch")
    check(result["metrics"].get("invariant_checks", 0) > 0, "no in-run invariant checks recorded")
    if strict:
        check(metadata["legacy_reservations"] == 0, "workload contains oracle output reservations")
        check(
            result.get("oracle_reservation_count") == 0,
            "runtime reports oracle/missing reservation count",
        )
    elif metadata["legacy_reservations"]:
        missing.append(f"legacy oracle output reservations: {metadata['legacy_reservations']}")
    expected_requests = metadata["requests"]
    got = {}
    for request in result["requests"]:
        key = request["agent"], request["invocation"]
        check(key not in got, "duplicate completed invocation")
        check(key in expected_requests, "unexpected completed invocation")
        check(
            request["output_tokens"] == expected_requests[key]["output"],
            "per-invocation output mismatch",
        )
        check(
            request["finish_ns"] - request["submit_ns"] == request["latency_ns"],
            "request duration mismatch",
        )
        got[key] = request
    check(got.keys() == expected_requests.keys(), "not every frozen invocation completed")
    check(
        result["metrics"]["emitted_tokens"] == metadata["expected_output"],
        "total emitted tokens mismatch",
    )
    check(
        result["workflows"].keys() == metadata["releases"].keys(), "workflow identity set mismatch"
    )
    for workflow, values in result["workflows"].items():
        check(values["start_ns"] == metadata["releases"][workflow], "workflow release changed")
        expected_end = max(
            r["finish_ns"] for (agent, _), r in got.items() if agent.split("/", 1)[0] == workflow
        )
        check(
            values["finish_ns"] == expected_end, "workflow finish disagrees with completed requests"
        )
        check(values["wct_ns"] == expected_end - values["start_ns"], "workflow duration mismatch")
    for worker, _ in enumerate(config["hosts"]):
        for rank in range(config["tp"]):
            name = f"hbm:{worker}:{rank}"
            check(name in result["peak_bytes"], f"missing per-rank peak: {name}")
            check(
                0 <= result["peak_bytes"][name] <= config["hbm_bytes_per_rank"],
                f"HBM occupancy exceeds cap: {name}",
            )
    for host in set(config["hosts"]):
        check(
            0 <= result["peak_bytes"][f"dram:{host}"] <= config["dram_bytes_per_host"],
            "host DRAM occupancy exceeds cap",
        )
    z = config["checkpoint_tokens"]
    check(z % config["block_tokens"] == 0, "checkpoint/physical-block alignment differs")
    if failure:
        actual = result["failure"]
        failed_workers = actual["workers"]
        check(
            bool(failed_workers)
            and len(set(failed_workers)) == len(failed_workers)
            and all(0 <= w < len(config["hosts"]) for w in failed_workers),
            "invalid failed-worker identity set",
        )
        if failure["scope"] == "worker":
            check(len(failed_workers) == 1, "worker failure removed multiple workers")
        else:
            host = config["hosts"][failed_workers[0]]
            check(
                set(failed_workers) == {w for w, h in enumerate(config["hosts"]) if h == host},
                "host failure did not remove exactly that host's workers",
            )
        target = expected_requests[failure["agent"], failure["invocation"]]
        check(
            actual["agent"] == failure["agent"] and actual["invocation"] == failure["invocation"],
            "fault target identity changed",
        )
        check(actual["total_tokens"] == target["total"], "fault total-token denominator changed")
        check(
            actual["logical_tokens"] == ceil(target["total"] * failure["progress"]),
            "fault logical-token point differs from plan",
        )
        check(
            any(
                r["agent"] == failure["agent"] and r["invocation"] == failure["invocation"]
                for r in result["recoveries"]
            ),
            "primary fault target has no recovery",
        )
    else:
        check(
            result["failure"] is None and not result["recoveries"], "F0 contains failure/recovery"
        )
    for recovery in result["recoveries"]:
        check(
            (recovery["agent"], recovery["invocation"]) in expected_requests,
            "recovery refers to an unknown invocation",
        )
        check(recovery["checkpoint_tokens"] % z == 0, "published checkpoint is not Z-aligned")
        check(
            recovery["durable_tokens"] - recovery["checkpoint_tokens"]
            == recovery["rebuild_tokens"],
            "rebuild token decomposition mismatch",
        )
        check(
            recovery["latency_ns"]
            == recovery["detection_ns"] + recovery["queue_ns"] + recovery["service_ns"],
            "recovery latency decomposition mismatch",
        )
        check(
            recovery["first_new_token_ns"] - recovery["failure_ns"] == recovery["latency_ns"],
            "recovery endpoint mismatch",
        )
        check(
            recovery["source_worker"] in result["failure"]["workers"],
            "recovery source did not fail",
        )
        check(
            recovery["retry_worker"] not in result["failure"]["workers"],
            "retry targeted a failed worker",
        )
        check(
            recovery["tail_exceeds_checkpoint_z"]
            == bool(recovery["checkpoint_tokens"] and recovery["rebuild_tokens"] > z),
            "copy-lag flag mismatch",
        )
    detailed = result.get("detailed_event_and_flow_logs_retained", False)
    check(detailed == job["detailed_logs"], "detailed log flag differs from plan")
    event_metrics = audit_events(folder / "events.jsonl.gz", detailed, config, result)
    flows = (
        audit_flows(folder / "flows.jsonl.gz", config, result["metrics"])
        if detailed
        else dict(
            independent_flow_audit=False,
            evidence="in-run invariants and summary counters only; raw intervals were not retained",
        )
    )
    return result, dict(
        id=job["id"],
        verified=True,
        missing_evidence=missing,
        occupancy_evidence=(
            "exported per-rank/host peaks checked; terminal conservation is an in-run assertion"
        ),
        flow_audit=flows,
        event_metrics=event_metrics,
    )


def compact_ids(values):
    return json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))


def run_metrics(job, result, event_metrics, accepted):
    wcts = [w["wct_ns"] / 1e9 for w in result["workflows"].values()]
    stats = distribution(wcts)
    fault = result["failure"]
    target = fault["agent"].split("/", 1)[0] if fault else None
    recoveries = result["recoveries"]
    workers = fault["workers"] if fault else []
    victims = {(r["agent"], r["invocation"]) for r in recoveries}
    primary = (fault["agent"], fault["invocation"]) if fault else None
    row = dict(
        run_id=job["id"],
        dataset=job.get("dataset", ""),
        model=job["model"],
        case=job["case"],
        workload=job["workload"],
        policy=job["policy"],
        fault=bool(fault),
        fault_index=job["fault_index"],
        f0_id=job["f0_id"],
        run_integrity_verified=accepted,
        workflow_count=len(wcts),
        wct_mean_s=stats["mean"],
        wct_p50_s=stats["p50"],
        wct_p95_s=stats["p95"],
        wct_p99_s=stats["p99"],
        fault_workflow=target or "",
        fault_agent=fault["agent"] if fault else "",
        fault_invocation=fault["invocation"] if fault else None,
        fault_logical_tokens=fault["logical_tokens"] if fault else None,
        failed_workers=compact_ids(workers),
        failed_hosts=compact_ids({job["config"]["hosts"][w] for w in workers}),
        victim_invocations=compact_ids([f"{agent}#{call}" for agent, call in victims]),
        co_victim_invocations=compact_ids(
            [f"{agent}#{call}" for agent, call in victims if (agent, call) != primary]
        ),
        fault_workflow_wct_s=result["workflows"][target]["wct_ns"] / 1e9 if target else None,
        collateral_workflows=sum(w != target for w in result["workflows"]) if target else None,
        collateral_mean_wct_s=mean(
            [v["wct_ns"] / 1e9 for w, v in result["workflows"].items() if w != target]
        )
        if target and len(wcts) > 1
        else None,
        recovery_count=len(recoveries),
        oracle_reservation_count=result.get("oracle_reservation_count"),
        detailed_logs_retained=result.get("detailed_event_and_flow_logs_retained", False),
    )
    for name in ("latency_ns", "detection_ns", "queue_ns", "service_ns"):
        dist = distribution([r[name] / 1e9 for r in recoveries])
        for metric in ("mean", "p95", "max"):
            row[f"recovery_{name.removesuffix('_ns')}_{metric}_s"] = dist.get(metric)
    for name in ("rebuild_tokens", "checkpoint_tokens", "hbm_blocks"):
        row[f"recovery_{name}_mean"] = mean([r[name] for r in recoveries]) if recoveries else None
    row["recovery_tail_exceeds_z_count"] = sum(
        r.get("tail_exceeds_checkpoint_z", False) for r in recoveries
    )
    for key, value in result["metrics"].items():
        row[f"metric_{key}"] = value
    for kind in ("checkpoint", "hot", "restore"):
        row[f"traffic_{kind}_bytes"] = result["metrics"].get(f"{kind}_bytes", 0)
    row["traffic_canceled_transferred_bytes"] = result["metrics"].get(
        "canceled_copy_transferred_bytes", 0
    )
    row["traffic_total_transferred_bytes"] = (
        sum(row[f"traffic_{kind}_bytes"] for kind in ("checkpoint", "hot", "restore"))
        + row["traffic_canceled_transferred_bytes"]
    )
    for kind in ("primary_hbm", "replica_hbm", "replica_dram"):
        row[f"{kind}_peak_bytes"] = result["peak_bytes"].get(kind, 0)
    for key, value in result["peak_bytes"].items():
        row[f"peak_bytes_{key}"] = value
    row.update(event_metrics)
    return row


def add_pairs(jobs, summaries, metrics, errors, missing):
    paired, controls = [], []
    indexed = {r["run_id"]: r for r in metrics}
    for job in jobs:
        if not job["failure"] or job["id"] not in summaries:
            continue
        if job["f0_id"] not in summaries:
            missing.append(f"F0 absent for completed F1: {job['id']}")
            continue
        f1, f0 = summaries[job["id"]], summaries[job["f0_id"]]
        matched = all(f0[k] == f1[k] for k in ("config_sha256", "workload_sha256", "policy"))
        matched &= f0["workflows"].keys() == f1["workflows"].keys()
        controls.append(dict(run_id=job["id"], f0_id=job["f0_id"], matched=matched))
        if not matched:
            errors.append(
                dict(scope=job["id"], message="F0/F1 config, policy, workload or workflow mismatch")
            )
            continue
        target = f1["failure"]["agent"].split("/", 1)[0]
        victim_workflows = {r["agent"].split("/", 1)[0] for r in f1["recoveries"]}
        delta, other = [], []
        for workflow in f0["workflows"]:
            normal = f0["workflows"][workflow]["wct_ns"] / 1e9
            failed = f1["workflows"][workflow]["wct_ns"] / 1e9
            difference = failed - normal
            delta.append(difference)
            if workflow != target:
                other.append(difference)
            paired.append(
                dict(
                    run_id=job["id"],
                    f0_id=job["f0_id"],
                    model=job["model"],
                    case=job["case"],
                    workload=job["workload"],
                    policy=job["policy"],
                    fault_index=job["fault_index"],
                    workflow=workflow,
                    workflow_role="primary_fault"
                    if workflow == target
                    else ("co_victim" if workflow in victim_workflows else "collateral"),
                    f0_wct_s=normal,
                    f1_wct_s=failed,
                    delta_wct_s=difference,
                    slowdown=failed / normal if normal else None,
                )
            )
        row = indexed[job["id"]]
        row["delta_wct_mean_s"] = mean(delta)
        row["delta_wct_p95_s"] = quantile(delta, 0.95)
        row["delta_wct_p99_s"] = quantile(delta, 0.99)
        row["fault_workflow_delta_s"] = (
            f1["workflows"][target]["wct_ns"] - f0["workflows"][target]["wct_ns"]
        ) / 1e9
        row["collateral_delta_mean_s"] = mean(other) if other else None
        row["collateral_delta_p95_s"] = quantile(other, 0.95)
        row["collateral_negative_delta_count"] = sum(x < 0 for x in other)
    no_backup = {
        (j["model"], j["case"], j["workload"]): summaries[j["id"]]
        for j in jobs
        if j["policy"] == "none" and not j["failure"] and j["id"] in summaries
    }
    for job in jobs:
        if job["id"] not in indexed or job["f0_id"] not in summaries:
            continue
        baseline = no_backup.get((job["model"], job["case"], job["workload"]))
        if baseline:
            healthy = summaries[job["f0_id"]]
            mean_base = mean(w["wct_ns"] for w in baseline["workflows"].values())
            mean_policy = mean(w["wct_ns"] for w in healthy["workflows"].values())
            indexed[job["id"]]["healthy_mean_wct_vs_none_delta_s"] = (mean_policy - mean_base) / 1e9
            indexed[job["id"]]["healthy_mean_wct_vs_none_ratio"] = mean_policy / mean_base
    return paired, controls


def compare_fault_sets(jobs, summaries, errors):
    groups = defaultdict(list)
    for job in jobs:
        if job["failure"]:
            groups[job["model"], job["case"], job["workload"], job["fault_index"]].append(job)
    reports = []
    for key, planned in groups.items():
        actual = []
        for job in planned:
            if job["id"] not in summaries:
                continue
            result = summaries[job["id"]]
            failure = result["failure"]
            victims = sorted([r["agent"], r["invocation"]] for r in result["recoveries"])
            actual.append(
                dict(
                    policy=job["policy"],
                    run_id=job["id"],
                    agent=failure["agent"],
                    invocation=failure["invocation"],
                    logical_tokens=failure["logical_tokens"],
                    total_tokens=failure["total_tokens"],
                    failed_workers=sorted(failure["workers"]),
                    failed_hosts=sorted({job["config"]["hosts"][w] for w in failure["workers"]}),
                    victim_invocations=victims,
                    co_victim_invocations=[
                        v for v in victims if v != [failure["agent"], failure["invocation"]]
                    ],
                )
            )
        identities = {
            (a["agent"], a["invocation"], a["logical_tokens"], a["total_tokens"]) for a in actual
        }
        primary_matches = len(identities) <= 1
        if not primary_matches:
            errors.append(
                dict(scope=str(key), message="cross-policy primary fault identity/progress differs")
            )
        same = {}
        for field in (
            "failed_workers",
            "failed_hosts",
            "victim_invocations",
            "co_victim_invocations",
        ):
            same[field] = len({json.dumps(a[field]) for a in actual}) <= 1 if actual else None
        reports.append(
            dict(
                model=key[0],
                case=key[1],
                workload=key[2],
                fault_index=key[3],
                expected_policies=[j["policy"] for j in planned],
                observed_policies=[a["policy"] for a in actual],
                complete=len(actual) == len(planned),
                primary_identity_and_progress_match=primary_matches,
                same_sets=same,
                actual=actual,
                interpretation=(
                    "co-victim/worker differences are retained, not hidden by matching only counts"
                ),
            )
        )
    return reports


def audit(base):
    base = Path(base).resolve()
    manifest, plan = read(base / "MANIFEST.json"), read(base / "PLAN.json")
    jobs = plan["jobs"]
    errors, missing, reports = [], [], []
    summaries, metadata_cache, profiles = {}, {}, {}
    strict = "control_sha256" in manifest
    if not strict:
        missing.append("legacy schema: PLAN/PRIORS are not bound by control hashes")
    elif not {"PLAN.json", "PRIORS.json"} <= manifest["control_sha256"].keys():
        missing.append("frozen control hashes do not cover both PLAN and PRIORS")
    required_sources = (
        {
            "python/moonkvsim/aegiskv/current/" + name + ".py"
            for name in ("model", "policy", "runtime", "tracker", "__main__")
        }
        | {
            "python/moonkvsim/aegiskv/evaluation_" + name + ".py"
            for name in ("profile", "campaign", "workload")
        }
        | {
            "python/moonkvsim/simulation/" + name + ".py"
            for name in ("global_des", "network", "ledger", "transaction")
        }
    )
    for relative in sorted(required_sources - manifest["source_sha256"].keys()):
        missing.append(f"required execution source absent from frozen manifest: {relative}")
    check(len({j["id"] for j in jobs}) == len(jobs), "duplicate PLAN job IDs")
    snapshots_ok = True
    live_matches = True
    for relative, expected in manifest["source_sha256"].items():
        path = base / "source_snapshot" / relative
        if not path.exists() or sha(path) != expected:
            snapshots_ok = False
            errors.append(
                dict(scope="source_snapshot", message=f"frozen source hash mismatch: {relative}")
            )
        if not (ROOT / relative).exists() or sha(ROOT / relative) != expected:
            live_matches = False
    for relative, expected in manifest.get("control_sha256", {}).items():
        if sha(base / relative) != expected:
            errors.append(
                dict(scope="controls", message=f"frozen control hash mismatch: {relative}")
            )
    for relative, expected in manifest["profile_sha256"].items():
        profiles[relative] = sha(base / relative)
        if profiles[relative] != expected:
            errors.append(
                dict(scope="profiles", message=f"frozen profile hash mismatch: {relative}")
            )
    input_sources = []
    for relative, expected in manifest.get("input_sha256", {}).items():
        path = ROOT / relative
        matches = path.exists() and sha(path) == expected
        input_sources.append(dict(path=relative, current_source_matches=matches))
        if not matches:
            missing.append(
                "upstream input unavailable or drifted; frozen workloads remain checked: "
                + relative
            )
    priors = read(base / "PRIORS.json")
    priors_sha = sha(base / "PRIORS.json")
    check(
        not set(plan.get("training_workflows", [])) & set(plan.get("evaluation_workflows", [])),
        "training and evaluation workflow sets overlap",
    )
    rows, absent, partial = [], [], []
    for job in jobs:
        folder = base / "runs" / job["id"]
        if not (folder / "COMPLETE.json").exists():
            (partial if folder.exists() else absent).append(job["id"])
            continue
        try:
            workload = plan["workloads"][job["workload"]]
            if job["workload"] not in metadata_cache:
                metadata_cache[job["workload"]] = workload_metadata(
                    base / workload["path"], workload
                )
            meta = metadata_cache[job["workload"]]
            train = set(priors[job["model"]]["training_workflows"])
            check(
                not train & meta["releases"].keys(),
                "predictor training/evaluation workflows overlap",
            )
            profile = read(base / f"profiles/{job['model']}.json")
            geometry, config = profile["config"], job["config"]
            expected_kv = (
                4 * geometry["num_key_value_heads"] * geometry["head_dim"] // profile["tp"]
            )
            check(
                (config["tp"], config["layers"], config["kv_bytes_per_token_per_layer_rank"])
                == (profile["tp"], geometry["num_hidden_layers"], expected_kv),
                "profile/KV geometry mismatch",
            )
            check(
                all(
                    r["model"] == profile["model"]
                    and r["layout"] == "bf16-kv"
                    and r["total"] <= max(profile["context_grid"])
                    for r in meta["requests"].values()
                ),
                "workload model/layout/context is outside frozen profile",
            )
            result, report = audit_run(base, job, workload, meta, profiles, priors_sha, strict)
            reports.append(report)
            missing.extend(f"{job['id']}: {m}" for m in report["missing_evidence"])
            summaries[job["id"]] = result
            rows.append(run_metrics(job, result, report["event_metrics"], True))
        except (AuditViolation, ValueError, KeyError, OSError, TypeError) as error:
            errors.append(dict(scope=job["id"], message=f"{type(error).__name__}: {error}"))
            reports.append(dict(id=job["id"], verified=False, error=str(error)))
    run_index_path = base / "RUNS.json"
    completed_ids = {r["id"] for r in reports}
    if run_index_path.exists():
        run_index = read(run_index_path)
        indexed_ids = [r["id"] for r in run_index]
        if len(set(indexed_ids)) != len(indexed_ids):
            errors.append(dict(scope="RUNS.json", message="duplicate run IDs"))
        if set(indexed_ids) - {j["id"] for j in jobs}:
            errors.append(dict(scope="RUNS.json", message="unplanned run IDs"))
        for row in run_index:
            marker_path = base / "runs" / row["id"] / "COMPLETE.json"
            if not marker_path.exists() or row != read(marker_path):
                errors.append(
                    dict(scope="RUNS.json", message=f"index/marker mismatch: {row['id']}")
                )
        if completed_ids - set(indexed_ids):
            missing.append("RUNS index has not yet incorporated every completed marker")
    elif completed_ids:
        missing.append("RUNS index is absent despite completed markers")
    paired, pair_controls = add_pairs(jobs, summaries, rows, errors, missing)
    fault_sets = compare_fault_sets(jobs, summaries, errors)
    all_finished = len(reports) == len(jobs) and not absent and not partial
    status = "FAIL" if errors else ("PASS" if all_finished and not missing else "PARTIAL")
    groups = defaultdict(list)
    for row in rows:
        groups[
            (
                row["dataset"],
                row["model"],
                row["case"],
                row["workload"],
                row["policy"],
                row["fault"],
            )
        ].append(row)
    summary_stats = []
    for key, members in groups.items():
        values = {
            name: distribution([r.get(name) for r in members])
            for name in (
                "wct_mean_s",
                "wct_p50_s",
                "wct_p95_s",
                "wct_p99_s",
                "delta_wct_mean_s",
                "fault_workflow_delta_s",
                "collateral_delta_mean_s",
                "recovery_latency_mean_s",
            )
        }
        summary_stats.append(
            dict(
                dataset=key[0],
                model=key[1],
                case=key[2],
                workload=key[3],
                policy=key[4],
                fault=key[5],
                run_ids=[r["run_id"] for r in members],
                scenarios=len(members),
                descriptive_across_run_statistics=values,
            )
        )
    stats = dict(
        status=status,
        confidence_intervals=None,
        interpretation=(
            "descriptive only: prespecified failure identities are not independent "
            "physical repeats; workflows within each run are dependent"
        ),
        within_run_quantiles=(
            "linear interpolation of empirical workflow WCTs; p50/p95/p99 are not confidence bounds"
        ),
        aggregation=(
            "each failure scenario contributes one run statistic; "
            "healthy F0 is not duplicated as a new sample per F1"
        ),
        negative_and_zero_outcomes_retained=True,
        collateral_definition=(
            "all workflows other than the injected target workflow, including co-victims; "
            "paired rows distinguish primary_fault, co_victim, and collateral"
        ),
        cells=summary_stats,
    )
    report = dict(
        schema="aegiskv.profile-campaign-audit.v1",
        status=status,
        passed=status == "PASS",
        planned_runs=len(jobs),
        completed_markers=len(reports),
        verified_runs=len(summaries),
        absent_runs=absent,
        partial_runs=partial,
        errors=errors,
        missing_evidence=missing,
        frozen_source_snapshots_verified=snapshots_ok,
        live_source_matches_snapshot=live_matches,
        upstream_inputs=input_sources,
        f0_f1_pairs=pair_controls,
        cross_policy_fault_sets=fault_sets,
        runs=reports,
        full_log_independent_flow_audits=sum(
            r.get("flow_audit", {}).get("independent_flow_audit", False) for r in reports
        ),
        summary_only_evidence=(
            "in-run invariants plus independently checked summary/workload "
            "identities and exported resource peaks; "
            "not independent flow/ledger replay"
        ),
        statistical_unit=stats["interpretation"],
        auditor_sha256=sha(Path(__file__)),
    )
    write_csv(base / "run-metrics.csv", rows)
    write_csv(base / "paired-workflows.csv", paired)
    write_json(base / "STATISTICS.json", stats)
    write_json(base / "AUDIT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.campaign)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "planned_runs",
                    "completed_markers",
                    "verified_runs",
                    "full_log_independent_flow_audits",
                )
            },
            indent=2,
        )
    )
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
