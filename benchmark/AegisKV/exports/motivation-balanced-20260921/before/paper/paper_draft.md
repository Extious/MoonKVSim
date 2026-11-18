# AegisKV：面向工作流的 DRAM／存储 KV 检查点管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。本稿对应 2026-09-20 用户确认的 **共享 DRAM＋SSD／共享存储** 方案：删除专用 Peer HBM 及其 L/K/容量控制，保留正常推理所需的 GPU HBM。Evaluation 区分理论分析、真实 trace 描述统计与 trace-driven model；它们没有证明新版系统已经实现或取得实测加速。

按 2026-09-21 最新要求，当前阶段取消 12 页压缩，以内容完整为先。Evaluation 已展开为 17 个小节、33 张单栏图；逐项实验规格、完整消融矩阵、trace 数据来源与可替换 CSV/绘图代码全部保留。图号以当前 `main.pdf` 为准。

## 1. Introduction

多 Agent 应用的用户等待的是整个任务完成，而不是某个请求单独完成。代码修改、并行检索和综合报告包含串行依赖、并行分支与汇合点；同样长的请求延迟，发生在不同分支上，对最终结果的影响可能完全不同。正常运行下的工作流调度和 prefix caching 已经利用这类信息，但故障提出了另一个问题：一个 worker 同时中断若干请求后，有限的快速恢复资源应该保护哪些上下文？

Agent 的多轮调用不断积累推理、代码和工具输出。失去 KV 后，重建长历史可能远比设备中断本身昂贵。KV checkpoint 可以避免这部分计算，但全部历史不能无限留在 DRAM。SSD 或共享存储提供更大容量，代价是读取、网络传输和排队。普通 LRU、单请求恢复速度、甚至单独的关键路径优先级，都不能完整描述这些权衡。

AegisKV 将共享缓存与故障恢复状态统一管理：**大 Slack 不禁止正常缓存；DRAM 降级与最后副本删除分别估值；同一故障域中断的请求共同经过 DAG 计算其影响。** KV Master 选择有限容量内的保留和迁移方案，引擎接口与传输路径在版本化 manifest、空间预留和 reader lease 约束下安全执行。Router 选择兼容且有执行空间的存活副本，不再要求预先绑定 Peer HBM 位置。

论文的拟议贡献包括：结合正常复用与共同故障的工作流恢复价值；区分降级和删除的在线有限容量管理；保留检查点有效性的异步迁移协议。分层缓存、KV 复制、预取和普通工作流调度均已有研究，不能作为本工作的独立新颖性主张。实验必须证明这些新增决策在强基线之上仍有收益。

## 2. Background and Motivation

### 2.1 Agent、请求、工作流与故障

一个 Agent 可以发出多轮 LLM 请求并等待工具或子 Agent；工作流由所有必须完成的输出及其依赖组成。GPU/worker 故障会同时造成 KV 不可访问和服务容量下降。本文聚焦存在兼容存活 replica、输入/token log 与控制状态可恢复、备份介质处于声明故障域之外的 fail-stop 故障。同机 SSD 不能自动覆盖整机丢失。

### 2.2 WCT 决定保护优先级

![工作流示例](figures/preview/workflow.png)

Figure 1(a) 保留真实四分支时序：A2 最晚完成，A1 虽更早结束，却可能具有较大的等待余量。A0/A5 是分叉前、汇合后的 Main 阶段示意，其节点宽度不表示执行时长；A1–A4 的条长和位置使用同一观测时间比例。这里的 join 假定需要所有分支输出，虚线表示该假定下的余量；示例不是总体分布。

![工作流最大分支差异](figures/preview/workflow-gaps.png)

Figure 1(b) 使用 393 个 CC/Weka session 中满足时间代理 fan-in 条件的 121 个工作流、286 个分支组。每个工作流贡献组内分支时长差的最大值，中位数约 138 s，P90 约 1173 s。它说明分支异质性，不是任意故障时刻的 Slack 分布；trace 中缺少显式结果消费边。

### 2.3 长上下文增加状态重建成本

![当前实测上下文恢复成本](figures/preview/recovery-cost.png)

**Figure 1(c) 支撑第二个动机。** 作业 1517208 在同一次 2×A100-PCIE-40GB 分配上完成 8K、64K、256K 和 1,010,000 的四路径实测：HBM reuse、DRAM reuse、Shared FS reuse 和稀疏 Full Prefill。1,010,000 处分别为 **1.305 s、2.663 s、10.156 s、571.21 s**。HBM 相对串行 DRAM 降低延迟 51.0%。旧三路径批次保留，当前图未拼接其他作业的数据。

**统一计算与终点。** Qwen2.5-7B-Instruct-1M，TP2、BF16、batch 1、SGLang 0.5.10rc0。所有路径共用官方 Qwen1M MInference vertical/slash 参数与 DCA；上下文超过 32K 时包括最后单 token 都使用稀疏 EXTEND。直接共享 GQA K/V；前缀每组最多两个 query heads，最后单 query 合并全部 heads。C=M+1；Full Prefill 从空 KV 按至多 8K 分块生成 M，再续算一个 token；复用路径使用该次生成的全部历史 KV。终点为模型主体完成并同步、全部 C-token KV 就绪，不含输出投影。 HBM 仅作为已驻留执行状态的参考，不重新引入 Peer-HBM 保护层。

