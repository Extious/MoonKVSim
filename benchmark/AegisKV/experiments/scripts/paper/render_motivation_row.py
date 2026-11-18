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
base.CC_CSV = base.ROOT / "benchmark/AegisKV/experiments/data/motivation-compact-cc/compact-example-failure-position.csv"
SELECTION = base.CC_CSV.with_name("SELECTION.json")
EXAMPLE_COSTS = base.CC_CSV.with_name("recovery-costs.json")
base.GAP_CSV = base.ROOT / "benchmark/AegisKV/experiments/data/motivation-fanin-cc/workflow-parallel-gap.csv"
GAP_SELECTION = base.GAP_CSV.with_name("SELECTION.json")
W, H = 2.24, 1.85
REUSE_W, REUSE_H = 3.34, 2.35
REUSE = base.ROOT / "benchmark/AegisKV/experiments/data/reuse-aiconfigurator-max-context-h100/estimates.json"
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
    ax.set_xlabel("Max. duration gap (s)")
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
    assert len(rows) == 4 and len({r["workflow_id"] for r in rows}) == 1
    assert all(0 < int(r["prefix_tokens"]) <= 131072 for r in rows)
    costs = json.loads(EXAMPLE_COSTS.read_text())["workflow_costs"]
    assert len(costs) == len(rows)
    assert all(c['branch_index'] == int(r['branch_index']) and c['prefix_tokens'] == int(r['prefix_tokens'])
               for c,r in zip(costs,rows))
    times = np.array([c['recompute_s'] for c in costs])
    slack = np.array([float(r["slack_s"]) for r in rows])
    exposed = np.maximum(times-slack, 0)
    absorbed = times-exposed
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.23, .28, .51, .50])
    stats = fig.add_axes([.79, .28, .19, .50], sharey=ax)
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
         f"Four independent branch-failure counterfactuals in workflow {rows[0]['workflow_id']}, "
         f"at {float(rows[0]['failure_time_s']):.1f} s; other branches/queues unchanged. "
         "Four-branch group selected for gap near 100 s and visible exposure; not representative "
         "population failure impact. Group is not its workflow maximum or a sample in the ECDF. "
         "Qwen3-14B AIConfigurator queries use each active request's input-size proxy "
         "(hash-block count times 64, not a tokenizer length), plus an assumed 64-token tail. "
         "No measured latency and no extrapolation of a measured curve.",
         [str(base.CC_CSV.relative_to(base.ROOT)), str(SELECTION.relative_to(base.ROOT)),
          str(EXAMPLE_COSTS.relative_to(base.ROOT))])
    return [dict(branch=f"A{i+1}", recompute_s=float(t), slack_s=float(s), exposed_s=float(e))
            for i, (t, s, e) in enumerate(zip(times, slack, exposed))]


