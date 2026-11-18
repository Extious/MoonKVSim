"""Independent reporting arithmetic on sealed native rows; no simulation imports."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
SOURCE = BASE / "native-transfer-postreview-v2"
PREVIOUS = BASE / "reviews/native-transfer-paper-summary-v1"
OUT = Path(__file__).resolve().parent
MODELS = ("NOSA-8B", "NSA-8B", "MiniCPM4.1-8B")
BOOKS = ("10146", "10321", "10356")
BANDWIDTHS = (8, 16, 32)
COMPUTES = (0, 25600, 256000, 2560000)
METHODS = ("DRAM", "Current", "Recency", "Oracle")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def csv_write(path, values):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)


def sign(value):
    return "positive" if value > 0 else "negative" if value < 0 else "zero"


def main():
    inputs = [
        SOURCE / name
        for name in (
            "PROTOCOL.json",
            "DELIVERY.json",
            "document-results.csv",
            "INDEPENDENT_AUDIT.json",
        )
    ]
    inputs += [PREVIOUS / name for name in ("SEAL.json", "model-bandwidth-compute-summary.csv")]
    inputs += [
        BASE / "reviews/native-transfer-figure-v1/SEAL.json",
        BASE / "reviews/postreview-methods-opus55/REVIEW.md",
        Path(__file__),
    ]
    before = {str(p): sha(p) for p in inputs}
    protocol, delivery = read(SOURCE / "PROTOCOL.json"), read(SOURCE / "DELIVERY.json")
    assert protocol["primary_M"] == 32000 and protocol["M"] == [32000, 32256]
    assert protocol["bandwidth_GBps"] == list(BANDWIDTHS)
    assert not any("primary" in k and "bandwidth" in k for k in protocol)
    assert delivery["status"] == "PASS"
    for name in ("PROTOCOL.json", "document-results.csv", "INDEPENDENT_AUDIT.json"):
        assert sha(SOURCE / name) == delivery["sha256"][name]
    old_seal = read(PREVIOUS / "SEAL.json")
    assert old_seal["source_delivery_sha256"] == sha(SOURCE / "DELIVERY.json")
    assert (
        sha(PREVIOUS / "model-bandwidth-compute-summary.csv")
        == old_seal["files"]["model-bandwidth-compute-summary.csv"]["sha256"]
    )
    original = rows(SOURCE / "document-results.csv")
    index = {
        (
            r["model"],
            r["book_id"],
            int(r["M"]),
            int(r["bandwidth_GBps"]),
            int(r["layer_compute_ns"]),
            r["method"],
        ): r
        for r in original
    }
    assert len(original) == len(index) == 864
    paired = []
    for model in MODELS:
        for book in BOOKS:
            for checkpoint in protocol["M"]:
                for bandwidth in BANDWIDTHS:
                    for compute in COMPUTES:
                        key = model, book, checkpoint, bandwidth, compute
                        selected = {method: index[*key, method] for method in METHODS}
                        assert len({r["background_order_sha256"] for r in selected.values()}) == 1
                        assert len({r["assumed_compute_ns"] for r in selected.values()}) == 1
                        values = {m: int(r["raw_component_finish_ns"]) for m, r in selected.items()}
                        dram, current = values["DRAM"], values["Current"]
                        row = dict(
                            model=model,
                            book=book,
                            M=checkpoint,
                            bandwidth_GBps=bandwidth,
                            layer_compute_ns=compute,
                            prespecified_primary_M=checkpoint == 32000,
                            dram_finish_ns=dram,
                            current_finish_ns=current,
                            assumed_compute_ns=int(selected["DRAM"]["assumed_compute_ns"]),
                            dram_exposed_wait_ns=int(selected["DRAM"]["exposed_wait_ns"]),
                        )
                        for comparator in ("DRAM", "Recency", "Oracle"):
                            gain = values[comparator] - current
                            assert gain == int(selected[comparator]["exposed_wait_ns"]) - int(
                                selected["Current"]["exposed_wait_ns"]
                            )
                            row[f"{comparator.lower()}_minus_current_ns"] = gain
                        gain = dram - current
                        row["saving_pct_of_dram_finish"] = float(Fraction(gain * 100, dram))
                        row["saving_pct_of_dram_exposed_wait"] = (
                            float(Fraction(gain * 100, row["dram_exposed_wait_ns"]))
                            if row["dram_exposed_wait_ns"]
                            else None
                        )
                        assert gain == int(selected["Current"]["gain_vs_dram_ns"])
                        paired.append(row)
    csv_write(OUT / "all216-document-checkpoint-pairs.csv", paired)
    raw_index = {
        (r["model"], r["book"], r["M"], r["bandwidth_GBps"], r["layer_compute_ns"]): r
        for r in paired
    }
    all_cells, document_means = {}, []
    old = {
        (r["model"], int(r["bandwidth_GBps"]), int(float(r["layer_compute_us"]) * 1000)): r
        for r in rows(PREVIOUS / "model-bandwidth-compute-summary.csv")
    }
    for analysis, checkpoints in (("primary_M32000", [32000]), ("posthoc_two_M", [32000, 32256])):
        cells = []
        for model in MODELS:
            for bandwidth in BANDWIDTHS:
                for compute in COMPUTES:
                    docs = []
                    for book in BOOKS:
                        selected = [
                            raw_index[model, book, m, bandwidth, compute] for m in checkpoints
                        ]
                        doc = {
                            field: sum(Fraction(r[field]) for r in selected) / len(selected)
                            for field in (
                                "dram_finish_ns",
                                "current_finish_ns",
                                "dram_minus_current_ns",
                                "recency_minus_current_ns",
                                "oracle_minus_current_ns",
                            )
                        }
                        docs.append(doc)
                        document_means.append(
                            dict(
                                analysis=analysis,
                                model=model,
                                book=book,
                                bandwidth_GBps=bandwidth,
                                layer_compute_ns=compute,
                                checkpoints=len(checkpoints),
                                **{k: float(v) for k, v in doc.items()},
                                saving_pct_of_dram_finish=float(
                                    100 * doc["dram_minus_current_ns"] / doc["dram_finish_ns"]
                                ),
                            )
                        )
                    cell = dict(
                        analysis=analysis,
                        model=model,
                        bandwidth_GBps=bandwidth,
                        layer_compute_ns=compute,
                        documents=3,
                        checkpoints_per_document=len(checkpoints),
                    )
                    for field in (
                        "dram_finish_ns",
                        "current_finish_ns",
                        "dram_minus_current_ns",
                        "recency_minus_current_ns",
                        "oracle_minus_current_ns",
                    ):
                        raw_sum = sum(
                            raw_index[model, book, m, bandwidth, compute][field]
                            for book in BOOKS
                            for m in checkpoints
                        )
                        average = Fraction(raw_sum, 3 * len(checkpoints))
                        assert average == sum(doc[field] for doc in docs) / 3
                        cell[field + "_sum"] = raw_sum
                        cell[field.removesuffix("_ns") + "_mean_ms"] = float(average / 1_000_000)
                        cell[field.removesuffix("_ns") + "_doc_min_ms"] = float(
                            min(d[field] for d in docs) / 1_000_000
                        )
                        cell[field.removesuffix("_ns") + "_doc_max_ms"] = float(
                            max(d[field] for d in docs) / 1_000_000
                        )
                        if analysis == "posthoc_two_M" and "minus_current" in field:
                            label = field.removesuffix("_ns")
                            saved = old[model, bandwidth, compute]
                            assert raw_sum == int(saved[label + "_six_checkpoint_sum_ns"])
                            for suffix, value in (
                                ("mean", average),
                                ("min", min(d[field] for d in docs)),
                                ("max", max(d[field] for d in docs)),
                            ):
                                assert (
                                    abs(float(value / 1000) - float(saved[label + f"_{suffix}_us"]))
                                    < 1e-9
                                )
                    cell["saving_pct_ratio_of_document_means"] = float(
                        Fraction(
                            100 * cell["dram_minus_current_ns_sum"], cell["dram_finish_ns_sum"]
                        )
                    )
                    cell["mean_of_document_saving_pct"] = float(
                        sum(100 * d["dram_minus_current_ns"] / d["dram_finish_ns"] for d in docs)
                        / 3
                    )
                    cell["document_saving_pct_min"] = float(
                        min(100 * d["dram_minus_current_ns"] / d["dram_finish_ns"] for d in docs)
                    )
                    cell["document_saving_pct_max"] = float(
                        max(100 * d["dram_minus_current_ns"] / d["dram_finish_ns"] for d in docs)
                    )
                    cells.append(cell)
        assert len(cells) == 36
        csv_write(OUT / (analysis + "-all36cells.csv"), cells)
        all_cells[analysis] = cells
    csv_write(OUT / "document-level-means.csv", document_means)
    statistics = {}
    for analysis, cells in all_cells.items():
        statistics[analysis] = dict(
            cells=36,
            documents_per_cell=3,
            dram_finish_mean_ms_range=[
                min(r["dram_finish_mean_ms"] for r in cells),
                max(r["dram_finish_mean_ms"] for r in cells),
            ],
            saving_mean_ms_range=[
                min(r["dram_minus_current_mean_ms"] for r in cells),
                max(r["dram_minus_current_mean_ms"] for r in cells),
            ],
            saving_pct_of_dram_mean_time_range=[
                min(r["saving_pct_ratio_of_document_means"] for r in cells),
                max(r["saving_pct_ratio_of_document_means"] for r in cells),
            ],
            recency_signs=dict(Counter(sign(r["recency_minus_current_ns_sum"]) for r in cells)),
            max_percentage_case=max(cells, key=lambda r: r["saving_pct_ratio_of_document_means"]),
            worst_recency_case=min(cells, key=lambda r: r["recency_minus_current_ns_sum"]),
            by_bandwidth={
                str(b): dict(
                    recency_signs=dict(
                        Counter(
                            sign(r["recency_minus_current_ns_sum"])
                            for r in cells
                            if r["bandwidth_GBps"] == b
                        )
                    ),
                    minimum_recency_minus_current_ms=min(
                        r["recency_minus_current_mean_ms"]
                        for r in cells
                        if r["bandwidth_GBps"] == b
                    ),
                )
                for b in BANDWIDTHS
            },
        )
    result = dict(
        status="PASS_BOUNDED_REPORTING_CHECK",
        source_sha256=before,
        original_method_rows=864,
        exact_four_method_pairs=216,
        all_bandwidths=list(BANDWIDTHS),
        prespecified_primary_M=32000,
        prespecified_primary_bandwidth=None,
        figure_bandwidth32_is_posthoc=True,
        two_checkpoint_pooling_is_posthoc=True,
        adjacent_checkpoints_dependent=True,
        saved_pooled36cells_all_comparators_means_ranges_reproduced=True,
        statistics=statistics,
        all216_current_vs_dram_total_finish_savings_below_one_pct=all(
            r["saving_pct_of_dram_finish"] < 1 for r in paired
        ),
        raw_pair_max_percentage=max(paired, key=lambda r: r["saving_pct_of_dram_finish"]),
        raw_pair_max_absolute_saving=max(paired, key=lambda r: r["dram_minus_current_ns"]),
        raw_pairs_above_half_percent=sum(r["saving_pct_of_dram_finish"] > 0.5 for r in paired),
        max_percentage_when_denominator_is_exposed_wait=max(
            paired, key=lambda r: r["saving_pct_of_dram_exposed_wait"] or 0
        ),
        raw_DRAM_time_ms_range=[
            min(r["dram_finish_ns"] for r in paired) / 1e6,
            max(r["dram_finish_ns"] for r in paired) / 1e6,
        ],
        limitations=[
            "Finite sealed case-set only; no universal <1% theorem or physical calibration.",
            "Percent saving=(DRAM total component finish-Current finish)/DRAM finish; denominator includes assumed compute.",
            "Exposed-wait percentage is a different denominator and can reach100%; never substitute it silently.",
            "Three documents are reused across models; M/loads/layers/queries are dependent settings, not repetitions.",
            "No normal residency preparation, selector/auxiliary readiness, physical kernel/full recovery or WCT claim.",
            "No model/parameter selection, no DES, no changes to original figure/protocol/results or paper.",
        ],
    )
    for name, digest in before.items():
        assert sha(Path(name)) == digest
    result["all_consumed_original_artifacts_unchanged"] = True
    write(OUT / "RESULT.json", result)
    print(
        json.dumps(
            {
                k: {
                    f: v[f]
                    for f in (
                        "dram_finish_mean_ms_range",
                        "saving_mean_ms_range",
                        "saving_pct_of_dram_mean_time_range",
                        "recency_signs",
                    )
                }
                for k, v in statistics.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
