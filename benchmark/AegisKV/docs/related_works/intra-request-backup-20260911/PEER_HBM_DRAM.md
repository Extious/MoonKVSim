**少量 Peer HBM + 其余 DRAM：请求内 KV 分层保护的论文定位**

场景修正版 · 2026-09-11

**核心修正**

用户明确的场景是：同一请求的一小部分 KV 位于 Peer HBM，其余位于 DRAM，两层共同保存完整 KV。之前将问题重点放在“只有少量总备份，其余需要重建或放弃”，偏离了这个设定。本版作为当前选题依据；[前版调研](RESEARCH.md)中的压缩、重算和编码分析保留为背景材料。

令完整历史状态为 K，Peer HBM 上的集合为 S，DRAM 至少包含 K\S。是否为 S 再保存 DRAM 副本，是另一个可靠性和空间选择，本报告不将其作为既定前提。讨论故障后这两层仍可访问的情形；未提交的异步复制、陈旧快照与两层同时失效需另行处理。

请求级 Slack 已决定保护优先级。当前要研究的是：**有限 Peer HBM 应放哪些状态，才能最大程度消除从 DRAM 恢复带来的等待？** 正确的基准是完整 KV 都从 DRAM 恢复，而不是一律从 token 重算。

由此，两个原始想法需要重新定位：

| 原想法 | 在新场景下的作用 | 判断 |
|---|---|---|
| 语义重要的 KV 优先 | 让恢复后近期实际需要的 KV 从快层获取，其他数据仍可从 DRAM 召回 | 更贴近目标，但需要按需恢复或相应执行方式 |
| 后段 KV 重建更贵 | 仅当系统会在 DRAM 加载与重算之间选择时影响价值 | 对纯 KV 搬运路径不是主要依据 |
| 新候选：首次使用时间与无法隐藏的加载延迟 | 加速最先阻塞恢复计算的状态，把其余传输藏在计算之后 | 精确 dense 恢复中值得首先验证 |

**1. 先看一个重要的负结果：全量搬完再恢复，会使很多块等价**

假设完整 KV 大小为 M，Peer 占比为 α，DRAM 和 Peer 到恢复 GPU 的有效带宽分别为 B_D、B_P，并假设 B_P>B_D。这里必须测量实际传输路径，不能用 HBM 芯片带宽替代 Peer 到目标 GPU 的链路带宽。

若执行方式要求全部 KV 到达目标 GPU 后才开始计算，串行加载的简化成本为：

$$
T_{\mathrm{serial}}=
\frac{(1-\alpha)M}{B_D}+\frac{\alpha M}{B_P}.
$$

相对于全 DRAM 的 T_D=M/B_D，节省比例为：

$$
\frac{T_D-T_{\mathrm{serial}}}{T_D}
=\alpha\left(1-\frac{B_D}{B_P}\right)\le \alpha.
$$

若两条路径完全并行：

$$
T_{\mathrm{parallel}}\approx
\max\left\{\frac{(1-\alpha)M}{B_D},\frac{\alpha M}{B_P}\right\}.
$$

在相同固定带宽假设下，剩余 DRAM 字节仍给出 T≥(1−α)M/B_D。即使 Peer 无限快，将 10% 字节移到 Peer，在这个模型中最多减少约 10% 的全量传输时间。

这不是一般系统时延的上界：排队、资源竞争、传输路径变化和计算重叠会改变结果。它给出的选题含义是：**如果所有块在恢复前都必须到齐、大小和路径成本接近，仅更换选块顺序不容易产生强烈的请求内收益差异。** 不应该先假设存在少量关键块，再用一个把所有块视为等价的执行器去验证它。

前版的 2r−r² 推导约束的是尾部备份避免的重算工作，在本场景的纯传输主路径中不适用。

**2. 语义方向：把“可以删除”改为“需要优先到达”**

现在冷 KV 仍在 DRAM，动态 attention 工作集不再意味着不可逆的信息丢失。Peer 的用途是为恢复初期的访问提供快速路径；预测失误时仍可以回到 DRAM。

但完整数据可得与计算精确性仍要区分：

