# AegisKV 论文图与证据叙述

[总导航](FIGURES.md) · [逐图审查](PAPER_FIGURE_REVIEW.md) · [旧版与补充图](Old_Figures.md) · [本轮实验协议](AGENT_LEASE_PROTOCOL.md)

本版对应 2026-09-08 修订的 **Agent 子租约 Algorithm 2** 和 **独立 Guarded AIMD Algorithm 3**。正文选入 38 张独立图；另外 13 张新图作为机制细节、敏感性和逐 Workflow 诊断保存。定量图有逐点 CSV，设计图有可编辑 Draw.io，全部提供 PDF/SVG/PNG；互补的单栏图可在 Markdown 同行阅读，LaTeX 仍分别插入。

这些图可用于具有明确证据范围的论文叙述：**观测动机、解析示意、未标定机制模拟和真实 GPU 组件微基准分别标注**。正常服务主结果中 AegisKV 的平均 WCT 为 55.230 s，相对 Mooncake 增加 4.9%；这组数据不支持“保护几乎没有开销”。算法收益需要进一步结合配对故障、消融与原生证据判断。

## Motivation

### 保护目标应落在 Workflow 完成时间上

多 Agent Workflow 的并行分支可能在不同时间完成。图 M1 用观测数据说明这种不均衡，图 M2 则说明无差别复制长上下文会消耗可观显存。动机由两个事实组成：不是所有分支重算都会等量暴露给 Workflow；保存每一份 KV 也不是免费的。观测分支时间差尚不是经过干预验证的可用 Slack，后续设计只使用已知 DAG 和当前恢复状态做联合价值计算。

<a id="paper-motivation-branch-gap"></a>
<a id="paper-motivation-kv-capacity"></a>

| **图 M1：并行分支留下多少时间差** | **图 M2：长上下文副本的容量代价** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/motivation-branch-gap.png" width="480" alt="M1 并行分支留下多少时间差">](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-branch-gap.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/motivation-kv-capacity.png" width="480" alt="M2 长上下文副本的容量代价">](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-kv-capacity.pdf) |
| 124 个具有重叠分支的观测 Workflow，每个对象取最大分支持续时间差；对数秒轴。它说明分支存在不均衡，还不能直接作为可消费的因果 Slack。 | 按 Qwen3-8B BF16 的 147,456 B/token 计算，96 Ki tokens 的一份 / 两份 KV 为 13.5 / 27 GiB。参考线仅扣模型权重和 2 GiB runtime，尚未扣动态前台 KV，不能视为 Peer 配额。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-branch-gap.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-branch-gap.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-branch-gap.csv) · 观测动机 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-kv-capacity.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-kv-capacity.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/motivation-kv-capacity.csv) · 解析计算 · 3.33 inch |

## System Design

### 将价值判断与前台资源约束分开

图 S1 从同一 Source 的 KV 出发，分别画出 Peer HBM 与 Store DRAM 的独立数据路径。Agent/执行分支记录保存当前请求轮号与恢复终点，物理块只计一次容量。Algorithm 2 决定有限备份空间留给哪些块；Algorithm 3 根据目标 GPU 的显存与 forward 预警调整可借上限。AIMD 不读取 Slack、Credit 或 Algorithm 2 队列。

<a id="paper-system-overview"></a>

**图 S1｜数据路径与三个算法的职责。** 同一 Source 分别向 Peer HBM 和 Store DRAM 复制；实线为数据，虚线为控制。Algorithm 2 管理物理块上的 Agent 子租约，Algorithm 3 独立限制目标 GPU 允许借给备份的显存。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/system-overview.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/system-overview.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/system-overview.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/system-overview.png" width="1008" alt="S1 数据路径与三个算法的职责">](../../../output/pdf/aegiskv-agent-lease-20260908/system-overview.pdf)

### Algorithm 2：联合收益、Agent 子租约与完整尾块检查

