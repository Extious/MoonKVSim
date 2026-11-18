# 稀疏注意力的 KV 检索、预取与分层缓存：面向 AegisKV 的文献调查

调查日期：2026-09-19。范围覆盖 2024—2026 年公开论文、作者代码/文档及本地 PDF。共整理 30 项工作：12 项已有本地 PDF，18 项在本轮扫描范围内未找到同名 PDF、通过在线一手来源研究。这里的“未找到”不表示整台机器上绝对没有下载。

本报告区分方法核对、摘要级线索和作者实验；没有新增实测，也没有修改 AegisKV 正文或实现。各项阅读深度、来源和本地文件 SHA-256 见 [SOURCES.json](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/kv-prefetch-survey-20260919/SOURCES.json)，可筛选表格见 [LITERATURE.csv](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/kv-prefetch-survey-20260919/LITERATURE.csv)。

## 1. 与当前设计最相关的结论

1. **固定的选择数量是可行的，块身份仍需滚动变化。** 例如 FreeKV 明确使用预设检索预算，ShadowKV 的作者配置使用 2048-token sparse budget。它们不能支持“历史变长必然使每步注意力选择数量按比例增加”这一判断，也不能直接决定 AegisKV 每请求每层的 Peer 驻留块数 K。反过来，固定选择预算也不意味着完整 KV、摘要、索引和所有辅助状态都不增长。[FreeKV](https://arxiv.org/html/2505.13109v5)、[ShadowKV 作者配置](https://github.com/ByteDance-Seed/ShadowKV)
2. **选择器决定访问集合，缓存管理器决定放置集合。** HiSparse 是最直接的参照：完整历史在 host，有界 GPU 缓存保存工作集，实际选择遗漏的 KV 在 attention 前补齐。活跃请求也能替换 GPU 中不再需要的块。[HiSparse §3](https://arxiv.org/html/2608.07009v1)
3. **“预取”至少有三种完全不同的提前量。** InfiniGen 提前一层预测，FreeKV 提前一个 token 推测，ECHO 在当前 indexer 尚未完全结束时提前搬运。它们提供的不是对任意未来故障时间或下一次工具返回的准确预言。[InfiniGen](https://www.usenix.org/conference/osdi24/presentation/lee)、[FreeKV](https://arxiv.org/html/2505.13109v5)、[ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)
4. **“准确率接近”与“不改变既定稀疏模型的选择”必须分开。** ECHO/HiSparse 主要改变放置与搬运；InfiniGen、FreeKV、SpeCache 等涉及稀疏/预测近似；SparDA 训练新的预测选择模块。这些路线不能放在同一个“lossless”标签下。
5. **AegisKV 最需要补足的是恢复阶段证据。** 大多数论文的收益来自稳定 decode 或更高并发，而 AegisKV 需要证明故障后重放多个 token 时，提前驻留的前 L 层副本能减少暴露等待，并最终改善工作流完成时间。这是本报告对文献适用范围的推断，不是这些论文已经验证的结果。

## 2. 文献地图：哪些是真正的预取，哪些是邻近工作

| 类别 | 代表工作 | 解决的问题 | 不能直接据此声称 |
|---|---|---|---|
| 当前 query 的稀疏检索 | Quest、InfLLM、PQCache、ClusterKV | 从完整历史找出本次重要 KV | 已经知道未来 query 的需求 |
| 可召回缓存及检索执行 | ArkVale、ShadowKV、RetrievalAttention、RetroInfer | 保存完整信息源，缩小 GPU 活跃工作集，降低检索/搬运代价 | 所有方案都将选中 KV 搬回 GPU |
| 跨层或跨 token 推测 | InfiniGen、FreeKV、SpeCache、OasisKV、ScoutAttention | 在真正消费前产生可用的预测信号 | 预测本身精确，或足以覆盖故障重放 |
| 原生模型与精确放置 | ECHO、HiSparse；模型协同路线 NOSA、SparDA | 利用原生稀疏索引或训练局部性改善 offload | 所有原生模型有相同索引共享/预测能力 |
| 缓存、分页和容量管理 | FlexiCache、OPKV、SparseServe、KVDrive | 刷新频率、淘汰、碎片、batch 与多层存储 | 命中率提升必然改善延迟 |
| 已知前缀/状态恢复及传输 | CachedAttention、HCache、Tutti、DirectKV | 按层恢复、重算与读取重叠、SSD 或零拷贝执行 | 等价于稀疏 query 的未来访问预测 |

H2O、SnapKV、StreamingLLM 等永久丢弃/压缩路线也相关，但本轮不把它们作为“完整历史可召回的预取系统”核心基线。InfLLM 与 InfLLM-V2 也必须分开：前者的检索式长上下文推理不能直接作为后者原生稀疏选择器的实现说明。

## 3. 最值得优先读的工作

### ECHO：与原生稀疏恢复流水线最接近

**本地已有；OSDI 2026。** Decode 利用历史阈值估计，随着当前 query 的 indexer 分数产生就开始取回候选 KV；prefill 则让一个 query 批次的取回与后续批次的评分重叠。最终实际选择仍决定 attention 输入。预取上限可随上下文改变，不能将其与最终 top-k 数量混用。

最关键的限制是 §6.4.3：prefill 预取微基准最多约 1.1× 改善，没有对应的独立端到端吞吐消融。故障重放应单独建模和验证。[论文及附件入口](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)

### HiSparse：固定缓存容量，以及活跃请求中的替换

**本轮在线；2026 年预印本与 SGLang 文档。** 每请求每层配置固定 GPU 缓存，完整历史留在 host；实际 selected set 必须齐备，非当前选中项可以淘汰。缓存容量与 top-k 分开配置。

精确跨层预取依赖模型共享 indexer 结果。普通的“上一层选块预测下一层”在论文中没有可测端到端收益，原因包括预测项已被缓存、剩余 miss 难预测。当前主要是 decode 路线，不是已验证的故障 retry-prefill 支持。[论文 §3、§4.6](https://arxiv.org/html/2608.07009v1)、[SGLang 官方指南](https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/hisparse_guide.mdx)

### SolidAttention：SSD 上的推测预取与实际需求纠错

**本地已有；FAST 2026。** 利用上一 decode 步同层选块及必需的局部块预测下一步，管理 SSD、DRAM 和 GPU 间的数据流；实际选择到来后处理遗漏，并组织乱序加载。其启示是固定工作集可以通过换入换出来追踪热点。预取不改变既定 sparse selection，不代表它采用的稀疏注意力与 dense attention 完全相同。[论文 §5](https://www.usenix.org/conference/fast26/presentation/zheng)

### FreeKV：前一 token 的检索，以及有条件纠正

**本轮在线；ICLR 2026，2025 年已有预印本。** 复用上一 token 取回的 KV，将本步检索/recall 与计算重叠；query 相似度过低时按 KV head 触发纠正。采用固定预算和 GQA 组内一致的页选择。

其纠正不是每次都核验真实 selected set。因此可以借鉴增量复制、布局与流水线，但不能把这种阈值纠正直接当成 AegisKV 保持原模型语义的证明。[论文 §3–4](https://arxiv.org/html/2505.13109v5)

### InfiniGen、SpeCache、OasisKV：不同的预测信号

- **InfiniGen，OSDI 2024：** 通过当前层输入和部分 Q/K rehearsal 提前判断下一层重要 KV；阈值选取可产生变长集合。应计入重投影、辅助 key 和筛选成本。[论文](https://www.usenix.org/conference/osdi24/presentation/lee)
- **SpeCache，ICML 2025：** GPU 保留低比特代理，CPU 保留高精度 KV，利用 speculative computation 提前取高精度子集。即使高精度热集有界，完整低比特代理仍占随历史增长的空间。[论文](https://proceedings.mlr.press/v267/jie25a.html)
- **OasisKV，2026 预印本：** 用 lookahead draft token 产生下一步取块信号，结合分页工作集和 host/remote fetch。论文中 draft 的作用是预取信号，不能直接解释为已经获得 speculative decoding 的接受收益；部分低 batch MoE 配置的 token 延迟反而更差。[论文 §3–5](https://arxiv.org/html/2608.08097v1)

### NOSA 与 SparDA：模型可以为 offload 提供更好的条件

NOSA 将 query-aware 与 query-agnostic 选择结合，以原生训练方式形成适合 CPU/GPU 分层的访问结构；它是原生稀疏基线的重要候选。[NOSA](https://arxiv.org/html/2510.13602v2)

SparDA 则训练 Forecast 模块，在当前层预测下一层选择以隐藏搬运。它改变了选择器，不能归为单纯放置优化；其 prefill 实验的 KV 已经位于 GPU，不能当成 DRAM-backed retry-prefill 的直接证据。[SparDA §3–4](https://arxiv.org/html/2606.04511v1)

### FlexiCache、OPKV、KVDrive：KV Master 管理策略的直接参考

| 工作 | 有用机制 | 对 AegisKV 的启示 |
|---|---|---|
| [FlexiCache，MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/hash/94bcb01789fccf15afe2764d8fe0f40e-Abstract-Conference.html) | 根据 head 稳定性采用不同驻留与更新频率；稳定组低频重选 | K 不必每 token 改变；块身份也可以带滞后更新。不同 head 的完整状态成本要单列 |
| [OPKV，MLSys 2026](https://proceedings.mlsys.org/paper_files/paper/2026/hash/71381211d0abef73ed1887b83c4547b1-Abstract-Conference.html) | selection 插件与 KV 对象管理分开；重聚合减少 I/O 放大；比较 FIFO/LRU/S3FIFO | 模型决定访问语义，Manager 管容量和搬运；LRU 是基线，不是普遍最优 |
| [KVDrive，2026](https://arxiv.org/abs/2605.18071) | GPU/DRAM/SSD、多层/多头 cache window、选择/取回/计算分段流水线 | 不只保存当前选中集合；可在预算内保留历史工作集降低反复搬运 |

以上三项均已有本地 PDF，已核对方法相关章节。没有在本轮运行它们的实现。

## 4. 几种容易被混为“预取”的不同执行路径

**Quest 先解决选谁，未自动解决何时传输。** 原方案在 GPU 上保留完整 KV，通过 query 与页摘要筛选访问；它适合作为 selector 基线。[Quest](https://arxiv.org/abs/2406.10774)

**ShadowKV 同时利用重建与搬运。** 低秩 key 状态留在 GPU，selected key 重建与 value recall 可以组织重叠。分析其内存时要加上随上下文增长的低秩状态，不能只算 sparse budget。[作者仓库](https://github.com/ByteDance-Seed/ShadowKV)

**RetrievalAttention 与 ScoutAttention 包含 CPU 计算。** 前者在 CPU 检索并计算 offloaded attention，再与 GPU 部分合并；后者利用估计的下一层 query 做 layer-ahead CPU 预计算。这些方案不是“把所有相关 KV 提前搬回 GPU 再算”的同一种路径。[RetrievalAttention](https://arxiv.org/html/2409.10516)、[ScoutAttention](https://arxiv.org/abs/2603.27138)

**CachedAttention/HCache 处理已有状态恢复。** 前者的共享前缀身份已知，可按层预加载；后者使用中间状态与重生成，在读取和计算之间分配工作。它们比下一-token 预测更接近恢复调度问题，但不替 AegisKV 决定故障前热集。[CachedAttention](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost)、[HCache](https://doi.org/10.1145/3689031.3696072)

**DirectKV 说明硬件可能改变前提。** 它在 GH200 等 NVLink-C2C 环境让 GPU kernel 直接访问 CPU KV，减少 staging 需求；这一结果不能外推为 PCIe DRAM 读取同样便宜。[DirectKV](https://www.usenix.org/conference/osdi26/presentation/luo)

## 5. 对 K、L 和副本生命周期的具体解释

本节已根据用户在 2026-09-19 对 K、引用锁和降级语义的澄清修订；定义与权限规则是当前讨论中确定的设计，执行条件是相应的正确性要求，不表示论文正文或运行时已经同步实现。

### 5.1 K 专指每请求、每层在 Peer HBM 中的 KV Block 数

- **K 的定义：** 一个 Agent/请求在一个 Layer 的 Peer HBM 中保存的 KV Block 数；稳定状态下对应该请求在该层已提交的 Peer 备份集合大小。原生注意力为单个 query 选择的 top-k 数量另行命名，不复用 K。
- **热集更新：** 数量相同的两个热集可以包含不同块；KV Master 决定需要驻留的块身份。正在换入但尚未提交的对象不能作为已就绪备份，正在换出的对象在释放前仍占物理空间。
- **总容量计账：** Peer 池还需计入在途预留、迁移临时空间和必要辅助状态；跨请求共享的物理副本只计一次。按请求统计的 K 不应直接作为这些额外开销的替代。

还必须注明 token、逻辑块、物理页以及 head/group 的单位。例如注意力选中 2048 个离散 token，并不保证只触碰 2048/页长 个物理页；跨 query、跨 group 的需求并集也可能变大。

**K 可以是固定容量上限，但这是一项缓存策略，不是对未来需求全部覆盖的承诺。** 早期不足 K 个候选时只保存已有对象；历史增长后更新块身份。在固定 K 下，真正要观察的是 missing bytes、实际补取等待和更新流量。

### 5.2 引用锁阻止跨请求抢占，允许缩容降级与所属请求更新热集

| 触发原因 | 是否允许撤销带请求引用的 Peer 驻留 | 处理方式 |
|---|---|---|
| 其他请求申请 Peer 空间 | 不允许 | 只使用空闲和可安全回收的无引用空间；不足则拒绝新增 Peer 准入，保留 DRAM 路径 |
| Adapter 下调 Peer 总容量 | 允许 | 先回收无引用副本；仍不足时允许将带引用副本降级至 DRAM |
| 所属请求更新每层热集 | 允许调整自己的驻留集合 | 保留交集，移出旧冷块，移入新热块；在已有容量内做差量替换，扩容另行准入 |
| LLM 请求结束 | 释放该请求引用 | 共享对象保留其他请求引用；无引用对象进入可回收队列 |

例如 K=4，热集从 {A,B,C,D} 更新为 {C,D,E,F}：保留 C、D，将 A、B 降级至 DRAM，将 E、F 换入 Peer HBM，完成后仍是 4 块。空间紧张时先安全换出再换入；复制重叠使用的临时空间必须预留，不能默认存在额外容量。Adapter 缩容后，热集更新仍受新预算约束，不能立即回填被收回的额度。

这里“驱逐”是降级存储，而不是丢弃逻辑 KV：若同版本、可用于恢复的 DRAM 副本已提交，直接复用它；否则先完成 HBM→DRAM 回写，再撤销 Peer 映射并释放物理空间。请求仍拥有其 KV，目录应反映当前存储位置。若 DRAM 空间或复制条件暂不满足，降级不能提前算作完成。

请求级驻留保护与正在读写缓冲区的执行保护必须分开。Adapter 可以覆盖前者，但物理释放必须等已发起的读写结束，并阻止新消费者取得即将释放的旧地址。热集更新只释放所属请求的引用；若旧块仍被其他请求引用，不能借此绕过跨请求保护释放共享物理副本。容量缩减因此可能需要迁移时间，已移出热集但尚未释放的字节仍计账。

这条已澄清的规则取代此前“所有旧 Peer 块都只能等请求结束才回收”的讨论假设。当前论文文件中的旧限制仍需在专门同步正文时修订；本次只修正调研报告，没有将新规则宣称为已实现功能。

### 5.3 L 与运行时预取距离不是同一个参数

文献中的“提前一层预取”，通常指正常执行时已计算出部分 query/索引后，在相邻层计算期间搬运。AegisKV 的 L 则表示故障发生前已经放到接管 DP 的层范围。

前者主要决定传输能与多少现有计算重叠；后者还承担故障开始时没有足够计算可供重叠的启动成本。不能把某论文的 prefetch distance 直接赋值给 L。

对于已备份前缀 M 与待重放尾部 N，不同 query 的历史访问集合可能不同。N 增大既增加可隐藏传输的计算，也可能增加需求并集、索引成本与链路竞争。因此 L 的收益没有由 N 或 Z 单独决定的普遍单调关系。

当前已确定的职责划分仍可保留：Z 是固定系统配置；Adapter 按窗口给出 Peer 容量；KV Master 按请求画像选择 L、保护集合与准入。文献支持这些控制量分开，但没有给出适用于所有请求的现成最优公式。

### 5.4 应预测“缓存之外的未来需求”

假设预测命中 90%，但这 90% 本来就在 Peer HBM，那么预取对关键路径可能没有帮助。应进一步记录：

- 实际 miss 中有多少提前到达；
- 预测取回但未使用的字节；
- 多余预取是否挤占按需补取或正常推理带宽；
- 队列、搬运和计算共同作用后剩余的暴露等待。

HiSparse 的跨层推测负结果与 ECHO 的 prefill 微基准提醒我们：集合相似度是预测特征，不是恢复收益本身。上述指标是面向 AegisKV 的评估建议。

## 6. 对论文定位和下一步证据的建议

**可以借鉴的成熟部件：** 有界热缓存、完整慢层 backing、选块与放置分离、实际 miss 补取、异步复制、分页/对象映射、活跃工作集替换，以及按层流水线。

**尚需 AegisKV 自己证明的部分：** 固定接管 DP 下的故障前副本放置；checkpoint 落后产生的重放尾部；多 Agent 按 Slack 争抢 Peer 预算；正常服务压力下的预算调整；这些机制如何共同改善故障后的 workflow completion time。仅凭“热 KV 放 HBM、冷 KV 放 DRAM”不足以形成充分的差异化论证。本轮调查不是穷尽性的新颖性认证。

暂不实测的前提下，可以先形成以下分析/模拟对照，所有图明确标注 simulated：

| 比较维度 | 建议控制与对照 | 要回答的问题 |
|---|---|---|
| 固定 K 与固定比例 | 固定相同 Peer 字节预算、同一条真实或明确标注合成的访问轨迹 | 历史增长时缺失和更新流量如何变化 |
| 无缓存 / 有界缓存 / 缓存加预取 | 使用同一 selector 和正确性契约，单列 oracle | 收益来自缓存还是提前搬运 |
| decode 与 N-token replay | 分别统计逐 query 需求、跨 query 并集、auxiliary state | 正常推理规律能否迁移到重放 |
| L 的边际收益 | 固定 M,N,K、带宽及并发，再逐一变化这些条件 | 增加一层保护减少多少暴露等待、花费多少字节 |
| 旧的请求结束才回收 / 当前允许热集替换和缩容降级 | 相同总容量，保留提交与 in-flight 安全限制，计入回写成本 | 新规则减少多少旧块累积，增加多少迁移开销 |
| 多请求压力 | 同一接管 DP、明确共享 H2D/复制资源与 foreground 负载 | 更高命中率是否仍改善 WCT |

建议先精读 ECHO、HiSparse、SolidAttention 和 FreeKV；再用 NOSA/SparDA 明确原生模型边界，用 OPKV/FlexiCache/KVDrive 设计管理接口。比较实验应分别列出“保持同一稀疏模型语义”的系统基线和“更换选择器/引入近似”的替代路线。

## 7. 完整目录与阅读深度

“方法章节”指核对与本问题相关的算法/系统章节，不表示逐页审稿或运行作者代码。“摘要/仓库”只作为扩展线索；详细机制未确认时在 CSV 中明确标注。会议版本与预印本版本不混用性能数字。

| 工作 | 年份 / 版本 | 本地 PDF | 核对层级 | 一手来源 |
|---|---|---|---|---|
| ECHO | 2026 / OSDI | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/ECHO: Efficient KV Cache Offloading with Lossless Prefetching for Serving Native Sparse Attention LLMs.pdf>) | 本地方法章节 | [原文](https://www.usenix.org/conference/osdi26/presentation/liu-guangda) |
| HiSparse | 2026 / arXiv v1; SGLang integration | 本轮范围内未找到 | 在线方法章节与官方文档 | [原文](https://arxiv.org/html/2608.07009v1) |
| NOSA | 2025 / arXiv v2 | 本轮范围内未找到 | 在线方法章节 | [原文](https://arxiv.org/html/2510.13602v2) |
| SparDA | 2026 / arXiv v1 | 本轮范围内未找到 | 在线方法章节 | [原文](https://arxiv.org/html/2606.04511v1) |
| SolidAttention | 2026 / FAST | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/SolidAttention: Low-Latency SSD-based Serving on Memory-Constrained PCs.pdf>) | 本地方法章节 | [原文](https://www.usenix.org/conference/fast26/presentation/zheng) |
| InfiniGen | 2024 / OSDI | 本轮范围内未找到 | 在线论文方法章节 | [原文](https://www.usenix.org/conference/osdi24/presentation/lee) |
| FreeKV | 2025 first preprint / ICLR 2026 | 本轮范围内未找到 | 在线方法章节 | [原文](https://arxiv.org/html/2505.13109v5) |
| SpeCache | 2025 / ICML | 本轮范围内未找到 | 在线论文方法章节 | [原文](https://proceedings.mlr.press/v267/jie25a.html) |
| OasisKV | 2026 / arXiv v1 | 本轮范围内未找到 | 在线方法章节 | [原文](https://arxiv.org/html/2608.08097v1) |
| ScoutAttention | 2026 / arXiv v1 | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/ScoutAttention: Efficient KV Cache Offloading via Layer-Ahead CPU Pre-computation for LLM Inference.pdf>) | 本地方法章节 | [原文](https://arxiv.org/abs/2603.27138) |
| Quest | 2024 / ICML | 本轮范围内未找到 | 论文与作者仓库 | [原文](https://arxiv.org/abs/2406.10774) |
| ArkVale | 2024 / NeurIPS | 本轮范围内未找到 | 作者仓库 | [原文](https://github.com/pku-liang/ArkVale) |
| InfLLM | 2024 / NeurIPS | 本轮范围内未找到 | 论文与作者仓库 | [原文](https://arxiv.org/abs/2402.04617) |
| ShadowKV | 2024 first preprint / ICML 2025 | 本轮范围内未找到 | 摘要与作者仓库 | [原文](https://arxiv.org/abs/2410.21465) |
| PQCache | 2024 first preprint / arXiv | 本轮范围内未找到 | 摘要与定向检索 | [原文](https://arxiv.org/html/2407.12820) |
| RetrievalAttention | 2024 first preprint / ICLR 2025 | 本轮范围内未找到 | 在线方法章节 | [原文](https://arxiv.org/html/2409.10516) |
| RetroInfer | 2025 first preprint; local 2026 PDF | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/RetroInfer: A Vector Storage Engine for Scalable Long-Context LLM Inference.pdf>) | 本地方法章节与在线摘要 | [原文](https://arxiv.org/abs/2505.02922) |
| ClusterKV | 2024 / arXiv | 本轮范围内未找到 | 摘要 | [原文](https://arxiv.org/abs/2412.03213) |
| TokenButler | 2025 / arXiv | 本轮范围内未找到 | 摘要与作者仓库 | [原文](https://arxiv.org/abs/2503.07518) |
| LServe | 2025 / arXiv | 本轮范围内未找到 | 摘要 | [原文](https://arxiv.org/abs/2502.14866) |
| FlexiCache | 2026 / MLSys | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/FlexiCache: Leveraging Temporal Stability of Attention Heads for Efficient KV Cache Management.pdf>) | 本地方法章节 | [原文](https://proceedings.mlsys.org/paper_files/paper/2026/hash/94bcb01789fccf15afe2764d8fe0f40e-Abstract-Conference.html) |
| OPKV | 2026 / MLSys | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/OPKV: A High-Throughput Plugin-Driven Framework for Recallable Sparsity in Paged KV Cache Systems.pdf>) | 本地方法章节 | [原文](https://proceedings.mlsys.org/paper_files/paper/2026/hash/71381211d0abef73ed1887b83c4547b1-Abstract-Conference.html) |
| SparseServe | 2025 / arXiv | 本轮范围内未找到 | 摘要 | [原文](https://arxiv.org/abs/2509.24626) |
| KVDrive | 2026 / arXiv v1 | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/KVDrive: A Holistic Multi-Tier KV Cache Management System for Long-Context LLM Inference.pdf>) | 本地方法章节 | [原文](https://arxiv.org/abs/2605.18071) |
| CachedAttention | 2024 / USENIX ATC | 本轮范围内未找到 | 在线论文方法章节 | [原文](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost) |
| HCache | 2025 / EuroSys | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2025/Fast State Restoration in LLM Serving with HCache.pdf>) | 本地方法章节 | [原文](https://doi.org/10.1145/3689031.3696072) |
| Tutti | 2026 / arXiv v1 | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving.pdf>) | 本地摘要与设计定位 | [原文](https://arxiv.org/abs/2605.03375) |
| DirectKV (No Buffer, No Bottleneck) | 2026 / OSDI | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/No Buffer, No Bottleneck: Efficient Zero-Copy KV Cache Offloading for Long-Context LLMs.pdf>) | 本地摘要与引言 | [原文](https://www.usenix.org/conference/osdi26/presentation/luo) |
| Predictive Multi-Tier Memory Management | 2026 / arXiv v2 | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Predictive Multi-Tier Memory Management for KV Cache in Large-Scale GPU Inference.pdf>) | 本地摘要与证据边界 | [原文](https://arxiv.org/abs/2604.26968) |
| CacheTune (Adaptive KV Cache Reuse) | 2026 / arXiv v1 | [已有](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Adaptive KV Cache Reuse for Fast Long-Context LLM Serving.pdf>) | 本地摘要与范围定位 | [原文](https://arxiv.org/abs/2605.24022) |


## 8. 来源与复核边界

- 本地扫描包括 MoonKVSim 的 related_works、Downloads、sglsim 和 rcllm 的目标文件名搜索；它不是全磁盘内容索引。已有论文没有重复下载或改动。
- 在线证据限论文、会议网站、作者代码和官方引擎文档。新找到的在线工作已保存链接，本轮没有新增 PDF 下载；一次 arXiv PDF 请求因环境代理 DNS 失败，不影响在线原文核对。
- SOURCES.json 记录每项的局限、阶段和阅读深度；LOCAL_PDFS.json 保存原路径、页数与哈希，避免把相似标题或旧版本当成同一个文件。
- 当前 SGLang 文档与本地某个旧 checkout 可能不同。本报告对官方文档的观察日期为 2026-09-19，不宣称工作区已经实现文档中的功能。
- 不直接横向比较论文首页的最大倍数：模型、稀疏预算、硬件、batch、上下文和指标不同。吞吐提高也不等于固定 batch 下单请求恢复更快。
- 第 5 节的 K 定义和引用锁权限以用户最新澄清为准；其余 AegisKV 实验建议属于基于文献的设计推断。设计效果仍需绑定具体模型、原生选择轨迹、故障提交前沿和运行时实现验证。
