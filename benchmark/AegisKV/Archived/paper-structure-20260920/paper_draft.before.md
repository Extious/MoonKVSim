# 2. Background and Motivation

**本章主线：先说明已有缓存能提供什么，再说明故障留下什么缺口；接着说明恢复成本与工作流延迟不同，最后引出按请求和 KV 状态分配额外保护。**

正文以连贯论证为主。编号 Insights 和具体算法放在 System Design，避免在背景中提前堆叠控制公式。

## 2.1 Workflows, Existing KV Caching, and the Failure Model

**本节回答：我们服务什么应用，已有缓存与 AegisKV 分别承担什么责任？**

- 第一段介绍两类 KV 生命周期：角色前缀的跨请求共享，以及工具调用间持续增长的 Agent 历史。将请求放回工作流的依赖关系中，而不是由角色名称推断优先级。
- 第二段介绍普通缓存：HBM 执行和复用、DRAM 保存与回迁、正常准入和淘汰。承认这些功能已有研究，AegisKV 的算法输入是当前可用的副本和资源状态。
- 第三段指出故障缺口：普通缓存可能已有可用副本，但未必覆盖活跃请求最近生成的状态，也未必在要求的时间内保留，或能被存活恢复目标访问。需要逐项查询、确认和补足，不能一概断言普通缓存“没有容错作用”。
- 第四段明确当前故障模型：fail-stop GPU/worker 故障；恢复目标已经有兼容模型权重；控制平面、token 历史、备份 DRAM 和恢复目标存活。TP worker 的恢复要求完整、兼容的分片。主机整体故障、静默数据损坏和丢失模型容量的重建不属于当前承诺。
- 第五段给出文献分工：普通多智能体缓存和调度研究解决健康运行期间的复用与竞争；直接容错研究解决 checkpoint 与恢复。AegisKV 聚焦在明确故障模型下，结合工作流延迟容忍度和请求内部恢复需求分配保护。