**共享文件系统路径。** 计算节点实际挂载为 DPC，不能按登录节点的 NFS 挂载或未知底层介质标成 SSD。每个 TP rank 将真实、未压缩 KV 保存到独立文件；计时内打开并读取到 pinned host buffer，关闭文件，完成全部 H2D 后再续算一个 token。文件读取、H2D 和计算均不重叠，不做选择性加载。1.01M 的逻辑历史 KV 合计 57,917,382,656 字节，文件中另有明确记录的 64 KiB 对齐填充。写文件、fsync、备份创建、缓存清理、校验及模型加载均在计时外。

**缓存与证据边界。** 使用 O_DIRECT；每次读取前后用 mincore 确认 Linux 文件页驻留为零，并在读取前清零目标缓冲区。全文件 SHA-256 与写入前匹配。DPC 内部缓存和服务端缓存状态不可控，因此图中称为 **Shared FS**，不是冷 SSD 延迟或纯介质带宽。

**样本与验证。** 一个固定重复文本流；HBM/DRAM 各预热一次、正式计时三次，显示中位数和 min–max；Full Prefill 和 Shared FS 每长度各一次，共 32 次正式计时。共享存储无文件读预热；256K/1.01M 不另做完整 Prefill 预热。七组原生算子比较包含 1M/8K-query 最大形状；64K 另有完整模型参考。所有路径检查 hidden、新 KV、greedy 输出和完整历史 KV，CUDA 事件检查串行 H2D。它们不证明稀疏/dense 等价或长上下文任务质量；图中 HBM 优势也不能直接推广到有传算重叠的实现。

[共享文件系统协议](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SHAREDFS_PROTOCOL.md)；[四路径数据](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.csv)；[原始计时](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/trials.jsonl)；[发布校验](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/publication-validation.json)；[共享 KV 清理记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/sharedfs-terminal-cleanup.json)。

### 2.4 故障位置改变保护收益

![恢复成本与工作流损失](figures/preview/recovery-exposure.png)

Figure 2 在同一例子的四个分支上分别构造独立故障反事实。A1 的恢复成本可以被其余量吸收，A2 的较短恢复却全部暴露。这里采用静态重建成本、固定其他执行和队列；不是同时四分支故障实验。它引出工作流价值，而共同 worker 故障及其资源竞争需要在新版 Evaluation 中另外验证。

## 3. AegisKV Design

本节采用共享 DRAM＋SSD／共享存储。GPU HBM 用于正常执行和有界恢复工作区。**存储在哪里、是否能跨过被保护的故障域，必须明确；本机 SSD 并不自动保护整机故障。** 本轮的新图分为机制示意和可复算分析模型，不是新控制器的端到端实测。

叙述顺序是：工作流损失决定保护价值 → 稀疏性和层间重叠决定哪些字节值得留在 DRAM → 租金筛选竞争者、完整计划验证收益 → 异步提交协议把计划变成真正可恢复的状态。

### 3.1 Design Insights

第一段承接 Motivation：故障恢复越快并不必然让 WCT 越短，需要看依赖和 Slack。但 Slack 较大的 Agent 仍会在工具返回后复用自己的历史。因而把“保留可复用副本”和“占用快速 DRAM”分开；正常复用价值不会因为故障概率低或 Slack 大而消失。

第二段介绍稀疏访问的机会与边界。原有稀疏模型发布概览说明适用背景；原生轨迹实验说明过去的访问能够预测部分未来需求，同时模型间差别明显。40% 预算下过去频率预测的覆盖率：NOSA 77.8%、MiniCPM4 53.6%、实验性 Seer 路径 43.0%。它们不是故障恢复加速比，也不足以支持删除未预测的 KV。

![原生稀疏模型样本](figures/preview/sparse-models.png)

![未来历史 KV 需求的预测覆盖](figures/preview/retry-kv-prediction.png)

**正文 Figure 3 保留预测覆盖图；发布概览作为详稿素材。**模型样本不是部署占比；预测实验为每模型三篇 PG19 文档的原生采集，历史 32K，以前 512 个查询预测后 64 个查询；物理评估单元是 layer/64-token block，含全部 KV heads，预算包括必需块。误差条为文档范围，不是置信区间。

第三段引出层间重叠：留在 DRAM 中仅省去 SSD 读取，H2D 仍在；后层 SSD 读取可能被前层**仍然需要执行**的回放计算遮住。收益由请求当前的 M、未提交尾部 N、查询揭示时刻、I/O、算力和缓冲区共同决定，不能统一规定一个 L。

### 3.2 System Overview

![共享 DRAM 与存储的系统架构](figures/preview/system-overview.png)

**本图放在架构段后，保持单栏和接近方形的比例，以部署位置和状态归属组织画面。** 顶部为工作流及全局 Recovery-aware Router，Router 中展示 KV 位置摘要和节点负载；左侧控制服务包含 Tracker、KV Master、存活目录与 token log；右侧两个可互换 DP 节点分别包含 GPU 执行资源和 HBM KV；底部为执行节点之外的共享 DRAM 与 SSD／storage。节点边界、内存块和存储对象用于说明系统由哪些资源组成，算法推导由后续机制图承担。

蓝色双向路径表示 KV 传输，灰色虚线表示控制／元数据，红色虚线表示一个故障重路由示例。图中的 KV fabric 表示共享传输路径；GPU 图标概括一个 DP 的 GPU／TP 组，不暗示固定一张卡。两个 DP 能力对称，并非永久主备。控制元数据和后备副本在被保护的计算 worker 故障后仍须存活；部署时仍需满足正文定义的实际故障域。HBM 中粗边框为需求候选，最后一列为未封闭尾部。

