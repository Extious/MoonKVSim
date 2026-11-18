# AegisKV：面向多 Agent Workflow 的 KV 保护

<!-- 中文论文正文源。三部分共 12 张独立图：Motivation 3，System Design 1，Evaluation 8。
参考原论文的论证结构；实验结果绑定 source-v3，不覆盖 Algorithm 2 后续调整。
选图理由、来源、补充材料和可复现入口在 PAPER_FIGURE_REVIEW.md 中维护。 -->

## Motivation

### Observation 1：并行分支具有显著的执行时间差

多 Agent 应用将一次任务组织为模型调用、工具调用与汇合结点组成的依赖图。用户等待的是整个 Workflow 完成，而汇合结点必须等待所有前驱。因此，单个请求恢复得更快，只有在缩短依赖图的完成时间时才产生用户可见收益。我们以 Workflow Completion Time（WCT）作为保护目标，即从 Workflow 首个请求释放到最后一个请求完成的时间。

公开 [CC/Weka 轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)提供了分支执行不均衡的观测依据。我们保留存在共同重叠区间的并行分支组，并对每个 Workflow 取最大的最长与最短分支持续时间差。图 {{ref:motivation-branch-gap}} 中，124 个符合条件的 Workflow 的中位差值为 140.6 s，P90 为 1,570.3 s。这些观测说明，不同分支距汇合完成的时间余量可能相差很大；持续时间差本身并不等于故障时刻可使用的 Slack。

### Observation 2：重算代价的排序不等于 Workflow 损失的排序

图 {{ref:motivation-recovery-exposure}} 使用旧动机实验中的同一个五分支轨迹示例，分离恢复暂停中被并行执行吸收的部分与实际推迟汇合的部分。对每条分支分别在 349.5 s 注入一次模型化故障，保持其他分支的执行不变。若分支恢复需要额外时间 $T_i$、到原汇合时刻的剩余间隔为 $s_i$，暴露的延迟为

$$
J_i=\max(0,T_i-s_i).
$$

A3 的模型化重算时间最长，为 46.6 s，但其 52.4 s 的汇合间隔可吸收全部暂停；A4 的重算时间较短，为 35.9 s，却因处于关键分支而全部暴露给 Workflow。因而，仅按 KV 大小或重算时间选择保护对象，会把资源分配给不改变完成时间的分支。保护价值应根据当前依赖图中能够避免的 WCT 损失定义，多个共享分支的改善也需要联合评价。

{{row:motivation-branch-gap,motivation-recovery-exposure}}

这一例子是轨迹锚定的反事实推演。重算时间来自冻结的 AIConfigurator Qwen3-235B-A22B、A100-80GB、TP8/PP4/EP8 配置，输入长度由轨迹中的 64-token hash block 数重建；它不是实际故障测量，也不是后文的 Qwen3-8B 实验。该推演解释评价目标的差别，不估计部署收益。实际恢复还会改变排队、并行进度与关键路径，因此后文同时测量恢复终点与完整 WCT。

### Observation 3：长上下文使无差别保护受到容量约束

副本空间随上下文长度线性增长。对于具有 $L$ 个注意力层、每层 $h_{\mathrm{kv}}$ 个 KV head、head dimension 为 $d$、元素宽度为 $b$ 字节的模型，每个 token 的 KV 大小为 $2Lh_{\mathrm{kv}}db$。本文 Qwen3-8B BF16 布局对应 147,456 B/token，一个 4,096-token chunk 占用 576 MiB。

图 {{ref:motivation-kv-capacity}} 显示，96 Ki tokens 的一份 KV 占用 13.5 GiB，两份占用 27 GiB。对一张 40 GiB GPU，仅扣除权重与固定运行时空间后，两份长上下文 KV 已超过剩余容量；前台推理还需要额外的动态 KV。因此，Peer HBM 的可借容量随前台需求变化，不能按静态空闲空间无限保留副本。

{{fig:motivation-kv-capacity}}

