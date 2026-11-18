#!/usr/bin/env python3
"""Read sealed native raw-KV results; pair and summarize, without simulator imports."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parents[1] / "native-transfer-postreview-v2"
EXPECTED_DELIVERY = "94917e6157bda55e25e5ba95f3e9e31ca542a107a566d7a1cfd59460234d1cad"
MODELS = ("NOSA-8B", "NSA-8B", "MiniCPM4.1-8B")
BOOKS = ("10146", "10321", "10356")
CHECKPOINTS = (32000, 32256)
BANDWIDTHS = (8, 16, 32)
COMPUTE = (0, 25600, 256000, 2560000)
METHODS = ("DRAM", "Current", "Recency", "Oracle")
COMPARATORS = ("DRAM", "Recency", "Oracle")
KEYS = ("model", "book_id", "M", "bandwidth_GBps", "layer_compute_ns")
INTEGER_KEYS = set(KEYS[2:])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def csv_read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def csv_write(name, rows):
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def key(row):
    return tuple(int(row[k]) if k in INTEGER_KEYS else row[k] for k in KEYS)


def signs(values):
    values = list(values)
    count = Counter("positive" if v > 0 else "negative" if v < 0 else "zero" for v in values)
    return {"pairs": len(values), **{k: count[k] for k in ("positive", "zero", "negative")}}


def main():
    assert sha(SOURCE / "DELIVERY.json") == EXPECTED_DELIVERY
    delivery = read(SOURCE / "DELIVERY.json")
    assert delivery["status"] == "PASS" and delivery["numerical_matrix_complete"]
    for relative, digest in delivery["sha256"].items():
        assert sha(SOURCE / relative) == digest, relative
    seal_counts = {}
    for name in ("COMPLETE.json", "PREPARED.json"):
        seal = read(SOURCE / name)
        for relative, digest in seal["sha256"].items():
            assert delivery["sha256"][relative] == digest
        seal_counts[name] = len(seal["sha256"])
    manifest = read(SOURCE / "MANIFEST.json")
    for relative, digest in manifest["source_sha256"].items():
        assert delivery["sha256"]["source_snapshot/" + relative] == digest
    protocol = read(SOURCE / "PROTOCOL.json")
    assert tuple(protocol["models"]) == MODELS
    assert tuple(protocol["documents"]) == BOOKS
    assert tuple(protocol["M"]) == CHECKPOINTS
    assert tuple(protocol["bandwidth_GBps"]) == BANDWIDTHS
    assert tuple(protocol["layer_compute_ns"]) == COMPUTE
    assert tuple(protocol["methods"]) == METHODS
    assert protocol["scenarios"] == 864

    rows = csv_read(SOURCE / "document-results.csv")
    assert len(rows) == 864
    by_key = {}
    for row in rows:
        identity = (*key(row), row["method"])
        assert identity not in by_key
        by_key[identity] = row
        trace = SOURCE / row["trace"]
        result_path = trace.with_suffix(".json")
        marker = read(trace.with_suffix(".complete.json"))
        result = read(result_path)
        assert marker["result_sha256"] == sha(result_path)
        assert marker["trace_sha256"] == row["trace_sha256"] == sha(trace)
        assert marker["prepared_sha256"] == row["prepared_sha256"] == sha(SOURCE / "PREPARED.json")
        for field, value in result.items():
            if isinstance(value, (int, float)):
                assert Decimal(row[field]) == Decimal(str(value)), (identity, field)
            else:
                assert row[field] == value, (identity, field)
        assert marker["identity"] == {
            field: result[field] for field in (*KEYS, "method", "background_order_sha256")
        }
        assert int(row["assumed_compute_ns"]) == 32 * int(row["layer_compute_ns"])
        assert int(row["raw_component_finish_ns"]) == (
            int(row["exposed_wait_ns"]) + int(row["assumed_compute_ns"])
        )
    expected = set(itertools.product(MODELS, BOOKS, CHECKPOINTS, BANDWIDTHS, COMPUTE, METHODS))
    assert set(by_key) == expected
    base_keys = list(itertools.product(MODELS, BOOKS, CHECKPOINTS, BANDWIDTHS, COMPUTE))
    paired = []
    for identity in base_keys:
        variants = {method: by_key[(*identity, method)] for method in METHODS}
        assert len({r["background_order_sha256"] for r in variants.values()}) == 1
        assert len({r["demanded_unique_bytes"] for r in variants.values()}) == 1
        for row in variants.values():
            assert int(row["gain_vs_dram_ns"]) == (
                int(variants["DRAM"]["raw_component_finish_ns"])
                - int(row["raw_component_finish_ns"])
            )
            assert int(row["bytes_saved_vs_dram"]) == (
                int(variants["DRAM"]["transferred_bytes"]) - int(row["transferred_bytes"])
            )
        record = dict(zip(KEYS, identity, strict=True))
        record["layer_compute_us"] = identity[-1] / 1000
        for method in METHODS:
            record[f"{method.lower()}_finish_ns"] = int(variants[method]["raw_component_finish_ns"])
        for comparator in COMPARATORS:
            field = comparator.lower() + "_minus_current_ns"
            record[field] = record[comparator.lower() + "_finish_ns"] - record["current_finish_ns"]
            assert record[field] == (
                int(variants[comparator]["exposed_wait_ns"])
                - int(variants["Current"]["exposed_wait_ns"])
            )
        paired.append(record)
    assert len(paired) == 216
    previous_pairs = csv_read(SOURCE / "paired-comparisons.csv")
    old_by_key = {key(row): row for row in previous_pairs}
    assert len(old_by_key) == len(previous_pairs) == len(paired)
    for row in paired:
        old = old_by_key[key(row)]
        for comparator in COMPARATORS:
            assert row[comparator.lower() + "_minus_current_ns"] == int(
                old["current_gain_vs_" + comparator.lower() + "_ns"]
            )

    # Exactly two checkpoint differences per document; keep integer sums for exact audit.
    documents = []
    pair_index = {key(row): row for row in paired}
    for model, book, bw, compute in itertools.product(MODELS, BOOKS, BANDWIDTHS, COMPUTE):
        pair = [pair_index[model, book, m, bw, compute] for m in CHECKPOINTS]
        record = dict(
            model=model,
            book_id=book,
            bandwidth_GBps=bw,
            layer_compute_us=compute / 1000,
            checkpoints_per_document=2,
        )
        for comparator in COMPARATORS:
            field = comparator.lower() + "_minus_current"
            total_ns = sum(r[field + "_ns"] for r in pair)
            record[field + "_checkpoint_sum_ns"] = total_ns
            record[field + "_us"] = float(Fraction(total_ns, 2000))
        documents.append(record)
    assert len(documents) == 108

    aggregated = []
    for model, bw, compute in itertools.product(MODELS, BANDWIDTHS, COMPUTE):
        group = [
            r
            for r in documents
            if (r["model"], r["bandwidth_GBps"], r["layer_compute_us"])
            == (model, bw, compute / 1000)
        ]
        assert {r["book_id"] for r in group} == set(BOOKS) and len(group) == 3
        record = dict(
            model=model,
            bandwidth_GBps=bw,
            layer_compute_us=compute / 1000,
            documents=3,
            checkpoints_per_document=2,
        )
        for comparator in COMPARATORS:
            field = comparator.lower() + "_minus_current"
            doc_values = [Fraction(r[field + "_checkpoint_sum_ns"], 2000) for r in group]
            record[field + "_six_checkpoint_sum_ns"] = sum(
                r[field + "_checkpoint_sum_ns"] for r in group
            )
            record[field + "_mean_us"] = float(sum(doc_values) / 3)
            record[field + "_min_us"] = float(min(doc_values))
            record[field + "_max_us"] = float(max(doc_values))
            for sign, count in signs(doc_values).items():
                record[field + "_doc_" + sign] = count
        aggregated.append(record)
    assert len(aggregated) == 36

    counts = {}
    for model in MODELS:
        counts[model] = {}
        for comparator in COMPARATORS:
            field = comparator.lower() + "_minus_current"
            original = signs(r[field + "_ns"] for r in paired if r["model"] == model)
            sealed = read(SOURCE / "REPORT_PROVENANCE.json")["sign_counts"][model][
                comparator.lower()
            ]
            assert (original["positive"], original["zero"], original["negative"]) == (
                sealed["faster"],
                sealed["equal"],
                sealed["slower"],
            )
            counts[model][comparator] = {
                "unpooled_document_checkpoint_conditions": original,
                "checkpoint_averaged_document_conditions": signs(
                    r[field + "_checkpoint_sum_ns"] for r in documents if r["model"] == model
                ),
                "three_document_mean_conditions": signs(
                    r[field + "_six_checkpoint_sum_ns"] for r in aggregated if r["model"] == model
                ),
            }
    csv_write("checkpoint-pairs.csv", paired)
    csv_write("document-checkpoint-means.csv", documents)
    csv_write("model-bandwidth-compute-summary.csv", aggregated)
    csv_write("paper-32GBps-summary.csv", [r for r in aggregated if r["bandwidth_GBps"] == 32])
    write_json("SIGN_COUNTS.json", counts)
    write_json(
        "SOURCE_AUDIT.json",
        {
            "status": "PASS",
            "source": str(SOURCE),
            "delivery_sha256": EXPECTED_DELIVERY,
            "delivery_files_rehashed": len(delivery["sha256"]),
            "nested_seal_counts": seal_counts,
            "csv_rows_matched_fieldwise_to_case_json": len(rows),
            "matched_case_trace_and_identity_bindings": len(rows),
            "existing_paired_rows_independently_reproduced": len(paired),
            "new_simulations": 0,
            "source_files_modified": False,
            "model_document_checkpoints_methods_bandwidth_compute": [3, 3, 2, 4, 3, 4],
            "method_runs": 864,
            "matched_four_method_conditions": 216,
            "comparator_contrasts_before_checkpoint_averaging": 648,
            "checkpoint_averaged_document_conditions": 108,
            "model_bandwidth_compute_conditions": 36,
            "documents_per_model": 3,
            "distinct_books_across_models": 3,
            "statistical_unit": (
                "PG19 document, conditional on model; models reuse the same three documents."
            ),
            "aggregation": (
                "First comparator minus Current at identical model/book/M/BW/compute; "
                "equal mean of two checkpoints within a document; then equal three-document "
                "mean/min/max. Range is among document checkpoint-means, "
                "not a CI or six raw-checkpoint extremes."
            ),
            "positive_difference": (
                "Current has lower raw component finish time; negative means comparator is faster."
            ),
            "precision": (
                "Integer nanoseconds through pairing/checkpoint sums; Fraction through document "
                "aggregation; CSV microseconds serialize floats plus exact sum columns."
            ),
            "new_summary_scope": (
                "Post-review checkpoint-averaged descriptive sensitivity; "
                "does not replace the sealed original primary M=32000 estimand."
            ),
            "auditor_sha256": sha(Path(__file__)),
            "inputs_sha256": {
                name: sha(SOURCE / name)
                for name in (
                    "DELIVERY.json",
                    "COMPLETE.json",
                    "PREPARED.json",
                    "MANIFEST.json",
                    "PROTOCOL.json",
                    "document-results.csv",
                    "paired-comparisons.csv",
                    "REPORT_PROVENANCE.json",
                    "INDEPENDENT_AUDIT.json",
                )
            },
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "rehashed_files": len(delivery["sha256"]),
                "matched_runs": len(rows),
                "pairs": len(paired),
                "document_means": len(documents),
                "summary_rows": len(aggregated),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