图 S2 给出可手算的共享块实例。按固定 Agent 顺序加入各分支恢复改善，边际分账之和恰好等于一次联合 DAG WCT 下降，不重复计算同一 Workflow 的收益。新块只评价已产生的 KV；已有块补备份和命中更新保留已经生成后缀的重算成本，不纳入未知未来输出。

<a id="paper-design-joint-wct"></a>

**图 S2｜按联合 Workflow 收益分账。** 同一 DAG 的两条分支共享一个物理块；按固定 Agent 顺序逐个加入恢复改善，WCT 为 12→12→10 ms，分账为 0+2 ms。单个分支的重算下降不等于整个 Workflow 等额缩短。数值为可核算示意。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.png" width="1008" alt="S2 按联合 Workflow 收益分账">](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.pdf)

图 S3 继续展示信用如何跨请求保存。新请求更新 Agent 记录；新轮首次参与竞争时只更新该 Agent 的子租约。同轮刷新不能补回已经消耗的信用。相同名称的并行 Agent 分支按输入 DAG 的固定因果链维护独立记录，避免一个请求完成覆盖另一条仍在执行分支的状态。

<a id="paper-design-agent-subleases"></a>

**图 S3｜信用跨请求保留，按 Agent 新轮更新。** 共享尾块 X 上 A/B 信用为 6/4，竞争尾块 Y 为 2；按物理容量收租后 X 为 4.8/3.2，Y 淘汰。仅 A 进入新轮时 X 变为 6/3.2；同轮命中不能补回已花信用。内部块 R 不参加尾块收租。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.png" width="1008" alt="S3 信用跨请求保留，按 Agent 新轮更新">](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.pdf)

实现只从可释放尾块组成的单一 Q 收租，内部块、被读取块和 pending 复制所需前缀不参与。收租前检查 Q 中每个尾块的版本；惰性优化只跳过版本未变的价值计算。空闲空间允许 G≥0，有淘汰时要求 G>D。试算信用和轮号标记在版本核验后才提交，物理释放完成后才分配目的地。完整的[单块试算状态图](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.pdf)与用户修订的[准入决策图](../docs/drawio/slacklandlord-patent-revised/algorithm-2-admission.drawio)、[命中更新图](../docs/drawio/slacklandlord-patent-revised/algorithm-2-cache-hit.drawio)分别保留。

### Algorithm 3：授权额度与物理占用分别计量

图 S4 以同一个显存布局展示增长、预警退让和容量收缩。C 是扣除前台新增需求与保留量后的硬上限；Q 是允许借用的额度，既不代表新增加的显存，也不等于已经占用的备份。有效监测、持续稳定、实际需求和上一轮调整完成共同决定增长；无效监测撤销授权。50 ms 控制窗口不因每次内存分配而虚增稳定次数。

<a id="paper-design-guarded-aimd"></a>

**图 S4｜独立的显存借用上限控制。** 40 GiB 示意布局明确区分前台、保留量、备份和 FREE。C 是硬上限，Q 是允许借用的额度，均不是实际占用；增长、预警减半和容量裁剪单独展示。实现使用 50 ms 窗口、连续 4 个稳定窗口、每次增 1 GiB、β=0.5。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.png" width="1008" alt="S4 独立的显存借用上限控制">](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.pdf)

### 提交与恢复沿用同一组物理对象

图 S5 说明 Peer ACK 不意味着 DRAM 也已提交，源故障后只能使用各 tier 的连续已提交前缀。前缀装入新 primary 之后，还可能需要后缀重算和 GPU 排队才能恢复解码。因此 Evaluation 同时报告装入与恢复终点，不能仅挑选更短的装入时间。后续复制失败不会复活已经释放的旧块。

<a id="paper-commit-tier-timeline"></a>

**图 S5｜独立提交决定故障后能恢复的前缀。** 同一 C1 的 Peer ACK 已到、DRAM 尚 pending 时 Source 故障，两个 tier 因而留下不同前缀。恢复仍须装入新 primary 并重算缺失后缀；图中间距仅表示逻辑次序。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.png" width="1008" alt="S5 独立提交决定故障后能恢复的前缀">](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.pdf)

