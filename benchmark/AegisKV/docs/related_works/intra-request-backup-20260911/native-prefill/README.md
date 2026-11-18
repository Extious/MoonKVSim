# 原生稀疏注意力如何执行 prefill

核对日期：2026-09-11。范围：NSA、DSA、InfLLM-V2，以及 NOSA 的两种 prefill 模式。这里解释机制，不声称穷尽现有模型。

三张图均为结构示意，掩码和块选择是构造例子，不是模型 trace、模拟结果或硬件测量。PNG 的预定阅读宽度为 1100 px；没有指定论文栏宽，也未进行论文排版检查。

## 1. 稀疏的是 attention 连接

![Sparse prefill 总览](01-prefill-overview.drawio.png)

冷启动 prefill 的输入 token 已知。在一层内，各位置从上一层隐藏状态生成 Q、K、V 或模型对应的潜在表示。启用稀疏路径后，每个 query 按模型规则选择部分因果可见的位置或块，主 attention 只计算这些连接；每个新输入位置仍需得到本层输出并经过 FFN。稀疏 attention 不等于只为少数输入计算 KV。

图中蓝色是计算连接，白色是因果允许但未选中的位置，灰色是未来位置。图中的历史块长为 3，局部区域含最近 3 个位置；有历史完整块时再选择一个。它只帮助理解稀疏因果矩阵，不代表任何论文的实际参数或选择结果。构造矩阵保存在 [EXAMPLES.json](EXAMPLES.json)。

prefill 可以并行处理 query 行或行块，不需要像 decode 一样先采样出下一个 token 才继续。这里的“并行”指逻辑上允许并行；实际 kernel、chunked prefill、资源约束和层间数据依赖仍影响调度。NSA 还利用同一 GQA 组的 query heads 共享所选 KV 块来组织计算。依据：[NSA §3.4](https://arxiv.org/html/2502.11089v1#S3.SS4)。

## 2. 选择机制不只有一种

![NSA 三分支](02-nsa-branches.drawio.png)

NSA 的压缩分支通过学习式压缩获得块摘要，再用 query 对摘要做 attention；相关分数指导另一个分支选择原始精度 KV 块。局部分支负责最近窗口。三个分支使用独立的 K/V，并将 attention 输出按学习式门控合并。压缩摘要的可见范围也必须满足因果约束。图为数据依赖图，三条路径并非没有依赖的三个同时完成阶段。依据：[NSA §3.3](https://arxiv.org/html/2502.11089v1#S3.SS3)。

| 方法 | 主 attention 之前的选择 | 得到输出的方式 |
|---|---|---|
| NSA | 压缩分支的注意力分数用于选块 | 压缩、选择、窗口三分支门控合并 |
| DSA（DeepSeek-V3.2） | Lightning Indexer 为每个 query 对历史位置打分，选 Top-k | 在所选位置上做主 attention，具体模型使用 MLA |
| InfLLM-V2 | 使用池化键表示产生块分数，选 Top-k 历史块 | 合并初始块、局部块和动态选中块后做一次 sparse attention |

DSA 的 indexer 使用较少的头、可采用 FP8；主 attention 读取所选 KV entries。它的 indexer key 状态与主 MLA KV 状态是不同对象。依据：[DeepSeek-V3.2 §2.1](https://arxiv.org/html/2512.02556#S2.SS1)。

InfLLM-V2 移除了压缩分支对最终输出的直接贡献，将压缩分数只用于选块，并允许 dense/sparse 切换。不能把 NSA 三分支图直接当作 InfLLM-V2 的结构。依据：[InfLLM-V2 §3.2–3.4](https://arxiv.org/html/2509.24663)。

“原生稀疏”也不能独自确定部署时的 prefill 路径：NOSA 的论文区分了 dense prefill + sparse decode 的 NOSA-F，以及两阶段都 sparse 的 NOSA-S。依据：[NOSA 表 2](https://arxiv.org/html/2510.13602v2)。

**复杂度的推导边界：**对于 DSA 的逐 query、逐历史位置 indexer，N 个输入的打分对数量仍随 N² 增长，只是单次打分比主 attention 轻；主 attention 的选中位置上限为 k 时，其连接数量约为 Nk。因此不能把“主 attention 稀疏”直接写成“整个 prefill 都是线性复杂度”。这是由算法结构得到的分析，不是本次性能测量。

## 3. 多轮 Agent 请求与恢复

![增量 prefill 的选择并集](03-prefill-working-set.drawio.png)

若本轮输入是已有前缀 P 拼接新增输入 U，并且各层的前缀 KV 及必要附加状态完整、有效，则增量 prefill 主要为 U 计算新的状态；每个新增 query 仍可能访问 P 中的历史 KV。前缀复用要求输入、位置及模型状态兼容，不能仅凭“同一个 Agent”就认定可直接复用。

图中设 P 有 8 个等大块，U 有 4 个 query；每个 query 选 2 个互不重叠的历史块。因此单个 query 的历史选择比例为 25%，这批 query 的选择并集为 100%。这只是反例，说明前一比例不能推出后一比例；它不是“所有真实 prefill 都会访问全部历史”的证据。

图只展示单层、单个 KV 组的动态历史选择。局部窗口、固定块、新增 token KV、摘要和 indexer 状态未纳入 25% 的分母；它们的计算和存储成本仍须另计。整个执行期间访问过的并集也不等于同时驻留的工作集，分页、预取和计算传输重叠可以改变 HBM 峰值需求。

对“少量 Peer HBM，其余 DRAM”的保护方案，可针对恢复窗口 W 定义：

\[
U_W = \bigcup_{(\ell,g,i)\in W} S_{\ell,g,i}.
\]

S 包含该层、KV 组和 query 实际需要的历史块；层/组身份属于块身份的一部分。若 Peer 集合为 H，那么 U_W 中不在 H 的状态仍需从 DRAM 获取或在缺失时重建，是否阻塞取决于它们的消费时刻与传输调度。NSA 的压缩输出依赖、DSA 等方法的选择器状态应单独列入依赖清单。

这提示实验应区分：冷启动 prefill、命中前缀的增量 prefill、故障后继续 decode。各场景中的并集大小、跨 query 重复访问和首次使用时间不同。prefill 热度可以成为预测特征，但不能直接当作恢复后访问分布或 decode 热度的真值。

## 可编辑文件与复现

- [总览 .drawio](01-prefill-overview.drawio)
- [NSA .drawio](02-nsa-branches.drawio)
- [增量 prefill .drawio](03-prefill-working-set.drawio)
- 同名 `.drawio.svg` 为可缩放导出；PNG/SVG 均嵌入 Draw.io XML。
- [构图脚本](build_diagrams.py)、[原生导出脚本](render_diagrams.py)、[审查记录](REVIEW.json)。

```bash
python3 benchmark/AegisKV/docs/related_works/intra-request-backup-20260911/native-prefill/build_diagrams.py
python3 benchmark/AegisKV/docs/related_works/intra-request-backup-20260911/native-prefill/render_diagrams.py
```

导出使用已安装的 Draw.io Desktop；受限环境需要允许 Xvfb 创建本地显示 socket。未修改算法代码、运行模型、下载权重或执行性能实验。