- Tracker 提供版本化的剩余时间、Slack 和可信度。
- KV Master 决定保留、提升、降级及有条件的最后副本删除；租金在 DRAM 和 SSD 中分别筛选竞争者。
- Router 做正常亲和路由、负载选择和故障接管；共享后备不再要求绑定特定 Peer 位置。
- 引擎接口提供原生块、稀疏状态、容量与执行进度；传输路径执行复制和恢复流水线，作为 KV Master 的实现支撑，不再单独设置 Adapter/Connector 策略组件或章节。
- 目录保存不可变对象身份、有效副本代际和完整 checkpoint manifest。

每个物理对象为某层某 TP shard 的一个封闭 token block，身份包含模型／权重版本、前缀与位置语义、精度等。稀疏选择粒度、kernel tile 和物理 block 可以不同；64 是现有轨迹实验的单位，不是所有稀疏算法强制要求。多个 Agent 共享一个物理对象时，容量只计算一次。

Prefill 产生封闭块后即可提议缓存；Decode 每个配置的、与物理块对齐的 Z 触发复核，此外响应到达、工具切换、重要画像变化和容量压力。Z 固定为系统配置。最近完整提交前缀为 M，尾部为 N；有提交积压时 N 可以大于 Z。单块复制完成不能推进整个 checkpoint frontier。

### 3.3 Workflow Tracker: Remaining Time and Slack

**先介绍 GBDT 预测什么、能看到什么，再把预测传到 DAG。** 预测目标是剩余执行时长，不能对已预测的剩余量再次扣除 elapsed time。输入分为三组：角色／模型和当前输入长度；已运行时间与完成调用数；完成调用的输出长度、API 时长、上下文增长及调用间隔。任务语义和工具类型可由 orchestrator 额外提供，但当前 trace 并没有这些字段，不能画成已有实证。未来调用数、当前调用的最终输出长度和未返回的工具结果都不可用。

![可观测因素与 Agent 剩余运行时间的相关性](figures/preview/tracker-correlations.png)

**本图放在 GBDT 特征定义之后，展示观测依据和局限。** 现有 CC/Weka 数据中，1,443 个 Agent、170 个 workflow，每个 Agent 仅在第 2 次请求到来、第一次调用已完成时取一个样本；目标为整个 Agent 从此时到结束的剩余秒数，包含后续调用和间隔。横轴为 Spearman 相关系数，误差条为 2,000 次完整 workflow bootstrap 的 95% 百分位区间。输入长度与上下文增长使用 64-token hash-prefix 代理。六项相关性分别约为：elapsed +0.060、当前输入长度 −0.081、上下文增长 −0.121、前次输出长度 +0.066、前次 API 时长 +0.084、前次调用后间隔 +0.056。全部区间跨过零；保留这一弱结果。单变量相关不是 GBDT 的 feature importance，也不代表准确率，更不能据此验证在线 residual-segment 的预测目标。

既有按 workflow 分开的五折 pilot 中，median baseline 的 P50 APE 为 76.2%，basic GBDT 为 67.1%，加 history 的 GBDT 为 69.3%；误差仍大，增加历史特征没有继续改善该指标。这轮没有重新训练模型，也没有新增 GPU 实测。未来验证须按完整 workflow 和时间隔离，并同时报告错误预测正 Slack 的比例。引用的 trajectory 预测论文是方法背景，不能替代 AegisKV 的秒数预测证据。

父任务按 fork/join 切成执行段，避免把子任务执行和父任务等待重复计算。CPM 的正反向遍历产生 segment Slack，同段多个请求共享该余量。缺失依赖或无效预测采用零 Slack，并按恢复代价及正常复用保守排序；DAG 更新发布新版本，使旧估值快照失效。正文唯一的 Algorithm 1 属于后面的 KV Master；这里用文字和相关性图解释预测，不引用不存在的 Tracker 算法列表。

### 3.4 Recovery-aware Router

正常路由考虑 Agent 的前缀亲和和负载；工具调用意味着一次执行引用可能结束，缓存和恢复声明仍可保留。故障后由 Router fencing 旧 epoch，查询最后完整 manifest，选择兼容且有工作区的健康 DP。

![同 Agent 与跨 Agent 前缀复用](figures/preview/agent-prefix-reuse.png)

**本图已恢复到 PDF 的正常路由段，保持单栏，解释为什么保留 Agent 亲和有价值。** 98,827 个请求、2,090 个 Agent、393 个 workflow 的前缀分析中，同 Agent 可覆盖 97.90%，其他 Agent 为 10.06%；二者重叠，其他 Agent 的额外覆盖仅 0.37%。这是相同 workflow／模型下更早完成请求的潜在 token 前缀复用，不是实际缓存命中率，也不能泛化为跨 workflow 共享比例。

正确恢复还要求确认输出前保留存活 token log，恢复 prompt 与工具输入，防止旧 epoch 回调和重复输出；外部工具副作用的 exactly-once 由 orchestrator 负责。

### 3.5 KV Master: Sparse Recovery Value and Online Rent

#### 3.5.1 Valuing retention and demotion：先回答“值不值得”

比较完整的可执行放置方案。单个独立分支可以用 `max(0, 恢复时间 − Slack)` 描述暴露延迟，但多个同源故障请求必须一起传播到 DAG。例如两个并行必需分支都晚 10 秒，只把其中一个降到 2 秒，Join 仍晚 10 秒，不能把局部块收益直接相加。

价值包含三个来源：正常下一轮复用、声明时间范围内故障带来的 WCT 变化，以及方案转换本身对正常服务的影响。场景权重是概率或期望事件数，不能直接把 failure rate 与秒数相乘而不定义时间范围。同一物理副本计一次容量，所有 owner 的影响都参与完整 DAG 比较。

