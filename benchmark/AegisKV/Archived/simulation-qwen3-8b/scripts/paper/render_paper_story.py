"""Reproducible, standalone figures at the manuscript's actual 7 / 3.333 inch widths.

The old 186 exports remain immutable. All workflow views use ONE permutation,
Mooncake WCT then workflow ID, and export every paired point to CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator, NullFormatter

from figure_style import save
from paper_paths import ROOT, DATA
from three_system_data import LABELS, SYSTEMS, load_case, sha, write_csv
from three_system_review_notes import controller_service

OUT = ROOT / "output/pdf/aegiskv-paper-story-20260908"
RUNS = ROOT / "output/three-system-20260908/data-final"
COLORS = {"mooncake": "#555D66", "dram": "#B86B00", "aegis": "#0072B2"}
STYLES = {"mooncake": "-", "dram": "--", "aegis": "-."}
MARKERS = {"mooncake": "o", "dram": "s", "aegis": "^"}
RECORDS = []
INPUTS = {}

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.labelsize": 10,
        "legend.fontsize": 10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "lines.linewidth": 1.4,
        "axes.axisbelow": True,
        "svg.hashsalt": "aegiskv-paper-story-v2",
        "font.family": "DejaVu Sans",
    }
)


@lru_cache(maxsize=3)
def case(name):
    result = load_case(RUNS / name)
    for s in SYSTEMS:
        path = RUNS / name / f"{s}.json"
        INPUTS[str(path.relative_to(ROOT))] = sha(path)
    return result


def canvas(xlabel, ylabel, *, wide=False, height=None):
    fig, ax = plt.subplots(figsize=(7 if wide else 10 / 3, height or (2.65 if wide else 2.55)))
    fig.subplots_adjust(
        left=0.102 if wide else 0.205,
        right=0.974 if wide else 0.95,
        bottom=0.205 if wide else 0.22,
        top=0.82 if wide else 0.975,
    )
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.grid(axis="y", color="#D8DCE1", linewidth=0.55)
    ax.tick_params(length=3, width=0.65, pad=3)
    ax.yaxis.set_major_locator(MaxNLocator(5))
    return fig, ax


def legend(ax, *, header=False, loc="lower right", columns=1):
    narrow = ax.figure.get_size_inches()[0] < 5
    handles, labels = ax.get_legend_handles_labels()
    if narrow and set(labels) == set(LABELS.values()):
        # A common legend band keeps CDF bodies and sparse tails unobscured.
        ax.figure.set_figheight(2.9)
        ax.figure.subplots_adjust(top=0.735, bottom=0.205)
        header, columns = True, 1
    if header:
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.55, 1),
            bbox_transform=ax.figure.transFigure,
            ncol=columns,
            frameon=False,
            handlelength=2.4,
            columnspacing=1.25,
            handletextpad=0.55,
        )
    else:
        ax.legend(
            loc=loc,
            frameon=True,
            facecolor="white",
            edgecolor="none",
            framealpha=0.93,
            handlelength=2.25,
            labelspacing=0.35,
            borderpad=0.25,
            handletextpad=0.5,
            ncol=columns,
        )


def line(ax, system, x, y, *, markers=False, thin=False):
    ax.plot(
        x,
        y,
        color=COLORS[system],
        linestyle=STYLES[system],
        linewidth=1.05 if thin else 1.6,
        label=LABELS[system],
        marker=MARKERS[system] if markers else None,
        markersize=4.2,
        markerfacecolor="white",
        markeredgewidth=1,
    )


def finish(fig, name, rows, *, evidence="modeled_exploration", sources=(), note=""):
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / f"{name}.csv", rows)
    save(fig, name, directory=OUT)
    RECORDS.append(
        {
            "name": name,
            "evidence": evidence,
            "note": note,
            "width_in": float(fig.get_size_inches()[0]),
            "height_in": float(fig.get_size_inches()[1]),
            "sources": list(sources),
            "files": {ext: sha(OUT / f"{name}.{ext}") for ext in ("pdf", "svg", "png", "csv")},
        }
    )


def cdf(ax, values, system=None, color=None):
    x = np.sort(np.asarray(values, dtype=float))
    assert len(x) and np.isfinite(x).all()
    x = np.r_[x[0], x]
    y = np.arange(len(x)) / (len(x) - 1)
    ax.step(
        x,
        y,
        where="post",
        linewidth=1.65,
        color=COLORS[system] if system else color or COLORS["aegis"],
        linestyle=STYLES[system] if system else "-",
        label=LABELS[system] if system else None,
    )
    ax.set_ylim(0, 1.025)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1], ["0", "0.25", "0.5", "0.75", "1"])


def support():
    path = DATA / "publication-figure-inputs.json"
    inputs = json.loads(path.read_text())
    INPUTS[str(path.relative_to(ROOT))] = sha(path)
    for key, scale, xlabel in (
        ("prompt_tokens", 1024, "Prompt length (Ki tokens)"),
        ("workflow_call_counts", 1, "Calls per workflow"),
    ):
        values = np.asarray(inputs[key]) / scale
        fig, ax = canvas(
            xlabel, "Fraction of requests" if key == "prompt_tokens" else "Fraction of workflows"
        )
        cdf(ax, values)
        ax.set_xlim(left=0)
        if key == "workflow_call_counts":
            ax.set_xticks([0, 5, 10, 15, 20, 27])
        finish(
            fig,
            f"workload-{key}",
            [{"value": v} for v in values],
            evidence="workload_description",
            sources=[str(path.relative_to(ROOT))],
            note=f"Original workload only; n={len(values)}; no synthetic revisit rows.",
        )

    path = DATA / "motivation-real-cc/real-cc-workflow-parallel-gap.csv"
    INPUTS[str(path.relative_to(ROOT))] = sha(path)
    rows = list(csv.DictReader(path.open()))
    values = np.array([float(r["max_duration_gap_s"]) for r in rows])
    assert len(values) == 124 and (values > 0).all()
    fig, ax = canvas("Parallel-branch duration gap (s)", "Fraction of workflows")
    cdf(ax, values)
    ax.set_xscale("log")
    ax.xaxis.set_minor_formatter(NullFormatter())
    finish(
        fig,
        "motivation-branch-gap",
        rows,
        evidence="trace_observation",
        sources=[str(path.relative_to(ROOT))],
        note="Observed duration difference, not validated causal CPM slack.",
    )

    fig, ax = canvas("Context length (Ki tokens)", "KV footprint (GiB)")
    x = np.arange(0, 97)
    one = x * 1024 * 147456 / 1024**3
    limit = 40 - 16381470720 / 1024**3 - 2
    ax.plot(x, one, label="One KV copy", color=COLORS["aegis"])
    ax.plot(x, one * 2, label="Two KV copies", color=COLORS["dram"], ls="--")
    ax.axhline(limit, color=COLORS["mooncake"], ls=":")
    ax.text(3, limit + 0.6, "After fixed memory", color=COLORS["mooncake"], va="bottom")
    ax.set(xlim=(0, 96), ylim=(0, 34))
    ax.set_xticks([0, 32, 64, 96])
    ax.set_yticks([0, 8, 16, 24, 32])
    legend(ax, loc="upper left")
    finish(
        fig,
        "motivation-kv-capacity",
        [
            dict(context_ki=a, one_copy_gib=b, two_copies_gib=2 * b, after_fixed_gib=limit)
            for a, b in zip(x, one)
        ],
        evidence="analytical",
        sources=["benchmark/AegisKV/experiments/THREE_SYSTEM_PROTOCOL.md"],
        note="147456 B/token; after weights and 2 GiB runtime, before dynamic foreground KV.",
    )


def workflow_views():
    data = case("f0-revisit")
    base = data["mooncake"]["workflows"]
    order = sorted(range(len(base)), key=lambda i: (base[i]["wct_s"], base[i]["workflow_id"]))
    ids = [base[i]["workflow_id"] for i in order]
    write_csv(
        OUT / "workflow-order.csv",
        [
            dict(
                rank=j + 1,
                workflow_id=base[i]["workflow_id"],
                original_id_index=i + 1,
                mooncake_wct_s=base[i]["wct_s"],
            )
            for j, i in enumerate(order)
        ],
    )
    services = controller_service(data)
    specs = [
        ("wct", "wct_s", "WCT (s)", False),
        ("wct-difference", "wct_s", "WCT change (s)", True),
        ("dram-hit", "dram_hit_pct", "DRAM token hit rate (%)", False),
        ("scheduler-queue", "mean_scheduler_queue_s", "Mean GPU queue delay (s)", False),
        ("hbm-wait", "mean_foreground_hbm_wait_s", "Mean HBM wait (s)", False),
        ("controller-service-difference", None, "CPU service change (ms)", True),
        ("background-copy", "background_copy_gib", "Background traffic (GiB)", False),
        ("peer-copy", "peer_copy_gib", "Peer copy traffic (GiB)", False),
    ]
    for suffix, key, ylabel, difference in specs:
        values = {
            s: np.array([r[key] for r in data[s]["workflows"]]) if key else np.array(services[s])
            for s in SYSTEMS
        }
        if difference:
            values = {s: values[s] - values["mooncake"] for s in SYSTEMS}
        fig, ax = canvas("Workflow (ordered by Mooncake WCT)", ylabel, wide=True)
        x = np.arange(1, len(order) + 1)
        for s in SYSTEMS:
            line(ax, s, x, values[s][order], thin=True)
        ax.set_xlim(1, len(order))
        ax.set_xticks([1, 40, 80, 120, 160])
        if not difference:
            ax.set_ylim(bottom=-0.015 * max(1, max(v.max() for v in values.values())))
        if suffix == "dram-hit":
            ax.set_ylim(-1, 55)
        legend(ax, header=True, columns=3)
        finish(
            fig,
            "f0-revisit-" + suffix,
            [
                dict(
                    workflow_rank=j + 1,
                    workflow_id=ids[j],
                    **{s: float(values[s][i]) for s in SYSTEMS},
                )
                for j, i in enumerate(order)
            ],
            sources=["f0-revisit"],
            note="Same baseline-WCT permutation for all workflow views; lines join paired workflows, not time or independent repeats.",
        )


def evaluation():
    data = case("f0-revisit")
    fig, ax = canvas("Workflow completion time (s)", "Fraction of workflows")
    for s in SYSTEMS:
        cdf(ax, [r["wct_s"] for r in data[s]["workflows"]], s)
    ax.set_xlim(left=0)
    legend(ax)
    finish(
        fig,
        "f0-revisit-wct-cdf",
        [
            dict(system=s, workflow_id=r["workflow_id"], wct_s=r["wct_s"])
            for s in SYSTEMS
            for r in data[s]["workflows"]
        ],
        sources=["f0-revisit"],
    )

    fig, ax = canvas("Time to first token (s)", "Fraction of requests")
    for s in SYSTEMS:
        cdf(ax, [r["ttft_ns"] / 1e9 for r in data[s]["requests"]], s)
    assert all(r["ttft_ns"] > 0 for s in SYSTEMS for r in data[s]["requests"])
    ax.set_xscale("log")
    ax.xaxis.set_minor_formatter(NullFormatter())
    legend(ax, loc="upper left")
    # The long middle label determines the legend rectangle. Keep its empty
    # lower-right area transparent where the CDF rises past the legend.
    ax.get_legend().set_frame_on(False)
    finish(
        fig,
        "f0-revisit-ttft-cdf",
        [
            dict(system=s, span_id=r["span_id"], ttft_s=r["ttft_ns"] / 1e9)
            for s in SYSTEMS
            for r in data[s]["requests"]
        ],
        sources=["f0-revisit"],
    )

    fig, ax = canvas("Request-mean TPOT (ms)", "Fraction at or above x")
    rows = []
    for s in SYSTEMS:
        vals = np.array(
            [
                r["request_tpot_ns"] / 1e6
                for r in data[s]["requests"]
                if r["request_tpot_ns"] is not None
            ]
        )
        assert (vals > 0).all()
        x, counts = np.unique(vals, return_counts=True)
        survival = np.cumsum(counts[::-1])[::-1] / len(vals)
        ax.step(x, survival, where="pre", color=COLORS[s], ls=STYLES[s], label=LABELS[s], lw=1.65)
        rows.extend(
            dict(system=s, tpot_ms=float(a), count=int(b), survival_ge=float(c))
            for a, b, c in zip(x, counts, survival)
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(1 / 2608, 1.18)
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_minor_formatter(NullFormatter())
    legend(ax, header=True, columns=3)
    finish(
        fig,
        "f0-revisit-tpot-tail",
        rows,
        sources=["f0-revisit"],
        note="Inclusive empirical survival, all 2432 requests with defined TPOT per system; request means, not individual inter-token gaps.",
    )

    fig, ax = canvas("Foreground GET slowdown (×)", "Fraction of successful GETs")
    rows = []
    for s in SYSTEMS:
        cdf(ax, [r["service_slowdown"] for r in data[s]["foreground_transfers"]], s)
        rows.extend(dict(system=s, **r) for r in data[s]["foreground_transfers"])
    ax.set_xlim(left=1)
    legend(ax)
    finish(
        fig,
        "f0-revisit-transfer-service_slowdown",
        rows,
        sources=["f0-revisit"],
        note="Data service / isolated same-byte bottleneck service; excludes setup; different GET populations across systems.",
    )

    fig, ax = canvas("GPU", "Time with <1 GiB free (%)", wide=True)
    rows = []
    for s in SYSTEMS:
        vals = [data[s]["hbm_pressure"][f"gpu-{i}"]["free_below_1gib_pct"] for i in range(8)]
        line(ax, s, range(8), vals, markers=True)
        rows.extend(dict(system=s, gpu=i, low_free_hbm_time_pct=v) for i, v in enumerate(vals))
    ax.set(ylim=(0, 100), xlim=(-0.15, 7.15))
    ax.set_xticks(range(8))
    legend(ax, header=True, columns=3)
    finish(
        fig,
        "f0-revisit-hbm-pressure",
        rows,
        sources=["f0-revisit"],
        note="Event-interval integration over workload makespan; includes reclaimable cache occupancy; not hardware HBM bandwidth.",
    )

    # The stack colors identify sources/operations; full system names label rows.
    for name, xlabel, components in [
        (
            "f0-revisit-cache-sources",
            "Prompt tokens (%)",
            [
                ("Local HBM", "#777F87", "local"),
                ("Store DRAM", "#B86B00", "dram"),
                ("Peer HBM", "#0072B2", "peer"),
                ("Computed", "#E4E7EB", "miss"),
            ],
        ),
        (
            "f0-revisit-controller-breakdown",
            "Modeled controller service (s)",
            [
                ("Lookup", "#777F87", "foreground_lookup"),
                ("Admission", "#0072B2", "admission"),
            ],
        ),
        (
            "f0-revisit-traffic-breakdown",
            "Transferred data (TiB)",
            [
                ("GET", "#777F87", "foreground"),
                ("DRAM write", "#B86B00", "dram"),
                ("Peer copy", "#0072B2", "peer"),
            ],
        ),
    ]:
        fig, ax = canvas("", xlabel, height=2.9)
        fig.subplots_adjust(left=0.19, bottom=0.235, top=0.79)
        values = {s: {} for s in SYSTEMS}
        rows = []
        for s in SYSTEMS:
            d = data[s]
            if name.endswith("cache-sources"):
                total = sum(r["prompt_tokens"] for r in d["requests"])
                for k in ("local", "dram", "peer"):
                    values[s][k] = 100 * sum(r[k + "_hit_tokens"] for r in d["requests"]) / total
                values[s]["miss"] = 100 - sum(values[s].values())
                assert abs(sum(values[s].values()) - 100) < 1e-10
            elif name.endswith("controller-breakdown"):
                values[s] = {
                    k: sum(r["service_ns"] for r in d["cpu_queue"] if r["operation"] == k) / 1e9
                    for _, _, k in components
                }
                assert np.isclose(
                    sum(values[s].values()), d["summary"]["modeled_controller_service_s"]
                )
            else:
                values[s] = {
                    "foreground": sum(r["foreground_copy_gib"] for r in d["workflows"]) / 1024,
                    "dram": d["summary"]["background_dram_gib"] / 1024,
                    "peer": d["summary"]["background_peer_gib"] / 1024,
                }
                assert np.isclose(
                    sum(values[s].values()) * 1024, d["summary"]["physical_transferred_gib"]
                )
            rows.append(dict(system=s, **values[s]))
        left = np.zeros(3)
        for j, (label, color, key) in enumerate(components):
            vals = np.array([values[s][key] for s in SYSTEMS])
            pattern = "//" if key == "peer" else ".." if key in {"dram", "admission"} else None
            ax.bar(
                range(3),
                vals,
                bottom=left,
                width=0.62,
                label=label,
                color=color,
                edgecolor="white",
                lw=0.45,
                hatch=pattern,
            )
            left += vals
        ax.set_xticks(range(3), ["Mooncake", "DRAM-only\nAegisKV", "AegisKV"])
        ax.set_xlim(-0.6, 2.6)
        ax.grid(axis="y", color="#D8DCE1", linewidth=0.55)
        ax.set_ylim(0, 100 if name.endswith("cache-sources") else max(left) * 1.10)
        legend(ax, header=True, columns=2)
        finish(
            fig,
            name,
            rows,
            sources=["f0-revisit"],
            note="Additive accounting; stack colors are component types, system identity is on the x axis.",
        )


def sensitivity():
    specs = [
        (
            "bandwidth",
            [5, 25, 50],
            ["f0-revisit-bw5", "f0-revisit", "f0-revisit-bw50"],
            "Shared bandwidth (GB/s)",
            "mean_wct_s",
            "Mean WCT (s)",
        ),
        (
            "concurrency",
            [8, 16, 32],
            ["f0-revisit-c8", "f0-revisit", "f0-revisit-c32"],
            "Active workflows",
            "mean_wct_s",
            "Mean WCT (s)",
        ),
        (
            "dram-capacity",
            [32, 128, 1e12 / 1024**3],
            ["f0-revisit-dram32", "f0-revisit-dram128", "f0-revisit"],
            "DRAM capacity (GiB)",
            "dram_hit_pct",
            "DRAM token hit rate (%)",
        ),
    ]
    for name, x, cases, xlabel, key, ylabel in specs:
        # Keep only summaries across large reduced runs.
        summaries = [{s: d["summary"][key] for s, d in case(c).items()} for c in cases]
        fig, ax = canvas(xlabel, ylabel, height=2.9)
        for s in SYSTEMS:
            line(ax, s, x, [r[s] for r in summaries], markers=True)
        ax.set_ylim(bottom=0)
        ax.set_xticks(x)
        if name == "dram-capacity":
            ax.set_xscale("log", base=2)
            ax.set_xticks(x, ["32", "128", "931.3"])
            ax.xaxis.set_minor_formatter(NullFormatter())
        legend(ax, header=True, columns=3)
        finish(
            fig,
            f"sensitivity-{name}-{key}",
            [dict(case=c, x=v, **row) for c, v, row in zip(cases, x, summaries)],
            sources=cases,
            note="Actual numerical x coordinates; one execution per point/system; connecting segments are guides, no interpolation evidence or CI.",
        )


def main():
    global OUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=OUT)
    args = p.parse_args()
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    support()
    workflow_views()
    evaluation()
    sensitivity()
    for path in [
        Path(__file__),
        Path(__file__).with_name("figure_style.py"),
        Path(__file__).with_name("three_system_data.py"),
        Path(__file__).with_name("three_system_review_notes.py"),
    ]:
        INPUTS[str(path.relative_to(ROOT))] = sha(path)
    (OUT / "statistics-manifest.json").write_text(
        json.dumps(
            {
                "schema": "aegiskv.paper_story.statistics.v1",
                "figures": RECORDS,
                "input_bindings": INPUTS,
                "workflow_order_sha256": sha(OUT / "workflow-order.csv"),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"Exported {len(RECORDS)} independent statistical figures to {OUT}")


if __name__ == "__main__":
    main()
