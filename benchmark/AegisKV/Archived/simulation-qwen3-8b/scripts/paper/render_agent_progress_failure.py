"""Render paired 80%-Agent failure effects from completed frozen simulations."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pymupdf

import agent_lease_style as style


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    campaign, out = args.campaign.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    status = load(campaign / "STATUS.json")
    assert status["status"] == "PASS" and len(status["completed"]) == 24
    protocol = load(campaign / "PROTOCOL.json")
    systems = tuple(protocol["systems"])
    focus = protocol["workflow_id"]
    style.install(SimpleNamespace())
    inputs, summaries = {}, {}
    for case, system in status["completed"]:
        directory = campaign / "runs" / case
        path = directory / f"{system}.summary.json"
        manifest = load(directory / f"{system}.manifest.json")
        assert manifest["status"] == "PASS" and sha(path) == manifest["summary_sha256"]
        assert manifest["runner_sha256"] == protocol["runner_sha256"]
        assert manifest["source_snapshot_sha256"] == protocol["source_snapshot_sha256"]
        summaries[case, system] = load(path)
        inputs[str(path.relative_to(campaign))] = manifest["summary_sha256"]
    controls = {s: {w["workflow_id"]: w for w in summaries["f0", s]["workflows"]} for s in systems}
    ids = sorted(controls["mooncake"], key=lambda wid: (controls["mooncake"][wid]["wct_ns"], wid))
    rank = {wid: i+1 for i, wid in enumerate(ids)}
    assert len(ids) == 160
    rows, focus_rows, counts, records = [], [], {}, []
    for position in protocol["positions"]:
        case = position["case"]
        for s in systems:
            summary = summaries[case, s]
            event, = summary["failure_events"]
            assert event["logical_trigger"]["focus_span_id"] == position["span_id"]
            for w in summary["workflows"]:
                wid = w["workflow_id"]
                control = controls[s][wid]
                assert w["wct_ns"] - control["wct_ns"] == w["delta_wct_ns"]
                assert w["delta_completion_ns"] == w["delta_release_ns"] + w["delta_wct_ns"]
                r = dict(w, case=case, agent_position=position["position"], agent_label=position["label"],
                         system=s, workflow_rank=rank[wid], focus_workflow=wid == focus,
                         failure_at_s=event["timestamp_ns"]/1e9, failure_gpu=event["target_gpu_id"],
                         f0_wct_s=w["f0_wct_ns"]/1e9, f1_wct_s=w["wct_ns"]/1e9,
                         delta_wct_s=w["delta_wct_ns"]/1e9, delta_completion_s=w["delta_completion_ns"]/1e9,
                         delta_release_s=w["delta_release_ns"]/1e9,
                         plotted_state="active" if w["active_victim"] else "queued_only" if w["queued_victim"] else
                                       "indirect" if w["indirect_wct_change"] else "unchanged")
                rows.append(r)
                if wid == focus:
                    details = next(x for x in summary["requests"] if x["span_id"] == position["span_id"])
                    r.update(focus_prompt_tokens=position["prompt_tokens"], focus_output_tokens=position["output_tokens"],
                             focus_completion_gpu=details["gpu_id"], focus_route_version=details["route_version"],
                             focus_restored_peer_tokens=details["restored_peer_tokens"],
                             focus_restored_dram_tokens=details["restored_store_tokens"],
                             focus_recomputed_tokens=details["recompute_tokens"])
                    focus_rows.append(r)
            if case == "a7":
                group = [r for r in rows if r["case"] == case and r["system"] == s]
                counts[s] = {"failure_at_s": event["timestamp_ns"]/1e9, "failure_gpu": event["target_gpu_id"],
                             "active": sum(r["active_victim"] for r in group),
                             "queued_only": sum(r["plotted_state"] == "queued_only" for r in group),
                             "indirect": sum(r["indirect_wct_change"] for r in group),
                             "unchanged": sum(r["plotted_state"] == "unchanged" for r in group),
                             "focal_f0_wct_s": controls[s][focus]["wct_ns"]/1e9,
                             "focal_delta_s": next(r["delta_wct_s"] for r in group if r["focus_workflow"])}

    def csv_file(name, selected):
        keys = list(dict.fromkeys(k for r in selected for k in r))
        with (out / name).open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader(); writer.writerows(selected)

    csv_file("agent80-all-workflows.csv", rows)
    csv_file("agent80-focus-positions.csv", focus_rows)
    final_rows = [r for r in rows if r["case"] == "a7"]
    csv_file("eval-agent80-workflow-wct.csv", final_rows)
    csv_file("eval-agent80-position-wct.csv", focus_rows)

    def finish(fig, name, caption):
        files = {}
        for ext in ("pdf", "svg", "png"):
            p = out / f"{name}.{ext}"
            fig.savefig(p, dpi=220)
            files[ext] = sha(p)
        files["csv"] = sha(out / f"{name}.csv")
        with pymupdf.open(out / f"{name}.pdf") as doc:
            page = doc[0]
            spans = [s for b in page.get_text("dict")["blocks"] if "lines" in b
                     for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            metadata = {"width_pt": page.rect.width, "height_pt": page.rect.height,
                        "min_font_pt": min(s["size"] for s in spans),
                        "text_within_page": all(-.1 <= s["bbox"][0] and -.1 <= s["bbox"][1] and
                            s["bbox"][2] <= page.rect.width+.1 and s["bbox"][3] <= page.rect.height+.1 for s in spans)}
            assert abs(page.rect.width - 504) < .1 and metadata["text_within_page"]
            assert metadata["min_font_pt"] >= 9.9
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(out / f"{name}-pdf-preview.png")
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY, alpha=False).save(out / f"{name}-grayscale.png")
        records.append({"name": name, "caption": caption, "files": files, "metadata": metadata,
                        "title": "最后一个 Agent 的进度触发故障对全部 Workflow 的影响" if name.endswith("workflow-wct") else "同一 Workflow 在不同 Agent 位置发生故障的 WCT 变化",
                        "width_in": float(fig.get_figwidth()), "height_in": float(fig.get_figheight()),
                        "evidence": "source_v3_uncalibrated_progress_conditioned_DES",
                        "caption_en": ("Same-system WCT(F1) minus WCT(F0) for all 160 workflow IDs. A single GPU failure is triggered when the fixed workflow's final Agent first crosses 80% of input-plus-output tokens. The shaded band marks the focus; the lower rows identify active, queued-only and indirect WCT effects. Each system contributes one F0/F1 pair, with 1,304 requests in one DAG round per run. Negative and zero effects are retained; timing is uncalibrated DES."
                                       if name.endswith("workflow-wct") else
                                       "The same focal workflow is compared across seven separately injected Agent positions. Each run fails the focus Agent's natural GPU at 80% of input-plus-output tokens for 120 seconds. A2-A6 are parallel branches, not a temporal sequence. Three systems times seven positions give 21 F1 runs, paired with three shared F0 controls. One complete 160-workflow simulation per condition; collateral victims differ naturally."),
                        "visual_review": "PENDING", "insertion_width_mm": 177.8})
        plt.close(fig)

    fig = plt.figure(figsize=(7, 4.65))
    ax = fig.add_axes([.145, .373, .835, .445])
    rug = fig.add_axes([.145, .172, .835, .129], sharex=ax)
    ax.set_ylabel("WCT(F1) − WCT(F0) (s)")
    ax.grid(axis="y", color="#DFE5EA", lw=.55)
    ax.axhline(0, color=style.GRAY, lw=.8)
    for s in systems:
        sub = sorted((r for r in final_rows if r["system"] == s), key=lambda r: r["workflow_rank"])
        ax.plot([r["workflow_rank"] for r in sub], [r["delta_wct_s"] for r in sub],
                color=style.COLORS[s], ls=style.STYLES[s], lw=1.15, label=style.LABELS[s])
        for state, face in [("active", style.COLORS[s]), ("queued_only", "white")]:
            hit = [r for r in sub if r["plotted_state"] == state]
            ax.scatter([r["workflow_rank"] for r in hit], [r["delta_wct_s"] for r in hit],
                       marker=style.MARKERS[s], s=23, edgecolors=style.COLORS[s], facecolors=face, linewidths=.85, zorder=4)
        y = 2 - systems.index(s)
        for r in sub:
            state = r["plotted_state"]
            if state == "unchanged":
                continue
            rug.plot(r["workflow_rank"], y, marker="x" if state == "indirect" else style.MARKERS[s],
                     ls="none", ms=3.5 if state == "indirect" else 4.5, mew=.75,
                     color=style.COLORS[s], mfc=style.COLORS[s] if state == "active" else "white")
    for plot in (ax, rug):
        plot.axvspan(rank[focus]-.65, rank[focus]+.65, color="#D2DCE5", alpha=.60, zorder=0)
        plot.set_xlim(.2, 160.8)
    values = [r["delta_wct_s"] for r in final_rows]
    low, high = min(0, min(values)), max(0, max(values))
    span = max(1, high-low)
    ax.set_ylim(low-.10*span, high+.16*span)
    ax.annotate(f"Focus {focus}: final Agent at 80%", xy=(rank[focus], high+.04*span),
                xytext=(.02, .93), textcoords="axes fraction", fontsize=10,
                arrowprops=dict(arrowstyle="->", lw=.75, color=style.INK), ha="left")
    ax.tick_params(labelbottom=False)
    rug.set_yticks([2, 1, 0], ["Mooncake", "DRAM-only", "AegisKV"])
    rug.set_ylim(-.55, 2.55)
    rug.set_xticks([1, 40, 80, 120, 160])
    rug.tick_params(axis="y", length=0, pad=5)
    rug.set_xlabel("Workflow (fixed Mooncake F0 order)")
    rug.spines["left"].set_visible(False)
    fig.text(.145, .322, "Affected Workflow IDs (same horizontal order)", fontsize=10)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.545, .99),
               ncol=3, frameon=False, handlelength=2.8, columnspacing=1.1, handletextpad=.4)
    handles = [Line2D([], [], color=style.INK, marker="o", ls="none", mfc=style.INK, ms=4.5, label="Active victim"),
               Line2D([], [], color=style.INK, marker="o", ls="none", mfc="white", ms=4.5, label="Queued-only"),
               Line2D([], [], color=style.INK, marker="x", ls="none", ms=4.5, label="Indirect WCT change")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.545, .913), ncol=3, frameon=False,
               handletextpad=.35, columnspacing=1.3)
    times = " / ".join(f'{counts[s]["failure_at_s"]:.3f}' for s in systems)
    fig.text(.145, .017, f"Failure: {times} s (legend order); GPU4 down for 120 s", fontsize=10)
    finish(fig, "eval-agent80-workflow-wct", "全部160个同ID Workflow的同系统 WCT(F1)−WCT(F0)。在固定Workflow最后一个Agent的总token进度80%时，使其自然宿主GPU故障120s；三系统触发时刻可不同。阴影标焦点，底部标直接活跃、仅排队和无直接受害但WCT改变的对象。每系统一对F0/F1；一轮DAG，每运行1304请求；未标定DES，保留负值。")

    fig, ax = style.canvas("Target Agent (each at 80% total token progress)",
                           "Focus WCT(F1) − WCT(F0) (s)", wide=True, height=3.4)
    fig.subplots_adjust(left=.145, right=.978, bottom=.255, top=.785)
    ax.axhline(0, color=style.GRAY, lw=.8)
    ax.axvspan(1.5, 6.5, color="#E9EEF2", alpha=.6, zorder=0)
    for s in systems:
        sub = sorted((r for r in focus_rows if r["system"] == s), key=lambda r: r["agent_position"])
        style.line(ax, s, [r["agent_position"] for r in sub], [r["delta_wct_s"] for r in sub], markers=True)
    ax.set_xticks(range(1, 8), ["A1\nPrerequisite", "A2\nBranch 1", "A3\nBranch 2", "A4\nBranch 3", "A5\nBranch 4", "A6\nBranch 5", "A7\nFinal"])
    ax.set_xlim(.8, 7.2)
    values = [r["delta_wct_s"] for r in focus_rows]
    low, high = min(0, min(values)), max(0, max(values)); span = max(1, high-low)
    ax.set_ylim(low-.12*span, high+.14*span)
    legend = style.legend(ax)
    legend.set_bbox_to_anchor((.55, .97), transform=fig.transFigure)
    fig.text(.56, .846, f"Workflow {focus}: A1 → parallel A2–A6 → A7", ha="center", fontsize=10)
    finish(fig, "eval-agent80-position-wct", "固定同一个Workflow，在A1前置、A2–A6并行分支和A7汇合请求各自总token进度80%处分别注入一次自然宿主GPU故障，停机120s。纵轴为同系统同焦点Workflow相对无故障的WCT变化。三系统×七位置=21次F1，复用三次F0；每条件一次完整160-Workflow模拟。A2–A6是并行分支编号，不是时间顺序；附带受害集合自然变化。")
    report = {"schema": "aegiskv.agent80_figures.v1", "protocol_sha256": sha(campaign/"PROTOCOL.json"),
              "renderer_sha256": sha(__file__), "source_snapshot_sha256": protocol["source_snapshot_sha256"],
              "inputs": inputs, "figures": records, "focus_workflow": focus,
              "focus_plot_rank": rank[focus], "final_agent_counts": counts,
              "runs": {"F0": 3, "F1": 21, "total": 24, "repeats_per_condition": 1},
              "plotted_workflow_pairs": len(final_rows), "agent_position_pairs": len(focus_rows),
              "all_workflow_pairs": len(rows)}
    with pymupdf.open() as proof:
        for number, record in enumerate(records, 8):
            page = proof.new_page(width=612, height=792)
            page.insert_text((54, 40), "Agent-progress failure experiment: placement proof", fontsize=11)
            with pymupdf.open(out/f'{record["name"]}.pdf') as source:
                height = source[0].rect.height
                page.show_pdf_page(pymupdf.Rect(54, 64, 558, 64+height), source, 0)
            caption = f'Figure {number}. '+record["caption_en"]
            remaining = page.insert_textbox(pymupdf.Rect(54, 82+height, 558, 700), caption,
                                            fontsize=10, fontname="helv", lineheight=1.35)
            assert remaining >= 0, "placement caption overflow"
            page.insert_text((54, 748), "Figure width: 177.8 mm (504 pt). Native vector PDF; caption: 10 pt.", fontsize=10)
        proof_path = out/"agent80-placement.pdf"
        proof.save(proof_path)
        for i, page in enumerate(proof, 1):
            page.get_pixmap(matrix=pymupdf.Matrix(1.65, 1.65), alpha=False).save(out/f"agent80-placement-page-{i}.png")
    report["placement_proof"] = {"pdf": "agent80-placement.pdf", "sha256": sha(proof_path), "pages": 2, "width_mm": 177.8}
    (out/"agent80-figure-manifest.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"counts": counts, "focus_rank": rank[focus], "figures": [f["name"] for f in records]}, indent=2))


if __name__ == "__main__":
    main()
