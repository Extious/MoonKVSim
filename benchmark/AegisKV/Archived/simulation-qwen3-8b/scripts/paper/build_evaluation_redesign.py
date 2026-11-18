"""Build the Evaluation redesign without overwriting frozen experiment records."""
from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
from pathlib import Path

from paper_paths import ROOT
from render_evaluation_redesign import ART, OUT, OLD, sha, SYSTEMS
from agent_lease_style import LABELS

DIR = ROOT / "benchmark/AegisKV/experiments"
TOOLS = Path(__file__).parent
TEMPLATE = TOOLS / "templates/evaluation-draft.md"


def rel(p):
    return os.path.relpath(p,DIR)


def table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","|"+"---|"*len(headers)]+
        ["| "+" | ".join(map(str,r))+" |" for r in rows])


def read_csv(path):
    with path.open() as f:return list(csv.DictReader(f))


def main():
    manifest=json.loads((OUT/"manifest.json").read_text())
    old=json.loads((ROOT/"output/agent-lease-20260908/paper-selection.json").read_text())
    prior=[r for r in old["figures"] if r["primary"] and r["section"] in ["Motivation","System Design"]]
    prior.sort(key=lambda r:int(r["id"]))
    figures=[]
    for r in prior:
        for ext in r["files"]:
            assert sha(OLD/f"{r['name']}.{ext}")==r["files"][ext]
            shutil.copy2(OLD/f"{r['name']}.{ext}",OUT/f"{r['name']}.{ext}")
        figures.append(dict(name=r["name"],title=r["draft_title"],caption=r["draft_caption"],
            caption_en=r["caption_en"],width_in=r["width_in"],height_in=r.get("height_in"),
            evidence=r["evidence"],files=r["files"],section=r["section"],inherited=True))
    for r in manifest["figures"]:
        if r["evidence"]=="layout_only_no_data":continue
        figures.append(dict(r,section="Evaluation",inherited=False))
    for i,r in enumerate(figures,1):
        r.update(id=str(i),primary=True)
    by_name={r["name"]:r for r in figures}
    template=(TOOLS/"templates/agent-lease-draft.md").read_text().split("## Evaluation",1)[0]+TEMPLATE.read_text()
    groups=[m[1].split(",") for m in re.finditer(r"\{\{(?:fig|row):([^}]+)\}\}",template)]
    assert [n for g in groups for n in g]==[r["name"] for r in figures]
    def preview(r):
        width=1008 if r["width_in"]>5 else 480
        return f'[<img src="{rel(OUT/(r["name"]+".png"))}" width="{width}" alt="{html.escape(r["id"]+" "+r["title"])}">]({rel(OUT/(r["name"]+".pdf"))})'
    def single(m):
        r=by_name[m[1]]
        return f'<a id="paper-{r["name"]}"></a>\n\n<figure class="paper-figure">\n\n{preview(r)}\n\n**图 {r["id"]}：{r["title"]}。** {r["caption"]}\n\n</figure>'
    def pair(m):
        rows=[by_name[n] for n in m[1].split(",")]
        assert len(rows)==2 and all(r["width_in"]<5 for r in rows)
        return "\n".join([*(f'<a id="paper-{r["name"]}"></a>' for r in rows),"",
            table([f'**图 {r["id"]}：{r["title"]}**' for r in rows],
                [[preview(r) for r in rows],[r["caption"] for r in rows]])])
    text=re.sub(r"\{\{fig:([^}]+)\}\}",single,template)
    text=re.sub(r"\{\{row:([^}]+)\}\}",pair,text)
    text=re.sub(r"\{\{ref:([^}]+)\}\}",lambda m:by_name[m[1]]["id"],text)
    summaries=json.loads((ART/"source-summaries.json").read_text())
    healthy=table(["系统","F0 平均 WCT (s)","WCT P95 (s)","TTFT P99 (s)","请求平均 TPOT 的 P99 (s)"],
        [[LABELS[s],*(f'{summaries[s][k]:.3f}' for k in ["mean_wct_s","p95_wct_s","p99_ttft_s","p99_request_tpot_s"])] for s in SYSTEMS])
    # This table explicitly labels request-average TPOT, never token-level TBT.
    resource=read_csv(OUT/"eval-healthy-resources.csv")
    metrics=[("Reference Python CPU","Python 参考 CPU 时间 (s)"),("Modeled CPU service","模拟 CPU 服务需求 (s)"),
        ("Foreground HBM wait","累计前台 HBM 等待 (s)"),("Scheduler queue P95","请求调度等待 P95 (s)"),
        ("DRAM + Peer write bytes","DRAM + Peer 写入 (TiB)"),("Foreground GET bytes","正常 GET (TiB)")]
    resources=table(["指标",*(LABELS[s] for s in SYSTEMS)],
        [[label,*(f'{float(next(r for r in resource if r["metric"]==key and r["system"]==s)["value"]):.3f}' for s in SYSTEMS)] for key,label in metrics])
    focal=read_csv(ART/"legacy-focal-workflows.csv")
    focal_table=table(["故障实例 / Workflow ID","系统","F0 WCT (s)","F1 WCT (s)","F1−F0 (s)"],
        [[r["case_id"]+" / "+r["workflow_id"],LABELS[r["system"]],*(f'{float(r[k]):.3f}' for k in ["f0_wct_s","f1_wct_s","delta_wct_s"])] for r in focal])
    fields=dict(healthy_table=healthy,resource_table=resources,focal_table=focal_table,
        aegis_mean=f'{summaries["aegis"]["mean_wct_s"]:.3f}',
        mean_overhead=f'{100*(summaries["aegis"]["mean_wct_s"]/summaries["mooncake"]["mean_wct_s"]-1):.2f}',
        hit_drop=f'{summaries["mooncake"]["dram_hit_pct"]-summaries["aegis"]["dram_hit_pct"]:.2f}')
    for k,v in fields.items():text=text.replace("{{"+k+"}}",v)
    assert "{{" not in text
    (DIR/"Paper_Draft.md").write_text(text)
    selection=dict(schema="aegiskv.evaluation_redesign.paper_selection.v1",figures=figures,
        layout_groups=groups,layout_only=[r for r in manifest["figures"] if r["evidence"]=="layout_only_no_data"],
        draft={"path":str((DIR/"Paper_Draft.md").relative_to(ROOT)),"language":"zh-CN"},
        template_sha256=sha(TEMPLATE),generator_sha256=sha(Path(__file__)),
        new_experiments=0,protocol_status="DRAFT_NOT_EXECUTED",
        prior_selection_sha256=sha(ROOT/"output/agent-lease-20260908/paper-selection.json"),
        source_manifest_sha256=sha(OUT/"manifest.json"))
    (ART/"paper-selection.json").write_text(json.dumps(selection,ensure_ascii=False,indent=2)+"\n")

    # Reuse the established native LaTeX placement builder with this edition's
    # output directory. Frozen source-v3 proofs and audit records stay intact.
    import build_agent_lease_index as legacy
    legacy.OUT,legacy.ARTIFACTS=OUT,ART
    legacy.build_latex([dict(r,caption_zh=r["caption"]) for r in figures],groups)
    review=["# Evaluation 重新设计的图稿与证据审查","",
        "[论文初稿](Paper_Draft.md) · [实验协议与图稿规格](EVALUATION_DESIGN.md) · [历史冻结审查](PAPER_FIGURE_REVIEW_BeforeEvaluation_20260909.md)","",
        "当前正文包含 3 张 Motivation、1 张 Overview、7 张 Evaluation，共 11 张独立图。Evaluation 七张是 source-v3 历史数据的新诊断视图；不是新算法实验，也尚不能支持无服务开销或稳定故障收益。四张空扫描布局单独保存在实验设计文档，后三类扩展保留文字位置。","",
        "本轮采用 PaperBanana 的参考检索、内容规划、统一风格、原生绘制与实际导出检查流程。统计图由真实历史数据计算，没有生成或修饰不存在的收益。每张图的点是 Workflow / 固定 case，而不是运行编号。","",
        "## 图稿","",
        "| 正文图 | 证据与边界 | 独立导出 |","|---|---|---|"]
    for r in figures:
        assets=" · ".join(f'[{ext.upper()}]({rel(OUT/(r["name"]+"."+ext))})' for ext in r["files"])
        review.append(f'| [{r["id"]} {r["title"]}](Paper_Draft.md#paper-{r["name"]}) | {r["caption"]} | {assets} |')
    review += ["","## 本轮修正的解释问题","",
        "- 逐 Workflow 绝对 WCT 改为同 ID 相对开销，保留全部 160 个对象和极值。",
        "- 故障图改为三个预选焦点 Workflow 的配对 WCT 与共同分母增量；完整批次的既有不利均值仍在正文陈述、原图归档。",
        "- 从实际 FAILURE_INJECT 日志确认旧触发口径是总请求 token 进度 60%，并非精确的 prefill-only 60% 或新方案 decode 第 8 token；新旧协议分开。",
        "- 明示历史 impact_contract_scope=OBSERVED_ONLY；布尔字段通过不等于三系统丢失集合相同。每例的目标、实际受害者和触发日志另存于 legacy-failure-contracts.json。",
        "- 只分解能相加的两个恢复阶段；不把 suffix+queue+resume 统称 GPU 重算，不把 resume 当成 DAG 完成。",
        "- 恢复来源保留 Peer=0；DRAM-only 完整标名，避免 M/D/A 等未解释缩写。",
        "- 请求平均 TPOT 的 P99 与真实逐 token TBT P99 分开；后者仍待采集。",
        "- 未执行的故障频率与并发扫描只显示标注 LAYOUT ONLY 的空轴，不填曲线。","",
        "## 复现和检查","",
        "绘图源：[render_evaluation_redesign.py](scripts/paper/render_evaluation_redesign.py)；正文源：[evaluation-draft.md](scripts/paper/templates/evaluation-draft.md)；生成入口：[build_evaluation_redesign.py](scripts/paper/build_evaluation_redesign.py)。旧 build_agent_lease_index.py 也会路由到当前版。","",
        "[逐点数据与文件哈希](../../../output/pdf/aegiskv-evaluation-20260909/manifest.json) · [图像 LaTeX](../../../output/pdf/aegiskv-evaluation-20260909/paper-figures.tex) · [可选同行组合](../../../output/pdf/aegiskv-evaluation-20260909/paper-pairs.tex) · [实际插入尺寸 PDF](../../../output/pdf/aegiskv-evaluation-20260909/paper-placement.pdf) · [中文浏览器预览](../../../output/pdf/aegiskv-evaluation-20260909/paper-story.html)","",
        "[本版检查记录](../../../output/evaluation-redesign-20260909/DELIVERY_AUDIT.json) 只覆盖数据变换、图像和排版；不是原生性能证明。旧 source-v3 的 51 次执行与源码证据继承已冻结审查，本轮未再运行或改写。新协议仍缺冻结 case、SLO、原生硬件和正式 commit。",""]
    (DIR/"PAPER_FIGURE_REVIEW.md").write_text("\n".join(review))
    (DIR/"FIGURES.md").write_text("# AegisKV 论文与图像导航\n\n- [中文论文初稿](Paper_Draft.md)\n- [Evaluation 实验与图稿设计](EVALUATION_DESIGN.md)\n- [图稿、来源与实际尺寸检查](PAPER_FIGURE_REVIEW.md)\n- [历史冻结实验协议](AGENT_LEASE_PROTOCOL.md)\n- [旧版与补充诊断图](Old_Figures.md)\n")
    # Archive every formerly primary Evaluation view, not only favorable plots.
    archive=DIR/"Old_Figures.md"
    current=archive.read_text()
    current=current.replace("## 版本边界：当前算法与旧 PrefixAdmission","## 历史冻结版本：Agent 子租约与 PrefixAdmission")
    current=current.replace("当前 [Paper_Draft.md](Paper_Draft.md) 使用 Agent 子租约",
        "重构前 [初稿](Paper_Draft_BeforeEvaluation_20260909.md) 使用 Agent 子租约")
    current=current.replace("当前正文 12 张，另有 43 张","该冻结版正文 12 张，另有 43 张")
    start,end="<!-- EVALUATION_REDESIGN_ARCHIVE_START -->","<!-- EVALUATION_REDESIGN_ARCHIVE_END -->"
    if start in current:current=current[:current.index(start)]+current[current.index(end)+len(end):]
    rows=[start,"## 2026-09-09 Evaluation 重构前的正文","",
        "下面保留此前八张正文 Evaluation 图及不利结果。完整旧稿另见 [重构前初稿](Paper_Draft_BeforeEvaluation_20260909.md)。原 source-v3 索引与审查描述其冻结版本；当前正文与新实验设计见顶部导航。",""]
    for r in old["figures"]:
        if not r["primary"] or r["section"]!="Evaluation":continue
        rows += [f'### 旧 E：{r["draft_title"]}',"",r["draft_caption"],"",
            f'[![{r["draft_title"]}]({rel(OLD/(r["name"]+".png"))})]({rel(OLD/(r["name"]+".pdf"))})',""]
    rows += [end,""]
    pos=current.index("\n\n")+2
    archive.write_text(current[:pos]+"\n".join(rows)+current[pos:])
    (DIR/"ACTIVE_PAPER_EDITION.json").write_text(json.dumps({"edition":"evaluation-redesign-20260909",
        "artifacts":str(ART.relative_to(ROOT)),"figures":str(OUT.relative_to(ROOT)),
        "selection":str((ART/"paper-selection.json").relative_to(ROOT)),
        "audit_command":".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_evaluation_redesign.py"},indent=2)+"\n")
    print(json.dumps({"paper_figures":len(figures),"evaluation":7,"paired_rows":sum(len(g)==2 for g in groups)}))


if __name__=="__main__":main()
