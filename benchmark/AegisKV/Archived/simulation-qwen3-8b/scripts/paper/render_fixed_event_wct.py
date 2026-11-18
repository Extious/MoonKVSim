"""Render the same-ID incremental effect of the fixed 180 s added fault.

This script reads audited simulation artifacts; it does not run experiments.
The displayed cohort is the post-treatment union of direct victims, used only
for a descriptive event detail. All original row fields remain in the CSV.
"""
from __future__ import annotations

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
from paper_paths import ROOT

OUT = ROOT / "output/pdf/aegiskv-revision-20260909"
ART = ROOT / "output/aegiskv-revision-20260909/scaling-rate"
SOURCE = ART / "data/event-pairs.json"
ORDER = ROOT / "output/pdf/aegiskv-evaluation-20260909/eval-healthy-workflow.csv"
PREFIX_AUDIT = ART / "FIXED_EVENT_PREFIX_AUDIT.json"
NAME = "eval-fixed-event-wct"
SYSTEMS = tuple(style.COLORS)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    style.install(SimpleNamespace())
    OUT.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    assert source["status"] == "PASS"
    selected = [r for r in source["rows"]
                if r["failure_count"] == 2 and r["event_index"] == 1]
    event, = [e for e in source["events"]
              if e["failure_count"] == 2 and e["event_index"] == 1]
    with ORDER.open() as f:
        ranks = {r["workflow_id"]: int(r["workflow_rank"])
                 for r in csv.DictReader(f) if r["system"] == "mooncake"}
    ids = sorted(event["union_workflow_ids"], key=ranks.__getitem__)
    assert len(ids) == 7 and len(selected) == 21
    assert len({(r["workflow_id"], r["system"]) for r in selected}) == 21
    assert all({r["workflow_id"] for r in selected if r["system"] == s} == set(ids)
               for s in SYSTEMS)
    assert {r["workflow_id"] for r in selected if r["direct_victim_workflow"]} == set(ids)
    rows = []
    for s in SYSTEMS:
        for wid in ids:
            original, = [r for r in selected if r["system"] == s and r["workflow_id"] == wid]
            r = dict(original)
            assert r["failure_at_s"] == 180 and r["target_gpu_id"] == "gpu-2"
            assert r["prefix_control_failure_count"] == 1 and r["added_event_indices"] == "1"
            assert np.isclose(r["incremental_delta_s"],
                              r["f1_wct_s"] - r["prefix_control_wct_s"], rtol=0, atol=1e-10)
            assert r["direct_victim_workflow"] == (r["active_victim_workflow"] or r["queued_victim_workflow"])
            # Active takes precedence when a workflow has both active and queued
            # requests on the failed GPU. The two original flags remain intact.
            state = ("active" if r["active_victim_workflow"] else
                     "queued_only" if r["queued_victim_workflow"] else "not_direct")
            r.update(workflow_plot_position=ids.index(wid) + 1,
                     mooncake_f0_workflow_rank=ranks[wid], workflow_short_id=wid[:8],
                     plotted_wct_k1_s=r["prefix_control_wct_s"],
                     plotted_wct_k2_s=r["f1_wct_s"], plotted_delta_s=r["incremental_delta_s"],
                     plotted_victim_state=state)
            rows.append(r)

    fig, ax = style.canvas("Workflow ID (fixed Mooncake no-failure order)",
                           "Added-fault WCT change (s)\nWCT(K2) − WCT(K1)",
                           wide=True, height=3.4)
    fig.subplots_adjust(left=.135, right=.978, top=.745, bottom=.20)
    ax.axhline(0, color=style.GRAY, lw=.85, zorder=1)
    for s in SYSTEMS:
        sub = [r for r in rows if r["system"] == s]
        x = [r["workflow_plot_position"] for r in sub]
        y = [r["plotted_delta_s"] for r in sub]
        ax.plot(x, y, color=style.COLORS[s], ls=style.STYLES[s], lw=1.4, zorder=2)
        for r in sub:
            marker = style.MARKERS[s] if r["plotted_victim_state"] != "not_direct" else "x"
            # At b6f7c88d DRAM-only and AegisKV are exactly zero. Nested crosses
            # show both observations without moving their coordinates.
            size = (8.0 if s == "dram" else 5.4) if marker == "x" else 6.0
            face = style.COLORS[s] if r["plotted_victim_state"] == "active" else "white"
            ax.plot(r["workflow_plot_position"], r["plotted_delta_s"], linestyle="none",
                    marker=marker, markersize=size, markeredgewidth=1.15,
                    color=style.COLORS[s], markerfacecolor=face, zorder=4)
    ax.set_xlim(.68, 7.32)
    ax.set_xticks(range(1, 8), [wid[:8] for wid in ids])
    ax.set_ylim(-20, 130)
    ax.set_yticks([-20, 0, 20, 40, 60, 80, 100, 120])
    assert min(r["plotted_delta_s"] for r in rows) > -20
    assert max(r["plotted_delta_s"] for r in rows) < 130

    system_handles = [Line2D([], [], color=style.COLORS[s], ls=style.STYLES[s],
                            marker=style.MARKERS[s], ms=5.2, lw=1.4,
                            markerfacecolor=style.COLORS[s], label=style.LABELS[s])
                      for s in SYSTEMS]
    status_handles = [
        Line2D([], [], color=style.INK, ls="none", marker="o", ms=5.8,
               markerfacecolor=style.INK, label="Active victim"),
        Line2D([], [], color=style.INK, ls="none", marker="o", ms=5.8,
               markerfacecolor="white", label="Queued-only victim"),
        Line2D([], [], color=style.INK, ls="none", marker="x", ms=6,
               label="No direct victim"),
    ]
    for handles, y in [(system_handles, .974), (status_handles, .867)]:
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.555, y),
                   ncol=3, frameon=False, fontsize=10, handlelength=2.8,
                   columnspacing=1.4, handletextpad=.5, borderaxespad=0, borderpad=0)

    files = {}
    for ext in ["pdf", "svg", "png"]:
        path = OUT / f"{NAME}.{ext}"
        fig.savefig(path, dpi=220,
                    metadata={"Creator": "AegisKV fixed event matched workflow figure"} if ext == "pdf" else None)
        files[ext] = sha(path)
    plt.close(fig)
    with (OUT / f"{NAME}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    files["csv"] = sha(OUT / f"{NAME}.csv")

    with pymupdf.open(OUT / f"{NAME}.pdf") as doc:
        assert len(doc) == 1
        page = doc[0]
        assert abs(page.rect.width - 504) < .01 and abs(page.rect.height - 244.8) < .01
        spans = [s for b in page.get_text("dict")["blocks"] if "lines" in b
                 for line in b["lines"] for s in line["spans"] if s["text"].strip()]
        assert min(s["size"] for s in spans) >= 9.9
        assert all(s["bbox"][0] >= -.1 and s["bbox"][1] >= -.1
                   and s["bbox"][2] <= page.rect.width + .1
                   and s["bbox"][3] <= page.rect.height + .1 for s in spans)
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(OUT / f"{NAME}-pdf-preview.png")
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY,
                        alpha=False).save(OUT / f"{NAME}-grayscale.png")

    caption = (
        "固定追加故障对同一 Workflow 的 WCT 影响。K1 和 K2 均在 60 s 对 GPU 0 注入一次故障；"
        "K2 仅额外在 180 s 对 GPU 2 注入一次故障，每次停机 120 s。每点为同系统、同 ID 的 "
        "WCT(K2)−WCT(K1)，不是相对无故障条件的增量；负值完整保留。横轴是三系统在追加故障中"
        "直接 active/queued 受害 Workflow 的共同并集，共 7 个对象，按已有 Mooncake 无故障 WCT "
        "顺序排列，三系统均展示同一组对象。实心表示含 active 受害请求，空心表示只有 queued "
        "受害请求，叉号表示该系统无直接受害请求；同时包含 active 和 queued 时采用实心。"
        "此并集是事后描述性分组，不是预定义因果 cohort，不代表全部 160 个 Workflow 的效果。"
        "每个系统每种日程一次模拟，共复用 6 次执行；7 个对象并非独立重复，连线只帮助按 ID 对照。"
        "该图不单独证明 Peer HBM 恢复收益。"
    )
    caption_en = (
        "Effect of one fixed added fault on the same workflows. K1 and K2 share the GPU 0 fault at 60 s; "
        "K2 adds only a GPU 2 fault at 180 s, with 120 s downtime per fault. Each point is the same-system, "
        "same-ID difference WCT(K2) minus WCT(K1), not a fault-free contrast; negative values are retained. "
        "All three systems show the same seven-workflow union of directly active or queued victims at the "
        "added fault, in the existing Mooncake fault-free WCT order. Filled markers indicate active victims "
        "(including workflows also having queued victims), hollow markers queued-only victims, and crosses "
        "no direct victim. This is a post-treatment descriptive union, not a prespecified causal cohort or "
        "an estimate for all 160 workflows. One simulation per system per schedule, reusing six executions; "
        "workflows are not independent repeats, and connecting lines only aid same-ID comparison. "
        "The figure alone does not establish a Peer HBM recovery benefit."
    )
    inputs = {str(SOURCE.relative_to(ROOT)): hashlib.sha256(source_bytes).hexdigest(),
              str(ORDER.relative_to(ROOT)): sha(ORDER),
              str(Path(__file__).resolve().relative_to(ROOT)): sha(Path(__file__).resolve()),
              str(Path(style.__file__).resolve().relative_to(ROOT)): sha(Path(style.__file__).resolve())}
    prefix = {"status": "PENDING", "path": str(PREFIX_AUDIT.relative_to(ROOT))}
    if PREFIX_AUDIT.exists():
        prefix_bytes = PREFIX_AUDIT.read_bytes()
        audit = json.loads(prefix_bytes)
        prefix["status"] = audit.get("status", "UNSPECIFIED")
        inputs[str(PREFIX_AUDIT.relative_to(ROOT))] = hashlib.sha256(prefix_bytes).hexdigest()
    manifest = {
        "figures": [{"name": NAME, "title": "固定追加故障对同一Workflow的WCT影响",
                     "caption": caption, "caption_en": caption_en,
                     "width_in": 7.0, "height_in": 3.4,
                     "evidence": "uncalibrated_frozen_algorithm_external_fault_simulation",
                     "files": files, "plotted_rows": 21, "workflow_count": 7,
                     "reused_execution_count": 6, "new_experiments_by_renderer": 0,
                     "visual_review": "PENDING"}],
        "inputs": inputs, "prefix_audit": prefix,
        "plot_spec": {
            "question": "How does adding the fixed 180 s fault change each displayed workflow's WCT?",
            "cohort": "post-treatment direct-victim union; descriptive only",
            "ordering": "existing Mooncake fault-free WCT rank",
            "workflow_ids": ids,
            "ordinate": "same-system WCT(K2) - WCT(K1), absolute seconds",
            "victim_state": "active precedence, then queued-only, otherwise no direct victim",
            "negative_value_count": sum(r["plotted_delta_s"] < 0 for r in rows),
            "zero_value_count": sum(r["plotted_delta_s"] == 0 for r in rows),
            "all_original_event_pair_fields_preserved": True,
            "overlapping_zero_crosses": "different marker sizes retain both exact coordinates; no jitter",
            "no_statistics_over_heterogeneous_raw_wct": True,
        },
        "reference": {
            "path": "output/pdf/aegiskv-revision-20260909/eval-workflow-delay-pdf-preview.png",
            "borrowed": "same system colors, line patterns, independent legend band, absolute seconds and zero line",
        },
        "review": {"pdf_size_in": [7, 3.4], "minimum_font_pt": min(s["size"] for s in spans),
                   "all_text_inside_page": True, "status": "PENDING_ACTUAL_IMAGE_REVIEW"},
    }
    (OUT / "fixed-event-wct-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"name": NAME, "rows": len(rows), "workflow_ids": ids,
                      "prefix_audit": prefix, "pdf_sha256": files["pdf"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
