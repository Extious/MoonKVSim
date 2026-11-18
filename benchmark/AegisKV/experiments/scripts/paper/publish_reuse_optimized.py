#!/usr/bin/env python3
"""Publish a complete, validated grouped-DCA matrix into the current cost panel."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'experiments/data/reuse-physical-qwen25-1m'
sys.path.insert(0, str(BASE))
from validate_prefill_optimized import validate_optimized


def replace_between(text, start, end, replacement):
    assert text.count(start) == text.count(end) == 1, (start, end)
    first, last = text.index(start), text.index(end)
    assert first < last
    return text[:first] + replacement.rstrip() + '\n\n' + text[last:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    args = ap.parse_args()
    run = args.run.resolve()
    audit = validate_optimized(run)
    data = json.loads((run/'measured.json').read_text())
    meta = data['metadata']
    assert meta['contexts'] == [8192, 65536, 262144, 1010000]
    assert meta['tp'] == 2 and meta['gpu'] == 'NVIDIA A100-PCIE-40GB'
    ledger = json.loads((BASE/'blsc/budget.json').read_text())
    job, = [j for j in ledger['jobs'] if j.get('job_id') == meta['job_id']]
    assert job['terminal']
    if job['last_slurm_state'] != 'COMPLETED':
        # A deferred batch-shell TERM trap can return 124 even after the
        # worker finishes. Keep the scheduler failure; require the ORIGINAL
        # full-run marker and every trial/state check, never create a marker.
        assert job['last_slurm_state'] == 'FAILED'
        status = json.loads((BASE/'blsc/latest-status.json').read_text())
        line, = [s for s in status['accounting']['stdout'].splitlines()
                 if s.startswith(meta['job_id']+'|')]
        assert line.split('|')[-1] == '124:0', line
        assert not list(run.glob('failure-*.json'))
        from datetime import datetime
        completed = (run/'COMPLETE').read_text().strip()
        terminated = (run/'terminated-at.txt').read_text().strip()
        assert datetime.fromisoformat(completed.replace('Z','+00:00')) <= datetime.fromisoformat(terminated)
        termination = {'slurm_state':job['last_slurm_state'],'slurm_exit':'124:0',
            'measurement_complete':True,'original_complete_marker':completed,
            'batch_term_trap_time':terminated,'formal_timings':audit['formal_timings'],
            'state_checks_passed':audit['passed'],
            'note':'Batch warning arrived during final warmup; worker continued and wrote the original full-run marker before the deferred TERM trap exited. Scheduler failure is retained, not relabeled as COMPLETED.',
            'evidence_sha256':{name:hashlib.sha256((run/name).read_bytes()).hexdigest()
                               for name in ['COMPLETE','terminated-at.txt','trials.jsonl','measured.json']}}
        (run/'termination-audit.json').write_text(json.dumps(termination,indent=2)+'\n')
    assert job['source_sha256']['measure_prefill_optimized.py'] == meta['script_sha256']
    for name, digest in meta['optimization_source_sha256'].items():
        assert job['source_sha256'][name] == digest
    snapshot = BASE/'optimization-archive'/f"{meta['job_id']}-full-matrix"
    for name, digest in job['source_sha256'].items():
        source = BASE/name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, name
        target = snapshot/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (snapshot/'source-sha256.json').write_text(json.dumps(job['source_sha256'], indent=2)+'\n')
    (run/'publication-validation.json').write_text(json.dumps(audit, indent=2)+'\n')
    with (run/'measured.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(data['rows'][0]))
        writer.writeheader();writer.writerows(data['rows'])
    rows = {(r['context_tokens'],r['path']):r['latency_ms']/1000 for r in data['rows']}
    h, d, f = [rows[1010000,p] for p in ['HBM','DRAM','Recompute']]
    gain = 100*(1-h/d)
    old = json.loads((BASE/'blsc/results/1516148/measured.json').read_text())
    native = {(r['context_tokens'],r['path']):r['latency_ms']/1000 for r in old['rows']}
    comparison = []
    for context in meta['contexts']:
        comparison.append({'context_tokens':context,'native_job':'1516148','optimized_job':meta['job_id'],
            'same_allocation_across_implementations':False,
            'native_hbm_s':native[context,'HBM'],'native_dram_s':native[context,'DRAM'],
            'optimized_hbm_s':rows[context,'HBM'],'optimized_dram_s':rows[context,'DRAM'],
            'optimized_full_prefill_s':rows[context,'Recompute'],
            'optimized_hbm_reduction_vs_dram_percent':100*(1-rows[context,'HBM']/rows[context,'DRAM'])})
    (run/'native-comparison.json').write_text(json.dumps(comparison, indent=2)+'\n')
    values = {'@HBM@':f'{h:.2f}', '@DRAM@':f'{d:.2f}', '@FULL@':f'{f:.2f}',
              '@GAIN@':f'{gain:.1f}', '@SPEED@':f'{d/h:.2f}', '@JOB@':meta['job_id']}
    def fill(text):
        for key, value in values.items():text=text.replace(key,value)
        return text

    tex_path = ROOT/'paper/background_and_motivation.tex'
    tex = tex_path.read_text()
    before = '    A100 PCIe 40\\,GB GPUs (TP2, BF16, batch one). HBM/DRAM reuse a\n'
    after = '    A100 PCIe 40\\,GB GPUs (TP2, BF16, batch one), using grouped-head\n    DCA across all paths. HBM/DRAM reuse a\n'
    assert before in tex
    tex = tex.replace(before, after, 1)
    tex = tex.replace('    one timing per length, after short kernel warmup. K~=~1,024; M~=~$10^6$.}',
                      '    one timing per length. K~=~1,024; M~=~$10^6$.}',1)
    tex = replace_between(tex, '0.5.10rc0 worker uses native Dual Chunk Attention', 'Total context is $C=M+1$.', r'''
0.5.10rc0 worker uses a grouped-head implementation of Dual Chunk Attention
(DCA), with sparse acceleration disabled and the same A100-compatible
kernel build across all paths. It batches query heads in each DCA call
and preserves the multi-head log-sum-exp layout, with one KV split and
GQA packing disabled. DCA position handling and chunk partitions are
unchanged.'''.lstrip())
    tex = replace_between(tex, 'At 1,010,000 tokens, the measured HBM, DRAM, and full-prefill latencies',
                          'A separate single-GPU test', fill(r'''
At 1,010,000 tokens, the measured HBM, DRAM, and full-prefill latencies
are @HBM@\,s, @DRAM@\,s, and @FULL@\,s, respectively.
Retaining KV avoids most historical computation in this configuration.
HBM further lowers latency by @GAIN@\% relative to DRAM by removing
transfer waiting. Both reuse paths still execute the same model forward;
reducing its common overhead makes the cost of H2D more visible.'''.lstrip()))
    tex = replace_between(tex, 'The figure uses one fixed synthetic text stream.', '\\begin{figure}[t]', r'''
The figure uses one fixed synthetic text stream. Each reuse point is the
median of three timings after one warmup; error bars show their range,
not workload variability. Each full-prefill point is one timed execution.
Kernel and operator checks precede measurement; native full-prefill
references also precede the 8K and 64K timings, but full-context warmup
is not repeated at the two longer lengths. Reuse executions check all-layer
new-token KV, hidden states, and the next greedy token against the
empty-cache reference with the same partition. We additionally compare
against native DCA for full prefill at 8K/64K and for the cached final token
at every length. Complete-history HBM and serialized DRAM are reference
states, not a finite-HBM policy or an overlapping DRAM baseline. These
worker-level results do not establish end-to-end WCT benefits or
long-context model quality.'''.lstrip())

    md_path = ROOT/'paper/paper_draft.md'
    md = md_path.read_text()
    md = replace_between(md, '**Figure 1(c) 支撑第二个动机。**', '**独立衔接段：', fill('''
**Figure 1(c) 支撑第二个动机。** 使用优化后作业 @JOB@ 同一次分配的 8K、64K、256K、1,010,000 数据，三条路径均为实测。总上下文 C=M+1；HBM/DRAM 复用 M 个 token 的 KV 后执行 1-token EXTEND，Full prefill 从空 KV 填充全部 C 个 token。1,010,000 处分别为 **@HBM@ s、@DRAM@ s、@FULL@ s**；HBM 相对 DRAM 延迟降低 **@GAIN@%**（DRAM/HBM=@SPEED@）。旧原生 DCA 和 64-token 数据独立保留。

条件：同次分配的 2 张 A100-PCIE-40GB、TP2、BF16 权重与 KV、batch 1；SGLang 0.5.10rc0 的显式分组 head DCA 实现，修正多 head LSE 布局，固定 num_splits=1、pack_gqa=False，保留 DCA 的位置处理、分块和合并逻辑，关闭稀疏加速。三路径共享同一实现、A100 内核构建和 FlashInfer SiLU。HBM 已驻留全部历史；DRAM 实际从 pinned host memory 完成 H2D 后再计算，不使用假设带宽、不与计算重叠；Full prefill 按至多 8K 的块填充 M，再独立执行同一个新 token。历史末页按实际 token 数复制。

终点是模型主体 forward 返回并 CUDA 同步，此时全部 C 个 token 的 KV 已填充，不含词表投影/采样。这个终点包含最后一层 attention/MLP，并非最后一次 KV 写入的单独时间戳；没有故障注入或 64-token 重建尾部，不包含模型加载、KV 备份创建、故障检测、排队和服务接管。

一个固定合成文本流。HBM/DRAM 各预热一次、正式计时三次，点为中位数，误差线为 min–max；完整空缓存 Prefill 每长度一次。测量前执行短 kernel 和随机算子检查，8K/64K 另有原生完整 Prefill 参考预运行；256K/1.01M 没有重复整个上下文预热，可能包含首次形状相关开销。这些计时重复不代表独立 workload，误差线不是置信区间。

**优化验证。** 8K/64K 对比原生与优化完整 Prefill；每个长度对比同一历史 KV 下的原生与优化 1-token 完整模型前向；每 rank 检查八种随机 Attention 形状，包括 DCA 分块边界及 1M 单 query。HBM/DRAM 还与优化空缓存参考配对检查全部层新 token KV、hidden、DECODE hidden 和 greedy token。没有为 256K/1.01M 的每个历史位置重新生成原生完整参考，不将这些检查宣称为任意输入等价证明或长上下文质量评估。自动 split 的首个候选未通过真实模型检查，错误与源码保留，未进入图。

**带宽与模型延迟分开解释。** 独立作业 1516171 的单卡 1 GiB 随机 BF16 测量为 HBM 流式读取 **1079.20 GB/s**、pinned H2D **23.98 GB/s**，比值 **45.00**（9 次计时中位数）。它不是 TP2 聚合带宽，也不是整个 Prefill 的加速比。DRAM 避免历史重算，HBM 额外避免传输等待；优化公共前向路径后，传输等待在复用延迟中的占比增大。这里完整 HBM 驻留和无重叠 DRAM 是参考状态，不能代替有限 Peer 容量和端到端 WCT 实验。

[优化实现及验证](@BASE@/OPTIMIZATION.md)；[完整矩阵数据](@BASE@/blsc/results/@JOB@/measured.json)；[逐次记录](@BASE@/blsc/results/@JOB@/trials.jsonl)；[原生对照](@BASE@/blsc/results/1516148/measured.json)。
'''.lstrip()).replace('@BASE@',str(BASE)))

    output = ROOT/'exports/reuse-prefill-optimized/recovery-cost'
    subprocess.run([sys.executable,str(ROOT/'experiments/scripts/paper/render_reuse_physical.py'),
                    str(run/'measured.json'),'--output',str(output)],check=True)
    tex_path.write_text(tex)
    md_path.write_text(md)
    shutil.copyfile(output.with_suffix('.pdf'),ROOT/'paper/figures/recovery-cost.pdf')
    (output.parent/'publication.json').write_text(json.dumps({'job_id':meta['job_id'],
        'data':str(run/'measured.json'),'hbm_s':h,'dram_s':d,'full_prefill_s':f,
        'hbm_reduction_vs_dram_percent':gain,'paper_build_and_visual_review':'pending'},indent=2)+'\n')
    print(json.dumps({'job_id':meta['job_id'],'hbm_s':h,'dram_s':d,'full_prefill_s':f,
                      'hbm_reduction_vs_dram_percent':gain},indent=2))

if __name__ == '__main__':main()
