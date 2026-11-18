# AegisKV 论文图与证据叙述

[总导航](FIGURES.md) · [逐图审查](PAPER_FIGURE_REVIEW.md) · [旧版与补充图](Old_Figures.md) · [本轮实验协议](AGENT_LEASE_PROTOCOL.md)

本版使用 2026-09-08 **source-v3 冻结实验**中的 Agent 子租约与独立 Guarded AIMD 结果。正文选入 {{primary_count}} 张独立图；另外 {{supplement_count}} 张图作为机制细节、敏感性和逐 Workflow 诊断保存。定量图有逐点 CSV，设计图有可编辑 Draw.io，全部提供 PDF/SVG/PNG；互补的单栏图可在 Markdown 同行阅读，LaTeX 仍分别插入。

本轮按 PaperBanana 优化全部当前图：统一系统编码、紧凑图例与最终插入尺寸，并以对象状态和数值对照重画机制图。[逐图记录](PAPER_FIGURE_REVIEW.md)说明参考与修改；[LaTeX 排版样张](../../../output/pdf/aegiskv-agent-lease-20260908/paper-placement.pdf)展示实际单栏/通栏效果。

Algorithm 2 仍在调整。按本轮约定，此次只优化绘图，不同步实现或重跑实验；定量结果对应[冻结算法清单](../../../output/agent-lease-20260908/ALGORITHM_AUTHORITY.json)，设计图用于说明机制，尚不代表算法最终定稿。

这些图可用于具有明确证据范围的论文叙述：**观测动机、解析示意、未标定机制模拟和真实 GPU 组件微基准分别标注**。正常服务主结果中 AegisKV 的平均 WCT 为 {{aegis_wct}} s，相对 Mooncake {{overhead}}；这组数据不支持“保护几乎没有开销”。算法收益需要进一步结合配对故障、消融与原生证据判断。

## Motivation

### 保护目标应落在 Workflow 完成时间上

多 Agent Workflow 的并行分支可能在不同时间完成。图 {{ref:motivation-branch-gap}} 用观测数据说明这种不均衡，图 {{ref:motivation-kv-capacity}} 则说明无差别复制长上下文会消耗可观显存。动机由两个事实组成：不是所有分支重算都会等量暴露给 Workflow；保存每一份 KV 也不是免费的。观测分支时间差尚不是经过干预验证的可用 Slack，后续设计只使用已知 DAG 和当前恢复状态做联合价值计算。

{{row:motivation-branch-gap,motivation-kv-capacity}}

## System Design

### 将价值判断与前台资源约束分开

图 {{ref:system-overview}} 从同一 Source 的 KV 出发，分别画出 Peer HBM 与 Store DRAM 的独立数据路径。Agent/执行分支记录保存当前请求轮号与恢复终点，物理块只计一次容量。Algorithm 2 决定有限备份空间留给哪些块；Algorithm 3 根据目标 GPU 的显存与 forward 预警调整可借上限。AIMD 不读取 Slack、Credit 或 Algorithm 2 队列。

{{fig:system-overview}}

### Algorithm 2：联合收益、Agent 子租约与完整尾块检查

图 {{ref:design-joint-wct}} 给出可手算的共享块实例。按固定 Agent 顺序加入各分支恢复改善，边际分账之和恰好等于一次联合 DAG WCT 下降，不重复计算同一 Workflow 的收益。新块只评价已产生的 KV；已有块补备份和命中更新保留已经生成后缀的重算成本，不纳入未知未来输出。

{{fig:design-joint-wct}}

图 {{ref:design-agent-subleases}} 继续展示信用如何跨请求保存。新请求更新 Agent 记录；新轮首次参与竞争时只更新该 Agent 的子租约。同轮刷新不能补回已经消耗的信用。相同名称的并行 Agent 分支按输入 DAG 的固定因果链维护独立记录，避免一个请求完成覆盖另一条仍在执行分支的状态。

{{fig:design-agent-subleases}}

图中只从可释放尾块组成的单一 Q 收租，内部块、被读取块和 pending 复制所需前缀不参与。收租前检查 Q 中每个尾块的版本；惰性优化只跳过版本未变的价值计算。空闲空间允许 G≥0，有淘汰时要求 G>D。试算信用和轮号标记在版本核验后才提交，物理释放完成后才分配目的地。完整的[单块试算状态图](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.pdf)与用户修订的[准入决策图](../docs/drawio/slacklandlord-patent-revised/algorithm-2-admission.drawio)、[命中更新图](../docs/drawio/slacklandlord-patent-revised/algorithm-2-cache-hit.drawio)分别保留。

