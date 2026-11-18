# Adapter 三面板候选与 Peer/DRAM 趋势解释

2026-09-19 修订：用户希望旧 (b)/(c) 只保留一幅。本版保留总恢复时延，重新编号为 (a) 风险与 Z、(b) 恢复时延与 L、(c) Peer 占用与前台排队。直接读取上一版 CSV，未重跑模拟、未修改任何数值，也没有新增实测。

![三面板](adapter-analysis-compact.png)

[PDF](adapter-analysis-compact.pdf) · [可编辑 SVG](adapter-analysis-compact.svg) · [原始参数、统计口径与数据](README.md) · [清单](COMPACT_MANIFEST.json)

## Z 较大时 Peer 和 DRAM 更接近，为什么合理

比较发生在同一故障状态、同一有效 checkpoint 前沿、同一已提交历史 M 下。两条路径都要重放未提交的 N 个 token，并完成一次恢复后的 decode；Peer 只改变已提交热块最初位于哪里。

    DRAM 路径总时延 = 尾部计算 + DRAM 路径的暴露加载等待
    Peer 路径总时延 = 相同尾部计算 + Peer 路径的暴露加载等待
    Peer 减少的恢复时延 = 两条路径暴露等待之差

较大的 N 留出更长的逐层计算时间，后续层的可预取 KV 有更多机会在这段时间内传完。如果每层计算已经长于下一层的热块加载时间，继续增加初始驻留层数就很难减少恢复关键路径。按需揭示的未命中不因此消失。

本图固定每层热块传输时间约 2.15 ms。固定 N=512 时，每层计算为 0.5+0.006×513=3.578 ms，后续热块预取可以被隐藏。DRAM-only 恢复约 133.76 ms；前一层热块已驻留后约 131.61 ms，差约 2.15 ms。两条路径都包含约 114.50 ms 的计算和约 17.11 ms 的按需补取，Peer 不消除这些共同成本。

Z 改变的是尾长分布，不是直接给 KV 存储介质设置另一种速度。固定同一个 M、N、热集和物理驻留状态时，仅改变配置标签 Z 不会改变恢复时间；零提交滞后、稳定 token 速率的本图假设下，Z 越大，长尾故障阶段的权重越大，所以平均增益降低。

| Z | DRAM-only 平均恢复 | 前 32 层热集 Peer 驻留 | 平均减少量 | 相对减少 |
|---:|---:|---:|---:|---:|
| 64 | 86.59 ms | 39.35 ms | 47.24 ms | 54.6% |
| 256 | 87.17 ms | 57.78 ms | 29.39 ms | 33.7% |
| 1024 | 140.50 ms | 131.51 ms | 8.99 ms | 6.4% |

因此当前曲线不只是“计算时间增大稀释了收益百分比”：暴露传输减少使绝对收益也从约 47 ms 降至约 9 ms。若传输和计算完全串行，在相同 KV 字节数下，Peer 省掉的绝对传输时间不会仅因 N 增大而减少，只会使相对百分比下降。

## 对 Adapter 的含义

这支持一个条件性选择：恢复以暴露加载等待为主时，增加 Peer 层更值得；恢复主要受尾部计算限制、加载已被隐藏时，应倾向较小 L，并把容量留给其他请求或前台。Peer 仍可能消除启动等待，所以“差别很小”不等于收益严格为零；最终是否准入还要比较 Slack、复制开销和容量机会成本。

Z=1024 的两条路径更接近，但它们都比短 Z 时恢复更慢。这不能作为主动增大 Z 的理由。Z 仍需权衡正常备份开销与恢复损失。

也不能直接改写为“Z 越大则 L 必须越小”。实际提交滞后、不同请求的上下文、稀疏需求并集和热集命中率都会改变结果；前台容量不足也会让较小 L 更有价值。当前图没有运行完整 Adapter/KV Master 竞争策略。

## 本图必须保留的假设

1. 已提交历史 M 固定为 32K；205 个热块、51 个按需未命中块在各 N 下固定。真实稀疏需求并集增长未建模。
2. 每层计算成本线性增加，属于声明的假设曲线，未经目标模型校准。
3. 预取/计算可充分并发；H2D 带宽固定，无 DMA/计算争用、调度空洞或副本排队。
4. Peer 和 DRAM 使用相同提交前沿。若 Peer 备份更及时、实际能减少 N，则它还可能减少重放计算，不能使用当前图量化这种收益。
5. 比较单次恢复关键路径，不计 Peer 减少传输对其他请求/共享链路的间接影响。
6. 故障阶段等权平均，零提交滞后；不是“所有失败都在 N=Z”。三个 Z 仍有相同短尾阶段，严格饱和位置在本模型中仍都是 L=25。

## 英文图注

Analytical and simulated motivation for windowed protection control. (a) Expected extra time per minute of useful generation under three assumed mean times between failures; markers identify the best checkpoint interval in the scan, and both axes are logarithmic. (b) Mean recovery latency versus initial Peer residency depth; L=0 is the DRAM-only baseline, and L>0 stores the hot sets of the first L layers. Curves average over N=0,...,Z-1 under zero commit lag and constant token rate. Larger tails provide more compute time to overlap hot-block prefetch, reducing the incremental value of Peer residency while potentially increasing total recovery latency. The 32-layer model assumes a fixed 32K committed history, 205 hot and 51 demand-miss blocks per layer, 64-token blocks, 1024 KV bytes per token per layer, 6.25 GB/s transfer bandwidth, and 0.5+0.006(N+1) ms per-layer compute. Recovery ends after tail replay and one resumed decode. (c) Synthetic memory-admission queues with a 48 GiB KV pool, 4 GiB headroom, and 1 GiB/one-second requests; means of ten run-level P95s with 95% confidence intervals across independent arrival streams. Costs and traffic are assumed; these are mechanism illustrations, not hardware or end-to-end controller results.

## 复现与审查

在仓库根目录运行：

    python3 benchmark/AegisKV/experiments/scripts/paper/render_adapter_analysis_compact.py

代码验证已有 CSV 哈希，再绘制三面板；完整生成器和原四面板仍可追溯。新版宽 7 inch（177.8 mm）、高 3.4 inch，最小 PDF 字体约 10.05 pt。主图 PNG、PDF 渲染与灰度按最终宽度查看。图中当前 (b) 与旧 (c) 的每一个曲线点完全一致，数据单位和聚合方式不变。

