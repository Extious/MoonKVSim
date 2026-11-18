#!/usr/bin/env python3
"""Aggregate a completed paired run, keeping timing repeats distinct from inputs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--completed-contexts-only", action="store_true",
                    help="Publish only committed full contexts from a stopped run; retain stop provenance.")
    args = ap.parse_args()
    root = args.run
    complete = (root / "COMPLETE").exists()
    if not complete and not args.completed_contexts_only:
        raise SystemExit("Refusing an incomplete run; preserve raw trials for diagnosis.")
    meta = json.loads((root / "metadata.json").read_text())
    truncated_records = []
    def read_rows(name):
        text = (root / name).read_text()
        lines = text.splitlines()
        result = []
        for index, line in enumerate(lines):
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                # A hard time limit may interrupt only the last append. Never
                # discard an interior malformed record or a terminated line.
                if complete or index != len(lines)-1 or text.endswith("\n"):
                    raise
                truncated_records.append({"file": name, "line": index+1})
        return result
    raw = read_rows("trials.jsonl")
    validations = read_rows("validation.jsonl")
    planned_contexts = meta["contexts"][:]
    if not complete:
        contexts = []
        for c in planned_contexts:
            marker = root / f"context-{c}-COMPLETE.json"
            if marker.exists():
                record = json.loads(marker.read_text())
                assert record["context_tokens"] == c
                assert all(record[k] == meta[k] for k in ["inputs", "repeats", "warmup"])
                contexts.append(c)
        assert contexts, "No fully completed paired context"
        meta = {**meta, "contexts": contexts, "planned_contexts": planned_contexts}
        raw = [r for r in raw if r["context_tokens"] in contexts]
        validations = [r for r in validations if r["context_tokens"] in contexts]
    assert all(r["correctness"] and r["status"] == "ok" for r in raw)
    assert all(r["correctness"] for r in validations)
    assert {(r["context_tokens"], r["input_id"]) for r in validations} == {
        (c, i) for c in meta["contexts"] for i in range(meta["inputs"])}
    rows = [r for r in raw if not r["warmup"]]
    for c in meta["contexts"]:
        for i in range(meta["inputs"]):
            assert sorted((r["path"], r["repetition"]) for r in raw
                          if r["context_tokens"] == c and r["input_id"] == i) == sorted(
                (p, n) for p in ["HBM", "DRAM", "Recompute"]
                for n in range(-meta["warmup"], meta["repeats"]))
    assert len(rows) == len(meta["contexts"]) * meta["inputs"] * meta["repeats"] * 3
    result = []
    for c in meta["contexts"]:
        hashes = {}
        for path in ["HBM", "DRAM", "Recompute"]:
            medians, all_times = [], []
            for i in range(meta["inputs"]):
                group = [r for r in rows if r["context_tokens"] == c
                         and r["input_id"] == i and r["path"] == path]
                assert sorted(r["repetition"] for r in group) == list(range(meta["repeats"]))
                assert len({r["input_sha256"] for r in group}) == 1
                h = group[0]["input_sha256"]
                assert hashes.setdefault(i, h) == h
                values = [r["latency_ms"] for r in group]
                medians.append(statistics.median(values))
                all_times.extend(values)
            result.append({"context_tokens": c, "history_tokens": c - 64,
                           "tail_tokens": 64, "path": path,
                           "latency_ms": statistics.median(medians),
                           "input_median_min_ms": min(medians),
                           "input_median_max_ms": max(medians),
                           "trial_min_ms": min(all_times), "trial_max_ms": max(all_times),
                           "inputs": meta["inputs"], "timing_repeats_per_input": meta["repeats"],
                           "input_medians_ms": medians, "status": "measured"})
    source_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                     for name in ["metadata.json", "trials.jsonl", "validation.jsonl"]}
    data = {"evidence": "physical_worker_microbenchmark", "metadata": meta,
            "run_complete": complete,
            "omitted_contexts": [c for c in planned_contexts if c not in meta["contexts"]],
            "truncated_final_records": truncated_records,
            "aggregation": "median within input, then median across fixed input streams",
            "source_sha256": source_hashes, "rows": result}
    (root / "measured.json").write_text(json.dumps(data, indent=2))
    with (root / "measured.csv").open("w") as f:
        fields = [k for k in result[0] if k != "input_medians_ms"]
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result)
    print(json.dumps({"contexts": len(meta["contexts"]), "paths": 3,
                      "measured_trials": len(rows), "tp": meta["tp"],
                      "gpu": meta["gpu"], "output": str(root / "measured.json")}))


if __name__ == "__main__":
    main()