### Algorithm 3：授权额度与物理占用分别计量

图 {{ref:design-guarded-aimd}} 以同一个显存布局展示增长、预警退让和容量收缩。C 是扣除前台新增需求与保留量后的硬上限；Q 是允许借用的额度，既不代表新增加的显存，也不等于已经占用的备份。有效监测、持续稳定、实际需求和上一轮调整完成共同决定增长；无效监测撤销授权。50 ms 控制窗口不因每次内存分配而虚增稳定次数。

{{fig:design-guarded-aimd}}

### 提交与恢复沿用同一组物理对象

图 {{ref:commit-tier-timeline}} 说明 Peer ACK 不意味着 DRAM 也已提交，源故障后只能使用各 tier 的连续已提交前缀。前缀装入新 primary 之后，还可能需要后缀重算和 GPU 排队才能恢复解码。因此 Evaluation 同时报告装入与恢复终点，不能仅挑选更短的装入时间。后续复制失败不会复活已经释放的旧块。

{{fig:commit-tier-timeline}}

## Evaluation

### 比较对象、输入与计量口径

| 项目 | 当前图像使用的配置与范围 |
|---|---|
| 三系统 | Mooncake：共享前缀 LRU DRAM Store 的模拟适配；DRAM-only AegisKV：冻结版 Algorithm 2、关闭 Peer；AegisKV：相同 DRAM 策略，加 Peer 与冻结版 Algorithm 3 |
| 模型与资源 | Qwen3-8B BF16，DP8/TP1/PP1，8×40 GiB，chunk=4,096 tokens；默认 DRAM=1 TB，共享路径=25 GB/s，活跃 Workflow=16 |
| Peer 控制 | 每 GPU 策略硬上限 8 GiB、前台保留 1 GiB；Q 从 0 开始，50 ms 窗口、4 个稳定窗口、每次增 1 GiB、预警减半；C 还扣除下一次前台新增需求，普通可复用缓存不计入可借 FREE |
| 冻结输入 | 160 个 FanOutQA 派生 Workflow、1,304 个原始请求；完整 DAG 做两轮受控精确重访，共 2,608 个请求。三系统共享 token、DAG、入场顺序 |
| 算法与故障绑定 | source-v3 的不可变快照覆盖实现、runner、输入和用户指定决策图；F0 无故障，F1 在预定第一轮长请求的 prefill 60% 处触发一次 GPU 故障，持续 120 s |
| 比较单位 | 每个配置、每个系统执行一次完整输入；主矩阵 47 次、另加预先记录的 30% DMA 扩展 4 次，共 51 次。3 次独立 CPU 报价校准不算主结果重复；跨目录复用同一次执行不重复计数 |
| 配对与顺序 | [固定 Workflow ID 映射](../../../output/pdf/aegiskv-agent-lease-20260908/workflow-order.csv)由 seed 0 Mooncake F0 WCT 确定；seed 1/2 只改变同一批对象的入场顺序，不产生新的独立 Workflow 总体 |
| GPU 时序与 CPU | GPU forward 为既有 observed-trace 模型，未标定为 A100 kernel；DAG 使用 trace 时长估计，不是训练完成的 GBDT。CPU 报价进入准入/派发服务队列；其他参考 CPU 工作量单独测量，尚未全部转成因果延迟 |
| 原生微基准 | Slurm 147489 独占两张 L40S，真实 Qwen3-8B BF16/SDPA；360 个 forward 样本、0 个 OOM，复制方向/额外占用/长度/batch 随机交错；另测每种大小 20 次释放 |

图 {{ref:workload-prompt_tokens}}、{{ref:workload-workflow_call_counts}} 界定模型输入，避免以“160 个 Workflow”掩盖请求长度和 DAG 规模。第二轮是受控重访压力，不是观测到的真实用户重访分布。两轮与单轮结果不能直接相减作为故障代价，本版 F1 均使用同一份两轮 F0 对照。

{{row:workload-prompt_tokens,workload-workflow_call_counts}}

### 正常服务：先报告总效果，再定位原因

图 {{ref:f0-revisit-wct}} 在同一配置下直接比较三条逐 Workflow 曲线，图 {{ref:f0-revisit-wct-difference}} 展示配对差值。全体均值如下；相同对象之间会因缓存和调度重排而出现正负变化，因此既保留尖峰，也保留更快的对象。

{{healthy_results}}

{{fig:f0-revisit-wct}}

{{fig:f0-revisit-wct-difference}}

