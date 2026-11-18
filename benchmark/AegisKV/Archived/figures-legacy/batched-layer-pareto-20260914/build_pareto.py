"""Exact Pareto classification of the existing 36 batch/residency configurations."""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE_DIR = OUT.parent / "batched-layer-pipeline-20260914"
SWEEP_DIR = OUT.parent / "batched-layer-sweep-20260914"
spec = importlib.util.spec_from_file_location("batch_base", BASE_DIR / "build_batched_pipeline.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pymupdf

BLUE, GREY, LIGHT = "#0072B2", "#8B929A", "#C3C8CE"


def write_json(name, data):
    (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")


def classify():
    c, d, size = base.layer_costs(32768, 512, 25)
    rows = []
    for b in range(1, 37):
        events = base.schedule(c, d, batch=b)
        rows.append({"batch": b, "cost_bytes": b*size, "wait": base.exact_wait(events),
                     "total_time": events[-1]["compute_end_ms"],
                     "partition": "+".join(str(x["layer_count"]) for x in events)})
    for p in rows:
        dominating = [q["batch"] for q in rows
                      if q["cost_bytes"] <= p["cost_bytes"] and q["wait"] <= p["wait"]
                      and (q["cost_bytes"] < p["cost_bytes"] or q["wait"] < p["wait"])]
        p["pareto"] = not dominating
        p["dominated_by"] = dominating
    # Independent monotone-cost record-minimum check, retaining exact ties.
    record_minimum = None
    scan = []
    for p in sorted(rows, key=lambda x: x["cost_bytes"]):
        if record_minimum is None or p["wait"] < record_minimum:
            scan.append(p["batch"])
            record_minimum = p["wait"]
    pareto = [p["batch"] for p in rows if p["pareto"]]
    assert pareto == scan == [1, 2, 3, 4, 5, 7, 8, 10, 13, 19, 20]
    assert rows[4]["wait"] == rows[5]["wait"] and rows[5]["dominated_by"] == [5]
    assert rows[7]["wait"] == rows[11]["wait"]  # 8 and 12: same wait, different cost.
    assert all(not p["pareto"] and 20 in p["dominated_by"] for p in rows[20:])
    # Fixed compute work means waiting and total recovery execution give the same frontier.
    assert all(p["total_time"]-p["wait"] == 36*c for p in rows)
    with (SWEEP_DIR / "batch-size-sweep.csv").open() as f:
        old = {int(r["batch_layers"]): r for r in csv.DictReader(f)
               if r["M"] == "32768" and r["N"] == "512"
               and float(r["effective_bandwidth_GB_s_assumed"]) == 25}
    assert len(old) == 36
    for p in rows:
        assert float(p["wait"]) == float(old[p["batch"]]["total_exposed_wait_ms"])
        assert p["cost_bytes"]/2**20 == float(old[p["batch"]]["initial_HBM_MiB"])
    public = [{"batch_layers": p["batch"], "initial_resident_layers": p["batch"],
               "initial_HBM_bytes": p["cost_bytes"], "initial_HBM_MiB": p["cost_bytes"]//2**20,
               "total_exposed_wait_ms": float(p["wait"]),
               "wait_exact_numerator": p["wait"].numerator, "wait_exact_denominator": p["wait"].denominator,
               "total_pipeline_ms": float(p["total_time"]), "batch_partition": p["partition"],
               "is_pareto": p["pareto"], "dominated_by_batch_layers": ";".join(map(str,p["dominated_by"]))}
              for p in rows]
    for name, values in (("pareto-classification.csv", public),
                         ("pareto-frontier.csv", [p for p in public if p["is_pareto"]])):
        with (OUT/name).open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(public[0]))
            writer.writeheader(); writer.writerows(values)
    write_json("validation.json", {
        "candidate_count": 36, "pareto_count": len(pareto), "dominated_count": 36-len(pareto),
        "pareto_batch_layers": pareto, "exact_pairwise_and_record_minimum_checks_agree": True,
        "original_sweep_points_matched": 36, "equal_wait_ties_checked": [[5,6],[8,12]],
        "cost_vs_total_execution_frontier_identical": True,
        "physical_experiments": 0, "independent_statistical_replicates": None,
    })
    return public


def plot(rows):
    fig = plt.figure(figsize=(178/25.4, 132/25.4))
    fig.text(.065, .941, "初始 HBM 容量与加载等待的帕累托取舍", fontsize=11.5)
    fig.text(.065, .900, "解析估算，非实测｜Qwen3-8B｜历史 32K，重放 512 token｜25 GB/s，100 TFLOP/s", fontsize=8.2)
    fig.text(.065, .858, "同时最小化初始 Peer HBM 占用与累计等待；比较全部 36 个分批配置。", fontsize=8.3)
    ax = fig.add_axes([.12, .260, .81, .465])
    bs = [p["batch_layers"] for p in rows]
    waits = [p["total_exposed_wait_ms"] for p in rows]
    ax.axvspan(20.5, 36.5, color="#F4F5F7", zorder=0)
    ax.plot(bs, waits, color=LIGHT, lw=1.0, zorder=1)
    dominated = [p for p in rows if not p["is_pareto"]]
    frontier = [p for p in rows if p["is_pareto"]]
    ax.scatter([p["batch_layers"] for p in dominated], [p["total_exposed_wait_ms"] for p in dominated],
               marker="x", s=28, linewidths=1.0, color=GREY, zorder=3)
    ax.scatter([p["batch_layers"] for p in frontier], [p["total_exposed_wait_ms"] for p in frontier],
               marker="o", s=34, color=BLUE, edgecolors="white", linewidths=.5, zorder=4)
    ax.set_xlim(0,37); ax.set_ylim(-1.0,25)
    ticks = [1, 6, 12, 18, 24, 30, 36]
    ax.set_xticks(ticks); ax.set_yticks([0,5,10,15,20,25]); ax.tick_params(labelsize=8.5)
    ax.set_xlabel("每批层数 / 初始驻留层数", fontsize=9, labelpad=6)
    ax.set_ylabel("累计加载等待（ms，越小越好）", fontsize=9)
    ax.set_axisbelow(True); ax.grid(alpha=.15)
    top = ax.secondary_xaxis("top", functions=(lambda v: v*128, lambda v: v/128))
    top.set_xticks([b*128 for b in ticks]); top.tick_params(labelsize=8.1, pad=4)
    top.set_xlabel("初始 Peer HBM 占用（MiB，越小越好）", fontsize=8.6, labelpad=7)
    fig.legend(handles=[Line2D([],[],marker="o",linestyle="none",color=BLUE,markersize=5.5,label="帕累托点"),
                        Line2D([],[],marker="x",linestyle="none",color=GREY,markersize=5.5,label="被支配点"),
                        Line2D([],[],linestyle="-",color=LIGHT,lw=1,label="原始扫描轨迹")],
               loc="center", bbox_to_anchor=(.525,.826), ncol=3, frameon=False,
               fontsize=8.5, handlelength=1.7, columnspacing=2)
    arrow = {"arrowstyle":"->", "lw":.7, "color":"#546978"}
    ax.annotate("5 层支配 6 层\n同等等待，少 128 MiB", xy=(6,waits[5]), xytext=(11,21.5),
                fontsize=8, ha="center", arrowprops=arrow)
    ax.annotate("13 层：1664 MiB\n等待 8.10 ms", xy=(13,waits[12]), xytext=(6,4.8),
                fontsize=8, ha="center", color=BLUE, arrowprops=arrow)
    ax.annotate("19 层：2432 MiB\n等待 1.09 ms", xy=(19,waits[18]), xytext=(25,9),
                fontsize=8, ha="center", color=BLUE, arrowprops=arrow)
    ax.annotate("20 层：2560 MiB\n等待 0 ms", xy=(20,0), xytext=(29,3.5),
                fontsize=8, ha="center", color=BLUE, arrowprops=arrow)
    ax.text(28.5,18,"21–36 层均被 20 层支配\n等待相同，初始占用更大", fontsize=8.3,
            ha="center", color="#68737D")
    fig.text(.065,.154,"蓝点对应层数：1–5、7、8、10、13、19、20；未指定成本权重，因此没有唯一最优点。",fontsize=8)
    fig.text(.065,.108,"被支配：存在另一个配置，占用与等待都不更差，并且至少一项严格更好。",fontsize=8.1)
    fig.text(.065,.062,"成本仅计初始 HBM 容量；沿用整批就绪、仅预取下一批规则，未计备份维护和前台竞争。",fontsize=7.9)
    for suffix in ("png","pdf","svg"):
        fig.savefig(OUT/f"batch-size-pareto.{suffix}",dpi=300,facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT/"batch-size-pareto.pdf") as pdf:
        assert abs(pdf[0].rect.width/72*25.4-178)<.01
        for dpi in (96,150):
            pdf[0].get_pixmap(dpi=dpi,alpha=False).save(OUT/f"batch-size-pareto.pdf-{dpi}dpi.png")


def main():
    rows = classify()
    plot(rows)
    write_json("parameters.json", {
        "M":32768,"N":512,"effective_bandwidth_GB_s_assumed":25,
        "effective_compute_TFLOP_s_assumed":100,"model":"Qwen3-8B","model_layers":36,
        "initial_resident_layers_equal_batch_layers":True,"batch_sizes":list(range(1,37)),
        "objectives":["minimize initial historical KV bytes in Peer HBM","minimize exposed loading wait"],
        "dominance":"No worse in both objectives and strictly better in at least one",
        "tie_handling":"Exact Fraction arithmetic; lower capacity dominates equal waiting",
        "cost_scope":"Initial HBM capacity only, not backup maintenance, money, lifetime HBM residency or foreground contention",
        "schedule":"Only next-batch prefetch; whole-batch readiness; actual partial tail; copied KV retained",
        "evidence":"Analytical, not measured or calibrated","unique_selected_optimum":None,
        "placed_width_mm":178,
    })
    source_paths=[BASE_DIR/"build_batched_pipeline.py",SWEEP_DIR/"batch-size-sweep.csv",SWEEP_DIR/"batch-size-detail.pdf"]
    write_json("MANIFEST.json", {
        "sources_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        "files_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in {".py",".csv",".json",".png",".pdf",".svg",".md"}
                         and p.name not in {"MANIFEST.json","REVIEW.json","figure-lesson.json"}},
    })
    print(json.dumps({"pareto_batch_layers":[r["batch_layers"] for r in rows if r["is_pareto"]],
                      "point_count":len(rows)},ensure_ascii=False))


if __name__ == "__main__":
    main()
