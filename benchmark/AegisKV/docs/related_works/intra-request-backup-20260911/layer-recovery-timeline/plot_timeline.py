"""Illustrative schedules, not measurements or a reproduction of LayerKV.

Run with: python plot_timeline.py
Each numbered KV transfer contains every historical token in that layer.
The recovery GPU, model weights, consistent cursor, and buffers are ready at t=0.
"""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


OUT = Path(__file__).resolve().parent
LAYERS = 10
DRAM_MS = 1.0
PEER_MS = 0.1
COMPUTE_MS = 2.0
COLORS = {"DRAM": "#326B9B", "Peer": "#8557A2", "Compute": "#307C65"}


def schedule(peer_layers):
    """Two independent transfer queues plus one sequential compute stream."""
    clocks = {"DRAM": 0.0, "Peer": 0.0}
    records = []
    arrivals = {}
    for layer in range(1, LAYERS + 1):
        path = "Peer" if layer in peer_layers else "DRAM"
        start = clocks[path]
        end = start + (PEER_MS if path == "Peer" else DRAM_MS)
        records.append(dict(kind=path, layer=layer, start_ms=start, end_ms=end))
        arrivals[layer] = end
        clocks[path] = end
    finish = 0.0
    for layer in range(1, LAYERS + 1):
        start = max(finish, arrivals[layer])
        if start > finish:
            records.append(dict(kind="Wait", layer=layer, start_ms=finish, end_ms=start))
        finish = start + COMPUTE_MS
        records.append(dict(kind="Compute", layer=layer, start_ms=start, end_ms=finish))
    return records, finish, max(arrivals.values())


