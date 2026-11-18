#!/usr/bin/env python3
"""Replay complete native selector histories with deployed checkpoint Top-K rules.

CPU-only analysis of sealed native captures. Does not modify the original cold
diagnostic, run model forwards, or estimate recovery latency.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
sys.path.insert(0, str(ROOT / "python"))
from moonkvsim.aegiskv.current.policy import top_blocks as runtime_top_blocks  # noqa: E402

_cold_path = Path(__file__).with_name("analyze_native_topk.py")
_spec = importlib.util.spec_from_file_location("frozen_cold_diagnostic", _cold_path)
cold = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cold)
assert cold.sha(_cold_path) == "102cf56d8a62d337842c72bd68af594c361471634f12802bca30f08886691770"
sha, write_json, write_csv = cold.sha, cold.write_json, cold.write_csv
CHECKPOINTS, K_VALUES, METHODS = cold.CHECKPOINTS, cold.K_VALUES, cold.METHODS
BLOCK_BYTES, STOP, Z = cold.BLOCK_BYTES, cold.STOP, 256
POLICY_PATH = ROOT / "python/moonkvsim/aegiskv/current/policy.py"
RUNTIME_PATH = ROOT / "python/moonkvsim/aegiskv/current/runtime.py"
VERIFY_CHECKPOINTS = {256, 4096, 8192, 31744, 32000, 32256}
LIFETIME_METHODS = {"decay_hysteresis", "cumulative_no_hysteresis", "uniform", "recency"}


def descending(counts, eligible):
    """Actual runtime rule: higher count, then earlier block position."""
    return sorted(range(eligible), key=lambda block: (-float(counts[block]), block))


def update_hysteresis(counts, old, k, eligible, epsilon):
    target = min(k, eligible)
    ranked = descending(counts, eligible)
    chosen = set(sorted((b for b in old if b < eligible), key=lambda b: (-counts[b], b))[:k])
    for candidate in ranked:
        if candidate in chosen:
            continue
        if len(chosen) < target:
            chosen.add(candidate)
        else:
            victim = max(chosen, key=lambda b: (-counts[b], b))
            if counts[candidate] > (1 + epsilon) * counts[victim]:
                chosen.remove(victim)
                chosen.add(candidate)
            else:
                # Remaining candidates cannot beat this unchanged weakest member.
                break
    assert len(chosen) == target
    return chosen


def load_chunk_counts(meta):
    """Deduplicate groups per query before summing exact completed chunks."""
    path = ROOT / meta["source_path"]
    assert sha(path) == meta["source_sha256"], path
    with np.load(path) as source:
        selected = source["selected_blocks"]
    assert list(selected.shape) == meta["source_shape"]
    assert selected.dtype == np.int16 and selected.min() >= -1
    assert selected.shape[1] >= STOP and selected.shape[0] == 2
    valid = selected >= 0
    assert np.all(valid.sum(axis=2) > 0)
    assert np.all((selected < 0) | (selected <= np.arange(selected.shape[1])[None, :, None] // 64))
    mask_check = None
    if meta["model"] == "NOSA-8B":
        mask_path = path.with_name(path.stem + "-mask.npz")
        with np.load(mask_path) as source:
            offset, actual = int(source["query_start"]), source["packed_mask"]
        tail = selected[:, offset : offset + actual.shape[1]]
        expected = np.zeros_like(actual)
        group, query, rank = np.nonzero(tail >= 0)
        block = tail[group, query, rank].astype(np.int64)
        np.bitwise_or.at(
            expected,
            (group, query, block // 64),
            np.left_shift(np.uint64(1), (block % 64).astype(np.uint64)),
        )
        assert np.array_equal(actual, expected)
        mask_check = {
            "path": str(mask_path.relative_to(ROOT)),
            "sha256": sha(mask_path),
            "query_range": [offset, offset + actual.shape[1]],
            "early_selector_queries_have_no_saved_packed_mask_identity_check": True,
        }
    selected = selected[:, :STOP]
    valid = selected >= 0
    query = np.broadcast_to(np.arange(STOP)[None, :, None], selected.shape)
    incidence = np.zeros((STOP, STOP // 64), dtype=bool)
    incidence[query[valid], selected[valid]] = True
    checks = (0, 1, 63, 255, 4095, 8191, 31743, 31999, 32256, STOP - 1)
    for index in checks:
        observed = selected[:, index].ravel()
        assert set(np.flatnonzero(incidence[index])) == set(observed[observed >= 0])
    counts = incidence.reshape(STOP // Z, Z, STOP // 64).sum(axis=1).astype(np.uint16)
    assert int(counts.max()) <= Z
    assert int(counts.sum()) == int(incidence.sum())
    return counts, {
        **meta,
        "captured_query_range": [0, meta["source_shape"][1]],
        "replayed_query_range": [0, STOP],
        "chunk_counts_shape": list(counts.shape),
        "cross_group_query_union_reference_indices": list(checks),
        "query_block_events": int(counts.sum()),
        "native_mask_identity": mask_check,
    }


def analyze_layer(chunks, meta, *, start_query=0, verify_runtime=True):
    """Past-only placement; oracle reads heldout future solely at evaluation."""
    assert chunks.shape == (127, 508) and chunks.dtype == np.uint16
    assert start_query in (0, 31744)
    rows, lifetime, runtime_checks = [], [], 0
    for k in K_VALUES:
        decayed = np.zeros(chunks.shape[1], dtype=np.float64)
        cumulative = np.zeros_like(decayed)
        placements = {method: set() for method in METHODS}
        entered_lifetime = {method: 0 for method in LIFETIME_METHODS}
        for checkpoint in range(start_query + Z, CHECKPOINTS[-1] + 1, Z):
            recent = chunks[checkpoint // Z - 1]
            decayed = (decayed + recent) * 0.9
            cumulative += recent
            eligible = checkpoint // 64
            future = chunks[checkpoint // Z, :eligible] if checkpoint in CHECKPOINTS else None
            for method in METHODS:
                if method not in LIFETIME_METHODS and checkpoint not in CHECKPOINTS:
                    continue
                old = placements[method]
                if method in ("decay_hysteresis", "cumulative_no_hysteresis"):
                    counts = decayed if method == "decay_hysteresis" else cumulative
                    epsilon = 0.1 if method == "decay_hysteresis" else 0.0
                    selected = update_hysteresis(counts, old, k, eligible, epsilon)
                    if verify_runtime and checkpoint in VERIFY_CHECKPOINTS:
                        expected = runtime_top_blocks(
                            {(0, b): float(counts[b]) for b in range(eligible)},
                            0,
                            eligible,
                            k,
                            incumbent=old,
                            hysteresis=epsilon,
                        )
                        assert selected == set(expected)
                        runtime_checks += 1
                elif method == "recency":
                    selected = set(range(max(0, eligible - k), eligible))
                elif method == "uniform":
                    selected = set(np.linspace(0, eligible - 1, min(k, eligible), dtype=int))
                elif method == "frequency_static":
                    selected = old.copy() if old else set(descending(cumulative, eligible)[:k])
                else:
                    assert method == "future_oracle" and future is not None
                    selected = set(descending(future, eligible)[:k])
                assert len(selected) == min(k, eligible) and max(selected) < eligible
                entering, evicted = selected - old, old - selected
                if method in LIFETIME_METHODS:
                    entered_lifetime[method] += len(entering)
                placements[method] = selected
                if checkpoint not in CHECKPOINTS:
                    continue
                demand = set(np.flatnonzero(future))
                covered = len(demand & selected)
                hits = int(future[list(selected)].sum())
                first = checkpoint == CHECKPOINTS[0]
                rows.append(
                    dict(
                        model=meta["model"],
                        book_id=meta["book_id"],
                        layer=meta["layer_one_based"],
                        checkpoint_tokens=checkpoint,
                        K=k,
                        method=method,
                        historical_blocks=eligible,
                        demanded_blocks=len(demand),
                        covered_blocks=covered,
                        missed_blocks=len(demand) - covered,
                        distinct_demand_coverage=covered / len(demand),
                        query_block_events=int(future.sum()),
                        covered_query_block_events=hits,
                        query_block_event_coverage=hits / int(future.sum()),
                        unique_miss_bytes=(len(demand) - covered) * BLOCK_BYTES,
                        initial_fill_bytes=k * BLOCK_BYTES if first else 0,
                        replacement_entering_bytes=0 if first else len(entering) * BLOCK_BYTES,
                        eviction_bytes=0 if first else len(evicted) * BLOCK_BYTES,
                        preceding_checkpoint_entering_bytes=len(entering) * BLOCK_BYTES,
                        selected_block_ids=" ".join(map(str, sorted(selected))),
                    )
                )
                if method in LIFETIME_METHODS:
                    lifetime.append(
                        dict(
                            model=meta["model"],
                            book_id=meta["book_id"],
                            layer=meta["layer_one_based"],
                            checkpoint_tokens=checkpoint,
                            K=k,
                            method=method,
                            query_start=start_query,
                            completed_counter_updates=(checkpoint - start_query) // Z,
                            cumulative_distinct_query_block_events=int(cumulative.sum()),
                            decayed_counter_sum=float(decayed.sum()),
                            initial_capacity_fill_bytes=k * BLOCK_BYTES,
                            lifetime_entering_bytes=entered_lifetime[method] * BLOCK_BYTES,
                            lifetime_replacement_entering_bytes=(entered_lifetime[method] - k)
                            * BLOCK_BYTES,
                        )
                    )
            if checkpoint in VERIFY_CHECKPOINTS:
                past = chunks[start_query // Z : checkpoint // Z]
                powers = np.power(0.9, np.arange(len(past), 0, -1))
                assert np.allclose(decayed, (past * powers[:, None]).sum(axis=0), atol=1e-9)
                assert np.array_equal(cumulative, past.sum(axis=0))
    groups = defaultdict(list)
    for row in rows:
        groups[row["checkpoint_tokens"], row["K"]].append(row)
    for group in groups.values():
        oracle = next(row for row in group if row["method"] == "future_oracle")
        assert oracle["covered_blocks"] == min(oracle["K"], oracle["demanded_blocks"])
        assert all(row["covered_blocks"] <= oracle["covered_blocks"] for row in group)
    return rows, lifetime, runtime_checks


def self_check():
    assert descending(np.array([0, 256, 1], dtype=np.uint16), 3) == [1, 2, 0]
    assert update_hysteresis(np.array([10.0, 11.0]), {0}, 1, 2, 0.1) == {0}
    assert update_hysteresis(np.array([10.0, 11.01]), {0}, 1, 2, 0.1) == {1}
    assert update_hysteresis(np.ones(4), set(), 2, 4, 0) == {0, 1}
    assert update_hysteresis(np.ones(4), {2, 3}, 2, 4, 0) == {2, 3}
    assert update_hysteresis(np.ones(4), set(), 64, 4, 0.1) == {0, 1, 2, 3}
    # A uniquely frequent early block must survive a weak most-recent chunk.
    chunks = np.zeros((127, 508), dtype=np.uint16)
    chunks[:, 0] = 256
    chunks[80:124, 300] = 256
    chunks[124:, 400] = 1
    meta = dict(model="test", book_id="test", layer_one_based=1)
    warm, _, _ = analyze_layer(chunks, meta)
    changed = chunks.copy()
    changed[125:] = 0
    changed[125:, 12] = 256
    alternate, _, _ = analyze_layer(changed, meta)
    for original, modified in zip(warm, alternate, strict=True):
        if original["method"] != "future_oracle" and original["checkpoint_tokens"] == 32000:
            assert original["selected_block_ids"] == modified["selected_block_ids"]
    reset, _, _ = analyze_layer(chunks, meta, start_query=31744)
    assert any(
        a["selected_block_ids"] != b["selected_block_ids"]
        for a, b in zip(warm, reset, strict=True)
        if a["method"] == "decay_hysteresis"
    )


def comparison_rows(warm, paired, legacy):
    keys = ("model", "K", "method", "first_L_layers")
    indexes = [{tuple(row[k] for k in keys): row for row in source} for source in (paired, legacy)]
    output = []
    for row in warm:
        key = tuple(row[k] for k in keys)
        result = {k: row[k] for k in keys}
        for metric in (
            "demand_weighted_coverage_mean",
            "event_weighted_coverage_mean",
            "total_replacement_entering_bytes_mean",
        ):
            reset, previous = (index[key][metric] for index in indexes)
            result["warm_" + metric] = row[metric]
            result["matched_cold_" + metric] = reset
            result["legacy_cold_" + metric] = previous
            result["lifetime_effect_" + metric] = row[metric] - reset
            result["tie_rule_effect_" + metric] = reset - previous
        output.append(result)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "native-topk-warm")
    parser.add_argument(
        "--single-case", action="store_true", help="Inspect first model/document/layer"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "AUDIT.json").exists():
        raise FileExistsError("Preserve published results; use another --output directory")
    self_check()
    manifest_path = BASE / "inputs/native-heldout-selector-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    cold_audit = json.loads((BASE / "native-topk/AUDIT.json").read_text())
    assert sha(manifest_path) == cold_audit["input_manifest_sha256"]
    policy_sha, runtime_sha = sha(POLICY_PATH), sha(RUNTIME_PATH)
    script_sha = sha(__file__)
    for relative, digest in manifest["references"].items():
        assert sha(ROOT / relative) == digest, relative
    capture_evidence = cold_audit["capture_provenance"]
    observer_paths = {
        "NOSA-8B": "20260921-concentration-nosa8b/capture_nosa8b.py",
        "NSA-8B": "20260921-concentration-new-models/capture_nsa.py",
        "MiniCPM4.1-8B": "20260921-concentration-new-models/capture_minicpm41_dual.py",
    }
    observer_evidence = {}
    for model, relative in observer_paths.items():
        path = ROOT / "benchmark/AegisKV/experiments/native-sparse" / relative
        digest = sha(path)
        assert digest == capture_evidence[model]["recorded_environment"]["script_sha256"]
        observer_evidence[model] = dict(path=str(path.relative_to(ROOT)), sha256=digest)
    for capture in capture_evidence.values():
        for record in capture["files"].values():
            assert sha(ROOT / record["path"]) == record["sha256"]
    protocol = dict(
        schema="moonkvsim.aegiskv.native_topk_complete_history.v1",
        evidence="CPU replay of native full causal prefill selections; no new model forwards",
        query_start=0,
        query_stop_exclusive=STOP,
        checkpoints=list(CHECKPOINTS),
        checkpoint_chunk_tokens=Z,
        physical_block_tokens=64,
        physical_raw_kv_block_bytes=BLOCK_BYTES,
        K=list(K_VALUES),
        first_L_layers=list(cold.DEPTHS),
        beta=0.9,
        epsilon=0.1,
        methods=list(METHODS),
        count_rule="per-query union across KV groups; at each checkpoint C=(C+new256)*beta",
        counter_updates_at_evaluation=[125, 126],
        placement_rule=(
            "update each checkpoint from 256; min(K, complete blocks); strict hysteresis"
        ),
        tie_rule="larger counter then earlier block index; equal candidates retain resident",
        deployed_policy=dict(path=str(POLICY_PATH.relative_to(ROOT)), sha256=policy_sha),
        deployed_runtime=dict(path=str(RUNTIME_PATH.relative_to(ROOT)), sha256=runtime_sha),
        runtime_comparison="independent reimplementation checked against actual runtime top_blocks",
        runtime_sample_checkpoints=sorted(VERIFY_CHECKPOINTS),
        frequency_static=(
            "rank full past cumulative frequency at M=32000, then freeze; not update-only ablation"
        ),
        cumulative_no_hysteresis="lifetime checkpoint evolution with beta=1,epsilon=0; strict ties",
        recency="last K complete historical blocks, every checkpoint",
        uniform="K evenly spaced complete historical blocks, every checkpoint",
        future_oracle="same-K future-frequency rank; maximum distinct coverage; future-aware",
        bytes=dict(
            units="logical raw-KV bytes; not physical traffic or latency",
            initial_fill_bytes="K-block capacity fill reported once at first evaluated checkpoint",
            replacement_entering_bytes="only set additions from evaluated M0=32000 to M1=32256",
            preceding_checkpoint_entering_bytes=(
                "current checkpoint set additions; includes M0 vs31744 for warm methods"
            ),
            lifetime="separate CSV; static/oracle have no continuously resident warmup placement",
        ),
        paired_cold_reset=dict(query_start=31744, tie_rule="same deployed earlier-index tie rule"),
        nosa_scope="native selectors for all q; saved packed-mask identity only q31680..32703",
        statistics=(
            "3 documents/model; document ratios first, then equal-document means and min/max; "
            "layers not n"
        ),
        limitations=[
            "PG19 documents, not Agent workload or measured recovery execution",
            "one full native sparse model forward; not rerun incremental/chunked model dispatch",
            "MiniCPM full request exceeds dense_len; short separate forwards can be dense",
            "continuous q0 lifecycle; deployment counts only protected/recovering requests",
            "excludes auxiliary state, compression branch, selector overhead, H2D latency and WCT",
            "two adjacent future256 windows and only three documents per model",
            "NOSA early selectors lack saved packed-mask identity validation",
        ],
        source_manifest_sha256=sha(manifest_path),
        frozen_cold_script_sha256=sha(_cold_path),
        script_sha256=script_sha,
        single_case=args.single_case,
    )
    write_json(args.output / "PROTOCOL.json", protocol)
    warm_rows, cold_rows, histories, source_checks, arrays = [], [], [], [], {}
    runtime_checks = 0
    metas = manifest["arrays"][:1] if args.single_case else manifest["arrays"]
    for index, meta in enumerate(metas):
        chunks, source_check = load_chunk_counts(meta)
        arrays[meta["key"]] = chunks
        source_checks.append(source_check)
        warm, lifetime, checks = analyze_layer(chunks, meta)
        reset, _, reset_checks = analyze_layer(chunks, meta, start_query=31744)
        warm_rows.extend(warm)
        cold_rows.extend(reset)
        histories.extend(lifetime)
        runtime_checks += checks + reset_checks
        if (index + 1) % 16 == 0:
            print(
                json.dumps(dict(layers=index + 1, total=len(metas), runtime_checks=runtime_checks)),
                flush=True,
            )
    write_csv(args.output / "layer-checkpoint-results.csv", warm_rows)
    write_csv(args.output / "paired-cold-reset-layer-checkpoint-results.csv", cold_rows)
    write_csv(args.output / "counter-lifetime-results.csv", histories)
    np.savez_compressed(args.output / "whole-history-chunk-counts.npz", **arrays)
    if not args.single_case:
        assert len(metas) == 288
        documents, summary = cold.aggregate(warm_rows)
        paired_documents, paired_summary = cold.aggregate(cold_rows)
        write_csv(args.output / "document-results.csv", documents)
        write_csv(args.output / "summary.csv", summary)
        write_json(args.output / "summary.json", summary)
        write_csv(args.output / "paired-cold-reset-document-results.csv", paired_documents)
        write_csv(args.output / "paired-cold-reset-summary.csv", paired_summary)
        write_json(args.output / "paired-cold-reset-summary.json", paired_summary)
        legacy_path = BASE / "native-topk/summary.json"
        assert sha(legacy_path) == cold_audit["result_sha256"]["summary.json"]
        write_csv(
            args.output / "warm-cold-tie-comparison.csv",
            comparison_rows(summary, paired_summary, json.loads(legacy_path.read_text())),
        )
    assert sha(POLICY_PATH) == policy_sha and sha(__file__) == script_sha
    write_json(
        args.output / "AUDIT.json",
        dict(
            source_manifest_sha256=sha(manifest_path),
            full_native_source_arrays=len(metas),
            source_audits=source_checks,
            capture_provenance=capture_evidence,
            observer_source_provenance=observer_evidence,
            runtime_top_blocks_equality_checks=runtime_checks,
            warm_counter_snapshots_independently_checked=(
                "closed-form decayed sum and full past sum at sampled checkpoints"
            ),
            independent_assertions=(
                "strict hysteresis; early capacity; deployed ties; future mutation invariance; "
                "same-budget oracle"
            ),
            native_mask_reconstructions=sum(
                row["native_mask_identity"] is not None for row in source_checks
            ),
            raw_warm_rows=len(warm_rows),
            raw_paired_cold_rows=len(cold_rows),
            lifetime_rows=len(histories),
            single_case=args.single_case,
            result_sha256={p.name: sha(p) for p in sorted(args.output.iterdir()) if p.is_file()},
        ),
    )
    print(
        json.dumps(dict(complete=True, layers=len(metas), runtime_checks=runtime_checks)),
        flush=True,
    )


if __name__ == "__main__":
    main()
