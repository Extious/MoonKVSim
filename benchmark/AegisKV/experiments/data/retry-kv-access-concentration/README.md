# 历史 KV 的访问频率是否集中？

本分析回答：每层少量 KV 块是否承担了一个窗口内的大部分逻辑访问？复用已完成的原生稀疏模型轨迹，不运行新的 GPU forward，不注入故障。

**观察结果：NOSA-3B 的频次集中度很高，MiniCPM4-8B 居中，Seer 在“同一个 Query 合并所有 head”之后集中度较弱。** 需求集合很大与访问频次集中可以同时成立。这里按同一窗口的实际频率事后排序，只检验热点是否存在，不代表可以提前准确预测这些热点。

## 图像

![访问频率集中度](../../../exports/retry-kv-access-concentration/access-concentration.png)

主图上排先在每个 Query 内合并所有 head/group 对同一物理块的需求，下排保留原生选择器的每次 head/group 选择。左列为 256 Query，右列为 512 Query。

- 横轴：每层按频率降序排列的历史 KV 块累计占比，分母为该层全部 512 个历史块，包括窗口内未访问的块。
- 纵轴：这些块承担的累计逻辑访问/选择次数占比。
- 曲线越靠近左上方，访问越集中；灰色对角线是每个块频次完全相同的参照。
- 每层分别排序、使用相同 K，先计算各层比率，再对层等权平均，最后对三个文档取平均。
- 阴影表示文档均值的 min/max，不是置信区间。曲线包含所有整数 K 的真实累计值，未平滑。

[主图 PDF](../../../exports/retry-kv-access-concentration/access-concentration.pdf) · [主图 SVG](../../../exports/retry-kv-access-concentration/access-concentration.svg)

![所有层的频次集中度](../../../exports/retry-kv-access-concentration/concentration-by-layer.png)

逐层图展示主口径下每个模型的所有层、两个 Query 窗口和两种配额。NOSA 的结果不只来自少数浅层。每个点平均三个复用文档，没有将层当作独立实验样本。

[逐层 PDF](../../../exports/retry-kv-access-concentration/concentration-by-layer.pdf) · [逐层 SVG](../../../exports/retry-kv-access-concentration/concentration-by-layer.svg)

## 两种计数口径

**Query—块访问（主口径，`query_block`）**：对于同一个 Query，只要某个 head/group 选择了块 b，就记该层块 b 被需要一次。多个 head 同时选择 b，仍只计一次；不同 Query 再次选择 b，则继续计数。备份对象始终是该层包含全部物理 KV heads 的完整块。

**原生选择事件（辅助口径，`selector_event`）**：NOSA/MiniCPM4 累计 query/KV-group 的选择次数；Seer 累计 query/head 的原生 mask 选择次数。同一个 Query 的多个 head 选择同一块会贡献多次。仍然对完整的层/块排序，未拆分 head 进行放置。

例如，同一个 Query 的 4 个 head 都选择块 b：主口径对 b 记 1，辅助口径记 4。如果随后另一个 Query 也需要 b，主口径再加 1。

两种口径都是由原生选择轨迹得到的逻辑计数，**都不等于 GPU HBM 实际读次数、DRAM→HBM 传输次数或注意力权重总和**。不能将不同原生 head/group 数对应的绝对事件量视为模型间相同的物理工作量。

Seer 的 native query block 为 64 Query。一个原生 mask 适用于这 64 个 Query，因此在两种口径中按 64 加权；没有将其伪装成 64 次独立的 gate 决策。该权重不改变同一窗口内的归一化累计曲线。

## 固定实验条件

| 项目 | 设置 |
|---|---|
| 历史长度 | 32768 token，512 个历史块/层 |
| 块大小 | 64 token，包含该层全部物理 KV heads |
| 模型 | NOSA-3B：32 层；MiniCPM4-8B：32 层；SeerAttention-Qwen3-8B：36 层 |
| 文档 | 三个已有 PG19 文档：10146、10321、10356 |
| 捕获次数 | 每模型/文档一次已完成的 M32768/N512 原生 forward，共 9 次；本次没有新增捕获 |
| Query 范围 | 256 窗口：32769–33024；512 窗口：32769–33280，位置从 1 开始 |
| 窗口依赖 | 256 Query 是同一次 512-Query 捕获的前半部分，非独立运行 |
| 排序 | 每层按被评估窗口自己的实际频率排序，两种指标各自排序 |
| 配额 | 每层相同 K，扫描整数 0–512，无跨层全局预算重新分配 |
| 必需块 | 集中度曲线不强制预留 sink/local 名额；它们的原生访问仍正常计数 |
| Top 10% / 20% / 40% | 实际为 52 / 103 / 205 块，即 10.1563% / 20.1172% / 40.0391% |

这里不强制预留必需块，是为了直接回答“访问频率是否集中”；不是可以直接部署的放置策略。未生成的 suffix KV 不属于历史块分母。