## Evaluation

### 比较对象、输入与计量口径

| 项目 | 当前图像使用的配置与范围 |
|---|---|
| 三系统 | Mooncake：共享前缀 LRU DRAM Store 的模拟适配；DRAM-only AegisKV：新 Algorithm 2、关闭 Peer；AegisKV：相同 DRAM 策略，加 Peer 与新 Algorithm 3 |
| 模型与资源 | Qwen3-8B BF16，DP8/TP1/PP1，8×40 GiB，chunk=4,096 tokens；默认 DRAM=1 TB，共享路径=25 GB/s，活跃 Workflow=16 |
| Peer 控制 | 每 GPU 策略硬上限 8 GiB、前台保留 1 GiB；Q 从 0 开始，50 ms 窗口、4 个稳定窗口、每次增 1 GiB、预警减半；C 还扣除下一次前台新增需求，普通可复用缓存不计入可借 FREE |
| 冻结输入 | 160 个 FanOutQA 派生 Workflow、1,304 个原始请求；完整 DAG 做两轮受控精确重访，共 2,608 个请求。三系统共享 token、DAG、入场顺序 |
| 算法与故障绑定 | source-v3 的不可变快照覆盖实现、runner、输入和用户指定决策图；F0 无故障，F1 在预定第一轮长请求的 prefill 60% 处触发一次 GPU 故障，持续 120 s |
| 比较单位 | 每个配置、每个系统执行一次完整输入；主矩阵 47 次、另加预先记录的 30% DMA 扩展 4 次，共 51 次。3 次独立 CPU 报价校准不算主结果重复；跨目录复用同一次执行不重复计数 |
| 配对与顺序 | [固定 Workflow ID 映射](../../../output/pdf/aegiskv-agent-lease-20260908/workflow-order.csv)由 seed 0 Mooncake F0 WCT 确定；seed 1/2 只改变同一批对象的入场顺序，不产生新的独立 Workflow 总体 |
| GPU 时序与 CPU | GPU forward 为既有 observed-trace 模型，未标定为 A100 kernel；DAG 使用 trace 时长估计，不是训练完成的 GBDT。CPU 报价进入准入/派发服务队列；其他参考 CPU 工作量单独测量，尚未全部转成因果延迟 |
| 原生微基准 | Slurm 147489 独占两张 L40S，真实 Qwen3-8B BF16/SDPA；360 个 forward 样本、0 个 OOM，复制方向/额外占用/长度/batch 随机交错；另测每种大小 20 次释放 |

图 E1、E2 界定模型输入，避免以“160 个 Workflow”掩盖请求长度和 DAG 规模。第二轮是受控重访压力，不是观测到的真实用户重访分布。两轮与单轮结果不能直接相减作为故障代价，本版 F1 均使用同一份两轮 F0 对照。

<a id="paper-workload-prompt_tokens"></a>
<a id="paper-workload-workflow_call_counts"></a>

| **图 E1：输入的 Prompt 长度分布** | **图 E2：输入的 Workflow 规模** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.png" width="480" alt="E1 输入的 Prompt 长度分布">](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.png" width="480" alt="E2 输入的 Workflow 规模">](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.pdf) |
| 冻结输入的 1,304 个原始请求；Ki=1,024 tokens。两轮扩展不作为新原始样本。总上下文最大 86,214 tokens，不能据此声称覆盖 128K。 | 160 个原始 Workflow 的调用数分布，最大为 27。样本单位是 Workflow；不是 160 次完整系统运行。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.csv) · 输入统计 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.csv) · 输入统计 · 3.33 inch |

### 正常服务：先报告总效果，再定位原因

图 E3 在同一配置下直接比较三条逐 Workflow 曲线，图 E4 展示配对差值。全体均值如下；相同对象之间会因缓存和调度重排而出现正负变化，因此既保留尖峰，也保留更快的对象。