| 执行合同 | DRAM 中的其余 KV 如何使用 | 精确性边界 |
|---|---|---|
| 原生稀疏模型 | 按模型原定规则选页；Peer 未命中的必需页从 DRAM 加载 | 完整执行同一稀疏模型，可保持其模型语义；需含索引器和其他分支状态 |
| 普通 dense 模型 | 每层 attention 仍使用全部所需位置；可以分块或流水加载 | 语义不因分层改变；仅用 attention 分数高的部分则会改变计算 |
| 近似 dense 续跑 | 先用 Peer 中的代表性子集，按策略从 DRAM 补充 | 需要任务质量验证；数据没有丢失也不保证已输出 token 正确 |
| 压缩草稿加完整验证 | Peer 子集用于草稿，完整 KV 在验证前可用 | 按验证规则提交输出；首次草稿时间不能当成首次可提交时间 |

这一方向的直接先行工作比纯驱逐算法更重要：

| 工作 | 与当前问题相关的机制 | 应保留的限制 |
|---|---|---|
| InfiniGen，OSDI 2024 | 将大量历史 KV 留在 CPU，用前一层的信息预测并预取少量重要条目 | 通过跳过一些 attention 项获得效率，相对原 dense 计算为近似；不是 Peer 故障备份策略 |
| Quest，ICML 2024 | 保留候选 KV，根据当前 query 和页摘要选择访问内容 | 适合研究工作集变化；本身的近似选择不能宣称 dense 输出等价 |
| ECHO，OSDI 2026 | 原生稀疏模型的 offload、recall 和无损预取 | 支撑“完整后备状态+稀疏访问”机制；尚不能证明恢复前预放在 Peer 的集合稳定 |
| VeriCache，2026 预印本 | 用压缩 cache 起草、完整 cache 验证，也讨论压缩状态先到和其余状态后台传输 | 已有非常接近的先行结构；需核算验证 GPU、全状态访问和提交等待 |

来源：InfiniGen[^1]、Quest[^2]、ECHO[^3]、VeriCache[^4]。

**新研究问题是恢复时间窗口内的工作集，而不仅是正常运行中的热门 token。** 设 A_j 为恢复后第 j 个步骤实际需要的历史 KV 集合，在允许的预取时间内，Peer 希望覆盖的是可能阻塞近期执行的部分，而非无限未来所有 A_j 的并集。冷数据有 DRAM 后备，较晚使用的内容可以提前加载；未来用途变化会表现为 miss 与等待，未必表现为不可恢复的信息丢失。

必须测两个分布：近期需要的逻辑 KV 是否集中，以及这些 KV 是否能被物理页/段有效表示。即便每步只读很少数据，步骤之间集合变化很快，也可能需要较多 Peer 空间或很高维护带宽。恢复瞬间又缺少正常缓存逐步积累的热状态，因此正常服务的 cache hit rate 不能直接代表故障恢复 hit rate。

对当前 query 已经确定的在线预取，与故障前尚不知道确切未来 query 的备份放置，也存在信息差。由故障后的完整 trace 选出的集合只能作为离线参考；在线策略应只使用当时可得的信息。

**3. 精确 dense 路线：优先研究 layer 和加载截止时间**

普通 dense attention 会读取各层的完整所需历史，但这些数据不一定必须在整个 forward 开始之前全部到齐。若恢复执行器允许按层启动，可以先恢复将被最早使用的层，同时在这些层计算期间加载之后的层。

这时，不同状态的重要性来自“何时必须到达”及“慢路径能否及时完成”。第一层的 KV 有冷启动期限，后面某层的 KV 可能有前面计算提供的预取窗口。然而不应直接固定为“越低层越好”：如果某个后续层数据量大、传输通道拥堵，或前面计算太短，它也可能成为真正的阻塞点。

LayerKV 的分层 KV 管理和传输/计算重叠，为这种粒度提供了机制先例。它研究的是正常服务内存管理与 SLO，不能将其 TTFT 改善直接解释为 Peer 备份收益。[^5]

下面的数字只是用于解释现象的理想例子，不是 GPU 实测。设 10 层，每层计算 2 ms；每层 DRAM 加载 1 ms，Peer 加载 0.1 ms；可提前预取之后各层，两条加载路径独立，且有足够缓冲：

