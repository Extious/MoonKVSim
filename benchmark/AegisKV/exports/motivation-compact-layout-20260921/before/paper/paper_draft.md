# AegisKV：面向工作流的 DRAM／存储 KV 检查点管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。本稿对应 2026-09-20 用户确认的 **共享 DRAM＋SSD／共享存储** 方案：删除专用 Peer HBM 及其 L/K/容量控制，保留正常推理所需的 GPU HBM。新增 Evaluation 图均为明确标注的理论分析；它们没有证明新版系统已经实现或取得实测加速。

正文现已整合为 12 页技术内容；本中文详稿保留全部设计解释与十张 Evaluation 图。模型发布概览、prefix locality 图和五张辅助 Evaluation 图保留于详稿／实验包，正文保留六张新设计图与五张主要 Evaluation 图。图号以当前 `main.pdf` 为准；完整扩展英文稿已归档。

## 1. Introduction

多 Agent 应用的用户等待的是整个任务完成，而不是某个请求单独完成。代码修改、并行检索和综合报告包含串行依赖、并行分支与汇合点；同样长的请求延迟，发生在不同分支上，对最终结果的影响可能完全不同。正常运行下的工作流调度和 prefix caching 已经利用这类信息，但故障提出了另一个问题：一个 worker 同时中断若干请求后，有限的快速恢复资源应该保护哪些上下文？

Agent 的多轮调用不断积累推理、代码和工具输出。失去 KV 后，重建长历史可能远比设备中断本身昂贵。KV checkpoint 可以避免这部分计算，但全部历史不能无限留在 DRAM。SSD 或共享存储提供更大容量，代价是读取、网络传输和排队。普通 LRU、单请求恢复速度、甚至单独的关键路径优先级，都不能完整描述这些权衡。

AegisKV 将共享缓存与故障恢复状态统一管理：**大 Slack 不禁止正常缓存；DRAM 降级与最后副本删除分别估值；同一故障域中断的请求共同经过 DAG 计算其影响。** Controller 选择有限容量内的保留和迁移方案，Adapter/Connector 在版本化 manifest、空间预留和 reader lease 约束下安全执行。Router 选择兼容且有执行空间的存活副本，不再要求预先绑定 Peer HBM 位置。

论文的拟议贡献包括：结合正常复用与共同故障的工作流恢复价值；区分降级和删除的在线有限容量管理；保留检查点有效性的异步迁移协议。分层缓存、KV 复制、预取和普通工作流调度均已有研究，不能作为本工作的独立新颖性主张。实验必须证明这些新增决策在强基线之上仍有收益。

## 2. Background and Motivation

### 2.1 Agent、请求、工作流与故障

一个 Agent 可以发出多轮 LLM 请求并等待工具或子 Agent；工作流由所有必须完成的输出及其依赖组成。GPU/worker 故障会同时造成 KV 不可访问和服务容量下降。本文聚焦存在兼容存活 replica、输入/token log 与控制状态可恢复、备份介质处于声明故障域之外的 fail-stop 故障。同机 SSD 不能自动覆盖整机丢失。

### 2.2 WCT 决定保护优先级

![工作流示例](figures/preview/workflow.png)

Figure 1(a) 保留真实四分支时序：A2 最晚完成，A1 虽更早结束，却可能具有较大的等待余量。这里的 join 假定需要所有分支输出。条长和位置对应观测时间，虚线表示在该 join 假定下的余量；示例不是总体分布。

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

**本图放在架构段后，保持单栏。** 上部为 Agent DAG；中部为 Tracker、KV Master、Router 和存活目录；下部为对称 DP 执行端及共享 DRAM／存储。蓝色实线表示 KV 数据移动，虚线表示控制／元数据，灰色工作流边表示依赖。

- Tracker 提供版本化的剩余时间、Slack 和可信度。
- KV Master 决定保留、提升、降级及有条件的最后副本删除；租金在 DRAM 和 SSD 中分别筛选竞争者。
- Router 做正常亲和路由、负载选择和故障接管；共享后备不再要求绑定特定 Peer 位置。
- Adapter 提供原生块、稀疏状态、容量与执行进度；Connector 执行复制和恢复流水线。
- 目录保存不可变对象身份、有效副本代际和完整 checkpoint manifest。