首先检查 DRAM 准入的副作用。图 {{ref:f0-revisit-dram-hit}} 以实际复用 token 为分子、全部 prompt token 为分母，图 {{ref:f0-revisit-cache-sources}} 将所有来源互斥分解。AegisKV 的 DRAM token 命中率为 {{aegis_hit}}%，Mooncake 为 {{mooncake_hit}}%；新保护策略并没有在这个受控重访输入上保住基线的正常 DRAM 复用水平。备份字节本身不能算 cache hit。

{{fig:f0-revisit-dram-hit}}

{{fig:f0-revisit-cache-sources}}

随后将资源等待分开。图 {{ref:f0-revisit-scheduler-queue}} 是 GPU-ready 后的调度等待，图 {{ref:f0-revisit-hbm-wait}} 是前台 HBM 准入等待，图 {{ref:f0-revisit-hbm-pressure}} 给出 GPU 的低空闲时间比例。跨系统差异同时受到缓存命中和调度影响；后面的静态 Peer 消融与真实 DMA 测量用于进一步检验机制。

{{fig:f0-revisit-scheduler-queue}}

{{fig:f0-revisit-hbm-wait}}

{{fig:f0-revisit-hbm-pressure}}

图 {{ref:f0-revisit-ttft-cdf}} 和 {{ref:f0-revisit-tpot-tail}} 再从请求体验检查这些变化。TTFT 从请求 release 开始；TPOT 每个请求只产生一个均值样本，不能写成逐 token ITL。两图均保留全部尾部。

{{row:f0-revisit-ttft-cdf,f0-revisit-tpot-tail}}

### 控制 CPU 与传输：工作量、服务时长与争用分开

图 {{ref:reference-cpu-breakdown}} 测量 Python 参考实现真正消耗的线程 CPU，图 {{ref:f0-revisit-controller-breakdown}} 则报告固定报价中实际进入 DES 时序的服务需求。前者不等于原生服务 CPU 利用率，后者还没有完整覆盖提交、回收与 AIMD 的因果时延；两者的差别不能被隐藏成一个“CPU overhead”数字。[逐 Workflow CPU 报价差值](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.pdf)保留在补充图中。

{{fig:reference-cpu-breakdown}}

{{row:f0-revisit-controller-breakdown,f0-revisit-traffic-breakdown}}

图 {{ref:f0-revisit-traffic-breakdown}} 统计实际传输组成，图 {{ref:f0-revisit-transfer-service_slowdown}} 将正常 GET 的服务时间与同字节量独占路径比较。GET 的总体会随缓存策略变化，不能把不同对象的 CDF 差异全部归因于保护复制。[逐 Workflow 后台字节](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.pdf)与[直接计量的 Peer 字节](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.pdf)提供进一步归因。

{{fig:f0-revisit-transfer-service_slowdown}}

### 故障收益：同一输入、同一事件规则与完整恢复终点