| 系统 | 平均 WCT (s) | DRAM token 命中率 (%) | P99 TTFT (s) | 比 Mooncake 更慢的 Workflow |
|---|---|---|---|---|
| Mooncake | 52.642 | 47.13 | 23.202 | 0/160 |
| DRAM-only AegisKV | 54.158 | 40.78 | 21.302 | 85/160 |
| AegisKV | 55.230 | 41.12 | 22.653 | 77/160 |

<a id="paper-f0-revisit-wct"></a>

**图 E3｜同配置逐 Workflow 的 WCT。** 每点是同一个 Workflow；从首次 release 至最后请求完成，不含活跃 slot 外的入场等待。三系统只按 Mooncake 的同一序列对齐，保留全部尖峰。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct.png" width="1008" alt="E3 同配置逐 Workflow 的 WCT">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct.pdf)

<a id="paper-f0-revisit-wct-difference"></a>

**图 E4｜逐 Workflow 的完成时间变化。** 各系统 WCT 减同一 Workflow 的 Mooncake WCT；零线为 Mooncake，正值更慢、负值更快。与上一图使用同一 ID 映射，不按差值重新排序。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.png" width="1008" alt="E4 逐 Workflow 的完成时间变化">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.pdf)

首先检查 DRAM 准入的副作用。图 E5 以实际复用 token 为分子、全部 prompt token 为分母，图 E6 将所有来源互斥分解。AegisKV 的 DRAM token 命中率为 41.12%，Mooncake 为 47.13%；新保护策略并没有在这个受控重访输入上保住基线的正常 DRAM 复用水平。备份字节本身不能算 cache hit。

<a id="paper-f0-revisit-dram-hit"></a>

**图 E5｜DRAM 准入是否保住正常复用。** 正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问和精确重访；恢复 token 不计入。它是 token 命中率，不是请求命中比例。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-dram-hit.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-dram-hit.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-dram-hit.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-dram-hit.png" width="1008" alt="E5 DRAM 准入是否保住正常复用">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-dram-hit.pdf)

<a id="paper-f0-revisit-cache-sources"></a>

**图 E6｜实际复用来自哪一层。** 将全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。Peer 备份写入量不会被计为正常服务的命中收益。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.png" width="480" alt="E6 实际复用来自哪一层">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.pdf)

随后将资源等待分开。图 E7 是 GPU-ready 后的调度等待，图 E8 是前台 HBM 准入等待，图 E9 给出 GPU 的低空闲时间比例。跨系统差异同时受到缓存命中和调度影响；后面的静态 Peer 消融与真实 DMA 测量用于进一步检验机制。

<a id="paper-f0-revisit-scheduler-queue"></a>

**图 E7｜正常请求的 GPU 调度排队。** 每个 Workflow 内请求的平均 GPU-ready→运行等待。GET、CPU 和等待分配 HBM 分开计量，不能把它们都写成 scheduler queue。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.png" width="1008" alt="E7 正常请求的 GPU 调度排队">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.pdf)

<a id="paper-f0-revisit-hbm-wait"></a>

**图 E8｜前台因 HBM 准入而等待多久。** 每个 Workflow 内请求的平均前台 HBM 等待；Peer 是否增加排队，需要同时看显存余量、动态消融和原生干扰微基准，不能仅凭跨系统的一个均值归因。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-wait.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-wait.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-wait.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-wait.png" width="1008" alt="E8 前台因 HBM 准入而等待多久">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-wait.pdf)

<a id="paper-f0-revisit-hbm-pressure"></a>

**图 E9｜GPU 的低空闲显存时间占比。** 按每张 GPU 的时长加权，统计 FREE 低于 1 GiB 的执行时间比例；保持真实 GPU 编号和同一阈值。包含可回收的普通缓存，低余量不等于 OOM、HBM 带宽饱和或服务违约。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.png" width="1008" alt="E9 GPU 的低空闲显存时间占比">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.pdf)

图 E10 和 E11 再从请求体验检查这些变化。TTFT 从请求 release 开始；TPOT 每个请求只产生一个均值样本，不能写成逐 token ITL。两图均保留全部尾部。