DRAM→SSD 的代价主要是下一次恢复／复用的 I/O 增量；删除最后一份有效副本则可能需要重算，两者分开。复制尚未提交时，不能按目标位置已经存在来估计收益。

#### 3.5.2 Sparse candidates and layer overlap：再回答“保留哪些块”

![完整 checkpoint 与稀疏预测的边界](figures/preview/sparse-recovery.png)

**本图在候选构造段后使用，按单栏上下排布。** 上半完整历史分布在 DRAM 和 SSD，尾部需要回放；下半预测 B0/B3，实际访问 B0/B2，B2 从 SSD 按需读取。蓝色／浅棕及 D／S 字母表示物理位置，灰度打印也能辨认。预测只改变驻留／提前读取，不能改变原生注意力语义，不能删除所有未预测的历史。

每层按最近的因果访问统计选出候选，保留原生必需块。候选可以是合法块组或有界的层顺序组合。实际 DRAM 中的 `K(r,layer)` 随上下文、访问和竞争变化；不设置所有请求共享的 L。跨同一故障域、同一 Join 的两个分支也允许有限的成对候选，降低只看单块造成的盲点，但不声称全局最优。

![SSD 读取、H2D 与层计算的恢复流水线](figures/preview/recovery-pipeline.png)

**这张图替代原 Peer-HBM Figure6 的论证，位于层间重叠段，三种方案纵向排列为单栏。** 四层，每层一个等大小需求组；SSD 读取 4 ms、H2D 1 ms、计算 3 ms。全部在 SSD 为 20 ms，保留第 4 层为 19 ms，保留第 1 层为 16 ms。后两者 DRAM 用量一致，区别来自时间位置。

上述是明确假设下的分析模型：t=0 已正确知道四组需求，独立 SSD/H2D/GPU 串行资源，有能容纳四组的临时工作区，无前台竞争、预测失误和 TP 开销。运行时必须用实际需求揭示时刻和有限缓冲模拟，不能把理想预知当成已实现能力。

![层驻留收益随计算画像变化](figures/preview/overlap-frontier.png)

**紧接流水线图，展示收益何时饱和。** 每条曲线固定一种计算画像，并有自己同画像的零驻留基线。计算更长可以遮住更多后续 I/O，但也可能增加总恢复时间；横轴层深仅为示例候选族，不是运行时统一配额。M／N 各请求不同，失败时刻未知，因此使用当前 M 和声明的 N 分布／上界评估候选，不推导“Z 大则 L 必然小”的规则。

#### 3.5.3 Online admission, rental, and eviction：最后回答“容量不足怎么办”

租金思想借鉴 Landlord，但此处不是经典独立对象 miss cost，不能继承它的竞争比。每一层存储独立维护租金水位，每个物理副本维护剩余 credit、大小和 expiration key；该层租金上升时按字节收租。DRAM 里的副本按降到 SSD 后增加的等待估值；SSD 最后副本按失去它后恢复／正常复用增加的重算估值。每个物理副本只计一次容量和对应层的租金。credit 来自局部的正常复用收益与独立故障暴露减少，**只作为筛选代理，完整 DAG 价值仍是最终判断**。

共享对象有 owner credit 份额：先按份额结清已收租金，发生新的因果 demand/checkpoint 事件时只续费该 owner；重复事件不续费，纯画像刷新只降低额度，不返还已经支付的租金。这样一个活跃 Agent 不会替所有其他 owner 永续保留共享块。

![租金、可降级集合与完整方案检查](figures/preview/rental-competition.png)

**本图放在定义租金和安全集合 Q 之后，保持单栏。** 四个等大小组，试探收租使 6/2/5 变为 4/0/3；有读 lease 的组从 credit=1 降到 0，仍不在 Q，但同样参与收租。过期只是候选，不表示已经释放 DRAM。

可选准入在私有快照中推进试探租金，逐个挑选 expiration key 最小且安全的受害者；来者必须有严格更高的 key，平局保留原对象。找到足够空间后，把来者和全部受害者作为一个计划；若 DRAM 降级还需要 SSD 受害者，该对象也必须计入同一计划，不能假设下层无限大。计划通过正常服务成本、完整 DAG 收益、不确定性和滞回门槛检查。拒绝计划不改变真实租金；接受计划时原子复核版本、预留资源、提交租金和迁移任务；物理空间要等复制提交、读者排空后才真正空出来。执行中失败应按已发生状态重规划，不能撤销现实中已完成的动作。

逻辑上仍活跃的请求可以安全降到 SSD。Q 排除的是正在读取的物理 lease、未完成依赖及无法预留下层空间的对象。强制容量收缩没有“来者”，从有限租金受害者方案中选择单位实际可释放字节损失最小者；没有安全方案就暂停新准入，等待推进。

SSD 也进行独立的租金竞争，但使用最后副本删除的价值。先处理无 owner 和已被完整新版本替代的状态；仍不足时，可以明确撤销较低价值的活跃 checkpoint 保护声明。删除最后副本之前，必须先把目录的恢复路径改为更早的完整 manifest，或退回可存活的 prompt＋token log 重算，并等待旧代际读者排空。所有 owner 因重算增加的成本都进入计划。没有合法回退和可执行受害者时，拒绝／合并新写入、保留现有 frontier。不能删除 KV 后仍对外声称旧 checkpoint 有效。两层容量和回退规则在基线中保持一致，排序策略作为消融变量。

