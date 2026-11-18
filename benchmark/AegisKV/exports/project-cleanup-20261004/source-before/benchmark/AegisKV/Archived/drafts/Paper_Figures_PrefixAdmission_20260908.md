# AegisKV：论文图与叙述

[旧图归档](Old_Figures.md) · [逐图修改与获奖论文参考](PAPER_FIGURE_REVIEW.md) · [独立图 LaTeX](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-figures.tex) · [并排插图 LaTeX](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-pairs.tex) · [排版预览](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-placement.pdf)

本文围绕一个问题展开：**怎样用有限 KV 保护资源减少工作流的故障损失，同时控制正常推理的代价？** Motivation 界定价值与成本，System Design 说明对象和状态，Evaluation 检查收益与代价是否实际出现。相邻图按同一问题并排；所有文件仍是独立矢量图，供论文分别编号和组合。单栏 3.33 inch，通栏 7 inch。

## Motivation

### 工作流依赖使保护价值不均等，而副本成本始终存在

图 M1、M2 分别呈现保护价值和资源成本这两个方面。真实 trace 中，并行分支的持续时间存在差异，提示恢复工作可能被其他分支吸收；这是观测动机，尚不能把持续时间差直接当作可消费的因果 Slack。另一方面，Qwen3-8B 在 96 Ki tokens 下保留两份 BF16 KV 就需要 27 GiB，保护会占用正式推理也需要的资源。

<a id="paper-motivation-branch-gap"></a>
<a id="paper-motivation-kv-capacity"></a>

| **图 M1：并行分支的时间差** | **图 M2：额外 KV 副本的容量代价** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/motivation-branch-gap.png" width="480" alt="M1 并行分支的时间差">](../../../output/pdf/aegiskv-paper-story-20260908/motivation-branch-gap.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/motivation-kv-capacity.png" width="480" alt="M2 额外 KV 副本的容量代价">](../../../output/pdf/aegiskv-paper-story-20260908/motivation-kv-capacity.pdf) |
| 124 个存在观测重叠分支的真实工作流，每个样本取工作流内最大分支持续时间差；横轴为对数秒。持续时间差尚未验证为因果 CPM Slack。 | Qwen3-8B BF16 按 147,456 B/token 计算；96 Ki tokens 的一份/两份 KV 为 13.5/27 GiB。灰线从 40 GiB 扣权重及 2 GiB runtime，未扣动态前台 KV。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/motivation-branch-gap.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/motivation-branch-gap.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/motivation-branch-gap.csv) · trace 观测 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/motivation-kv-capacity.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/motivation-kv-capacity.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/motivation-kv-capacity.csv) · 解析推导 |

这形成了设计的两个要求：保护策略需要知道一个前缀对后续工作流有多大价值；每一次复制、保留和回收还必须服从容量与传输约束。固定 DAG 的简化关系为 `暴露延迟 = max(恢复延迟 − Slack, 0)`，其具体依赖和时间安排在图 S2 中展开。

## System Design

### 以共享 KV 对象连接工作流和存储资源

图 S1 将工作流依赖、控制状态和物理 KV 缓冲区放在同一张图中。Source 对 Peer HBM 与 Store DRAM 分别复制，两个 tier 分别维护提交前缀；Peer 上的备份空间与正式推理 primary 空间相互区分。控制器中的 Slack ticket、共享对象引用、tier frontier 和资源许可分别回答价值、身份、可恢复范围和执行条件。

<a id="paper-system-overview"></a>