- 全 DRAM、按层流水：首层等待 1 ms，之后的传输都能被计算隐藏，总时间约 21 ms。
- 只有首层位于 Peer：首层等待 0.1 ms，其他传输仍能隐藏，总时间约 20.1 ms。
- 所有层位于 Peer：同一流水假设下也约 20.1 ms。

在这个例子中，10% Peer 字节获得了相对全 Peer 参照的全部额外加速，却只让总时延减少约 4.3%。它说明“少量 KV 获得大部分 Peer 收益”可能成立，但不等价于“总恢复时间减少大部分”。

若每层 DRAM 加载远慢于可隐藏的计算，这种集中性也可能消失。应以分层流水的全 DRAM 方案为基线；不能将一个笨重的全量加载屏障去掉后，把收益全部归因于 Peer 选块。

**4. 后段更贵，应从核心 Motivation 降为条件性因素**

读取一个现成后段 KV 块，通常不需要重新计算它对前段的 attention。因此，同样大小、相同传输路径的前段和后段块，加载成本可以基本一致。只有系统主动选择“重算还是加载”，或者 DRAM 中有缺失、陈旧状态时，重建成本才重新进入 Peer 价值。

Cake 与 CacheFlow 已研究重算前段、加载后段的恢复方式，适合用作允许混合重算时的基线。[^6][^7] 在用户当前设定下，更直接的优先级依据是：**如果这个块仍在 DRAM，会在恢复关键路径上增加多少无法被隐藏的等待？**

这个量依赖其他已选块、通道竞争和执行计划。可以用条件边际收益表示：

$$
\Delta_b(S)=R(S)-R(S\cup\{b\}),\qquad
\rho_b(S)=\frac{\Delta_b(S)}{\mathrm{bytes}(b)},
$$

其中 R(S) 是 Peer 放置为 S 时的首个可提交输出延迟，DRAM 后备保持完整。这里是评价定义，不是已证明的 greedy 算法；块间依赖可能使收益不能相加。请求级 Slack 可以继续把这些恢复延迟映射为暴露惩罚，租金机制无需参与当前选题判断。

**5. 论文 Motivation 与创新边界**

更贴合场景的动机可以写为：

> DRAM 保存完整恢复状态，但有限传输带宽会阻塞故障后的执行。恢复过程只在特定时刻需要某些状态；一部分访问可以延迟或预取，另一部分直接阻塞计算。本文研究能否用有限 Peer HBM 保护后者，使少量高速状态获得接近全量高速恢复的收益。

对于稀疏模型，“某些状态”可能沿 token/head 维度集中；对于精确 dense 模型，差异更可能来自 layer、分块执行和预取期限。两条路径应分别验证，不能将稀疏工作集的结论直接移植到 dense 全量加载上。

“热 KV 放 HBM，冷 KV 放 DRAM”以及“压缩 KV 先到、完整 KV 后到”都已经存在密切相关工作。潜在贡献必须落实到故障恢复特有的问题：

1. 恢复初期的阻塞工作集是否与正常访问频率不同，能否在故障前低成本预测。
2. 如何按实际可复制粒度选择 Peer 状态，并使 DRAM 预取与恢复计算协同。
3. 在固定 Peer 容量、正常服务开销和正确性合同下，是否接近离线恢复放置参考。

不应预先承诺一定存在高度集中，也不应声称这个目标或公式本身已经足够新。InfiniGen/ECHO 的动态选择、LayerKV 的分层管理和 VeriCache 的渐进传输，都是需要认真比较的近邻。

**6. 最先做的实验应直接检验这个新命题**

固定请求级 Slack、总完整 KV 和故障游标；只改变 Peer 放置。先测目标拓扑下 DRAM→恢复 GPU、Peer→恢复 GPU 两条路径单独和同时运行的有效带宽，尤其检查是否共享 NIC、PCIe 或 copy engine。Peer 的存储介质更快，并不保证访问路径更快。

第一组实验保留“全部恢复后再执行”的实现，比较等预算随机、前缀、后缀和语义选择。如果结果接近，这是符合模型的有价值负结果。

