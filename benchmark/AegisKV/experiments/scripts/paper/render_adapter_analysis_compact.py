"""Three-panel revision using saved analytical/queue data without rerunning it."""
from pathlib import Path
import csv
import json

import render_adapter_analysis as src
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def rows(name):
    with (src.DATA / name).open() as f:
        return [{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]


def main():
    previous = json.loads((src.OUT / "MANIFEST.json").read_text())
    for filename, digest in previous["csv_sha256"].items():
        assert src.sha(src.DATA / filename) == digest, filename
    typography = src.configure()
    plt.rcParams.update({"axes.spines.top":False, "axes.spines.right":False,
                         "axes.linewidth":.65, "pdf.fonttype":42, "svg.fonttype":"none"})
    rr, cr = rows("risk-curves.csv"), rows("recovery-curves.csv")
    risk = {h:[r for r in rr if r["MTBF_hours"] == h] for h in src.R["mean_time_between_failures_hours"]}
    recovery = {z:[r for r in cr if r["Z_tokens"] == z] for z in src.M["checkpoint_intervals_tokens"]}
    queue = rows("queue-summary.csv")
    fig, axs = plt.subplots(1, 3, figsize=(7, 3.4))
    fig.subplots_adjust(left=.084, right=.984, bottom=.275, top=.70, wspace=.46)
    for ax, old_panel in zip(axs, "acd"):
        src.draw_panel(ax, old_panel, risk, recovery, queue, previous["checkpoint_scan_minima"])
        ax.get_legend().remove()
        ax.set_title("")
        ax.set_title("", loc="left")
    a,b,c = axs
    for ax,title in zip(axs,["(a) Risk and checkpointing", "(b) Recovery latency", "(c) Foreground queueing"]):
        ax.set_title(title,loc="left",pad=36)
    a.set_xlabel("Checkpoint Z (tokens)")
    a.set_ylabel("Extra time (ms/min)")
    a.set_xticks([64, 256, 1024, 8192], labels=["64", "256", "1K", "8K"])
    a.texts[0].set_text("")
    handles=[Line2D([],[],color=src.COLORS[i],ls=src.STYLES[i],lw=1.65,
                    label=str(h)+" h") for i,h in enumerate(src.R["mean_time_between_failures_hours"])]
    a.legend(handles=handles,title="Assumed MTBF",ncol=3,loc="lower center",bbox_to_anchor=(.5,1.01),
             frameon=False,borderaxespad=0,handlelength=1.2,handletextpad=.25,columnspacing=.55)
    b.set_xlabel("Peer front layers L")
    b.set_ylabel("Mean recovery time (ms)")
    b.set_xticks([0, 8, 16, 24, 32])
    handles=[Line2D([],[],color=src.COLORS[i],ls=src.STYLES[i],marker=src.MARKERS[i],ms=3.5,
                    lw=1.65,label=str(z)) for i,z in enumerate(src.M["checkpoint_intervals_tokens"])]
    b.legend(handles=handles,title="Z (tokens)",ncol=3,loc="lower center",bbox_to_anchor=(.5,1.01),
             frameon=False,borderaxespad=0,handlelength=1.15,handletextpad=.2,columnspacing=.55)
    b.text(.045,.045,"L=0: DRAM-only",transform=b.transAxes,color="#555555")
    c.set_xlabel("Peer occupancy (GiB)")
    c.set_ylabel("Foreground P95 (s)")
    c.set_xticks([0, 8, 16, 24])
    handles=[Line2D([],[],color=src.COLORS[i],ls=src.STYLES[i],marker=src.MARKERS[i],
                    ms=5.5 if i==0 else 3.4,mfc="white",mew=1.1,lw=1.65,label=str(r))
             for i,r in enumerate(src.Q["arrival_rates_per_s"])]
    c.legend(handles=handles,title="Arrival rate (req/s)",ncol=2,loc="lower center",bbox_to_anchor=(.5,1.01),
             frameon=False,borderaxespad=0,handlelength=1.6,handletextpad=.35,columnspacing=1.2)
    fig.text(.5,.985,"Analytical recovery model and synthetic queue simulation",ha="center",va="top",weight="bold")
    fig.text(.084,.085,"(a,b) Assumed costs and checkpoint phases. (c) 95% CI over 10 synthetic streams.")
    fig.text(.084,.03,"No GPU measurements. Recovery includes tail replay and one resumed decode.",color="#555555")
    meta=src.save(fig,"adapter-analysis-compact")
    result={"evidence":src.CFG["evidence"],"layout":"one row, three panels; old a/c/d",
            "generator":str(Path(__file__).relative_to(src.ROOT)),"generator_sha256":src.sha(__file__),
            "shared_generator_sha256":src.sha(Path(src.__file__)),"typography":typography,
            "parent_manifest_sha256":src.sha(src.OUT/"MANIFEST.json"),
            "source_csv_sha256":previous["csv_sha256"],"figure":meta,
            "data_reused_without_regeneration":True,"new_simulation_runs":0,"physical_runs":0,
            "panel_mapping":{"a":"old a: risk cost","b":"old c: total recovery","c":"old d: foreground queue"},
            "main_curve_values_unchanged":True,"visual_review":"pending"}
    src.dump(src.OUT/"COMPACT_MANIFEST.json",result)
    print(json.dumps({"output":str(src.OUT/"adapter-analysis-compact.pdf"),"metadata":meta},indent=2))


if __name__=="__main__":
    main()
