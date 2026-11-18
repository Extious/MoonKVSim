"""PaperBanana visual specification for current Agent-lease figures.

Only visual encodings change. Raw/derived values, identities, orders, units and
sample ranges remain owned by the existing, audited renderers.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FuncFormatter

INK = "#263442"
GRAY = "#555D66"
BLUE = "#0072B2"
ORANGE = "#B86B00"
COLORS = {"mooncake": GRAY, "dram": ORANGE, "aegis": BLUE}
STYLES = {"mooncake": "-", "dram": "--", "aegis": "-."}
MARKERS = {"mooncake": "o", "dram": "s", "aegis": "^"}
LABELS = {"mooncake": "Mooncake", "dram": "DRAM-only AegisKV", "aegis": "AegisKV"}


def install(plot):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.labelsize": 10.5, "axes.labelcolor": INK,
        "axes.edgecolor": "#5B6670", "axes.linewidth": .65,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.labelsize": 10, "ytick.labelsize": 10,
        "xtick.color": INK, "ytick.color": INK,
        "legend.fontsize": 10, "text.color": INK,
        "pdf.fonttype": 42, "svg.fonttype": "none",
        "svg.hashsalt": "aegiskv-agent-lease-paperbanana-v1",
        "hatch.linewidth": .5, "axes.axisbelow": True,
    })
    plot.canvas, plot.legend, plot.line = canvas, legend, line


def canvas(xlabel, ylabel, *, wide=False, height=None):
    fig, ax = plt.subplots(figsize=(7 if wide else 10/3, height or (2.45 if wide else 2.55)))
    fig.subplots_adjust(left=.115 if wide else .22, right=.978 if wide else .963,
        bottom=.22, top=.80 if wide else .945)
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.grid(axis="y", color="#DFE5EA", lw=.55)
    ax.tick_params(length=3, width=.6, pad=3)
    ax.yaxis.set_major_locator(MaxNLocator(4))
    return fig, ax


def legend(ax, *, header=False, loc="lower right", columns=1):
    del header, loc  # Every quantitative legend has its own unobstructed band.
    handles, labels = ax.get_legend_handles_labels()
    narrow = ax.figure.get_size_inches()[0] < 5
    if set(labels) == set(LABELS.values()):
        columns = 3
        if narrow:
            labels = [v.replace("DRAM-only AegisKV", "DRAM-only\nAegisKV") for v in labels]
    current = ax.get_legend()
    if current is not None:
        current.remove()
    result = ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5 if narrow else .55, .993),
        bbox_transform=ax.figure.transFigure, ncol=columns, frameon=False,
        fontsize=10, handlelength=2.0 if narrow else 2.1,
        columnspacing=.7 if narrow else 1.4, handletextpad=.35 if narrow else .5,
        borderpad=0, borderaxespad=0, labelspacing=.45)
    return result


def line(ax, system, x, y, *, markers=False, thin=False):
    ax.plot(x, y, color=COLORS[system], ls=STYLES[system],
        lw=1.0 if thin else 1.55, label=LABELS[system],
        marker=MARKERS[system] if markers or thin else None,
        markevery=(0, 10) if thin else None,
        ms=3.2 if thin else 4.3, markerfacecolor="white", markeredgewidth=.85)


def polish(fig, name):
    """Apply explicit per-family layout after legacy builders finish plotting."""
    ax = fig.axes[0]
    narrow = fig.get_size_inches()[0] < 5
    ax.grid(axis="y", color="#DFE5EA", lw=.55)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_linewidth(.65)
        spine.set_color("#5B6670")
    ax.tick_params(length=3, width=.6, pad=3)
    for label in [ax.xaxis.label, ax.yaxis.label]:
        label.set_fontsize(10.5)
        label.set_color(INK)
    legend_obj = ax.get_legend()
    if name == "aimd-quota-and-occupancy":
        ax.set_ylabel("Backup memory (GiB)")
    if narrow:
        height = 2.55
        top = .785 if legend_obj else .945
        bottom = .225
        left = .22
        if name == "native-memory-occupancy":
            left = .26
        if name == "ablation-lazy-refresh":
            left = .30
            ax.set_yticks([0, 100000, 200000, 300000])
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        if name in {"f0-revisit-cache-sources", "f0-revisit-controller-breakdown", "f0-revisit-traffic-breakdown"}:
            bottom = .265
            ax.set_xlim(-.48, 2.48)
        if name == "ablation-aimd-interference":
            ax.set_xticks([0, 1, 2], ["DRAM-only\nAegisKV", "Guarded\nAIMD", "Static\nPeer cap"])
        fig.set_figheight(height)
        fig.subplots_adjust(left=left, right=.963, bottom=bottom, top=top)
    else:
        height, top, bottom = 2.45, .80, .22
        if name == "reference-cpu-breakdown":
            height, top, bottom = 2.7, .755, .21
        elif name == "failure-focal-recovery-phases":
            height, top, bottom = 2.9, .70, .20
        elif name == "ablation-normal-wct":
            height, top, bottom = 2.2, .945, .25
        elif name == "f0-revisit-hbm-pressure":
            height, top, bottom = 2.2, .785, .245
        fig.set_figheight(height)
        fig.subplots_adjust(left=.115, right=.978, bottom=bottom, top=top)
    # At these two measured parameter sweeps the range is narrow. Show actual
    # values on an explicitly ticked local axis; no truncation or ratio claim.
    if name in {"sensitivity-cpu-quote", "sensitivity-dma"}:
        values = [float(v) for line in ax.lines for v in line.get_ydata()]
        ax.set_ylim(min(values)-1.2, max(values)+1.2)
        ax.yaxis.set_major_locator(MaxNLocator(4))
    if name == "aimd-warning-windows":
        # All observations fit; 100% is a possible bound, not observed data.
        ax.set_ylim(0, 20)
        ax.set_yticks([0, 5, 10, 15, 20])
        assert max(float(v) for line in ax.lines for v in line.get_ydata()) < 20
    if name in {"f0-revisit-wct-difference", "f0-revisit-controller-service-difference"} or name.startswith("f1-q"):
        ax.axhline(0, color=GRAY, lw=.85, zorder=0)
    if name.startswith("order-"):
        ax.set_ylim(0, 1.025)
        ax.set_yticks([0, .25, .5, .75, 1])
    if name == "motivation-kv-capacity":
        for text in ax.texts:
            if text.get_text() == "After fixed memory":
                text.set_text("After weights + runtime")
                text.set_fontsize(10)
