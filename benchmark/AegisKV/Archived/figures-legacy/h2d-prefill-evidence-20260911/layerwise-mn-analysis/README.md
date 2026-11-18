# 逐层比较：Prefill(N | M) 与 H2D(M)

这是用户在 2026-09-11 明确纠正后的比较口径：第 1 层已有 M 个历史 token 的 KV 在接管 GPU 的 HBM 中；第 1 层处理 N 个待补算 token 的同时，从 Host 加载第 2 层这 M 个历史 token 的 KV。

两项分别是 **当前一层的 N token 增量 Prefill** 和 **下一层的 M token 历史 KV 搬运**。此前完整前缀的 360/192 ms 文献比较不能直接回答本问题，也不能通过除以层数修复其中 M/N 相同的限制。

![逐层解析比较](layerwise-prefill-vs-h2d.png)

## 变量与模型

结构参数来自 [Qwen3-8B 官方 config](https://huggingface.co/Qwen/Qwen3-8B/raw/main/config.json)，于 2026-09-11 核对。这里只计算单个 dense/GQA Transformer 层，不乘总层数。

- d=4096：hidden size；Dq=32×128=4096；Dkv=8×128=1024；I=12288：MLP intermediate size。
- BF16 KV：每元素 s=2 字节。单层每 token 的 K+V 共 2×Dkv×s=4096 字节。
- M=32768，N∈{128,512,1024}，单请求，TP=1。模型权重与本层 M 个历史 KV 已就绪，下一层 H2D 与本层计算同时开始。
- **F=100 TFLOP/s、B=25 GB/s 都是未校准的有效速率假设**，没有将它们标成某张 GPU 的实测或标称性能。

下一层传输时间：

    T_H2D(M) = 2 M Dkv s / B

单层线性矩阵参数数目：

    P_layer = 2 d Dq + 2 d Dkv + 3 d I = 192937984

当前层 N 个新位置访问 M 个历史位置，再访问新增 N 个位置的因果三角部分。每次乘加按 2 FLOPs 计，QK 与 AV 都计入：

    FLOPs_prefill(N | M)
      = 2 N P_layer + 4 Dq [MN + N(N+1)/2]
    T_prefill(N | M) ≈ FLOPs_prefill / F

Prefill 指完整一层的前向，包括 QKV 投影、attention、输出投影与 FFN。这些工作可以为下一层的数据提供传输窗口。**只生成本层 K/V 的两次投影**工作量为 4NdDkv，时间更短，但只看这两次投影会漏掉同层后续可重叠的计算。没有本层完整的输出隐藏状态，还不能生成下一层 N 个 token 的 QKV。

## 结果与适用范围

| N | 当前层增量 Prefill | 下一层 M 个 token 的 H2D | 当前层计算窗口是否足以覆盖传输 |
|---:|---:|---:|---|
| 128 | 1.18 ms | 5.37 ms | 否，计算先结束 |
| 512 | 4.75 ms | 5.37 ms | 否，计算略先结束 |
| 1024 | 9.53 ms | 5.37 ms | 是，传输先结束 |

这里下一层要搬运 128 MiB。在上述假设下，交点 N≈578.84，整数 N≥579 后当前层计算时间不短于传输时间。交点依赖算力与带宽，不能当作通用阈值。更多 F/B 参数组合的交点保存在 REVIEW.json。

当 T_prefill≥T_H2D 时，在允许复制与计算并发、缓冲充足且无竞争减速的模型中，下一层数据能在本层计算完成前到齐。这是足够条件；若细分算子，下一层自己的 QKV 投影也可能先执行，因此不把 max(T_H2D−T_prefill,0) 无条件等同于实测 attention stall。

算力模型忽略显式的 HBM 访存、算子启动、归一化、RoPE、softmax 和激活成本；不用于预测 N≈1 的 decode 延迟。传输忽略固定 DMA 开销、非连续页布局、NUMA 和竞争。没有运行模型、GPU、故障或 WCT 实验。单 query 的原生稀疏率也不能直接代入为物理传输字节比例。

## 文件

- [PNG](layerwise-prefill-vs-h2d.png)、[矢量 PDF](layerwise-prefill-vs-h2d.pdf)、[SVG](layerwise-prefill-vs-h2d.svg)，按 168 mm 宽导出。
- [计算与绘图源码](plot_layerwise.py)、[参数](parameters.json)、[逐项数据](layerwise-times.csv)、[检查记录](REVIEW.json)。
- 复现：`python3 plot_layerwise.py`。只执行 CPU 上的公式计算与绘图。
