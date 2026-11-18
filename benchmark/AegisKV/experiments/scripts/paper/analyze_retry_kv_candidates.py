"""Exploratory CPU comparison of causal placement scores on existing traces.

Same documents, checkpoint, future tail, per-layer capacity and mandatory blocks
as Figure 3(b). These previously examined documents are not a fresh test set.
No model forward, failure injection, parameter search or manuscript replacement.
"""

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/native-sparse"
DATA = ROOT / "benchmark/AegisKV/experiments/data"
OUT = DATA / "retry-kv-candidates"
MODELS = {
    "NOSA-3B": "20260915-nosa-3b",
    "MiniCPM4-8B": "20260915",
    "SeerAttention-Qwen3-8B": "20260918-seer-qwen3",
}
BOOKS = ["10146", "10321", "10356"]
M, PAST, TAIL, BLOCK = 32768, 512, 64, 64
B = M // BLOCK
CAPACITY = math.ceil(0.4 * B)
METHODS = {
    "past_frequency": "Original 512-query selection frequency",
    "recent_first": "Original descending historical token position",
    "frequency_last64": "Selection frequency in the final 64 past queries",
    "frequency_last128": "Selection frequency in the final 128 past queries",
    "frequency_decay128": "Frequency in eight 64-query windows, half-life 128 queries",
    "presence_decay128": "Per-window union presence, half-life 128 queries",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def query_window_counts(trace, record, start, stop):
    if record.get("trace_format") == "query_head_query_block_key_block_bool":
        assert start % BLOCK == stop % BLOCK == 0
        assert record["native_mask_identity_verified"]
        mask = trace["block_mask"]
        assert mask.dtype == np.bool_
        return mask[:, start // BLOCK:stop // BLOCK, :B].sum(
            axis=(0, 1), dtype=np.int64
        ) * BLOCK
    selected = trace["selected_blocks"][:, start:stop]
    valid = selected[(selected >= 0) & (selected < B)]
    return np.bincount(valid, minlength=B)


def selections(past_counts, mandatory):
    """Only historical counts enter the ranking; ties prefer later positions."""
    decay = np.exp2(-np.arange(7, -1, -1) / 2.0)
    scores = {
        "past_frequency": past_counts.sum(axis=0),
        "recent_first": np.arange(B),
        "frequency_last64": past_counts[-1],
        "frequency_last128": past_counts[-2:].sum(axis=0),
        "frequency_decay128": decay @ past_counts,
        "presence_decay128": decay @ (past_counts > 0),
    }
    available = np.ones(B, dtype=bool)
    available[mandatory] = False
    chosen = {}
    for method, score in scores.items():
        order = np.lexsort((-np.arange(B), -score))
        selected = np.r_[mandatory, order[available[order]]][:CAPACITY]
        assert len(selected) == len(np.unique(selected)) == CAPACITY
        assert set(mandatory).issubset(selected)
        chosen[method] = selected
    return chosen


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original_path = DATA / "design-insights/retry-kv-summary.json"
    original = json.loads(original_path.read_text())
    protocol = {
        "scope": "Exploratory offline re-scoring of previously examined native PG19 traces",
        "future_information": "No tail selection enters any candidate score",
        "checkpoint": M,
        "past_queries": PAST,
        "target_queries": TAIL,
        "physical_object": "layer, 64-token block, all KV heads",
        "historical_blocks_per_layer": B,
        "selected_blocks_per_layer": CAPACITY,
        "budget_fraction_realized": CAPACITY / B,
        "mandatory_policy": "Same sink and full local window as original figure",
        "methods": METHODS,
        "tie_break": "Descending token position for every score",
        "aggregation": "Sum hits and demand across layers per document, then mean over documents",
        "oracle": "Report both original relaxed bound and mandatory-respecting bound",
        "limitations": [
            "Three previously examined documents per model, one checkpoint per document",
            "No fresh generalization evaluation or hyperparameter selection",
            "No measured recovery time, transfer traffic, selector overhead or WCT",
        ],
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    provenance = {str(original_path.relative_to(ROOT)): digest(original_path)}
    layer_rows, document_rows = [], []
    for model, folder in MODELS.items():
        root = BASE / folder
        env_path = root / "measured-environment.json"
        cfg = json.loads(env_path.read_text())["native_layer_config"]
        for path in [env_path]:
            key = str(path.relative_to(ROOT))
            provenance[key] = digest(path)
            assert provenance[key] == original["source_sha256"][key]
        mandatory = np.unique(np.r_[
            np.arange(cfg["init_blocks"]), np.arange(B - cfg["local_blocks"], B)
        ])
        assert len(mandatory) <= CAPACITY
        for book in BOOKS:
            run_path = root / "traces" / f"pg19-{book}-M{M}-N512" / "run.json"
            run = json.loads(run_path.read_text())
            assert run["status"] == "complete" and run["logits_finite"]
            key = str(run_path.relative_to(ROOT))
            provenance[key] = digest(run_path)
            assert provenance[key] == original["source_sha256"][key]
            totals = {method: 0 for method in METHODS}
            totals.update(oracle_relaxed=0, oracle_mandatory=0)
            total_needed = 0
            for record in run["layers"]:
                path = root / record["trace_file"]
                key = str(path.relative_to(ROOT))
                provenance[key] = digest(path)
                assert provenance[key] == record["trace_sha256"] == original["source_sha256"][key]
                with np.load(path) as trace:
                    past = np.stack([
                        query_window_counts(trace, record, start, start + BLOCK)
                        for start in range(M - PAST, M, BLOCK)
                    ])
                    selected = selections(past, mandatory)
                    needed = query_window_counts(trace, record, M, M + TAIL) > 0
                demand = int(needed.sum())
                total_needed += demand
                required_hits = int(needed[mandatory].sum())
                totals["oracle_relaxed"] += min(CAPACITY, demand)
                exact_bound = required_hits + min(
                    CAPACITY - len(mandatory), demand - required_hits
                )
                totals["oracle_mandatory"] += exact_bound
                for method, blocks in selected.items():
                    hits = int(needed[blocks].sum())
                    assert hits <= exact_bound
                    totals[method] += hits
                    layer_rows.append({
                        "model": model, "book_id": book,
                        "layer": record["layer_zero_based"] + 1,
                        "method": method, "selected_blocks": CAPACITY,
                        "mandatory_blocks": len(mandatory),
                        "needed_blocks": demand, "covered_blocks": hits,
                    })
            for method, hits in totals.items():
                document_rows.append({
                    "model": model, "book_id": book, "method": method,
                    "needed_blocks": total_needed, "covered_blocks": hits,
                    "coverage": hits / total_needed,
                })
            print(model, book, "complete", flush=True)
    summary = {}
    for model in MODELS:
        summary[model] = {}
        for method in [*METHODS, "oracle_relaxed", "oracle_mandatory"]:
            values = [row["coverage"] for row in document_rows
                      if row["model"] == model and row["method"] == method]
            summary[model][method] = {
                "mean": float(np.mean(values)), "min": min(values), "max": max(values)
            }
        for new_key, old_key in [("past_frequency", "past_frequency"),
                                 ("recent_first", "recent_first"),
                                 ("oracle_relaxed", "oracle")]:
            for stat in ["mean", "min", "max"]:
                assert abs(summary[model][new_key][stat] - original["summary"][model][old_key][stat]) < 1e-12
    write_csv("documents.csv", document_rows)
    write_csv("layers.csv", layer_rows)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    provenance[str(Path(__file__).resolve().relative_to(ROOT))] = digest(Path(__file__))
    (OUT / "source-sha256.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("Baseline means, ranges, and original upper bounds reproduced exactly.")
    for model, results in summary.items():
        print(model, {method: round(stats["mean"] * 100, 3) for method, stats in results.items()})


if __name__ == "__main__":
    main()
