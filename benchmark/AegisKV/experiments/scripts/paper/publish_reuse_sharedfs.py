"""Publish only a complete, validated sparse four-path physical matrix."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from publish_reuse_sparse import between

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'experiments/data/reuse-physical-qwen25-1m'
sys.path.insert(0, str(BASE))
from validate_prefill_sparse import validate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    args = ap.parse_args()
    run = args.run.resolve()
    audit = validate(run)
    data = json.loads((run/'measured.json').read_text())
    meta = data['metadata']
    assert meta['protocol'] == 'sparse_prefill_kv_fill_one_token_v3_sharedfs'
    assert meta['contexts'] == [8192, 65536, 262144, 1010000]
    assert meta['gpu'] == 'NVIDIA A100-PCIE-40GB'
    mounts = json.loads(meta['sharedfs_preflight']['mount'])['filesystems']
    assert any(m['fstype'] == 'dpc' for m in mounts), mounts
    ledger = json.loads((BASE/'blsc/budget.json').read_text())
    job, = [j for j in ledger['jobs'] if j.get('job_id') == meta['job_id']]
    assert job['terminal'] and job['last_slurm_state'] == 'COMPLETED'
    assert job['source_sha256']['measure_prefill_sparse.py'] == meta['script_sha256']
    assert job['source_sha256']['sg_sparse_backend.py'] == meta['sparse_adapter_sha256']
    assert job['source_sha256']['sharedfs_io.py'] == meta['sharedfs_io_sha256']
    for name, digest in job['source_sha256'].items():
        assert hashlib.sha256((BASE/'sparse-archive'/meta['job_id']/name).read_bytes()).hexdigest() == digest, name
    cleanup = json.loads((run/'sharedfs-terminal-cleanup.json').read_text())
    assert cleanup['remaining_checkpoint_files'] == 0 and not cleanup['directory_exists']
    paths = ['HBM', 'DRAM_no_overlap', 'SharedFS_no_overlap', 'FullPrefill']
    assert set(audit['paths']) == set(paths) and audit['formal_timings'] == 32
    audit.update(plotted_paths=paths, sharedfs_checkpoint_cleanup=cleanup)
    (run/'publication-validation.json').write_text(json.dumps(audit, indent=2)+'\n')
    with (run/'measured.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(data['rows'][0]))
        writer.writeheader(); writer.writerows(data['rows'])
    rows = {(r['context_tokens'], r['path']): r['latency_ms']/1000 for r in data['rows']}
    h, d, s, full = [rows[1010000, p] for p in paths]
    tokens = {'@H@': f'{h:.3f}', '@D@': f'{d:.3f}', '@S@': f'{s:.3f}', '@F@': f'{full:.2f}',
              '@SAVE@': f'{(1-h/d)*100:.1f}', '@JOB@': meta['job_id'], '@BASE@': str(BASE), '@RUN@': str(run)}
    def fill(text):
        for a, b in tokens.items(): text = text.replace(a, b)
        return text
    output = ROOT/'exports/reuse-prefill-sharedfs/recovery-cost'
    subprocess.run([sys.executable, str(ROOT/'experiments/scripts/paper/render_reuse_physical.py'),
                    str(run/'measured.json'), '--output', str(output), '--paths', *paths], check=True)
    archive = ROOT/'Archived'/('reuse-three-paths-before-sharedfs-'+time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    for name in ['background_and_motivation.tex', 'paper_draft.md', 'main.pdf',
                 'figures/recovery-cost.pdf', 'figures/preview/recovery-cost.png']:
        src = ROOT/'paper'/name
        if src.exists():
            dest = archive/name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dest)
    tex_path = ROOT/'paper/background_and_motivation.tex'
    tex = tex_path.read_text()
    caption = r'''    (c) Measured Prefill latency for Qwen2.5-7B-Instruct-1M on two
    A100 PCIe 40\,GB GPUs (TP2, BF16, batch one), with MInference/DCA
    sparse Prefill above 32K, including the final one-token EXTEND.
    Reuse restores the same $(C-1)$-token KV and computes one new token.
    DRAM and shared-filesystem reads/H2D complete before computation.
    Shared FS is the measured DPC mount, with direct I/O and no resident
    Linux file pages; internal storage caches are uncontrolled.
    Full prefill starts from empty KV with 8K chunks.
    HBM/DRAM show medians and min--max ranges of three timings;
    Shared FS/full prefill each have one timing per length.
    K~=~1,024; M~=~$10^6$.}'''
    tex = between(tex, '    (c) Measured Prefill latency', '  \\label{fig:motivation}\n', caption)
    start = tex.index('Right: three measured Prefill curves')
    end = tex.index('Both axes are logarithmic.}', start)+len('Both axes are logarithmic.}')
    tex = tex[:start]+'''Right: four measured Prefill curves for Qwen2.5-7B-Instruct-1M
    from 8K to 1,010,000 tokens: blue circles for HBM reuse, orange squares
    for serialized DRAM reuse, purple diamonds for serialized shared-filesystem
    reuse, and red triangles for full prefill. Both axes are logarithmic.}'''+tex[end:]
    body = fill(r'''To isolate the cost of populating KV,
Figure~\ref{fig:motivation}(\subref{fig:motivation-recompute}) compares
HBM, DRAM, and shared-filesystem reuse with full prefill from empty KV.
We measure Qwen2.5-7B-Instruct-1M~\cite{qwen2025qwen25oneM} on two A100
PCIe 40\,GB GPUs with TP2, BF16 weights and KV, and batch one, in one
allocation. The SGLang 0.5.10rc0 worker uses MInference's vertical/slash
sparse attention~\cite{jiang2024minference} with the published Qwen1M
head configuration and DCA position handling. Above the retained 32K
context threshold, even the final one-token EXTEND uses sparse attention;
shorter contexts use grouped dense DCA. GQA K/V is shared without repeated
head copies; prefix chunks group at most two query heads to bound selector
memory, while the final query batches all heads. All paths use the same
implementation and configuration.

Total context is $C=M+1$. Full prefill processes $M$ tokens in chunks of
at most 8,192, then executes one separate token. Every reuse path uses
that same sparse-generated historical KV and executes the same final
token. HBM has the history resident before timing. DRAM restores all
historical KV from pinned host memory and synchronizes the copy stream
before computation. Shared FS first reads a per-rank KV file from the
cluster's DPC shared filesystem into those pinned buffers, then performs
the same H2D and computation. File I/O, H2D and computation are serialized;
there is no compression or selective loading. At 1,010,000 tokens,
the historical KV contains 57.92\,GB across both ranks.
Every path ends at synchronized model-body completion with all $C$
tokens' KV resident, before vocabulary projection. Model loading and
backup creation are excluded; no failure is injected.

At 1,010,000 tokens, HBM, DRAM, shared-filesystem reuse, and full prefill
take @H@\,s, @D@\,s, @S@\,s, and @F@\,s, respectively.
KV reuse avoids historical computation even with sparse attention
enabled; HBM additionally avoids the measured restore waits.
Its latency is @SAVE@\% below serialized DRAM in this configuration.
This comparison does not quantify the benefit over transfer--compute
pipelines. Shared-filesystem latency includes file open/read/close,
H2D and the final forward. Direct I/O and page-residency checks exclude
Linux file-page hits, but DPC internal and server caches are uncontrolled;
these results are not cold-device or identified-SSD measurements.

We use one fixed synthetic text stream. HBM and DRAM each have
one warmup and three timings; points and bars show the median and
min--max range. Full prefill and Shared FS each have one timing per
length, with no file-read warmup. These are timing samples, not independent
workloads. Short forwards and seven operator checks precede timing,
including a 1M-context, 8K-query case. The 64K point additionally has a
complete original all-head sparse model reference; 256K and 1.01M have
no separate full-prefill warmup. We verify the complete checkpoint hashes,
historical KV, final hidden states, all-layer new KV, and greedy outputs.
CUDA events confirm serialized transfer and computation. These checks
validate the matched paths under the same sparse configuration, not
equivalence to dense attention or long-context task quality. Complete-history
HBM is an execution-state reference; it does not add a Peer-HBM tier to
the DRAM/storage design. Worker latency alone does not establish
end-to-end WCT benefits.''')
    tex = between(tex, 'To isolate the cost of populating KV,', '\\begin{figure}[t]\n', body)
    md_path = ROOT/'paper/paper_draft.md'
    md = md_path.read_text()
    md_body = fill('''**Figure 1(c) 支撑第二个动机。** 作业 @JOB@ 在同一次 2×A100-PCIE-40GB 分配上完成 8K、64K、256K 和 1,010,000 的四路径实测：HBM reuse、DRAM reuse、Shared FS reuse 和稀疏 Full Prefill。1,010,000 处分别为 **@H@ s、@D@ s、@S@ s、@F@ s**。HBM 相对串行 DRAM 降低延迟 @SAVE@%。旧三路径批次保留，当前图未拼接其他作业的数据。

**统一计算与终点。** Qwen2.5-7B-Instruct-1M，TP2、BF16、batch 1、SGLang 0.5.10rc0。所有路径共用官方 Qwen1M MInference vertical/slash 参数与 DCA；上下文超过 32K 时包括最后单 token 都使用稀疏 EXTEND。直接共享 GQA K/V；前缀每组最多两个 query heads，最后单 query 合并全部 heads。C=M+1；Full Prefill 从空 KV 按至多 8K 分块生成 M，再续算一个 token；复用路径使用该次生成的全部历史 KV。终点为模型主体完成并同步、全部 C-token KV 就绪，不含输出投影。

**共享文件系统路径。** 计算节点实际挂载为 DPC，不能按登录节点的 NFS 挂载或未知底层介质标成 SSD。每个 TP rank 将真实、未压缩 KV 保存到独立文件；计时内打开并读取到 pinned host buffer，关闭文件，完成全部 H2D 后再续算一个 token。文件读取、H2D 和计算均不重叠，不做选择性加载。1.01M 的逻辑历史 KV 合计 57,917,382,656 字节，文件中另有明确记录的 64 KiB 对齐填充。写文件、fsync、备份创建、缓存清理、校验及模型加载均在计时外。

**缓存与证据边界。** 使用 O_DIRECT；每次读取前后用 mincore 确认 Linux 文件页驻留为零，并在读取前清零目标缓冲区。全文件 SHA-256 与写入前匹配。DPC 内部缓存和服务端缓存状态不可控，因此图中称为 **Shared FS**，不是冷 SSD 延迟或纯介质带宽。

**样本与验证。** 一个固定重复文本流；HBM/DRAM 各预热一次、正式计时三次，显示中位数和 min–max；Full Prefill 和 Shared FS 每长度各一次，共 32 次正式计时。共享存储无文件读预热；256K/1.01M 不另做完整 Prefill 预热。七组原生算子比较包含 1M/8K-query 最大形状；64K 另有完整模型参考。所有路径检查 hidden、新 KV、greedy 输出和完整历史 KV，CUDA 事件检查串行 H2D。它们不证明稀疏/dense 等价或长上下文任务质量；图中 HBM 优势也不能直接推广到有传算重叠的实现。

[共享文件系统协议](@BASE@/SHAREDFS_PROTOCOL.md)；[四路径数据](@RUN@/measured.csv)；[原始计时](@RUN@/trials.jsonl)；[发布校验](@RUN@/publication-validation.json)；[共享 KV 清理记录](@RUN@/sharedfs-terminal-cleanup.json)。''')
    if '**Figure 1(c) 支撑第二个动机。**' in md:
        md = between(md, '**Figure 1(c) 支撑第二个动机。**', '**独立衔接段：', md_body)
    else:
        section = '''### 2.3 长上下文增加状态重建成本

![当前实测上下文恢复成本](figures/preview/recovery-cost.png)

'''+md_body
        md = between(md, '### 2.3 长上下文增加状态重建成本', '### 2.4 故障位置改变保护收益', section)
        md = md.replace('完整 HBM 驻留是参考状态，有限 Peer 容量及端到端 WCT 收益仍需另外验证。',
                        'HBM 仅作为执行状态参考，不重新引入 Peer-HBM 保护层；DRAM/存储设计的端到端 WCT 收益仍需另外验证。')
    tex_path.write_text(tex); md_path.write_text(md)
    shutil.copyfile(output.with_suffix('.pdf'), ROOT/'paper/figures/recovery-cost.pdf')
    table = '| 总上下文 | HBM (s) | DRAM，无重叠 (s) | Shared FS，无重叠 (s) | Full Prefill (s) |\n|---|---:|---:|---:|---:|\n'
    for c in meta['contexts']:
        table += '| '+str(c)+' | '+' | '.join(f'{rows[c,p]:.6f}' for p in paths)+' |\n'
    used = ledger['prior_inventory_gpu_seconds']+sum(j['actual_gpu_seconds'] for j in ledger['jobs'] if j.get('terminal'))
    summary = fill('''共享文件系统四路径完整实测已完成。作业 **@JOB@** 在同一次 2×A100-PCIe-40GB 分配测量 Qwen2.5-7B-Instruct-1M、TP2、BF16、batch1。DRAM 和 Shared FS 都不与计算重叠。Shared FS 为实际 DPC 文件系统，直接读取真实历史 KV，再串行 H2D 和 1-token EXTEND；不是 SSD 介质测量。Linux 文件页在读前/后均未驻留，但 DPC/服务端缓存不受控。

''')+table+fill('''
HBM/DRAM 各三次取中位数和 min–max；Shared FS/Full Prefill 各一次，共 32 次正式计时，一个固定合成文本流。所有恢复、全文件哈希和串行时序校验通过；末尾 KV 文件已删除且作业已退出。原三路径 1517055 和早期失败结果保留，不与本次样本混合。

协议：[SHAREDFS_PROTOCOL.md](@BASE@/SHAREDFS_PROTOCOL.md)。原始数据和校验：[@JOB@](@RUN@)。成本面板为 Figure 1(c)，更新 Markdown、LaTeX 和 canonical main.pdf。
''')+f'\n累计实际使用 {used} GPU·秒（{used/3600:.4f} GPU·小时），当前台账上限 {ledger["budget_gpu_seconds"]/3600:g} GPU·小时。\n'
    (BASE/'SHAREDFS_RESULTS.md').write_text('# Shared-filesystem KV reuse results\n\n'+summary)
    readme = BASE/'README.md'
    older = readme.read_text().replace('## Current: sparse three-path figure', '## Historical: sparse three-path figure', 1)
    readme.write_text('## Current: sparse four-path figure ('+meta['job_id']+')\n\n'+summary+'\n'+older)
    for name in ['SPARSE_RESULTS.md', 'SPARSE_OVERLAP_PROTOCOL.md']:
        p = BASE/name
        p.write_text('> Historical three-path record. The current published figure adds the measured Shared FS path from allocation '
                     +meta['job_id']+'. See [SHAREDFS_RESULTS.md](SHAREDFS_RESULTS.md) and '
                     '[SHAREDFS_PROTOCOL.md](SHAREDFS_PROTOCOL.md). The historical measurements below remain unchanged.\n\n'
                     +p.read_text())
    plan = ROOT/'experiments/plans/reuse-latency-insight.md'
    old = plan.read_text().split('\n', 1)[1].lstrip()
    plan.write_text('# KV 复用与 Prefill 填充时间：Motivation 图设计\n\n'+summary+'\n## 历史：稀疏三路径完整矩阵\n\n'+old)
    (output.parent/'publication.json').write_text(json.dumps(dict(run=str(run), job_id=meta['job_id'],
        data_sha256=hashlib.sha256((run/'measured.json').read_bytes()).hexdigest(),
        plotted_paths=paths, previous_paper_archive=str(archive), validation=audit), indent=2)+'\n')
    print(json.dumps(dict(job_id=meta['job_id'], latency_at_1M_s=dict(zip(paths, [h,d,s,full])))))


if __name__ == '__main__':
    main()
