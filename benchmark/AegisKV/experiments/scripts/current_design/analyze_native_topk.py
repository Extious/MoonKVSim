#!/usr/bin/env python3
"""Causal Top-K diagnostics on pinned native selectors; no runtime/WCT claims."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
METHODS = (
    "decay_hysteresis",
    "cumulative_no_hysteresis",
    "frequency_static",
    "uniform",
    "recency",
    "future_oracle",
)
START, STOP = 31744, 32512
CHECKPOINTS = (32000, 32256)
K_VALUES = (4, 16, 64)
DEPTHS = (1, 4, 8, 32)
BLOCK_BYTES = 64 * 2 * 2 * 128 * 2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def descending(counts, eligible):
    """Highest counter first; ties favor recent blocks, deterministically."""
    return sorted(range(eligible), key=lambda index: (counts[index], index), reverse=True)


def update_hysteresis(counts, old, k, eligible, epsilon):
    chosen = {index for index in old if index < eligible}
    ranked = descending(counts, eligible)
    for index in ranked:
        if len(chosen) == k:
            break
        chosen.add(index)
    for candidate in ranked:
        if candidate in chosen:
            continue
        victim = min(chosen, key=lambda index: (counts[index], index))
        if counts[candidate] > (1 + epsilon) * counts[victim]:
            chosen.remove(victim)
            chosen.add(candidate)
    assert len(chosen) == k
    return chosen


def extract_inputs(source_metadata, destination):
    """Recreate compact cross-head incidence from immutable native recordings."""
    metadata = json.loads(source_metadata.read_text())
    source_hashes = json.loads((source_metadata.parent / "source-sha256.json").read_text())
    arrays, rows, references, token_ref = {}, [], {}, {}
    for model, info in metadata.items():
        folder = Path(info["capture_folder"])
        for book in ("10146", "10321", "10356"):
            directories = list((folder / "traces").glob(f"pg19-{book}-M*-N512"))
            assert len(directories) == 1
            directory = directories[0]
            run_path = directory / "run.json"
            run = json.loads(run_path.read_text())
            assert sha(run_path) == source_hashes[str(run_path.relative_to(ROOT))]
            input_path = directory / "input_ids.npy"
            ids = np.load(input_path)[:32704]
            token_ref.setdefault(book, ids)
            assert np.array_equal(ids, token_ref[book])
            references[str(input_path.relative_to(ROOT))] = sha(input_path)
            for layer in run["layers"]:
                path = folder / layer["trace_file"]
                digest = sha(path)
                assert digest == layer["trace_sha256"]
                assert digest == source_hashes[str(path.relative_to(ROOT))]
                with np.load(path) as archive:
                    selected = archive["selected_blocks"][:, START:STOP, :]
                assert selected.shape[:2] == (2, STOP - START)
                assert np.all(
                    (selected < 0) | (selected <= (np.arange(START, STOP) // 64)[None, :, None])
                )
                valid = selected >= 0
                query = np.broadcast_to(np.arange(STOP - START)[None, :, None], selected.shape)
                incidence = np.zeros((STOP - START, STOP // 64), dtype=bool)
                incidence[query[valid], selected[valid]] = True
                for index in (0, 1, 63, 255, 256, 511, 512, 767):
                    values = selected[:, index].ravel()
                    assert set(np.flatnonzero(incidence[index])) == set(values[values >= 0])
                identity_check = "native_kernel_indices_equal_selected_blocks"
                if model == "NOSA-8B":
                    assert layer["native_mask_equals_selected_blocks"]
                    lo, hi = layer["native_mask_checked_query_range"]
                    assert lo <= START and hi >= STOP
                    mask_path = directory / f"layer-{layer['layer_zero_based'] + 1:02d}-mask.npz"
                    with np.load(mask_path) as mask:
                        offset = int(mask["query_start"])
                        actual = mask["packed_mask"][:, START - offset : STOP - offset]
                    reconstructed = np.zeros_like(actual)
                    head, position, rank = np.nonzero(valid)
                    block = selected[head, position, rank].astype(np.int64)
                    np.bitwise_or.at(
                        reconstructed,
                        (head, position, block // 64),
                        np.left_shift(np.uint64(1), (block % 64).astype(np.uint64)),
                    )
                    assert np.array_equal(actual, reconstructed)
                    references[str(mask_path.relative_to(ROOT))] = sha(mask_path)
                    identity_check = "packed_native_mask_reconstructed_equal_for_entire_crop"
                else:
                    assert layer[identity_check]
                key = f"{model.replace('.', '_')}__{book}__layer{layer['layer_zero_based'] + 1:02d}"
                arrays[key] = incidence
                rows.append(
                    dict(
                        key=key,
                        model=model,
                        book_id=book,
                        layer_one_based=layer["layer_zero_based"] + 1,
                        source_path=str(path.relative_to(ROOT)),
                        source_sha256=digest,
                        native_identity_check=identity_check,
                        shape=list(incidence.shape),
                        source_shape=layer["selection_shape"],
                    )
                )
            references[str(run_path.relative_to(ROOT))] = sha(run_path)
    destination.mkdir(parents=True, exist_ok=True)
    artifact = destination / "native-heldout-selector-windows.npz"
    np.savez_compressed(artifact, **arrays)
    manifest = dict(
        schema="moonkvsim.aegiskv.native_selector_windows.v1",
        artifact=dict(path=str(artifact.relative_to(ROOT)), sha256=sha(artifact)),
        provenance=metadata,
        source_metadata=dict(
            path=str(source_metadata.relative_to(ROOT)), sha256=sha(source_metadata)
        ),
        source_summary=dict(
            path=str((source_metadata.parent / "source-sha256.json").relative_to(ROOT)),
            sha256=sha(source_metadata.parent / "source-sha256.json"),
        ),
        references=references,
        arrays=rows,
        audit=dict(
            layer_document_model_arrays=len(rows),
            token_inputs_equal_across_three_models_through=32704,
            source_hashes_verified=True,
            causal_indices_verified=True,
            cross_group_union_reference_checked=True,
            nosa_native_mask_arrays_rechecked=96,
            new_model_forwards=0,
            kernel_timings_available=False,
        ),
    )
    write_json(destination / "native-heldout-selector-manifest.json", manifest)
    return manifest


def analyze_layer(incidence, metadata):
    assert incidence.shape == (768, 508) and incidence.dtype == np.bool_
    raw_rows = []
    for k in K_VALUES:
        counters = {method: np.zeros(508, dtype=float) for method in METHODS}
        placements = {method: set() for method in METHODS}
        for checkpoint_index, checkpoint in enumerate(CHECKPOINTS):
            offset = checkpoint - START
            historical_blocks = checkpoint // 64
            # Submission at this checkpoint sees completed queries only.
            recent = incidence[offset - 256 : offset].sum(axis=0)
            future = incidence[offset : offset + 256, :historical_blocks]
            future_counts = future.sum(axis=0)
            demand = set(np.flatnonzero(future_counts))
            for method in METHODS:
                old = placements[method]
                counters[method] += recent
                counters[method] *= 0.9 if method == "decay_hysteresis" else 1.0
                if method == "decay_hysteresis":
                    selected = update_hysteresis(counters[method], old, k, historical_blocks, 0.1)
                elif method == "frequency_static" and checkpoint_index:
                    selected = old.copy()
                elif method == "cumulative_no_hysteresis":
                    selected = update_hysteresis(counters[method], old, k, historical_blocks, 0.0)
                elif method == "frequency_static":
                    selected = set(descending(counters[method], historical_blocks)[:k])
                elif method == "uniform":
                    selected = set(np.linspace(0, historical_blocks - 1, k, dtype=int).tolist())
                elif method == "recency":
                    selected = set(range(historical_blocks - k, historical_blocks))
                else:
                    assert method == "future_oracle"
                    selected = set(descending(future_counts, historical_blocks)[:k])
                assert len(selected) == k and max(selected) < historical_blocks
                covered = len(demand & selected)
                entered, evicted = selected - old, old - selected
                event_hits = int(future_counts[list(selected)].sum())
                raw_rows.append(
                    dict(
                        model=metadata["model"],
                        book_id=metadata["book_id"],
                        layer=metadata["layer_one_based"],
                        checkpoint_tokens=checkpoint,
                        K=k,
                        method=method,
                        historical_blocks=historical_blocks,
                        demanded_blocks=len(demand),
                        covered_blocks=covered,
                        missed_blocks=len(demand) - covered,
                        distinct_demand_coverage=covered / len(demand),
                        query_block_events=int(future_counts.sum()),
                        covered_query_block_events=event_hits,
                        query_block_event_coverage=event_hits / int(future_counts.sum()),
                        unique_miss_bytes=(len(demand) - covered) * BLOCK_BYTES,
                        initial_fill_bytes=len(entered) * BLOCK_BYTES
                        if checkpoint_index == 0
                        else 0,
                        replacement_entering_bytes=len(entered) * BLOCK_BYTES
                        if checkpoint_index
                        else 0,
                        eviction_bytes=len(evicted) * BLOCK_BYTES,
                        selected_block_ids=" ".join(map(str, sorted(selected))),
                    )
                )
                placements[method] = selected
    # Oracle is an equal-byte upper bound on distinct historical demand coverage.
    groups = defaultdict(list)
    for row in raw_rows:
        groups[row["checkpoint_tokens"], row["K"]].append(row)
    for rows in groups.values():
        oracle = next(row for row in rows if row["method"] == "future_oracle")
        assert oracle["covered_blocks"] == min(oracle["K"], oracle["demanded_blocks"])
        assert all(row["covered_blocks"] <= oracle["covered_blocks"] for row in rows)
    return raw_rows


def aggregate(rows):
    grouped = defaultdict(list)
    for row in rows:
        for depth in DEPTHS:
            if row["layer"] <= depth:
                grouped[row["model"], row["book_id"], row["K"], row["method"], depth].append(row)
    documents = []
    for (model, book, k, method, depth), group in grouped.items():
        assert len(group) == depth * len(CHECKPOINTS)
        documents.append(
            dict(
                model=model,
                book_id=book,
                K=k,
                method=method,
                first_L_layers=depth,
                checkpoint_observations=len(CHECKPOINTS),
                macro_layer_checkpoint_coverage=float(
                    np.mean([r["distinct_demand_coverage"] for r in group])
                ),
                demand_weighted_coverage=sum(r["covered_blocks"] for r in group)
                / sum(r["demanded_blocks"] for r in group),
                event_weighted_coverage=sum(r["covered_query_block_events"] for r in group)
                / sum(r["query_block_events"] for r in group),
                total_unique_miss_bytes=sum(r["unique_miss_bytes"] for r in group),
                total_initial_fill_bytes=sum(r["initial_fill_bytes"] for r in group),
                total_replacement_entering_bytes=sum(
                    r["replacement_entering_bytes"] for r in group
                ),
                total_eviction_bytes=sum(r["eviction_bytes"] for r in group),
            )
        )
    summaries = []
    keys = {
        tuple(row[key] for key in ("model", "K", "method", "first_L_layers")) for row in documents
    }
    for model, k, method, depth in sorted(keys):
        group = [
            row
            for row in documents
            if (row["model"], row["K"], row["method"], row["first_L_layers"])
            == (model, k, method, depth)
        ]
        assert len(group) == 3
        summary = dict(model=model, K=k, method=method, first_L_layers=depth, documents=3)
        for metric in (
            "macro_layer_checkpoint_coverage",
            "demand_weighted_coverage",
            "event_weighted_coverage",
            "total_unique_miss_bytes",
            "total_initial_fill_bytes",
            "total_replacement_entering_bytes",
        ):
            values = [row[metric] for row in group]
            summary[metric + "_mean"] = float(np.mean(values))
            summary[metric + "_min"] = min(values)
            summary[metric + "_max"] = max(values)
        summaries.append(summary)
    return documents, summaries


def self_check():
    # Strict relative hysteresis: equality never replaces a held block.
    assert update_hysteresis(np.array([10.0, 11.0]), {0}, 1, 2, 0.1) == {0}
    assert update_hysteresis(np.array([10.0, 11.01]), {0}, 1, 2, 0.1) == {1}
    incidence = np.zeros((768, 508), dtype=bool)
    incidence[:256, 3] = True
    incidence[256:512, 91] = True
    incidence[512:, 22] = True
    meta = dict(model="test", book_id="test", layer_one_based=1)
    rows = analyze_layer(incidence, meta)
    first = next(
        row
        for row in rows
        if row["method"] == "decay_hysteresis"
        and row["K"] == 4
        and row["checkpoint_tokens"] == 32000
    )
    assert 3 in map(int, first["selected_block_ids"].split())
    assert 91 not in map(int, first["selected_block_ids"].split())
    assert first["covered_blocks"] == 0  # future access never leaks into past rank
    assert next(row for row in rows if row["method"] == "future_oracle")["covered_blocks"] == 1
    changed = incidence.copy()
    changed[256:] = False
    changed[256:, 4] = True
    alternate = analyze_layer(changed, meta)
    for original, modified in zip(rows, alternate, strict=True):
        if original["method"] != "future_oracle" and original["checkpoint_tokens"] == 32000:
            assert original["selected_block_ids"] == modified["selected_block_ids"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "native-topk")
    parser.add_argument("--rebuild-inputs", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    input_manifest = BASE / "inputs/native-heldout-selector-manifest.json"
    if args.rebuild_inputs:
        extract_inputs(
            ROOT
            / "benchmark/AegisKV/experiments/data/kv-access-concentration-8b-20260921"
            / "model-provenance.json",
            BASE / "inputs",
        )
    manifest = json.loads(input_manifest.read_text())
    artifact = ROOT / manifest["artifact"]["path"]
    assert sha(artifact) == manifest["artifact"]["sha256"]
    capture_evidence = {}
    for model, provenance in manifest["provenance"].items():
        folder = Path(provenance["capture_folder"])
        files = {
            name: folder / name
            for name in (
                "measured-environment.json",
                "measured-loading.json",
                "measured-observer-validation.json",
            )
        }
        environment = json.loads(files["measured-environment.json"].read_text())
        loading = json.loads(files["measured-loading.json"].read_text())
        observer = json.loads(files["measured-observer-validation.json"].read_text())
        assert environment["revision"] == provenance["revision"]
        assert all(
            not loading[key] for key in ("missing_keys", "unexpected_keys", "mismatched_keys")
        )
        assert observer["paired_forward_max_abs_logit_diff"] == 0.0
        capture_evidence[model] = {
            "files": {
                name: {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}
                for name, path in files.items()
            },
            "recorded_environment": environment,
            "weight_verification_scope": "recorded capture-time manifests; no new model download",
        }
    self_check()
    protocol = dict(
        evidence="CPU causal replay of observed native selector indices, no new model forwards",
        query_start=START,
        query_stop_exclusive=STOP,
        checkpoints=list(CHECKPOINTS),
        checkpoint_chunk_tokens=256,
        physical_block_tokens=64,
        physical_raw_kv_block_bytes=BLOCK_BYTES,
        K=list(K_VALUES),
        first_L_layers=list(DEPTHS),
        beta=0.9,
        epsilon=0.1,
        methods=list(METHODS),
        cumulative_ablation=(
            "same strict admission with beta=1 and epsilon=0; equal counts retain residents"
        ),
        counter_initialization="zero at query31744; first256 queries warmup",
        update=(
            "counts += just-completed256-query cross-group unions; "
            "multiply by beta; rank once at checkpoint"
        ),
        selection=(
            "eligible complete historical blocks only; strict > (1+epsilon)*victim for replacement"
        ),
        uniform="K evenly spaced historical block positions; deterministic",
        oracle=(
            "future-aware same-K maximum distinct coverage; "
            "tie-order prioritizes future query frequency"
        ),
        tie_break="larger block position",
        synthetic_token_ids=False,
        source_manifest_sha256=sha(input_manifest),
        script_sha256=sha(Path(__file__)),
        uncertainty=(
            "min/max over 3 documents; correlated layers/checkpoints never independent samples"
        ),
        bytes=(
            "logical unique raw-KV footprints only; "
            "excludes selector/auxiliary metadata, headers and transfers in flight"
        ),
        limitations=[
            "PG19 literature, not Agent workloads",
            "native causal prefill selectors, not measured recovery execution",
            "two adjacent heldout windows after a short warm start",
            "three documents per model",
            "no H2D bandwidth, overlap, latency or WCT claim",
            "counter/scatter-add overhead not measured",
        ],
    )
    # Freeze the protocol on disk before reading any outcome.
    write_json(args.output / "PROTOCOL.json", protocol)
    rows = []
    with np.load(artifact) as archive:
        for meta in manifest["arrays"]:
            source = ROOT / meta["source_path"]
            assert sha(source) == meta["source_sha256"]
            rows.extend(analyze_layer(archive[meta["key"]], meta))
    documents, summary = aggregate(rows)
    write_csv(args.output / "layer-checkpoint-results.csv", rows)
    write_csv(args.output / "document-results.csv", documents)
    write_csv(args.output / "summary.csv", summary)
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "AUDIT.json",
        dict(
            input_manifest_sha256=sha(input_manifest),
            input_array_sha256=sha(artifact),
            source_arrays_verified=288,
            layer_checkpoint_rows=len(rows),
            document_rows=len(documents),
            model_K_method_depth_summaries=len(summary),
            native_selector_inputs=manifest["audit"],
            independent_documents_per_model=3,
            full_manifest=manifest,
            capture_provenance=capture_evidence,
            independent_assertions=(
                "strict hysteresis boundary, no-future-leak constructed case, "
                "per-layer same-budget oracle bound, all-byte counts and full document cardinality"
            ),
            result_sha256={
                name: sha(args.output / name)
                for name in (
                    "layer-checkpoint-results.csv",
                    "document-results.csv",
                    "summary.csv",
                    "summary.json",
                )
            },
        ),
    )
    print(
        json.dumps(dict(layer_rows=len(rows), document_rows=len(documents), summaries=len(summary)))
    )


if __name__ == "__main__":
    main()