正文 Algorithm 1 串起事件、credit 更新、候选、试探租金、完整价值检查、资源预留与执行回调。它不是“每新增一个 token 必须搬迁一次”。需要实测的是完整决策延迟、候选预算影响、画像误差及控制器抖动，不能仅用 heap 的 O(log n) 代替总开销。

**方案的安全执行（仍属于 3.5.3，不再设独立 Adapter/Connector 小节）。** 引擎接口提供实际可用的 DRAM／存储空间、封闭块、访问摘要及正常执行工作区；传输路径执行有界的前台复用、需求恢复、checkpoint／writeback 队列。有限服务份额和调度粒度控制干扰；恢复队列中真实 miss 优先于推测预取，但不声称备份零开销。

![Checkpoint frontier 和安全降级](figures/preview/checkpoint-lifecycle.png)

**本图在 KV Master 的异步执行段使用，三个面板上下排布为单栏。** 上半说明 M=128 时复制 129–192 未完成，frontier 仍是 128；所有层／TP shard／辅助状态／token log 依赖完整后才到 192。中间说明 `copy → verify/commit → redirect → drain → free`：DRAM 租金过期与物理释放是两回事。最后一行说明 SSD 最后副本删除之前，先验证并发布旧 checkpoint 或 token-log 重算的回退路径，再排空读者并删除。数字是构造的 token 位置，图不证明具体存储后端的持久性。

故障恢复先取得完整 manifest 和副本 lease，再在有界工作区里分层预取和回放。原生选择暴露 miss 时补取，dense 层按完整需求，必要稀疏元数据先恢复或重建；TP collective 和回放 batching 必须符合引擎语义。本图与执行段文字共同说明提交、重定向、读者排空和恢复步骤；它们是存储实现的必要机制，不是 Peer HBM 容量控制算法的保留。重复回调、旧 epoch 和复制失败都不能错误推进 frontier。

## 4. Evaluation

本节按“主结果—因果解释—真实 trace—完整消融—代价与边界”组织，当前有 **33 张原生单栏图**。证据分为解析模型、真实 trace 的描述统计、trace-driven model、待执行物理实验；没有把理论曲线写成已完成的系统测量。完整逐项执行规格在 [EXPERIMENT_MATRIX.md](../experiments/eurosys27/EXPERIMENT_MATRIX.md)，逐图说明在 [FIGURE_CATALOG.md](../experiments/eurosys27/FIGURE_CATALOG.md)。

### 4.1 实验契约、基线和统计对象

物理系统至少需要两个故障分离的 serving replicas 和故障后仍可访问的 backing store。TP2 的 host failure 需要两台各有两张兼容 GPU 的 host。GPU process、整个 replica、host、storage host 失效是不同实验；同 host 的 SSD 不能支持 host-loss 保护声明。DP=2/4/8 与 TP=1/2 分开测，记录真实剩余容量、执行 KV、activation 和 staging HBM。

工作负载包括 coding agents、FanOutQA 和受控 sequential / balanced fork-join / heterogeneous fork-join，每 family 至少 30 个独立 workflow。原始 DAG 只运行一次，首调用也进入完整 prompt 分母；主实验冻结工具响应，live tools 单独验证外部有效性。覆盖 dense/native-sparse 模型和受支持的 32K/128K/512K/1.01M 长度；不支持/OOM 的 cell 不伪造数据。

Recompute 对照说明可靠 checkpoint 的作用；同样完整覆盖、同样 DRAM/storage 预算、同样 manifest/lease/transfer 的 LRU 与 reuse-only，才隔离工作流价值的贡献。All-DRAM 是放宽容量的参考；小实例 oracle 仅在同候选集合与同目标内有效。外部系统必须运行真实 artifact 或标注 reimplementation，不能给 DéjàVu/GhostServe/LUMEN 编造理论性能。

每个策略各有 healthy mate，定义 D=WCT_fault−WCT_healthy，策略比较用同 ID 的 D_LRU−D_Aegis。并列报告绝对 WCT、completion、deadline goodput 和 p50/p95/p99。分三类 cohort：直接 interrupted、未被 kill 但共享 reader/NIC/GPU、资源独立。10 个独立 paired campaigns 是一级重复单位；workflow、request、token/层/块是其下级，不能混充独立重复。

### 4.2 一次故障：系统收益有多大

主 cell 在固定 workflow/Agent/request 达到冻结总 token progress 80% 时 kill source replica，包含该 source 上全部受影响请求。Mechanism attribution 固定故障前路由、committed coverage、transfer scheduler；full-system 比较允许真实路由和 achieved frontier 变化，但固定原 arrival cohort 做 intent-to-treat，不能按各策略自身“幸存样本”筛选。

理论基例有四个分支：state=4/8/12/16GiB，remaining=12/10/5/1s；DRAM16GiB、storage160GiB，DRAM/storage/NIC/H2D=20/4/12/20GiB/s，两恢复目标，floor0.25s、replay0.4s。0.25GiB chunks 通过共享 reader、NIC 和目标 H2D 调度。所有 rates 都是声明的模型假设，未标成某种 SSD/GPU 的校准。

36 个 size×slack×storage-rate 配置中，workflow value 对 LRU 为17优、19平。LRU 与 reuse-only 在此构造顺序下恰好选同对象，不能外推所有复用策略等价。基例 penalty：storage-only5.5583s，LRU3.6208s，workflow value1.6125s；相对 LRU 减少2.0083s，即 **failure penalty 减少55.5%**。这是 residual join 从15.6208s降到13.6125s，不能宣传为完整 WCT 降55.5%。

![workflow-outcomes](figures/preview/eval-workflow-outcomes.png)