def draw_panel(ax, records, finish, title):
    ys = {"Peer": 2, "DRAM": 1, "Compute": 0, "Wait": 0}
    for y in range(3):
        ax.axhline(y, color="#E3E7EB", lw=0.6, zorder=0)
    for item in records:
        kind = item["kind"]
        start, end = item["start_ms"], item["end_ms"]
        y = ys[kind]
        if kind == "Wait":
            ax.broken_barh([(start, end - start)], (y - 0.23, 0.46),
                          facecolors="#E3E7EB", edgecolors="#77828E",
                          linewidth=0.6, hatch="////", zorder=3)
        else:
            ax.broken_barh([(start, end - start)], (y - 0.23, 0.46),
                          facecolors=COLORS[kind], edgecolors="white", linewidth=0.6,
                          zorder=3)
            if end - start >= 0.5:
                ax.text((start + end) / 2, y, str(item["layer"]),
                        color="white", ha="center", va="center", fontsize=8.5, zorder=4)
    if not any(item["kind"] == "Peer" for item in records):
        ax.text(0.25, 2, "No Peer placement", color="#65717E", va="center", fontsize=9)
    else:
        ax.annotate("Layer 1 KV arrives at 0.1 ms", xy=(0.05, 2), xytext=(2.0, 2.42),
                    ha="left", va="center", fontsize=9, color=COLORS["Peer"],
                    arrowprops=dict(arrowstyle="->", color=COLORS["Peer"], lw=0.8))
    ax.annotate(f"Decoder done: {finish:.1f} ms", xy=(finish, 0),
                xytext=(finish, -0.63), fontsize=9, ha="right", va="center",
                arrowprops=dict(arrowstyle="-", color="#58636F", lw=0.7),
                color="#25303B")
    ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", pad=8)
    ax.set_xlim(0, 22)
    ax.set_ylim(-0.85, 2.75)
    ax.set_yticks([2, 1, 0], ["Peer → GPU\nhistorical KV", "DRAM → GPU\nhistorical KV",
                             "GPU compute\ncurrent token"])
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.tick_params(axis="y", length=0, pad=8, labelsize=9)
    ax.tick_params(axis="x", labelsize=9, length=3)
    for side in ["top", "left", "right"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#ABB3BA")
    ax.grid(axis="x", color="#EFF1F3", linewidth=0.6, zorder=0)


def main():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "svg.fonttype": "none", "axes.unicode_minus": False})
    scenarios = [
        ("all_dram", set(), "(a) All DRAM; layer-wise recovery"),
        ("first_layer_peer", {1}, "(b) Layer 1 in Peer HBM; layers 2–10 in DRAM"),
    ]
    fig, axs = plt.subplots(2, 1, figsize=(168 / 25.4, 150 / 25.4))
    fig.subplots_adjust(left=0.185, right=0.975, top=0.865, bottom=0.285, hspace=0.57)
    fig.suptitle("Overlap historical KV loading with current-token compute",
                 x=0.02, y=0.978, ha="left", fontsize=11, fontweight="bold")
    fig.text(0.02, 0.936, "ILLUSTRATIVE: 10 equal-size layers; independent transfer paths",
             fontsize=9, color="#505D68")
    table = []
    metrics = {}
    for ax, (name, peer, title) in zip(axs, scenarios):
        records, finish, loaded = schedule(peer)
        draw_panel(ax, records, finish, title)
        table.extend(dict(scenario=name, **record) for record in records)
        metrics[name] = {"decoder_complete_ms": finish,
                         "historical_kv_fully_loaded_ms": loaded,
                         "compute_wait_ms": sum(r["end_ms"] - r["start_ms"]
                                                for r in records if r["kind"] == "Wait")}
    axs[1].set_xlabel("Time since recovery GPU is ready (ms)", labelpad=6, fontsize=9)
    fig.legend(handles=[Patch(facecolor=COLORS["DRAM"], label="DRAM load"),
                        Patch(facecolor=COLORS["Peer"], label="Peer load"),
                        Patch(facecolor=COLORS["Compute"], label="Layer compute"),
                        Patch(facecolor="#E3E7EB", edgecolor="#77828E", hatch="////",
                              label="KV wait")],
               loc="lower center", bbox_to_anchor=(0.55, 0.142), ncol=4,
               frameon=False, fontsize=8.5, columnspacing=1.2, handlelength=1.4)
    fig.text(0.02, 0.117, "Numbers in bars are layer IDs; each KV load covers that layer's full history.",
             fontsize=8.5)
    fig.text(0.02, 0.083, "Per layer: DRAM 1 ms / Peer 0.1 ms / compute 2 ms. Schematic, not measured.",
             fontsize=8.5)
    fig.text(0.02, 0.049, "Next output requires all 10 layers + output head / sampling (head time omitted).",
             fontsize=8.5, fontweight="bold")
    fig.savefig(OUT / "timeline.png", dpi=300, facecolor="white")
    fig.savefig(OUT / "timeline.svg", facecolor="white")
    fig.savefig(OUT / "review-168mm-96dpi.png", dpi=96, facecolor="white")
    plt.close(fig)
    with (OUT / "schedule.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["scenario", "kind", "layer", "start_ms", "end_ms"])
        writer.writeheader()
        writer.writerows(table)
    metadata = {
        "evidence_type": "illustrative analytical schedule, not GPU measurements",
        "source_mechanism": "https://arxiv.org/html/2410.00428v3",
        "attribution": "Layer-wise management/transfer overlap is prior work; fault-recovery placement is an illustrative extension.",
        "review_width_mm": 168,
        "assumptions": {
            "layers": LAYERS, "equal_kv_bytes_per_layer": True,
            "dram_load_ms_per_layer": DRAM_MS, "peer_load_ms_per_layer": PEER_MS,
            "compute_ms_per_layer": COMPUTE_MS,
            "independent_transfer_queues": True,
            "fixed_effective_durations_without_shared_bottleneck": True,
            "weights_cursor_metadata_and_buffers_ready_at_zero": True,
            "recovery_gpu_can_retain_full_request_kv": True,
            "output_head_and_sampling_time_excluded": True,
            "peer_subset_need_not_have_dram_duplicate": True,
        },
        "results": metrics,
    }
    (OUT / "parameters.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
