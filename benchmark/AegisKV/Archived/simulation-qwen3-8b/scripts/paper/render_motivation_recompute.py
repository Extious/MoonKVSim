#!/usr/bin/env python3
"""Replot frozen long-context recomputation predictions; execute no predictor.

The historical source is preserved beside the export. Only the two dense-model
configurations are used: the old 235B PP4 prediction has an unresolved 94-layer
partition, and the old reuse-path inset uses uncalibrated model-independent
coefficients. Neither is appropriate evidence for this observation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from figure_style import save

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "output/pdf/aegiskv-revision-20260909"
SOURCE = OUT / "sources/motivation-recompute"
NAME = "motivation-recompute"
EXPECTED_CSV_SHA = "0d26ac74283c0fa6b905f17750052c87cf93bbebc0ec0ed29bb4dae4e38046f6"
SERIES = (
    ("Qwen3-8B", "#0072B2", "o", "-"),
    ("Qwen3-32B", "#B86B00", "s", "--"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows():
    path = SOURCE / "legacy-data.csv"
    assert sha(path) == EXPECTED_CSV_SHA, "Historical source CSV changed"
    with path.open(newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    assert len(all_rows) == 24
    source_meta = all_rows[0]
    assert sha(SOURCE / "legacy-renderer.py") == source_meta["generator_sha256"]
    assert sha(SOURCE / "aiconfigurator-predictor.py") == source_meta["predictor_source_sha256"]
    selected = [r for r in all_rows if r["path_key"] == "recompute"
                and r["model"] in {x[0] for x in SERIES}]
    assert len(selected) == 8
    for row in selected:
        assert (int(row["tp_size"]), int(row["pp_size"]), int(row["ep_size"])) == (4, 2, 1)
        assert row["aiconfigurator_database_mode"] == "SILICON"
        assert row["aiconfigurator_system"] == "a100_sxm"
        assert row["aiconfigurator_backend"] == "sglang-0.5.10"
        assert float(row["aiconfigurator_prefill_scale_factor"]) == 1.05
        chunks = [float(x) for x in row["chunk_latencies_s"].split(";")]
        assert len(chunks) == int(row["chunk_count"])
        assert len(chunks) * int(row["chunk_tokens"]) == int(row["context_tokens"])
        assert math.isclose(sum(chunks), float(row["component_time_s"]), rel_tol=1e-10)
    return selected


def main():
    rows = load_rows()
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.labelsize": 10.5, "axes.labelcolor": "#263442",
        "axes.edgecolor": "#5B6670", "axes.linewidth": .65,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.labelsize": 10, "ytick.labelsize": 10,
        "xtick.color": "#263442", "ytick.color": "#263442",
        "legend.fontsize": 10, "text.color": "#263442",
        "pdf.fonttype": 42, "svg.fonttype": "none",
        "svg.hashsalt": "aegiskv-motivation-recompute-20260909",
        "axes.axisbelow": True,
    })
    fig, ax = plt.subplots(figsize=(10/3, 2.9))
    fig.subplots_adjust(left=.20, right=.96, bottom=.205, top=.77)
    statistics = []
    for model, color, marker, linestyle in SERIES:
        points = sorted((r for r in rows if r["model"] == model),
                        key=lambda r: int(r["context_tokens"]))
        x = [int(r["context_tokens"]) / 1024 for r in points]
        y = [float(r["component_time_s"]) for r in points]
        assert x == [16, 32, 64, 128]
        ax.plot(x, y, label=model, color=color, marker=marker,
                linestyle=linestyle, linewidth=1.6, markersize=4.8,
                markerfacecolor="white", markeredgewidth=1.05)
        statistics.append({"model": model, "at_16ki_s": y[0], "at_128ki_s": y[-1],
                           "ratio_128ki_over_16ki": y[-1]/y[0]})
    ax.set(xlabel="Lost prefix (Ki tokens)", ylabel="Predicted recomputation (s)",
           xlim=(10, 137), ylim=(-1.5, 36))
    ax.set_xticks([16, 32, 64, 128])
    ax.set_yticks([0, 10, 20, 30])
    ax.grid(axis="y", color="#D8DCE1", linewidth=.55)
    ax.tick_params(length=3, width=.65, pad=3)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.56, 1.005), ncol=1, frameon=False,
               handlelength=2.0, handletextpad=.6, labelspacing=.25)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{NAME}.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(fig, NAME, directory=OUT)
    manifest = {
        "name": NAME,
        "evidence": "historical_silicon_database_configuration_prediction",
        "new_experiments": 0,
        "predictor_executed": False,
        "width_in": 10/3, "height_in": 2.9,
        "sources": {str(p.relative_to(ROOT)): sha(p) for p in sorted(SOURCE.iterdir()) if p.is_file()},
        "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)),
                      "sha256": sha(Path(__file__))},
        "files": {ext: sha(OUT/f"{NAME}.{ext}") for ext in ["png", "pdf", "svg", "csv"]},
        "statistical_unit": "one deterministic configured component-time prediction per model and prefix length",
        "configuration_count": 8, "full_failure_runs": 0, "independent_repeats": 0,
        "transformation": "Select all dense-model full-recompute rows; tokens/1024 on x; unchanged component_time_s on y; no smoothing or error bars",
        "configuration": {"accelerator": "A100-SXM 80GB", "tp": 4, "pp": 2, "ep": 1, "dp": 1,
                          "precision": "BF16", "batch_requests": 1, "chunk_tokens": 8192,
                          "backend": "sglang-0.5.10", "database_mode": "SILICON", "prefill_scale_factor": 1.05},
        "excluded_source_rows": [
            {"count": 4, "selector": "Qwen3-235B-A22B recompute", "reason": "Historical README flags unresolved 94-layer PP4 partition and unverified physical PP runtime; retained in source CSV"},
            {"count": 12, "selector": "peer_hbm, local_dram, ssd", "reason": "Different uncalibrated model-independent path-coefficient evidence; irrelevant to isolated full-prefix recomputation observation"},
        ],
        "statistics": statistics,
        "observation_zh": "在这两个固定模型与并行配置的历史预测中，丢失前缀由 16 Ki 增至 128 Ki 时，单请求完整前缀重算由 0.49/1.72 s 增至 9.16/32.82 s，长上下文显著放大重建 KV 的计算代价。",
        "caption_zh": "长上下文的完整前缀重算代价。Qwen3-8B 与 Qwen3-32B 在 A100-80GB、TP4/PP2、BF16 配置下，按 8 Ki-token 分块累加单请求 prefill 预测；Ki=1,024。每条线连接四个历史 AIConfigurator SILICON 配置预测点，无故障运行或重复测量。",
        "caption_en": "Full-prefix recomputation grows with context length. Historical AIConfigurator SILICON predictions for Qwen3-8B and Qwen3-32B on A100-80GB, TP4/PP2, BF16, summing 8 Ki-token prefill chunks for one request. Ki = 1,024. Lines connect four configured predictions per model; these are neither physical failure runs nor end-to-end recovery measurements.",
        "boundaries": ["No measured AegisKV or Mooncake comparison", "No failure detection, queueing, state transfer, decode replay, or workflow propagation", "Different parallel configuration from current Qwen3-8B DP8/TP1 evaluation", "Archived predictor and generator hashes verified; underlying performance-database revision was not pinned by the old export", "Component-time prediction does not establish physical PP deployment feasibility or end-to-end recovery latency"],
        "visual_review": "pending actual PNG and final-width PDF inspection",
    }
    (OUT/f"{NAME}-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"files": manifest["files"], "statistics": statistics}, indent=2))


if __name__ == "__main__":
    main()