每个物理对象为某层某 TP shard 的一个封闭 token block，身份包含模型／权重版本、前缀与位置语义、精度等。稀疏选择粒度、kernel tile 和物理 block 可以不同；64 是现有轨迹实验的单位，不是所有稀疏算法强制要求。多个 Agent 共享一个物理对象时，容量只计算一次。

Prefill 产生封闭块后即可提议缓存；Decode 每个配置的、与物理块对齐的 Z 触发复核，此外响应到达、工具切换、重要画像变化和容量压力。Z 固定为系统配置。最近完整提交前缀为 M，尾部为 N；有提交积压时 N 可以大于 Z。单块复制完成不能推进整个 checkpoint frontier。

### 3.3 Workflow Tracker: Remaining Time and Slack

用因果可见的角色、模型、已知上下文、运行时间和已完成调用预测剩余时长；不把未来 token／工具结果作为特征。父任务按 fork/join 切成执行段，避免把子任务时间和父任务等待重复计算。CPM 的正反向遍历产生 segment Slack，同段的多个请求共享该余量。

Algorithm 1 展示事件触发的预测、DAG 计算和版本发布。未知依赖或过期预测进入保守回退，不能假装未来 DAG 已知。引用的其他预测论文提供方法背景，不是本系统秒数预测精度。

### 3.4 Recovery-aware Router

正常路由考虑 Agent 的前缀亲和和负载；工具调用意味着一次执行引用可能结束，缓存和恢复声明仍可保留。故障后由 Router fencing 旧 epoch，查询最后完整 manifest，选择兼容且有工作区的健康 DP。

![同 Agent 与跨 Agent 前缀复用](figures/preview/agent-prefix-reuse.png)

**本图放在正常路由段，解释为什么保留 Agent 亲和有价值。** 98,827 个请求、2,090 个 Agent、393 个 workflow 的前缀分析中，同 Agent 可覆盖 97.90%，其他 Agent 为 10.06%；二者重叠，其他 Agent 的额外覆盖仅 0.37%。这是相同 workflow／模型下更早完成请求的潜在 token 前缀复用，不是实际缓存命中率，也不能泛化为跨 workflow 共享比例。

正确恢复还要求确认输出前保留存活 token log，恢复 prompt 与工具输入，防止旧 epoch 回调和重复输出；外部工具副作用的 exactly-once 由 orchestrator 负责。

### 3.5 KV Master: Sparse Recovery Value and Online Rent

#### 3.5.1 Valuing retention and demotion：先回答“值不值得”

比较完整的可执行放置方案。单个独立分支可以用 `max(0, 恢复时间 − Slack)` 描述暴露延迟，但多个同源故障请求必须一起传播到 DAG。例如两个并行必需分支都晚 10 秒，只把其中一个降到 2 秒，Join 仍晚 10 秒，不能把局部块收益直接相加。

价值包含三个来源：正常下一轮复用、声明时间范围内故障带来的 WCT 变化，以及方案转换本身对正常服务的影响。场景权重是概率或期望事件数，不能直接把 failure rate 与秒数相乘而不定义时间范围。同一物理副本计一次容量，所有 owner 的影响都参与完整 DAG 比较。

DRAM→SSD 的代价主要是下一次恢复／复用的 I/O 增量；删除最后一份有效副本则可能需要重算，两者分开。复制尚未提交时，不能按目标位置已经存在来估计收益。

#### 3.5.2 Sparse candidates and layer overlap：再回答“保留哪些块”

![完整 checkpoint 与稀疏预测的边界](figures/preview/sparse-recovery.png)

**本图在候选构造段后使用。** 左边完整历史分布在 DRAM 和 SSD，尾部需要回放；右边预测 B0/B3，实际访问 B0/B2，B2 从 SSD 按需读取。蓝色／浅棕及 D／S 字母表示物理位置，灰度打印也能辨认。预测只改变驻留／提前读取，不能改变原生注意力语义，不能删除所有未预测的历史。

每层按最近的因果访问统计选出候选，保留原生必需块。候选可以是合法块组或有界的层顺序组合。实际 DRAM 中的 `K(r,layer)` 随上下文、访问和竞争变化；不设置所有请求共享的 L。跨同一故障域、同一 Join 的两个分支也允许有限的成对候选，降低只看单块造成的盲点，但不声称全局最优。

![SSD 读取、H2D 与层计算的恢复流水线](figures/preview/recovery-pipeline.png)

