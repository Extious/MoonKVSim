#!/usr/bin/env python3
"""Render descriptive workload panels directly from the exact frozen workload."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    repository_root,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.common.hash import sha256_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=repository_root())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    configs = load_experiment_configs(default_config_dir(root), root=root)
    workload, manifest = workload_paths(configs.requests, root=root)
    records, binding, _ = load_frozen_workload(workload, manifest, retain_exact_token_ids=True)
    context = sorted(int(row["prompt_tokens"]) + int(row["output_tokens"]) for row in records)
    workflows = Counter(str(row["workflow_id"]) for row in records)
    span_counts = sorted(workflows.values())
    if len(context) != 1304 or len(workflows) != 160:
        raise ValueError("workload population differs from the complete frozen protocol")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.labelsize": 10,
        "xtick.labelsize": 10, "ytick.labelsize": 10, "axes.titlesize": 10,
        "legend.fontsize": 10, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False,
    })
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.7), layout="constrained")
    panels = (
        (axes[0], np.array(context) / 1024, "Context length (Ki tokens)", "(a) 1,304 model calls"),
        (axes[1], np.array(span_counts), "Model calls per workflow", "(b) 160 complete workflows"),
    )
    for ax, values, xlabel, title in panels:
        x = np.r_[0, values]
        y = np.r_[0, np.arange(1, len(values) + 1) / len(values)]
        ax.step(x, y, where="post", color="#222222", linewidth=1.5)
        ax.set(xlabel=xlabel, ylabel="Empirical CDF", title=title, ylim=(0, 1.04))
        ax.grid(axis="y", color="0.88", linewidth=0.5)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
    axes[0].set_xlim(0, 128)
    axes[0].set_xticks([0, 32, 64, 96, 128])
    axes[0].annotate(
        f"Maximum: {max(context):,} tokens\n128K bucket: 0 calls",
        xy=(max(context) / 1024, 1), xytext=(39, 0.45),
        arrowprops={"arrowstyle": "-", "color": "0.4", "linewidth": 0.7},
        fontsize=10, ha="left",
    )
    axes[1].set_xlim(0, max(span_counts) + 1)
    axes[1].set_xticks(sorted({0, min(span_counts), 8, 12, max(span_counts)}))
    outputs = {}
    for extension in ("pdf", "svg", "png"):
        path = out / f"workload-characteristics.{extension}"
        fig.savefig(path, dpi=200)
        outputs[path.name] = file_sha256(path)
    plt.close(fig)
    data = {
        "schema": "moonkvsim.simulation-paper-workload-figure.v1", "status": "PASS",
        "workload_binding": binding.to_dict(),
        "context_prompt_plus_output_tokens": context,
        "model_calls_by_workflow": dict(sorted(workflows.items())),
        "panels": {
            "a": {"population": "all 1304 spans", "statistic": "descriptive ECDF"},
            "b": {"population": "all 160 workflows", "statistic": "descriptive ECDF"},
        },
        "ci": "not applicable; finite-population description, no sampling inference",
        "transformations": "context tokens divided by 1024; no truncation or padding",
        "generator_sha256": file_sha256(Path(__file__)), "outputs": outputs,
        "modeled_uncalibrated": True, "physical_execution": False,
        "observed_deployed_agent_requests": False,
        "submission_ready": False,
    }
    (out / "workload-characteristics.json").write_text(
        json.dumps({**data, "fingerprint": sha256_json(data)}, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