**图 S1｜保护路径与资源所有权。** 工作流依赖对应版本化控制状态；Source 分别写 Peer HBM 与 Store DRAM。图中画出 primary、backup、共享消费者和独立复制路径；恢复时备份仍需装入 primary 空间。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/system-overview.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/system-overview.svg) · [可编辑源](../../../output/pdf/aegiskv-paper-story-20260908/system-overview.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/system-overview.png" width="1008" alt="S1 保护路径与资源所有权">](../../../output/pdf/aegiskv-paper-story-20260908/system-overview.pdf)

### Algorithm 1：用具体依赖计算可消费的时间余量

图 S2 使用同起点的两条分支：A 需要 3 s，B 需要 8 s，汇合由 B 决定。A 的最晚开始时间比最早开始时间晚 5 s；扣除 1 s 保守余量后，得到 4 s 的 ticket。这个例子把 DAG、时间线和 ticket 对应起来。ticket 还绑定消费者、DAG 版本和有效期，信息缺失或失效时回退为零。完整设计需要剩余时间预测器；后文模拟使用理想 trace duration，不验证 GBDT 准确率。

<a id="paper-motivation-exposed-recovery"></a>

<a id="paper-design-slack-tickets"></a>

**图 S2｜一个 DAG 中的 Slack 与保守 ticket。** 同起点的 A/B 分支分别执行 3/8 s，在 8 s 汇合。A 的结构 Slack 为 5 s，扣 1 s 保守余量后 ticket 为 4 s；B 为零。epoch=7 和所有时长均为设计示例。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/design-slack-tickets.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/design-slack-tickets.svg) · [可编辑源](../../../output/pdf/aegiskv-paper-story-20260908/design-slack-tickets.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/design-slack-tickets.png" width="1008" alt="S2 一个 DAG 中的 Slack 与保守 ticket">](../../../output/pdf/aegiskv-paper-story-20260908/design-slack-tickets.pdf)

### Algorithm 2：物理容量只计一次，删除损失覆盖全部引用

图 S3 中，A/B 各引用三个 chunk，但 C0/C1 是同一组物理对象。删除 C1 时，必须连同 C2-A/C2-B 一起删除，才能保持前缀连续；释放的是 3b 物理字节，两个 consumer 各损失 2b 的可复用前缀。这个差别决定了准入不能简单按逻辑引用大小收费，也不能只看被选中 chunk 自身的价值。

tier 内的预计损失使用 `Σ wᵢ·max(Tᵢ − Slackᵢ, 0)`。新候选从第一缺口形成连续组；stage、复制 ACK 复核和原子替换完成之后，才切换保护集合。复制失败时保留原集合。

<a id="paper-design-shared-prefix"></a>

**图 S3｜共享前缀的物理容量与联合删除损失。** A/B 各引用三个等长 chunk，其中 C0/C1 共享；六次逻辑引用对应 4b 物理字节。删除 C1 的后代闭包释放 3b，而两个 consumer 各损失 2b 可复用前缀；b 为一个 chunk 的字节数。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/design-shared-prefix.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/design-shared-prefix.svg) · [可编辑源](../../../output/pdf/aegiskv-paper-story-20260908/design-shared-prefix.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/design-shared-prefix.png" width="1008" alt="S3 共享前缀的物理容量与联合删除损失">](../../../output/pdf/aegiskv-paper-story-20260908/design-shared-prefix.pdf)

### Algorithm 3：上限收缩之后，仍要等待物理释放

图 S4 将同一个 40 GiB 包络画成三个状态。primary 新增 4 GiB 需求时，允许借给 Peer 的容量从 6 降至 2 GiB；但撤销命令并没有让已经占用的 4 GiB 立即消失。只有收到 free ACK，账本和新的分配才能使用这部分空间。图中的显存数值用于解释机制。

复制还要获得源、目标和链路许可，并持有有效 QoS 证书；配额增长需要稳定余量、实际需求和已完成回收。后文主实验使用容量受限的 Peer 探索模式，完整 ForegroundBudget 的证书行为仍需独立验证。

<a id="paper-design-foreground-budget"></a>

**图 S4｜显存包络收缩与 free ACK 前的计账。** 40 GiB 示意包络：固定占用 16、primary 12、前台预留 6、Peer 6。primary 新增 4 GiB 使 Peer 上限降至 2；撤销后仍按 6 计账，收到 free ACK 后才降至 2。示意数值不代表实测 allocator 轨迹。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/design-foreground-budget.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/design-foreground-budget.svg) · [可编辑源](../../../output/pdf/aegiskv-paper-story-20260908/design-foreground-budget.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/design-foreground-budget.png" width="1008" alt="S4 显存包络收缩与 free ACK 前的计账">](../../../output/pdf/aegiskv-paper-story-20260908/design-foreground-budget.pdf)

### 用同一组 chunk 解释提交、故障和恢复

图 S5 连续追踪同一个 C1：Peer ACK 已到，而 DRAM 仍 pending 时 Source 故障，因此两个 tier 留下不同的可恢复前缀。下方的内存快照和恢复路径继续使用 C0/C1/C2，使提交状态、实际恢复内容与后缀重算直接对应。前缀装入只是一个里程碑；完整恢复还包括后缀计算、GPU 排队与解码恢复。Evaluation 使用相同的两个阶段计时。

<a id="paper-commit-recoverable-prefix"></a>
<a id="paper-commit-materialize-recompute"></a>

<a id="paper-commit-tier-timeline"></a>

**图 S5｜从独立提交到故障后的前缀装入。** 同一 C1 的 Peer ACK 先于源故障，DRAM pending 随后 abort；故障时 Peer 可恢复 C0–C1，DRAM 仅 C0。备份装入新 primary 后仍需重算 C2 才恢复解码。时间线表示逻辑次序，全部 chunk 为示意。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/commit-tier-timeline.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/commit-tier-timeline.svg) · [可编辑源](../../../output/pdf/aegiskv-paper-story-20260908/commit-tier-timeline.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/commit-tier-timeline.png" width="1008" alt="S5 从独立提交到故障后的前缀装入">](../../../output/pdf/aegiskv-paper-story-20260908/commit-tier-timeline.pdf)

## Evaluation

### 实验对象与比较口径

Evaluation 依次回答四个问题：保护是否改变正常服务；变化来自缓存、排队还是控制与传输；故障恢复是否减少 Workflow 损失；结论能否跨配置成立。

| 项目 | 本文图使用的配置与范围 |
|---|---|
| 比较系统 | **Mooncake**：独立 LRU Store 模型；**DRAM-only AegisKV**：PrefixAdmission、禁用 Peer；**AegisKV**：同一 DRAM 策略、启用受容量包络约束的 Peer 探索 |
| 模型与资源 | Qwen3-8B BF16；DP8/TP1/PP1；8×40 GiB；chunk=4,096 tokens；默认 DRAM=1 TB、共享路径=25 GB/s、活跃 Workflow=16 |
| 原始输入 | 冻结 FanOutQA 派生的 160 个 Workflow、1,304 个请求；所有系统共享相同精确 token、DAG 和入场次序 |
| 无故障复用压力 | 每个 Workflow 完整 DAG 执行两轮，第二轮精确重访；共 2,608 个请求，属于受控 synthetic 压力测试，不是观测到的用户重访分布 |
| 配对与重复 | 每配置每系统执行一次；160 个 Workflow 是配对对象，不是 160 次独立重复；不绘制跨重复置信区间；图间复用运行不重复计数 |
| Workflow 横轴 | [ID 映射 CSV](../../../output/pdf/aegiskv-paper-story-20260908/workflow-order.csv) 固定按无故障重访 Mooncake WCT 排序，所有逐 Workflow 图共用；连线仅连接对象 |
| 测量范围 | source-v6 的原矩阵加 source-v7 的独立故障补跑；v7 只改变 runner 的故障选点，核心模拟代码哈希相同。GPU 时序未标定；CPU 为固定服务报价模型；未模拟 kernel 与 DMA 的硬件 HBM 带宽竞争 |

因此，这部分支持的是**在明确假设下的机制分析**。Mooncake 曲线不是原生 Mooncake 服务测量，AegisKV 曲线也不是完整 Algorithm 3 已认证的性能。参数、计量分母和资源模型见 [实验协议](THREE_SYSTEM_PROTOCOL.md)；补跑规则见 [故障补跑协议](PAPER_FAILURE_PROTOCOL.md)。

图 E1、E2 先界定输入的长度和 DAG 规模。原始一次访问条件的 DRAM 正常命中为零，三系统平均 WCT 均约 39.066 s；用这一个条件宣称保护“没有开销”缺乏复用压力。因此后面的正常服务主分析使用两轮受控重访，同时保留原始访问作为故障实验的 matched F0。

<a id="paper-workload-prompt_tokens"></a>
<a id="paper-workload-workflow_call_counts"></a>

| **图 E1：原始输入的 Prompt 分布** | **图 E2：Workflow 规模分布** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/workload-prompt_tokens.png" width="480" alt="E1 原始输入的 Prompt 分布">](../../../output/pdf/aegiskv-paper-story-20260908/workload-prompt_tokens.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/workload-workflow_call_counts.png" width="480" alt="E2 Workflow 规模分布">](../../../output/pdf/aegiskv-paper-story-20260908/workload-workflow_call_counts.pdf) |
| 冻结 FanOutQA 派生输入的 1,304 个请求；Ki=1,024 tokens。仅含原始访问，总上下文最大 86,214 tokens，未宣称覆盖 128K。 | 同一输入中 160 个 Workflow 的原始调用数分布，最大为 27；样本单位是 Workflow，两轮重访不混入这张输入统计图。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/workload-prompt_tokens.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/workload-prompt_tokens.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/workload-prompt_tokens.csv) · 输入统计 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/workload-workflow_call_counts.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/workload-workflow_call_counts.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/workload-workflow_call_counts.csv) · 输入统计 |

