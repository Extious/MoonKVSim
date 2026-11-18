"""Fit and draw a causal, one-landmark-per-agent remaining-time audit.

The landmark is the second LLM request's arrival, provided the first LLM
request has completed. The trace has no separate tool-completion timestamps.
This is an episode-level observational experiment, not Tracker validation.
"""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-agent-early-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf as fitz
from design_plot_typography import configure

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "benchmark/AegisKV/experiments/data/design-insights"
DATA = ROOT / "benchmark/AegisKV/experiments/data/agent-time-early"
OUT = ROOT / "benchmark/AegisKV/paper/figures/agent-time-early"
PANELS = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
SALT = "aegiskv-design-insight-agent-20260918"
NUMERIC = ["elapsed_s", "current_prompt_tokens", "first_prompt_tokens",
           "first_output_tokens", "first_api_s", "since_first_completion_s"]
CONFIG = dict(estimators=80, learning_rate=.06, max_depth=3,
              min_leaf=32, max_bins=32)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def collect(agents):
    rows = []
    counts = Counter()
    for a in agents:
        counts["input_agents"] += 1
        reqs = a["requests"]
        if len(reqs) < 2:
            counts["excluded_single_request"] += 1
            continue
        first, current = reqs[:2]
        finished = first["t"] + first["latency"]
        if finished > current["t"]:
            counts["excluded_overlapping_first_two_requests"] += 1
            continue
        elapsed = current["t"] - a["start"]
        remaining = a["duration_s"] - elapsed
        assert remaining > 0 and elapsed >= 0
        fold = int.from_bytes(hashlib.sha256(
            (SALT + ":" + a["workflow_id"]).encode()).digest()[:8], "big") % 5
        rows.append(dict(workflow_id=a["workflow_id"], agent_id=a["agent_id"],
                         role=a["role"], model=current["model"], fold=fold,
                         landmark_s=current["t"], first_completion_s=finished,
                         elapsed_s=elapsed, current_prompt_tokens=current["prompt"],
                         first_prompt_tokens=first["prompt"],
                         first_output_tokens=first["output"], first_api_s=first["latency"],
                         since_first_completion_s=current["t"] - finished,
                         actual_remaining_s=remaining, total_duration_s=a["duration_s"]))
    counts["eligible_agents"] = len(rows)
    counts["input_workflows"] = len({a["workflow_id"] for a in agents})
    counts["eligible_workflows"] = len({r["workflow_id"] for r in rows})
    return rows, dict(counts)


def matrix(rows, roles, models):
    # Vocabulary and tree binning are fitted on the training fold only.
    # Labels, total duration, identities, and future request counts are excluded.
    return np.asarray([
        [np.log1p(r[key]) for key in NUMERIC] +
        [float(r["role"] == role) for role in roles] +
        [float(r["model"] == model) for model in models]
        for r in rows], dtype=float)


