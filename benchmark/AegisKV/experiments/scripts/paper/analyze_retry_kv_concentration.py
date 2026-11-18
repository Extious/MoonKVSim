"""Measure same-window hot-block concentration in existing native selector traces.

All placement objects contain all physical KV heads. Two counting conventions
are kept separate: query/block incidence (merge heads per query), and native
selector occurrences (count each query/head-or-group occurrence). Neither is
measured GPU memory traffic or a causal prediction result.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from analyze_retry_kv_insight import trace_counts


ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/native-sparse"
DATA = ROOT / "benchmark/AegisKV/experiments/data"
OUT = DATA / "retry-kv-access-concentration"
MODELS = {
    "NOSA-3B": ("20260915-nosa-3b", 32),
    "MiniCPM4-8B": ("20260915", 32),
    "SeerAttention-Qwen3-8B": ("20260918-seer-qwen3", 36),
}
BOOKS = ("10146", "10321", "10356")
M, BLOCK, BLOCKS = 32768, 64, 512
WINDOWS = (256, 512)
METRICS = ("query_block", "selector_event")
BUDGETS = {"10": 52, "20": 103, "40": 205}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def statistics(values):
    return {"mean": float(np.mean(values)), "min": float(np.min(values)),
            "max": float(np.max(values))}


def cumulative(counts):
    total = int(counts.sum())
    assert total > 0 and counts.shape == (BLOCKS,)
    curve = np.r_[0, np.cumsum(np.sort(counts)[::-1], dtype=np.int64)]
    assert curve[-1] == total and np.all(np.diff(curve) >= 0)
    assert np.all(curve / total + 1e-12 >= np.arange(BLOCKS + 1) / BLOCKS)
    return curve


def query_block_counts(trace, record, cfg, n):
    if record.get("trace_format") == "query_head_query_block_key_block_bool":
        # A Seer mask is shared by all 64 queries in each native query block.
        # Weight each such incidence by 64, without inventing 64 independent
        # selector decisions. All queried boundaries align to native blocks.
        size = cfg["query_block_size"]
        assert M % size == n % size == 0 and record["native_mask_identity_verified"]
        mask = trace["block_mask"][:, M // size:(M + n) // size, :BLOCKS]
        assert mask.dtype == np.bool_
        return mask.any(axis=0).sum(axis=0, dtype=np.int64) * size
    selected = trace["selected_blocks"][:, M:M + n]
    good = (selected >= 0) & (selected < BLOCKS)
    query = np.broadcast_to(np.arange(n)[None, :, None], selected.shape)
    incidence = np.zeros((n, BLOCKS), dtype=bool)
    incidence[query[good], selected[good]] = True
    # Independent set-per-query check: a head/group duplicate must not count
    # twice in this convention.
    check = np.zeros(BLOCKS, dtype=np.int64)
    for q in range(n):
        ids = selected[:, q].ravel()
        check[np.unique(ids[(ids >= 0) & (ids < BLOCKS)])] += 1
    result = incidence.sum(axis=0, dtype=np.int64)
    assert np.array_equal(result, check)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA / "design-insights/retry-kv-summary.json"
    reference = json.loads(manifest_path.read_text())["source_sha256"]
    legacy_path = DATA / "retry-kv-z512/layers.csv"
    with legacy_path.open() as stream:
        legacy = {(r["model"], r["book_id"], int(r["layer"]), int(r["target_queries"])): r
                  for r in csv.DictReader(stream) if float(r["budget_fraction"]) == .4}
    old_concentration_path = BASE / "20260915/SUMMARY_MODELS.json"
    old_concentration = json.loads(old_concentration_path.read_text())["results"]
    sources = {str(p.relative_to(ROOT)): sha(p) for p in
               (manifest_path, legacy_path, old_concentration_path)}
    protocol = {
        "evidence": "Offline analysis of existing native-model PG19 traces; no new forward, failure injection, or memory-traffic measurement",
        "question": "Does a small per-layer subset of historical KV blocks account for many logical selection references?",
        "history_tokens": M, "block_tokens": BLOCK, "historical_blocks_per_layer": BLOCKS,
        "object": "One request/layer/64-token block containing all physical KV heads; no head-level placement",
        "windows": {str(n): [M + 1, M + n] for n in WINDOWS},
        "window_dependence": "256 queries are nested in the same 512-query forward, not an independent run",
        "query_block": "One count when any head/group selects the block for a query; merge heads within each query but retain repeats across queries",
        "selector_event": "Sum native query/group selection occurrences for NOSA/MiniCPM4; query/head mask occurrences for Seer. This is not a common count of physical HBM reads across models",
        "seer_semantics": "Native 64-query-block masks are counted with weight 64; there are no independent per-token gate decisions",
        "ranking": "Each layer is sorted by its actual frequency in the SAME evaluated window, separately for each counting convention. Retrospective concentration, not future prediction",
        "quota": "Equal K per layer, swept over every integer 0..512; x denominator includes all 512 historical blocks, including never-accessed blocks",
        "mandatory_policy": "No forced sink/local reservations in pure concentration ranking; their native accesses remain counted",
        "primary_aggregation": "At each K, normalize cumulative counts per document/layer; average all layers equally within each document, then average the three documents",
        "secondary_aggregation": "Also retain event-weighted aggregation within each document before averaging documents",
        "interval": "Document min/max over n=3 reused documents, not confidence intervals",
        "books": BOOKS, "layers": {m: layers for m, (_, layers) in MODELS.items()},
        "captures": "Nine previously completed native forwards: three documents per model, one M32768/N512 capture per model/document",
        "reported_budgets": {label: {"K": k, "actual_fraction": k / BLOCKS} for label, k in BUDGETS.items()},
        "limits": "No attention-mass, model-quality, online hit-rate, unique-demand-coverage, H2D-traffic, or recovery-latency claim. Three PG19 documents do not establish agentic-workload generality",
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")

    def verify(path):
        rel = str(path.relative_to(ROOT))
        digest = sha(path)
        assert digest == reference[rel], rel
        sources[rel] = digest

    layer_rows, document_rows, curve_rows, summaries, stored = [], [], [], [], {}
    pooled_reference_checks = 0
    for model, (folder, layers) in MODELS.items():
        root = BASE / folder
        env_path = root / "measured-environment.json"
        verify(env_path)
        cfg = json.loads(env_path.read_text())["native_layer_config"]
        mandatory = np.unique(np.r_[np.arange(cfg["init_blocks"]),
                                    np.arange(BLOCKS - cfg["local_blocks"], BLOCKS)]).astype(int)
        document_curves = {}
        for book in BOOKS:
            run_path = root / "traces" / f"pg19-{book}-M{M}-N512/run.json"
            verify(run_path)
            run = json.loads(run_path.read_text())
            assert run["status"] == "complete" and run["logits_finite"]
            assert (run["M"], run["N"]) == (M, 512)
            assert sorted(r["layer_zero_based"] for r in run["layers"]) == list(range(layers))
            counts_by_window = {(n, metric): [] for n in WINDOWS for metric in METRICS}
            for record in run["layers"]:
                path = root / record["trace_file"]
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                rel = str(path.relative_to(ROOT))
                assert digest == reference[rel] == record["trace_sha256"]
                sources[rel] = digest
                with np.load(io.BytesIO(raw)) as archive:
                    trace = {key: archive[key] for key in archive.files}
                assert record.get("causal_and_nonempty", record.get("causal_and_unique"))
                if "block_mask" in trace:
                    assert record["native_mask_identity_verified"]
                elif model == "NOSA-3B":
                    assert record["native_mask_equals_selected_blocks"]
                    lo, hi = record["native_mask_checked_query_range"]
                    assert lo <= M and hi >= M + 512
                layer = record["layer_zero_based"] + 1
                for n in WINDOWS:
                    event = trace_counts(trace, record, cfg, M, M + n, BLOCKS)
                    query_block = query_block_counts(trace, record, cfg, n)
                    assert np.all(query_block <= n) and np.all(query_block <= event)
                    assert np.array_equal(query_block > 0, event > 0)
                    assert np.count_nonzero(event) == int(legacy[model, book, layer, n]["needed_blocks"])
                    if n == 512 and "cached_history_selections_in_suffix" in record:
                        assert event.sum() == record["cached_history_selections_in_suffix"]
                    for metric, counts in (("query_block", query_block), ("selector_event", event)):
                        counts_by_window[n, metric].append(counts)
                        key = f"{model}_{book}_layer{layer}_n{n}_{metric}"
                        stored[key] = counts.astype(np.int32)
                        csum = cumulative(counts)
                        total = int(csum[-1])
                        share = csum / total
                        layer_rows.append(dict(
                            model=model, book_id=book, layer=layer, window_queries=n, metric=metric,
                            counts_key=key, total_references=total, distinct_blocks=int(np.count_nonzero(counts)),
                            native_mandatory_references=int(counts[mandatory].sum()),
                            blocks_for_80pct=int(np.searchsorted(share, .8)),
                            blocks_for_90pct=int(np.searchsorted(share, .9)),
                            **{f"top{label}_references": int(csum[k]) for label, k in BUDGETS.items()},
                            **{f"top{label}_share": float(share[k]) for label, k in BUDGETS.items()}))
                del raw, trace
            for (n, metric), vectors in counts_by_window.items():
                assert len(vectors) == layers
                stack = np.stack(vectors)
                sums = np.stack([cumulative(v) for v in vectors])
                macro = (sums / sums[:, -1:]).mean(axis=0)
                weighted = sums.sum(axis=0) / sums[:, -1].sum()
                document_curves[book, n, metric] = (macro, weighted)
                document_rows.append(dict(model=model, book_id=book, window_queries=n, metric=metric,
                                          layers=layers, total_references=int(stack.sum()),
                                          distinct_blocks=int(np.count_nonzero(stack)),
                                          **{f"top{label}_macro": float(macro[k]) for label, k in BUDGETS.items()},
                                          **{f"top{label}_weighted": float(weighted[k]) for label, k in BUDGETS.items()}))
                # Earlier figures pooled all layer/block scores and used a
                # globally shared quota. Reproduce those old numbers solely
                # as an input consistency check; do not mix that policy into
                # the current equal-per-layer main curves.
                if metric == "selector_event" and model != "SeerAttention-Qwen3-8B":
                    old_key = f"{model}/{book}/M{M}" + (f"/N{n}" if n != 512 else "")
                    old = old_concentration[old_key]
                    assert int(stack.sum()) == old["access_events"]
                    flat = np.sort(stack.ravel())[::-1]
                    pooled = np.r_[0, np.cumsum(flat, dtype=np.int64)] / flat.sum()
                    for point in old["granularities"]["layer_block"]["budgets"].values():
                        assert abs(pooled[point["units"]] - point["offline_access_coverage"]) < 1e-12
                        pooled_reference_checks += 1
            print(model, book, "complete", flush=True)
        for n in WINDOWS:
            for metric in METRICS:
                macro = np.stack([document_curves[book, n, metric][0] for book in BOOKS])
                weighted = np.stack([document_curves[book, n, metric][1] for book in BOOKS])
                for k in range(BLOCKS + 1):
                    curve_rows.append(dict(model=model, window_queries=n, metric=metric, K=k,
                                           block_fraction=k / BLOCKS,
                                           **statistics(macro[:, k]), weighted_mean=float(weighted[:, k].mean())))
                group = [r for r in layer_rows if r["model"] == model and r["window_queries"] == n and r["metric"] == metric]
                summaries.append(dict(model=model, window_queries=n, metric=metric, documents=3, layers=layers,
                                      **{f"top{label}": {"macro": statistics(macro[:, k]), "weighted": statistics(weighted[:, k])}
                                         for label, k in BUDGETS.items()},
                                      layer_fraction_for_90pct_mean=float(np.mean([r["blocks_for_90pct"] / BLOCKS for r in group])),
                                      mean_distinct_fraction=float(np.mean([r["distinct_blocks"] / BLOCKS for r in group])),
                                      layers_with_top20_at_least_80pct_per_document={book: sum(r["top20_share"] >= .8 for r in group if r["book_id"] == book) for book in BOOKS}))
    write_csv(OUT / "layers.csv", layer_rows)
    write_csv(OUT / "documents.csv", document_rows)
    write_csv(OUT / "curves.csv", curve_rows)
    np.savez_compressed(OUT / "counts.npz", **stored)
    (OUT / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    for p in (Path(__file__).resolve(), Path(__file__).with_name("analyze_retry_kv_insight.py")):
        sources[str(p.relative_to(ROOT))] = sha(p)
    (OUT / "source-sha256.json").write_text(json.dumps(sources, indent=2) + "\n")
    checks = dict(layer_metric_rows=len(layer_rows), document_metric_rows=len(document_rows),
                  curve_points=len(curve_rows), saved_count_vectors=len(stored),
                  legacy_pooled_concentration_points_reproduced=pooled_reference_checks,
                  legacy_unique_demand_rows_reproduced=len(layer_rows) // 2)
    (OUT / "analysis-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps(checks), flush=True)
    for row in summaries:
        print(row["model"], row["window_queries"], row["metric"],
              {b: round(100 * row[f"top{b}"]["macro"]["mean"], 2) for b in BUDGETS}, flush=True)


if __name__ == "__main__":
    main()