### 正常服务：从总体变化追踪到缓存复用

图 E3 给出同一配置、同一批 Workflow 的三条 WCT 曲线；图 E4 保留逐对象的增减，图 E5 展示整体分布。25 GB/s 条件下，平均 WCT 从 Mooncake 的 53.39 s 增加到 DRAM-only 的 64.05 s 和 AegisKV 的 69.74 s。AegisKV 相对 Mooncake 增加约 30.6%，且 129/160 个 Workflow 更慢。后面的分解需要解释这一不利结果。

<a id="paper-f0-revisit-wct"></a>

**图 E3｜逐 Workflow 的 WCT。** 无故障两轮重访，160 个 Workflow 严格配对；按 Mooncake WCT 统一排序。均值依次为 53.39/64.05/69.74 s；WCT 不含活跃 slot 外的入场等待。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct.png" width="1008" alt="E3 逐 Workflow 的 WCT">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct.pdf)

<a id="paper-f0-revisit-wct-difference"></a>

**图 E4｜逐 Workflow 的 WCT 增减。** 图 E3 的逐对象差值：各系统 WCT 减 Mooncake WCT；正值更慢，负值更快。AegisKV 有 129/160 个 Workflow 更慢；不按正负筛选样本。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-difference.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-difference.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-difference.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-difference.png" width="1008" alt="E4 逐 Workflow 的 WCT 增减">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-difference.pdf)

