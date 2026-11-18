"""Publish the two reviewed Agent-progress figures without changing runtime code."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def atomic_text(p, text, expected=None):
    p = Path(p)
    if expected is not None:
        assert p.read_text() == expected, f"concurrent edit: {p}"
    tmp = p.with_name(p.name+".agent80.tmp")
    try:
        tmp.write_text(text)
        if expected is not None:
            assert p.read_text() == expected, f"concurrent edit: {p}"
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_copy(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name+".agent80.tmp")
    try:
        shutil.copyfile(source, tmp)
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--campaign-root", required=True, type=Path)
    p.add_argument("--figures", required=True, type=Path)
    args = p.parse_args()
    repo, data, figures = args.repo.resolve(), args.campaign_root.resolve(), args.figures.resolve()
    manifest = read(figures/"agent80-figure-manifest.json")
    assert read(data/"campaign/RUN_AUDIT.json")["status"] == "PASS"
    visual_path = figures/"agent80-visual-review.json"
    if not visual_path.exists():
        visual_path = figures/"VISUAL_REVIEW.json"
    assert read(visual_path)["status"] == "PASS"
    storage_record = data/"STORAGE.json"
    working = Path(read(storage_record)["source_worktree"]) if storage_record.exists() else data.parent.parent
    assert (working/"MECHANISM_SOURCE_SNAPSHOT.json").exists()
    docs = repo/"benchmark/AegisKV/experiments"
    shared_out = repo/"output/pdf/aegiskv-revision-20260909"
    destination = repo/"output/agent80-20260909"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.resolve() != data:
        for source in data.rglob("*"):
            if not source.is_file() or "before-publication" in source.parts:
                continue
            target = destination/source.relative_to(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.name.endswith(".json.gz"):
                if not target.exists() and not target.is_symlink():
                    target.symlink_to(source)
            else:
                atomic_copy(source, target)
    atomic_text(destination/"STORAGE.json", json.dumps({
        "source_worktree": str(working), "raw_location": str(working/"output/agent80-20260909"),
        "frozen_source_fallback": str(repo/"output/agent-lease-20260908/source-v3"),
        "durable": "run summaries, manifests, protocols, audit reports, manuscript, plots and CSVs are copied into the main workspace",
        "raw_storage": "large raw json.gz results remain on /tmp via per-file symlinks because the home quota cannot hold them",
    }, indent=2)+"\n")
    atomic_copy(working/"MECHANISM_SOURCE_SNAPSHOT.json", destination/"MECHANISM_SOURCE_SNAPSHOT.json")
    atomic_copy(working/"output/agent-lease-20260908/CPU_QUOTES.json", destination/"CPU_QUOTES.json")
    data = destination
    for source in figures.iterdir():
        if source.is_file() and source.name.startswith(("eval-agent80", "agent80")):
            target = shared_out/source.name
            if target.resolve() != source:
                atomic_copy(source, target)
    atomic_copy(visual_path, shared_out/"agent80-visual-review.json")
    tools_dir = docs/"scripts"
    for name in ("run_agent_progress_failure.py", "run_agent_progress_campaign.py", "audit_agent_progress_campaign.py"):
        source = working/"benchmark/AegisKV/experiments/scripts"/name
        atomic_text(tools_dir/name, source.read_text())
    for name in ("render_agent_progress_failure.py", "publish_agent_progress_failure.py", "audit_agent_progress_delivery.py"):
        source = working/"benchmark/AegisKV/experiments/scripts/paper"/name
        if source.exists():
            atomic_text(tools_dir/"paper"/name, source.read_text())

    before = data/"before-publication"
    before.mkdir(exist_ok=True)
    draft = docs/"Paper_Draft.md"
    active = read(docs/"ACTIVE_PAPER_EDITION.json")
    selection_path = repo/active["selection"]
    current_selection = read(selection_path)
    for path in (draft, docs/"PAPER_FIGURE_REVIEW.md", docs/"ACTIVE_PAPER_EDITION.json", selection_path,
                 tools_dir/"paper/templates/revision-draft.md", tools_dir/"paper/build_revision_story.py"):
        target = before/path.name
        if not target.exists():
            shutil.copy2(path, target)
    previous = current_selection
    new = {r["name"]: dict(r, section="Evaluation", primary=True,
                          directory="output/pdf/aegiskv-revision-20260909") for r in manifest["figures"]}
    added = ["eval-agent80-workflow-wct", "eval-agent80-position-wct"]
    selection = dict(previous)
    selected = []
    for r in previous["figures"]:
        selected.extend([new[n] for n in added] if r["name"] == "eval-fixed-event-wct" else [new.get(r["name"], r)])
    assert len(selected) == 14
    for i, r in enumerate(selected, 1):
        r["id"] = str(i)
    by_name = {r["name"]: r for r in selected}
    assert [by_name[n]["id"] for n in added] == ["8", "9"]
    selection["figures"] = selected
    selection["layout_groups"] = [g for group in previous["layout_groups"]
                                  for g in ([[n] for n in added] if group == ["eval-fixed-event-wct"] else [group])]
    systems = ("mooncake", "dram", "aegis")
    counts = manifest["final_agent_counts"]
    position_rows = []
    import csv
    with (figures/"agent80-focus-positions.csv").open() as f:
        position_rows = list(csv.DictReader(f))
    paired = {(int(r["agent_position"]), r["system"]): r for r in position_rows}
    better = sum(int(paired[i,"aegis"]["delta_wct_ns"]) < int(paired[i,"mooncake"]["delta_wct_ns"]) for i in range(1,8))
    worse = sum(int(paired[i,"aegis"]["delta_wct_ns"]) > int(paired[i,"mooncake"]["delta_wct_ns"]) for i in range(1,8))
    times = "、".join(f'{counts[s]["failure_at_s"]:.3f} s/{counts[s]["failure_gpu"]}' for s in systems)
    indirect = "、".join(str(counts[s]["indirect"]) for s in systems)
    penalties = "、".join(f'{counts[s]["focal_delta_s"]:+.3f} s' for s in systems)
    assert all(int(r["focus_restored_peer_tokens"]) == 0 for r in position_rows)
    def image_block(name):
        r = by_name[name]
        path = f"../../../output/pdf/aegiskv-revision-20260909/{name}"
        return f'<a id="paper-{name}"></a>\n\n<figure class="paper-figure">\n\n[<img src="{path}.png" width="1008" alt="{r["id"]} {r["title"]}">]({path}.pdf)\n\n**图 {r["id"]}：{r["title"]}。** {r["caption"]}\n\n</figure>'
    paragraphs = [
        "<!-- AGENT80_SECTION_START -->",
        "### 按固定 Workflow 的 Agent 进度触发单次故障",
        "为比较相同逻辑进度下的故障影响，本组使用一轮完整 DAG：160 个 Workflow、1,304 个请求，重新运行三策略各自的无故障 F0；当前图 5–7 也复用这三次 F0，不重复计数。模型、资源、C=16、seed=0 和 source-v3 算法保持一致。事前从输入中取结点数为众数 7、一个入口和一个 final 的 Workflow，再按 ID 字典序选定 `00065f204bddb94d`，不按故障收益选例。",
        "该 Workflow 的 A1 是前置 Agent，A2–A6 是五个并行分支，A7 是最终汇合 Agent。一次 F1 只注入一次 GPU 故障：当固定请求首次跨过输入 prefill 与输出 decode 总 token 的 80% 时，使其实际宿主 GPU 不可用 120 s。各策略按自身执行进度触发，不固定绝对时刻或附带受害集合，也不等备份完成。阈值在调度步内按既有模拟器插值解析；A7 的 378 个输入与 61 个输出 token 对应 351.2-token 阈值，仍处于 prefill，且短于一个 4K 保护 chunk。",
        "图 {{ref:eval-agent80-workflow-wct}} 在 A7 触发故障时保留全部 160 个同 ID 对象，纵轴为同系统 WCT(F1)−WCT(F0)。横轴沿用本组 Mooncake 单轮 F0 的固定排序；阴影标出焦点。实心标记表示有 active 请求直接受害，空心表示仅排队请求受害；底部叉号表示没有这两类直接受害请求、但 WCT 发生变化的对象。",
        "{{fig:eval-agent80-workflow-wct}}",
        f"按 Mooncake、DRAM-only AegisKV、AegisKV 的顺序，实际触发位置分别为 {times}；焦点 Workflow 的故障增量为 {penalties}。无直接受害请求但 WCT 改变的 Workflow 分别有 {indirect} 个。此分类按同系统 F0/F1 的精确差值形成，包含容量、排队和后续入场变化；不是仅凭故障时仍活跃就认定受影响。完整数据同时保留释放 R、完成 C 和 WCT W，并逐行核对 ΔC=ΔW+ΔR，不能将释放延后造成的较短 WCT 等同于更早完成。",
        "A7 案例中，三者都从 GPU4 重路由至 GPU2，各从 DRAM 恢复 64 tokens、重算 314 tokens，焦点 Peer 恢复量均为零。焦点 Workflow 的释放时刻与 F0 相等，因此这里的负增量确实对应完成提前；它包含恢复后的排队与组批变化，不能直接当作 Peer 保护收益。全部七个位置的 21 次焦点恢复也都没有使用 Peer tokens。",
        "### 同一 Workflow 在不同 Agent 位置的故障增量",
        "图 {{ref:eval-agent80-position-wct}} 将故障焦点依次换为 A1–A7，每组仍跟踪同一个 Workflow，且三种策略固定相同 Agent ID 与 80% 总 token 阈值。A2–A6 仅按输入分支编号排列，它们相互并行，不是连续时间阶段。纵轴只比较该焦点 Workflow 相对本策略 F0 的完整 WCT 变化。",
        "{{fig:eval-agent80-position-wct}}",
        f"这七个位置中，AegisKV 的故障增量在 {better} 个位置小于 Mooncake、{worse} 个位置大于 Mooncake；负值和零值均保留。负值可能来自故障后的调度变化，不能解释为故障本身有益。不同位置的请求长度、Slack、恢复来源和附带受害者都可能不同，因此这些结果描述该固定 Workflow 的位置敏感性，不能单独归因为 Peer HBM 或外推为所有 Workflow 均受益。每策略 7 次独立单故障执行复用 1 次 F0，共 24 次完整模拟；A7 的三次 F1 同时用于前图。每个条件一次运行，没有跨重复置信区间，未执行原生硬件标定。",
        "[完整实验协议与检查](../../../output/agent80-20260909/EXPERIMENT_AND_FIGURE_SPEC.md) · [全部位置的逐 Workflow 数据](../../../output/pdf/aegiskv-revision-20260909/agent80-all-workflows.csv) · [焦点位置配对数据](../../../output/pdf/aegiskv-revision-20260909/agent80-focus-positions.csv)",
        "<!-- AGENT80_SECTION_END -->",
    ]
    template_section = "\n\n".join(paragraphs)+"\n\n"
    rendered = template_section
    for name in added:
        rendered = rendered.replace("{{ref:"+name+"}}", by_name[name]["id"])
        rendered = rendered.replace("{{fig:"+name+"}}", image_block(name))
    begin, end = "<!-- AGENT80_SECTION_START -->", "<!-- AGENT80_SECTION_END -->"
    def replace_section(text, section):
        if begin in text:
            a, b = text.index(begin), text.index(end)+len(end)
        else:
            a = text.index("### 固定追加故障：同一 Workflow 的完成时间变化")
            b = text.index("### 恢复机制：已有副本是否减少了重算", a)
        return text[:a]+section+text[b:].lstrip("\n")
    old = draft.read_text()
    text = old
    if begin not in text:
        text = re.sub(r"图 (\d+)", lambda m: "图 "+str(int(m[1])+(int(m[1])>=9)), text)
        text = re.sub(r'(<img[^>]+alt=")(\d+)', lambda m: m[1]+str(int(m[2])+(int(m[2])>=9)), text)
    text = replace_section(text, rendered)
    text = text.replace("相应单轮故障更新由独立实验继续完成", "图 8–9 已完成同一 Workflow 的单轮进度故障实验，与正常服务图共享三个 F0")
    text = text.replace("后文按 Agent 进度注入故障的实验也可复用这三次 F0", "后文按 Agent 进度注入故障的实验复用这三次 F0")
    text = text.replace("接固定追加故障结果", "接进度触发故障结果")
    atomic_text(draft, text, old)
    template = tools_dir/"paper/templates/revision-draft.md"
    old = template.read_text()
    atomic_text(template, replace_section(old, template_section), old)
    builder = tools_dir/"paper/build_revision_story.py"
    old = builder.read_text()
    changed = old.replace("'fixed-event-wct-manifest.json']", "'fixed-event-wct-manifest.json','agent80-figure-manifest.json']")
    changed = changed.replace("'eval-fixed-event-wct','eval-fault-paired-wct'", "'eval-agent80-workflow-wct','eval-agent80-position-wct','eval-fault-paired-wct'")
    changed = changed.replace("audit_revision_story.py'", "audit_agent_progress_delivery.py'")
    if "republish_agent_progress_if_available" not in changed:
        changed += "\n    from publish_agent_progress_failure import republish_if_available as republish_agent_progress_if_available\n    republish_agent_progress_if_available(ROOT)\n"
    atomic_text(builder, changed, old)
    selection.update(template_sha256=sha(template), generator_sha256=sha(builder),
                     agent80_manifest_sha256=sha(figures/"agent80-figure-manifest.json"),
                     agent80_run_audit_sha256=sha(data/"campaign/RUN_AUDIT.json"),
                     prior_selection_sha256=sha(before/"paper-selection.json"))
    selection["draft"] = dict(path=str(draft.relative_to(repo)), sha256=sha(draft), language="zh-CN")
    atomic_text(data/"paper-selection.json", json.dumps(selection, ensure_ascii=False, indent=2)+"\n")
    edition = dict(active, **{"edition": "agent-progress-20260909", "artifacts": "output/agent80-20260909",
               "figures": "output/pdf/aegiskv-revision-20260909", "selection": "output/agent80-20260909/paper-selection.json",
               "audit_command": ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_agent_progress_delivery.py",
               "audit_scope": "24 progress-failure campaign runs; two new figures; preserve single-pass normal figure overrides and other historical exports"})
    atomic_text(docs/"ACTIVE_PAPER_EDITION.json", json.dumps(edition, indent=2)+"\n")
    review = docs/"PAPER_FIGURE_REVIEW.md"
    old = review.read_text()
    note = "\n\n<!-- AGENT80_REVIEW -->\n## 2026-09-09：固定 Agent 80% 故障实验\n\n当前正文为 14 图。新图 8 展示 A7 故障后的全部 Workflow 配对变化；新图 9 替换旧固定 180 s 的 Figure 8，比较同一 Workflow 的七个 Agent 位置。原图 9–13 顺延为 10–14。三策略 ×（1 个 F0 + 7 个 F1）=24 次完整单轮模拟；下面的旧 13 图审查与插入样张属于此前版本。\n\n[新实验协议与证据边界](../../../output/agent80-20260909/EXPERIMENT_AND_FIGURE_SPEC.md) · [原始运行复算](../../../output/agent80-20260909/campaign/RUN_AUDIT.json) · [新图清单](../../../output/pdf/aegiskv-revision-20260909/agent80-figure-manifest.json) · [当前交付检查](../../../output/agent80-20260909/DELIVERY_AUDIT.json)\n\n<!-- AGENT80_REVIEW_END -->\n"
    if "<!-- AGENT80_REVIEW -->" in old:
        old2 = re.sub(r"\n*<!-- AGENT80_REVIEW -->.*?<!-- AGENT80_REVIEW_END -->\n*", "\n", old, flags=re.S)
    else:
        old2 = old
    at = old2.index("\n")
    atomic_text(review, old2[:at]+note+old2[at:], old)
    archive = docs/"Old_Figures.md"
    old = archive.read_text()
    if "<!-- AGENT80_ARCHIVE -->" not in old:
        note = "\n\n<!-- AGENT80_ARCHIVE -->\n## 2026-09-09：原固定 180 s Figure 8\n\n该图作为外部故障日程的历史诊断保留，已由同一 Workflow 的七个 Agent 80% 进度故障实验替换。其数据与原图不改动。\n\n[原 Figure 8 PDF](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.pdf) · [原始数据](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.csv)\n"
        atomic_text(archive, old+note, old)
    print(json.dumps({"published": True, "paper_figures": 14, "new_figures": [8,9], "main_runtime_modified": False}))


def republish_if_available(repo):
    """Reapply this scoped overlay after the legacy and normal-section builders."""
    import sys
    repo = Path(repo).resolve()
    data = repo/"output/agent80-20260909"
    figures = repo/"output/pdf/aegiskv-revision-20260909"
    manifest = figures/"agent80-figure-manifest.json"
    if not manifest.exists() or not (data/"campaign/RUN_AUDIT.json").exists():
        return
    saved = sys.argv
    try:
        sys.argv = [__file__, "--repo", str(repo), "--campaign-root", str(data),
                    "--figures", str(manifest.resolve().parent)]
        main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    main()