<a id="paper-f0-revisit-ttft-cdf"></a>
<a id="paper-f0-revisit-tpot-tail"></a>

| **图 E10：请求 TTFT 的完整分布** | **图 E11：请求平均 TPOT 的尾部** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.png" width="480" alt="E10 请求 TTFT 的完整分布">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.png" width="480" alt="E11 请求平均 TPOT 的尾部">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.pdf) |
| 所有 2,608 个请求从 release 到第一个输出 token 的经验分布；与只量 GPU prefill 的耗时不同，包含执行路径上的等待。 | 每系统 2,432 个分母有效的请求先计算首 token 后的平均 TPOT，再绘制包含等号的经验生存比例；保留完整尾部。它不是逐 token ITL 分布，也不是跨运行置信区间。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.csv) · 未标定机制模拟 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.csv) · 未标定机制模拟 · 3.33 inch |

### 控制 CPU 与传输：工作量、服务时长与争用分开

图 E12 测量 Python 参考实现真正消耗的线程 CPU，图 E13 则报告固定报价中实际进入 DES 时序的服务需求。前者不等于原生服务 CPU 利用率，后者还没有完整覆盖提交、回收与 AIMD 的因果时延；两者的差别不能被隐藏成一个“CPU overhead”数字。[逐 Workflow CPU 报价差值](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.pdf)保留在补充图中。

<a id="paper-reference-cpu-breakdown"></a>

**图 E12｜Python 参考实现的实际 CPU 工作量。** 按线程 CPU 时间分解前台派发、准入与 DAG、提交、回收与 AIMD，扣除嵌套计量避免重复。它是本参考实现的组件工作量，未覆盖原生服务的全部 CPU。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.csv) · Python 参考 CPU 实测 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.png" width="1008" alt="E12 Python 参考实现的实际 CPU 工作量">](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.pdf)

<a id="paper-f0-revisit-controller-breakdown"></a>
<a id="paper-f0-revisit-traffic-breakdown"></a>

| **图 E13：进入模拟时序的控制 CPU 服务** | **图 E14：实际传输量的组成** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.png" width="480" alt="E13 进入模拟时序的控制 CPU 服务">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.png" width="480" alt="E14 实际传输量的组成">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.pdf) |
| 固定服务报价的总和，分为前台派发和准入；经过同一个控制器队列。提交、回收和 AIMD 的全部 CPU 工作量还没有完整转成因果延迟。 | 累计模拟内传输的字节，分为正常 GET、DRAM 写入和 Peer 复制，纵轴 TiB。更多副本写入与较少正常命中可能同时发生，不能仅比较总字节得出带宽无争用。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.csv) · 未标定机制模拟 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.csv) · 未标定机制模拟 · 3.33 inch |

图 E14 统计实际传输组成，图 E15 将正常 GET 的服务时间与同字节量独占路径比较。GET 的总体会随缓存策略变化，不能把不同对象的 CDF 差异全部归因于保护复制。[逐 Workflow 后台字节](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.pdf)与[直接计量的 Peer 字节](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.pdf)提供进一步归因。

<a id="paper-f0-revisit-transfer-service_slowdown"></a>

**图 E15｜保护流量是否拖慢前台 GET。** 每个成功正常 GET 的实际传输服务时长 / 同字节量独占链路时长；横轴倍率。不同系统的命中对象和 GET 数量会变，CDF 是描述性分布。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.png" width="480" alt="E15 保护流量是否拖慢前台 GET">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.pdf)

### 故障收益：同一输入、同一事件规则与完整恢复终点