整体分布与缓存组成放在同一行：左图显示完成时间的整体变化，右图显示实际复用 token 来自哪里；后面的逐 Workflow 命中图再定位差异。

<a id="paper-f0-revisit-wct-cdf"></a>
<a id="paper-f0-revisit-cache-sources"></a>

| **图 E5：WCT 的整体分布** | **图 E6：正常服务的缓存来源分解** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-cdf.png" width="480" alt="E5 WCT 的整体分布">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-cdf.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-cache-sources.png" width="480" alt="E6 正常服务的缓存来源分解">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-cache-sources.pdf) |
| 图 E3 中全部 160 个 Workflow 的经验分布；保留完整尾部。这里的分布描述同一次执行中的异质工作流，不提供跨独立重复置信区间。 | 对全部 prompt token 做互斥分解：Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。本配置正常请求的 Peer 命中为零；Peer 备份字节不算正常复用收益。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-cdf.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-cdf.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-wct-cdf.csv) · 机制模拟 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-cache-sources.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-cache-sources.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-cache-sources.csv) · 机制模拟 |

首先检查准入是否改变正常 KV reuse。图 E7 显示 DRAM 的 token 命中贡献从 48.08% 降至 26.54% 和 18.89%。图 E6 将所有 prompt token 分解成互斥来源，避免将备份流量、请求命中比例与实际复用 token 混为一谈。当前保护准入目标并没有同时保住 Mooncake 的正常 DRAM 复用水平；两轮分母也解释了为什么第二轮大量命中时总体比例仍接近 50%。

<a id="paper-f0-revisit-dram-hit"></a>

**图 E7｜准入改变后的 DRAM 复用率。** 正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问与第二轮访问。总体 token 加权比例为 48.08%/26.54%/18.89%，不是请求命中比例。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-dram-hit.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-dram-hit.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-dram-hit.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-dram-hit.png" width="1008" alt="E7 准入改变后的 DRAM 复用率">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-dram-hit.pdf)

### 前台干扰：分别检查 GPU 排队、显存等待与服务尾部