**这张图替代原 Peer-HBM Figure6 的论证，位于层间重叠段。** 四层，每层一个等大小需求组；SSD 读取 4 ms、H2D 1 ms、计算 3 ms。全部在 SSD 为 20 ms，保留第 4 层为 19 ms，保留第 1 层为 16 ms。后两者 DRAM 用量一致，区别来自时间位置。

上述是明确假设下的分析模型：t=0 已正确知道四组需求，独立 SSD/H2D/GPU 串行资源，有能容纳四组的临时工作区，无前台竞争、预测失误和 TP 开销。运行时必须用实际需求揭示时刻和有限缓冲模拟，不能把理想预知当成已实现能力。

![层驻留收益随计算画像变化](figures/preview/overlap-frontier.png)

**紧接流水线图，展示收益何时饱和。** 每条曲线固定一种计算画像，并有自己同画像的零驻留基线。计算更长可以遮住更多后续 I/O，但也可能增加总恢复时间；横轴层深仅为示例候选族，不是运行时统一配额。M／N 各请求不同，失败时刻未知，因此使用当前 M 和声明的 N 分布／上界评估候选，不推导“Z 大则 L 必然小”的规则。

#### 3.5.3 Online admission, rental, and eviction：最后回答“容量不足怎么办”

租金思想借鉴 Landlord，但此处不是经典独立对象 miss cost，不能继承它的竞争比。每一层存储独立维护租金水位，每个物理副本维护剩余 credit、大小和 expiration key；该层租金上升时按字节收租。DRAM 里的副本按降到 SSD 后增加的等待估值；SSD 最后副本按失去它后恢复／正常复用增加的重算估值。每个物理副本只计一次容量和对应层的租金。credit 来自局部的正常复用收益与独立故障暴露减少，**只作为筛选代理，完整 DAG 价值仍是最终判断**。

共享对象有 owner credit 份额：先按份额结清已收租金，发生新的因果 demand/checkpoint 事件时只续费该 owner；重复事件不续费，纯画像刷新只降低额度，不返还已经支付的租金。这样一个活跃 Agent 不会替所有其他 owner 永续保留共享块。

![租金、可降级集合与完整方案检查](figures/preview/rental-competition.png)

**本图放在定义租金和安全集合 Q 之后。** 四个等大小组，试探收租使 6/2/5 变为 4/0/3；有读 lease 的组从 credit=1 降到 0，仍不在 Q，但同样参与收租。过期只是候选，不表示已经释放 DRAM。

可选准入在私有快照中推进试探租金，逐个挑选 expiration key 最小且安全的受害者；来者必须有严格更高的 key，平局保留原对象。找到足够空间后，把来者和全部受害者作为一个计划；若 DRAM 降级还需要 SSD 受害者，该对象也必须计入同一计划，不能假设下层无限大。计划通过正常服务成本、完整 DAG 收益、不确定性和滞回门槛检查。拒绝计划不改变真实租金；接受计划时原子复核版本、预留资源、提交租金和迁移任务；物理空间要等复制提交、读者排空后才真正空出来。执行中失败应按已发生状态重规划，不能撤销现实中已完成的动作。

逻辑上仍活跃的请求可以安全降到 SSD。Q 排除的是正在读取的物理 lease、未完成依赖及无法预留下层空间的对象。强制容量收缩没有“来者”，从有限租金受害者方案中选择单位实际可释放字节损失最小者；没有安全方案就暂停新准入，等待推进。

SSD 也进行独立的租金竞争，但使用最后副本删除的价值。先处理无 owner 和已被完整新版本替代的状态；仍不足时，可以明确撤销较低价值的活跃 checkpoint 保护声明。删除最后副本之前，必须先把目录的恢复路径改为更早的完整 manifest，或退回可存活的 prompt＋token log 重算，并等待旧代际读者排空。所有 owner 因重算增加的成本都进入计划。没有合法回退和可执行受害者时，拒绝／合并新写入、保留现有 frontier。不能删除 KV 后仍对外声称旧 checkpoint 有效。两层容量和回退规则在基线中保持一致，排序策略作为消融变量。

正文 Algorithm 1 串起事件、credit 更新、候选、试探租金、完整价值检查、资源预留与执行回调。它不是“每新增一个 token 必须搬迁一次”。需要实测的是完整决策延迟、候选预算影响、画像误差及控制器抖动，不能仅用 heap 的 O(log n) 代替总开销。

### 3.6 Adapter and Connector: Safe Layered Recovery