故障焦点在失败运行前从 Mooncake F0 选定，不根据 AegisKV 收益筛选。三个系统对同一请求在同一 prefill 进度触发，绝对时刻、路由和同 GPU 上的其他受影响请求可能不同。图 E16 是中期选点的全部 Workflow 配对损失，早期和后期的[完整差值](Old_Figures.md#agent-lease-supplements)也保留；图 E18 汇总三个位置，图 E17 追踪同一焦点请求的恢复阶段。

| 预定位置 | 参考时已完成 Workflow | P95 配对 WCT 变化 (s)：Mooncake / DRAM-only / AegisKV |
|---|---|---|
| 25% | 40/160 | 26.769 / 28.174 / 25.498 |
| 50% | 80/160 | 17.501 / 18.648 / 15.732 |
| 75% | 121/160 | 15.466 / 12.775 / 13.069 |

这些百分位是单次配置中 160 个对象的描述统计；三个不同位置没有被当作独立重复。

<a id="paper-f1-q50-workflow-penalty"></a>

**图 E16｜50% 进度选点的逐 Workflow 故障代价。** 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 50% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 三个故障位置使用同一纵轴范围。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.png" width="1008" alt="E16 50% 进度选点的逐 Workflow 故障代价">](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.pdf)

<a id="paper-failure-focal-recovery-phases"></a>

**图 E17｜保护缩短的是哪个恢复阶段。** 每根柱追踪同一个预定焦点请求：从故障到前缀装入，再到后缀计算与解码恢复；Peer/DRAM 恢复 token 和重算 token 另存 CSV。只缩短前缀装入不等于总恢复获益。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.png" width="1008" alt="E17 保护缩短的是哪个恢复阶段">](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.pdf)

<a id="paper-failure-progress-p95-penalty"></a>

**图 E18｜不同故障位置的尾部 Workflow 损失。** 每个预定故障位置，对全部 160 个配对 Workflow 的 F1−F0 求 P95。三个位置是不同干预，不是同条件三次独立重复；实际参考进度另表给出。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.png" width="480" alt="E18 不同故障位置的尾部 Workflow 损失">](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.pdf)

### 入场顺序与算法消融

图 E19、E20 使用相同 160 个 Workflow 的三个预定入场顺序。线与阴影分别表示各经验分位的中位数和最小/最大值；它检验调度顺序敏感性，不提供跨独立集群的置信区间。

<a id="paper-order-normal-wct"></a>
<a id="paper-order-failure-penalty"></a>

| **图 E19：更换入场顺序后的正常 WCT** | **图 E20：更换入场顺序后的故障代价** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.png" width="480" alt="E19 更换入场顺序后的正常 WCT">](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.png" width="480" alt="E20 更换入场顺序后的故障代价">](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.pdf) |
| 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。无故障、资源和两轮输入均相同。 | 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。每个顺序各自从 Mooncake F0 选择中期故障，再减本系统对应 F0。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.csv) · 未标定机制模拟 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.csv) · 未标定机制模拟 · 3.33 inch |

图 E21 分别改变 DAG 价值、空闲准入门和 Peer 控制。为了避免把少做保护带来的正常服务加速误认为完整收益，DAG 价值同时比较配对故障条件。图 E22 中，两者均检查 299,957 个尾块，价值计算从 Eager 的 299,957 次降至 Lazy 的 8,087 次，减少约 97.3%；完整准入状态和牺牲者序列相同。固定 CPU 报价未随这次消融改变，因此这项计算量减少不直接等于已测 WCT 加速。

| 价值模型 | F0 平均 WCT (s) | 中期 F1 平均 WCT (s) | F1−F0 (s) |
|---|---|---|---|
| DAG WCT | 55.230 | 55.713 | 0.483 |
| Sum recovery | 53.065 | 54.808 | 1.743 |

<a id="paper-ablation-normal-wct"></a>

**图 E21｜Algorithm 2 / 3 的正常服务消融。** 分别去掉 DAG 联合价值、将空闲门改为严格 G>0、或将动态 Peer 改为静态容量上限。相同输入与 CPU 报价，每次只改一个因素；减少保护可能降低正常开销，也可能损失恢复覆盖。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.png" width="1008" alt="E21 Algorithm 2 / 3 的正常服务消融">](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.pdf)

<a id="paper-ablation-lazy-refresh"></a>

