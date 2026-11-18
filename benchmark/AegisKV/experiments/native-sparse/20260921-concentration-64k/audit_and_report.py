"""Verify saved count vectors against tables and document the actual experiment."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

BASE=Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV')
HERE=Path(__file__).resolve().parent
DATA=BASE/'experiments/data/kv-access-concentration-64k-20260921'
OUT=BASE/'exports/kv-access-concentration-64k-20260921'


def main():
    protocol=json.loads((DATA/'protocol.json').read_text())
    summary=json.loads((DATA/'summary.json').read_text())
    provenance=json.loads((DATA/'model-provenance.json').read_text())
    with (DATA/'layers.csv').open() as f: rows=list(csv.DictReader(f))
    with (DATA/'documents.csv').open() as f: docs=list(csv.DictReader(f))
    with (DATA/'curves.csv').open() as f: curves=list(csv.DictReader(f))
    budgets={'10':102,'20':204,'40':407}
    checked=0
    with np.load(DATA/'counts.npz') as archive:
        assert len(archive.files)==len(rows)==372
        for r in rows:
            counts=archive[r['counts_key']]
            assert counts.shape==(1016,) and counts.max()<=512 and counts.min()>=0
            assert counts.sum()==int(r['query_block_references'])
            assert np.count_nonzero(counts)==int(r['distinct_blocks'])
            for label,k in budgets.items():
                value=np.partition(counts,-k)[-k:].sum()/counts.sum()
                assert abs(value-float(r[f'top{label}']))<1e-12
                checked+=1
        for s in summary:
            for label,k in budgets.items():
                group=[r for r in rows if r['model']==s['model']]
                assert len(group)==3*s['layers']
                assert abs(np.mean([float(r[f'top{label}']) for r in group])-s[f'top{label}_mean'])<1e-12
                doc_values=[]
                for d in [d for d in docs if d['model']==s['model']]:
                    actual=np.mean([float(r[f'top{label}']) for r in group if r['book_id']==d['book_id']])
                    assert abs(actual-float(d[f'top{label}']))<1e-12
                    doc_values.append(actual)
                point=next(p for p in curves if p['model']==s['model'] and int(p['k'])==k)
                assert abs(float(point['coverage_mean'])-np.mean(doc_values))<1e-12
                assert abs(float(point['coverage_min'])-min(doc_values))<1e-12
                assert abs(float(point['coverage_max'])-max(doc_values))<1e-12
    audit=dict(status='passed',count_vectors=372,independent_partition_checks=checked,
        all_layer_macro_means_verified=True,document_ranges_verified=True,
        target_full_forward_runs=12,source_texts=3,
        note='Layers and Queries are repeated observations, not independent experimental replicates')
    (DATA/'independent-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    table=['| Model | Top 10% | Top 20% | Top 40% | Blocks for 90% of mean references |',
           '|---|---:|---:|---:|---:|']
    for s in summary:
        label=s['model']+('*' if s['model'] in ('NOSA-8B','NSA-8B') else '†' if s['model'].startswith('Qwen') else '')
        table.append(f"| {label} | {100*s['top10_mean']:.2f}% | {100*s['top20_mean']:.2f}% | "
            f"{100*s['top40_mean']:.2f}% | {s['k90_for_mean_curve']}/1016 "
            f"({100*s['k90_fraction_for_mean_curve']:.2f}%) |")
    jobs='\n'.join(f"- **{model}**: Slurm `{p['environment']['slurm_job_id']}`; checkpoint revision "
                   f"`{p['environment']['revision']}`; [capture]({p['capture_folder']})."
                   for model,p in provenance.items())
    qwen=provenance['Qwen2.5-7B-Instruct-1M']
    qp=Path(qwen['capture_folder'])
    operator=json.loads((qp/'packed-kernel-reference.json').read_text())
    max_ref_error=max(x['max_abs_error'] for x in operator)
    nsa=provenance['NSA-8B']
    qwen_blocks=np.mean([float(r['mean_blocks_per_query']) for r in rows if r['model'].startswith('Qwen')])
    report=f'''# 64K / 512-Query KV access concentration

四个模型已统一为 **65536 tokens 总上下文**，分析末尾 **512 个 Query**；历史长度 M=65024，对应每层 1016 个 64-token 历史块。旧 32K 结果保留在 [old report]({BASE}/exports/kv-access-concentration-8b-20260921/README.md)。本文档与图像为独立实验产物，未修改论文正文或 main.pdf。

## Results

{chr(10).join(table)}

*NOSA-8B、NSA-8B 的发布配置上限是 32768，本次是保留权重与 RoPE 的 **64K 外推诊断**，并未证明其在 64K 的任务质量。†Qwen 使用官方 Qwen 选块函数与 MInference CUDA/Triton 后端，详细边界见下文。

![64K access concentration]({OUT}/access-concentration.png)

横轴是每层最热历史块的比例；纵轴是它们占该层历史块访问次数的份额。每个 Query 对同一层同一物理块只计一次，合并所有 heads；不同 Query 的重复访问继续计数。先在每篇文本、每层分别按频率排序及归一化，再平均模型的所有层，最后等权平均三篇文本。阴影为三篇文本的最小值到最大值，**不是置信区间**。

本图是窗口内的**事后最优频率覆盖**。它回答“是否存在少量反复使用的块”，并不检验“过去窗口能否预测下一窗口”。它也不是 attention mass、不同需求块的覆盖率、传输字节命中率或恢复延迟。观察来自完整 prefill 中的 Query，不是逐 token decode 性能测试。

在这些输入中，NOSA 和 NSA 的最热 20% 原始层块覆盖超过 90% 的访问；MiniCPM4.1 需要接近 40% 的块才能超过 90%。Qwen 在本轮存储粒度下接近均匀：平均每个 Query 合并所有 heads 后触及 {qwen_blocks:.2f}/1016 个历史层块（{qwen_blocks/1016*100:.2f}%）。其发布的部分 head 采用较大的 vertical/slash 配额，而 64-token 分块和跨 head 并集进一步扩大了块覆盖范围。这是整层块粒度的观察，不代表 token/head 粒度的稀疏性或注意力权重分布；应保留该负面结果。

## Matched protocol and limits

- 四模型均使用 PG19 test 的原始文本 10321、10356、10762，不重复或补齐文本。原有 10146 在 MiniCPM/NOSA tokenizer 下只有 62675 tokens，无法满足 64K，因此保留另两篇，并在采集前换入下一个足够长的 test 文本。见 [length check]({HERE}/input-length-check.json)。样本是三个长文本诊断输入，尚不是多智能体轨迹。
- NOSA、NSA、MiniCPM4.1 的 65536 个输入 token IDs 已逐个核对完全相同；Qwen 使用自己的 tokenizer，因此虽然同为这些原始文本的前缀且 token 数相同，实际消耗的文本长度并不相同。见 [input checks]({DATA}/input-checks.json)。
- 12 个目标完整前向：每模型三篇文本各一次；此外每模型执行一对有/无 observer 的校验前向。三篇文本是不同输入样本，层和 Query 不视作额外独立实验重复；未从这些样本推导总体显著性。
- 每层逻辑存储块包含该层全部 KV heads 的连续 64 tokens。前三模型为 2 KV heads、32 层，每块原始 BF16 K+V 为 64 KiB；Qwen 为 4 KV heads、28 层，每块 128 KiB。因此比较的是各模型原始 KV 的相同比例，并非跨模型相同总字节容量。
- Top 10%/20%/40% 向上取整为 K=102/204/407 块，即实际 10.04%/20.08%/40.06%。对同一百分比，模型所有层采用相同 K，块身份逐文档、逐层分别排序。
- 原生 sparse selector 的预算完全保留：NOSA、NSA 为 64 blocks/KV group，MiniCPM4.1 为 96 blocks/KV group，含各自 sink/local 配额；Qwen 保留发布配置的每 Query head vertical/slash 预算及官方修正规则。没有为取得更高集中度调整预算或筛选层。
- 固定原生选块数量而增加历史长度，本身会降低每次访问相对历史 KV 的比例；因此不能把相较旧图的提高全部归因于更强的时间局部性。此外本轮替换了一篇文本，旧 32K 与新 64K 不是严格的仅长度变化对照。
- 图中只统计原始历史 KV。NSA 实际同时执行压缩分支，历史压缩 K+V 另需 {nsa['compressed_prefix_bytes_per_layer']/2**20:.3f} MiB/层（{nsa['compressed_prefix_vectors']} 个压缩位置）。选择器/池化/压缩状态、元数据和故障后的重建计算需另外计入恢复预算。

## All layers

![All-layer concentration]({OUT}/concentration-by-layer.png)

图包含 NOSA、NSA、MiniCPM4.1 的全部 32 层及 Qwen 的全部 28 层。曲线为三篇文本均值，阴影为逐层文本 min–max。未只选浅层或高集中度层。完整数值见 [layers.csv]({DATA}/layers.csv)，12 条文档均值见 [documents.csv]({DATA}/documents.csv)。

## Native paths and checks

{jobs}

所有成功采集均通过 Slurm，batch=1、BF16，在两张 GPU 上按层加载，并核对实际分配 GPU 没有其他进程。NOSA、NSA、MiniCPM4.1 使用 RTX 4090；Qwen 的原生 MLP 在 24 GiB 显存上 OOM 后改用 80GB GPU（实际分配为 A800 + A100 PCIe），保持模型计算不变。完整权重、checkpoint revision、模型源码、输入、采集脚本、原始 trace 和数值检查均记录在 [model provenance]({DATA}/model-provenance.json) 及 [source hashes]({DATA}/source-sha256.json)。硬件不一致且存在采集开销，因此运行耗时不用于速度比较。

**NOSA-8B**：发布 checkpoint 的 max_position_embeddings=32768，原生池化也限制长度。本轮单独复制池化实现，仅将工作区长度上限扩大到 65536、允许等于上限；保留权重、RoPE、attention 规则。8704-token 全模型校验比较原生池化与扩展池化+observer，最大 logit 差为 0。64K 运行记录真实选块及算子 packed mask；分析另外独立重建并核对 96 个层/文本的 packed mask。这验证采集和边界扩展的一致性，不验证外推任务质量。

**NSA-8B**：指 [fasa-org/MiniCPM-4-8B-NSA](https://huggingface.co/fasa-org/MiniCPM-4-8B-NSA)。发布长度配置也是 32768，本次保留其权重/RoPE。原生 64K 全 head 压缩分支中间张量导致 24 GiB GPU OOM；成功版本将该分支按每 4 个 Query heads 分批运行，仍使用原生 CUDA 算子、softmax、einsum，不改变 selector。8704-token 全模型与原始全 head 分支比较，最大 logit 差为 0。64K 的压缩分支实际执行且输出有限。沿用已记录的旧 API 参数桥接与 GPU device 上下文适配。

**MiniCPM4.1-8B**：在发布 65536 长度内运行，原生 InfLLM-v2 selector/attention 保持不变。有/无 observer 的 8704-token 配对前向最大 logit 差为 0，核对传入原生算子的选块 tensor 身份。

**Qwen2.5-7B-Instruct-1M**：使用发布权重；从 QwenLM/vllm 固定源码提取原始 selector 函数，使用发布的 refined head 配置，保留 `vertical_size==30` 时加 100 的官方规则。完整 64K prefill chunk 超过官方 32K 稀疏阈值，并完全位于第一个 DCA chunk（262144−8192）内，无跨 chunk attention 或 LSE 合并。保留模型 Q/K/V/O 投影与 RoPE。

Qwen selector 使用当前 prefill chunk 最后 64 个 Queries 来选 vertical/slash，原生 attention kernel 再执行因果掩码。这不是逐 Query 的在线预测器，也不能把该窗口内选块解释为过去 512 Queries 预测未来 512 Queries。推理输入 chunk 划分会影响这种选块，故本轮固定为单个完整 65536-token chunk。

Qwen attention 后端显式使用 Microsoft MInference 的原生 CUDA index packer 与 Triton fallback（revision `29ef1974fcb5a1440ccf92d7d7996900230fddcf`），并非声称完整复现生产 vLLM 调度路径。成功版本的 selector 保留官方全部 28 heads 一起计算的调用方式、group_size=7 的 GQA 展开，以及跨 head 最大 top-k buffer 的排序规则；attention kernel 按 head 启动以记录索引。记录的是 **实际 packed block/column 索引**，不是 CPU 构造的理想 vertical/slash 图案；将实际 64-token 访问范围和单列映射为 64-token 存储块，未对不对齐的起点简单截断。每 Query 合并 28 个 Query heads 所触及的物理层块。

Qwen 33024-token 有/无 observer 全模型最大 logit 差为 0；另外在校验输入及每个 64K 输入的第 1 层第 1 head，抽查窗口首 Query、第 64 个及末 Query，将真实 packed mask 对应的 FP32 softmax 参考与原生 Triton 输出比较，12 点最大绝对误差为 {max_ref_error:.6f}。原生 BF16 内核先缩放并量化 Q，因此该参考不是逐位相等基线；逐点误差见 [operator checks]({qp}/packed-kernel-reference.json)。此检查并不覆盖全部层的数值等价或任务质量。

## Retained attempts

- 153956 / 153958：NOSA / MiniCPM 的配对校验通过，目标输入 10146 长度不足而退出。
- 153957：NSA 触发发布配置 32K 长度检查；随后明确采用带标记的外推诊断。
- 153959：NSA 在替换输入前遇到同一文本长度不足。
- 153962：NSA 原生全 head 压缩分支在 64K 的显存分配失败；改为分批 head 计算并验证。
- 153966：Qwen 发现环境存在可自动选中的其他 sparse backend；成功脚本显式固定 MInference CUDA/Triton 路径。
- 153968：Qwen 检测到分配 GPU 上存在其他进程而自动退出；切换节点重试，没有终止其他进程。
- 153969：Qwen 通过 33024-token 采集一致性验证，但原生 MLP 的 64K 中间张量导致 RTX 4090 显存不足；改用更大显存的 A100，未修改 MLP 或 attention。
- 153971：取消该早期逐 head selector 调度尝试，成功版本改为原始全 head selector 调用；旧脚本保留为 `capture_qwen_per_head_attempt.py`，不纳入正式图像。
- 所有失败日志保留在 [campaign]({HERE})，不算作有效样本。后续若有接口适配失败也保留对应日志；成功样本只取上述 provenance 中明确完成的任务。

## Artifacts and reproduction

- [Raw captures and scripts]({HERE})；[protocol]({HERE}/protocol.json)；[analysis]({HERE}/analyze.py)；[renderer]({HERE}/render.py)；[audit]({HERE}/audit_and_report.py)。
- [Summary]({DATA}/summary.json)；[count vectors]({DATA}/counts.npz)；[analysis checks]({DATA}/analysis-checks.json)；[independent audit]({DATA}/independent-audit.json)。
- [Concentration PDF]({OUT}/access-concentration.pdf) / [SVG]({OUT}/access-concentration.svg)；[all-layer PDF]({OUT}/concentration-by-layer.pdf)。

从项目根目录，用 native-sparse runtime-20260914 venv 执行 `analyze.py --qwen-dir {qp}`；用项目 `.venv/bin/python` 执行 `render.py` 和 `audit_and_report.py`。GPU 重新采集通过对应 `.sbatch`，每次创建带任务 ID 的新目录。

用户后续授权可使用 BLSC-A100，并指定参考 Motivation 任务。已读取该任务中的 jump 跳板、远程隔离环境与预算提交脚本；本轮只读检查确认连接成功、远程 aarch64 环境、稀疏构建和 Qwen checkpoint 均在。见 [BLSC read-only check]({HERE}/blsc-readonly-check.json)。本轮 GPU 样本已在本地集群完成，未新增 BLSC GPU 分配；跨平台重新运行需要重新编译本地 x86_64 CUDA 扩展，不能直接复制二进制。
'''
    (OUT/'README.md').write_text(report)
    (DATA/'README.md').write_text(f'[Full report]({OUT}/README.md)\n')
    print('\n'.join(table))


if __name__=='__main__':main()
