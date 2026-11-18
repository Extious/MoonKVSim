"""Algorithm 3 mechanism candidate: analytic recovery + synthetic M/D/c queues.

All timing, risk and traffic values are declared assumptions. No model execution,
GPU tools, native attention traces, or measured timing inputs are used.
"""
from __future__ import annotations

import csv
import hashlib
import heapq
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-adapter-analysis-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fitz
from PIL import Image

from design_plot_typography import configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/adapter-analysis"
OUT = ROOT / "output/pdf/aegiskv-adapter-analysis-20260919"
CFG = json.loads((DATA / "config.json").read_text())
M, R, Q = CFG["model"], CFG["risk"], CFG["queue"]
H = M["layers"]
BLOCK_BYTES = M["block_tokens"] * M["kv_bytes_per_token_per_layer"]
HOT_MS = M["hot_blocks_per_layer"] * BLOCK_BYTES / (M["bandwidth_GB_s"] * 1e9) * 1000
MISS_MS = M["demand_miss_blocks_per_layer"] * BLOCK_BYTES / (M["bandwidth_GB_s"] * 1e9) * 1000
COLORS = ["#0072B2", "#D55E00", "#009E73"]
STYLES = ["-", "--", "-."]
MARKERS = ["o", "s", "^"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def csv_write(name, rows):
    with (DATA / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def compute_ms(n):
    # Endpoint includes one resumed decode, so even N=0 has positive work.
    return (M["compute_startup_ms_per_layer"] +
            M["compute_ms_per_tail_token_per_layer"] *
            (np.asarray(n) + M["next_decode_tokens"]))


def times(n, depth, bandwidth=None):
    """Exact homogeneous max-plus model with demand transfers at layer release.

    Hot preloads run in one serial stream during compute or exposed hot waits.
    Each layer releases an unpredicted miss after the preceding layer finishes;
    that transfer preempts speculative preloads and contributes to the floor.
    """
    scale = M["bandwidth_GB_s"] / (bandwidth or M["bandwidth_GB_s"])
    p, q = HOT_MS * scale, MISS_MS * scale
    c = compute_ms(n)
    removable = p + (H - 1) * np.maximum(p - c, 0)
    wait = H * q + np.maximum(removable - depth * p, 0)
    return H * c + wait, wait


def event_schedule(n, depth, bandwidth=None):
    """Independent discrete event recurrence, without using the closed form."""
    scale = M["bandwidth_GB_s"] / (bandwidth or M["bandwidth_GB_s"])
    p, q, c = HOT_MS * scale, MISS_MS * scale, float(compute_ms(n))
    remaining = np.full(H, p)
    remaining[:depth] = 0
    now = 0.0
    events = []
    moved = 0.0
    for layer in range(H):
        previous = now
        now += q
        moved += q
        now += remaining[layer]
        moved += remaining[layer]
        remaining[layer] = 0
        start = now
        available = c
        for future in range(layer + 1, H):
            copied = min(remaining[future], available)
            remaining[future] -= copied
            available -= copied
            moved += copied
            if available <= 1e-12:
                break
        now += c
        events.append({"N_tokens": n, "L_layers": depth, "layer": layer + 1,
                       "compute_start_ms": start, "compute_finish_ms": now,
                       "exposed_wait_ms": start - previous})
    assert np.isclose(moved, H * q + (H - depth) * p)
    return now, sum(e["exposed_wait_ms"] for e in events), events


def recovery_data():
    curves, rows, summaries = {}, [], []
    # Deterministic equal-weight phase enumeration. No sampling error bars.
    for z in M["checkpoint_intervals_tokens"]:
        n = np.arange(z) + M["commit_lag_tokens"]
        base, _ = times(n, 0)
        group = []
        for depth in range(H + 1):
            total, wait = times(n, depth)
            row = dict(Z_tokens=z, L_layers=depth, phase_states=len(n),
                       min_N_tokens=int(n.min()), max_N_tokens=int(n.max()),
                       mean_N_tokens=float(n.mean()),
                       peer_MiB=depth * M["hot_blocks_per_layer"] * BLOCK_BYTES / 2**20,
                       mean_saved_wait_ms=float(np.mean(base - total)),
                       mean_wait_ms=float(wait.mean()),
                       mean_total_recovery_ms=float(total.mean()),
                       phase_p95_total_recovery_ms=float(np.quantile(total, .95)))
            group.append(row)
        curves[z] = group
        rows.extend(group)
        gains = np.array([r["mean_saved_wait_ms"] for r in group])
        summaries.append(dict(Z_tokens=z, baseline_ms=float(base.mean()),
                              full_peer_ms=group[-1]["mean_total_recovery_ms"],
                              maximum_mean_saving_ms=float(gains[-1]),
                              L_at_90pct_of_maximum_mean_saving=int(np.flatnonzero(gains >= .9*gains[-1])[0]),
                              exact_saturation_L=int(np.flatnonzero(np.isclose(gains, gains[-1], atol=1e-9, rtol=0))[0])))
    csv_write("recovery-curves.csv", rows)
    return curves, summaries


def risk_data():
    rows, curves, minima = [], {}, []
    zs = np.arange(R["Z_scan_min_tokens"], R["Z_scan_max_tokens"] + 1,
                   R["Z_scan_step_tokens"])
    for hours in R["mean_time_between_failures_hours"]:
        group = []
        for z in zs:
            total, _ = times(np.arange(z), 0)
            # Both terms have units seconds of extra work per useful second.
            checkpoint = R["fixed_exposed_checkpoint_cost_ms"] / 1000 * R["useful_decode_tokens_per_s"] / z
            recovery = float(total.mean()) / 1000 / (hours * 3600)
            group.append(dict(MTBF_hours=hours, Z_tokens=int(z),
                              checkpoint_ms_per_useful_minute=float(checkpoint * 60000),
                              recovery_ms_per_useful_minute=float(recovery * 60000),
                              extra_ms_per_useful_minute=float((checkpoint + recovery) * 60000)))
        best = min(group, key=lambda x: x["extra_ms_per_useful_minute"])
        minima.append(best)
        curves[hours] = group
        rows.extend(group)
    csv_write("risk-curves.csv", rows)
    return curves, minima


def memory_queue(arrivals, slots):
    """FCFS admission to fixed KV slots; no compute/bandwidth contention."""
    ends = [0.0] * slots
    heapq.heapify(ends)
    latency, starts = [], []
    for arrival in arrivals:
        start = max(float(arrival), heapq.heappop(ends))
        end = start + Q["service_time_s"]
        heapq.heappush(ends, end)
        latency.append(end - arrival)
        starts.append(start)
    return np.asarray(latency), np.asarray(starts)


def queue_data():
    raw, checks = [], []
    count = Q["warmup_requests"] + Q["scored_requests"]
    for rate in Q["arrival_rates_per_s"]:
        for seed in Q["seeds"]:
            # Same uniforms give paired request IDs across loads; exact same
            # arrivals and service times are reused across all Peer capacities.
            rng = np.random.default_rng(seed)
            arrivals = np.cumsum(rng.exponential(1 / rate, count))
            prior_latency = None
            for peer in Q["peer_residency_GiB"]:
                usable = Q["kv_pool_GiB"] - Q["foreground_headroom_GiB"] - peer
                slots = int(usable // Q["request_kv_GiB"])
                assert slots > 0 and rate * Q["service_time_s"] < slots
                latency, starts = memory_queue(arrivals, slots)
                if prior_latency is not None:
                    assert np.all(latency >= prior_latency - 1e-10)
                prior_latency = latency
                scored = latency[Q["warmup_requests"]:]
                raw.append(dict(arrival_rate_per_s=rate, seed=seed,
                                actual_peer_GiB=peer, foreground_slots=slots,
                                offered_slot_utilization=rate*Q["service_time_s"]/slots,
                                completed_requests=count, scored_requests=len(scored),
                                timeouts=0, failures=0, dropped=0,
                                p95_latency_s=float(np.quantile(scored, .95)),
                                mean_latency_s=float(scored.mean()),
                                mean_admission_wait_s=float(scored.mean()-Q["service_time_s"]),
                                last_completion_s=float(starts[-1]+Q["service_time_s"])))
    aggregate = []
    for rate in Q["arrival_rates_per_s"]:
        for peer in Q["peer_residency_GiB"]:
            group = [r for r in raw if r["arrival_rate_per_s"] == rate and r["actual_peer_GiB"] == peer]
            p95 = np.array([r["p95_latency_s"] for r in group])
            # Student-t interval over 10 independent synthetic arrival streams.
            assert len(p95) == 10
            half = 2.2621571628540993 * float(np.std(p95, ddof=1)) / np.sqrt(len(p95))
            aggregate.append(dict(arrival_rate_per_s=rate, actual_peer_GiB=peer,
                                  independent_streams=len(p95), mean_run_p95_s=float(p95.mean()),
                                  ci95_lower_s=float(p95.mean()-half), ci95_upper_s=float(p95.mean()+half)))
    csv_write("queue-runs.csv", raw)
    csv_write("queue-summary.csv", aggregate)
    return aggregate, len(raw)


def validate():
    # Compare an independently implemented causal event schedule to all plotted
    # depths for representative tail lengths and multiple link bandwidths.
    checked, events = 0, []
    for bw in (6.25, 12.5, 25, 100):
        for n in (0, 1, 32, 63, 127, 255, 511, 1023, 8191):
            previous = None
            for depth in range(H + 1):
                total, wait, trace = event_schedule(n, depth, bw)
                analytic = times(n, depth, bw)
                assert np.allclose((total, wait), analytic, atol=1e-8, rtol=0)
                deadlines = np.array([e["compute_finish_ms"] for e in trace])
                if previous is not None:
                    assert np.all(deadlines <= previous + 1e-8)
                previous = deadlines
                checked += 1
                if bw == M["bandwidth_GB_s"] and n in (0, 63, 1023) and depth in (0, 4, 16, 32):
                    events.extend(trace)
    csv_write("example-layer-events.csv", events)
    # Counterexamples: fast transfers flatten the layer benefit; lag may exceed Z.
    sensitivity = []
    for bw in (6.25, 25, 100):
        for z in M["checkpoint_intervals_tokens"]:
            for lag in (0, 128):
                n = np.arange(z) + lag
                base, _ = times(n, 0, bw)
                for depth in range(H + 1):
                    total, _ = times(n, depth, bw)
                    sensitivity.append(dict(bandwidth_GB_s=bw, Z_tokens=z,
                                            commit_lag_tokens=lag, max_N_tokens=int(n.max()),
                                            L_layers=depth, mean_saved_wait_ms=float((base-total).mean()),
                                            mean_total_ms=float(total.mean())))
    csv_write("sensitivity.csv", sensitivity)
    # Small hand-solvable admission examples check warm/cold queue behavior.
    assert np.allclose(memory_queue(np.array([0., 0., 0.]), 1)[0], [1, 2, 3])
    assert np.allclose(memory_queue(np.array([0., 0., 0.]), 2)[0], [1, 1, 2])
    return dict(event_schedule_vs_closed_form_states=checked,
                layer_deadlines_never_later_with_more_initial_residency=True,
                copy_byte_conservation=True, hand_solved_queue_checks=2,
                physical_runs=0, modeled_endpoint="reconstruct known tail and complete one resumed decode")


def decorate(ax, title):
    ax.set_title(title, loc="left", pad=37)
    ax.grid(axis="y", color="#E6E6E6", lw=.55)
    ax.set_axisbelow(True)
    ax.tick_params(length=3, pad=3)


def draw_panel(ax, panel, risk, recovery, queue, minima):
    if panel == "a":
        for i, hours in enumerate(R["mean_time_between_failures_hours"]):
            group = risk[hours]
            ax.plot([r["Z_tokens"] for r in group], [r["extra_ms_per_useful_minute"] for r in group],
                    color=COLORS[i], ls=STYLES[i], lw=1.65, label=f"{hours} h")
            best = minima[i]
            ax.plot(best["Z_tokens"], best["extra_ms_per_useful_minute"], marker=MARKERS[i],
                    color=COLORS[i], ms=5.5, mec="white", mew=.5, zorder=5)
        ax.set_xscale("log", base=2)
        ax.set_xticks([64, 256, 1024, 4096, 8192], labels=["64", "256", "1K", "4K", "8K"])
        ax.set_xlim(58, 9100)
        ax.set_yscale("log")
        ax.set_ylim(.16, 17)
        ax.set_yticks([.2, .5, 1, 2, 5, 10], labels=["0.2", "0.5", "1", "2", "5", "10"])
        ax.minorticks_off()
        ax.set_xlabel("Checkpoint interval Z (tokens)")
        ax.set_ylabel("Extra time (ms / useful minute)")
        ax.legend(title="Assumed MTBF", ncol=3, loc="lower left", bbox_to_anchor=(-.02, 1.01),
                  frameon=False, borderaxespad=0, columnspacing=.8, handlelength=1.8,
                  handletextpad=.35, title_fontsize=10.05)
        ax.text(.04, .91, "Markers: best scanned Z", transform=ax.transAxes, color="#555555")
        decorate(ax, "(a) Failure risk and checkpoint interval")
    elif panel in ("b", "c"):
        field = "mean_saved_wait_ms" if panel == "b" else "mean_total_recovery_ms"
        for i, z in enumerate(M["checkpoint_intervals_tokens"]):
            group = recovery[z]
            ax.plot([r["L_layers"] for r in group], [r[field] for r in group],
                    color=COLORS[i], ls=STYLES[i], marker=MARKERS[i], markevery=4,
                    ms=4, lw=1.65, label=f"Z={z}")
        ax.set(xlim=(-.6, 32.6), xticks=[0, 8, 16, 24, 32])
        ax.set_xlabel("Peer-resident front layers L")
        if panel == "b":
            ax.set_ylabel("Mean recovery wait saved (ms)")
            ax.set_ylim(-1, 53)
            decorate(ax, "(b) Average benefit of Peer layers")
        else:
            ax.set_ylabel("Mean total recovery time (ms)")
            ax.set_ylim(0, 155)
            decorate(ax, "(c) Recovery includes tail computation")
        ax.legend(ncol=3, loc="lower left", bbox_to_anchor=(-.02, 1.01), frameon=False,
                  borderaxespad=0, handlelength=1.7, columnspacing=.65, handletextpad=.3)
    else:
        for i, rate in enumerate(Q["arrival_rates_per_s"]):
            group = [r for r in queue if r["arrival_rate_per_s"] == rate]
            x = np.array([r["actual_peer_GiB"] for r in group])
            y = np.array([r["mean_run_p95_s"] for r in group])
            lo = np.array([r["ci95_lower_s"] for r in group])
            hi = np.array([r["ci95_upper_s"] for r in group])
            ax.errorbar(x, y, yerr=[y-lo, hi-y], color=COLORS[i], marker=MARKERS[i],
                        ls=STYLES[i], lw=1.65, ms=5.5 if i == 0 else 3.4,
                        mfc="white", mew=1.1, capsize=2.5,
                        label=f"{rate} req/s")
        ax.set(xlim=(-.6, 24.6), xticks=[0, 4, 8, 12, 16, 20, 24])
        ymax=max(r["ci95_upper_s"] for r in queue)
        ax.set_ylim(0, ymax*1.13)
        ax.set_xlabel("Actual Peer occupancy (GiB)")
        ax.set_ylabel("Foreground P95 latency (s)")
        ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(-.02, 1.01), frameon=False,
                  borderaxespad=0, handlelength=1.8, columnspacing=1.2)
        decorate(ax, "(d) Memory pressure and admission delay")


def save(fig, name):
    # Preserve the declared insertion width; do not bbox-crop the PDF.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    from matplotlib.text import Text
    for artist in fig.findobj(Text):
        if artist.get_visible() and artist.get_text():
            box = artist.get_window_extent(renderer)
            # Ignore axis offset text disabled by the log formatter.
            assert box.x0 >= -.75 and box.y0 >= -.75 and box.x1 <= fig.bbox.width+.75 and box.y1 <= fig.bbox.height+.75, (name, artist.get_text(), box)
    for ext in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=CFG["plot"]["dpi"], facecolor="white")
    doc = fitz.open(OUT / f"{name}.pdf")
    page = doc[0]
    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(OUT / f"{name}-pdf-preview.png")
    Image.open(OUT / f"{name}-pdf-preview.png").convert("L").save(OUT / f"{name}-gray.png")
    spans = [s for b in page.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line.get("spans", [])]
    meta = dict(width_in=page.rect.width/72, height_in=page.rect.height/72,
                minimum_pdf_font_pt=min(s["size"] for s in spans),
                exported_sha256={ext:sha(OUT / f"{name}.{ext}") for ext in ("pdf", "svg", "png")})
    doc.close()
    plt.close(fig)
    return meta


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    typography = configure()
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": .65, "pdf.fonttype": 42, "svg.fonttype": "none"})
    validation = validate()
    recovery, summaries = recovery_data()
    risk, minima = risk_data()
    queue, runs = queue_data()
    validation["synthetic_queue_runs"] = runs
    validation["paired_capacity_comparisons"] = True
    validation["all_synthetic_requests_drained_without_censoring"] = True
    fig, axs = plt.subplots(2, 2, figsize=(CFG["plot"]["width_in"], CFG["plot"]["height_in"]))
    fig.subplots_adjust(left=.103, right=.985, bottom=.16, top=.85, wspace=.38, hspace=.92)
    for ax, panel in zip(axs.flat, "abcd"):
        draw_panel(ax, panel, risk, recovery, queue, minima)
    fig.text(.5, .989, "Analytical recovery model and synthetic queue simulation", ha="center", va="top", weight="bold")
    fig.text(.103, .051, "(a-c) Equal-weight checkpoint phases; assumed costs.  (d) Mean of 10 run-level P95s.", ha="left")
    fig.text(.103, .024, "No GPU measurements. Error bars in (d): 95% CI across synthetic arrival streams.", ha="left", color="#555555")
    figures = {"adapter-analysis": save(fig, "adapter-analysis")}
    for panel in "abcd":
        fig, ax = plt.subplots(figsize=(3.5, 3.3))
        fig.subplots_adjust(left=.20, right=.97, bottom=.22, top=.72)
        draw_panel(ax, panel, risk, recovery, queue, minima)
        fig.text(.5, .025, "Synthetic queue model" if panel == "d" else "Analytical model; assumed parameters", ha="center", color="#555555")
        figures[f"adapter-analysis-{panel}"] = save(fig, f"adapter-analysis-{panel}")
    record = dict(evidence=CFG["evidence"], physical_runs=0,
                  config=CFG, config_sha256=sha(DATA / "config.json"),
                  generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(__file__),
                  typography=typography, hot_transfer_ms_per_layer=HOT_MS,
                  demand_transfer_ms_per_layer=MISS_MS, recovery_summary=summaries,
                  checkpoint_scan_minima=minima, validation=validation, figures=figures,
                  csv_sha256={p.name:sha(p) for p in sorted(DATA.glob("*.csv"))},
                  manuscript_replaced=False, visual_review="pending")
    dump(OUT / "MANIFEST.json", record)
    dump(DATA / "summary.json", {k:record[k] for k in ("evidence", "recovery_summary", "checkpoint_scan_minima", "validation")})
    print(json.dumps({"output":str(OUT), "recovery":summaries, "risk_minima":minima,
                      "queue_last_points":[r for r in queue if r["actual_peer_GiB"] == 24],
                      "validation":validation}, indent=2))


if __name__ == "__main__":
    main()
