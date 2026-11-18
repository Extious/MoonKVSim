# Native sparse KV access concentration: three-model diagnostic

本轮回答：同一层中是否有一小部分历史 KV 块被反复访问。**这是原生模型实测 trace 的离线频率分析，不是下一窗口预测命中率，也不是 HBM/DRAM 流量或故障恢复延迟。**

## Results

| Model | Queries | Top 10% | Top 20% | Top 40% | Blocks for 90% on mean curve |
|---|---:|---:|---:|---:|---:|
| NOSA-3B | 256 | 51.61% | 89.10% | 99.39% | 104/504 (20.63%) |
| NOSA-3B | 512 | 52.69% | 88.16% | 98.99% | 108/504 (21.43%) |
| NSA-8B | 256 | 49.07% | 77.26% | 96.17% | 149/504 (29.56%) |
| NSA-8B | 512 | 48.15% | 74.85% | 95.02% | 160/504 (31.75%) |
| MiniCPM4.1-8B | 256 | 35.72% | 60.09% | 87.44% | 219/504 (43.45%) |
| MiniCPM4.1-8B | 512 | 34.64% | 56.77% | 83.29% | 247/504 (49.01%) |

这组输入上，NOSA 的频率集中度最高，NSA 次之，MiniCPM4.1 更分散。以 256 Query 为例，平均达到 90% 的访问份额分别需要约 20.6%、29.6%、43.5% 的历史块；不是三种模型都能用 20% 的块覆盖约 90% 的访问。扩大到 512 Query 后，三者的 top-20% 份额分别为 88.16%、74.85%、56.77%。

同时，256 Query 窗口内实际触及的不同历史块比例，逐层/文档平均分别是 NOSA 49.56%、NSA 63.68%、MiniCPM4.1 84.55%。因此，即使存在高频热点，也不能据此认定剩下的冷块不需要载入；它们可能仅被访问少数几次。

![Native access concentration](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/access-concentration.png)

曲线横轴是每层最热历史块的比例，纵轴是这些块占该层全部历史块访问次数的比例。每个 Query 对同一块只计一次，不重复累计其多个 KV head 的访问；不同 Query 的重复访问继续计数。先逐文档、逐层归一化，再平均全部 32 层，最后等权平均 3 个文档。阴影为文档之间的最小值到最大值，不是置信区间。对角线是均匀频率的参考线。

## Protocol and limitations