Adapter 提供每个窗口可用的 DRAM／存储空间以及正常执行工作区，Connector 执行有界的前台复用、需求恢复、checkpoint／writeback 队列。有限服务份额和调度粒度控制干扰；恢复队列中真实 miss 优先于推测预取，但不声称备份零开销。

![Checkpoint frontier 和安全降级](figures/preview/checkpoint-lifecycle.png)

**本图在异步一致性段使用。** 上半说明 M=128 时复制 129–192 未完成，frontier 仍是 128；所有层／TP shard／辅助状态／token log 依赖完整后才到 192。中间说明 `copy → verify/commit → redirect → drain → free`：DRAM 租金过期与物理释放是两回事。最后一行说明 SSD 最后副本删除之前，先验证并发布旧 checkpoint 或 token-log 重算的回退路径，再排空读者并删除。数字是构造的 token 位置，图不证明具体存储后端的持久性。

故障恢复先取得完整 manifest 和副本 lease，再在有界工作区里分层预取和回放。原生选择暴露 miss 时补取，dense 层按完整需求，必要稀疏元数据先恢复或重建；TP collective 和回放 batching 必须符合引擎语义。Algorithm 3 展示提交、重定向、读者排空和恢复步骤。重复回调、旧 epoch 和复制失败都不能错误推进 frontier。

## 4. Evaluation

详细执行矩阵、日志字段、配对统计和失败处理见 [PROTOCOL.md](../experiments/eurosys27/PROTOCOL.md)。当前理论模型的全部假设见 [THEORY.md](../experiments/eurosys27/THEORY.md)。以下图形的布局已固定，实测时通过 [数据契约](../experiments/eurosys27/DATA_CONTRACT.md) 填入数据，不修改图像坐标代码。

### 4.1 统计口径与模型

主指标为同策略的 `fault WCT − healthy WCT`；策略间再进行配对比较。同时报告正常／故障绝对 WCT、完成率、TTFT、token delay、SLO goodput、I/O／迁移字节、checkpoint lag、重算量和控制器开销。包括直接中断及共享资源受影响的工作流。

理论模型包含四个 4/8/12/16 GiB checkpoint group、16 GiB DRAM、有限的 160 GiB backing；采用声明的 DRAM／storage／network／H2D 速率，并以 event calendar 模拟有依赖的分块传输。三个状态规模、四个 Slack 倍率与三个 storage 带宽组成 36 个确定性配置。它不是实测 repeat，也不执行原生模型、GBDT 或异步 Controller；不画虚构置信区间。

### 4.2 工作流收益和容量边界

![工作流损失](figures/preview/workflow-outcomes.png)
![容量曲线](figures/preview/capacity-frontier.png)

Figure 10：AegisKV 静态放置模型在 17 个配置优于 LRU，19 个持平；均值为 9.518 与 10.892 s。该网格不代表生产负载概率分布。可行枚举 oracle 的均值为 9.386 s，贪心方案存在非零目标 regret；不能称为最优解。当前 LRU 和 reuse-only 因假设排序相同而重合。容量为零及全部状态可放入 DRAM 时，策略应收敛，这是必须保留的负对照。

### 4.3 Storage、checkpoint lag 和预测误差

![存储带宽](figures/preview/storage-bottleneck.png)
![提交落后](figures/preview/checkpoint-lag.png)

Figure 11：storage 变快可能缩小 DRAM placement 的价值；链路或计算仍可能成为共同瓶颈。Z 只是 review 间隔，未提交 tail 可以因 backlog 超过 Z。理想模型枚举 N=0..Z−1；真实故障必须按相同 ID 和逻辑进度匹配，以实际 frontier 计算 tail。SSD 与共享文件系统分开测量。

![预测扰动](figures/preview/prediction-robustness.png)
![正常 I/O 干扰](figures/preview/healthy-io.png)

辅助分析图：时长扰动图使用真实时长计算 outcome，仅扰动 placement 输入，它不是 GBDT accuracy CDF。I/O 图采用另一个 M/D/1 模型，说明利用率升高后排队非线性放大；它不是系统 TTFT 测量。实测需分别报告 duration error、false-positive Slack、fallback、decision regret 与正常服务成本。

### 4.4 消融与安全迁移