## 结果：所有层等权平均（%）

### 同一 Query 内合并 head/group

| 模型 | 窗口 Query 数 | Top 10% | Top 20% | Top 40% |
|---|---:|---:|---:|---:|
| NOSA-3B | 256 | 52.70 | **89.50** | 99.03 |
| NOSA-3B | 512 | 53.81 | **88.26** | 98.57 |
| MiniCPM4-8B | 256 | 36.39 | **61.95** | 89.01 |
| MiniCPM4-8B | 512 | 35.17 | **58.41** | 84.92 |
| SeerAttention-Qwen3-8B | 256 | 11.23 | **22.24** | 44.25 |
| SeerAttention-Qwen3-8B | 512 | 11.26 | **22.31** | 44.39 |

NOSA 在两个窗口下、每个文档的全部 32 层中，Top 20% 的 Query—块访问占比均超过 80%。这一结论是这些已观测文档/层的结果，不是对新工作负载的保证。

### 累计原生 head/group 选择次数

| 模型 | 窗口 Query 数 | Top 10% | Top 20% | Top 40% |
|---|---:|---:|---:|---:|
| NOSA-3B | 256 | 59.18 | **90.95** | 99.19 |
| NOSA-3B | 512 | 59.02 | **89.71** | 98.78 |
| MiniCPM4-8B | 256 | 47.24 | **69.44** | 91.39 |
| MiniCPM4-8B | 512 | 45.53 | **66.12** | 88.05 |
| SeerAttention-Qwen3-8B | 256 | 29.95 | **49.39** | 73.56 |
| SeerAttention-Qwen3-8B | 512 | 29.32 | **48.39** | 72.40 |

Seer 的两种统计差别较大：在当前配置中，多个 head 同时选择某些块，会使原生事件计数更集中；合并同一 Query 的物理层/块需求后，曲线接近对角线。不能将下排的较高数值直接用于声称完整物理块的取数需求同样集中。

## 与此前覆盖率结果的关系

此前的 `retry-kv-window-presence` 统计未来窗口需要的**不同历史块**，重复访问同一块只计一次，并使用历史窗口预测。

本图保留跨 Query 的重复访问，且使用同一窗口事后排序。**统计目标和可用信息都不同**，因此不能把本图较高的数字表述为新预测器已经提高了此前的覆盖率。

例如，少量热点块可以反复被访问，同时大量冷块各被访问一两次。频次曲线可以很集中，但完整恢复仍需要这些冷块。如果加载一次后可以保留并复用某块，多次逻辑访问并不对应多次跨层级传输。

本图可支持：这些 NOSA 轨迹存在强烈的整层块访问频次热点；MiniCPM4 的热点较弱；Seer 对计数粒度敏感。它不能单独支持：少量备份覆盖全部恢复需求、这些热点可被提前预测、Agent 工作负载泛化、恢复延迟降低或 WCT 收益。

## 来源、核对与复现

来源为 `experiments/native-sparse/20260915-nosa-3b`、`20260915`、`20260918-seer-qwen3` 下保存的原生选择器输出/原生 mask。逐文件核对源哈希、完整运行状态和层数，保留配置与 checkpoint provenance。Seer 使用已固定的实验性 Prefill gate 配置，不代表所有 Seer 或 stock dense Qwen3。

本次仅使用捕获中的未来 256/512 Query，均位于 NOSA 已独立验证的原生 mask 区间 `[32256,33280)` 内。未扩大原生验证范围，也未重跑 forward。

核对包括：

- 600 个文档/层/窗口的不同需求块数与此前数据逐项一致。
- 1200 个计数向量完整保留；Query—块计数不超过 Query 数，也不超过原生事件计数；两者正值集合一致。
- NOSA/MiniCPM4 的 head 合并结果通过独立的逐 Query 集合计数复核。
- 原有 NOSA/MiniCPM4 全局层/块集中度中的 60 个预算点精确复现。旧图使用跨层全局排序，本图每层配额相同，旧值仅作数据一致性检查，不混入当前均值。
- 0% / 100% 端点、单调性、均匀频率下界和累计总数一致。
- 保存两种聚合：图中所有层等权平均；CSV/JSON 同时保留按事件数加权的汇总。
- 实际 PDF 渲染、灰度及阅读尺寸均查看；按 7 英寸宽导出，最小文字约 10.05 pt。这是独立分析图，插入其他宽度需要重新排版检查。

文件：`protocol.json`、`counts.npz`、`layers.csv`、`documents.csv`、`curves.csv`、`summary.json`、`source-sha256.json`、`analysis-checks.json`。图像导出及审核记录在 `exports/retry-kv-access-concentration/`。未修改论文正文或原有图像。

在仓库根目录运行：

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_concentration.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_retry_kv_concentration.py
```
