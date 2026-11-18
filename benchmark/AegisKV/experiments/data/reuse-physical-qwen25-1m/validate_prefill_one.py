#!/usr/bin/env python3
"""Read-only audit of a committed 1-token Prefill dataset before publication."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def validate(root):
    assert (root / "COMPLETE").exists(), "The full requested run is incomplete"
    data = json.loads((root / "measured.json").read_text())
    meta = json.loads((root / "metadata.json").read_text())
    assert data["metadata"] == meta and data["run_complete"] and not data["omitted_contexts"]
    assert meta["protocol"] == "prefill_kv_fill_one_token_v1"
    assert meta["new_tokens"] == 1 and meta["forward_mode"].startswith("EXTEND")
    assert meta["inputs"] == 1
    for name, digest in data["source_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    raw = [json.loads(s) for s in (root / "trials.jsonl").read_text().splitlines()]
    checks = [json.loads(s) for s in (root / "validation.jsonl").read_text().splitlines()]
    assert len(checks) == len(meta["contexts"])
    assert {c["context_tokens"] for c in checks} == set(meta["contexts"])
    assert all(c["correctness"] for c in checks)
    assert len(data["rows"]) == len(meta["contexts"]) * 3
    assert len(raw) == len(meta["contexts"]) * (1 + 2*(meta["repeats_by_path"]["HBM"]+1))
    max_errors = {k: 0.0 for k in ["hidden_max_abs", "new_token_kv_max_abs", "decode_max_abs"]}
    for context in meta["contexts"]:
        marker = json.loads((root / f"context-{context}-COMPLETE.json").read_text())
        assert marker["context_tokens"] == context
        group = [r for r in raw if r["context_tokens"] == context]
        assert len({r["input_sha256"] for r in group}) == 1
        assert all(r["new_tokens"] == 1 and r["history_tokens"] == context-1 for r in group)
        assert all(r["correctness"] and r["status"] == "ok" for r in group)
        for row in group:
            assert math.isfinite(row["latency_ms"]) and row["latency_ms"] > 0
            expected_bytes = (context-1) * 28 * 2 * 4 * 128 * 2 if row["path"] == "DRAM" else 0
            assert row["transferred_bytes"] == expected_bytes
            if row["path"] != "Recompute":
                for key in max_errors:
                    assert math.isfinite(row[key]) and row[key] >= 0
                    max_errors[key] = max(max_errors[key], row[key])
        for path, repeats in meta["repeats_by_path"].items():
            selected = [r for r in group if r["path"] == path]
            expected_reps = list(range(repeats)) if path == "Recompute" else list(range(-1, repeats))
            assert sorted(r["repetition"] for r in selected) == expected_reps
            assert all(r["warmup"] == (r["repetition"] < 0) for r in selected)
            values = [r["latency_ms"] for r in selected if not r["warmup"]]
            summary, = [r for r in data["rows"] if r["context_tokens"] == context and r["path"] == path]
            assert summary["new_tokens"] == 1 and summary["history_tokens"] == context-1
            assert summary["status"] == "measured" and summary["timing_repeats_per_input"] == repeats
            assert summary["latency_ms"] == statistics.median(values)
            assert summary["trial_min_ms"] == min(values) and summary["trial_max_ms"] == max(values)
    return {"passed": True, "job_id": meta["job_id"], "contexts": meta["contexts"],
            "formal_timings": sum(not r["warmup"] for r in raw),
            "max_errors": max_errors, "source_sha256": data["source_sha256"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    args = ap.parse_args()
    print(json.dumps(validate(args.run), indent=2))