故障焦点在失败运行前从 Mooncake F0 选定，不根据 AegisKV 收益筛选。三个系统对同一请求在同一 prefill 进度触发，绝对时刻、路由和同 GPU 上的其他受影响请求可能不同。图 {{ref:f1-q50-workflow-penalty}} 是中期选点的全部 Workflow 配对损失，早期和后期的[完整差值](Old_Figures.md#agent-lease-supplements)也保留；图 {{ref:failure-progress-p95-penalty}} 汇总三个位置，图 {{ref:failure-focal-recovery-phases}} 追踪同一焦点请求的恢复阶段。

{{fault_results}}

{{fig:f1-q50-workflow-penalty}}

{{fig:failure-focal-recovery-phases}}

{{fig:failure-progress-p95-penalty}}

### 入场顺序与算法消融

图 {{ref:order-normal-wct}}、{{ref:order-failure-penalty}} 使用相同 160 个 Workflow 的三个预定入场顺序。线与阴影分别表示各经验分位的中位数和最小/最大值；它检验调度顺序敏感性，不提供跨独立集群的置信区间。

{{row:order-normal-wct,order-failure-penalty}}

图 {{ref:ablation-normal-wct}} 分别改变 DAG 价值、空闲准入门和 Peer 控制。为了避免把少做保护带来的正常服务加速误认为完整收益，DAG 价值同时比较配对故障条件。图 {{ref:ablation-lazy-refresh}} 中，两者均检查 299,957 个尾块，价值计算从 Eager 的 299,957 次降至 Lazy 的 8,087 次，减少约 97.3%；完整准入状态和牺牲者序列相同。固定 CPU 报价未随这次消融改变，因此这项计算量减少不直接等于已测 WCT 加速。

{{dag_results}}

{{fig:ablation-normal-wct}}

{{fig:ablation-lazy-refresh}}

### 真实 GPU 组件：显存占用与 DMA 干扰

图 {{ref:native-forward-b1}}、{{ref:native-forward-b4}} 在真实 L40S 上分开测量 Peer 输入、输出和 DRAM 写入。短 prompt、batch 1 条件的 Peer 输入会产生约 31% 的 forward 时长增加；这说明“有空余显存”与“复制不干扰推理”不是同一个条件。该结果用于增加一个明确的 30% 模型敏感性扩展，未将 L40S 组件数值直接标定为 A100 三系统 WCT。

{{row:native-forward-b1,native-forward-b4}}

图 {{ref:native-memory-occupancy}} 改变额外触达分配量，图 {{ref:native-release-ack}} 测量 fence 与 allocator 释放完成；其范围限于本模型、batch、长度和一次独占 GPU 分配。[实测复制 CPU 需求](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.pdf)显示，本微基准并发复制时进程平均使用约 1.9–2.0 核，无复制时约 1 核；其中包含复制线程与 CUDA 同步等待，不能当作原生 AegisKV 准入算法的 CPU。原生服务的跨线程调度和完整回收路径仍需单独测量。[并发有效复制速率](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.pdf)也作为补充保留。

{{row:native-memory-occupancy,native-release-ack}}

### Guarded AIMD 与配置敏感性

在明确设置的 30% DMA forward 时长系数下，图 {{ref:aimd-quota-and-occupancy}} 同时画出允许上限和真实占用，图 {{ref:aimd-warning-windows}} 比较动态反馈与静态 Peer。预警窗口比例是控制信号，不是请求 SLO 违约率；它与[三方式 WCT 消融](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.pdf)共同检验控制结果，不能从额度下降本身推断性能改进。

{{aimd_results}}

{{fig:aimd-quota-and-occupancy}}

{{fig:aimd-warning-windows}}

最后用图 {{ref:sensitivity-bandwidth}}、{{ref:sensitivity-dram-capacity}} 检查共享带宽与 DRAM 容量。只连接实际执行的设置，不将少数点拟合成普遍规律。[并发 16/32](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.pdf)、[CPU 报价 1×/2×](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.pdf)与[DMA 0/5/30%](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.pdf)的独立图保留在补充材料。

{{row:sensitivity-bandwidth,sensitivity-dram-capacity}}

### 用故障收益偿还正常开销的条件

图 {{ref:benefit-cost-fault-mixture}} 将已执行的无故障均值与三个故障条件做显式概率混合，直接回答在当前模型假设下，故障收益何时可能抵消正常服务代价。横轴概率与三个位置等权都是分析假设；图中若没有交点，也保留这一结果，不外推到未测的多次故障或故障频率。

{{mixture_results}}

{{fig:benefit-cost-fault-mixture}}

### 当前证据支持什么，还缺什么

本轮已经把用户修订的两个算法落实到可执行的模拟路径，补上 Agent 跨请求与并行分支、Q 的完整尾块检查、联合 DAG 分账、同轮信用、独立 AIMD、三系统配对、详细资源计量、故障位置、惰性/门限/DAG/静态控制消融，以及真实 GPU 组件干扰与释放测量。旧 PrefixAdmission 结果完整归档，没有重标为新算法。**当前结果支持惰性计算减少、部分故障增量下降和强争用下动态控制的机制效果，但三组主故障条件的 AegisKV 平均 WCT 仍高于 Mooncake，未证明总体端到端收益。**

仍不能据此宣称原生 AegisKV 已获得端到端收益：三系统实际服务的 WCT/吞吐/CPU/故障恢复、在线预测器误差与校准、更多真实 workload 和多故障/多节点泛化尚缺独立证据。DAG 时长估计和 DMA 系数也没有经过统一硬件标定。当前论文应将对应定量结论明确写为机制模拟或组件微基准，保留所有负结果，并以这些缺口决定完整系统投稿前的后续实验。

[逐图 CSV 与来源选择清单](../../../output/agent-lease-20260908/paper-selection.json) · [独立图 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-figures.tex) · [可选并排 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-pairs.tex) · [实际插入尺寸校样](../../../output/pdf/aegiskv-agent-lease-20260908/paper-placement.pdf) · [完整核对记录](../../../output/agent-lease-20260908/DELIVERY_AUDIT.json)