def fit():
    DATA.mkdir(parents=True, exist_ok=True)
    agents = [json.loads(line) for line in (SOURCE / "agent-episodes.jsonl").read_text().splitlines()]
    rows, counts = collect(agents)
    protocol = dict(
        landmark="Second LLM request arrival, with first request completed; one sample per eligible episode",
        target="Seconds from landmark to reported whole-agent completion, including observed intervening delays",
        counts=counts, folds=5, fold_salt=SALT, numeric_features=NUMERIC,
        categorical_features=["role", "current_model"], config=CONFIG,
        baseline="Training-fold median remaining time at the same landmark, grouped by role and current model; role then global fallback",
        error="100 * abs(predicted_remaining_s - actual_remaining_s) / actual_remaining_s",
        exclusions="Clock-inconsistent episodes were excluded by the upstream extraction; then exclude single-request episodes and overlapping first two requests. No outcome/error threshold.",
        hyperparameter_selection="Fixed previous diagnostic configuration; no tuning on these held-out predictions",
        source_episode_sha256=sha(SOURCE / "agent-episodes.jsonl"),
        source_extraction=json.loads((SOURCE / "agent-extraction.json").read_text()),
        limitations=["No explicit tool-completion event or semantic task/role annotations; all roles are Subagent",
                     "Whole episodes are not fork/join-separated Tracker segments",
                     "The cohort requires a second request after first-request completion; coverage is reported",
                     "Five-fold cross-validation is not chronological deployment validation",
                     "Observed wall-clock time includes service and tool effects; no new hardware execution"])
    # Persist the fixed protocol before seeing model errors.
    write_json(DATA / "protocol.json", protocol)
    write_csv(DATA / "landmarks.csv", rows)
    path = SOURCE / "provenance/aegis_gbdt.py"
    spec = importlib.util.spec_from_file_location("early_aegis_gbdt", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    folds = []
    for k in range(5):
        train = [r for r in rows if r["fold"] != k]
        test = [r for r in rows if r["fold"] == k]
        tw = {r["workflow_id"] for r in train}
        vw = {r["workflow_id"] for r in test}
        assert not tw & vw
        roles = sorted({r["role"] for r in train})
        models = sorted({r["model"] for r in train})
        y = np.array([r["actual_remaining_s"] for r in train])
        model = module.AegisGBDTRegressor(module.AegisGBDTConfig(**CONFIG)).fit(
            matrix(train, roles, models), y)
        predicted = model.predict(matrix(test, roles, models))
        grouped, byrole = defaultdict(list), defaultdict(list)
        for r in train:
            grouped[(r["role"], r["model"])].append(r["actual_remaining_s"])
            byrole[r["role"]].append(r["actual_remaining_s"])
        fallback_count = 0
        for r, prediction in zip(test, predicted):
            key = (r["role"], r["model"])
            fallback_count += key not in grouped
            history = grouped.get(key, byrole.get(r["role"], y))
            median = float(np.median(history))
            r.update(gbdt_remaining_s=float(prediction), median_remaining_s=median,
                     baseline_training_count=len(history))
            for method in ("gbdt", "median"):
                delta = r[method + "_remaining_s"] - r["actual_remaining_s"]
                r[method + "_signed_error_s"] = delta
                r[method + "_ape_pct"] = 100 * abs(delta) / r["actual_remaining_s"]
        folds.append(dict(fold=k, train_agents=len(train), test_agents=len(test),
                          train_workflows=len(tw), test_workflows=len(vw),
                          roles=roles, models=models, baseline_fallbacks=fallback_count,
                          fitted_model=model.manifest()))
        print(f"Fold {k}: train {len(train)}, test {len(test)}", flush=True)
    write_csv(DATA / "predictions.csv", rows)
    stats = {}
    for method in ("gbdt", "median"):
        errors = np.array([r[method + "_ape_pct"] for r in rows])
        signed = np.array([r[method + "_signed_error_s"] for r in rows])
        stats[method] = dict(median_pct=float(np.median(errors)),
                             p90_pct=float(np.quantile(errors, .9)),
                             max_pct=float(errors.max()), mae_s=float(np.mean(abs(signed))),
                             within_10_pct=float(np.mean(errors <= 10)),
                             within_20_pct=float(np.mean(errors <= 20)),
                             within_50_pct=float(np.mean(errors <= 50)),
                             underprediction_fraction=float(np.mean(signed < 0)))
    fractions = np.array([r["elapsed_s"] / r["total_duration_s"] for r in rows])
    summary = dict(protocol_sha256=sha(DATA / "protocol.json"),
                   model_source_sha256=sha(path), generator_sha256=sha(Path(__file__)),
                   counts=counts, eligible_fraction=len(rows) / len(agents),
                   elapsed_fraction_quantiles=dict(zip(["p10", "p50", "p90"],
                                                      np.quantile(fractions, [.1, .5, .9]).tolist())),
                   roles=dict(Counter(r["role"] for r in rows)),
                   fold_results=folds, metrics=stats,
                   statistical_unit="One paired observation per agent episode, clustered in workflows; five fitted models, no independent repeated physical runs",
                   smoothing=False, truncated_errors=False)
    write_json(DATA / "summary.json", summary)
    print(json.dumps({"counts": counts, "metrics": stats}, indent=2), flush=True)


def render(rows, compact):
    width, height = (2.24, 1.85) if compact else (3.34, 2.3)
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([.25, .27, .72, .52] if compact else [.18, .23, .79, .57])
    max_error = max(float(r[method + "_ape_pct"]) for r in rows for method in ("gbdt", "median"))
    magnitude = 10 ** math.floor(math.log10(max(max_error, 1000)))
    limit = next(scale * magnitude for scale in (1, 2, 5, 10)
                 if scale * magnitude >= max(max_error, 1000))
    for method, label, color, style in [
            ("gbdt", "GBDT", "#246B94", "-"),
            ("median", "Median" if compact else "Historical median", "#72777D", "--")]:
        values = np.sort([float(r[method + "_ape_pct"]) for r in rows])
        cdf = np.arange(1, len(values) + 1) / len(values)
        ax.step(np.r_[0, values, limit], np.r_[0, cdf, 1], where="post",
                color=color, linestyle=style, linewidth=1.5, label=label)
    ax.set_xscale("symlog", linthresh=100, linscale=1)
    ax.set_xlim(0, limit)
    ax.set_ylim(0, 1.02)
    ticks = [0, 100, 1000, 10000, 100000]
    labels = ["0", "100", "1k", "10k", "100k"]
    selected = [(t, label) for t, label in zip(ticks, labels) if t <= limit]
    ax.set_xticks([t for t, _ in selected], [label for _, label in selected])
    ax.set_yticks([0, .5, 1], ["0", "0.5", "1"])
    ax.minorticks_off()
    ax.set_xlabel("Remaining-time error (%)", labelpad=3)
    ax.set_ylabel("Fraction of agents", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", linewidth=.6)
    ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.55, .985), ncol=2, frameon=False,
               handlelength=1.65, handletextpad=.4, columnspacing=.85)
    name = "agent-time-panel" if compact else "agent-time-single-column"
    for ext in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{name}.{ext}", facecolor="white")
    plt.close(fig)
    return limit