**图 E22｜惰性计算是否保持同样的准入决策。** DRAM-only 上比较 Lazy / Eager：两者都检查全部可释放尾块，只允许跳过版本未变的价值计算。比较每次接纳/拒绝与牺牲块序列必须完全相同；计数包含被拒绝的试算。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.png" width="480" alt="E22 惰性计算是否保持同样的准入决策">](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.pdf)

### 真实 GPU 组件：显存占用与 DMA 干扰

图 E23、E24 在真实 L40S 上分开测量 Peer 输入、输出和 DRAM 写入。短 prompt、batch 1 条件的 Peer 输入会产生约 31% 的 forward 时长增加；这说明“有空余显存”与“复制不干扰推理”不是同一个条件。该结果用于增加一个明确的 30% 模型敏感性扩展，未将 L40S 组件数值直接标定为 A100 三系统 WCT。

<a id="paper-native-forward-b1"></a>
<a id="paper-native-forward-b4"></a>

| **图 E23：真实 forward 与 DMA 并发：batch 1** | **图 E24：真实 forward 与 DMA 并发：batch 4** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.png" width="480" alt="E23 真实 forward 与 DMA 并发：batch 1">](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.png" width="480" alt="E24 真实 forward 与 DMA 并发：batch 4">](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.pdf) |
| batch=1，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | batch=4，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.csv) · 真实 GPU 组件微基准 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.csv) · 真实 GPU 组件微基准 · 3.33 inch |

图 E25 改变额外触达分配量，图 E26 测量 fence 与 allocator 释放完成；其范围限于本模型、batch、长度和一次独占 GPU 分配。[实测复制 CPU 需求](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.pdf)显示，本微基准并发复制时进程平均使用约 1.9–2.0 核，无复制时约 1 核；其中包含复制线程与 CUDA 同步等待，不能当作原生 AegisKV 准入算法的 CPU。原生服务的跨线程调度和完整回收路径仍需单独测量。[并发有效复制速率](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.pdf)也作为补充保留。

<a id="paper-native-memory-occupancy"></a>
<a id="paper-native-release-ack"></a>

| **图 E25：分配容量与复制争用分别测量** | **图 E26：撤销备份后的实际释放延迟** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.png" width="480" alt="E25 分配容量与复制争用分别测量">](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.png" width="480" alt="E26 撤销备份后的实际释放延迟">](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.pdf) |
| batch=4、prompt=4,096，额外触达分配 0/8/16 GiB；比较四种 DMA 条件的真实 forward 时长。纵轴放大局部变化，零 OOM 只适用于这批条件。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 1/4/8 GiB 分配各 20 次：等待异步写入 fence 与 allocator free+empty_cache+同步分开测。两部分都是实测完成时间，不能直接替代原生服务的回收延迟。 标记和误差线为 20 次测量的中位数与最小/最大值。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.csv) · 真实 GPU 组件微基准 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.csv) · 真实 GPU 组件微基准 · 3.33 inch |

### Guarded AIMD 与配置敏感性

在明确设置的 30% DMA forward 时长系数下，图 E27 同时画出允许上限和真实占用，图 E28 比较动态反馈与静态 Peer。预警窗口比例是控制信号，不是请求 SLO 违约率；它与[三方式 WCT 消融](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.pdf)共同检验控制结果，不能从额度下降本身推断性能改进。

| 30% DMA 敏感性条件 | 平均 WCT (s) |
|---|---|
| DRAM-only AegisKV | 53.970 |
| AegisKV | 53.929 |
| Static Peer cap | 55.017 |

<a id="paper-aimd-quota-and-occupancy"></a>

**图 E27｜AIMD 授权与实际副本占用。** 在 30% DMA 额外 forward 时长的敏感性条件下，按 50 ms 窗口汇总 8 张 GPU 的 C、Q 和实际副本。物理占用含 pending；模拟器在 fence 后同步 free，真实释放时长另图测量。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-quota-and-occupancy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-quota-and-occupancy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-quota-and-occupancy.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/aimd-quota-and-occupancy.png" width="1008" alt="E27 AIMD 授权与实际副本占用">](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-quota-and-occupancy.pdf)

<a id="paper-aimd-warning-windows"></a>

