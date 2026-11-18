"""Render completed, audited scaling cells; never interpolate missing runs."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt

import agent_lease_style as style
from paper_paths import ROOT

ART = ROOT / 'output/aegiskv-revision-20260909'
OUT = ROOT / 'output/pdf/aegiskv-revision-20260909'
SYSTEMS = tuple(style.COLORS)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    style.install(style)
    OUT.mkdir(parents=True, exist_ok=True)
    records, inputs = [], {}
    specs = [
        ('scaling/points.json', 'concurrency', [8, 16, 32, 64], [
            ('eval-concurrency-throughput', 'workflows_per_second', 'Completed workflows / s',
             '并发扩展的完整批次完成速率',
             '固定 160 个 Workflow、两轮重访和相同资源，改变最大活跃 Workflow 数，横轴为 log2 刻度。完成速率为 160 除以完整批次时长，包含填充与排空；不是 SLO goodput。每个系统每点一次冻结算法模拟，无重复置信区间。',
             'Fixed 160-workflow, two-visit workload; concurrency uses a log2 axis. Completion rate is 160 divided by full batch duration, including fill and drain; it is not SLO goodput. Each system has one frozen-algorithm simulation per point; no replicate confidence intervals.'),
            ('eval-concurrency-tail', 'p95_wct_s', 'Workflow WCT P95 (s)',
             '并发扩展的 Workflow 尾部延迟',
             '与完成速率图相同的输入和执行。每点为一次完整执行内 160 个 Workflow 的 WCT P95；不包含 Workflow 释放前等待。三系统同一并发比较，不把 Workflow 数当作独立运行重复。',
             'Same executions as the completion-rate plot. Each point is the WCT P95 across 160 workflows in one full execution; waiting before workflow release is excluded. Compare systems at the same concurrency; workflows are not independent run replicates.')]),
        ('scaling-rate/points.json', 'failure_rate_per_cluster_hour', [0, 7.5, 15, 30], [
            ('eval-failure-rate-throughput', 'window_workflows_per_second', 'Completed workflows / s',
             '固定时间窗口内的故障频率与完成速率',
             '预定 480 s 窗口内注入 K=0/1/2/4 次故障，横轴为 K/480 s 的每集群小时换算。三系统使用相同外部时刻与 GPU，每次不可用 120 s；窗口内停机暴露分别为 0/120/240/420 GPU·s，末次修复越过窗口。纵轴为窗口内完成数/480 s。此范围为压力扫描；每点每系统一次模拟。',
             'K=0,1,2,4 external GPU failures in a prespecified 480-s window, expressed per cluster-hour. Systems share times and GPU targets; each outage lasts 120 s. In-window downtime is 0,120,240,420 GPU-s; the final repair extends beyond the window. The ordinate counts workflows completed by 480 s divided by 480 s. One simulation per system and stress point.'),
            ('eval-failure-rate-tail', 'p95_wct_s', 'Workflow WCT P95 (s)',
             '故障频率扩展的完整批次尾部延迟',
             '同一有限故障计划在 480 s 后不再注入新故障；旧故障继续修复。完整排空后统计全部 160 个 Workflow 的 WCT P95，避免仅统计窗口内完成者；这不是恒定故障率的稳态尾部。输入频率分母固定为 480 s，自然受害者集合允许不同。',
             'Same finite external failure plans: no new events after 480 s, while existing outages finish repairing. WCT P95 uses all 160 workflows after drain, not only in-window completions; it is not a steady-state tail under constant-rate failures. Input rate always uses 480 s; natural victim sets may differ.')])]
    for source, xkey, expected_x, metrics in specs:
        path = ART / source
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        assert isinstance(rows, list)
        inputs[str(path.relative_to(ROOT))] = sha(path)
        assert len(rows) == len(SYSTEMS) * len(expected_x)
        for s in SYSTEMS:
            cells = sorted((r for r in rows if r['system'] == s), key=lambda r: r[xkey])
            assert [r[xkey] for r in cells] == expected_x
            assert all(r['completed_workflows'] == r['expected_workflows'] == 160 for r in cells)
            assert all(r['completed_requests'] == r['expected_requests'] == 2608 for r in cells)
        xlabel = ('Maximum active workflows' if xkey == 'concurrency'
                  else 'Failures / cluster-hour')
        for name, ykey, ylabel, title, caption, en in metrics:
            # Heterogeneous raw-WCT P95 is retained in the source data only.
            # Main-text replacements compare the same Workflow ID directly.
            if ykey == 'p95_wct_s':
                continue
            fig, ax = style.canvas(xlabel, ylabel, height=2.95)
            fig.subplots_adjust(left=.245, right=.968, top=.765, bottom=.225)
            output = []
            for s in SYSTEMS:
                cells = sorted((r for r in rows if r['system'] == s), key=lambda r: r[xkey])
                style.line(ax, s, [r[xkey] for r in cells], [r[ykey] for r in cells], markers=True)
                output.extend(dict(system=s, **{xkey:r[xkey]}, metric=ykey, value=r[ykey],
                                   completed_workflows=r['completed_workflows'],
                                   completed_requests=r['completed_requests']) for r in cells)
            if xkey == 'concurrency':
                ax.set_xscale('log', base=2)
            ax.set_xticks(expected_x, [f'{v:g}' for v in expected_x])
            ax.minorticks_off()
            # Reset both limits after introducing zero: the old auto limit used
            # only the narrow data range and could clip the highest marker.
            ax.set_ylim(0, max(r[ykey] for r in rows)*1.12)
            style.legend(ax)
            files = {}
            for ext in ['pdf','svg','png']:
                p = OUT / f'{name}.{ext}'
                metadata = ({'Creator':'AegisKV scaling renderer','CreationDate':None,'ModDate':None}
                            if ext=='pdf' else {'Date':None} if ext=='svg' else None)
                fig.savefig(p, dpi=220, metadata=metadata)
                files[ext] = sha(p)
            p = OUT / f'{name}.csv'
            with p.open('w', newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(output[0])); w.writeheader(); w.writerows(output)
            files['csv'] = sha(p)
            records.append(dict(name=name,title=title,caption=caption,caption_en=en,
                                width_in=float(fig.get_figwidth()),height_in=float(fig.get_figheight()),
                                evidence='uncalibrated_frozen_algorithm_scaling_simulation',files=files))
            plt.close(fig)
    manifest = dict(figures=records,inputs=inputs,generator_sha256=sha(Path(__file__)),
                    statistical_unit='one entire 160-workflow execution per system/configuration',
                    visual_review='PENDING')
    (OUT/'scaling-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'scaling_figures':len(records)}))


if __name__ == '__main__':
    main()
