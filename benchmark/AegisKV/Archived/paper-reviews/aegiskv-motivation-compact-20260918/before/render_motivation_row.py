"""Export the data plots for EuroSys Motivation Figures 1 and 2.

Each panel is 0.32 * 7 = 2.24 inches wide, with >=10-point text at that
insertion width. Recovery-path estimates form a separate 3.34-inch Figure 2.
The workflow topology has its own editable Draw.io generator.
Reuses the checked inputs of render_draft_20260915.py;
does not overwrite the single-column figures or the shared figure manifest.
"""
from __future__ import annotations

import csv
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-motivation-mpl")
SOURCE = Path(__file__).with_name("render_draft_20260915.py")
spec = importlib.util.spec_from_file_location("draft_figures", SOURCE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
np, plt = base.np, base.plt
OUT = base.ROOT / "benchmark/AegisKV/paper/figures/motivation-row"
base.OUT = OUT
base.CC_CSV = base.ROOT / "benchmark/AegisKV/experiments/data/motivation-wide-cc/wide-example-failure-position.csv"
SELECTION = base.CC_CSV.with_name("SELECTION.json")
base.GAP_CSV = base.ROOT / "benchmark/AegisKV/experiments/data/motivation-fanin-cc/workflow-parallel-gap.csv"
GAP_SELECTION = base.GAP_CSV.with_name("SELECTION.json")
W, H = 2.24, 2.40
REUSE = base.ROOT / "benchmark/AegisKV/experiments/data/reuse-aiconfigurator-a100/estimates.json"
plt.rcParams.update({
    "font.size": 10.25, "axes.labelsize": 10.25,
    "xtick.labelsize": 10.25, "ytick.labelsize": 10.25,
    "legend.fontsize": 10.25,
})


def save(fig, name, evidence, note, sources, width=W):
    base.save(fig, name, evidence=evidence, width_in=width, note=note, sources=sources)


def branch_gap():
    with base.GAP_CSV.open() as f:
        rows = list(csv.DictReader(f))
    gap = np.sort([float(r["max_duration_gap_s"]) for r in rows])
    selection = json.loads(GAP_SELECTION.read_text())
    assert len(gap) == selection["retained_workflows"] > 0
    med, p90 = np.median(gap), np.percentile(gap, 90)
    assert abs(med-selection["median_duration_gap_s"]) < 1e-9
    assert abs(p90-selection["p90_duration_gap_s"]) < 1e-9
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.27, .28, .69, .66])
    ax.step(np.r_[.3, gap, 3e4], np.r_[0, np.arange(1, len(gap)+1)/len(gap), 1],
            where="post", color=base.BLUE, lw=1.4)
    ax.hlines(.5, .3, med, color="#C5CDD3", lw=.7, ls=(0, (2, 3)))
    ax.plot(med, .5, "o", color=base.BLUE, ms=4)
    ax.annotate(f"Median\n{med:.0f} s", xy=(med, .5), xytext=(.58, .13),
                textcoords="axes fraction", color=base.BLUE, ha="left",
                linespacing=1.2,
                arrowprops=dict(arrowstyle="-", color=base.BLUE, lw=.7))
    ax.annotate(f"P90\n{p90:,.0f} s",
                xy=(p90, np.searchsorted(gap, p90, side="right")/len(gap)),
                xytext=(.03, .69), textcoords="axes fraction", color=base.BLUE,
                ha="left", linespacing=1.2,
                arrowprops=dict(arrowstyle="-", color=base.BLUE, lw=.7))
    ax.set_xscale("log")
    ax.set_xlim(.3, 3e4)
    ax.set_ylim(0, 1.04)
    ax.set_xticks([1, 100, 10000], ["1", "100", "10k"])
    ax.minorticks_off()
    ax.set_yticks([0, .5, 1], ["0", "50", "100"])
    ax.set_xlabel("Branch-duration gap (s)")
    ax.set_ylabel("Workflows (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    save(fig, "motivation-branch-gap", "trace",
         f"{len(gap)} workflow maxima after filtering all groups for temporally inferred fan-in; "
         "completed overlapping branches followed by a later Main request. Main activity during "
         "branches is allowed. No explicit dependency edges in trace. Unsmoothed ECDF on a log "
         "x-axis. Median and P90 only; no title, prefix references or fault-absorption interpretation.",
         [str(base.GAP_CSV.relative_to(base.ROOT)), str(GAP_SELECTION.relative_to(base.ROOT))])


