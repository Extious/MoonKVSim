"""Read-only, resumable artifact comparison; no runtime imports or DES execution."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAIRS = {
    "formal": ("formal-core-v1", "formal-core-v2-corrected"),
    "structural": ("structural-campaign-v1", "structural-campaign-v2-main"),
    "sensitivity": ("sensitivity-campaign-v1", "sensitivity-campaign-v2-corrected"),
    "capacity": ("capacity-slack-ablation-v1", "capacity-slack-ablation-v2-corrected"),
    "posthoc": ("slack-mechanism-posthoc-v1", "slack-mechanism-posthoc-v2-corrected"),
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_sha(value):
    return hashlib.sha256(
        (
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode()
    ).hexdigest()


def delta(a, b):
    return {
        k: {"old": a.get(k), "new": b.get(k)}
        for k in sorted(a.keys() | b.keys())
        if a.get(k) != b.get(k)
    }


def normal_config(config):
    return {"slack_mode": "dag", **config}


def workload(plan, job):
    if "workloads" in plan:
        return plan["workloads"][job.get("workload_id", job.get("workload"))]
    row = plan["workload"]
    return {"path": row} if isinstance(row, str) else row


def profile(plan, job):
    return plan.get("profile", f"profiles/{job.get('model')}.json")


def verified_source(folder):
    manifest = read(folder / "MANIFEST.json")
    for relative, expected in manifest["source_sha256"].items():
        assert sha(folder / "source_snapshot" / relative) == expected, (folder, relative)
    return {
        "manifest_sha256": sha(folder / "MANIFEST.json"),
        "plan_sha256": sha(folder / "PLAN.json"),
        "source_files_verified": len(manifest["source_sha256"]),
        "runtime_sha256": manifest["source_sha256"]["python/moonkvsim/aegiskv/current/runtime.py"],
        "design_version": manifest["design_version"],
    }


def verified_summary(folder, job, plan, kind):
    run = folder / "runs" / job["id"]
    marker = read(run / "COMPLETE.json")
    assert marker["id"] == job["id"]
    assert "summary_sha256" not in marker or marker["summary_sha256"] == sha(run / "summary.json")
    for field in ("artifact_sha256", "artifacts_sha256"):
        for name, expected in marker.get(field, {}).items():
            assert sha(run / name) == expected, (run, name)
    if "job_sha256" in marker:
        assert marker["job_sha256"] == value_sha(job)
    for key, name in (
        ("plan_sha256", "PLAN.json"),
        ("manifest_sha256", "MANIFEST.json"),
        ("priors_sha256", "PRIORS.json"),
    ):
        if key in marker:
            assert marker[key] == sha(folder / name)
    config, failure = read(run / "config.json"), read(run / "failure.json")
    assert normal_config(config) == normal_config(job["config"])
    assert failure == job["failure"]
    s = read(run / "summary.json")
    assert s["config_sha256"] == sha(run / "config.json") and s["policy"] == job["policy"]
    assert s["complete"] and s["output_tokens_exact"] and s["terminal_allocations_zero"]
    assert s["oracle_reservation_count"] == 0
    w = workload(plan, job)
    expected_workload = (
        w["sha256"]
        if kind == "structural"
        else w.get("content_sha256", plan.get("workload_sha256"))
    )
    assert s["workload_sha256"] == expected_workload, (
        folder.name,
        job["id"],
        s["workload_sha256"],
        expected_workload,
    )
    if "profile_sha256" in marker:
        assert marker["profile_sha256"] == sha(folder / profile(plan, job))
    return s


def normalized_summary(s):
    result = dict(s)
    removed = {}
    # These identities are separately bound to byte-verified source/config/inputs.
    for field in ("design_version", "config_sha256", "workload_sha256", "recovery_eos_model"):
        if field in result:
            removed[field] = result.pop(field)
    if result.get("history_restores") == []:
        removed["history_restores"] = result.pop("history_restores")
    return result, removed


def compare_group(base, label, names, workflow_rows):
    old, new = (base / name for name in names)
    po, pn = read(old / "PLAN.json"), read(new / "PLAN.json")
    sources = {"old": verified_source(old), "new": verified_source(new)}
    application = read(HERE / "QUEUED_HISTORY_APPLICATION.json")
    assert sources["new"]["runtime_sha256"] == application["runtime_after_sha256"]
    assert sources["new"]["design_version"] == application["design_version"]
    if (old / "PRIORS.json").exists():
        assert (old / "PRIORS.json").read_bytes() == (new / "PRIORS.json").read_bytes()
        sources["priors_sha256"] = sha(new / "PRIORS.json")
    old_jobs = {j["id"]: j for j in po["jobs"]}
    inputs, results, pending = {}, [], []
    for nj in pn["jobs"]:
        identity = nj["id"]
        oj = old_jobs[identity]
        assert normal_config(oj["config"]) == normal_config(nj["config"]), identity
        assert {k: v for k, v in oj.items() if k != "config"} == {
            k: v for k, v in nj.items() if k != "config"
        }, identity
        wo, wn = workload(po, oj), workload(pn, nj)
        key = wn["path"]
        if key not in inputs:
            fo, fn = old / wo["path"], new / wn["path"]
            ao, an = gzip.decompress(fo.read_bytes()), gzip.decompress(fn.read_bytes())
            assert ao == an, (label, key, "workload content changed")
            logical = hashlib.sha256(an).hexdigest()
            for directory, spec in ((old, wo), (new, wn)):
                if "content_sha256" in spec:
                    assert spec["content_sha256"] == logical
                    assert spec["sha256"] == sha(directory / spec["path"])
                elif "sha256" in spec:
                    assert spec["sha256"] == logical
            pro, prn = old / profile(po, oj), new / profile(pn, nj)
            assert pro.read_bytes() == prn.read_bytes(), (label, key, "profile changed")
            inputs[key] = {
                "workload_decompressed_sha256": logical,
                "old_compressed_sha256": sha(fo),
                "new_compressed_sha256": sha(fn),
                "profile_sha256": sha(prn),
            }
        if not (new / "runs" / identity / "COMPLETE.json").exists():
            pending.append(identity)
            continue
        a, b = verified_summary(old, oj, po, label), verified_summary(new, nj, pn, label)
        assert a["failure"] == b["failure"], (
            label,
            identity,
            "actual fault identity or time changed",
        )
        assert a["workflows"].keys() == b["workflows"].keys()
        na, ma = normalized_summary(a)
        nb, mb = normalized_summary(b)
        requests_a = {(r["agent"], r["invocation"]): r for r in a["requests"]}
        requests_b = {(r["agent"], r["invocation"]): r for r in b["requests"]}
        assert requests_a.keys() == requests_b.keys()
        assert all(
            requests_a[k]["output_tokens"] == requests_b[k]["output_tokens"] for k in requests_a
        )
        wf_diffs = delta(a["workflows"], b["workflows"])
        for wf in a["workflows"]:
            x, y = a["workflows"][wf], b["workflows"][wf]
            workflow_rows.append(
                {
                    "group": label,
                    "run_id": identity,
                    "fault": nj["failure"] is not None,
                    "workflow": wf,
                    "old_start_ns": x["start_ns"],
                    "new_start_ns": y["start_ns"],
                    "old_finish_ns": x["finish_ns"],
                    "new_finish_ns": y["finish_ns"],
                    "old_wct_ns": x["wct_ns"],
                    "new_wct_ns": y["wct_ns"],
                    "new_minus_old_wct_ns": y["wct_ns"] - x["wct_ns"],
                }
            )
        history_a, history_b = a.get("history_restores", []), b.get("history_restores", [])
        assert not (
            {(r["agent"], r["invocation"]) for r in b["recoveries"]}
            & {(r["agent"], r["invocation"]) for r in history_b}
        )
        row = {
            "id": identity,
            "fault": nj["failure"] is not None,
            "old_summary_sha256": sha(old / "runs" / identity / "summary.json"),
            "new_summary_sha256": sha(new / "runs" / identity / "summary.json"),
            "ignored_bound_identity_or_added_schema_fields": delta(ma, mb),
            "normalized_summary_equal": na == nb,
            "workflows_equal": a["workflows"] == b["workflows"],
            "request_endpoints_equal": requests_a == requests_b,
            "output_counts_equal": True,
            "metrics_equal": a["metrics"] == b["metrics"],
            "peak_bytes_equal": a["peak_bytes"] == b["peak_bytes"],
            "metrics_changes": delta(a["metrics"], b["metrics"]),
            "peak_bytes_changes": delta(a["peak_bytes"], b["peak_bytes"]),
            "workflow_changes": wf_diffs,
            "changed_request_count": sum(requests_a[k] != requests_b[k] for k in requests_a),
            "workflow_count": len(a["workflows"]),
            "wct_sum_new_minus_old_ns": sum(
                b["workflows"][k]["wct_ns"] - a["workflows"][k]["wct_ns"] for k in a["workflows"]
            ),
            "active_recoveries_equal": a["recoveries"] == b["recoveries"],
            "active_agent_ids_old": sorted({r["agent"] for r in a["recoveries"]}),
            "active_agent_ids_new": sorted({r["agent"] for r in b["recoveries"]}),
            "history_agent_ids_old": sorted({r["agent"] for r in history_a}),
            "history_agent_ids_new": sorted({r["agent"] for r in history_b}),
            "active_recoveries_old": a["recoveries"],
            "active_recoveries_new": b["recoveries"],
            "history_restores_old": history_a,
            "history_restores_new": history_b,
            "unexplained_summary_top_level_differences": sorted(
                set(delta(na, nb))
                - {
                    "workflows",
                    "requests",
                    "metrics",
                    "peak_bytes",
                    "recoveries",
                    "history_restores",
                }
            ),
        }
        if nj["failure"] is not None:
            f0 = nj["f0_id"]
            if (new / "runs" / f0 / "COMPLETE.json").exists():
                f0o, f0n = (read(folder / "runs" / f0 / "summary.json") for folder in (old, new))
                row["paired_delta_wct_ns"] = {
                    wf: {
                        "old": a["workflows"][wf]["wct_ns"] - f0o["workflows"][wf]["wct_ns"],
                        "new": b["workflows"][wf]["wct_ns"] - f0n["workflows"][wf]["wct_ns"],
                    }
                    for wf in a["workflows"]
                }
        results.append(row)
    f0 = [r for r in results if not r["fault"]]
    f1 = [r for r in results if r["fault"]]
    violations = [r["id"] for r in f0 if not r["normalized_summary_equal"]]
    unexplained = [r["id"] for r in results if r["unexplained_summary_top_level_differences"]]
    return {
        "old_campaign": str(old),
        "new_campaign": str(new),
        "sources": sources,
        "status": "FAIL_COMPARISON"
        if violations or unexplained
        else "PARTIAL"
        if pending
        else "PASS",
        "planned": len(pn["jobs"]),
        "compared": len(results),
        "pending_ids": pending,
        "old_jobs_outside_new_scope": sorted(set(old_jobs) - {j["id"] for j in pn["jobs"]}),
        "f0_compared": len(f0),
        "f0_normalized_summary_equal": len(f0) - len(violations),
        "f0_not_equal_ids": violations,
        "f1_compared": len(f1),
        "f1_changed_workflow_run_count": sum(not r["workflows_equal"] for r in f1),
        "f1_history_restore_rows": sum(len(r["history_restores_new"]) for r in f1),
        "inputs": inputs,
        "runs": results,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, default=HERE.parent)
    p.add_argument("--out", type=Path, default=HERE / "v1-v2-comparison")
    p.add_argument("--groups", nargs="+", choices=list(PAIRS), default=list(PAIRS))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    workflow_rows = []
    groups = {g: compare_group(args.base, g, PAIRS[g], workflow_rows) for g in args.groups}
    statuses = {g["status"] for g in groups.values()}
    report = {
        "status": "FAIL_COMPARISON"
        if "FAIL_COMPARISON" in statuses
        else "PARTIAL"
        if "PARTIAL" in statuses
        else "PASS",
        "checked_utc": datetime.now(UTC).isoformat(),
        "simulations_executed": 0,
        "script_sha256": sha(Path(__file__)),
        "groups": groups,
        "normalization": [
            "Missing old config.slack_mode is verified equivalent to explicit dag "
            "before ignoring config SHA.",
            "Decompressed workload and profile bytes must be identical; "
            "regenerated gzip containers can have different hashes.",
            "Source/version, config/workload SHA and added recovery_eos_model text "
            "are separately recorded, not numeric endpoints.",
            "Absent history_restores equals only an explicitly empty array; "
            "nonempty rows remain semantic differences.",
        ],
        "limits": [
            "Read-only comparison of completed runs only; partial is never campaign-wide PASS.",
            "Token replay exactness is the runtime assertion plus identical workload IDs "
            "and emitted counts; no native answer generation is rerun.",
            "Summary-only resource fields rely on in-run invariants; "
            "this is not independent byte-flow integration.",
            "F1 changes combine version fixes and resulting scheduling effects; "
            "paired differences are not an isolated queue-free causal decomposition.",
            "Active interrupted recoveries and queued history_restores are reported separately, "
            "never merged into co-victim counts.",
            "No bootstrap intervals: fixed fault scenarios and paired policies "
            "are not independent repetitions.",
        ],
    }
    (args.out / "COMPARISON.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    with (args.out / "paired-workflows.csv").open("w") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(workflow_rows[0]) if workflow_rows else ["group", "run_id"]
        )
        writer.writeheader()
        writer.writerows(workflow_rows)
    fields = (
        "id",
        "fault",
        "normalized_summary_equal",
        "workflows_equal",
        "request_endpoints_equal",
        "metrics_equal",
        "peak_bytes_equal",
        "workflow_count",
        "changed_request_count",
        "wct_sum_new_minus_old_ns",
        "active_recoveries_equal",
    )
    with (args.out / "run-comparison.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=["group", *fields, "history_restore_count"])
        writer.writeheader()
        for group, data in groups.items():
            for row in data["runs"]:
                writer.writerow(
                    {
                        "group": group,
                        **{k: row[k] for k in fields},
                        "history_restore_count": len(row["history_restores_new"]),
                    }
                )
    overview = [
        "# Frozen v1 to corrected v2: read-only comparison",
        "",
        f"Status: **{report['status']}**, checked {report['checked_utc']}. Zero simulations.",
        "",
        "| Group | Compared / planned | F0 exact numeric summary | F1 with changed WCT | "
        "New queued-history rows | Status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for group, data in groups.items():
        overview.append(
            f"| {group} | {data['compared']} / {data['planned']} | "
            f"{data['f0_normalized_summary_equal']} / {data['f0_compared']} | "
            f"{data['f1_changed_workflow_run_count']} / {data['f1_compared']} | "
            f"{data['f1_history_restore_rows']} | {data['status']} |"
        )
    overview.extend(
        [
            "",
            "All counts cover completed pairs at the time of this read, not pending jobs.",
            "F0 equality includes all request/workflow endpoints, emitted counts, every metric "
            "and peak allocation. Ignored fields are listed per run and below.",
            "",
            *[f"- {item}" for item in report["normalization"]],
            "",
            "`COMPARISON.json` contains bound source/input/summary hashes, all numerical metric "
            "changes, and separate full active recovery and queued history records. "
            "`paired-workflows.csv` includes every old/new workflow endpoint, including zeros "
            "and adverse changes. `run-comparison.csv` summarizes all completed runs.",
            "",
            *[f"- {item}" for item in report["limits"]],
            "",
            "Re-run `reviews/compare_corrected_campaigns.py` after additional COMPLETE markers "
            "arrive. It only reads frozen campaign files and updates this review output.",
        ]
    )
    (args.out / "README.md").write_text("\n".join(overview) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "groups": {
                    k: {
                        f: v[f]
                        for f in (
                            "status",
                            "compared",
                            "planned",
                            "f0_compared",
                            "f0_normalized_summary_equal",
                            "f1_compared",
                            "f1_changed_workflow_run_count",
                            "f1_history_restore_rows",
                        )
                    }
                    for k, v in groups.items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
