"""Re-layout the existing, calibrated recovery illustration at 7-inch width.

No data or scheduling model changes. The old 10-inch figure is retained.
Only the named pipeline calculation is used; archived evaluation is not run.
"""
import json
from pathlib import Path

import render_draft_20260915 as src
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np


def main():
    src.OUT = src.OUT / "design-paper"
    h = src.u_profile("MiniCPM4-8B", quantity="preload")
    k, floor, scan = src.topk_peer_frontier(h, src.U_REQ, src.C_MS, src.D_MS)
    row = next(r for r in src.LAT_META_M["rows"] if r["context"] == src.CTX_REF)
    history_s = float(row["prefill_median_s"])
    tail_s = src.LAYERS * src.C_MS / 1000
    fig = plt.figure(figsize=(7, 6.5))
    legend = [Patch(color=src.BLUE, label="Preload / full KV"),
              Patch(facecolor=src.ORANGE, edgecolor="white", hatch="///", label="Demand fetch"),
              Patch(color=src.PALE_BLUE, label="Cold KV"),
              Patch(color=src.GRAY, label="Tail compute"),
              Patch(color=src.RED, label="KV wait"),
              Patch(color=src.PURPLE, label="History prefill")]
    fig.legend(handles=legend, loc="upper center", bbox_to_anchor=(.51, .995), ncol=3,
               handlelength=1.15, columnspacing=1.2, handletextpad=.4)
    full = fig.add_axes([.13, .756, .84, .105])
    full.barh(0, history_s, height=.62, color=src.PURPLE)
    full.barh(0, tail_s, left=history_s, height=.62, color=src.GRAY)
    full.text(history_s/2, 0, f"32K history: {history_s:.2f} s", ha="center", va="center", color="white")
    full.text(history_s+tail_s+.14, 0, f"{history_s+tail_s:.2f} s", va="center")
    full.set(xlim=(0, 6.0), ylim=(-.65, .65), yticks=[0], yticklabels=["Compute"], xticks=range(7))
    full.tick_params(axis="y", length=0)
    full.set_xlabel("Time (s) — no KV restore")
    fig.text(.13, .874, "(a) Recompute history + known tail", weight="bold")
    fig.text(.13, .660, "(b–e) Restore KV + recompute the same tail", weight="bold")
    fig.text(.13, .627, "Expanded millisecond scale; tail = 64 tokens")
    labels = ["(b) Token-block order", "(c) Layer-major, full KV",
              "(d) Layer-major, preload + demand", f"(e) Peer hot set: first {k} layers ({k*h*32:.0f} MiB)"]
    waits, totals, transfer_summaries = [], [], []
    for i, label in enumerate(labels):
        y = .484 - i*.127
        ax = fig.add_axes([.13, y, .84, .086])
        if i < 2:
            _, start, finish = src.pipeline(0, src.D_MS, src.C_MS, layer_major=(i == 1))
            transfers = [("preload", l, l*src.D_MS, src.D_MS) for l in range(src.LAYERS)]
        else:
            start, finish, transfers = src.sparse_pipeline(0 if i == 2 else k, h, src.U_REQ, src.C_MS, src.D_MS)
        for kind, _, left, duration in transfers:
            ax.barh(1, duration, left=left, height=.68,
                    color={"preload":src.BLUE, "demand":src.ORANGE, "cold":src.PALE_BLUE}[kind],
                    edgecolor="white", lw=.25, hatch="///" if kind == "demand" else None)
        for l in range(src.LAYERS):
            prev = finish[l-1] if l else 0
            if start[l] > prev:
                ax.barh(0, start[l]-prev, left=prev, height=.68, color=src.RED)
            ax.barh(0, src.C_MS, left=start[l], height=.68, color=src.GRAY, edgecolor="white", lw=.3)
        wait = float(finish[-1]-src.LAYERS*src.C_MS)
        waits.append(wait)
        totals.append(float(finish[-1]))
        transfer_summaries.append({kind:sum(d for t,_,_,d in transfers if t==kind) for kind in ["preload","demand","cold"]})
        ax.set(xlim=(0, 310), ylim=(-.5, 1.5), yticks=[0,1], yticklabels=["Compute", "H2D"], xticks=np.arange(0,301,50))
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", labelbottom=(i==3))
        # The title, total, and wait occupy separate bands/positions.
        fig.text(.13, y+.099, label, weight="bold")
        fig.text(.97, y+.099, f"{finish[-1]:.0f} ms", ha="right")
        ax.text(finish[-1]+4, 0, f"{wait:.0f} ms wait", color=src.RED, va="center")
        if i==3:
            ax.set_xlabel("Time after take-over starts (ms)")
    old = json.loads((src.OUT.parent / "MANIFEST.json").read_text())
    previous = old["model_parameters"]["figure7_topk_pipeline"]
    assert np.allclose(waits, previous["exposed_wait_ms"], rtol=0, atol=1e-9)
    assert np.allclose(totals, previous["tail_completion_ms"], rtol=0, atol=1e-9)
    assert k == previous["peer_front_layers"]
    assert abs(k*h*32 - previous["peer_mib"]) < 1e-9
    src.save(fig, "design-layer-pipeline", evidence="calibrated analytic illustration", width_in=7,
             note="Layout-only revision of design-layer-pipeline. The existing causal, preemptible-copy model and "
                  "calibration are unchanged. Full-recompute panel composes a measured history prefill and calibrated "
                  "known-tail cost, not a one-shot or end-to-end measurement. Panel (a) seconds; (b-e) milliseconds. "
                  "Peer includes hot sets of a front-layer prefix; demand misses remain. Cold copies are after tail completion.",
             sources=[str(src.LATENCY["MiniCPM4-8B"].relative_to(src.ROOT)), str(src.REPLAY_JSON.relative_to(src.ROOT)),
                      str((src.SPARSE / "needed_fraction_models.csv").relative_to(src.ROOT)),
                      str(Path(src.__file__).relative_to(src.ROOT))])
    record = src.MANIFEST["design-layer-pipeline"]
    record.update(generator=str(Path(__file__).relative_to(src.ROOT)), generator_sha256=src.sha(Path(__file__)),
                  source_hashes={p:src.sha(src.ROOT/p) for p in record["sources"]},
                  h=h, effective_fraction=src.U_REQ, C_ms=src.C_MS, D_ms=src.D_MS,
                  peer_layers=k, peer_mib=k*h*32, demand_floor_ms=floor,
                  waits_ms=waits, totals_ms=totals, transfers_ms=transfer_summaries,
                  full_recompute_s=history_s+tail_s, frontier_scan=scan,
                  previous_manifest_sha256=src.sha(src.OUT.parent/"MANIFEST.json"))
    (src.OUT / "MANIFEST.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({k:record[k] for k in ["peer_layers","peer_mib","waits_ms","totals_ms","demand_floor_ms"]},indent=2))


if __name__ == "__main__":
    main()