Peer HBM 是否伤害正式推理，不能只看一个 HBM 占用率。图 E8 的纯 GPU 排队变长，而图 E9 的 GET 目标 HBM 等待反而减少；图 E10 再检查全部 8 个 GPU 的低空闲 HBM 时间比例。由于正常命中和 GET 数量也改变，这些结果描述的是各系统整体运行状态，不能把差值直接解释成 Peer 的单独因果作用。

<a id="paper-f0-revisit-scheduler-queue"></a>

**图 E8｜前台 GPU 调度排队。** 点为 Workflow 内请求首次实际入 GPU 队列到首次计算的平均等待；CPU、GET 和 HBM 申请等待另计。请求级 P95 依次为 9.48/13.15/16.72 s，不能把点误读为 P95。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-scheduler-queue.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-scheduler-queue.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-scheduler-queue.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-scheduler-queue.png" width="1008" alt="E8 前台 GPU 调度排队">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-scheduler-queue.pdf)

<a id="paper-f0-revisit-hbm-wait"></a>

**图 E9｜GET 目标 HBM 的申请等待。** 逐 Workflow 的请求平均 HBM 申请等待。跨请求累计为 414.33/63.42/4.15 s；方向与 GPU 排队不同，GET 样本量也随命中率变化，不能独立归因为 Peer。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-wait.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-wait.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-wait.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-wait.png" width="1008" alt="E9 GET 目标 HBM 的申请等待">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-wait.pdf)

<a id="paper-f0-revisit-hbm-pressure"></a>

**图 E10｜全部 GPU 的显存占用压力。** 按事件区间积分，统计每个 GPU 未分配 HBM 低于 1 GiB 的时间比例。包括可回收缓存占用，分母为各系统自身 workload makespan；不是硬件 HBM 带宽利用率。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-pressure.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-pressure.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-pressure.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-pressure.png" width="1008" alt="E10 全部 GPU 的显存占用压力">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-hbm-pressure.pdf)

图 E11、E12 将资源状态连接到前台可见时延：AegisKV 的 P99 TTFT 更长，但请求平均 TPOT 的极端尾部小于 Mooncake。这两个指标方向不同，说明平均 WCT、首 token 和持续输出体验不能相互替代。TPOT 使用请求内平均值，尚不足以验证逐 token 的停顿上界。

<a id="paper-f0-revisit-ttft-cdf"></a>
<a id="paper-f0-revisit-tpot-tail"></a>

| **图 E11：首 token 延迟分布** | **图 E12：请求平均 TPOT 的长尾** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-ttft-cdf.png" width="480" alt="E11 首 token 延迟分布">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-ttft-cdf.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-tpot-tail.png" width="480" alt="E12 请求平均 TPOT 的长尾">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-tpot-tail.pdf) |
| 全部 2,608 个请求的 TTFT，横轴用对数秒以同时显示主体与完整尾部。P99 为 21.68/22.20/27.87 s；没有据此宣称满足原生 QoS 阈值。 | 每系统 2,432 个 TPOT 有定义的请求；双对数生存曲线给出不小于横轴值的请求比例。每个请求先求平均 TPOT，不能当成逐 token 间隔分布。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-ttft-cdf.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-ttft-cdf.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-ttft-cdf.csv) · 机制模拟 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-tpot-tail.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-tpot-tail.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-tpot-tail.csv) · 机制模拟 |

### 控制与传输：先量化新增工作，再检查前台争用

图 E13 按 Workflow 配对比较控制面 CPU 服务需求。图 E14、E15 并排呈现两类可加总的代价：控制服务需求从 2.58 s 增至 5.44 s 和 6.05 s，Peer 还引入约 5,059.6 GiB 的复制。这两幅图共用系统顺序，纹理区分工作类型；CPU 数值是固定报价形成的服务需求，不是原生 CPU 利用率。

<a id="paper-f0-revisit-controller-service-difference"></a>

**图 E13｜逐 Workflow 的控制面代价。** 查询与准入的模型服务需求减 Mooncake 对应值；按相同 Workflow 配对。CPU 报价固定，前台查询 50 µs 为假设，不是原生 CPU 利用率。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-service-difference.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-service-difference.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-service-difference.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-service-difference.png" width="1008" alt="E13 逐 Workflow 的控制面代价">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-service-difference.pdf)

