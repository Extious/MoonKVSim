# AegisKV：面向工作流的 DRAM／存储 KV 检查点管理

英文完整稿与编译入口为 [main.tex](main.tex)，当前 PDF 为 [main.pdf](main.pdf)。本稿对应 2026-09-20 用户确认的 **共享 DRAM＋SSD／共享存储** 方案：删除专用 Peer HBM 及其 L/K/容量控制，保留正常推理所需的 GPU HBM。新增 Evaluation 图均为明确标注的理论分析；它们没有证明新版系统已经实现或取得实测加速。

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

Figure 1(c) 保留 Motivation 对话的实测证据：Qwen2.5-7B-Instruct-1M、两张 A100 PCIe 40 GB、TP2/BF16、batch=1、支持的 MInference/DCA 配置。总上下文 C=M+1；reuse 从相同历史 KV 开始，完成相同的最后一个 token；full prefill 从空 KV 开始，包含同一最终边界。DRAM 采用完整历史 H2D 串行恢复，不与计算重叠。

当前三路径在 1,010,000 tokens 的结果是 HBM reuse 1.266 s、串行 DRAM reuse 2.517 s、稀疏 full prefill 565.93 s。reuse 每点三次计时，full prefill 每长度一次，不能当作跨任务统计置信度。HBM 曲线是已经驻留的状态参考，不是恢复 Peer HBM 设计；本图没有注入系统故障，也不能代替 WCT、有限 DRAM 或优化流水线实验。共享文件系统结果如由 Motivation 任务补入，必须使用实际后端和缓存状态标签。

### 2.4 故障位置改变保护收益

![恢复成本与工作流损失](figures/preview/recovery-exposure.png)

Figure 2 在同一例子的四个分支上分别构造独立故障反事实。A1 的恢复成本可以被其余量吸收，A2 的较短恢复却全部暴露。这里采用静态重建成本、固定其他执行和队列；不是同时四分支故障实验。它引出工作流价值，而共同 worker 故障及其资源竞争需要在新版 Evaluation 中另外验证。

## 3. AegisKV Design

### 3.1 Design Insights

第一，恢复时间相同不意味着 WCT 损失相同；共同故障下还不能把各请求的孤立损失简单相加。两条关键分支各需 10 s，仅把一条减到 2 s，join 仍延后 10 s。

第二，DRAM 降到存储通常增加读取等待，删除最后副本可能触发完整重算。大 Slack Agent 仍应保留普通复用机会，避免每轮请求重建历史。

第三，期望放置不等于可恢复状态。只有依赖完整且已经提交的检查点可以用于恢复；只有替代副本提交、目录切换和旧 reader 退出后，原内存才真正可释放。

### 3.2 System Overview

![DRAM 与存储的新架构](figures/preview/storage-overview.png)

Figure 3 的应用层提交 DAG/进度；Tracker 提供时间估计，KV Master 决策保留／降级／删除；Router 和存活目录连接推理 replicas 与共享存储。两个 DP 对称地具有正常执行 KV、Adapter 和 I/O Connector。没有专用 Peer HBM。新架构的 [Draw.io 源](../exports/eurosys-complete-20260920/storage-overview.drawio) 保持可编辑。

物理对象按 layer/token block 存放，包含该层全部 KV heads 的本地 shard。对象身份绑定模型／权重／位置编码／layout／精度／prefix／token 区间。一个 checkpoint group 包含恢复所需的完整依赖集合；共享对象物理字节只计一次，价值必须考虑所有受影响的 owner。稀疏模型还需恢复 selector 状态，放置策略不更改原生注意力选择。

### 3.3 Workflow Tracker

Tracker 在不重复计算父 Agent 等待的 residual DAG 上，用 GBDT 直接预测剩余 segment 时长，再以 CPM 求最早／最晚完成时间与 Slack。输入仅包括当前可见角色、模型、已消耗时间、prompt 和已完成调用的信息。训练／测试按完整工作流和时间分离。未知未来分支、缺失映射或无效预测触发零 Slack／请求成本 fallback；同一 segment 的多请求不能各自独立花掉同一份余量。

### 3.4 Recovery-aware Router

正常路由考虑兼容 prefix 和负载，故障后先 fencing 再选择健康、layout 兼容、有真实执行空间的目标。共享 backing 允许依据当前负载调整目标。token 在确认给用户前进入存活的顺序日志，旧 epoch 的复制或输出不能重新生效；重试重建已确认 suffix 并抑制重复输出。外部工具副作用仍依赖 orchestrator 的幂等协议。

### 3.5 KV Master

**价值估计。** 对候选 placement P′，比较迁移造成的前台延迟 A，以及各种正常 next-use／故障 episode 下工作流完成时间的变化：

`ΔJ(P′|P) = A(P′,P) + Σ_e p_e Σ_w [T_w(P′,e) − T_w(P,e)]`。

所有项为秒；概率不能直接用每秒故障率代替。同一 source 故障同时作用于其所有请求，再通过 DAG 和共享资源 profile 求 WCT。DRAM demotion 与 storage deletion 使用不同替代路径，shared block 的完整收益不能重复授给每一个物理块。

