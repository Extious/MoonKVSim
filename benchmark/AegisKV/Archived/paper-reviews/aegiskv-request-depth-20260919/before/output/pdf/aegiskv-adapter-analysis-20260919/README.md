# Adapter 分析图与合成队列模拟

日期：2026-09-19。用户要求先画分析/模拟图，不新增实测。本组图由可复算的解析模型和 CPU 上的离散事件队列生成，**没有 GPU 作业、模型推理或实测时延输入**。这是 Algorithm 3 的控制依据候选，尚未替换正文 Figure 5，也不是完整 Algorithm 3 的端到端评估。

当前修订：[三面板候选与 Peer/DRAM 趋势解释](COMPACT_README.md)。用户要求旧 (b)/(c) 只保留一幅，已保留总恢复时延，原始数值不变。下文保留原四面板编号及完整模型说明用于追溯。

![当前三面板分析图](adapter-analysis-compact.png)

## 原四面板说明（旧 c 对应当前 b，旧 d 对应当前 c）

- **(a) 故障风险与 checkpoint 间隔。** 在固定 L=0 下，同时计算正常 checkpoint 的固定开销和风险加权恢复代价。故障间隔越短表示风险越高；标记是扫描集合中代价最低的 Z。横纵轴均为对数轴。三种假设 MTBF 为 24、6、1 小时，较优 Z 分别为 1536、768、384 token。这些风险档与成本是假设场景，不是生产故障统计或部署建议。
- **(b) Z 与 Peer 层数的平均收益。** 每条线枚举该 checkpoint 周期内所有可能尾长，计算相对同 Z、同恢复调度、L=0 的等待减少量，再取均值。随着 Z 增大，较长的尾部计算隐藏更多预取，所以 Peer 能消除的平均等待变少。
- **(c) 恢复总时延。** 与 (b) 使用完全相同的数据，同时包含重放计算和剩余等待。较大的 Z 虽然降低了 Peer 的额外价值，仍可能显著增加恢复总时间；不能由 (b) 推断“大 Z 恢复更快”。
- **(d) 实际 Peer 占用与前台排队。** 合成请求在可用 KV 槽位不足时排队。低负载下增加 Peer 占用几乎没有影响；高负载下接近容量边界时，排队使 P95 上升。此图隔离内存准入竞争，未模拟真实 GPU 算力竞争或复制干扰。

## 解析恢复模型

所有数值均为本图声明的假设。只沿用现有 Figure 5 的“逐层预取、按需补取优先”的调度语义，没有沿用其校准时延或稀疏命中率。

| 项目 | 本图设定 |
|---|---|
| 模型规模 | 32 个同质层；不标为任何真实模型的执行结果 |
| 已提交历史 | 32768 token，每 token 每层 1024 字节 KV，即每层 32 MiB |
| 物理块 | 64 token，每层 512 块，每块 64 KiB |
| 热集 | 每层固定 205 块，h=205/512≈40.04%；含强制块 |
| 按需未命中 | 每层另有 51 块；与热集不重叠，当前层开始时才揭示 |
| 有效 H2D 带宽 | 假设 6.25 GB/s，十进制 GB |
| 每层计算 | 0.5 + 0.006×(N+1) ms；含一次恢复后的 decode |
| checkpoint 阶段 | N=0,…,Z−1，等权枚举；主图假设零提交滞后、稳定生成速率 |
| Peer 初始驻留 | 前 L 层的热集全部已提交、可用；容量充足，没有淘汰和共享竞争 |
| 计时终点 | 已知尾部 KV 重建后，完成一次恢复后的 decode |

N=0 时仍需完成下一次 decode，因此仍可能加载历史 KV。这一终点与旧 Figure 5 的“已知尾部 KV 重建完成”不同，不能直接对比两图的绝对毫秒值。

热集固定不意味着真实稀疏需求并集固定。本模型额外假定每个尾长都产生相同的热集和未命中字节数，目的是隔离计算与传输的重叠；这不是从原生注意力轨迹测得的结论。真实需求随 N 增长、不同层计算不均匀等情况仍需单独研究。选择器和辅助状态的计算/传输成本在本简化模型中设为零。

