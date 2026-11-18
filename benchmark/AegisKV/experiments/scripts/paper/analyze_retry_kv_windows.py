"""Evaluate a fixed past-512-query placement against up to 512 future queries.

Reuses verified native sparse selector traces. No GPU execution or fault test.
The new 512->512 protocol is separate from the original 512->64 figure.
"""

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from analyze_retry_kv_insight import trace_counts


ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/native-sparse"
DATA = ROOT / "benchmark/AegisKV/experiments/data"
OUT = DATA / "retry-kv-z512"
MODELS = {
    "NOSA-3B": ("20260915-nosa-3b", 32),
    "MiniCPM4-8B": ("20260915", 32),
    "SeerAttention-Qwen3-8B": ("20260918-seer-qwen3", 36),
}
BOOKS = ("10146", "10321", "10356")
M, Z, BLOCK = 32768, 512, 64
BLOCKS = M // BLOCK
HORIZONS = (64, 128, 256, 512)
FRACTIONS = (.1, .2, .3, .4, .5, .6, .8, 1.)
METRICS = ("past_frequency", "recent_first", "oracle_mandatory", "oracle_relaxed")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old_summary_path = DATA / "design-insights/retry-kv-summary.json"
    old_rows_path = DATA / "design-insights/retry-kv-documents.csv"
    old_summary = json.loads(old_summary_path.read_text())
    with old_rows_path.open() as stream:
        old_rows = {(r["model"], r["book_id"], float(r["budget_fraction"])): r
                    for r in csv.DictReader(stream)}
    protocol = {
        "requested_question": "Top-K from the preceding Z=512 queries covers what historical KV demand in the following Z=512 queries?",
        "evidence": "Offline analysis of existing native model PG19 selector traces; no new forward or fault injection",
        "checkpoint_history_tokens": M,
        "past_queries_one_based": [M - Z + 1, M],
        "primary_target_queries_one_based": [M + 1, M + Z],
        "sensitivity_target_lengths": HORIZONS,
        "physical_object": "(layer, 64-token block), all physical KV heads",
        "historical_blocks_per_layer": BLOCKS,
        "per_layer_budget_fractions": FRACTIONS,
        "rounding": "ceil(fraction * historical_blocks_per_layer)",
        "policy": "Reserve the same mandatory sink/local blocks; fill remaining quota by past selection frequency; break ties by descending position",
        "counting": "Sum native selection occurrences across query positions and selector groups; a Seer 64-query block mask is counted for its 64 queries",
        "placement_updates_during_target_window": False,
        "baseline": "Same mandatory blocks, then most recent historical token positions",
        "primary_metric": "Covered distinct historical layer/block objects divided by needed distinct historical layer/block objects",
        "new_tail_kv": "Excluded from the historical-demand denominator because it does not exist at the checkpoint and must be regenerated during replay",
        "aggregation": "Sum counts over layers for each document, then average the three document coverages",
        "variability": "Document min/max; not confidence intervals",
        "sample": "3 previously used PG19 documents per model, one checkpoint per document, one existing native forward capture per model/document",
        "oracle": "Both mandatory-respecting and relaxed per-layer-capacity upper bounds; never used for ranking",
        "failure_phase": "512 is a fixed full-window target; not an expectation over random failure positions N<=Z",
        "reference": "Windowed adaptation of temporal locality; not a reproduction of SolidAttention's previous-decode-step policy",
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    source_hashes = {str(p.relative_to(ROOT)): sha(p)
                     for p in [old_summary_path, old_rows_path]}
    documents, layers = [], []

    def verify(path):
        key = str(path.relative_to(ROOT))
        source_hashes[key] = sha(path)
        assert source_hashes[key] == old_summary["source_sha256"][key], key

    for model, (folder, layer_count) in MODELS.items():
        root = BASE / folder
        env_path = root / "measured-environment.json"
        verify(env_path)
        cfg = json.loads(env_path.read_text())["native_layer_config"]
        mandatory = np.unique(np.r_[np.arange(cfg["init_blocks"]),
                                    np.arange(BLOCKS - cfg["local_blocks"], BLOCKS)])
        for book in BOOKS:
            run_path = root / "traces" / f"pg19-{book}-M{M}-N{Z}" / "run.json"
            verify(run_path)
            run = json.loads(run_path.read_text())
            assert run["status"] == "complete" and run["logits_finite"]
            assert (run["M"], run["N"]) == (M, Z)
            assert len(run["layers"]) == layer_count
            totals = {(n, f): dict(needed=0, **{key: 0 for key in METRICS})
                      for n in HORIZONS for f in FRACTIONS}
            for record in run["layers"]:
                path = root / record["trace_file"]
                verify(path)
                assert source_hashes[str(path.relative_to(ROOT))] == record["trace_sha256"]
                with np.load(path) as archive:
                    trace = {key: archive[key] for key in archive.files}
                if "block_mask" in trace:
                    assert trace["block_mask"].shape[-2] * BLOCK >= M + Z
                    assert cfg["query_block_size"] == BLOCK
                else:
                    assert trace["selected_blocks"].shape[1] >= M + Z
                past = trace_counts(trace, record, cfg, M - Z, M, BLOCKS)
                hot_order = np.lexsort((-np.arange(BLOCKS), -past))
                eligible = np.ones(BLOCKS, dtype=bool)
                eligible[mandatory] = False
                orders = {
                    "past_frequency": np.r_[mandatory, hot_order[eligible[hot_order]]],
                    "recent_first": np.r_[mandatory, np.arange(BLOCKS)[::-1][eligible[::-1]]],
                }
                for order in orders.values():
                    assert len(order) == len(np.unique(order)) == BLOCKS
                # Ranking is fixed before any target-window demand is inspected.
                previous_needed = np.zeros(BLOCKS, dtype=bool)
                for n in HORIZONS:
                    needed = trace_counts(trace, record, cfg, M, M + n, BLOCKS) > 0
                    assert np.all(~previous_needed | needed)
                    previous_needed = needed
                    demand = int(needed.sum())
                    forced_hits = int(needed[mandatory].sum())
                    for fraction in FRACTIONS:
                        k = math.ceil(fraction * BLOCKS)
                        assert k >= len(mandatory)
                        hits = {key: int(needed[order[:k]].sum()) for key, order in orders.items()}
                        hits["oracle_relaxed"] = min(k, demand)
                        hits["oracle_mandatory"] = forced_hits + min(
                            k - len(mandatory), demand - forced_hits)
                        assert max(hits["past_frequency"], hits["recent_first"]) <= hits["oracle_mandatory"]
                        total = totals[n, fraction]
                        total["needed"] += demand
                        for key in METRICS:
                            total[key] += hits[key]
                        layers.append(dict(model=model, book_id=book,
                                           layer=record["layer_zero_based"] + 1,
                                           target_queries=n, budget_fraction=fraction,
                                           selected_blocks=k, mandatory_blocks=len(mandatory),
                                           needed_blocks=demand, **{key + "_covered_blocks": hits[key] for key in METRICS}))
                del trace
            for (n, fraction), total in totals.items():
                row = dict(model=model, book_id=book, target_queries=n,
                           budget_fraction=fraction, selected_blocks_per_layer=math.ceil(fraction * BLOCKS),
                           needed_blocks=total["needed"],
                           needed_fraction=total["needed"] / (layer_count * BLOCKS),
                           **{key: total[key] / total["needed"] for key in METRICS})
                if n == 64:
                    old = old_rows[model, book, fraction]
                    for new_key, old_key in [("past_frequency", "past_frequency"),
                                             ("recent_first", "recent_first"),
                                             ("oracle_relaxed", "oracle"),
                                             ("needed_fraction", "needed_fraction")]:
                        assert abs(row[new_key] - float(old[old_key])) < 1e-12
                documents.append(row)
            print(model, book, "complete", flush=True)
    for model in MODELS:
        for book in BOOKS:
            for n in HORIZONS:
                group = sorted((row for row in documents if row["model"] == model
                                and row["book_id"] == book and row["target_queries"] == n),
                               key=lambda row: row["budget_fraction"])
                for metric in METRICS:
                    assert all(a[metric] <= b[metric] for a, b in zip(group, group[1:]))
                    assert group[-1][metric] == 1.
    summary = []
    for model in MODELS:
        for n in HORIZONS:
            for fraction in FRACTIONS:
                group = [r for r in documents if r["model"] == model
                         and r["target_queries"] == n and r["budget_fraction"] == fraction]
                assert len(group) == 3
                summary.append(dict(model=model, target_queries=n, budget_fraction=fraction,
                                    selected_blocks_per_layer=math.ceil(fraction * BLOCKS), documents=3,
                                    **{key: dict(mean=float(np.mean([r[key] for r in group])),
                                                min=min(r[key] for r in group), max=max(r[key] for r in group))
                                       for key in (*METRICS, "needed_fraction")}))
    write_csv("documents.csv", documents)
    write_csv("layers.csv", layers)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for p in [Path(__file__).resolve(), Path(__file__).with_name("analyze_retry_kv_insight.py")]:
        source_hashes[str(p.relative_to(ROOT))] = sha(p)
    (OUT / "source-sha256.json").write_text(json.dumps(source_hashes, indent=2) + "\n")
    print("Reproduced all original 64-query document results at all eight budgets.")
    for row in summary:
        if row["budget_fraction"] == .4:
            print(row["model"], "N=", row["target_queries"],
                  {key: round(row[key]["mean"] * 100, 3) for key in (*METRICS, "needed_fraction")})


if __name__ == "__main__":
    main()