三条 Observation 导出 AegisKV 的设计目标：以联合 WCT 改善决定保护价值，对共享 KV 按物理对象计量，并随前台需求撤销 Peer 显存借用。DRAM 保留策略还可能改变正常前缀复用，复制与准入也消耗带宽及 CPU；这些代价需要与故障收益在同一实验配置下共同评价。

## System Design

### 系统架构与独立保护路径

图 {{ref:system-overview}} 展示 AegisKV 的整体架构。应用侧提供当前可见的 Workflow DAG 与 Agent 状态，价值接口将分支剩余执行时间映射为恢复对 WCT 的影响，池级准入决定保留哪些物理 chunk。目标 GPU 上独立的显存控制器根据前台内存需求和 forward 反馈限制备份借用。

源 Worker 持有正常推理的 primary KV。密封的 C0、C1 可以分别复制到 Peer HBM 与 DRAM Store，两条路径各自分配空间、执行复制并确认提交；某一层拒绝或丢失副本，不影响另一层已经提交的同名对象。共享 C0 的多个 Agent 引用不会在同一个池中重复占用 C0 的容量。Peer Worker 的前台 P0、P1 与借用空间中的备份 C0、C1 是不同物理对象。

{{fig:system-overview}}

本文考虑执行 Worker 的 fail-stop 故障，故障导致其本地 KV 丢失，应用层、Router 与控制器继续运行。Router 撤销旧执行权限，将请求迁移到恢复 Worker；恢复过程在新的 primary 分配中装入任一可用层的兼容、连续、已提交前缀，再重算缺失后缀并恢复解码。图中装入的是 C0、C1，重算的是 C2，备份不会被直接改写为其他请求的前台 KV。副本身份包含模型、数据类型、布局和分片；pending 副本不能用于恢复。本文评估 TP=PP=1 的执行配置，不涉及控制面故障或跨布局恢复。

### Workflow 价值与物理块准入

价值接口在请求和工具返回时更新当前可见的剩余 DAG。对正在执行的结点估计剩余时间，对已知但尚未开始的结点估计完整时间；未知分支不预先计价。沿 DAG 计算最早与最迟执行时间，可以识别哪些恢复暂停会改变汇合终点。预测余量需要随执行进度更新，不能作为未来进度不变的保证。

对候选物理块 $x$，在同一组受影响 Workflow 上分别计算准入前后的恢复完成时间。其联合收益及单位容量价值定义为

$$
G_x=\sum_w \mathrm{WCT}_w^{\mathrm{before}}
    -\sum_w \mathrm{WCT}_w^{\mathrm{after}},\qquad
P_x=G_x/b_x.
$$

这里的 $b_x$ 是物理块字节数。恢复代价包含装入当前可用完整前缀以及重算已产生的缺失后缀，不预支未知输出。多个 Agent 引用同一块时，先评价联合终点，再分配授信，避免将各分支重算节省直接相加。信用记录剩余保留额度，不能在每次价值检查时重新补满。

容量竞争仅选择可以释放的尾块，保护内部前缀与在读对象。准入比较新块收益与淘汰造成的联合损失；试算期间不改变真实可读集合。账本提交、物理释放和副本发布分别受版本核验、释放确认与复制确认约束。算法的具体授信与刷新规则仍在调整；后文定量结果对应已冻结的 source-v3 参考版本。

### 前台约束下的 Peer HBM 控制

Peer 控制器与价值及信用计算独立。它区分备份可用显存硬上限 $C(t)$、授权额度 $Q(t)$ 和仍占用物理地址的副本 $U(t)$。硬上限在固定开销、当前前台分配、下一步新增需求和保留量之外计算，并受策略上限与实际分配器容量限制；授权必须满足

$$
0\le Q(t)\le C(t).
$$

稳定且有备份需求时，Guarded AIMD 逐步增加授权；forward 预警触发乘法退让，新的前台需求直接裁剪硬上限，无效观测撤销借用权限。降低 $Q(t)$ 不会立刻释放 $U(t)$：复制中、已提交和回收中的字节均保持计费，直到 DMA fence 与物理释放完成。前台分配依据真实物理可行性，而非仅依据较小的授权数字。

