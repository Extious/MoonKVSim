"""Publish the requested three sparse paths; retain all original run records."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'experiments/data/reuse-physical-qwen25-1m'
sys.path.insert(0, str(BASE))
from validate_prefill_sparse import validate


def between(text, start, end, replacement):
    assert text.count(start) == 1 and text.count(end) == 1, (start, end)
    a, b = text.index(start), text.index(end)
    assert a < b
    return text[:a]+replacement.rstrip()+'\n\n'+text[b:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    args = ap.parse_args()
    run = args.run.resolve()
    audit = validate(run)
    data = json.loads((run/'measured.json').read_text())
    meta = data['metadata']
    assert meta['contexts'] == [8192,65536,262144,1010000]
    assert meta['gpu'] == 'NVIDIA A100-PCIE-40GB'
    ledger = json.loads((BASE/'blsc/budget.json').read_text())
    job, = [j for j in ledger['jobs'] if j.get('job_id') == meta['job_id']]
    assert job['terminal'] and job['last_slurm_state'] == 'COMPLETED'
    assert job['source_sha256']['measure_prefill_sparse.py'] == meta['script_sha256']
    assert job['source_sha256']['sg_sparse_backend.py'] == meta['sparse_adapter_sha256']
    snapshot = BASE/'sparse-archive'/meta['job_id']
    for name, digest in job['source_sha256'].items():
        assert hashlib.sha256((snapshot/name).read_bytes()).hexdigest() == digest, name
    plotted_paths = ['HBM', 'DRAM_no_overlap', 'FullPrefill']
    audit['plotted_paths'] = plotted_paths
    audit['plotted_formal_timings'] = 28
    audit['path_selection_reason'] = 'Latest user request: DRAM without overlap only. Preserve earlier overlap diagnostics in their original allocations.'
    (run/'publication-validation.json').write_text(json.dumps(audit,indent=2)+'\n')
    with (run/'measured.csv').open('w') as f:
        writer = csv.DictWriter(f,fieldnames=list(data['rows'][0]));writer.writeheader();writer.writerows(data['rows'])
    with (run/'published-three-paths.csv').open('w') as f:
        writer = csv.DictWriter(f,fieldnames=list(data['rows'][0]));writer.writeheader()
        writer.writerows(r for r in data['rows'] if r['path'] in plotted_paths)
    rows = {(r['context_tokens'],r['path']):r['latency_ms']/1000 for r in data['rows']}
    h,d,f = [rows[1010000,p] for p in plotted_paths]
    values = {'@H@':f'{h:.3f}', '@D@':f'{d:.3f}', '@F@':f'{f:.2f}',
              '@DH@':f'{d/h:.2f}', '@SAVING@':f'{(1-h/d)*100:.1f}', '@JOB@':meta['job_id'],
              '@BASE@':str(BASE), '@RUN@':str(run), '@GROUP@':str(meta['sparse_head_group'])}
    def fill(s):
        for k,v in values.items():s=s.replace(k,v)
        return s
    output = ROOT/'exports/reuse-prefill-sparse/recovery-cost'
    subprocess.run([sys.executable,str(ROOT/'experiments/scripts/paper/render_reuse_physical.py'),
                    str(run/'measured.json'),'--output',str(output),'--paths',*plotted_paths],check=True)
    archive = ROOT/'Archived'/f"reuse-dense-before-sparse-{time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())}"
    for name in ['background_and_motivation.tex','paper_draft.md','main.pdf','figures/recovery-cost.pdf',
                 'figures/preview/recovery-cost.png']:
        src=ROOT/'paper'/name
        if src.exists():
            dest=archive/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    tex_path = ROOT/'paper/background_and_motivation.tex'
    tex = tex_path.read_text()
    start = '    (c) Measured Prefill latency'
    end = '  \\label{fig:motivation}\n'
    caption = r'''    (c) Measured Prefill latency for Qwen2.5-7B-Instruct-1M on two
    A100 PCIe 40\,GB GPUs (TP2, BF16, batch one), with MInference/DCA
    sparse Prefill above 32K context, including the final one-token EXTEND.
    Reuse starts from the same $(C-1)$-token KV and computes
    one new token. DRAM restores all historical KV by pinned H2D,
    without transfer--compute overlap.
    Full prefill starts from empty KV with 8K chunks and the same final
    one-token boundary. Reuse points are medians and min--max ranges of
    three timings; full prefill has one timing per length.
    K~=~1,024; M~=~$10^6$.}'''
    tex = between(tex,start,end,caption)
    a=tex.index('Right: three measured Prefill curves')
    b=tex.index('Both axes are logarithmic.}',a)+len('Both axes are logarithmic.}')
    tex=tex[:a]+'''Right: three measured Prefill curves for Qwen2.5-7B-Instruct-1M
    from 8K to 1,010,000 tokens. Blue circles denote HBM reuse,
    orange squares DRAM reuse without overlap, and red triangles
    full prefill with sparse attention above 32K. Both axes are logarithmic.}'''+tex[b:]
    body=fill(r'''To isolate the cost of populating KV,
Figure~\ref{fig:motivation}(\subref{fig:motivation-recompute}) compares
three paths: HBM reuse, DRAM reuse without transfer--compute overlap,
and full prefill from empty KV. We measure
Qwen2.5-7B-Instruct-1M~\cite{qwen2025qwen25oneM} on two A100 PCIe
40\,GB GPUs with TP2, BF16 weights and KV, and batch one. The SGLang
0.5.10rc0 worker uses MInference's vertical/slash sparse
attention~\cite{jiang2024minference} with the published Qwen1M head
configuration and DCA position handling. We retain the 32K context
threshold; above it, even the final one-token EXTEND uses sparse attention.
At or below the threshold, all paths use grouped dense DCA.
The sparse implementation shares GQA K/V without materializing repeated
heads. Prefix chunks group at most @GROUP@ query heads to bound selector
memory; the final query batches all heads. All three paths use the same
implementation and configuration.

Total context is $C=M+1$. Full prefill processes $M$ tokens in chunks of
at most 8,192, then executes one separate token. Each reuse path starts
from that same sparse-generated historical KV and executes the same
one-token EXTEND. HBM reuse has the prefix resident before timing.
DRAM reuse copies the complete historical KV from pinned host memory
and synchronizes the copy stream before computation. It neither
compresses KV nor loads only selected sparse blocks.
Every path ends at synchronized model-body completion with all $C$
tokens' KV resident, before vocabulary projection. Model loading and
backup creation are excluded; no failure is injected.

At 1,010,000 tokens, HBM reuse, DRAM reuse, and sparse full prefill
take @H@\,s, @D@\,s, and @F@\,s, respectively. KV reuse avoids
historical computation even with sparse Prefill enabled. HBM reduces
latency by @SAVING@\% relative to serialized DRAM in this configuration.
This comparison isolates a non-overlapping restore path; it does not
quantify HBM's advantage over a pipelined DRAM implementation.

The figure uses one fixed synthetic text stream. Each reuse point is
the median of three timings after one warmup; error bars show min--max
ranges, not independent-workload uncertainty. Full prefill has one
timing per length. Short forwards and operator checks precede timing,
including a 1M-context, 8K-query operator check. A complete original
all-head sparse model reference additionally precedes the 64K point;
no separate full-prefill warmup is run at 256K or 1.01M.
We check matched final hidden states, all-layer new-token KV, and greedy
outputs, and verify historical KV bitwise after restoration. CUDA events
confirm that DRAM transfer completes before computation. These
checks validate the measured paths under the same sparse configuration;
they do not establish equivalence to dense attention or long-context
task quality. Complete-history HBM is a reference state, not a
finite-HBM protection policy, and worker-level latency does not establish
end-to-end WCT benefits.''')
    tex=between(tex,'To isolate the cost of populating KV,','\\begin{figure}[t]\n',body)
    md_path=ROOT/'paper/paper_draft.md'
    md=md_path.read_text()
    md_body=fill('''**Figure 1(c) 支撑第二个动机。** 作业 @JOB@ 在同一次 2×A100-PCIE-40GB 分配上实测 8K、64K、256K 和 1,010,000。按用户最新要求，图中仅保留三条曲线：稀疏 Full Prefill、HBM reuse、DRAM reuse（无 Overlap）。1,010,000 处依次为 **@F@ s、@H@ s、@D@ s**；HBM 相对无重叠 DRAM 降低延迟 **@SAVING@%**。旧 dense 结果与已启动批次的 overlap 诊断均保留为历史，不进入当前三曲线对比。

**统一计算与数据条件。** Qwen2.5-7B-Instruct-1M，TP2、BF16 权重与 KV、batch 1，SGLang 0.5.10rc0。历史 Prefill 使用 MInference 官方 Qwen1M vertical/slash 参数与 DCA，保留 32K 上下文启用阈值。稀疏实现直接共享 GQA K/V，去除按 query head 重复展开 K/V 的临时副本；多 query 前缀每组最多 @GROUP@ 个 query heads 以控制选择器临时显存，最后单 query 合并全部 heads。超过 32K 上下文阈值时，三条路径末尾一个新 token 也执行同一稀疏 EXTEND；阈值以内统一使用 grouped dense DCA。没有另加多 token 的恢复尾部。

**终点与传输。** 总上下文 C=M+1；Full Prefill 从空 KV 开始按至多 8K 的块处理 M，再续算一个 token。两种复用都使用该次稀疏 Prefill 生成的历史 KV。HBM 在计时前驻留历史；DRAM 在计时内完整搬运 M-token KV 并同步 copy stream 后再计算，包含末尾不完整页，不做压缩、选择性加载或传算重叠。统一计时至模型主体返回且 CUDA 同步，全部 C-token KV 就绪；不含输出投影、备份创建、模型加载、排队或故障检测。

**样本与验证。** 一个固定合成重复文本流。HBM/DRAM 各预热一次、正式计时三次；点为中位数，误差线为 min–max，不是置信区间。Full Prefill 每长度一次，当前图共使用 28 次正式计时。测量前有短前向与七组算子验证，包含 1M 上下文／8K-query 最大形状；64K 另有原始 all-head 稀疏完整参考，256K/1.01M 不重复完整上下文预热。验证最后 token hidden、全部层新 KV 和 greedy 输出；每种复用每个长度额外逐字节检查完整历史 KV。CUDA 事件确认 DRAM 复制完成后才开始模型计算。稀疏配置内的恢复正确性不等于稀疏与 dense 数值等价，也不是任务质量评估。

**图像结论。** 启用稀疏 Prefill 后，保留 KV 仍可避免大量历史重算，HBM 又省去串行 H2D 的等待。这里的 DRAM 明确不与计算重叠，图中的 HBM 优势不能推广到允许传算流水线的 DRAM 实现。完整 HBM 驻留是参考状态，有限 Peer 容量及端到端 WCT 收益仍需另外验证。

[实验与选取协议](@BASE@/SPARSE_OVERLAP_PROTOCOL.md)；[图中三路径数据](@RUN@/published-three-paths.csv)；[完整原始记录](@RUN@/trials.jsonl)；[发布校验](@RUN@/publication-validation.json)。''')
    md=between(md,'**Figure 1(c) 支撑第二个动机。**','**独立衔接段：',md_body)
    refs=ROOT/'paper/references.bib'
    if 'jiang2024minference' not in refs.read_text():
        with refs.open('a') as fref:
            fref.write(r'''
@inproceedings{jiang2024minference,
  author = {Huiqiang Jiang and Yucheng Li and Chengruidong Zhang and Qianhui Wu and Xufang Luo and Surin Ahn and Zhenhua Han and Amir H. Abdi and Dongsheng Li and Chin-Yew Lin and Yuqing Yang and Lili Qiu},
  title = {{MInference} 1.0: Accelerating Pre-filling for Long-Context {LLMs} via Dynamic Sparse Attention},
  booktitle = {Advances in Neural Information Processing Systems},
  year = {2024},
  url = {https://proceedings.neurips.cc/paper_files/paper/2024/hash/5dfbe6f5671e82c76841ba687a8a9ecb-Abstract-Conference.html}
}
''')
    tex_path.write_text(tex);md_path.write_text(md)
    shutil.copyfile(output.with_suffix('.pdf'),ROOT/'paper/figures/recovery-cost.pdf')
    status=fill('''## Current: sparse three-path figure (@JOB@)

8K--1.01M physical measurements completed with the same sparse-generated KV.
At 1.01M: Full Prefill @F@ s; HBM @H@ s; DRAM without overlap @D@ s.
The user requested serial DRAM only. Plot published-three-paths.csv.
Earlier overlap diagnostics remain in their original allocations;
the current v2 measurement script runs only three paths.
Protocol and selection decision: SPARSE_OVERLAP_PROTOCOL.md.
Raw records: blsc/results/@JOB@/. Source snapshot: sparse-archive/@JOB@/.
Old dense and 64-token results below are historical, not sparse measurements.

''')
    readme=BASE/'README.md';readme.write_text(status+readme.read_text())
    (ROOT/'exports/reuse-prefill-sparse/publication.json').write_text(json.dumps({
        'run':str(run),'job_id':meta['job_id'],'data_sha256':hashlib.sha256((run/'measured.json').read_bytes()).hexdigest(),
        'plotted_paths':plotted_paths,'previous_paper_archive':str(archive),'validation':audit},indent=2)+'\n')
    print(json.dumps({'published_cost_panel':str(output),'latencies_at_1M_s':{'HBM':h,'DRAM_no_overlap':d,'FullPrefill':f}}))


if __name__=='__main__':main()