![paired-benefit](figures/preview/eval-paired-benefit.png)


### 4.3 一次故障：优势来自哪里

四分支 join slack 为0/2/7/11s。LRU 把最大、最近的 A3 保留在 DRAM；workflow value 保留 A0/A1。前者加速的 A3 大部分恢复本可隐藏在 Slack 内，后者优先消除 A0 的暴露延迟。WCT penalty 应直接计算 max(d_i+R_i)−max(d_i)，不是把所有单请求 positive-part penalty 相加。

![branch-exposure](figures/preview/eval-branch-exposure.png)


固定 placement 后，按 floor→read→NIC→H2D→replay 顺序恢复资源成本，逐次计算最终 join 的差，得到可以望远镜相加的 counterfactual 分解。交互项归属依赖顺序；它不是唯一“因果贡献”。实测还应沿 parent event 链抽取真实关键路径，只累加路径上不重叠的时间。总 SSD+NIC+H2D+GPU work 必须另列，不能当成恢复 wall time。

![recovery-attribution](figures/preview/eval-recovery-attribution.png)

![storage-traffic](figures/preview/eval-storage-traffic.png)


重要反例是：workflow value 从 storage 读28GiB，高于 LRU 的24GiB；整个恢复池占用7.6833s，也高于6.6833s。它改善当前 workflow 的 join，但没有减少所有资源成本。图像和正文都保留这一点。

### 4.4 一次故障：是否把延迟转嫁给其他 workflow

实验交叉变化 simultaneously interrupted workflows=1/2/4/8、targets=1/2/4、固定前台负载30/60/85%；增加 reader/NIC 独立的对照。记录 direct/collateral/isolated cohort 的 WCT、retry queue、backlog、恢复到预设 latency band 的时间。共享拓扑不存在时，不声称跨目标 cascade。

FIFO 模型中一个四分支恢复独占两目标 pool 直到最后一个 ready，n 个同刻恢复的均值为 D+(n−1)S/2。n=8 时，workflow value28.5042s，反而差于 LRU27.0125s。单次收益不能直接外推成 burst 收益；完整 load-aware router 是否纠正这种问题，仍需真实实验。

![burst-interference](figures/preview/eval-burst-interference.png)

![background-backlog](figures/preview/eval-background-backlog.png)


流体 backlog 图固定正常 I/O 使用70%的4GiB/s reader，以剩余带宽消化恢复字节，说明更大的 bytes 会拖长清空。它是 I/O backlog，不是 TTFT 或未失败 workflow 的实测 WCT。

### 4.5 故障阶段、Z 与实际提交滞后

同 ID 重复20/50/80/95%逻辑进度，另外测 prefill/decode/tool wait/迁移 commit 边界。当前 phase 模型只改变历史 state 大小，固定 remaining 与预算，用来隔离增长效应；物理实验必须同时记录实际 DAG、原生需求与 committed frontier。

![logical-fault-phase](figures/preview/eval-logical-fault-phase.png)

![checkpoint-lag](figures/preview/eval-checkpoint-lag.png)


Z=64/256/1024 的理想平均应枚举所有 phase，同 Z 同 phase 配对后再平均。实际日志保存 trigger/attempt/start/commit/frontier/ack，tail N 可以超过 Z。短 Z 可能增加 write contention 与失败提交，不能把 Z 当 durability 上界。

### 4.6 真实 failure trace：先核对语义

LANL 官方数据定义是带 node/system、start/end、cause 的历史节点 interruption。原始 FTP 当前不可达；本次取得版本钉住的公开原格式 CSV redistribution，共23,739行，而官网描述23,741行；**差异未解决，不能声称与原始archive字节一致**。清洗保留 purpose=compute，排除非compute1,648行、零时长122行，同节点相交/相接区间合并231，得到21,738 intervals、22 systems、3,542 observed nodes。所有原因都保留，包括可能的 maintenance，不能改称 hardware-only crashes。

![trace-outages](figures/preview/eval-trace-outages.png)

![trace-bursts](figures/preview/eval-trace-bursts.png)


分钟分辨率下，19,561个同系统 start groups 中568个多节点，最大45节点；时间相同不证明同一物理原因。不同系统不叠成一个集群。历史 CPU/HPC trace 用于检验时间聚簇，不是2027 GPU failure rate或fleet availability 的估计。

现代 Reflex/ByteDance 数据有98个训练 job、344,175条 alerts、144个 faulty node/job labels，其中108个 label 没有该节点 alert；各 job 又独立平移时间且无repair times。因此只做 label 分布，不拿first alert当fail-stop，不拼接跨job日历。

![modern-trace-labels](figures/preview/eval-modern-trace-labels.png)


### 4.7 原始日历重放：平均收益与尾部必须同时看

当前条件模型把每个 cleaned node start 映射成一个假设的四分支 workflow 恢复；每 original system 有独立 FIFO spare pool。placement 在 trace 前固定，保留原始 start 间隔，以 node ID打破同刻顺序。递推 q_i=max(0,q_(i−1)+S−Δa)，penalty=q_i+D。原始数据提供到达日历，服务时间来自字节与速率模型。

这个模型假设恢复池一直可用，没重放健康服务、有限spare、真实GPU修复、第二次target失败，所以只能称 **trace-driven recovery-load model**。不能因为 input trace真实就把输出称物理WCT实测。

![trace-penalty](figures/preview/eval-trace-penalty.png)

![trace-queue](figures/preview/eval-trace-queue.png)