def recompute():
    from matplotlib.lines import Line2D

    data = json.loads(REUSE.read_text())
    fig, ax = plt.subplots(figsize=(REUSE_W, REUSE_H))
    # Reserve fixed physical bands for the three legend rows and axis labels.
    fig.subplots_adjust(left=.21, right=.97, bottom=.40/REUSE_H,
                        top=1-.66/REUSE_H)
    # Paths have redundant color/line encodings, including in grayscale.
    # Marker shape identifies the model; hollow points flag only the two
    # named extrapolation regimes. Every point, filled or hollow, is static.
    paths = [("hbm_ms", "HBM reuse", base.BLUE, "-"),
             ("dram_ms", "DRAM reuse", base.ORANGE, "--"),
             ("recompute_ms", "Recompute", base.RED, ":")]
    models = [("Qwen3-14B", "o", 5),
              ("Llama-3.1-70B", "s", 4),
              ("Qwen3-235B-A22B-Instruct-2507", "^", 4.5),
              ("DeepSeek-V3.2", "D", 4)]
    labels = {"Qwen3-235B-A22B-Instruct-2507": "Qwen3-235B (2507)"}
    assert set(data['models']) == {m[0] for m in models}
    for model, marker, size in models:
        rows = sorted((r for r in data['rows'] if r['model'] == model),
                      key=lambda r: r['total_tokens'])
        assert all(r['status'] == 'estimated' for r in rows)
        assert rows[-1]['total_tokens'] == data['models'][model]['context_limit']
        assert all(r['context_tokens']+r['tail_tokens'] == r['total_tokens'] for r in rows)
        for key, label, color, style in paths:
            ax.plot([r['total_tokens'] for r in rows], [r[key] for r in rows],
                    color=color, ls=style, lw=1.15, label=f'{model}: {label}')
            for r in rows:
                extrapolated = r['dsa_beyond_table_context'] or r['qwen_full_attention_projection']
                ax.plot(r['total_tokens'], r[key], color=color, marker=marker,
                        ls='none', ms=size, mfc='white' if extrapolated else color,
                        mew=.9)
    ax.set_xscale('log', base=2); ax.set_yscale('log')
    ax.set_xlim(6800, 1250000); ax.set_ylim(7, 500000)
    ax.set_yticks([10, 100, 1000, 10000, 100000], ['10', '100', '1k', '10k', '100k'])
    ax.set_xticks([8192, 32768, 131072, 1000000], ['8K','32K','128K','1M'])
    ax.minorticks_off(); ax.tick_params(length=2.5, pad=2)
    ax.grid(axis='y', color='#E3E7EB', lw=.5)
    ax.set_xlabel('Total context (tokens)', labelpad=3)
    ax.set_ylabel('Recovery time (ms)', labelpad=3)
    # Three path keys in a row, then four model keys in a separate two-column key.
    # This avoids twelve repetitive legend entries at single-column width.
    path_handles = [Line2D([], [], color=c, ls=s, lw=1.8, label=label)
                    for _, label, c, s in paths]
    model_handles = [Line2D([], [], color=base.INK, marker=m, ls='none',
                           ms=z, mfc=base.INK, mew=.9, label=labels.get(name, name))
                     for name, m, z in models]
    fig.legend(handles=path_handles, loc='upper center',
               bbox_to_anchor=(.5, 1-.025/REUSE_H), borderpad=0, borderaxespad=0,
               ncol=3, handlelength=1.3, columnspacing=.4, handletextpad=.35)
    fig.legend(handles=model_handles, loc='upper center',
               bbox_to_anchor=(.5, 1-.23/REUSE_H), borderpad=0, borderaxespad=0,
               ncol=2, handlelength=1.5, columnspacing=.7, handletextpad=.4, labelspacing=.25)
    save(fig, "motivation-recompute", "static-estimate",
         "Single-column, single-axis recovery comparison: color and line style encode path; "
         "marker shape encodes model. Hollow markers flag DSA table extrapolation beyond 32K "
         "and Qwen2507 full-attention cost projection beyond 256K. Filled markers are also static estimates. "
         "All 75 points are deterministic estimates; no jitter. "
         "Qwen3-14B dense TP1 to 128K with YaRN, Llama-3.1-70B dense TP4 to 128K, "
         "Qwen3-235B-A22B-Instruct-2507 dense-attention MoE TP/EP16 to 1,010,000, "
         "DeepSeek-V3.2 671B sparse DSA MoE TP/EP32. PP1; H100-SXM BF16 batch1, "
         "AIConfigurator 0.9.0 HYBRID, vLLM 0.19.0. Different GPU allocations, not equal-resource ranking. "
         "DeepSeek ends at its official configuration limit of 160K. Total C=M+64 on the x-axis. "
         "Recompute sums sequential 8K chunks; vocabulary projection is excluded in all paths. "
         "Qwen2507 beyond 256K is a full-attention cost projection; DCA and sparse-kernel speedups are not modeled. "
         "Known 64-token tail included in all paths. HBM holds full history plus sparse auxiliary state. "
         "DRAM restores each rank concurrently at assumed 64 GB/s per GPU before tail compute. "
         "DSA state includes replicated MLA latent, RoPE key and FP8 indexer with FP32 scales. "
         "DSA module tables end at 32768 total tokens; beyond-table shapes use extrapolation. "
         "No measured H2D, software recovery overhead, overlap, workload statistics or accuracy validation.",
         [str(REUSE.relative_to(base.ROOT))], width=REUSE_W)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("gap", "example", "figure1", "figure2", "all"), default="all")
    args = parser.parse_args()
    previous = json.loads((OUT/"MANIFEST.json").read_text()) if args.only != "all" else None
    if args.only in ("example", "figure2"):
        base.MANIFEST["motivation-branch-gap"] = previous["figures"]["motivation-branch-gap"]
    else:
        branch_gap()
    if args.only in ("gap", "figure2"):
        base.MANIFEST["motivation-recovery-exposure"] = previous["figures"]["motivation-recovery-exposure"]
        cases = previous["exposure_cases"]
    else:
        cases = exposure()
    if args.only not in ("all", "figure2"):
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
                       figure2_height_in=REUSE_H, font_pt=10.25),
        source_sha256={p:base.sha(base.ROOT/p) for p in sorted(sources)},
        exposure_cases=cases, figures=base.MANIFEST)
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({k:v["size_in"] for k,v in base.MANIFEST.items()}))