<a id="paper-f0-revisit-controller-breakdown"></a>
<a id="paper-f0-revisit-traffic-breakdown"></a>

| **图 E14：控制面服务需求的组成** | **图 E15：前台读取与后台复制的组成** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-breakdown.png" width="480" alt="E14 控制面服务需求的组成">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-breakdown.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-traffic-breakdown.png" width="480" alt="E15 前台读取与后台复制的组成">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-traffic-breakdown.pdf) |
| 按事件将前台查询与准入服务时间求和，总量为 2.58/5.44/6.05 s。该和不含排队，也不等于请求延迟或 CPU 使用百分比。 | 由实际传输记录互斥分解为正常 GET、DRAM 写入和 Peer 复制，含已传输的中止部分与收尾；TiB=2^40 bytes。Peer 开启后 DRAM 流量本身也会改变。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-breakdown.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-controller-breakdown.csv) · 机制模拟 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-traffic-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-traffic-breakdown.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-traffic-breakdown.csv) · 机制模拟 |

图 E16、E17 再按相同 Workflow 顺序显示后台总流量与 Peer 分项，避免用两系统总流量相减推测 Peer 流量。图 E18 衡量成功 GET 的共享路径减速；三系统的 GET 样本组成也会变化，因此这些分解描述整体执行状态，不能独立估计 Peer 的净因果效应。

<a id="paper-f0-revisit-background-copy"></a>

**图 E16｜逐 Workflow 的后台传输量。** DRAM 写入与 Peer 复制的实际传输字节，含中止前已传部分及收尾阶段；按源请求归属 Workflow 累计。它表示累计流量，不能当作驻留副本容量。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-background-copy.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-background-copy.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-background-copy.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-background-copy.png" width="1008" alt="E16 逐 Workflow 的后台传输量">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-background-copy.pdf)

<a id="paper-f0-revisit-peer-copy"></a>

**图 E17｜新增 Peer 路径的传输成本。** 直接累计 Peer flow 的实际字节。Mooncake 和 DRAM-only 的两条零线重合，因为未启用该路径；不用两个系统的总流量之差估计 Peer 流量。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-peer-copy.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-peer-copy.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-peer-copy.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-peer-copy.png" width="1008" alt="E17 新增 Peer 路径的传输成本">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-peer-copy.pdf)

<a id="paper-f0-revisit-transfer-service_slowdown"></a>

**图 E18｜正常 GET 的链路争用。** GET 数据服务时间 / 相同字节量的独占瓶颈服务时间，不含固定 setup。成功 GET 样本数为 1,284/773/662，P95 为 33.56/10.71/12.65 倍；不是隔离 Peer 效应的因果对照。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-transfer-service_slowdown.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-transfer-service_slowdown.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-transfer-service_slowdown.csv) · 机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-transfer-service_slowdown.png" width="480" alt="E18 正常 GET 的链路争用">](../../../output/pdf/aegiskv-paper-story-20260908/f0-revisit-transfer-service_slowdown.pdf)

### 故障恢复：检查不同工作进度，并回到 Workflow 代价

故障影响随工作流完成进度而变化，因此实验使用三个预定进度位置：在 Mooncake 无故障参考执行中，选择最接近 25%、50%、75% 完成比例、prompt 至少 16 Ki tokens 的请求，再在同一焦点请求的 prefill 60% 处对三系统分别触发逻辑 GPU 故障。事件身份与进度配对，绝对触发时刻和同 GPU 上的其他请求状态可以随系统执行而变化。

补跑包括 **12 次执行**：三个系统各一次无故障对照，加三个故障位置各三个系统；各位置每系统一次，未把不同干预当成独立重复。三组新 F0 的 160 个 WCT 均与原 source-v6 对照完全一致。

| 预定位置 | 参考时已完成 Workflow | Mooncake / DRAM-only / AegisKV 的 P95 配对 WCT 差值 |
|---|---:|---|
| 25% 附近 | 39/160（24.375%） | 24.163 s / 25.606 s / 26.733 s |
| 50% 附近 | 79/160（49.375%） | 22.783 s / 20.261 s / 20.261 s |
| 75% 附近 | 119/160（74.375%） | 8.489 s / 8.487 s / 8.487 s |