**在线计划。** 新封存状态默认尝试进入有限共享缓存，Slack 不取消其资格。固定 Z 与请求／DAG／负载事件触发 review，review 可以完全不迁移。在压力下，按可释放字节的边际损失选择合法降级，选择后重新估值；将新 admission 与完整 victim／writeback 方案一起比较。可选变化需超过 uncertainty 与 hysteresis 门槛。无合法受害者时拒绝／合并新写入，保留旧有效 frontier。当前版本采用直接重估；租金只是相同价值模型下的可选维护机制，未声称继承 Landlord 的竞争比。

**提交协议。** `copy → verify → commit → redirect → drain → free`。一个 manifest 只有覆盖全部 layers、TP shards、token 区间、selector 状态和 token-log 前缀才发布。partial copy 不推进 frontier；未提交新版本不影响旧版本可用性。storage 的 commit 要符合声明故障模型，不能把 buffered write 返回一律等同介质持久化。删除最后副本必须先撤销其保护承诺或确认替代状态。

### 3.6 Adapter / Connector

逐层记录 committed、reserved、retiring、staging 与真正 free 的字节。容量 target 收缩时允许物理占用暂时超出 target，但不可据此假报已释放空间。前台读取、demand restore 与必要 writeback 各有正服务份额和有限队列；字节公平调度避免一个长上下文垄断路径。带宽上限不是延迟上限。GPU 恢复仍需保留 workspace 和 TP collective 一致性；只有后端合法的 kernel 边界才能推进或暂停。

这些是待实现和验证的协议约束，并非“已经完成新版端到端系统”的声明。

## 4. Evaluation

详细执行矩阵、日志字段、配对统计和失败处理见 [PROTOCOL.md](../experiments/eurosys27/PROTOCOL.md)。当前理论模型的全部假设见 [THEORY.md](../experiments/eurosys27/THEORY.md)。以下图形的布局已固定，实测时通过 [数据契约](../experiments/eurosys27/DATA_CONTRACT.md) 填入数据，不修改图像坐标代码。

### 4.1 统计口径与模型

主指标为同策略的 `fault WCT − healthy WCT`；策略间再进行配对比较。同时报告正常／故障绝对 WCT、完成率、TTFT、token delay、SLO goodput、I/O／迁移字节、checkpoint lag、重算量和控制器开销。包括直接中断及共享资源受影响的工作流。

理论模型包含四个 4/8/12/16 GiB checkpoint group、16 GiB DRAM、有限的 160 GiB backing；采用声明的 DRAM／storage／network／H2D 速率，并以 event calendar 模拟有依赖的分块传输。三个状态规模、四个 Slack 倍率与三个 storage 带宽组成 36 个确定性配置。它不是实测 repeat，也不执行原生模型、GBDT 或异步 Controller；不画虚构置信区间。

### 4.2 工作流收益和容量边界

![工作流损失](figures/preview/workflow-outcomes.png)
![容量曲线](figures/preview/capacity-frontier.png)

Figure 4：AegisKV 静态放置模型在 17 个配置优于 LRU，19 个持平；均值为 9.518 与 10.892 s。该网格不代表生产负载概率分布。可行枚举 oracle 的均值为 9.386 s，贪心方案存在非零目标 regret；不能称为最优解。当前 LRU 和 reuse-only 因假设排序相同而重合。容量为零及全部状态可放入 DRAM 时，策略应收敛，这是必须保留的负对照。

### 4.3 Storage、checkpoint lag 和预测误差

![存储带宽](figures/preview/storage-bottleneck.png)
![提交落后](figures/preview/checkpoint-lag.png)

Figure 5：storage 变快可能缩小 DRAM placement 的价值；链路或计算仍可能成为共同瓶颈。Z 只是 review 间隔，未提交 tail 可以因 backlog 超过 Z。理想模型枚举 N=0..Z−1；真实故障必须按相同 ID 和逻辑进度匹配，以实际 frontier 计算 tail。SSD 与共享文件系统分开测量。

![预测扰动](figures/preview/prediction-robustness.png)
![正常 I/O 干扰](figures/preview/healthy-io.png)

Figure 6：时长扰动图使用真实时长计算 outcome，仅扰动 placement 输入，它不是 GBDT accuracy CDF。I/O 图采用另一个 M/D/1 模型，说明利用率升高后排队非线性放大；它不是系统 TTFT 测量。实测需分别报告 duration error、false-positive Slack、fallback、decision regret 与正常服务成本。

### 4.4 消融与安全迁移

![消融](figures/preview/policy-ablation.png)

Figure 7 分别去掉依赖和正常复用价值，并同时呈现故障损失与下次调用 restore 时间。当前理论数据保留了偏重故障时正常复用等待增加的权衡。需要与相同 I/O、相同容量、相同 failure routing 的强基线比较，不能只靠对比 Recompute 证明新策略。

![安全降级](figures/preview/safe-demotion.png)
![共同故障](figures/preview/common-fault.png)

Figure 8 左图中，8 GiB 在 1 s 开始迁移，5 s 完成复制，5.5 s 完成 commit／reader drain 才释放 DRAM；target 不能冒充物理释放。右图显示 sum-of-local-penalties 与共同故障的 join delay 不相同。二者都是构造例子，不是并发正确性测试。

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