- 三个模型分别使用同一组 PG19 test 文档 10146、10321、10356 的文本前缀与各自 tokenizer，事后逐 token 核对确认三个模型的这 32768 个输入 token IDs 也完全相同。**只有 3 个文档；它们是长文本诊断输入，并非多智能体任务轨迹。**
- 总长度 32768 tokens：历史 M=32256，随后 512 个 Query；同时统计前 256 个 Query。两个窗口嵌套，不能作为独立重复。历史共有 504 个 64-token 块，每层一个块包括全部 2 个 KV heads，BF16 共 64 KiB。
- Top 10%/20%/40% 向上取整为每层 51/101/202 块，实际比例为 10.12%/20.04%/40.08%。所有层使用相同 K；每个文档和层分别按该窗口中的真实访问频率排序。
- **排序看到了同一窗口的未来访问。** 因此它衡量热点集中度及该等层预算下的事后最优频率份额，不能当作前一窗口预测下一窗口的结果。频率份额也不等于所有不同需求块的覆盖率。
- 使用完整因果 prefill 前向中的 Query，不是逐 token decode 的性能测量。原生 sink/local 访问包含在统计中，未调小原生 top-k 来提高集中度。
- NOSA-3B 复用已有 33280-token 实测前向中 [32256,32768) 的因果窗口。该窗口保存的原生 packed masks 已逐层重新核对，未生成新的 NOSA 数据。其余两个模型新增各 3 次 32768-token 完整前向。
- NSA-8B 特指 [fasa-org/MiniCPM-4-8B-NSA](https://huggingface.co/fasa-org/MiniCPM-4-8B-NSA)，是该公开发布的具体实现。它同时执行压缩 KV 与 top-k 原始 KV 分支。图仅统计原始 KV 块；所有模型的选择器辅助状态均不计入横轴。NSA 的历史压缩 K+V 还需 1.968 MiB/层（2015 个压缩位置），不能由原始块集中度推断完整恢复状态预算。
- 原生预算不同：NOSA 和 NSA 的 top-k 为 64/group，MiniCPM4.1 为 96/group（包括 32 个本地块的配额）。因此横向差异同时包含模型、训练和原生稀疏配置差异，不是控制所有变量后的算法优劣比较。

## All layers

![Every layer](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/concentration-by-layer.png)

每条线保留全部 32 层，没有挑选集中度高的层。精确逐层数据在 [layers.csv](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/layers.csv)。另外保留 [按原生 KV-group 选块次数累计的次要口径](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/selector-event-concentration.png)，该口径不把跨组重复块去重，不能替代上面的物理层块口径。

## Native execution provenance

- **NOSA-3B**: revision `c5a4d505d5811f7555d786a031a4623787da7fb0`, Slurm `151771`; native top-k `64` per KV group (includes native sink/window policy); [capture](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915-nosa-3b).
- **NSA-8B**: revision `126d6d657ce3b18d99f835ec0ef326e4899fa370`, Slurm `153894`; native top-k `64` per KV group (includes native sink/window policy); [capture](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/nsa8b-attempt-153894).
- **MiniCPM4.1-8B**: revision `3a8dfed9c79a45e07dbff95bcd49d792343fa1a3`, Slurm `153892`; native top-k `96` per KV group (includes native sink/window policy); [capture](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/minicpm41).

两个新增 8B 采集使用两张 RTX 4090 分层加载：前 16 层在 GPU 0，后 16 层在 GPU 1，batch=1，BF16。每层保持发布权重、原生稀疏配置与 attention 计算；没有 CPU 权重卸载或人为构造选块。记录器开启/关闭的配对前向最大 logit 差均为 0，实际选块 tensor 的身份在原生算子入口核对。NSA 的压缩分支也被实际执行并检查有限输出。设备映射、加载结果、权重/源文件 SHA256、GPU 信息与日志随数据保留。MiniCPM4.1 的双卡选块与先前单卡留下的 46 份 trace（32 层校验输入和 14 层完整长度输入）完全一致，见 [placement-equivalence](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/minicpm41-placement-equivalence.json)。NSA 使用固定版本的 OpenBMB 原生 InfLLM CUDA 内核；为适配旧 checkpoint API，仅补充与压缩 K 相同的 V 长度元数据 `cu_seqlens_v`，没有改动注意力分数或选块规则。原始 Triton launcher 默认使用当前 GPU，双卡执行时显式设置为 Query 所在 GPU；这只是设备上下文适配。日志中的旧 `peak_cuda_allocated_bytes` 字段仅对应设备 0，不是双卡显存总量，本报告不作性能比较。

保留的失败/调度记录：153888 在单张 24GB GPU 上完整 MiniCPM4.1 前向显存不足；153889 等待 L40S 资源后取消；153891 因分配的 A100 上存在其他 GPU 进程而在模型加载前主动停止。153893 的 NSA 首次双卡尝试因原生 Triton launcher 的默认 GPU 上下文不匹配而失败，显式设置设备上下文后重跑。上述失败尝试没有完整结果，不进入统计。最终成功任务编号见上述 provenance。

## Reproduction and artifacts

- [Frozen protocol](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/protocol.json), [analysis](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/analyze.py), [renderer](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/render.py), [independent audit](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-new-models/audit_and_report.py).
- [Summary](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/summary.json), [documents](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/documents.csv), [count vectors](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/counts.npz), [source hashes](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/source-sha256.json), [independent audit](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921/independent-audit.json).
- [Vector PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/access-concentration.pdf), [editable SVG](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/access-concentration.svg), [layer PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-three-models-20260921/concentration-by-layer.pdf).
- 使用 `runtime-20260914/venv/bin/python` 运行采集和 `analyze.py --nsa-dir <successful NSA capture folder>`；使用项目 `.venv/bin/python` 运行 `render.py` 和 `audit_and_report.py`。采集只在 Slurm GPU 分配中运行。

诊断产物保存在 experiments/ 与 exports/，未改动当前论文正文或 main.pdf。