这一区分也规定了评估终点。前缀装入完成之后仍可能需要后缀重算、调度等待与其他分支执行，局部恢复时间的缩短不能代替完整 Workflow 收益。

## Evaluation

### 实验方法

评估分为轨迹驱动的离散事件模拟与真实 GPU 组件微基准。模拟用于比较三个策略在相同 Workflow、路由、资源模型和恢复路径下的行为；GPU 微基准用于测量复制对 forward 的物理干扰。source-v3 模拟时序尚未在目标平台上完成统一标定，价值接口使用轨迹时长而非已训练的在线 GBDT，因此本节提供机制分析，不构成原生三系统端到端部署测量。

**工作负载与基线。** 我们从 [FanOutQA](https://aclanthology.org/2024.acl-short.2/) 构造 160 个完整 Workflow、1,304 个原始请求，使用固定 Qwen3-8B tokenizer 保持 token 与共享前缀身份一致。每个完整 DAG 执行两轮受控精确重访，共 2,608 个请求；该构造提供明确的复用压力，不代表真实重访频率。最大总上下文为 86,214 tokens，每个 Workflow 最多有 27 次原始调用。

Mooncake 基线采用共享前缀 LRU DRAM Store；DRAM-only AegisKV 使用 AegisKV 的 DRAM 保护策略并关闭 Peer HBM；完整 AegisKV 增加 Peer HBM 与 Guarded AIMD。DRAM-only 是隔离 Peer 作用的消融。三系统共用正常执行、复制提交、故障恢复与闭环调度路径。

| 参数 | 默认配置 |
|---|---|
| 模型 / 并行方式 | Qwen3-8B BF16 / DP=8，TP=1，PP=1 |
| GPU / DRAM Store | 8 × 40 GiB / 1 TB |
| 共享路径 / KV chunk | 25 GB/s / 4,096 tokens（576 MiB） |
| 活跃 Workflow | 16，三系统使用相同入场顺序 |
| Peer 策略上限 / 前台保留量 | 每 GPU 8 GiB / 1 GiB |
| 动态控制 | 初始授权为零；50 ms 窗口，四个稳定窗口后增 1 GiB，预警减半 |
| 故障条件 | F0：无故障；F1：一次执行 GPU 故障，持续 120 s |

**配对与统计单位。** 每次执行处理上述完整输入，逐 Workflow 图中的每个点是同一个逻辑 Workflow，不是一轮系统运行。所有对象按 Mooncake F0 的 WCT 从小到大排列，并在其他系统和指标中保持相同 ID 顺序。WCT 不包含活跃名额之外的入场等待；token hit rate 是实际复用 token 占全部 prompt token 的比例。

故障在处理组运行前从 Mooncake F0 中选定：分别取基准完成进度最接近 25%、50%、75% 的合格第一轮长请求，在其 prefill 完成 60% 时触发故障，对应基准已完成 40、80、121 个 Workflow。三个系统针对同一逻辑请求与进度干预，实际墙钟时刻和路由可不同。设 $W_{s,i}^{F}$ 为系统 $s$ 中 Workflow $i$ 在条件 $F$ 下的 WCT，配对故障增量为

$$
\Delta_{s,i}=W_{s,i}^{F1}-W_{s,i}^{F0}.
$$

冻结矩阵含 47 次完整执行，DMA 扩展另含 4 次，共 51 次。每个配置与系统的曲线使用其对应执行；不同配置不是重复实验。seed 1、2 仅重排同一组 Workflow，用于检查入场顺序敏感性，不产生独立部署的置信区间。

### 正常执行与故障恢复是否改善完整 Workflow

图 {{ref:f0-revisit-wct}} 对齐三个系统的全部 160 个 Workflow。AegisKV 的平均 WCT 为 {{aegis_wct}} s，相对 Mooncake {{overhead}}，DRAM-only 的均值也更高。AegisKV 有 77 个 Workflow 慢于 Mooncake，少于总体一半，但较大的延迟仍推高均值；不能用改善对象的数量代替完成时间收益。

{{fig:f0-revisit-wct}}

{{healthy_results}}

图 {{ref:f1-q50-workflow-penalty}} 比较中期故障相对各系统自身 F0 的增量。曲线保留所有正值、负值与零值：闭环调度中，故障会改变争用和后续入场，部分对象因而更早完成；负值不能解释为故障本身有益。AegisKV 的增量 P95 由 Mooncake 的 17.501 s 降至 15.732 s，但其绝对 F1 平均 WCT 仍更高。

{{fig:f1-q50-workflow-penalty}}

| 故障位置 | 系统 | F1 平均 WCT (s) | 增量 P95 (s) | 焦点请求恢复解码 (s) |
|---|---|---:|---:|---:|
{{compact_fault_rows}}

三处预定故障均未使 AegisKV 的绝对平均 WCT 优于 Mooncake。早期焦点请求的恢复解码延迟明显缩短，中期则略高于 Mooncake；并且这三次 AegisKV 焦点恢复均未读取 Peer token，不能将局部改善归因于 Peer 装入。该结果表明，尾部故障增量与局部恢复改善尚未抵消正常服务成本。

### DRAM 准入是否损害正常 KV 复用

图 {{ref:f0-revisit-dram-hit}} 对同一组 Workflow 比较正常服务的 DRAM token 命中。Mooncake、DRAM-only 与 AegisKV 的整体命中率分别为 47.13%、40.78% 和 41.12%，AegisKV 相对 Mooncake 下降 6.01 个百分点。两种 AegisKV 配置都出现下降，说明复用代价已存在于 DRAM 保留策略中。

{{fig:f0-revisit-dram-hit}}

按全部 prompt token 统计，三系统的正常 Peer 命中均为零；重新计算比例分别为 51.67%、57.97% 和 57.51%。Peer 保护写入在此输入上没有转化为额外正常命中。恢复价值与正常复用价值需要共同权衡，保护字节数不能作为命中收益的替代指标。

### Peer HBM 是否增加前台等待

图 {{ref:f0-revisit-hbm-wait}} 展示每个 Workflow 内请求的平均前台 HBM 准入等待。HBM 等待与 GPU-ready 后的调度排队分别计量，避免将复制、内存分配及执行队列混为一个延迟。

{{fig:f0-revisit-hbm-wait}}

| 指标 | Mooncake | DRAM-only AegisKV | AegisKV |
|---|---:|---:|---:|
| 累计前台 HBM 等待 (s) | 188.634 | 150.208 | 116.597 |
| 请求调度等待 P95 (s) | 10.908 | 11.614 | 10.444 |
| 请求 TTFT P99 (s) | 23.202 | 21.302 | 22.653 |

当前模拟没有显示开启 Peer 必然增加这两类等待。不过，命中、批处理与执行进度同时变化，跨系统差异不能单独识别 Peer 复制的因果影响。下文通过真实复制微基准和动态控制消融进一步检查这一问题。

### 准入与复制增加多少 CPU 和共享路径成本

图 {{ref:evaluation-resource-cost}} 将五个不同指标分别除以同一指标的 Mooncake 值，使增加的计算与变化的流量可以在一个坐标中比较。第一行是 Python 参考实现的实测线程 CPU 时间；其他行是进入模拟时序的服务需求、传输字节与 GET 争用。各行独立归一化，不能相加为总开销。

{{fig:evaluation-resource-cost}}

| 指标 | Mooncake | DRAM-only AegisKV | AegisKV |
|---|---:|---:|---:|
| Python 参考 CPU 时间 (s) | 9.989 | 56.538 | 68.502 |
| 模拟 CPU 服务需求 (s) | 3.743 | 18.335 | 27.729 |
| DRAM + Peer 写入 (TiB) | 3.549 | 3.471 | 3.643 |
| 正常 GET 字节 (TiB) | 3.386 | 2.930 | 2.954 |
| GET 服务时长 / 独占时长，P95 | 27.21 | 22.53 | 21.20 |

AegisKV 的 Python CPU 时间约为 Mooncake 的 6.86 倍，额外工作分布在准入与 DAG、提交、回收及 AIMD。模拟 CPU 服务需求约为 7.41 倍，但其报价尚未包含全部参考 CPU 操作，因此不能将模拟 WCT 视为完整原生控制开销的测量。

AegisKV 产生约 0.109 TiB Peer 流量，DRAM 与 Peer 写入合计比 Mooncake 多约 2.6%。其正常 GET 流量和成功 GET 的争用倍率更低，但同时伴随更低的 token 命中率；未命中请求转为重算会减少读取字节，GET 对象总体也随策略改变。这些指标用于解释代价来源，不能单独作为网络效率收益。

### 真实复制是否拖慢 GPU forward

我们在一次独占的双 L40S 分配中运行 Qwen3-8B BF16/SDPA。图 {{ref:evaluation-native-interference}} 在同一纵轴上比较 batch 1、4 与三种 prompt 长度，保留原微基准中额外分配 8 GiB 的 120 个观测。无复制、DRAM 写入、Peer 输入和 Peer 输出按五个随机交错测量块配对；倍率先在块内计算，点为倍率中位数，误差线为最小至最大观测。

{{fig:evaluation-native-interference}}

512-token 条件下，Peer 输入使 batch 1 的 forward 中位倍率达到 1.322，即增加 32.2%；batch 4 为 1.096，即增加 9.6%。因此，即使备份容量可容纳，复制仍可能干扰前台计算，干扰程度还依赖前台形状。整个微基准含 360 个 forward 观测且未出现 OOM，这只覆盖所测条件，不能推出任意负载下的显存安全性或原生系统 WCT 收益。

### 动态控制能否约束借用，机制消融说明什么

图 {{ref:aimd-quota-and-occupancy}} 使用显式设置 30% DMA forward 时长系数的模拟条件，区分八张 GPU 的硬上限、授权与实际占用。备份主要集中在执行初段，随后多数时段的授权与占用接近零；默认等待较低也不能据此解释为持续借用没有成本。额度裁剪与副本物理释放并不同步，因而不能将较小的授权视为内存已经可用。该系数用于敏感性分析，没有把 L40S 测量直接标定为模拟平台的端到端延迟。

{{fig:aimd-quota-and-occupancy}}

{{aimd_results}}

Guarded AIMD 的平均 WCT 比静态 Peer 控制低约 1.98%，但与 DRAM-only 的差异很小。动态控制缓解了该强争用假设下静态借用的代价，尚不支持完整系统在默认条件下的平均收益。

{{dag_results}}

联合 DAG 价值相对按恢复时间相加的变体降低了中期故障增量，却增加了正常平均 WCT。另一个等价性消融中，Lazy 与 Eager 均执行 299,957 次尾块检查，价值求值从 299,957 次降至 8,087 次，减少 97.3%，准入和牺牲者序列完全一致。由于对应 CPU 报价未随求值次数变化，这一结果只证明减少重复求值，不能据此宣称 WCT 加速。

### 相对表现是否依赖资源配置

图 {{ref:evaluation-configuration-effects}} 将原先分散的带宽、容量、并发、CPU 与 DMA 扫描合为一个逐配置比较。每行只改变默认配置的一个因素，使用该行 Mooncake 作为配对基准；八行是不同实验条件，不是八次重复，也不在异质配置之间连线拟合趋势。

{{fig:evaluation-configuration-effects}}

5 GB/s 下，AegisKV 与 Mooncake 的平均 WCT 分别为 73.876 和 75.123 s，AegisKV 略快；25 和 50 GB/s 下则更慢。排名随资源条件变化，说明应同时报告受益区域与代价区域。三种入场顺序的完整分布、其他请求尾部、恢复阶段和释放观测保留为补充材料，正文不重复展开同一证据。

当前结果支持 Workflow 价值、真实资源干扰及动态控制的必要性，但尚未建立 AegisKV 的普遍端到端优势。默认正常成本与三处故障结果仍需共同改善；后续验证还需要同步完成的算法版本、原生三系统服务、在线预测校准与独立工作负载。