新增设计机制需要独立消融：同价值模型下的直接重估、完整租金、无续费和无老化；稀疏访问排名对比 recency；相同完整 checkpoint 和临时工作区下的串行读取与层间流水；SSD 满时的显式回退。当前四分支静态放置曲线不验证这些在线机制，须与本轮层流水线的分析模型分开。

![消融](figures/preview/policy-ablation.png)

Figure 12 分别去掉依赖和正常复用价值，并同时呈现故障损失与下次调用 restore 时间。当前理论数据保留了偏重故障时正常复用等待增加的权衡。需要与相同 I/O、相同容量、相同 failure routing 的强基线比较，不能只靠对比 Recompute 证明新策略。

![安全降级](figures/preview/safe-demotion.png)
![共同故障](figures/preview/common-fault.png)

辅助协议图中，8 GiB 在 1 s 开始迁移，5 s 完成复制，5.5 s 完成 commit／reader drain 才释放 DRAM；target 不能冒充物理释放。右图显示 sum-of-local-penalties 与共同故障的 join delay 不相同。二者都是构造例子，不是并发正确性测试。

![控制器规模](figures/preview/controller-scaling.png)

控制器图预留 E9 的 decision-time 坐标。当前按两遍 DAG、八个 episode、每 node visit 0.2 μs 的**假设**计算，不是 CPU benchmark；测量时替换为相同规模／candidate budget 下的实际 latency。它保留了控制成本可能很高的情况。

### 4.5 实验顺序和可推翻条件

| 实验 | 主要问题 | 必须保留的对照或失败 |
|---|---|---|
| E0 | manifest／lease／模型恢复是否正确 | pending、stale epoch、last copy、full storage、reader race |
| E1 | 端到端故障 WCT | 每策略 healthy mate；共同 worker 故障；间接受影响工作流 |
| E2 | 有限 DRAM／存储价值 | 0 DRAM、all-fit、backing exhaustion |
| E3 | 恢复分解与共享资源 | 优化流水线、实际带宽、队列与 overlap |
| E4 | DAG／reuse／migration 的贡献 | 相同基底、非零 oracle regret、正常服务退化 |
| E5 | 预测鲁棒性 | causal split、偏差、未知 DAG、弱或负面结果 |
| E6 | Z、阶段和实际 lag | 相同 ID/逻辑进度、N>Z、复制期间故障 |
| E7 | 无故障成本与多轮复用 | 原始 DAG 一遍、完整 prompt 分母、SLO 与命中单位 |
| E8 | 动态压力和迁移安全 | target≠free、writeback backlog、退化／饥饿 |
| E9 | 控制器及规模 | 决策 CPU 成本、有限工作预算、unsupported topology |

主实验先按独立 campaign 配对，各策略保持同一 workload／arrival／logical fault，记录随机运行顺序；先在每个 campaign 内聚合，再 bootstrap campaign。10 个 seed 不会把相同的工作流变成新的独立任务。超时和失败保留完成率及共同时间窗分析，不能只删去不完成的样本。

## 5. Related Work

DéjàVu、GhostServe 和 RaidServe 已分别研究 KV 复制／编码及 TP 故障恢复；LUMEN 已研究 load-aware checkpoint 与恢复分配。Mooncake、CachedAttention、Strata 和 HCache 已研究分层复用、传算重叠、存储布局或其他状态表示。Parrot、KVFlow、Pythia、Cortex 与 TOPAS 已使用工作流信息优化正常执行。特别是 TOPAS 已结合 remaining service path、reuse 和 movement cost，因此“Slack 加缓存”不足以支持新颖性。

本稿把拟议差异限定为：共同故障域对多个请求的联合影响，正常复用与恢复保护共存，DRAM demotion 与 last-copy deletion 的不同后果，以及异步迁移时有效 checkpoint 的保持。完整原始来源和对应实验要求见 [RELATED_WORK.md](../experiments/eurosys27/RELATED_WORK.md)。这些差异需要实现与消融证明，而非由命名或架构图自动成立。

## 6. Conclusion

AegisKV 将 KV 保护视为有限 DRAM 与存储中的在线工作流资源管理。它保留普通复用，按依赖评估共同故障，并将期望放置与实际提交状态分开。理论分析给出了可能有价值的区域和明确限制：DRAM 容量充裕、storage 较快、预测偏差或共享队列都可能使收益变小。新版完整论文、模型与图像已经形成可复算的研究草稿；能否成为有竞争力的 EuroSys 系统论文，仍取决于协议实现、强基线和真实配对实验。