def exposure():
    with base.CC_CSV.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 10 and len({r["workflow_id"] for r in rows}) == 1
    assert all(0 < int(r["prefix_tokens"]) <= 131072 for r in rows)
    costs = json.loads(REUSE.read_text())["workflow_costs"]
    assert len(costs) == len(rows)
    assert all(c['branch_index'] == int(r['branch_index']) and c['prefix_tokens'] == int(r['prefix_tokens'])
               for c,r in zip(costs,rows))
    times = np.array([c['recompute_s'] for c in costs])
    slack = np.array([float(r["slack_s"]) for r in rows])
    exposed = np.maximum(times-slack, 0)
    absorbed = times-exposed
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.23, .22, .51, .60])
    stats = fig.add_axes([.79, .22, .19, .60], sharey=ax)
    y = np.arange(len(rows))
    ax.barh(y, absorbed, height=.57, color=base.PALE_GREEN, edgecolor=base.GREEN,
            hatch="//", lw=.6, label="Slack absorbs")
    ax.barh(y, exposed, left=absorbed, height=.57, color=base.RED, label="WCT loss")
    for i, (t, s) in enumerate(zip(times, slack)):
        ax.text(t+.35, i, f"{t:.1f}", ha="left", va="center")
        stats.text(.5, i, f"{s:.1f}", ha="center", va="center", color=base.GRAY)
    ax.set_yticks(y, ["A"+str(int(r["branch_index"])+1) for r in rows])
    ax.set_ylim(len(rows)-.45, -.55)
    ax.set_xlim(0, 65)
    ax.set_xticks([0, 20, 40, 60])
    ax.set_xlabel("Recompute time (s)")
    ax.set_ylabel("Agent branch", labelpad=3)
    ax.tick_params(axis="y", length=0, pad=3)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#E3E7EB", lw=.6)
    stats.set_xlim(0, 1)
    stats.set_axis_off()
    stats.text(.5, 1.045, "Slack\n(s)", transform=stats.transAxes,
               ha="center", va="bottom", color=base.GRAY, linespacing=1.2)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left",
               bbox_to_anchor=(.12, 1), ncol=1, handlelength=1.1,
               handletextpad=.4, borderaxespad=0, labelspacing=.3)
    save(fig, "motivation-recovery-exposure", "trace+static-estimate",
         f"Ten independent branch-failure counterfactuals in workflow {rows[0]['workflow_id']}, "
         f"at {float(rows[0]['failure_time_s']):.1f} s; other branches/queues unchanged. "
         "Case and fault time intentionally selected for wider fan-out and larger loss; not representative "
         "population failure impact. Gap is near the median and is this workflow's maximum. "
         "Exact Qwen3-14B AIConfigurator queries rebuild the trace-derived prefix plus an assumed "
         "64-token tail. No measured latency and no extrapolation of a measured curve.",
         [str(base.CC_CSV.relative_to(base.ROOT)), str(SELECTION.relative_to(base.ROOT)),
          str(REUSE.relative_to(base.ROOT))])
    return [dict(branch=f"A{i+1}", recompute_s=float(t), slack_s=float(s), exposed_s=float(e))
            for i, (t, s, e) in enumerate(zip(times, slack, exposed))]


