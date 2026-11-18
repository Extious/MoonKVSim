"""Independently check frozen current-design campaign artifacts and flow capacity."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_bytes())


def lines(path: Path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(row) for row in stream]


def capacity(resource: str, config: dict) -> float:
    if resource == "fabric" or resource.startswith("nic:"):
        return config["network_bytes_per_second"]
    if resource.startswith("dram-bw:"):
        return config["dram_bytes_per_second"]
    if resource.startswith("h2d:"):
        return config["h2d_bytes_per_second"]
    if resource.startswith("d2h:"):
        return config["d2h_bytes_per_second"]
    raise ValueError(f"unknown resource {resource}")


def audit(base: Path) -> dict:
    root = Path(__file__).resolve().parents[5]
    manifest = read(base / "MANIFEST.json")
    snapshots = manifest["source_sha256"]
    assert all(
        sha(base / "source_snapshot" / path) == digest for path, digest in snapshots.items()
    ), "source snapshot mismatch"
    live_source_matches = all(sha(root / path) == digest for path, digest in snapshots.items())
    runs = read(base / "RUNS.json")
    assert len({r["id"] for r in runs}) == len(runs)
    results = []
    by_pair = defaultdict(dict)
    by_case = defaultdict(list)
    for run in runs:
        folder = base / "runs" / run["id"]
        assert sha(folder / "summary.json") == run["summary_sha256"], "summary hash mismatch"
        summary = read(folder / "summary.json")
        config = read(folder / "config.json")
        # Legacy snapshots used one 256-token field for both notions. Current
        # runs freeze independently configurable Z and physical KV block size.
        checkpoint_tokens = config.get("checkpoint_tokens", config["block_tokens"])
        assert checkpoint_tokens % config["block_tokens"] == 0
        assert sha(folder / "config.json") == summary["config_sha256"]
        assert summary["complete"] and summary["terminal_allocations_zero"]
        assert (
            summary["output_tokens_exact"] and summary["evidence_class"] == "modeled_uncalibrated"
        )
        by_pair[run["case"], run["seed"], run["policy"]][run["fault"]] = summary
        if run["fault"]:
            by_case[run["case"], run["seed"]].append(summary["failure"]["logical_tokens"])
        assert (
            sum(r["output_tokens"] for r in summary["requests"])
            == summary["metrics"]["emitted_tokens"]
        )
        for recovery in summary["recoveries"]:
            assert recovery["checkpoint_tokens"] % checkpoint_tokens == 0
            assert recovery["rebuild_tokens"] == (
                recovery["durable_tokens"] - recovery["checkpoint_tokens"]
            )
            assert recovery["latency_ns"] == (
                recovery["detection_ns"] + recovery["queue_ns"] + recovery["service_ns"]
            )
            assert recovery["source_worker"] in summary["failure"]["workers"]
            assert recovery["retry_worker"] not in summary["failure"]["workers"]
            if "tail_exceeds_checkpoint_z" in recovery:
                assert recovery["tail_exceeds_checkpoint_z"] == bool(
                    recovery["checkpoint_tokens"] and recovery["rebuild_tokens"] > checkpoint_tokens
                )
        for resource, peak in summary["peak_bytes"].items():
            if resource.startswith("hbm:"):
                assert peak <= config["hbm_bytes_per_rank"]
            if resource.startswith("dram:"):
                assert peak <= config["dram_bytes_per_host"]
        events = lines(folder / "events.jsonl.gz")
        assert [r["time_ns"] for r in events] == sorted(r["time_ns"] for r in events)
        updates = [r for r in events if r["kind"] == "topk_update"]
        commits = [r for r in events if r["kind"] == "checkpoint_commit"]
        if "count_decay" in config:
            assert [(e["time_ns"], e["agent"], e["frontier"]) for e in updates] == [
                (e["time_ns"], e["agent"], e["frontier"]) for e in commits
            ], "Top-K update occurred outside checkpoint publication"
            assert summary["metrics"].get("topk_layer_reranks", 0) == len(commits) * config["depth"]
            for e in events:
                if e["kind"] != "policy_sample":
                    continue
                expected_gain = max(
                    0,
                    max(0, e["dram_recovery_estimate_ns"] - e["slack_ns"])
                    - max(0, e["hbm_recovery_estimate_ns"] - e["slack_ns"]),
                )
                assert e["hbm_gain_ns"] == expected_gain
        assert summary.get("detailed_event_and_flow_logs_retained", True), (
            "full byte/rate audit requires retained flow intervals"
        )
        intervals = lines(folder / "flows.jsonl.gz")
        physical_bytes = sum(r["transferred_bytes"] for r in intervals)
        accounted = sum(
            summary["metrics"].get(f"{kind}_bytes", 0) for kind in ("checkpoint", "hot", "restore")
        )
        accounted += summary["metrics"].get("canceled_copy_transferred_bytes", 0)
        residual = physical_bytes - accounted
        assert abs(residual) < 1, (run["id"], "transfer byte mismatch", residual)
        rates = defaultdict(lambda: defaultdict(float))
        for row in intervals:
            assert row["end_ns"] >= row["start_ns"]
            for resource in row["path_resource_ids"]:
                rate = row["allocated_rate_bytes_per_second"]
                rates[resource][row["start_ns"]] += rate
                rates[resource][row["end_ns"]] -= rate
        peak_utilization = 0.0
        for resource, changes in rates.items():
            allocated = 0.0
            cap = capacity(resource, config)
            for _, delta in sorted(changes.items()):
                allocated += delta
                assert -1e-7 * cap <= allocated <= cap * (1 + 1e-7), (run["id"], resource)
                peak_utilization = max(peak_utilization, allocated / cap)
            assert abs(allocated) <= 1e-7 * cap
        results.append(
            {
                "run": run["id"],
                "pass": True,
                "transfer_byte_residual": residual,
                "maximum_resource_utilization": peak_utilization,
                "recovery_count": len(summary["recoveries"]),
                "long_tail_count": sum(r["tail_exceeds_256"] for r in summary["recoveries"]),
            }
        )
    for pair in by_pair.values():
        assert set(pair) == {False, True}
        assert pair[False]["workload_sha256"] == pair[True]["workload_sha256"]
        assert pair[False]["config_sha256"] == pair[True]["config_sha256"]
        assert pair[False]["workflows"].keys() == pair[True]["workflows"].keys()
    assert all(len(values) == 3 and len(set(values)) == 1 for values in by_case.values())
    report = {
        "pass": True,
        "runs": len(runs),
        "f0_f1_pairs": len(by_pair),
        "frozen_sources_verified": True,
        "live_source_matches_snapshot": live_source_matches,
        "recovery_decomposition_exact": True,
        "flow_resource_caps_verified": True,
        "flow_bytes_reconciled": True,
        "checkpoint_and_block_alignment_verified": True,
        "checkpoint_only_topk_and_gain_verified": True,
        "results": results,
        "auditor_sha256": sha(Path(__file__)),
    }
    (base / "AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    result = audit(args.campaign)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