**引用安排。** 当前正文已有 DéjàVu、GhostServe、LUMEN、Mooncake、KVFlow、TOPAS。TokenCake 与 Continuum 可用于说明普通管理的不同取舍，不作为算法必须依赖的基础系统。它们分别涉及工具感知卸载/提前回迁与空间调度、TTL 保留与程序级调度：[TokenCake v4](https://arxiv.org/html/2510.18586v4)、[Continuum v6](https://arxiv.org/html/2511.02230v6)。两篇尚未加入当前 `references.bib`；正式改写时再补充，不能将其整体系统收益当成某个独立缓存策略的收益。

**图像安排。** 本节用概念和生命周期定义建立边界，后文通过 Figure 1 说明工作流；当前没有可直接充当“正常缓存与容错接口图”的独立图片。具体接口放在 3.2，以文字/表格讲清楚。

**过渡句。** 即使能够保存 KV，也仍需判断哪些请求值得获得更强保护，因为恢复耗时并不等于最终工作流受到的延迟。

## 2.2 Recovery Cost Is Not Workflow Delay

**本节回答：为什么仅按上下文长度或重算成本排列备份优先级不够？**

**第 1 段：定义工作流延迟余量。** 定义 WCT、依赖关系和 Slack。Slack 是在给定调度下不延长工作流完成的延迟余量；工具调用时长、Agent 总时长或最长减最短分支时长都不能直接代替它。

**第 2 段：用 Figure 1(a) 展示分支时长差异。** 先介绍 trace 的选取和统计口径，再说明多个工作流的分支执行时间存在明显差异，为研究延迟容忍度提供背景。

![Figure 1(a). Workflow-maximum gaps](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/workflow-gaps.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/workflow-gaps.pdf)

**Figure 1(a) 的作用。** 支持本段“工作流存在分支时长差异”的观察。每个工作流贡献一个最大时长差，样本为 121 个工作流；这条 ECDF 不能直接读成请求或故障时刻的 Slack 分布。对应标签：`fig:motivation-branch-gap`。

**第 3 段：用 Figure 1(b) 解释差异如何影响汇合点。** 从总体统计进入一个具体四分支示例：在下游需要所有分支结果的假设下，最晚完成的分支决定汇合时间，较早完成的分支可能吸收部分延迟。

![Figure 1(b). Four-branch workflow](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/workflow.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/workflow.pdf)

**Figure 1(b) 的作用。** 帮助读者理解依赖与延迟余量，连接“时长差异”和“工作流影响”。图中位置与时长来自 trace，汇合依赖由时间信息推定；该示例不是 Figure 1(a) 中对应工作流的最大差值样本。对应标签：`fig:motivation-workflow`。

**第 4 段：用 Figure 1(c) 比较相近重建成本产生的不同 WCT 影响。** 在上述依赖假设下，分别考虑各分支上的一次故障，将恢复时间区分为被余量吸收的部分和暴露给 WCT 的部分。

![Figure 1(c). Estimated recovery exposure](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-exposure.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-exposure.pdf)

**Figure 1(c) 的作用。** 支持“只按重建成本排序可能错配保护”的论证，引出按工作流影响分配容错资源。图中是独立单分支反事实，结合 trace 时间、假设依赖和静态重建成本；不是同时发生的四个故障，也不是实际故障恢复测量。对应标签：`fig:motivation-recovery-exposure`。

**第 5 段：收束到容错决策。** Slack 用于评估追加保护；普通缓存仍可以因为跨轮复用价值保留高 Slack 请求的 KV。请求优先级解决“保护谁”，接下来还需要决定“保护到哪个层级”。

论文中 Figure 1 保留现有跨双栏三子图布局；这里分开展示，分别紧邻它支持的段落。

## 2.3 Long Contexts and the Incremental Value of Recovery Tiers

**本节回答：已有 DRAM 副本能够避免大量重算，为什么还研究 Peer HBM？**

**第 1 段：说明长上下文带来的重建成本。** 多轮推理会积累历史 KV。已有兼容缓存能够减少重建，应先计入恢复起始状态，再讨论额外保护的必要性。

**第 2 段：用 Figure 2 比较三条恢复路径。** 对同一模型配置、同一历史和已知尾部，比较无可用副本、历史在 DRAM、历史已在实际恢复目标 HBM 的情况。

![Figure 2. Static recovery estimates](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-cost.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-cost.pdf)

**Figure 2 的作用。** 支持两个不同结论：DRAM 保存历史主要减少重建计算；HBM 在此基础上主要减少传输等待。图中是静态估计，完整 HBM 驻留和先全量加载的 DRAM 路径用于展示成本差异，不代表有限 Peer 热集方案或优化后的 DRAM 基线。不同模型 GPU 数量不同，只在各自配置内比较恢复路径。对应标签：`fig:motivation-recompute`；论文保留单栏。

**第 3 段：解释 Peer 额外收益的边界。** 有副本的两条路径都需要处理尚未提交的尾部；Peer 只能进一步消除仍暴露在恢复关键路径上的等待。不能把 DRAM 已避免的全部重算成本归给 Peer HBM。

**第 4 段：引出有限容量下的选择。** Peer 副本占用正常推理需要的 HBM，并产生复制与迁移流量。不同层的需求时间和访问块不同，需要挑选能减少暴露等待的状态，而不是默认全量驻留。

**过渡句。** 保护决策应结合请求延迟容忍度、已有可恢复状态和新增保护的资源成本；请求内部的依据在 3.1、3.5 展开。

## 2.4 Problem Statement and Design Goals

建议本节以如下问题收束：

> 给定正常缓存留下的可用 KV 状态，以及有限的 HBM、DRAM 和传输资源，应为哪些请求补充哪些故障保护，才能降低故障对工作流完成时间的影响，同时控制健康请求的额外开销？

设计目标写成五项即可：

1. **复用已有状态。** 相同、兼容且可存活的副本可以承担保护；没有缺失字节时不重复复制，但新增保留承诺仍计入容量成本。
2. **按工作流影响分配。** 结合 Slack 和恢复代价，而不是只看 token 数、KV 大小或角色身份。
3. **区分恢复覆盖与加速驻留。** 有效 checkpoint 决定能从哪里恢复；Peer 热集决定减少多少等待，热集命中率本身不是恢复正确性。
4. **约束健康运行代价。** 显式限制容量和带宽，并计算缓存挤占、迁移、重算和排队变化。
5. **保持可恢复与可退让。** 拒绝新增保护不阻塞正常推理；已有承诺只能经安全迁移、替代版本提交或明确撤销后释放。

同一故障影响多个分支时，单请求的“恢复延迟减 Slack”不能直接相加为 WCT。跨请求改善也需要实际共享的链路或恢复资源；论文应将局部决策指标与最终工作流评估区分。

# 3. System Design

本章按照设计依据、系统边界、工作流信息、恢复目标、增量保护、容量控制的顺序展开。3.4、3.5、3.6 分别对应 Recovery Manager、KV Master 和 Adapter。

## 3.1 Insights and Design Implications

**本节回答：为什么有信息支持请求级与块级的保护决策？**

**第 1 段 / Insight 1：利用已有方法估计剩余工作。** 用 Figure 3(a) 说明执行上下文具有预测信息，再引出 Tracker 将经部署校准的剩余时间转换为工作流 Slack。预测方法是可采用的已有能力。

![Figure 3(a). Agent trajectory prediction](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent-prediction.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/agent-prediction.pdf)

**Figure 3(a) 的作用。** 支持使用已有 Agent 进度预测方法的设计前提，并在 3.3 再次引用。结果归属 Heddle，指标是剩余轨迹长度的 Pearson 相关性，不能写成 AegisKV 的执行时间准确率或本地 GBDT 的实验结果。对应标签：`fig:insight-agent-time`。

**第 2 段 / Insight 2：原生稀疏注意力改变恢复对象。** 用 Figure 3(b) 展示选取的模型发布实例，说明不同机制涉及不同的 token、block、压缩表示和辅助状态。KV Master 因而需要读取模型实际需求。

![Figure 3(b). Selected sparse releases](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/sparse-models.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/sparse-models.pdf)

**Figure 3(b) 的作用。** 说明为何设计需要适配多种原生稀疏机制；它是发布实例及原生上下文的整理，不能推出部署占比或所有模型具有相同块大小。对应标签：`fig:insight-sparse-adoption`。

**第 3 段 / Insight 3：过去访问能够预测部分恢复需求。** 用 Figure 3(c) 比较相同容量下按历史频率和按近期性选块的覆盖率，引出为恢复提前驻留热集，同时保留真实未命中的按需读取路径。

![Figure 3(c). Retry KV prediction](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/retry-kv-prediction.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/retry-kv-prediction.pdf)

**Figure 3(c) 的作用。** 支持 KV Master 将历史访问作为候选信号。图中是原生 PG19 选择 trace 的留出窗口，每个模型 3 个文档，胡须表示文档范围；MiniCPM4 与 Seer 的增益较弱，应保留这个限制。该图不证明 Agent 故障恢复收益，也不验证预测错误后恢复执行的正确性。对应标签：`fig:insight-retry-kv`。

三个子图共同支持机制前提。论文保留跨双栏组合，Markdown 按三个 Insight 分别插入，方便逐段检查论证。

## 3.2 System Overview and the Cache–Protection Boundary

**本节回答：哪些部件属于正常服务，哪些决策属于 AegisKV，两者如何共享状态？**

**第 1 段：用 Figure 4 建立模块分工。** 应用和正常引擎继续发起请求、执行模型、复用缓存和正常准入；Tracker、Recovery Manager、KV Master、Adapter 分别提供 Slack、绑定恢复目标、选择追加保护、控制 Peer 容量。

![Figure 4. AegisKV System Overview](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/system-overview.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/system-overview.pdf)

**Figure 4 的作用。** 作为后续 3.3–3.6 的模块导航，说明控制路径、存储位置和数据传输由谁负责。3.4 使用 Recovery Manager 与 Retry 路径，3.6 使用 Adapter、Peer KV 与 Shared DRAM 路径。论文保持等比例单栏、DP0/DP1 对称能力和现有模块编号。对应标签：`fig:system-overview`。

**第 2 段：解释共享对象与不同保留原因。** KV directory、allocator 和 Connector 是共同执行层。同一有效 DRAM 对象可以同时用于正常复用与故障保护，但应区分普通缓存保留状态、故障保护引用、正在执行的计算/I/O 引用。释放保护引用不等于删除正常缓存；任何策略都不能释放仍在使用的物理缓冲区。

**第 3 段：给出隔离接口和冲突规则。** 正常策略与容错分别提出需求，由共享分配器最终仲裁；固定策略不意味着实际命中率、空间和排队不受影响。

| 交互 | 输入与结果 | 边界与冲突处理 |
| --- | --- | --- |
| 查询状态 | 请求/逻辑块 → 副本、版本、已提交前沿、故障域和引用 | 查到副本不等于已承诺保留，执行前原子核查 |
| 申请保护 | 所需恢复状态 → 复用副本或补缺复制，加保护引用 | 有效副本不重复写；在途复制合并依赖但不提前算提交 |
| 容量仲裁 | 正常保留、Peer/DRAM 保护及淘汰申请 → 接纳或拒绝 | 物理字节去重计费，保护延长保留的成本另计；预算不足可以拒绝 |
| 生命周期通知 | checkpoint、请求结束、工具返回、预算变化、故障 | 刷新策略；完整依赖提交后才推进前沿 |

普通淘汰遇到受保护对象时，应保留或安全迁移；容错申请遇到空间不足时，不能默认无限挤占普通缓存。DRAM 可使用统一池加保护预算，不必硬切固定“缓存区/备份区”。Figure 4 已含共享目录与数据路径，但尚未画出上述引用和仲裁细节，这些责任由本段及表格明确。

**第 4 段：走一遍正常与故障生命周期。** 请求到达后先命中或计算，再作增量保护。一轮 LLM 请求结束并交接工具时，可释放当前请求的保护引用；正常策略仍可为下一轮保留历史。工具返回后使用有效副本并评估新增后缀。故障发生时，绑定目标从存活目录恢复有效前沿；跨工具等待的整个 Agent KV 保证需要额外定义保护寿命，不自动继承当前请求的引用。

## 3.3 Workflow Tracker: From Remaining Work to Slack

**本节回答：如何为容错提供请求级延迟容忍度？**

- 输入当前可观测 DAG、请求进度和部署校准的剩余时间估计。完成阶段从残余图移除；fork/join 处分段，避免把子任务执行与父任务等待重复计算。
- 保留当前 Algorithm 1 的结构：估计剩余段时长，做前向/后向传播，将段的 Slack 映射到请求，并随进度刷新。
- 一个段中的多个请求共享同一延迟余量，不能把该 Slack 当作每个请求可独立花费的预算。未知依赖或不足预测信息采用保守值；独立请求使用零 Slack。
- 正常缓存可有自己的复用价值判断；Tracker 的输出只说明保护紧迫性，不能单独决定多轮历史是否保留。

引用 Figure 3(a) 说明采用已有预测能力。算法名称可写为 “Slack estimation from remaining work”，GBDT 保留为当前可替换实现，避免将 Heddle 的文献相关性归给本地 GBDT。

## 3.4 Recovery Manager: Preassigned Takeover

**本节回答：故障之前确定到哪里恢复，故障之后如何使用存活状态？**

- **到达时绑定。** 正常 Router 选择源 DP 后，Recovery Manager 绑定另一个兼容 DP；该 DP 同时是 Peer 副本目的地与首选恢复位置。普通请求路由和故障恢复绑定分别说明。
- **存活元数据。** 请求身份、已确认 token、接受的工具输入、恢复目标、版本与 checkpoint manifest 位于源故障域之外。恢复前隔离旧执行者，避免旧 epoch 继续提交。
- **恢复时解析真实状态。** 从最新有效且依赖完整的 manifest 恢复；匹配的普通缓存副本也可以使用。Peer 位于实际目标才能直接视作本地 HBM，DRAM 需要读取，缺失部分按依赖重算。
- **按可执行条件推进。** 多个 retry 独立进入等待空间、等待数据、就绪、运行状态；按正常引擎能支持的 batch/kernel 边界推进。保护优先级不要求高优先级请求先恢复完，其他请求才能开始。
- **目标变化。** 若绑定目标失效或无法容纳必要工作集，重新绑定并核查副本位置；旧目标的 HBM 不能继续记成新目标的本地命中。

引用 Figure 4 的恢复绑定与 Retry 路径。重点保持“恢复位置与正确性”的职责，层数与块集留给 KV Master。

## 3.5 KV Master: Incremental Protection and Request-Specific Placement

**本节回答：在已有正常缓存基础上，何时追加多少保护，以及如何更新每个请求的 Peer 状态？**

### 3.5.1 先查询现状，再作保护决策

每次评估先查询兼容副本、保留状态、提交前沿和正在进行的复制。评估“不追加保护”的恢复代价时，也要利用预计在故障时仍可用的正常缓存；没有保留承诺的副本不能被当成必然存活。

| 决策 | 容错新增行为 | 对普通缓存的含义 |
| --- | --- | --- |
| 不追加保护，沿用当前 R 标签 | 不建立或续接新的保护承诺；必要时撤销本模块旧承诺 | 保留正常缓存策略的处置权；恢复时有有效副本仍可使用，缺失时才重算 |
| DRAM 保护，D | 对已有兼容 DRAM 副本添加保护引用，或只复制缺失状态；提交完整恢复前沿 | 不重复保存相同字节；延长保留时间的容量成本需计费 |
| Peer 加速，P | 在可恢复状态基础上，为该请求选择部分层与块驻留恢复目标 HBM | 这是额外的快速驻留；未放入 Peer 的必要状态仍要能获取或合法重建 |

当前正文将 R 的成本直接写成重算，并有 “For D/P, request DRAM” 的表述。正式改写应改为基于已有副本的可行恢复路径，以及“确保所需 DRAM 保护；已有则引用，缺失才复制”。Peer 与 DRAM 可并行复制，各自提交；P 的热集本身不能代表完整 checkpoint。

### 3.5.2 何时评估与复制多少

- 到达时建立策略；prefill 结束后提供已经封存的状态；decode 每新增配置的 `Z` 个 token 触发复核。Slack、副本、预算或上下文发生显著变化可以提前复核。
- `Z` 是固定系统配置，不是物理块大小。Prefill 和 decode 使用同一声明的逻辑块布局；未封存尾块按版本/封存规则处理。64 token 是当前 trace 与对象映射使用的配置，不宣称所有稀疏模型天然采用它。
- 当上下文增长使额外保护值得投入，应补齐目标恢复前沿缺失的依赖状态，已有正常 DRAM 副本可以减少新增字节。不能一律只备份最新 `Z` token，否则较早的缺口依旧存在。
- DRAM 接纳失败时保留先前有效 checkpoint；新请求可继续执行，之后从旧前沿重放更长后缀，或从输入重算。checkpoint 触发不是完成提交，复制滞后时尾部可以超过 `Z`。

### 3.5.3 每个请求自己的 L 与 K

- `L_r` 是请求 r 的目标 Peer 层深；不同请求可以不同，并在本请求的策略事件上复核。当前候选族取前若干层，是控制搜索范围的设计选择，不宣称其全局最优。
- `K_{r,l}` 是该请求第 l 层**实际已提交驻留**的块数。它与原生 selector 的 top-k、希望保存的配额、尚在传输的块数分开。
- 配额可以采用固定块数，也可以采用固定历史比例；这是需要声明和固定比较的配置。固定配额下 K 不必随历史长度一直增长，但被选中的块身份仍可能改变。
- 评估 L 时使用请求自身的提交历史、可能的未提交尾部和目标负载画像；不把未知故障尾部固定成 `Z`，也不把所有请求强制放进同一个 L。
- 预测选块仅决定驻留位置。遗漏的原生注意力输入必须按需读取；辅助索引、压缩状态、强制访问分支及数值/重放约束仍需满足。

**恢复流水说明段：用 Figure 5 解释 L 和热集的价值。** 在层深与候选热块的定义之后，比较相同历史和尾部下的四种恢复流水。先说明按层加载、热集预加载已能隐藏部分传输，再通过 (c) 与 (d) 解释已有 Peer 热集进一步消除了哪些等待。

![Figure 5. Modeled recovery pipelines](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/recovery-pipeline.png)

[原始 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/recovery-pipeline.pdf)

**Figure 5 的作用。** 支持本节“按层和块选择驻留，以减少暴露等待”的机制解释；不能将 (a) 到 (d) 的所有收益都归给 Peer。该图由测得的 forward 延迟派生层均值，并使用假设带宽；7 层、约 147 MiB 和覆盖比例属于固定案例，不是所有请求的参数或每层整数 K。它不验证 L 随上下文变化、热集迁移或多请求 WCT 收益。对应标签：`fig:design-pipeline`；论文保留单栏。

### 3.5.4 准入、替换与局部目标

新请求先使用空闲或可安全回收的 Peer 空间。其他运行请求的保护引用不能被普通竞争抢占；资源不足就拒绝该次 Peer 增量，采用可行的 DRAM/重建路径。Slack 小不意味着必然得到 HBM。

请求可以更新自己的热集：保留交集，退出旧块，只传入新增块。若退出的块仍承载恢复承诺，需要先确认 DRAM 副本，或完成提交后再退休旧地址；其他共享者的引用仍有效。旧块物理释放前不能先把空间记成空闲。

决策比较新增恢复收益与复制、迁移、缓存挤占和前台排队成本。可沿用当前按 Slack 排序的局部评估，但明确它是启发式；共享前缀字节不能重复计费，同源故障和 fork/join 的工作流收益也不能直接按请求相加。

**Algorithm 2 的建议主干。**

```text
OnProtectionEvent(request):
    查询已有副本、有效前沿、引用、目标 DP 与剩余资源
    估计不追加保护时的可行恢复路径及其工作流影响
    选择不追加保护 / DRAM 保护 / 申请 Peer 加速
    对所需恢复状态：复用有效副本，只申请缺失复制与新增保留
    为该请求生成维持现状及不同层深的候选热集
    预演自身旧块退出、新块传入、临时空间和前台成本
    在不抢占其他请求保护引用的条件下，选可接纳的稳定改进
    原子核查预算与引用，提交增量操作；失败则保留可行回退
    复制完成后发布实际驻留集合；依赖完整后才推进恢复前沿
```

## 3.6 Adapter: Windowed Peer Capacity and Safe Demotion

**本节回答：正常推理需要更多资源时，如何让容错减少 HBM 占用且不破坏仍有效的保护？**

- 每个时间窗口估计正常 KV 需求与增长余量，并发布目标 DP 的 Peer 总容量。正文不固定窗口秒数。
- 管理池先排除模型权重与固定运行时开销；Peer 上限可沿用当前池容量的一半。这里“一半”是容量比例，实际输出仍是字节数；预算包含已经驻留的 Peer 副本，不是额外可分配空间。
- Adapter 只控制容量，`Z` 仍由系统配置，`L_r` 与热块仍由 KV Master 决定。窗口内目标可以固定，但每次实际申请仍要核查物理空间。
- 收缩时首先停止超预算的新申请，回收可安全释放的无保护引用副本；若不足，允许将仍有保护引用的 Peer 副本迁移到 DRAM。系统收缩权限与请求间抢占分开。
- DRAM 已有兼容有效副本时不重复回传；没有则先申请空间、复制并提交。之后切换目录位置、关闭旧地址的新访问，等已有计算/I/O 引用排空后释放 HBM。
- 收缩不能强行删除唯一受保护副本或正在使用的缓冲区。DRAM 不足、复制失败或 I/O 尚未结束时，报告尚未完成的收缩与真实占用；必要时正常准入仍可能等待。
- DRAM 的接纳由共享分配器和保护预算管理，不再隐含为 Adapter 控制的无限后备池。迁移与需求读取有明确进展份额，避免等待所有长请求结束才能缩容。

**Algorithm 3 的建议主干。**

```text
AtWindowBoundary(target_DP):
    根据正常 KV 需求和增长余量，计算下一窗口 Peer 总预算
    将预算限制在零到管理池容量一半之间，并发布给 KV Master
    限制超预算的新申请；回收可安全释放的无保护引用副本
    如仍需收缩，按已声明的保护优先级选择 Peer → DRAM 迁移
    复用已提交 DRAM 副本，或先完成所需写回
    切换目录、排空旧物理引用，再释放 HBM
    持续报告实际占用、待释放字节和更新后的保护覆盖
```

可保留当前“较大 Slack、较深层、较低近期选择频率”的迁移排序作为明确启发式；共享对象考虑仍受保护的最紧迫拥有者。排序不形成请求级串行恢复屏障。

**本节图像的使用位置。** 开篇介绍预算发布时，回引 3.2 的 Figure 4 中 Adapter → Peer KV 的控制关系；解释降级时，回引 Peer KV、Connector 与 Shared DRAM 的数据路径。Algorithm 3 表达执行步骤。Figure 5 只支撑 3.5 的恢复流水；窗口缩容、前台代价和多请求收益仍需后续验证。
