#!/usr/bin/env python3
"""Independent flow/byte-capacity audit and host D2H rate denominators."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def capacity(resource, config):
    prefix = resource.split(":")[0]
    return config[
        {
            "h2d": "h2d_bytes_per_second",
            "d2h": "d2h_bytes_per_second",
            "nic": "network_bytes_per_second",
            "fabric": "network_bytes_per_second",
            "dram-bw": "dram_bytes_per_second",
        }[prefix]
    ]


def audit(out):
    plan, manifest = read(out / "PLAN.json"), read(out / "MANIFEST.json")
    hashes = {}

    def check(path, expected):
        actual = sha(path)
        assert actual == expected, str(path)
        hashes[str(path)] = actual

    for relative, expected in manifest["source_sha256"].items():
        check(out / "source_snapshot" / relative, expected)
    for relative, expected in manifest["control_sha256"].items():
        check(out / relative, expected)
    check(out / plan["profile"], manifest["profile_sha256"])
    check(out / plan["workload"]["path"], plan["workload"]["sha256"])
    rows, flow_audit = [], []
    for job in plan["jobs"]:
        folder = out / "runs" / job["id"]
        marker = read(folder / "COMPLETE.json")
        assert marker["id"] == job["id"]
        for relative, expected in marker["artifact_sha256"].items():
            check(folder / relative, expected)
        summary, config = read(folder / "summary.json"), read(folder / "config.json")
        assert config == job["config"]
        assert summary["detailed_event_and_flow_logs_retained"]
        assert all(
            summary[k] is True
            for k in ("complete", "output_tokens_exact", "terminal_allocations_zero")
        )
        rates = defaultdict(lambda: defaultdict(float))
        physical, d2h = 0.0, defaultdict(float)
        with gzip.open(folder / "flows.jsonl.gz", "rt") as stream:
            for line in stream:
                interval = json.loads(line)
                assert interval["end_ns"] >= interval["start_ns"]
                physical += interval["transferred_bytes"]
                d2h_resources = [r for r in interval["path_resource_ids"] if r.startswith("d2h:")]
                assert len(d2h_resources) <= 1
                if d2h_resources:
                    worker = int(d2h_resources[0].split(":")[1])
                    d2h[config["hosts"][worker]] += interval["transferred_bytes"]
                for resource in interval["path_resource_ids"]:
                    rate = interval["allocated_rate_bytes_per_second"]
                    rates[resource][interval["start_ns"]] += rate
                    rates[resource][interval["end_ns"]] -= rate
        metrics = summary["metrics"]
        accounted = sum(
            metrics.get(f"{kind}_bytes", 0) for kind in ("checkpoint", "hot", "restore")
        )
        accounted += metrics.get("canceled_copy_transferred_bytes", 0)
        residual = physical - accounted
        assert abs(residual) < 1, (job["id"], residual)
        max_utilization = 0.0
        for resource, changes in rates.items():
            allocated, cap = 0.0, capacity(resource, config)
            for _, delta in sorted(changes.items()):
                allocated += delta
                assert -1e-7 * cap <= allocated <= cap * (1 + 1e-7), (job["id"], resource)
                max_utilization = max(max_utilization, allocated / cap)
            assert abs(allocated) <= 1e-7 * cap
        flow_audit.append(
            dict(
                run=job["id"],
                transfer_byte_residual=residual,
                maximum_resource_utilization=max_utilization,
            )
        )
        if job["fault"] == "F0":
            start = min(w["start_ns"] for w in summary["workflows"].values())
            end = max(w["finish_ns"] for w in summary["workflows"].values())
            assert end > start
            for host in sorted(set(config["hosts"])):
                rows.append(
                    dict(
                        run=job["id"],
                        coefficient=config["compute_dma_slowdown"],
                        policy=job["policy"],
                        host=host,
                        d2h_transferred_bytes=d2h[host],
                        observation_start_ns=start,
                        observation_end_ns=end,
                        observation_seconds=(end - start) / 1e9,
                        d2h_bytes_per_second=d2h[host] / ((end - start) / 1e9),
                        includes_partially_transferred_canceled_flows=True,
                    )
                )
    csv_path = out / "healthy-host-d2h.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    record = dict(
        status="PASS",
        runs=len(flow_audit),
        physical_transfer_bytes_reconciled=True,
        per_resource_rate_caps_verified=True,
        healthy_host_rows=len(rows),
        d2h_denominator=(
            "common run window: first workflow release to last workflow completion, "
            "including host idle time"
        ),
        source_sha256=hashes,
        audit_script_sha256=sha(Path(__file__)),
        csv_sha256=sha(csv_path),
        runs_audit=flow_audit,
        limits=[
            "Only24 new detailed runs; old18 parameter points lack uniform per-host logging",
            "Host rates are simulator payload accounting, not measured DMA bandwidth",
        ],
    )
    (out / "FLOW_AUDIT.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("status", "runs", "healthy_host_rows")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    audit(parser.parse_args().out.resolve())