原速下 LRU mean10.4533s、workflow value9.4673s，改善9.4%；但queue wait6.8324→7.8548s，p95 37.0375→40.0292s，p99 204.1208→232.1125s。逐 system 图保留负值。均值改善支持条件结论，尾部变差否定“所有尾部均更好”的声明。

![trace-system-benefit](figures/preview/eval-trace-system-benefit.png)

![trace-burst-control](figures/preview/eval-trace-burst-control.png)

![trace-time-stress](figures/preview/eval-trace-time-stress.png)


同分钟事件按node ID均匀展开到59秒的分辨率敏感性下，LRU/价值模型mean为8.0997/7.0224s、p99为163.8936/191.8852s，负尾部仍在；构造的秒级时间不是推断出的真实时间。even-spacing对照保留每系统事件数量和首末时间，去掉聚簇；10/100/1000倍time compression明确是压力测试，只有1倍保留原速。完整campaign必须：固定workload/domain mapping并公开seed；按down/up真实减少/返还capacity；保留故障簇、recovery期间再次失败、所有open-loop arrivals、未完成workflow；不同spare fraction和storage-domain另列。事件簇大于机器规模时明确unsupported或按声明规模仿真，不能偷偷串行化45节点事件。

### 4.8 完整价值消融与四格交互

消融矩阵包括：无DAG/Slack、joint source-event改为isolated sum、无normal reuse、无failure value、frozen placement、direct revaluation替代rent、无renewal、无hysteresis、recency替代causal sparse history、serial替代bounded layer overlap、locality-only替代load-aware router，以及singleton与bounded-pair候选。每项保留同样安全覆盖、预算与原生attention。

![ablation-fault](figures/preview/eval-ablation-fault.png)

![ablation-reuse](figures/preview/eval-ablation-reuse.png)

![common-fault](figures/preview/eval-common-fault.png)


当前两个主柱状图只评价static value，其余机制不能借这两个图声称已被完整验证。共同失败反例显示候选存在互补性，必须整方案revalue；增加pairs时同时报告oracle regret和控制成本。

四组2×2交互：DAG×joint-fault、sparse rank×overlap、rent×hysteresis、load-aware route×shared-link contention。四个cell同campaign配对，interaction=(Y11−Y10)−(Y01−Y00)，不能把独立speedup相加。安全协议不做“关闭后更快”的有效性能基线。

### 4.9 稀疏需求与layer overlap的解构

八层模型，每层full selected payload的SSD4ms、H2D1ms、compute3ms；DRAM同样容纳两层payload，staging最多当前+下一层。early/late placement与serial/pipeline四格保持同需求。改变selected-density时所有策略一起变，不允许为了cache策略更好而改变native attention。

![layer-factorial](figures/preview/eval-layer-factorial.png)

![layer-exposure](figures/preview/eval-layer-exposure.png)

![sparse-misses](figures/preview/eval-sparse-misses.png)


full demand下两个serial都56ms，late-pipeline34ms、early-pipeline32ms；所有case required compute都24ms，差别来自exposedwait。错误prefetch消耗额外读、真实需求等reveal才读；当前correct-prefetch比例是人为输入，正确位置按层序指定，不是学习器准确率。

原生实验捕获held-out retry的per-layer demand union与reveal时刻，用此前历史预测；按workflow/document分训练验证，不按blocks拆分。equal physical bytes、mandatory sink/window和coverage保持一致，报告all-layer coverage、unused/miss bytes、reveal-to-ready、GPU stall、workspacepeak、total replay和WCT。早期层100%命中不等于全部层100%。

### 4.10 在线租用、续租与迁移滞回

独立tier模型含8slots、24等字节对象、512次确定性机会，所有策略共用causal value与visit/next-use序列。direct value与trial rent同样做current joint replacement check，后者多了credit screening；拒绝preview不改变committed rent。额外删除hysteresis或renewal分别对照。

![rental-churn](figures/preview/eval-rental-churn.png)

![rental-revaluation](figures/preview/eval-rental-revaluation.png)

![rental-cost](figures/preview/eval-rental-cost.png)


direct迁移108次、trial rent106次，但两者都396次完整revaluation；总miss+movement成本462.96对506.39，rent更差。去hysteresis迁移121次；去renewal虽然只77次，成本升到526.05。少搬迁不等于更好的系统，也没有证据说rent降低CPU。

实际需重放平滑漂移/突变、toolhandoff、pressure与leases，分别记录DRAM/storage rent、credit、trial/committed、renewal、safevictims、planvalue、字节、CPU与WCT。如果direct value足够便宜且更好，应简化机制，而不是删除负例。

### 4.11 容量、I/O和有限可靠覆盖

DRAM/unique-working-set为0/0.1/0.25/0.5/1，storage为0.5/1/2；shared物理对象按actual replica计费，reserved/retiring/metadata也计入。小storage要真实触发last-copy eviction，不能靠无限SSD假设掩盖fallback。All-DRAM只有参考地位。

![capacity-frontier](figures/preview/eval-capacity-frontier.png)

![storage-bottleneck](figures/preview/eval-storage-bottleneck.png)


测read/write/同时读写、不同IO粒度、并发、NIC/H2D、client与server cache。Direct IO只控制client路径；DPC或sharedFS server cache未知就保留未知。加storage slowdown/loss，对比真实可恢复coverage，不将低预测latency当状态可用性的证明。

### 4.12 预测、stale profile与fallback

剩余时间学习器用causal landmarks，按完整workflow做时间划分；报告remaining error、falseSlack、criticalrank、fallback率和推理成本。不能从相关系数/WAPE反推raw CDF。对照median、zeroSlack和oracle duration。

