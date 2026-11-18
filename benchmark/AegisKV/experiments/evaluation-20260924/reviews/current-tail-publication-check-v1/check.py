"""Bounded sealed-log tail check. No DES, runtime imports, or v3 log reads."""

import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
OUT = Path(__file__).resolve().parent
CASES = (
    ("formal-core-v2-corrected", "Qwen3-8B-load0.65-aegiskv-F1-2"),
    ("formal-core-v2-corrected", "Qwen3-32B-load0.65-aegiskv-F1-2"),
    ("sensitivity-campaign-v2-corrected", "center-aegiskv-F0"),
    ("sensitivity-campaign-v2-corrected", "center-aegiskv-F1"),
    ("structural-campaign-v2-main", "forkjoin_skew-n8-s7-aegiskv-left.decode"),
    ("structural-campaign-v2-main", "long_decode_drift-n8-s7-aegiskv-left.decode"),
)
HASHES = {}


def data(path):
    value = path.read_bytes()
    HASHES[str(path)] = hashlib.sha256(value).hexdigest()
    return value


def read(path):
    return json.loads(data(path))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main():
    snapshots, scans, runtime_hashes = [], [], set()
    for campaign, identity in CASES:
        base = BASE / campaign
        plan, manifest = read(base / "PLAN.json"), read(base / "MANIFEST.json")
        job = next(job for job in plan["jobs"] if job["id"] == identity)
        assert job.get("detailed_logs") or job.get("retain_detailed_logs")
        runtime_relative = "python/moonkvsim/aegiskv/current/runtime.py"
        runtime = base / "source_snapshot" / runtime_relative
        runtime_text = data(runtime).decode()
        runtime_sha = HASHES[str(runtime)]
        runtime_hashes.add(runtime_sha)
        assert runtime_sha == manifest["source_sha256"][runtime_relative]
        # Source-backed meaning of the logged failure snapshots, not prompt length.
        assert "state.durable = max(state.durable, end)" in runtime_text
        assert '"logical_tokens": target.computed' in runtime_text
        assert '"durable_tokens": state.durable' in runtime_text
        assert '"checkpoint_tokens": frontier' in runtime_text
        assert "cp.frontier + c.checkpoint_tokens > state.computed" in runtime_text
        directory = base / "runs" / identity
        marker, config = read(directory / "COMPLETE.json"), read(directory / "config.json")
        summary = read(directory / "summary.json")
        assert summary["complete"] and summary["detailed_event_and_flow_logs_retained"]
        digest = marker.get("summary_sha256", marker.get("artifact_sha256", {}).get("summary.json"))
        assert digest == HASHES[str(directory / "summary.json")]
        assert config == job["config"]
        event_bytes = data(directory / "events.jsonl.gz")
        events = [json.loads(line) for line in gzip.decompress(event_bytes).splitlines()]
        # Flow bytes are bound, but only their schema is inspected: the serializer
        # lacks an Agent/epoch/checkpoint-owner join, so no identity is guessed.
        flow_bytes = data(directory / "flows.jsonl.gz")
        first_flow = next(iter(gzip.decompress(flow_bytes).splitlines()), None)
        flow_fields = sorted(json.loads(first_flow)) if first_flow else []
        kinds = Counter(e["kind"] for e in events)
        assert not any(e["kind"] in ("forward_done", "forward_complete", "token_accepted") for e in events)
        failures = [(i, e) for i, e in enumerate(events) if e["kind"] == "failure"]
        assert len(failures) == (1 if summary["failure"] else 0)
        scan = dict(campaign=campaign, run_id=identity, checkpoint_z=config["checkpoint_tokens"],
                    runtime_sha256=runtime_sha, design_version=summary["design_version"],
                    event_rows=len(events), event_kinds=dict(kinds), first_flow_fields=flow_fields,
                    full_run_max_tail_reconstructable=False,
                    full_run_max_tail=None, failure_snapshots=0)
        for failure_index, fault in failures:
            assert {k: fault[k] for k in summary["failure"]} == summary["failure"]
            prior = list(enumerate(events[:failure_index], 1))
            records = [("active_recovery", r) for r in summary["recoveries"]]
            records += [("queued_history", r) for r in summary.get("history_restores", [])]
            for kind, recovery in records:
                key = recovery["agent"]
                assert recovery["failure_ns"] == fault["time_ns"]
                accepted, frontier = recovery["durable_tokens"], recovery["checkpoint_tokens"]
                if not frontier:
                    continue  # Unprotected/cold-start gaps cannot be the requested witness.
                commits = [(i, e) for i, e in prior if e["kind"] == "checkpoint_commit" and e["agent"] == key]
                assert commits
                commit_line, commit = commits[-1]
                assert commit["frontier"] == frontier and commit["tp_acks"] == config["tp"]
                assert commit["peer"] not in fault["workers"]
                submits = [(i, e) for i, e in prior if e["kind"] == "submit" and e["agent"] == key]
                assert submits
                submit_line, submit = submits[-1]
                assert submit["invocation"] == recovery["invocation"]
                policy = [(i, e) for i, e in prior if e["kind"] == "policy_sample" and e["agent"] == key]
                is_target = key == fault["agent"] and recovery["invocation"] == fault["invocation"]
                if is_target:
                    assert accepted == fault["logical_tokens"]
                    assert policy and policy[-1][1]["protected"]
                    # The last control sample can precede a later CP publication;
                    # it corroborates protection but is not a fault-time snapshot.
                    assert policy[-1][1]["checkpoint_tokens"] <= frontier
                tail = accepted - frontier
                assert tail == recovery["rebuild_tokens"] and tail >= 0
                snapshots.append(dict(
                    campaign=campaign, run_id=identity, agent=key,
                    invocation=recovery["invocation"], snapshot_kind=kind,
                    is_fault_target=is_target, fault_time_ns=fault["time_ns"],
                    failure_event_line=failure_index + 1,
                    accepted_frontier=accepted, committed_frontier=frontier, tail_tokens=tail,
                    checkpoint_z=config["checkpoint_tokens"], strictly_exceeds_z=tail > config["checkpoint_tokens"],
                    checkpoint_identity=commit["identity"], checkpoint_peer=commit["peer"],
                    checkpoint_commit_ns=commit["time_ns"], checkpoint_commit_event_line=commit_line,
                    latest_submit_event_line=submit_line,
                    latest_submit_local_prefix_tokens=submit["local_prefix_tokens"],
                    latest_protected_sample_event_line=policy[-1][0] if policy else None,
                    latest_protected_sample=policy[-1][1] if policy else None,
                    checkpoint_available_at_failure=True,
                    recovery_epoch=0,
                    epoch_basis="source-derived: first and only fault; no earlier recovery/EOS cleanup epoch change",
                    publication_pending_recorded=None,
                    publication_pending_inferred=False if tail < config["checkpoint_tokens"] else None,
                    pending_inference=("Pending append requires computed >= frontier+Z; computed<=durable. "
                                       "Here durable-frontier<Z, so that same checkpoint cannot have an append pending. "
                                       "This is a code-derived inference, not a recorded pending flag."),
                ))
                scan["failure_snapshots"] += 1
        scans.append(scan)
    assert len(runtime_hashes) == 1
    live = ROOT / "python/moonkvsim/aegiskv/current/runtime.py"
    data(live)
    assert HASHES[str(live)] in runtime_hashes
    data(Path(__file__))
    assert len(snapshots) == 11
    targets = [s for s in snapshots if s["is_fault_target"]]
    assert len(targets) == 5
    result = dict(
        status="BOUNDED_CHECK_COMPLETE_NO_CURRENT_TAIL_GT_Z_WITNESS",
        scope=[dict(campaign=c, run_id=r) for c, r in CASES],
        source_sha256=HASHES.copy(), scanned_cases=scans,
        snapshots=snapshots, fault_target_snapshot_count=len(targets),
        queued_history_snapshot_count=len(snapshots) - len(targets),
        maximum_aligned_failure_tail_tokens=max(s["tail_tokens"] for s in snapshots),
        maximum_aligned_target_failure_tail_tokens=max(s["tail_tokens"] for s in targets),
        strictly_exceeds_z_snapshot_count=sum(s["strictly_exceeds_z"] for s in snapshots),
        global_maximum_tail_tokens=None,
        global_maximum_reconstructable=False,
        limitations=[
            "Normal completed-forward/accepted-token frontier is not logged; policy_sample lacks it.",
            "checkpoint_commit has Agent, frontier and checkpoint identity but no invocation/epoch/pending flag.",
            "Before the sole failure, epoch0 is source-derived; event order and last submit align invocation.",
            "flow intervals lack Agent/epoch/checkpoint identity owner; no join is inferred from copy numeric IDs.",
            "recovery_layer query ranges describe replay computation, not newly accepted-token progress.",
            "The five aligned fault-target tails are100,100,100,128,77 withZ256. No global <=Z claim follows.",
            "No original prompt length or total output length is used as accepted progress.",
            "No v3 log or unselected case is read, no DES is run, and sealed campaigns are unchanged.",
        ],
    )
    for name, digest in HASHES.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
    result["input_files_unchanged"] = True
    write(OUT / "RESULT.json", result)
    rows = [{k: v for k, v in s.items() if not isinstance(v, dict)} for s in snapshots]
    with (OUT / "failure-snapshots.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("6cases;5target+6history snapshots;max128/Z256;globalmax unavailable;no >Z witness")


if __name__ == "__main__":
    main()