第二组加入可执行的按层恢复，比较随机层、均匀分层、最早使用层和预测阻塞层；所有方法使用同样的预取能力。第三组若采用原生稀疏或近似执行，再比较访问频率、近期 query、任务无关评分和离线未来参考。精确 native sparse 与近似 dense 分开报告。

扫描 Peer 占比 0%、5%、10%、20%、40%，并使用全 Peer 的单请求性能作为参照。全 Peer 不能冒充固定容量下的公平系统基线。记录：

- 首个可提交 token 的恢复延迟，以及恢复后前若干 token 的 TPOT。
- 相同工作流和逻辑故障位置下的 WCT 增量。
- Peer 物理字节、DRAM 读取量、未命中等待和预取隐藏比例。
- 备份选择与更新开销、正常服务尾延迟，以及近似方案的功能质量。

定义相对全 Peer 参照的收益覆盖率：

$$
\eta(\alpha)=
\frac{R_{\mathrm{DRAM}}-R_{\alpha}}
{R_{\mathrm{DRAM}}-R_{\mathrm{allPeer}}},
$$

仅在分母为正、同一执行方式和正确性合同下使用，并同时报告绝对毫秒与整体相对改善。若 all-Peer 本身几乎无收益，η 即使很高也没有很强的系统意义。

**当前建议：**把主要假设从“少数 KV 更难重建”改为“少数 KV 的慢层访问支配恢复等待”。先验证 dense 分层流水能否产生有意义的差异；若采用稀疏 attention，则将 Peer 当作恢复初期工作集的快速后备，DRAM 承担冷状态召回。近似草稿与精确验证作为另一条合同明确的支线，其先行工作重合程度更高。

**来源**

本修订沿用前次核验的相关来源，并补查 InfiniGen 与 LayerKV；检索日期为 2026-09-11。上面的时延界限与数值例子是分析，不是论文或当前系统实测。没有执行新的 GPU/DES 实验。

[^1]: Wonbeom Lee, Jungi Lee, Junghwan Seo, Jaewoong Sim. **InfiniGen: Efficient Generative Inference of Large Language Models with Dynamic KV Cache Management**. OSDI 2024. [USENIX 官方论文页](https://www.usenix.org/conference/osdi24/presentation/lee)；[正文 §3.1–4.1](https://arxiv.org/html/2406.19707v1)。CPU pool 也支持内存压力管理，不能将所有配置概括为无损无限保留。
[^2]: Jiaming Tang et al. **Quest: Query-Aware Sparsity for Efficient Long-Context LLM Inference**. ICML 2024. [官方论文页](https://proceedings.mlr.press/v235/tang24l.html)；[正文 §3.4–3.5 与 §4](https://arxiv.org/html/2406.10774v1)。
[^3]: Guangda Liu et al. **ECHO: Efficient KV Cache Offloading with Lossless Prefetching for Serving Native Sparse Attention LLMs**. OSDI 2026. [官方论文页与摘要](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)。
[^4]: Jiayi Yao et al. **VeriCache: Turning Lossy KV Cache into Lossless LLM Inference**. 2026 预印本. [正文 §4.1、§4.2.2、附录 B.2 的 P2 路径](https://arxiv.org/html/2605.17613v1)。其中的分离验证依赖额外的合适 GPU 及数据路径；不能直接假定当前 Peer 已提供该执行能力。
[^5]: Yi Xiong et al. **LayerKV: Optimizing Large Language Model Serving with Layer-wise KV Cache Management**. 2024 预印本，本次未核实后续会议状态. [正文 §3.1.2–3.1.3](https://arxiv.org/html/2410.00428v3)。
[^6]: Shuowei Jin et al. **Compute or Load KV Cache? Why Not Both?**（Cake）. ICML 2025. [官方论文页](https://proceedings.mlr.press/v267/jin25d.html)。
[^7]: Sean Nian et al. **CacheFlow: Efficient LLM Serving with 3D-Parallel KV Cache Restoration**. 2026 预印本. [正文 §3.1–3.3](https://arxiv.org/html/2604.25080v1)。
