#!/usr/bin/env python3
"""Independently reconstruct transfer/ready evidence; never launch simulations."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    base = args.out.resolve()
    p, complete = read(base / "PROTOCOL.json"), read(base / "COMPLETE.json")
    for marker in (read(base / "PREPARED.json"), complete):
        for name, expected in marker["sha256"].items():
            assert sha(base / name) == expected, name
    assert complete["prepared_sha256"] == sha(base / "PREPARED.json")
    residents = {}
    with (base / "prepared-residency.csv").open() as stream:
        for row in csv.DictReader(stream):
            key = row["model"], row["book_id"], int(row["M"]), row["method"]
            residents.setdefault(key, set()).update(
                (int(row["layer"]) - 1, int(block)) for block in row["block_ids"].split()
            )
    future_cache = {}
    for doc in read(base / "INPUT_AUDIT.json")["documents"]:
        with np.load(base / doc["input"]) as data:
            future_cache[doc["model"], doc["book_id"]] = data["future"]
    with (base / "document-results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 864
    summaries, cases = {}, []
    observed_segments, zero_compute_checks = 0, 0
    for index, row in enumerate(rows):
        model, book = row["model"], row["book_id"]
        checkpoint, bandwidth, compute = (
            int(row[k]) for k in ("M", "bandwidth_GBps", "layer_compute_ns")
        )
        history = checkpoint // 64
        initial = residents[model, book, checkpoint, row["method"]]
        assert len(initial) == (0 if row["method"] == "DRAM" else 64)
        assert all(layer < 4 and 0 <= block < history for layer, block in initial)
        future = future_cache[model, book][:, checkpoint - 32000 : checkpoint - 32000 + 256]
        historical = future[:, :, :history]
        union = historical.any(axis=1)
        with np.load(base / row["trace"]) as data:
            query, layers, segments = data["queries"], data["layers"], data["transfer_segments"]
        assert query.shape == (32, 256, 7) and layers.shape == (32, 10)
        assert segments.ndim == 2 and segments.shape[1] == 7
        assert not len(segments) or (
            np.all(segments[:, 0] < 32)
            and np.all(segments[:, 1] < history)
            and np.all(segments[:, 2] < segments[:, 3])
            and np.all(segments[1:, 2] >= segments[:-1, 3])
            and np.all(segments[:, 4] == (segments[:, 3] - segments[:, 2]) * bandwidth)
        )
        served = np.zeros((32, history), dtype=np.int64)
        ready = np.full((32, history), -1, dtype=np.int64)
        for layer, block in initial:
            ready[layer, block] = 0
        if len(segments):
            np.add.at(served, (segments[:, 0], segments[:, 1]), segments[:, 4])
            finishes = segments[segments[:, 6] == 1]
            assert len({tuple(x) for x in finishes[:, :2]}) == len(finishes)
            ready[finishes[:, 0], finishes[:, 1]] = finishes[:, 3]
            assert np.all(served[finishes[:, 0], finishes[:, 1]] == 65536)
        assert np.all((served >= 0) & (served <= 65536))
        assert all(served[layer, block] == 0 for layer, block in initial)
        assert np.all(ready[union] >= 0)
        transferred = int(served.sum())
        partial = (served > 0) & (served < 65536)
        assert transferred == int(row["transferred_bytes"])
        assert int(served[~union].sum()) == int(row["transferred_but_not_demanded_bytes"])
        assert int(served[partial].sum()) == int(row["partial_transfer_bytes_at_stop"])
        assert int((65536 - served[partial]).sum()) == int(
            row["canceled_unfinished_object_remaining_bytes"]
        )
        assert 32 * history * 65536 == (
            transferred + len(initial) * 65536 + int(row["not_transferred_checkpoint_bytes"])
        )
        assert int(union.sum()) * 65536 == int(row["demanded_unique_bytes"])
        assert sum(bool(union[layer_id, b]) for layer_id, b in initial) * 65536 == int(
            row["resident_demanded_bytes"]
        )
        assert layers[0, 0] == 0 and np.array_equal(layers[1:, 0], layers[:-1, 3])
        assert layers[-1, 3] == int(row["raw_component_finish_ns"])
        assert layers[:, 4].sum() == int(row["exposed_wait_ns"])
        assert layers[-1, 3] == 32 * compute + layers[:, 4].sum()
        bytes_by_layer = np.zeros(32, dtype=np.int64)
        if len(segments):
            transfer_layer = np.searchsorted(layers[:, 3], segments[:, 2], side="right")
            assert np.all(transfer_layer < 32)
            assert np.all(segments[:, 3] <= layers[transfer_layer, 3])
            np.add.at(bytes_by_layer, transfer_layer, segments[:, 4])
            urgent = segments[segments[:, 5] == 1]
            assert np.all(union[urgent[:, 0], urgent[:, 1]])
            assert np.all(urgent[:, 2] >= layers[urgent[:, 0], 0])
        assert np.array_equal(bytes_by_layer, layers[:, 9])
        for layer in range(32):
            entry, all_ready, hit_compute, done, wait, needed, missing, hits, references, _ = (
                layers[layer]
            )
            at_entry = (ready[layer] >= 0) & (ready[layer] <= entry)
            history_counts = historical[layer].sum(axis=1)
            local = future[layer, :, history:].sum(axis=1)
            hit_counts = historical[layer, :, at_entry].sum(axis=0)
            # NumPy advanced indexing makes the selected blocks the leading dimension.
            expected_ready = np.maximum(
                entry, np.where(historical[layer], ready[layer][None, :], entry).max(axis=1)
            )
            assert np.all(query[layer, :, 0] == entry)
            assert np.array_equal(query[layer, :, 1], expected_ready)
            assert np.array_equal(query[layer, :, 2], expected_ready - entry)
            assert np.array_equal(query[layer, :, 3], history_counts)
            assert np.array_equal(query[layer, :, 4], local)
            assert np.array_equal(query[layer, :, 5], hit_counts)
            assert np.array_equal(query[layer, :, 6], history_counts - hit_counts)
            assert hits == int(hit_counts.sum() + local.sum())
            assert references == int(future[layer].sum())
            assert hit_compute == compute * hits // references
            assert all_ready == max(entry, int(ready[layer, union[layer]].max()))
            assert wait == max(0, all_ready - entry - hit_compute)
            assert done == entry + compute + wait
            assert needed == int(union[layer].sum())
            assert missing == int((union[layer] & ~at_entry).sum())
        assert np.isclose(query[:, :, 2].mean(), float(row["query_ready_wait_mean_ns"]))
        assert query[:, :, 2].max() == int(row["query_ready_wait_max_ns"])
        if compute == 0:
            zero_compute_checks += 1
            bytes_needed = int(row["demanded_unique_bytes"]) - int(row["resident_demanded_bytes"])
            assert transferred == bytes_needed
            assert layers[-1, 3] == bytes_needed // bandwidth
            assert int(row["transferred_but_not_demanded_bytes"]) == 0
        key = model, book, checkpoint, row["method"], bandwidth, compute
        assert key not in summaries
        summaries[key] = row
        cases.append(
            dict(
                model=model,
                book=book,
                M=checkpoint,
                method=row["method"],
                bandwidth_GBps=bandwidth,
                layer_compute_ns=compute,
                transfer_segments=len(segments),
                status="PASS",
            )
        )
        observed_segments += len(segments)
        if (index + 1) % 96 == 0:
            print("Independent transfer/ready audit", index + 1, "/", len(rows), flush=True)
    for key, row in summaries.items():
        model, book, checkpoint, _, bandwidth, compute = key
        base_row = summaries[model, book, checkpoint, "DRAM", bandwidth, compute]
        assert int(row["gain_vs_dram_ns"]) == (
            int(base_row["raw_component_finish_ns"]) - int(row["raw_component_finish_ns"])
        )
        assert int(row["bytes_saved_vs_dram"]) == (
            int(base_row["transferred_bytes"]) - int(row["transferred_bytes"])
        )
        assert row["background_order_sha256"] == base_row["background_order_sha256"]
    result = dict(
        status="PASS",
        cases=len(cases),
        query_rows=len(cases) * 32 * 256,
        layer_rows=len(cases) * 32,
        transfer_segments=observed_segments,
        exact_zero_compute_byte_time_checks=zero_compute_checks,
        imports_simulation_engine=False,
        simulations_run=0,
        complete_sha256=sha(base / "COMPLETE.json"),
        protocol_sha256=sha(base / "PROTOCOL.json"),
        auditor_sha256=sha(__file__),
        negative_results_retained=True,
        assumptions=p["limitations"],
        cases_detail=cases,
    )
    (base / "INDEPENDENT_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
