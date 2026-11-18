#!/usr/bin/env python3
"""Report sealed raw-KV component results, retaining negative comparisons."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    base = args.out.resolve()
    audit = json.loads((base / "INDEPENDENT_AUDIT.json").read_text())
    assert audit["status"] == "PASS" and audit["cases"] == 864
    assert audit["complete_sha256"] == sha(base / "COMPLETE.json")
    with (base / "document-results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    lookup = {
        (
            r["model"],
            r["book_id"],
            int(r["M"]),
            r["method"],
            int(r["bandwidth_GBps"]),
            int(r["layer_compute_ns"]),
        ): r
        for r in rows
    }
    models = ["NOSA-8B", "NSA-8B", "MiniCPM4.1-8B"]
    books = ["10146", "10321", "10356"]
    paired = []
    for model in models:
        for book in books:
            for checkpoint in (32000, 32256):
                for bandwidth in (8, 16, 32):
                    for compute in (0, 25600, 256000, 2560000):
                        values = {
                            method: lookup[model, book, checkpoint, method, bandwidth, compute]
                            for method in ("DRAM", "Current", "Recency", "Oracle")
                        }
                        current = int(values["Current"]["raw_component_finish_ns"])
                        paired.append(
                            dict(
                                model=model,
                                book_id=book,
                                M=checkpoint,
                                bandwidth_GBps=bandwidth,
                                layer_compute_ns=compute,
                                current_gain_vs_dram_ns=int(
                                    values["DRAM"]["raw_component_finish_ns"]
                                )
                                - current,
                                current_gain_vs_recency_ns=int(
                                    values["Recency"]["raw_component_finish_ns"]
                                )
                                - current,
                                current_gain_vs_oracle_ns=int(
                                    values["Oracle"]["raw_component_finish_ns"]
                                )
                                - current,
                            )
                        )
    with (base / "paired-comparisons.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)
    lines = [
        "# Native raw-KV transfer component",
        "",
        "All 864 prespecified component scenarios completed; independent timestamp/byte "
        "reconstruction passed. This is CPU replay of measured native selector indices, "
        "not execution of native recovery, generated-token timing, or workflow completion.",
        "",
        "The unit is a PG19 document: three documents per model. The two adjacent M "
        "values, bandwidths, compute assumptions, layers and queries are paired conditions, "
        "not additional independent samples. Means and document ranges are descriptive; no CI.",
        "",
        "## Zero-compute raw-transfer boundary",
        "",
        "Primary M=32000; 32 GB/s. DRAM is total demanded raw-KV copy time. "
        "Positive gains mean less component time than DRAM. The exact zero-compute relation "
        "is demanded nonresident unique bytes / bandwidth; it is verified from copy events. "
        "These microsecond gains are not native inference or WCT gains.",
        "",
        "| Model | DRAM mean (ms) | Current gain mean [range] (µs) | "
        "Recency gain (µs) | Oracle gain (µs) |",
        "|---|---:|---:|---:|---:|",
    ]
    primary = []
    for model in models:
        by_method = {
            method: [lookup[model, book, 32000, method, 32, 0] for book in books]
            for method in ("DRAM", "Current", "Recency", "Oracle")
        }
        gains = [int(r["gain_vs_dram_ns"]) / 1000 for r in by_method["Current"]]
        dram = mean(int(r["raw_component_finish_ns"]) / 1e6 for r in by_method["DRAM"])
        recency = mean(int(r["gain_vs_dram_ns"]) / 1000 for r in by_method["Recency"])
        oracle = mean(int(r["gain_vs_dram_ns"]) / 1000 for r in by_method["Oracle"])
        lines.append(
            f"| {model} | {dram:.6f} | {mean(gains):.3f} [{min(gains):.3f}, "
            f"{max(gains):.3f}] | {recency:.3f} | {oracle:.3f} |"
        )
        primary.append(
            dict(
                model=model,
                dram_mean_ms=dram,
                current_gain_mean_us=mean(gains),
                current_gain_range_us=[min(gains), max(gains)],
                recency_gain_mean_us=recency,
                oracle_gain_mean_us=oracle,
            )
        )
    lines += [
        "",
        "## Compute-assumption sensitivity",
        "",
        "Primary M=32000; 32 GB/s. Assumed compute is identical for every policy. "
        "Hit-compute overlap uses selected block-reference proportions; this is an "
        "uncalibrated sensitivity, not a matched native kernel profile. A positive "
        "Current-versus-Recency value means Current is faster. All signs are retained.",
        "",
        "| Model | Assumed layer compute (µs) | Current gain vs DRAM (µs) | "
        "Current gain vs Recency (µs) |",
        "|---|---:|---:|---:|",
    ]
    for model in models:
        for compute in (0, 25600, 256000, 2560000):
            selected = [
                r
                for r in paired
                if r["model"] == model
                and r["M"] == 32000
                and r["bandwidth_GBps"] == 32
                and r["layer_compute_ns"] == compute
            ]
            lines.append(
                f"| {model} | {compute / 1000:g} | "
                f"{mean(r['current_gain_vs_dram_ns'] for r in selected) / 1000:.3f} | "
                f"{mean(r['current_gain_vs_recency_ns'] for r in selected) / 1000:.3f} |"
            )
    negatives = {}
    lines += ["", "## Retained signs and scope", ""]
    for model in models:
        selected = [r for r in paired if r["model"] == model]
        counts = {}
        for comparator in ("dram", "recency", "oracle"):
            values = [r[f"current_gain_vs_{comparator}_ns"] for r in selected]
            counts[comparator] = dict(
                faster=sum(v > 0 for v in values),
                equal=sum(v == 0 for v in values),
                slower=sum(v < 0 for v in values),
                min_ns=min(values),
                max_ns=max(values),
            )
        negatives[model] = counts
        r = counts["recency"]
        lines.append(
            f"- {model}: Current vs Recency is faster/equal/slower in "
            f"{r['faster']}/{r['equal']}/{r['slower']} of 72 paired sensitivity "
            "conditions. Those 72 cases are not independent samples."
        )
    lines += [
        "",
        "All policies share the same Current-derived layer-ordered background stream. "
        "Only prepared residency changes: 4 layers x 16 blocks x 65536 bytes = 4 MiB for "
        "Current, Recency and Oracle; DRAM starts with no raw-KV residency. Prepared "
        "selector/auxiliary state is equally ready by assumption. Initial fill and "
        "normal-time replacement traffic are excluded, so this is not net system benefit.",
        "",
        "All 256 query demands are released together at layer entry. Rebuilt causal "
        "tail KV is local and never fetched from DRAM. Query-ready means all historical "
        "raw-KV copies needed by that query have completed after release, not that native "
        "attention or output has completed. Object-granular transfer completion differs "
        "from current runtime LoadBatch completion, so ordering agreement is not runtime "
        "timing equivalence. Future-frequency Oracle is not claimed latency-optimal.",
        "",
        "Native full-prefill traces do not establish selector equivalence under chunked "
        "resume; MiniCPM's dense threshold and native compressed/index/window state remain "
        "outside this experiment. There is no matching compute profile, TP/queue/other "
        "request contention, preparation cost, or physical H2D calibration.",
        "",
        "`document-results.csv` retains all per-document endpoints and paired DRAM "
        "differences. `layer-results.csv` retains every layer. Each `cases/*.npz` retains "
        "8192 query-ready records and all byte-transfer segments; column definitions are "
        "in `ARRAY_SCHEMA.json`. Unused transferred bytes, partial bytes at stop, "
        "cancelled remaining bytes, and untransferred checkpoint bytes are separate fields.",
        "",
        "The v1 directory is a preserved prepared-only snapshot. Before any matrix "
        "execution, v2 corrected an all-hit preemption-counter issue and strengthened "
        "per-case reuse bindings. Experimental conditions did not change.",
    ]
    (base / "RESULTS.md").write_text("\n".join(lines) + "\n")
    result = dict(
        status="PASS",
        primary_zero_compute=primary,
        sign_counts=negatives,
        independent_audit_sha256=sha(base / "INDEPENDENT_AUDIT.json"),
        complete_sha256=sha(base / "COMPLETE.json"),
        script_sha256=sha(__file__),
        simulations_run=0,
        report_sha256=sha(base / "RESULTS.md"),
        paired_comparisons_sha256=sha(base / "paired-comparisons.csv"),
    )
    (base / "REPORT_PROVENANCE.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