恢复时，仅有一条串行 H2D 流。热块在计算空隙连续预取；当前层的新未命中先传输，再补足当前层热块，然后计算该层。L 只改变初始驻留，不引入整批屏障，也不改变预取深度。尚未用到的冷块不计入当前恢复终点。

每层热集传输需要 2.1495808 ms；每层按需补取需要 0.53477376 ms。即使所有热集都驻留，32 层仍存在 17.11276032 ms 的按需等待下限。

本图用闭式计算生成完整曲线，并用另一个逐层事件调度器逐点核对代表状态。每种 Z、每个 L 对相同阶段配对：先求各阶段的 L=0 与 L 的差，再平均；不是先选一个平均 N 代入非线性模型。

| Z | 平均 N | L=0 总恢复时延 | L=32 总恢复时延 | 最大平均等待收益 |
|---:|---:|---:|---:|---:|
| 64 | 31.5 | 86.59 ms | 39.35 ms | 47.24 ms |
| 256 | 127.5 | 87.17 ms | 57.78 ms | 29.39 ms |
| 1024 | 511.5 | 140.50 ms | 131.51 ms | 8.99 ms |

**保留的限制性结果：三个 Z 的严格饱和位置都是 L=25。** 原因是三个周期都包含 N=0 附近的短尾；大 Z 只降低这些阶段的权重，并没有排除它们。因此，“大 Z 的平均边际收益变小”有本图支持，“大 Z 必然在更小 L 完全饱和”没有。数据另列达到最大平均收益 90% 的层数（20、17、17），仅为描述性指标，未用于选择 Algorithm 3 的 L。实际共同 L 仍应比较容量/复制代价、Slack 和真实准入覆盖。

每增加一层驻留占用 12.8125 MiB；L=32 共 410 MiB。层数图为容量充足的机制比较，不能用它直接宣称所有候选请求都会被保护。

## 风险与 checkpoint 的代价口径

(a) 使用每秒生成 50 token、每次 checkpoint 固定暴露成本 0.05 ms 的假设。该成本只代表不能隐藏的固定决策/提交部分。增量复制的逐 token 成本在本隔离模型中视为与 Z 无关，省略这个共同常数；不代表真实复制免费。提交队列、带宽争用、热集替换和迁移开销均未加入。

纵轴是“一分钟有效生成时间对应的预计额外毫秒数”，按下式计算：

    每分钟额外时间
      = 每分钟 checkpoint 次数 × 每次固定成本
      + 每分钟期望故障次数 × 该 Z 下的平均恢复时延。

两个分项都是同一有效运行时间下的毫秒数，原始 CSV 分开记录。这是低开销、稀少故障下的一阶代价近似，条件恢复为单次源故障；不模拟恢复过程中再次故障，也不把原始故障率直接当作请求故障概率。故障检测、接管绑定等与 Z 无关的代价省略。它不是 workflow WCT，也不是 Adapter 请求评分之和的实测值。

Z 扫描范围为 64…8192，步长 64。图上最低点仅是这组固定参数、这组离散候选中的较优值；不是全局最优或 Algorithm 3 的实际在线输出。主图零提交滞后、稳定 token 速率，阶段均匀分布是一项解析近似，不是对真实异步备份的保证。

## 合成队列的统计口径

(d) 是一个 M/D/c 内存准入模型：Poisson 请求到达、每个请求固定服务 1 秒、占用 1 GiB KV；FCFS 队列无限，所有请求最终完成。KV 池为 48 GiB，前台 headroom 为 4 GiB，实际 Peer 静态占用从 0 到 24 GiB，因此可并发的前台槽位从 44 降到 20。Peer 占用由构造保证真实存在，不把未使用预算当成占用；24 GiB 恰为 KV 池的一半。

两种到达率为 12、19 req/s。它们是合成负载设定；相对于槽位的压力范围分别为 27.3%…60% 和 43.2%…95%。单请求服务时间不随并发变化，是本隔离模型的关键简化。