**图 E28｜预警反馈是否随控制变化。** 同一 30% 争用假设下，比较 Guarded AIMD 和只保留显存上限的 Static Peer；1 s 桶内统计产生归一化 forward 预警的目标窗口比例。预警不是请求 SLO 违约率。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.png" width="1008" alt="E28 预警反馈是否随控制变化">](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.pdf)

最后用图 E29、E30 检查共享带宽与 DRAM 容量。只连接实际执行的设置，不将少数点拟合成普遍规律。[并发 16/32](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.pdf)、[CPU 报价 1×/2×](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.pdf)与[DMA 0/5/30%](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.pdf)的独立图保留在补充材料。

<a id="paper-sensitivity-bandwidth"></a>
<a id="paper-sensitivity-dram-capacity"></a>

| **图 E29：共享路径带宽敏感性** | **图 E30：DRAM 容量与正常命中** |
|---|---|
| [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.png" width="480" alt="E29 共享路径带宽敏感性">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.pdf) | [<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.png" width="480" alt="E30 DRAM 容量与正常命中">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.pdf) |
| 实际执行 5/25/50 GB/s，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 实际执行 250 GB / 1 TB，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 |
| [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.csv) · 未标定机制模拟 · 3.33 inch | [PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.csv) · 未标定机制模拟 · 3.33 inch |

### 用故障收益偿还正常开销的条件

图 E31 将已执行的无故障均值与三个故障条件做显式概率混合，直接回答在当前模型假设下，故障收益何时可能抵消正常服务代价。横轴概率与三个位置等权都是分析假设；图中若没有交点，也保留这一结果，不外推到未测的多次故障或故障频率。

相对 Mooncake，在 p∈[0,1] 没有交点（p=0/1 的 AegisKV−基线为 2.588/2.545 s）；相对 DRAM-only AegisKV，在 p∈[0,1] 没有交点（p=0/1 的 AegisKV−基线为 1.072/0.582 s）。这些交点只适用于图中明确的概率混合假设。

<a id="paper-benefit-cost-fault-mixture"></a>

**图 E31｜何种故障概率下才能抵消正常开销。** 解析混合 E[WCT]=(1−p)·F0+p·平均 F1，假定一次完整执行至多一个故障，三个预定位置等权。p 是分析参数，不能解释成观测故障率、MTBF 或多次故障结果。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.csv) · 模拟结果的解析混合 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.png" width="1008" alt="E31 何种故障概率下才能抵消正常开销">](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.pdf)

### 当前证据支持什么，还缺什么

本轮已经把用户修订的两个算法落实到可执行的模拟路径，补上 Agent 跨请求与并行分支、Q 的完整尾块检查、联合 DAG 分账、同轮信用、独立 AIMD、三系统配对、详细资源计量、故障位置、惰性/门限/DAG/静态控制消融，以及真实 GPU 组件干扰与释放测量。旧 PrefixAdmission 结果完整归档，没有重标为新算法。**当前结果支持惰性计算减少、部分故障增量下降和强争用下动态控制的机制效果，但三组主故障条件的 AegisKV 平均 WCT 仍高于 Mooncake，未证明总体端到端收益。**

仍不能据此宣称原生 AegisKV 已获得端到端收益：三系统实际服务的 WCT/吞吐/CPU/故障恢复、在线预测器误差与校准、更多真实 workload 和多故障/多节点泛化尚缺独立证据。DAG 时长估计和 DMA 系数也没有经过统一硬件标定。当前论文应将对应定量结论明确写为机制模拟或组件微基准，保留所有负结果，并以这些缺口决定完整系统投稿前的后续实验。

[逐图 CSV 与来源选择清单](../../../output/agent-lease-20260908/paper-selection.json) · [独立图 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-figures.tex) · [可选并排 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-pairs.tex) · [实际插入尺寸校样](../../../output/pdf/aegiskv-agent-lease-20260908/paper-placement.pdf) · [完整核对记录](../../../output/agent-lease-20260908/DELIVERY_AUDIT.json)
