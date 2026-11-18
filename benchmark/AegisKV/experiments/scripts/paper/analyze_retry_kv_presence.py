"""Evaluate layer/block window-presence prediction on existing native traces.

Parameters are fixed before viewing outcomes: 2048 past queries, windows matching
the 256/512-query target, decay 0.5 per completed window, and 205 blocks/layer.
This is an offline placement diagnostic, not a recovery execution.
"""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from analyze_retry_kv_insight import trace_counts


ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/native-sparse"
DATA = ROOT / "benchmark/AegisKV/experiments/data"
OUT = DATA / "retry-kv-window-presence"
MODELS = {
    "NOSA-3B": ("20260915-nosa-3b", 32),
    "MiniCPM4-8B": ("20260915", 32),
    "SeerAttention-Qwen3-8B": ("20260918-seer-qwen3", 36),
}
BOOKS = ("10146", "10321", "10356")
M, BLOCK, PAST, K, DECAY = 32768, 64, 2048, 205, .5
BLOCKS = M // BLOCK
HORIZONS = (256, 512)
METHODS = ("window_presence", "frequency_2048", "frequency_512", "oracle")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def stats(values):
    return {"mean": float(np.mean(values)), "min": float(min(values)),
            "max": float(max(values))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old_manifest_path = DATA / "design-insights/retry-kv-summary.json"
    old_manifest = json.loads(old_manifest_path.read_text())
    old_layer_path = DATA / "retry-kv-z512/layers.csv"
    with old_layer_path.open() as stream:
        old_layers = {(r["model"], r["book_id"], int(r["layer"]), int(r["target_queries"])): r
                      for r in csv.DictReader(stream) if float(r["budget_fraction"]) == .4}
    protocol = {
        "evidence": "Offline scoring of existing native-model selector traces; no new model forward or failure injection",
        "scope": "Common history-based ranking component only; no trained model-specific prior, online tuning, replacement simulation or latency claim",
        "history_tokens": M, "physical_block_tokens": BLOCK,
        "physical_object": "request/layer/64-token block containing all physical KV heads",
        "past_queries": PAST, "past_queries_one_based": [M - PAST + 1, M],
        "target_lengths": HORIZONS, "main_target_length": 256,
        "target_windows_one_based": {str(n): [M + 1, M + n] for n in HORIZONS},
        "statistics_window_queries": "Equal to target length: eight completed 256-query windows or four completed 512-query windows",
        "window_presence": "A historical block contributes one if selected by any query/group in that completed window, otherwise zero",
        "decay_per_window": DECAY,
        "score": "Normalized exponentially weighted window presence; newest window has weight 1, next 0.5, etc. Equivalent ranking to zero-initialized EMA",
        "parameter_selection": "Fixed before viewing this diagnostic; no sweep, test-set selection, or per-layer fitted decay",
        "quota_blocks_per_layer": K, "historical_blocks_per_layer": BLOCKS,
        "realized_budget_fraction": K / BLOCKS,
        "mandatory_policy": "Same sealed sink/local blocks in every method, counted inside K; remaining scores tie-break by descending block position",
        "prediction_update_during_target": False,
        "baselines": {"frequency_2048": "Selection-event frequency over the same 2048 past queries",
                      "frequency_512": "Original selection-event frequency over the final 512 past queries",
                      "oracle": "Target-aware upper bound with the same mandatory blocks and per-layer quota"},
        "primary_metric": "Distinct historical layer/block demand coverage; repeated accesses count once and new suffix KV is excluded",
        "per_layer_aggregation": "Coverage ratio per document/layer, then mean over three documents",
        "model_macro_aggregation": "Equal mean of all layer ratios within a document, then mean over three documents",
        "model_weighted_aggregation": "Sum covered blocks across layers / sum needed blocks across layers within a document, then mean over three documents",
        "interval": "Min/max over three paired documents, not a confidence interval",
        "sample": "Three reused PG19 documents per model, one checkpoint per document, one existing native capture per model/document",
        "trace_boundary": "NOSA recorded selectors cover the complete forward; its separate selection-vs-mask equality check covers only [32256,33280). This analysis uses recorded selector outputs before that subrange without claiming a new expanded mask check",
        "failure_boundary": "Fixed replay targets; not an expectation over failure phases. Review interval does not imply an asynchronously copied checkpoint has committed",
        "placement_boundary": "Standalone layer-local prediction diagnostic under this task's Peer-residency contract; no manuscript integration",
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    sources = {str(p.relative_to(ROOT)): sha(p) for p in (old_manifest_path, old_layer_path)}
    layers, plans = [], {}

    def verify(path):
        key = str(path.relative_to(ROOT))
        value = sha(path)
        assert value == old_manifest["source_sha256"][key], key
        sources[key] = value
        return value

    for model, (folder, layer_count) in MODELS.items():
        root = BASE / folder
        env_path = root / "measured-environment.json"
        verify(env_path)
        cfg = json.loads(env_path.read_text())["native_layer_config"]
        mandatory = np.unique(np.r_[np.arange(cfg["init_blocks"]),
                                    np.arange(BLOCKS - cfg["local_blocks"], BLOCKS)])
        allowed = np.ones(BLOCKS, dtype=bool)
        allowed[mandatory] = False
        assert K >= len(mandatory)

        def choose(score):
            order = np.lexsort((-np.arange(BLOCKS), -score))
            chosen = np.r_[mandatory, order[allowed[order]]][:K]
            assert len(chosen) == len(np.unique(chosen)) == K
            assert set(mandatory).issubset(chosen)
            return chosen

        for book in BOOKS:
            run_path = root / "traces" / f"pg19-{book}-M{M}-N512/run.json"
            verify(run_path)
            run = json.loads(run_path.read_text())
            assert run["status"] == "complete" and run["logits_finite"]
            assert run["M"] == M and run["N"] == 512 and len(run["layers"]) == layer_count
            for record in run["layers"]:
                path = root / record["trace_file"]
                assert verify(path) == record["trace_sha256"]
                with np.load(path) as archive:
                    trace = {key: archive[key] for key in archive.files}
                assert record["causal_and_nonempty"] if "block_mask" in trace else record["causal_and_unique"]
                if "block_mask" in trace:
                    assert trace["block_mask"].shape[-2] * BLOCK >= M + 512
                else:
                    assert trace["selected_blocks"].shape[1] >= M + 512
                # All placement scores are finalized from pre-checkpoint data.
                freq_2048 = trace_counts(trace, record, cfg, M - PAST, M, BLOCKS)
                freq_512 = trace_counts(trace, record, cfg, M - 512, M, BLOCKS)
                prediction = {}
                for n in HORIZONS:
                    counts = np.stack([trace_counts(trace, record, cfg, lo, lo + n, BLOCKS)
                                       for lo in range(M - PAST, M, n)])
                    assert np.array_equal(counts.sum(axis=0), freq_2048)
                    presence = counts > 0
                    weights = DECAY ** np.arange(len(presence) - 1, -1, -1)
                    score = weights @ presence / weights.sum()
                    assert np.all((0 <= score) & (score <= 1))
                    prediction[n] = {"window_presence": choose(score),
                                     "frequency_2048": choose(freq_2048),
                                     "frequency_512": choose(freq_512)}
                    key = f"{model}_{book}_layer{record['layer_zero_based'] + 1}_n{n}"
                    plans[key + "_presence"] = presence
                    plans[key + "_score"] = score
                    plans[key + "_selected"] = prediction[n]["window_presence"]
                # Evaluation begins only after all predictor scores are fixed.
                for n in HORIZONS:
                    needed = trace_counts(trace, record, cfg, M, M + n, BLOCKS) > 0
                    demand = int(needed.sum())
                    assert demand > 0
                    hits = {method: int(needed[chosen].sum()) for method, chosen in prediction[n].items()}
                    forced_hits = int(needed[mandatory].sum())
                    hits["oracle"] = forced_hits + min(K - len(mandatory), demand - forced_hits)
                    assert all(h <= hits["oracle"] <= demand for h in hits.values())
                    old = old_layers[model, book, record["layer_zero_based"] + 1, n]
                    assert int(old["needed_blocks"]) == demand
                    assert int(old["past_frequency_covered_blocks"]) == hits["frequency_512"]
                    assert int(old["oracle_mandatory_covered_blocks"]) == hits["oracle"]
                    layers.append(dict(model=model, book_id=book, layer=record["layer_zero_based"] + 1,
                                       target_queries=n, observed_queries=PAST, statistics_window=n,
                                       selected_blocks=K, mandatory_blocks=len(mandatory), needed_blocks=demand,
                                       **{method + "_covered_blocks": hits[method] for method in METHODS},
                                       **{method + "_coverage": hits[method] / demand for method in METHODS}))
                del trace
            print(model, book, "complete", flush=True)
    documents, layer_summary, summary = [], [], []
    for model, (_, layer_count) in MODELS.items():
        for n in HORIZONS:
            for book in BOOKS:
                group = [r for r in layers if (r["model"], r["target_queries"], r["book_id"]) == (model, n, book)]
                assert len(group) == layer_count and len({r["layer"] for r in group}) == layer_count
                demand = sum(r["needed_blocks"] for r in group)
                row = dict(model=model, book_id=book, target_queries=n, layers=layer_count, needed_blocks=demand)
                for method in METHODS:
                    row[method + "_macro"] = float(np.mean([r[method + "_coverage"] for r in group]))
                    row[method + "_weighted"] = sum(r[method + "_covered_blocks"] for r in group) / demand
                documents.append(row)
            for layer in range(1, layer_count + 1):
                group = [r for r in layers if (r["model"], r["target_queries"], r["layer"]) == (model, n, layer)]
                assert len(group) == 3
                layer_summary.append(dict(model=model, layer=layer, target_queries=n, documents=3,
                                          **{method: stats([r[method + "_coverage"] for r in group]) for method in METHODS}))
            group = [r for r in documents if (r["model"], r["target_queries"]) == (model, n)]
            record = dict(model=model, target_queries=n, layers=layer_count, documents=3)
            for method in METHODS:
                record[method] = {metric: stats([r[method + "_" + metric] for r in group])
                                  for metric in ("macro", "weighted")}
            record["paired_delta_vs_same_history"] = {
                metric: stats([r["window_presence_" + metric] - r["frequency_2048_" + metric] for r in group])
                for metric in ("macro", "weighted")}
            summary.append(record)
    write_csv(OUT / "layers.csv", layers)
    write_csv(OUT / "documents.csv", documents)
    (OUT / "layer-summary.json").write_text(json.dumps(layer_summary, indent=2) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    np.savez_compressed(OUT / "prediction-plans.npz", **plans)
    for p in (Path(__file__).resolve(), Path(__file__).with_name("analyze_retry_kv_insight.py")):
        sources[str(p.relative_to(ROOT))] = sha(p)
    (OUT / "source-sha256.json").write_text(json.dumps(sources, indent=2) + "\n")
    print("Verified all original 512-observation per-layer counts for both target lengths.")
    for r in summary:
        print(r["model"], "target", r["target_queries"],
              {m: {a: round(r[m][a]["mean"] * 100, 3) for a in ("macro", "weighted")} for m in METHODS})


if __name__ == "__main__":
    main()