这些数值衡量不同故障位置对本输入的影响；同一 GPU 上的其他活跃请求也可能受故障影响。完整选点、实际事件、恢复 token 与阶段时长见 [选点 CSV](../../../output/pdf/aegiskv-paper-story-20260908/failure-focus-plan.csv) 和 [恢复阶段 CSV](../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.csv)。

补跑也没有给出一致的 AegisKV 故障收益：早期位置的 P95 Workflow 差值反而更大；中期位置 DRAM-only 与 AegisKV 几乎相同、均小于 Mooncake；后期三系统近似相同。三个焦点请求中，AegisKV 的前缀装入阶段较短，但装入的保护 token 也更少，后缀重算更长，完整恢复解码均晚于 Mooncake。不能将较短的复制阶段单独写成恢复加速。

图 E19–E21 分别保留三个位置下全部 Workflow 的有符号变化，不能只展示焦点 Workflow 或受益对象。图 E22 对这些配对差值求 P95；越晚注入，分母中故障前已完成的对象越多，跨位置的下降不能单独解释为恢复更容易。图 E23 才缩小到预先选定的焦点请求，分开计算前缀装入和后续恢复解码阶段。前缀复制更快不必然意味着完整 Workflow 恢复更快。

<a id="paper-f1-q25-workflow-penalty"></a>

**图 E19｜25% 进度附近故障的逐 Workflow 影响。** 按无故障基准完成进度选择最接近 25% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f1-q25-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f1-q25-workflow-penalty.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f1-q25-workflow-penalty.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f1-q25-workflow-penalty.png" width="1008" alt="E19 25% 进度附近故障的逐 Workflow 影响">](../../../output/pdf/aegiskv-paper-story-20260908/f1-q25-workflow-penalty.pdf)

<a id="paper-f1-q50-workflow-penalty"></a>

**图 E20｜50% 进度附近故障的逐 Workflow 影响。** 按无故障基准完成进度选择最接近 50% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f1-q50-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f1-q50-workflow-penalty.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f1-q50-workflow-penalty.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f1-q50-workflow-penalty.png" width="1008" alt="E20 50% 进度附近故障的逐 Workflow 影响">](../../../output/pdf/aegiskv-paper-story-20260908/f1-q50-workflow-penalty.pdf)

<a id="paper-f1-q75-workflow-penalty"></a>

**图 E21｜75% 进度附近故障的逐 Workflow 影响。** 按无故障基准完成进度选择最接近 75% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/f1-q75-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/f1-q75-workflow-penalty.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/f1-q75-workflow-penalty.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/f1-q75-workflow-penalty.png" width="1008" alt="E21 75% 进度附近故障的逐 Workflow 影响">](../../../output/pdf/aegiskv-paper-story-20260908/f1-q75-workflow-penalty.pdf)

<a id="paper-failure-progress-p95-penalty"></a>

**图 E22｜故障位置与尾部 WCT 代价。** 三个预定故障位置的逐 Workflow WCT 差值之 P95，横轴为真实基准完成比例。先逐对象求差再求 P95；包含故障前已完成对象，因此跨位置的下降不能直接解释为单次恢复更容易。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/failure-progress-p95-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/failure-progress-p95-penalty.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/failure-progress-p95-penalty.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/failure-progress-p95-penalty.png" width="1008" alt="E22 故障位置与尾部 WCT 代价">](../../../output/pdf/aegiskv-paper-story-20260908/failure-progress-p95-penalty.pdf)

<a id="paper-failure-focal-recovery-phases"></a>

**图 E23｜故障请求恢复的阶段分解。** 每位置仅展示预先选定的焦点请求。前段为故障至连续前缀装入，后段为装入后至恢复解码；分别包括对应等待和实际服务。总长才是焦点请求恢复延迟。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.csv) · 机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.png" width="1008" alt="E23 故障请求恢复的阶段分解">](../../../output/pdf/aegiskv-paper-story-20260908/failure-focal-recovery-phases.pdf)

### 配置敏感性与本文能支持的结论