def recompute():
    data = json.loads(REUSE.read_text())
    fig, axes = plt.subplots(3, 1, figsize=(3.34, 4.30), sharex=True, sharey=True)
    fig.subplots_adjust(left=.21, right=.97, bottom=.12, top=.86, hspace=.21)
    paths = [("hbm_ms", "HBM reuse", base.BLUE, "o", "-"),
             ("dram_ms", "DRAM reuse", base.ORANGE, "s", "--"),
             ("recompute_ms", "Recompute", base.RED, "^", "-.")]
    for ax, model in zip(axes, data['models']):
        rows = [r for r in data['rows'] if r['model'] == model]
        assert len(rows) == 5 and all(r['status'] == 'estimated' for r in rows)
        for key, label, color, marker, style in paths:
            ax.plot([r['context_tokens'] for r in rows], [r[key] for r in rows],
                    color=color, marker=marker, ls=style, lw=1.25, ms=3.5, mfc='white', label=label)
        ax.set_xscale('log', base=2); ax.set_yscale('log')
        ax.set_xlim(7000, 153000); ax.set_ylim(6, 130000)
        ax.set_yticks([10, 100, 1000, 10000], ['10', '100', '1k', '10k'])
        ax.minorticks_off(); ax.tick_params(length=2.5, pad=2)
        ax.grid(axis='y', color='#E3E7EB', lw=.5)
        ax.text(.025, .98, model, transform=ax.transAxes, va='top', ha='left',
                bbox=dict(facecolor='white', edgecolor='none', pad=.5))
    axes[-1].set_xticks([8192, 16384, 32768, 65536, 131072], ['8K','16K','32K','64K','128K'])
    axes[-1].set_xlabel('Context length (tokens)', labelpad=3)
    fig.text(.025, .47, 'Recovery latency (ms)', rotation=90, ha='center', va='center')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.54,1.01),
               ncol=2, handlelength=1.4, columnspacing=.8, handletextpad=.4, labelspacing=.25)
    save(fig, "motivation-recompute", "static-estimate",
         "Single-column three-model recovery comparison; all curves are deterministic estimates. "
         "Qwen3-4B/8B/14B, AIConfigurator 0.9.0 HYBRID, vLLM 0.14.0, A100-SXM, BF16, batch 1, TP1. "
         "Known 64-token tail is included in all paths. HBM has entire history; DRAM serializes "
         "full-history H2D using system YAML's assumed 32 GB/s before the same tail forward. "
         "No measured H2D, software recovery overhead, overlap, workload statistics or accuracy validation.",
         [str(REUSE.relative_to(base.ROOT))], width=3.34)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("gap", "example", "figure1", "all"), default="all")
    args = parser.parse_args()
    previous = json.loads((OUT/"MANIFEST.json").read_text()) if args.only != "all" else None
    if args.only == "example":
        base.MANIFEST["motivation-branch-gap"] = previous["figures"]["motivation-branch-gap"]
    else:
        branch_gap()
    if args.only == "gap":
        base.MANIFEST["motivation-recovery-exposure"] = previous["figures"]["motivation-recovery-exposure"]
        cases = previous["exposure_cases"]
    else:
        cases = exposure()
    if args.only != "all":
        base.MANIFEST["motivation-recompute"] = previous["figures"]["motivation-recompute"]
    else:
        recompute()
    sources = {p for r in base.MANIFEST.values() for p in r["sources"]}
    manifest = dict(
        generator=str(Path(__file__).relative_to(base.ROOT)),
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        original_generator_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        figure_members={"1a":"motivation-branch-gap", "1b":"motivation-workflow.drawio",
                        "1c":"motivation-recovery-exposure", "2":"motivation-recompute"},
        workflow_manifest="benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.json",
        example_selection=str(SELECTION.relative_to(base.ROOT)),
        fanin_selection=str(GAP_SELECTION.relative_to(base.ROOT)),
        insertion=dict(text_width_in=7, figure1_panel_width_in=W, panel_fraction=.32,
                       figure1_panel_height_in=H, figure2_width_in=3.34,
                       figure2_height_in=4.30, font_pt=10.25),
        source_sha256={p:base.sha(base.ROOT/p) for p in sorted(sources)},
        exposure_cases=cases, figures=base.MANIFEST)
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({k:v["size_in"] for k,v in base.MANIFEST.items()}))
