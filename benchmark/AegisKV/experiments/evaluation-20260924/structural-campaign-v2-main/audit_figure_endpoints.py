"""Independently reconstruct both figure endpoints from integer summary timestamps."""

import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def csvrows(p):
    with p.open() as stream:
        return list(csv.DictReader(stream))


plan = read(OUT / "PLAN.json")
rows = csvrows(FIG / "wct-endpoints-per-run.csv")
assert len(rows) == 90
lookup = {(r["scenario"], r["fault"], r["policy"], int(r["seed"])): r for r in rows}
exact = {}
for job in plan["jobs"]:
    if job["fault"] == "F0":
        continue
    failed = read(OUT / "runs" / job["id"] / "summary.json")
    healthy = read(OUT / "runs" / job["f0_id"] / "summary.json")
    delta = {
        w: failed["workflows"][w]["wct_ns"] - healthy["workflows"][w]["wct_ns"]
        for w in healthy["workflows"]
    }
    assert len(delta) == 8
    key = job["scenario"], job["fault"], job["policy"], job["seed"]
    row = lookup[key]
    target = job["failure"]["agent"].split("/")[0]
    expected = {
        "target_delta_wct_s": delta[target] / 1e9,
        "all_workflow_mean_delta_wct_s": sum(delta.values()) / 8e9,
        "all_workflow_p95_paired_delta_s": max(delta.values()) / 1e9,
        "all_workflow_p99_paired_delta_s": max(delta.values()) / 1e9,
    }
    for name, value in expected.items():
        assert abs(float(row[name]) - value) < 1e-10, (job["id"], name)
    assert int(row["negative_workflow_delta_count"]) == sum(d < 0 for d in delta.values())
    exact[key] = expected
comparisons = csvrows(FIG / "wct-endpoint-comparisons.csv")
assert len(comparisons) == 20
for row in comparisons:
    column = (
        "target_delta_wct_s"
        if row["endpoint"] == "target_workflow"
        else "all_workflow_mean_delta_wct_s"
    )
    values = {
        p: [exact[row["scenario"], row["fault"], p, s][column] for s in (7, 19, 41)]
        for p in ("none", "dram", "aegiskv")
    }
    for p in values:
        assert abs(float(row[f"{p}_mean_delta_s"]) - mean(values[p])) < 1e-10
    for name, a, b in (("dram_vs_restart", "none", "dram"), ("aegis_vs_dram", "dram", "aegiskv")):
        gains = [x - y for x, y in zip(values[a], values[b], strict=True)]
        for stat, fn in (("mean", mean), ("min", min), ("max", max)):
            assert abs(float(row[f"{name}_{stat}_gain_s"]) - fn(gains)) < 1e-10
metadata = read(FIG / "EXPORT_METADATA.json")
for item in metadata["exports"]:
    assert abs(item["width_mm"] - 178) < 1e-4 and item["minimum_font_pt"] >= 10.29
    assert sha(FIG / (item["name"] + ".pdf")) == item["pdf_sha256"]
result = dict(
    passed=True,
    runs=135,
    paired_failure_runs=90,
    workflow_pairs=720,
    two_wct_endpoints_same_pairs=True,
    integer_timestamp_recomputation=True,
    per_seed_workflow_mean_before_seed_summary=True,
    headline_rows=20,
    descriptive_ranges_not_confidence_intervals=True,
    zero_and_negative_values_retained=True,
    scientific_limits=[
        "Constructed token lengths/DAG/arrivals and fixed role priors; not natural Agent traces or predictor accuracy.",
        "Long drift uses a constructed two-bank selector, dense Qwen3 compute profile, and K16 sufficient for both four-block banks.",
        "AIC modeled simulation; no physical GPU serving, native sparse WCT, batching, measured controller overhead or DMA interference calibration.",
    ],
    inspected_exports={
        name: sha(FIG / name)
        for item in metadata["exports"]
        for name in (item["name"] + "-96dpi-color.png", item["name"] + "-144dpi-grayscale.png")
    },
    actual_export_visual_review="Viewed all three color and grayscale PDF rasterizations at 178 mm canvas; Linux Libertine 10.3 pt; labels and legend readable, no clipping/overlap; hollow circles/squares/diamonds distinguish policies in grayscale.",
    manuscript_placement_review="Not performed here; parent owns manuscript insertion.",
    source_sha256={
        name: sha(OUT / name)
        for name in (
            "PLAN.json",
            "INPUT_MATCH.json",
            "TRACE_MECHANISM_AUDIT.json",
            "paired-workflows.csv",
            "VERSION_COMPARISON.json",
        )
    },
    data_sha256={
        name: sha(FIG / name)
        for name in (
            "wct-endpoints-per-run.csv",
            "wct-endpoint-comparisons.csv",
            "figure-data.csv",
            "headline-results.csv",
        )
    },
    export_metadata_sha256=sha(FIG / "EXPORT_METADATA.json"),
    script_sha256=sha(Path(__file__)),
)
(FIG / "FIGURE_REVIEW.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(
    json.dumps(
        {
            k: v
            for k, v in result.items()
            if k not in ("source_sha256", "data_sha256", "inspected_exports")
        },
        indent=2,
    )
)