最后检查结论对资源条件的依赖。图 E24 中，5 GB/s 的平均 WCT 为 150.45/81.00/82.07 s，比较方向与 25 GB/s 不同。图 E25、E26 分别改变并发与 DRAM 容量，限制将单配置结论推广到其他负载的范围。所有连线仅连接实际测试点。

<a id="paper-sensitivity-bandwidth-mean_wct_s"></a>
<a id="paper-sensitivity-concurrency-mean_wct_s"></a>

| **图 E24：带宽改变时的完成时间权衡** | **图 E25：并发压力与 Workflow 完成时间** |
| :--- | :--- |
| [<img src="../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-bandwidth-mean_wct_s.png" width="480" alt="E24 带宽改变时的完成时间权衡">](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-bandwidth-mean_wct_s.pdf) | [<img src="../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-concurrency-mean_wct_s.png" width="480" alt="E25 并发压力与 Workflow 完成时间">](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-concurrency-mean_wct_s.pdf) |
| 5/25/50 GB/s 的实际测试点，线性横轴。其他配置相同，每点每系统一次执行、160 个 Workflow。5 GB/s 均值为 150.45/81.00/82.07 s，比较方向反转。 | 活跃 Workflow 并发 8/16/32，线性横轴，其他条件相同。点为 160 个 Workflow 的平均 WCT；闭环入场时间随先前完成变化，不能作为开放到达率吞吐曲线。 |
| [PDF](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-bandwidth-mean_wct_s.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-bandwidth-mean_wct_s.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-bandwidth-mean_wct_s.csv) · 机制模拟 | [PDF](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-concurrency-mean_wct_s.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-concurrency-mean_wct_s.svg) · [数据](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-concurrency-mean_wct_s.csv) · 机制模拟 |

<a id="paper-sensitivity-dram-capacity-dram_hit_pct"></a>

**图 E26｜DRAM 容量与正常复用率。** 32/128/931.3 GiB 的实际容量，对数横轴（底 2）。token 命中率包含两轮全部 prompt token；C=16、25 GB/s，每点每系统一次执行。

[PDF](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-dram-capacity-dram_hit_pct.pdf) · [SVG](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-dram-capacity-dram_hit_pct.svg) · [图中数据](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-dram-capacity-dram_hit_pct.csv) · 机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-dram-capacity-dram_hit_pct.png" width="480" alt="E26 DRAM 容量与正常复用率">](../../../output/pdf/aegiskv-paper-story-20260908/sensitivity-dram-capacity-dram_hit_pct.pdf)

这组机制结果说明：保护引入的容量与传输工作可能改变正常复用、排队与尾部，方向随资源条件变化。原矩阵的零 Slack 消融没有改变 WCT，严格无证书模式关闭 Peer；零结果仍保留在 [归档](Old_Figures.md#three-system-cross-case)，不能据此宣称 Slack 已带来可测收益，或完整 QoS 目标已满足。

若论文的投稿主张是“完整 AegisKV 在真实部署中以有限正常开销获得稳定故障收益”，仍缺少以下证据。这里保留清晰的实验缺口，不用示意趋势填补结果图：

| 缺少的论文图 | 所需数据及本轮不能替代的部分 |
|---|---|
| 原生三系统正常服务与干扰 | 同硬件、同 trace、开放到达负载及独立重复下的 TTFT、逐 token 延迟、goodput、CPU 利用率、真实 allocator/显存及 DMA 争用；当前 CPU 报价和 DES 不能替代 |
| 完整 Algorithm 3 的有效性 | 有效/失效证书、突发前台压力、配额撤销与真实 free ACK 的对齐轨迹；本轮探索模式不是完整控制器实验 |
| Algorithm 1 与 Slack 价值 | Workflow 隔离的训练/校准/测试集，预测误差与保守覆盖率，以及确实触发不同准入选择的 Slack 消融；理想 duration 与零效应不能证明预测器有效 |
| 故障收益的泛化 | 多个独立 workload、更多预定故障对象与进度、不同故障数/故障域、足够独立重复；三个逻辑位置只补足本输入的受控机制覆盖 |

33 张独立图的来源、旧图映射、获奖论文对照与实际 PDF 检查记录集中在 [逐图审查](PAPER_FIGURE_REVIEW.md)。这份叙述可以支撑明确标明假设的机制分析稿；上述真实部署主张仍需相应实验结果。