- 10 个独立随机到达流，seed=0…9。每个到达流在全部 7 个容量点精确配对复用。
- 共 2×7×10=140 次合成队列运行；每次从空系统开始，先暖机 1000 个请求，再统计接着的 5000 个请求。
- 单次运行计算这 5000 个请求的 P95；图中点是 10 次运行 P95 的均值，而非混合全部请求后的 P95。
- 误差线为运行层面的 95% Student-t 均值区间，df=9。它不是单请求的覆盖区间，也不表示真实部署的不确定性。
- 统计请求全部完成后再汇总；没有删掉慢请求，没有超时、丢弃或 OOM。最大负载仍低于模型稳态容量。
- 低负载的 P95=1 秒仅表示本模型至少 95% 请求没有准入等待，不表示所有请求或真实系统零开销。

实际 Peer=24 GiB 时，高负载 P95 均值约 2.248 秒，95% 区间约 [1.891,2.605] 秒；低负载为 1 秒。这个模型展示“保留更多前台 KV 空间可降低内存排队”的机制，未验证 B 的预测精度、引用释放速度或整个在线控制器的效果。

## 可用于论文的英文图注

Analytical and simulated motivation for windowed protection control. (a) Expected checkpoint and recovery cost under three assumed mean times between failures; markers identify the best interval in a block-aligned scan. Both axes are logarithmic. (b) Mean recovery-wait reduction from initially storing the hot sets of the first L layers, relative to the same-Z, zero-Peer baseline. (c) Total recovery latency for the same states, including tail computation and one resumed decode. The homogeneous 32-layer model uses 32K committed tokens, 205 hot and 51 demand-miss blocks per layer, 64-token blocks, an assumed 6.25 GB/s transfer rate, and assumed per-layer compute cost 0.5+0.006(N+1) ms. Phases N=0,...,Z-1 are enumerated with equal weights under zero commit lag. (d) Synthetic FCFS memory-admission queues with a 48 GiB KV pool, 4 GiB headroom, and 1 GiB/one-second requests. Points average run-level P95s over ten independent arrival streams; error bars are 95% confidence intervals across streams. All costs and traffic parameters are assumptions; no GPU execution or end-to-end controller measurement is represented.

## 文件和复现

- [主图 PDF](adapter-analysis.pdf)、[可编辑 SVG](adapter-analysis.svg)、[PNG](adapter-analysis.png)。
- 分面板文件：adapter-analysis-a/b/c/d.pdf、.svg、.png。
- [配置](../../../benchmark/AegisKV/experiments/data/adapter-analysis/config.json)、[逐点数据目录](../../../benchmark/AegisKV/experiments/data/adapter-analysis/)。
- [生成代码](../../../benchmark/AegisKV/experiments/scripts/paper/render_adapter_analysis.py)。
- [清单与数值检查](MANIFEST.json)。主图宽 7 inch（177.8 mm），最小 PDF 字号 10.05 pt，未通过裁切改变插入尺寸。

在仓库根目录运行：

    python3 benchmark/AegisKV/experiments/scripts/paper/render_adapter_analysis.py

附加 sensitivity.csv 保留 25/100 GB/s 的高带宽，以及 128-token 提交滞后的结果。在 100 GB/s 下，三种 Z 都仅需 L=1 就达到最大平均收益，且收益仅约 0.134 ms；更高风险并不保证增大 L 有实际价值。带滞后时最大 N=Z−1+128，明确允许 N>Z。该敏感性仍为假设模型，没有将输出当成新实测。

## 核对范围与未覆盖内容

已用独立事件递推核对 1188 个恢复状态，包括所有 L、代表 N 和四种带宽；核对逐层就绪时间随初始驻留增加不会变晚、复制字节守恒以及队列的手算例子。还检查同一到达流减少 KV 槽位不会降低逐请求时延，140 次队列运行均保留全部统计请求。

已实际查看最终主图 PNG、PDF 渲染与灰度版本，并检查分面板导出。修正了线性纵轴压缩低风险曲线最低点、底部说明过近，以及队列重合曲线的 marker 遮挡。没有修改任何数值来适应版式。

本组图支持选择 Z/L/B 的条件性理由。它没有实现或验证 Adapter 的风险估计、窗口切换、Master 的竞争准入、Slack 排序、引用淘汰、备份提交竞争或恢复正确性；图中的一个服务秒也不规定控制窗口必须多长。