def compose(typography):
    doc = fitz.open()
    page = doc.new_page(width=7 * 72, height=2.22 * 72)
    page.insert_font(fontname="libertine", fontfile=typography["regular_path"])
    panel_paths = [OUT / "agent-time-panel.pdf", PANELS / "sparse-attention-survey.pdf",
                   PANELS / "retry-kv-prediction.pdf"]
    captions = ["(a) Agent-time prediction", "(b) Sparse attention adoption", "(c) Retry KV prediction"]
    for i, (path, caption) in enumerate(zip(panel_paths, captions)):
        x = i * 2.38 * 72
        with fitz.open(path) as source:
            page.show_pdf_page(fitz.Rect(x, 0, x + 2.24 * 72, 1.85 * 72), source, 0)
        available = page.insert_textbox(fitz.Rect(x, 1.90 * 72, x + 2.24 * 72, 2.22 * 72),
                                        caption, fontsize=10.05, fontname="libertine", align=1)
        assert available >= 0, f"Subcaption does not fit: {caption}"
    doc.save(OUT / "figure3-row.pdf")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(OUT / "figure3-row.png")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY,
                   alpha=False).save(OUT / "figure3-row-gray.png")
    doc.close()
    return {str(p.relative_to(ROOT)): sha(p) for p in panel_paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if not args.render_only:
        fit()
    OUT.mkdir(parents=True, exist_ok=True)
    with (DATA / "predictions.csv").open() as f:
        rows = list(csv.DictReader(f))
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": .7, "pdf.fonttype": 42,
                         "svg.fonttype": "none", "savefig.dpi": 250})
    typography = configure()
    limit = render(rows, compact=False)
    render(rows, compact=True)
    panels = compose(typography)
    write_json(OUT / "MANIFEST.json", dict(
        evidence="New fixed-landmark GBDT cross-validation on observed CC episodes",
        generator_sha256=sha(Path(__file__)),
        input_sha256=sha(DATA / "predictions.csv"), summary_sha256=sha(DATA / "summary.json"),
        typography=typography, xscale=dict(name="symlog", linthresh=100, limit=limit),
        smoothing=False, panel_inputs=panels,
        outputs={p.name: sha(p) for p in OUT.iterdir() if p.suffix in (".pdf", ".svg", ".png")}))


if __name__ == "__main__":
    main()
