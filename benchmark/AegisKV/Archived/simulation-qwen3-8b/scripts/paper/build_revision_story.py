"""Build the evidence-driven revision without changing historical figures."""
from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
from pathlib import Path

from paper_paths import ROOT
from render_revision_scaling import ART, OUT, sha, SYSTEMS
from agent_lease_style import LABELS
from revision_draft_captions import CAPTIONS

DIR = ROOT/'benchmark/AegisKV/experiments'
TOOLS = Path(__file__).parent
TEMPLATE = TOOLS/'templates/revision-draft.md'
PLANNED = TOOLS/'templates/planned-figures.json'
PRIOR = ROOT/'output/evaluation-redesign-20260909'
PRIOR_OUT = ROOT/'output/pdf/aegiskv-evaluation-20260909'


def rel(p):
    return os.path.relpath(p, DIR)


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '|'+'---|'*len(headers)] +
                     ['| '+' | '.join(map(str,r))+' |' for r in rows])


def load(p):
    return json.loads(p.read_text())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    previous = load(PRIOR/'paper-selection.json')
    figures = []
    for name in ['motivation-branch-gap','motivation-recovery-exposure']:
        r = dict(next(r for r in previous['figures'] if r['name']==name))
        for ext, digest in r['files'].items():
            p=PRIOR_OUT/f'{name}.{ext}'
            assert sha(p)==digest
            shutil.copy2(p,OUT/p.name)
        figures.append(r)
    m=load(OUT/'motivation-recompute-manifest.json')
    figures.append(dict(name=m['name'],title='长上下文的完整前缀重算代价',
        caption=m['caption_zh'],caption_en=m['caption_en'],evidence=m['evidence'],
        files=m['files'],width_in=m['width_in'],height_in=m['height_in'],section='Motivation'))
    m=load(OUT/'overview-manifest.json')
    figures.append(dict(name=m['name'],title='AegisKV System Overview',
        caption='工作流上下文生成 Agent 保护优先级，源端独立向 Peer HBM 和 DRAM 复制同名 KV；副本在复制 ACK 后可读。Peer 控制器独立约束备份借用。故障后从存活层恢复新 primary C0/C1，再重算 C2。彩色箭头为 KV 传输，虚线为控制，灰色 DAG 边为依赖。',
        caption_en='AegisKV system overview. Workflow context informs Agent priorities. The source independently copies named KV chunks to Peer HBM and DRAM; copies become readable after ACK. A separate Peer controller bounds backup borrowing. Recovery materializes C0/C1 into new primary allocations and recomputes C2. Colored arrows carry KV, dashed arrows indicate control, and gray DAG edges indicate dependencies.',
        evidence='design',files=m['files'],width_in=m['width_in'],height_in=m['height_in'],section='System Design'))
    evaluation_records={}
    for filename in ['diagnostics-manifest.json','scaling-manifest.json','concurrency-workflow-manifest.json','fixed-event-wct-manifest.json','agent80-figure-manifest.json']:
        manifest=load(OUT/filename)
        evaluation_records.update({r['name']:dict(r,section='Evaluation') for r in manifest['figures']})
    evaluation_order=['eval-workflow-delay','eval-initial-reuse','eval-preemption-progress',
        'eval-agent80-workflow-wct','eval-agent80-position-wct','eval-fault-paired-wct','eval-fault-token-source',
        'eval-concurrency-throughput','eval-concurrency-workflow','eval-failure-rate-throughput']
    figures.extend(evaluation_records[name] for name in evaluation_order)
    for i,r in enumerate(figures,1):
        if r['name'] in CAPTIONS:
            r['caption'],r['caption_en']=CAPTIONS[r['name']]
        r.update(id=str(i),primary=True)
        for ext,digest in r['files'].items():
            assert sha(OUT/f"{r['name']}.{ext}")==digest, (r['name'],ext)
    by_name={r['name']:r for r in figures}
    assert len(by_name)==len(figures)
    planned=load(PLANNED)
    plans={r['key']:r for r in planned['groups']}
    template=TEMPLATE.read_text()
    assert re.findall(r'\{\{plan:([^}]+)\}\}',template)==list(plans)
    has_rate='eval-failure-rate-throughput' in by_name
    assert has_rate, "Completed rate data is required for this draft edition"
    groups=[m[1].split(',') for m in re.finditer(r'\{\{(?:fig|row):([^}]+)\}\}',template)]
    assert [n for g in groups for n in g]==list(by_name), ([n for g in groups for n in g], list(by_name))
    def preview(r):
        width=1008 if r['width_in']>5 else 480
        return f'[<img src="{rel(OUT/(r["name"]+".png"))}" width="{width}" alt="{html.escape(r["id"]+" "+r["title"])}">]({rel(OUT/(r["name"]+".pdf"))})'
    def single(m):
        r=by_name[m[1]]
        return f'<a id="paper-{r["name"]}"></a>\n\n<figure class="paper-figure">\n\n{preview(r)}\n\n**图 {r["id"]}：{r["title"]}。** {r["caption"]}\n\n</figure>'
    def pair(m):
        rr=[by_name[n] for n in m[1].split(',')]
        assert len(rr)==2 and all(r['width_in']<5 for r in rr)
        return '\n'.join([*(f'<a id="paper-{r["name"]}"></a>' for r in rr),'',
            table([f'**图 {r["id"]}：{r["title"]}**' for r in rr],
                  [[preview(r) for r in rr],[r['caption'] for r in rr]])])
    text=re.sub(r'\{\{fig:([^}]+)\}\}',single,template)
    text=re.sub(r'\{\{row:([^}]+)\}\}',pair,text)
    text=re.sub(r'\{\{ref:([^}]+)\}\}',lambda m:by_name[m[1]]['id'],text)
    def plan(m):
        r=plans[m[1]]
        assert r['status']=='PLANNED_NOT_RUN'
        rows=[[p['id']+'：'+p['type'],p['x'],p['y'],p['series']] for p in r['plots']]
        return '\n\n'.join([
            f'<aside class="planned-figure" id="planned-{r["key"]}">',
            f'**待绘图 {r["id"]}：{r["title"]}（尚无结果）**',r['question'],
            table(['独立候选图 / 图型','横轴','纵轴','系列与对照'],rows),
            '**固定条件与统计：** '+r['protocol'],
            '**理论预期（待检验）：** '+r['expected'],
            '**不成立或反转的条件：** '+r['refutation'],
            '**待采集数据：** '+r['data'],
            '**正文取舍：** '+r['placement'],
            '</aside>'])
    text=re.sub(r'\{\{plan:([^}]+)\}\}',plan,text)
    summaries=load(PRIOR/'source-summaries.json')
    healthy=table(['系统','F0 平均 WCT (s)','TTFT P99 (s)'],
        [[LABELS[s],*(f'{summaries[s][k]:.3f}' for k in ['mean_wct_s','p99_ttft_s'])] for s in SYSTEMS])
    with (PRIOR_OUT/'eval-healthy-resources.csv').open() as f: cost=list(csv.DictReader(f))
    metrics=[('Reference Python CPU','Python 参考控制 CPU (s)'),
             ('Modeled CPU service','模拟入场/准入 CPU 服务需求 (s)'),
             ('DRAM + Peer write bytes','DRAM + Peer 写入 (TiB)'),
             ('Foreground GET bytes','正常 GET (TiB)')]
    resource=table(['指标',*(LABELS[s] for s in SYSTEMS)],
        [[label,*(f'{float(next(r for r in cost if r["metric"]==key and r["system"]==s)["value"]):.3f}' for s in SYSTEMS)] for key,label in metrics])
    cp=load(ART/'scaling/points.json')
    concurrency_result=f'四个并发值形成 {len(cp)} 个配置—系统点，每系统每点一次完整模拟。'
    concurrency_result+='并发 32 时，Mooncake 与 AegisKV 的完成速率分别为 '
    c32={r['system']:r for r in cp if r['concurrency']==32}
    concurrency_result+=f'{c32["mooncake"]["workflows_per_second"]:.3f} 与 {c32["aegis"]["workflows_per_second"]:.3f} Workflow/s。'
    c64={r['system']:r for r in cp if r['concurrency']==64}
    paired=load(OUT/'concurrency-workflow-manifest.json')['figures'][0]['statistics']['aegis']
    concurrency_result+=f'并发 64 时，完成速率从 Mooncake 的 {c64["mooncake"]["workflows_per_second"]:.3f} 提高到 AegisKV 的 {c64["aegis"]["workflows_per_second"]:.3f} Workflow/s，但同 ID 比较中有 {paired["faster"]} 个 Workflow 更快、{paired["slower"]} 个更慢。批次整体完成得更快，并不意味着各对象的 WCT 均降低。这些点体现配置相关的得失，不能外推为所有负载下均无开销。'
    rate_result=''
    if has_rate:
        rp=load(ART/'scaling-rate/points.json')
        rate_result=f'四个频率点共 {len(rp)} 个系统—配置结果；每点每系统一次模拟，未构造跨运行置信区间。各点实际注入次数、受害集合、修复事件和完成率随原始结果一同记录。'
        last={r['system']:r for r in rp if r['failure_rate_per_cluster_hour']==30}
        rate_result+=f'在每集群小时 30 次的压力点，Mooncake 与 AegisKV 的窗口完成速率分别为 {last["mooncake"]["window_workflows_per_second"]:.3f} 与 {last["aegis"]["window_workflows_per_second"]:.3f} Workflow/s，窗口内分别完成 {last["mooncake"]["window_completed_workflows"]} 与 {last["aegis"]["window_completed_workflows"]} 个 Workflow。'
    for key,value in dict(healthy_table=healthy,resource_table=resource,concurrency_result=concurrency_result,rate_result=rate_result).items():
        text=text.replace('{{'+key+'}}',value)
    assert '{{' not in text
    (DIR/'Paper_Draft.md').write_text(text)
    selection=dict(schema='aegiskv.evidence_revision.paper_selection.v1',figures=figures,layout_groups=groups,
        draft=dict(path=str((DIR/'Paper_Draft.md').relative_to(ROOT)),language='zh-CN'),
        template_sha256=sha(TEMPLATE),generator_sha256=sha(Path(__file__)),
        captions_sha256=sha(TOOLS/'revision_draft_captions.py'),
        planned_figures=dict(path=str(PLANNED.relative_to(ROOT)),sha256=sha(PLANNED),groups=len(plans),candidate_figures=sum(len(r['plots']) for r in plans.values()),status='PLANNED_NOT_RUN'),
        prior_selection_sha256=sha(PRIOR/'paper-selection.json'),
        algorithm2_implementation='UNCHANGED_FROZEN_SOURCE_V3',rate_figures=has_rate)
    (ART/'paper-selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
    import build_agent_lease_index as legacy
    legacy.OUT,legacy.ARTIFACTS=OUT,ART
    legacy.build_latex([dict(r,caption_zh=r['caption']) for r in figures],groups,
        proof_note="Placement proof at actual column and text widths. Captions distinguish historical predictions, design and uncalibrated simulations. New scaling executions retain the source-v3 algorithms; the external-clock failure protocol is separately derived and audited. This proof does not certify performance of the Algorithm 2 revision.")
    review=['# 论文图稿与证据审查','',
        '[中文初稿](Paper_Draft.md) · [实验设计](EVALUATION_DESIGN.md) · [事件诊断](../../../output/aegiskv-revision-20260909/EVALUATION_DIAGNOSIS.md) · [修改前初稿](Paper_Draft_BeforeDiagnosis_20260909.md)','',
        f'正文共 {len(figures)} 张独立图：3 张 Motivation、1 张 Overview、{len(figures)-4} 张 Evaluation。定量图的排版可直接插入 LaTeX；当前模拟结果尚不能作为“近零开销且稳定故障收益”的投稿证据。所有不利结果和旧图完整保留。','',
        '## 本轮修正','',
        '- Observation 3 改为长上下文的完整前缀重算预测，移出容量图；旧 235B/PP4 未验证配置不加入该新图。',
        '- Overview 使用具体 primary/backup 对象、独立复制与 ACK、故障恢复路径；清理主文旧联合终点授信公式，保留当前 Agent 接口和不变条件。',
        '- 正常 WCT 保留全部对象和离群点，以秒展示实际增加的延迟，并由同一请求的抢占/进度轨迹解释。',
        '- 重访命中单独统计，区分初次读取与抢占后实际避免的计算；不把冷访问混入重访分母。',
        '- 删除混合量纲归一资源图，分项绝对量进正文表；旧初始等待指标不能证明完整生命周期排队没有增长。',
        '- 单故障改为同一 Workflow 的 F0→F1 配对，并邻接实际恢复来源；明确 Peer=0 和受害集合差异。',
        '- 扩展曲线只使用完成并审计的真实模拟点，不插值缺测点、不添加不存在的收益或置信区间。','',
        '- 按用户新纠正，原始 WCT P95 移出正文图与服务表。并发使用最高并发点的同 ID 差值，故障细节使用共同历史下 K2−K1 的固定追加事件影响；释放时刻变化单独核对。','',
        '- 将固定追加故障比较提前到恢复机制之前；正文图注缩短，完整字段与来源保留在原图 manifest。',
        f'- 增加 {len(plans)} 组待绘位置、{sum(len(r["plots"]) for r in plans.values())} 张独立候选的图型、坐标、条件预期与反证条件。所有候选均为未执行规格，不计入正文结果图或模拟次数。',
        '- 补充故障范围、请求级 Slack 快照、当前 Agent 续租、物理发布/释放约束及 DMA-to-forward 未建模边界。','',
        '[论文整体审查与落实修改](PAPER_DRAFT_REVIEW.md) · [未绘图的结构化规格](scripts/paper/templates/planned-figures.json) · [本次文字修订前初稿](Paper_Draft_BeforeStory_20260909.md)','',
        '## 图像与来源','',
        '| 图 | 科学口径与限制 | 文件 |','|---|---|---|']
    for r in figures:
        links=' · '.join(f'[{ext.upper()}]({rel(OUT/(r["name"]+"."+ext))})' for ext in r['files'])
        review.append(f'| [{r["id"]} {r["title"]}](Paper_Draft.md#paper-{r["name"]}) | {r["caption"]} | {links} |')
    review+=['','## 生成与实际检查','',
        '图稿采用 PaperBanana 的参考、规划、统一编码、原生生成与导出核对流程。Overview 参考 [Mooncake FAST25 Best Paper](https://www.usenix.org/conference/fast25/presentation/qin) 的资源拓扑与 [Ensō OSDI23 Best Paper](https://www.usenix.org/conference/osdi23/presentation/sadok) 的具体对象表达；Evaluation 参考 [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html) 的受控故障与进度跟踪。参考图与数据没有移植到本实验。','',
        '[Overview 审查](../../../output/pdf/aegiskv-revision-20260909/SYSTEM_OVERVIEW_REVIEW.md) · [重算预测来源](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute-manifest.json) · [诊断图 manifest](../../../output/pdf/aegiskv-revision-20260909/diagnostics-manifest.json) · [扩展图 manifest](../../../output/pdf/aegiskv-revision-20260909/scaling-manifest.json)','',
        '[并发运行审计](../../../output/aegiskv-revision-20260909/scaling/RUN_AUDIT.json) · [并发原始证据归档](../../../output/aegiskv-revision-20260909/scaling/RAW_ARCHIVE.json) · [故障频率事件审计](../../../output/aegiskv-revision-20260909/scaling-rate/EVENT_AUDIT.json)。两扫描共享 C16/F0 三个点；24 个点对应 21 次不同的完整执行，其中 15 次为本轮新增。小回归单独计，不作为性能重复。','',
        '[独立 PDF 的 LaTeX](../../../output/pdf/aegiskv-revision-20260909/paper-figures.tex) · [可选同行组合](../../../output/pdf/aegiskv-revision-20260909/paper-pairs.tex) · [实际插入样张](../../../output/pdf/aegiskv-revision-20260909/paper-placement.pdf) · [中文预览](../../../output/pdf/aegiskv-revision-20260909/paper-story.html) · [交付检查](../../../output/aegiskv-revision-20260909/DELIVERY_AUDIT.json)','',
        '[逐 Workflow 并发配对](../../../output/pdf/aegiskv-revision-20260909/concurrency-workflow-manifest.json) · [固定追加故障图](../../../output/pdf/aegiskv-revision-20260909/fixed-event-wct-manifest.json) · [故障前日志核对](../../../output/aegiskv-revision-20260909/scaling-rate/FIXED_EVENT_PREFIX_AUDIT.json) · [全部 Workflow 的事件差值](../../../output/aegiskv-revision-20260909/scaling-rate/data/fixed-event-all-workflows.json)','',
        '绘图入口：[Motivation](scripts/paper/render_motivation_recompute.py)、[Overview](scripts/paper/build_revised_overview.py)、[诊断](scripts/paper/render_revision_diagnostics.py)、[吞吐扩展](scripts/paper/render_revision_scaling.py)、[并发逐对象比较](scripts/paper/render_concurrency_workflow.py)、[固定追加故障](scripts/paper/render_fixed_event_wct.py)。正文入口：[build_revision_story.py](scripts/paper/build_revision_story.py)，正文源：[revision-draft.md](scripts/paper/templates/revision-draft.md)。历史源快照、算法文件及原始图像保持冻结。','']
    (DIR/'PAPER_FIGURE_REVIEW.md').write_text('\n'.join(review))
    (DIR/'ACTIVE_PAPER_EDITION.json').write_text(json.dumps(dict(edition='evidence-revision-20260909',
        artifacts=str(ART.relative_to(ROOT)),figures=str(OUT.relative_to(ROOT)),
        selection=str((ART/'paper-selection.json').relative_to(ROOT)),
        audit_command='.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_agent_progress_delivery.py'),indent=2)+'\n')
    archive=DIR/'Old_Figures.md'; archived=archive.read_text()
    start,end='<!-- EVIDENCE_REVISION_ARCHIVE_START -->','<!-- EVIDENCE_REVISION_ARCHIVE_END -->'
    if start in archived:
        archived=archived[:archived.index(start)]+archived[archived.index(end)+len(end):]
    lines=[start,'## 2026-09-09 诊断修订前的图像','',
        '[诊断修订前初稿](Paper_Draft_BeforeDiagnosis_20260909.md)保留原 11 张图；[论述修订前初稿](Paper_Draft_BeforeStory_20260909.md)保留其后的 13 图版本。下列 Evaluation 图和容量动机图均保留，不因负结果而删除。','']
    for r in previous['figures']:
        if r['section']!='Evaluation' and r['name']!='motivation-kv-capacity': continue
        lines += [f'### 原图 {r["id"]}：{r["title"]}','',r['caption'],'',
                  f'[![{r["title"]}]({rel(PRIOR_OUT/(r["name"]+".png"))})]({rel(PRIOR_OUT/(r["name"]+".pdf"))})','']
    if (OUT/'eval-concurrency-tail.pdf').exists():
        lines += ['### 撤出正文：全体 WCT P95 并发图','',
            '这是本次修订过程中生成的中间图。异质 Workflow 的原始 WCT P95 无法识别同一个对象的变化，已由 C64 同 ID 配对差值图替换；保留此图和原始点表用于追溯，不作为故障收益证据。','',
            f'[原始 P95 图]({rel(OUT/"eval-concurrency-tail.pdf")})','']
    lines += [end,'']; pos=archived.index('\n\n')+2
    archive.write_text(archived[:pos]+'\n'.join(lines)+archived[pos:])
    print(json.dumps({'paper_figures':len(figures),'rate_figures':has_rate}))


if __name__=='__main__':
    main()
    # Preserve the original-workload F0 correction when rebuilding the older
    # evidence edition. The overlay leaves concurrent F1 experiment work alone.
    from integrate_single_pass_f0 import apply_single_pass
    apply_single_pass()

    from publish_agent_progress_failure import republish_if_available as republish_agent_progress_if_available
    republish_agent_progress_if_available(ROOT)