![prediction-robustness](figures/preview/eval-prediction-robustness.png)


当前alternating−25%扰动使workflow value penalty4.5583s，差于LRU3.6208s。实验扫描独立/相关±10/25/50/100%、缺边、coldstart、模型shift、带宽profile过期和failureprobability误校准；重新运行策略决策，再对真实结果计regret。

### 4.13 正常服务与保护值不值得

F0使用原DAG一次，首调用和全部requests计入。报告WCT、TTFT、ITL、SLOgoodput、GPU/CPU成本和分tier request/tokenhit，区分potential prefixsharing与runtime命中。当前M/D/1只说明I/O干扰，不是TTFT。

![healthy-io](figures/preview/eval-healthy-io.png)

![rate-break-even](figures/preview/eval-rate-break-even.png)


同horizon、同单位的摊销模型是 p_f×ΔD−C_h。基例ΔD2.0083s、健康成本0.05s时，需要p_f>0.0249。该概率与健康成本均为敏感性输入，不是trace估计；真实低故障率可能让总体净收益为负，即使条件恢复更快。

### 4.14 正确性、故障交错与pressure

覆盖reservation、partialcopy、checksum、COMMITTED、redirect、tokenack、lease drain前后注入；增加duplicatecallback、staleepoch、targetloss、missingTP/selector、timeout和fulltiers。PENDING不可读、manifest必须闭合、accepted output不重复、tokenlog生存、greedy-next-token和all-layer状态在声明精度下匹配。工具副作用的idempotency另查。

![safe-demotion](figures/preview/eval-safe-demotion.png)


24→16GiB target不代表物理内存立即释放；当前模型5.5s才在commit/redirect/drain后释放8GiB。真实测试包括reversepressure、leaseoverlap、copyfailure和lastcopyfallback；逐事件核对物理/预留/提交/retiring/free。小状态机穷举并对每类交错至少100次随机执行，不能只用静态assert代替协议运行。

### 4.15 扩展性与控制成本

DP2/4/8，DAG10/100/1000，groups10²/10³/10⁴，候选16/64/256；独立扫描sourceconcurrency和targetcount。测decisionp50/p95/p99、profilecalls、nodes/edges visits、lock、metadata、planage、foregroundstall和actualWCT。

![controller-scaling](figures/preview/eval-controller-scaling.png)


当前图只是声明per-node cost的操作投影，没有校准CPU，也没有把复杂profile与候选枚举成本藏进O(V+E)。oracle只在小集合可行，不能把大规模无oracle写成gap=0。

### 4.16 统计、复现与执行顺序

一级单位为独立pairedcampaign，先算同workflow的各策略F1−F0，再算策略差，campaign内聚合后bootstrap campaigns（10,000 resamples，固定分析seed）。trace要同时给event-weighted与system/window-weighted结果，整簇/整非重叠window重采样，不将同一次事故的节点数当独立运行数。所有当前解析/trace模型图physicalruns=0，不制造CI。

统一观察τ，所有输入workflow进入completion/deadlinegoodput；complete-case latency需要共同eligiblecohort和排除计数。使用RMST须声明估计器与删失假设，timeout不能填假的完成时间。原始日志、manifest、sourcehash、数据转换和绘图命令必须可追溯。

执行顺序：正确性/后端校准 → 单次故障主结果及关键路径/队列分解 → 正常开销 → 关键四格消融 → 连续真实trace → 压力/预测/扩展性。当前两个必须面对的研究问题是 **静态workflow优先级的队列尾部回归** 与 **rent未证明优于direct value**；后续实验应解决或缩小这些主张。

### 4.17 图像配置与数据替换

图像宽3.33465in，固定物理字体和边距，PDF/SVG/PNG三种导出；输入CSV与独立visual spec。数据换成实测后，保留同坐标、单位和layout；负值、timeout和尾部不能删。`prepare_measured_figures.py`检查原始物理日志hash、aggregationcommand、campaignunit及sampleaccounting，支持只替换已有实测的图；未测图继续保留原证据标签。理论结果解释与caption不会因换了CSV而自动获得实测含义。


## 5. Related Work

DéjàVu、GhostServe 和 RaidServe 已分别研究 KV 复制／编码及 TP 故障恢复；LUMEN 已研究 load-aware checkpoint 与恢复分配。Mooncake、CachedAttention、Strata 和 HCache 已研究分层复用、传算重叠、存储布局或其他状态表示。Parrot、KVFlow、Pythia、Cortex 与 TOPAS 已使用工作流信息优化正常执行。特别是 TOPAS 已结合 remaining service path、reuse 和 movement cost，因此“Slack 加缓存”不足以支持新颖性。

本稿把拟议差异限定为：共同故障域对多个请求的联合影响，正常复用与恢复保护共存，DRAM demotion 与 last-copy deletion 的不同后果，以及异步迁移时有效 checkpoint 的保持。完整原始来源和对应实验要求见 [RELATED_WORK.md](../experiments/eurosys27/RELATED_WORK.md)。这些差异需要实现与消融证明，而非由命名或架构图自动成立。

## 6. Conclusion

AegisKV 将 KV 保护视为有限 DRAM 与存储中的在线工作流资源管理。它保留普通复用，按依赖评估共同故障，并将期望放置与实际提交状态分开。理论分析给出了可能有价值的区域和明确限制：DRAM 容量充裕、storage 较快、预测偏差或共享队列都可能使收益变小。新版完整论文、模型与图像已经形成可复算的研究草稿；能否成为有竞争力的 EuroSys 系统论文，仍取决于协议实现、强基线和真实配对实验。
