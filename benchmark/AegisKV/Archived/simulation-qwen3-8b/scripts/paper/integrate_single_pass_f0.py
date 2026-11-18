"""Apply the original-DAG F0 section without rewriting the parallel F1 work.

The historical revision generator may run this final overlay automatically.
All other figure files and experiment results retain their original paths.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from render_single_pass_f0 import ART, OUT, ROOT, SYSTEMS, table
from reduce_single_pass_f0 import sha
from agent_lease_style import LABELS

DIR = ROOT / "benchmark/AegisKV/experiments"
TOOLS = Path(__file__).parent
TEMPLATE = TOOLS / "templates/single-pass-f0-section.md"
START = "<!-- SINGLE_PASS_F0_START -->"
END = "<!-- SINGLE_PASS_F0_END -->"


def rel(path):
    return os.path.relpath(path, DIR)


def apply_single_pass():
    manifest_path = OUT / "single-pass-manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    statistics = manifest["statistics"]
    figures = {r["name"]: r for r in manifest["figures"]}
    doc = DIR / "Paper_Draft.md"
    text = doc.read_text()
    ids = {}
    for name in figures:
        match = re.search(r'<a id="paper-'+re.escape(name)+r'"></a>.*?\*\*图 (\d+)：', text, re.S)
        assert match, f"missing existing figure anchor: {name}"
        ids[name] = match[1]

    def figure(name):
        r = figures[name]
        return (f'<a id="paper-{name}"></a>\n\n<figure class="paper-figure">\n\n'
                f'[<img src="{rel(OUT/(name+".png"))}" width="1008" alt="{ids[name]} {r["title"]}">]'
                f'({rel(OUT/(name+".pdf"))})\n\n**图 {ids[name]}：{r["title"]}。** {r["caption"]}\n\n</figure>')

    planned_path = TOOLS / "templates/planned-figures.json"
    plans = json.loads(planned_path.read_text())
    p1 = next(p for p in plans["groups"] if p["key"] == "effective-reuse")
    # An execution repeat for uncertainty is different from copying each DAG.
    p1["plots"][0]["x"] = "原始 160 个 Workflow ID，按同一单轮 Mooncake 顺序排列"
    p1["plots"][0]["y"] = "各原始 Workflow 全生命周期实际 prefill 相对同 ID Mooncake 的增量（Ki tokens，Ki=1,024）"
    p1["protocol"] = "F0；每个原始 DAG 只执行一次，共 1,304 个请求。固定输入、并发、资源和算法版本；每个逻辑 token 位置的每次实际执行都计费，保留正常抢占后的重复工作。当前三次 F0 已有单次累计工作计数；待补独立完整重复和更多自然共享负载，token 和请求不是独立重复。"
    p1["data"] = "每次 prefill 的逻辑区间、执行次数、起止时间、GET 来源与失效，以及原始 request→Workflow 映射。保留全部 WCT/release/completion；不添加人工重复 DAG，不将命中 token 直接当作避免计算。"
    p1["placement"] = "图 eval-initial-reuse 旁保留实际 prefill 的单次计数；此候选用于补独立重复和自然复用压力，不将当前零抢占结果外推。"
    planned_path.write_text(json.dumps(plans,ensure_ascii=False,indent=2)+"\n")

    def plan(key):
        r = next(p for p in plans["groups"] if p["key"] == key)
        return "\n\n".join([
            f'<aside class="planned-figure" id="planned-{key}">',
            f'**待绘图 {r["id"]}：{r["title"]}（尚无结果）**',r["question"],
            table(["独立候选图 / 图型","横轴","纵轴","系列与对照"],
                  [[p["id"]+"："+p["type"],p["x"],p["y"],p["series"]] for p in r["plots"]]),
            "**固定条件与统计：** "+r["protocol"],"**理论预期（待检验）：** "+r["expected"],
            "**不成立或反转的条件：** "+r["refutation"],"**待采集数据：** "+r["data"],
            "**正文取舍：** "+r["placement"],"</aside>"])

    costs = {r["system"]:r for r in manifest["focus_costs"]}
    vals = dict(
        wct_id=ids["eval-workflow-delay"],cache_id=ids["eval-initial-reuse"],cost_id=ids["eval-preemption-progress"],
        mean_wcts="、".join(f'{statistics[s]["mean_wct_s"]:.3f}' for s in SYSTEMS),
        mean_change=f'{statistics["aegis"]["mean_wct_change_pct"]:.4f}',
        slower=statistics["aegis"]["slower"],faster=statistics["aegis"]["faster"],
        wct_figure=figure("eval-workflow-delay"),cache_figure=figure("eval-initial-reuse"),cost_figure=figure("eval-preemption-progress"),
        healthy_table=table(["系统","单轮 F0 平均 WCT (s)","批次时长 (s)","请求 TTFT P99 (s)"],
            [[LABELS[s],*(f'{statistics[s][k]:.3f}' for k in ["mean_wct_s","batch_s","p99_ttft_s"])] for s in SYSTEMS]),
        cache_table=table(["系统","本地 HBM 命中 tokens","DRAM / Peer 命中 tokens","总 token 命中率","命中至少一个前缀的请求"],
            [[LABELS[s],f'{statistics[s]["local_hit_tokens"]:,}',"0 / 0",f'{statistics[s]["total_hit_pct"]:.6f}%',f'{statistics[s]["hit_request_count"]} / 1304'] for s in SYSTEMS]),
        prefill_totals="、".join(f'{statistics[s]["prefill_executed_tokens"]:,}' for s in SYSTEMS),
        paired_csv=rel(OUT/"all-workflows-paired.csv"),focus_id=manifest["focus_workflow_id"],
        focus_wcts="、".join(f'{costs[s]["wct_s"]:.3f}' for s in ["mooncake","aegis"]),
        focus_delta=f'{costs["aegis"]["wct_s"]-costs["mooncake"]["wct_s"]:.3f}',
        cost_table=table(["系统","关键路径 batch 参与 (s)","等待/调度间隙 (s)","控制/GET/依赖间隔 (s)","WCT (s)"],
            [[LABELS[s],*(f'{costs[s][k]/1e9:.6f}' for k in ["critical_gpu_step_ns","critical_queue_other_ns","other_stages_ns"]),f'{costs[s]["wct_s"]:.6f}'] for s in SYSTEMS]),
        gpu_delta=f'{(costs["aegis"]["critical_gpu_step_ns"]-costs["mooncake"]["critical_gpu_step_ns"])/1e9:.3f}',
        queue_delta=f'{(costs["aegis"]["critical_queue_other_ns"]-costs["mooncake"]["critical_queue_other_ns"])/1e9:.3f}',
        batch_evidence=rel(ART/"final-request-batch-evidence.json"),
        effective_reuse_plan=plan("effective-reuse"),native_overhead_plan=plan("native-overhead"),
        resource_table=table(["指标",*(LABELS[s] for s in SYSTEMS)],[
            ["Python 参考控制 CPU (s)",*(f'{statistics[s]["reference_control_cpu_s"]:.3f}' for s in SYSTEMS)],
            ["模拟控制器服务需求 (s)",*(f'{statistics[s]["modeled_controller_service_s"]:.3f}' for s in SYSTEMS)],
            ["DRAM 写入 (GiB)",*(f'{statistics[s]["transfer_bytes"].get("AEGIS_STORE_DRAM_PROTECTION",0)/1024**3:.3f}' for s in SYSTEMS)],
            ["Peer 写入 (GiB)",*(f'{statistics[s]["transfer_bytes"].get("AEGIS_PEER_HBM_PROTECTION",0)/1024**3:.3f}' for s in SYSTEMS)],
            ["正常 GET (GiB)","0","0","0"]]))
    section = TEMPLATE.read_text()
    for key,value in vals.items():
        section = section.replace("{{"+key+"}}",str(value))
    assert "{{" not in section
    block = START+"\n\n"+section.rstrip()+"\n\n"+END
    if START in text:
        text = text[:text.index(START)]+block+text[text.index(END)+len(END):]
    else:
        start = text.index("### 正常运行的复用与排队成本")
        end = text.index("\n### ",start+4)
        text = text[:start]+block+"\n"+text[end:]
    old_setting = "输入包含 160 个 FanOutQA-derived Workflow，每个完整 DAG 执行两轮精确重访，共 2608 个请求，默认最大活跃 Workflow 数为 16。这是控制复用压力的负载构造，不代表生产重访频率。"
    new_setting = "正常服务评估使用原始 160 个 FanOutQA-derived Workflow，每个完整 DAG 执行一次，共 1,304 个请求，最大活跃 Workflow 数为 16。正常 WCT、Cache hit 与原因分析共享这批单轮 F0。暂留的历史故障、并发和频率图仍来自两轮重复 DAG，属于另一负载，不能用它们替代单轮正常服务结论；相应单轮故障更新由独立实验继续完成。输入 prompt 来自冻结 FanOutQA 构造，执行仍是未标定模拟。"
    text = text.replace(old_setting,new_setting)
    text = text.replace("冻结原型暴露出正常重访下降、抢占停顿及部分场景没有 Peer 副本的问题，固定故障与扩展实验也未显示统一优势。",
                        "原始单轮负载的正常命中量几乎相同，平均 WCT 未出现两轮实验中的增长，但仍有由批次时序与排队解释的对象级长尾。暂留的历史故障与扩展结果仍属于两轮负载，不能代替这一单轮结论。")
    # Write only this section and its workload/evidence description. The
    # parallel agent-position failure sections are not reconstructed here.
    doc.write_text(text)
    (ART/"normal-section.md").write_text(section)

    old_selection = ROOT/"output/aegiskv-revision-20260909/paper-selection.json"
    selection = json.loads(old_selection.read_text())
    for r in selection["figures"]:
        if r["name"] in figures:
            r.update(figures[r["name"]])
            r["id"] = ids[r["name"]]
        else:
            r.setdefault("directory","output/pdf/aegiskv-revision-20260909")
    selection["draft"] = dict(path=str(doc.relative_to(ROOT)),sha256=sha(doc))
    selection["normal_f0_override"] = dict(manifest=str(manifest_path.relative_to(ROOT)),
        sha256=sha(manifest_path),template=str(TEMPLATE.relative_to(ROOT)),template_sha256=sha(TEMPLATE),
        generator=str(Path(__file__).relative_to(ROOT)),generator_sha256=sha(__file__))
    selection["planned_figures"]["sha256"] = sha(planned_path)
    (ART/"paper-selection.json").write_text(json.dumps(selection,ensure_ascii=False,indent=2)+"\n")
    active_path = DIR/"ACTIVE_PAPER_EDITION.json"
    active = json.loads(active_path.read_text())
    active.update(edition="single-pass-normal-20260909",selection=str((ART/"paper-selection.json").relative_to(ROOT)),
                  normal_f0_artifacts=str(ART.relative_to(ROOT)),
                  figure_overrides={k:str(OUT.relative_to(ROOT)) for k in figures},
                  audit_command=".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_single_pass_f0.py",
                  audit_scope="single-pass normal figures and their manuscript section; remaining figures retain historical source manifests")
    active_path.write_text(json.dumps(active,ensure_ascii=False,indent=2)+"\n")
    review_path = DIR/"PAPER_FIGURE_REVIEW.md"
    review = review_path.read_text()
    a,b="<!-- SINGLE_PASS_REVIEW_START -->","<!-- SINGLE_PASS_REVIEW_END -->"
    note="\n\n".join([a,"## 单轮正常服务图更新（2026-09-09）",
        "原 Figure 5–7 的两轮口径退出正常服务论证。当前三图复用 Agent-80 会话的三个单轮 F0；各 160 个原始 DAG、1,304 个请求、seed 0。其余图仍按各自历史来源解释。",
        f'[当前单轮来源与审查]({rel(ART/"REPORT.md")}) · [逐 Workflow 配对表]({rel(OUT/"all-workflows-paired.csv")}) · [单轮检查]({rel(ART/"AUDIT.json")})',
        "重建命令：`.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_single_pass_f0.py`，随后运行 `integrate_single_pass_f0.py`。旧版正文生成器已接入这一最终替换步骤。旧插入样张与旧总体审查只绑定其历史文件，不代表本次新正文。",b])
    if a in review:
        review=review[:review.index(a)]+note+review[review.index(b)+len(b):]
    else:
        pos=review.index("\n")+1;review=review[:pos]+"\n"+note+"\n"+review[pos:]
    for name,r in figures.items():
        line=f'| [{ids[name]} {r["title"]}](Paper_Draft.md#paper-{name}) | {r["caption"]} | '+" · ".join(f'[{ext.upper()}]({rel(OUT/(name+"."+ext))})' for ext in r["files"])+" |"
        review=re.sub(r'^\| \[[^\n]*\]\(Paper_Draft\.md#paper-'+re.escape(name)+r'\)[^\n]*$',lambda _:line,review,flags=re.M)
    review_path.write_text(review)
    print(json.dumps(dict(updated_normal_figures=list(figures),paper_sha256=sha(doc),reused_f0_runs=3)))


if __name__ == "__main__":
    apply_single_pass()
    from publish_agent_progress_failure import republish_if_available
    republish_if_available(ROOT)
