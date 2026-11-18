"""Independent count-to-table audit and report for the matched three-8B comparison."""
import csv
import json
from pathlib import Path
import numpy as np

BASE = Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV')
HERE = Path(__file__).resolve().parent
DATA = BASE / 'experiments/data/kv-access-concentration-8b-20260921'
OUT = BASE / 'exports/kv-access-concentration-8b-20260921'
PREVIOUS = BASE / 'exports/kv-access-concentration-three-models-20260921'


def main():
    protocol = json.loads((DATA / 'protocol.json').read_text())
    blocks = protocol['historical_blocks_per_layer']
    with (DATA / 'layers.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    summaries = json.loads((DATA / 'summary.json').read_text())
    provenance = json.loads((DATA / 'model-provenance.json').read_text())
    token_checks = json.loads((DATA / 'tokenization-comparison.json').read_text())
    assert len(token_checks) == 9 and all(r['identical_to_nosa8b'] for r in token_checks)
    expected_rows = len(protocol['models']) * len(protocol['books']) * 32 * 2 * 2
    budget_checks = 0
    with np.load(DATA / 'counts.npz') as counts:
        assert len(counts.files) == len(rows) == expected_rows
        for r in rows:
            x = counts[r['counts_key']]
            assert x.shape == (blocks,) and np.all(x >= 0)
            assert int(x.sum()) == int(r['references'])
            assert np.count_nonzero(x) == int(r['distinct_blocks'])
            for label, k in protocol['budgets'].items():
                label = label.removesuffix('_percent')
                top = np.partition(x, len(x) - k)[-k:].sum() / x.sum()
                assert abs(top - float(r[f'top{label}_share'])) < 1e-12
                budget_checks += 1
        for s in summaries:
            group = [r for r in rows if r['model'] == s['model'] and r['metric'] == s['metric']
                     and int(r['window_queries']) == s['window_queries']]
            assert len(group) == 96
            for label in ('10', '20', '40'):
                assert abs(np.mean([float(r[f'top{label}_share']) for r in group])
                           - s[f'top{label}']['mean']) < 1e-12
    check = dict(count_vectors=expected_rows, independent_partition_budget_checks=budget_checks,
                 all_layer_macro_means_verified=True, all_count_totals_verified=True,
                 matched_input_token_checks=len(token_checks))
    (DATA / 'independent-audit.json').write_text(json.dumps(check, indent=2) + '\n')
    table = ['| Model | Queries | Top 10% | Top 20% | Top 40% | Blocks for 90% on mean curve |',
             '|---|---:|---:|---:|---:|---:|']
    for s in summaries:
        if s['metric'] != 'query_block':
            continue
        k90 = s['K_for_90pct_on_mean_curve']
        table.append(f"| {s['model']} | {s['window_queries']} | {s['top10']['mean']*100:.2f}% | "
                     f"{s['top20']['mean']*100:.2f}% | {s['top40']['mean']*100:.2f}% | "
                     f"{k90}/{blocks} ({k90/blocks*100:.2f}%) |")
    def get(model, n=256):
        return next(s for s in summaries if s['metric'] == 'query_block'
                    and s['model'] == model and s['window_queries'] == n)
    observations = '\n'.join(
        f"- **{model}**：256-query 窗口内，20% 块的平均访问份额为 "
        f"{get(model)['top20']['mean']*100:.2f}%；平均曲线达到 90% 份额需要 "
        f"{get(model)['K_for_90pct_on_mean_curve']/blocks*100:.2f}% 的块。"
        f"窗口内实际触及的不同历史块比例，逐层/文档平均为 "
        f"{get(model)['mean_distinct_fraction']*100:.2f}%。"
        for model in protocol['models'])
    jobs = '\n'.join(
        f"- **{model}**: revision `{p['revision']}`, Slurm `{p['gpu_job']}`; "
        f"native top-k `{p['native_config']['topk']}` per KV group; "
        f"[capture]({p['capture_folder']})." for model, p in provenance.items())
    nsa = provenance['NSA-8B']
    ratios = '/'.join(f"{k/blocks*100:.2f}%" for k in protocol['budgets'].values())
    report = f'''# Native sparse KV access concentration: three 8B models

根据用户要求，将当前三模型对照中的 NOSA-3B 替换为 **NOSA-8B 的新增原生 GPU 采集结果**。旧版本保留在 [previous comparison]({PREVIOUS}/README.md)，并未将 3B 数据更名为 8B。

本图回答同一层是否有少量历史 KV 块被反复访问。它是原生模型实测 trace 的离线频率分析；下一窗口预测命中率、真实缓存流量和故障恢复延迟需要分别验证。

## Results

{chr(10).join(table)}

{observations}

![Native access concentration]({OUT}/access-concentration.png)

横轴是每层最热历史块的比例，纵轴是这些块占该层全部历史块访问次数的比例。每个 Query 对同一块只计一次，合并多个 KV head 对它的访问；不同 Query 的重复访问继续计数。先逐文档、逐层归一化，再平均全部 32 层，最后等权平均 3 个文档。阴影为三个文档的最小值到最大值，不是置信区间。对角线为均匀频率参考。不同块的访问并集与重复访问的频率份额不同，冷块仍可能需要载入。

## Matched protocol

- 三个模型采用相同的 PG19 test 文档 10146、10321、10356。使用各自 tokenizer，并逐 token 核对三个模型的前 **32704 个 token IDs 完全一致**，见 [tokenization comparison]({DATA}/tokenization-comparison.json)。只有三个长文本诊断输入，并非多智能体任务轨迹。
- 历史 M=32192，随后 N=512；同时统计前 256 个 Query。两窗口嵌套，不作为独立重复。每层历史为 {blocks} 个 64-token 块；每块包括该层全部两个 KV heads，BF16 原始 K+V 共 64 KiB。
- NOSA-8B 固定版本的原生 `cis_pooling.py` 要求总长度严格小于 32768。因此本轮将三个模型的比较窗口统一前移一个 64-token 块，总长由旧版 32768 变成 **32704**。保留原生算子上限和选块规则；NSA 与 MiniCPM4.1 也按新窗口重新统计。
- NOSA-8B 新增三个完整前向。NSA 和 MiniCPM4.1 从各自原有 32768-token 完整因果前向中取 [32192,32704)，每个 Query 仍只能访问因果可见的 KV。后两个模型的数据来源和失败尝试记录保留在 [previous report]({PREVIOUS}/README.md)。
- Top 10%/20%/40% 向上取整为每层 51/101/202 块，实际比例为 {ratios}。所有层使用相同 K，块身份在每个文档、每层分别排序。
- 排序使用该窗口中已经观测到的访问，衡量该等层预算下的**事后最优频率份额**。不能解释为前一窗口预测后一窗口的覆盖率，也不等于 attention mass、不同需求块的覆盖率或节省的物理传输量。
- 这些是完整因果 prefill 前向中的 Query 轨迹，不是逐 token decode 的性能测量。原生 sink/local 访问计入统计，未调整原生选块预算。
- NSA-8B 特指 [fasa-org/MiniCPM-4-8B-NSA](https://huggingface.co/fasa-org/MiniCPM-4-8B-NSA)。该实现同时运行压缩 KV 和 top-k 原始 KV 分支；图仅统计原始 KV 块，所有模型的选择器辅助状态均不计入横轴。NSA 历史压缩 K+V 为 {nsa['compressed_prefix_bytes_per_layer']/2**20:.3f} MiB/层（{nsa['compressed_prefix_vectors']} 个压缩位置），完整恢复预算还需计入这些状态。
- 原生 top-k 为 NOSA 64/group、NSA 64/group、MiniCPM4.1 96/group，均含各自原生 sink/local 配额。三个模型虽然都是 8B、32 层，横向差异仍同时包含训练、结构及原生稀疏配置差异。

## All layers

![All layers]({OUT}/concentration-by-layer.png)

保留全部 32 层，无高集中度层筛选。精确值在 [layers.csv]({DATA}/layers.csv)。另保留 [原生 KV-group 选块事件口径]({OUT}/selector-event-concentration.png)；这个次要口径不做跨组去重。

## Native execution and verification

{jobs}

NOSA-8B 使用 [官方公开权重](https://huggingface.co/openbmb/NOSA-8B)。固定 revision 下的配置、模型源码、tokenizer 与完整 16 GB safetensors 已对照发布元数据逐文件核验，见 [checkpoint verification]({HERE}/checkpoint-verification.json)。

三个成功的 8B 采集均在 Slurm 分配的两张 RTX 4090 上按层加载，前 16 层在 GPU 0，后 16 层在 GPU 1，batch=1、BF16。保留发布权重与原生 attention 数学；设备上下文适配仅确保原生 Triton launcher 使用当前层所在 GPU。NOSA-8B 未修改原生 `MAX_LEN`，没有 CPU 构造选块。对每个模型，开启/关闭采集器的配对前向最大 logit 差为 0。NOSA 的真实 packed mask 与选块索引逐层核对，本轮分析还独立重建新窗口的 96 份 mask。其余两个模型在原生算子入口核对选块 tensor 身份，NSA 压缩分支实际执行且输出有限。

这些检查验证采集一致性，不把有采集开销的前向耗时当作模型性能。旧 NSA API 的 `cu_seqlens_v` 参数桥接与 MiniCPM4.1 单卡/双卡选块一致性记录见旧版报告。权重加载、双卡显存、实际 GPU、脚本/输入/源码哈希和原始 trace 均保留。

## Artifacts and reproduction

- [Frozen protocol]({HERE}/protocol.json), [capture script]({HERE}/capture_nosa8b.py), [Slurm script]({HERE}/capture.sbatch), [capture log]({HERE}/capture-153951.log).
- [Analysis]({HERE}/analyze.py), [renderer]({HERE}/render.py), [independent audit]({HERE}/audit_and_report.py).
- [Summary]({DATA}/summary.json), [documents]({DATA}/documents.csv), [counts]({DATA}/counts.npz), [source hashes]({DATA}/source-sha256.json), [independent checks]({DATA}/independent-audit.json).
- [Vector PDF]({OUT}/access-concentration.pdf), [editable SVG]({OUT}/access-concentration.svg), [all-layer PDF]({OUT}/concentration-by-layer.pdf).

在项目根目录用 `benchmark/AegisKV/experiments/native-sparse/runtime-20260914/venv/bin/python` 执行 `analyze.py --nosa-dir <NOSA capture folder> --nsa-dir <NSA capture folder>`；用项目 `.venv/bin/python` 执行 `render.py`、`audit_and_report.py`。采集只能通过 Slurm 运行。当前产物位于 experiments/ 与 exports/，未改动论文正文或 main.pdf。
'''
    (OUT / 'README.md').write_text(report)
    (DATA / 'README.md').write_text(f'[Full report]({OUT}/README.md)\n')
    print('\n'.join(table))


if __name__ == '__main__':
    main()
