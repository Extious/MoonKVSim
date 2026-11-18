# AegisKV：面向多 Agent Workflow 的 KV 保护

<!-- 正文源：experiments/scripts/paper/templates/agent-lease-draft.md。
沿用 paper/sections/{motivation,system-design,experimental-method,results}.tex 的论证结构；
定量结果仅来自 Agent-lease source-v3 冻结实验，算法 2 后续调整不在本节实验的覆盖范围内。
图像来源、版本映射和复现入口见 PAPER_FIGURE_REVIEW.md，不属于论文正文。 -->

## Motivation

### Workflow 的恢复代价取决于依赖关系

多 Agent 应用将一次任务分解为相互依赖的模型调用、工具调用和控制结点。并行分支可以独立推进，但汇合结点必须等待所有前驱完成。因此，一次 GPU 故障对用户可见完成时间的影响，不仅取决于丢失了多少 KV，还取决于故障发生在哪条分支，以及其他分支尚需执行多久。我们以 Workflow Completion Time（WCT）作为保护目标，即从 Workflow 首个请求释放到最后一个请求完成的时间。

我们分析公开 [CC/Weka 执行轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)中具有同时重叠分支的 124 个 Workflow，对每个 Workflow 取最长与最短并行分支的最大持续时间差。图 {{ref:motivation-branch-gap}} 显示，这一差值跨越多个数量级，说明分支执行时间具有明显的不均衡性。该统计描述已观测到的执行差异；实际能够吸收恢复暂停的时间，还受到故障时刻、后续依赖和资源排队的影响。

考虑一个分支，其恢复需要额外时间 $T_i$，而当前到汇合点的可用时间余量为 $s_i$。在其他分支执行不变的条件下，暴露给 Workflow 的延迟可近似为

$$
J_i=\max(0,T_i-s_i).
$$

当 $T_i\le s_i$ 时，重算可被并行执行吸收；当分支位于关键路径上时，恢复暂停会直接推迟汇合。多个分支共享 KV 或同时受影响时，关键路径可能随恢复状态改变，逐分支相加的重算时间因而不足以表达联合收益。保护策略需要比较同一 Workflow 在不同可恢复前缀下的完成时间。

### 保护副本与正常推理竞争资源

KV 副本本身具有显著的空间成本。设模型有 $L$ 个注意力层、每层 $h_{\mathrm{kv}}$ 个 KV head、head dimension 为 $d$，每个元素占用 $b$ 字节，则每个 token 的 KV 大小为 $2Lh_{\mathrm{kv}}db$。对于本文采用的 [Qwen3-8B](https://arxiv.org/abs/2505.09388) BF16 布局，这一数值为 147,456 B/token，一个 4,096-token chunk 占用 576 MiB。

图 {{ref:motivation-kv-capacity}} 展示上下文增长时的副本容量：96 Ki tokens 的一份 KV 占用 13.5 GiB，两份占用 27 GiB。对一张 40 GiB GPU，仅扣除权重和固定运行时空间后，两份长上下文副本就可能超过剩余容量；正常推理仍需在此基础上分配动态 KV。Peer GPU 的空闲显存因此只能作为可撤销的备份空间，不能被视为静态、专用的缓存容量。

{{row:motivation-branch-gap,motivation-kv-capacity}}

DRAM 和 Peer HBM 的代价也不同。改变 DRAM 保留策略会影响后续请求的前缀命中，而 Peer 备份同时消耗源端读取、目标端写入及互连带宽。即使容量足够，复制仍可能延长 GPU forward，准入与回收也会增加 CPU 工作量。AegisKV 因此需要同时满足三项要求：以 Workflow 的恢复收益分配保护空间；对共享物理 KV 只计一次容量和联合收益；根据前台需求撤销 Peer 显存借用，并以物理释放完成作为复用内存的依据。

## System Design

### 系统架构与故障模型

AegisKV 将应用层的 Workflow 信息、请求执行所有权和物理 KV 保护分开管理。应用层维护当前可见的依赖图与 Agent 状态，Router 跟踪请求所在的源 Worker，保护控制器在密封的 KV chunk 上执行准入和保留决策。图 {{ref:system-overview}} 给出两条独立的数据路径：源 Worker 可将同一 chunk 分别复制到 Peer HBM 和 Store DRAM，每个目的地独立分配空间、执行复制并确认提交。一个层级的缺失或拒绝不会使另一个已提交副本失效。

本文考虑执行 Worker 的 fail-stop 故障：故障导致该 Worker 的本地 KV 丢失，应用层、Router 与控制器继续运行。备份须位于独立于故障源的目标上，并匹配模型、KV 数据类型、布局与完整分片身份。恢复前，Router 撤销旧路由的执行权限，避免迟到的提交污染新执行。本文的评估配置使用 TP=PP=1；控制面故障、网络分区和跨布局恢复不属于该故障模型。

{{fig:system-overview}}

### 以因果可见的剩余工作估计保护价值

应用层在请求或工具返回时更新剩余 DAG。对正在执行的结点，代价接口给出剩余执行时间；对已经可见但尚未启动的结点，接口给出完整执行时间；纯结构结点的权重为零。沿拓扑序计算最早开始时间，再反向计算最迟开始时间，可得到分支的可用时间余量。对预测余量扣除校准裕量，并随时间衰减，有助于减少过期估计带来的过度保护。

这一接口对应 Algorithm 1 的 GBDT–CPM 设计。未知分支不预先计价；结构或预测缺失时，系统撤销相应余量信息。预测出的余量不是未来进度的保证，调度与故障恢复仍可能改变关键路径。本文实验使用轨迹时长构造该代价接口，学习型预测器的在线误差与校准独立于本节机制评估。

### 从联合 WCT 改善到 Agent 子租约

Algorithm 2 在每个备份池中维护具有前缀依赖的物理 chunk，以及引用这些 chunk 的 Agent 子租约。一个共享 chunk 只占用一次物理容量，而每个仍然有效的 Agent 引用记录自己的生命周期、当前请求轮号和剩余信用。对 Agent $a$，恢复代价 $T_a(k_a)$ 由当前可恢复前缀和已经产生的 KV 决定；新生成 chunk 的评价不预支未知输出，已有 chunk 的评价则保留已经产生后缀的恢复成本。

为了避免共享分支重复计价，我们将同一 chunk 的恢复改善逐个加入对应 DAG。设 $F_0$ 是加入任何改善之前、受影响 Workflow 的剩余 WCT 之和，$F_j$ 是按固定 Agent 顺序加入前 $j$ 个改善之后的该总和，则第 $j$ 个 Agent 的收益份额与物理 chunk 的总收益分别为

$$
W_{a_j,x}=F_{j-1}-F_j,\qquad
G_x=\sum_{j=1}^{m}W_{a_j,x}=F_0-F_m.
$$

图 {{ref:design-joint-wct}} 中，两条分支共享一个 chunk。加入第一个分支的恢复改善后，另一个分支仍决定汇合时间，WCT 保持 12 ms；加入第二个改善后，WCT 才降到 10 ms。因此两个子租约分别获得 0 和 2 ms 的收益份额，总和等于一次联合改善。该分账使用固定顺序保证可重复性，并不声称是最优或唯一的收益分配。

{{fig:design-joint-wct}}

对于大小为 $b_x$ 的 chunk，Agent 的价值密度为 $P_{a,x}=W_{a,x}/b_x$。收益份额决定新额度，剩余信用 $c_{a,x}$ 则记录其中尚未支付给容量竞争的部分。物理 chunk 的总剩余信用为 $\mathrm{Credit}_x=\sum_a c_{a,x}$；它与 $G_x$ 的含义不同，不能在普通刷新时直接恢复为当前总收益。

图 {{ref:design-agent-subleases}} 展示跨请求的信用演化。共享尾块 X 的两个子租约最初为 6 和 4，收租后降为 4.8 和 3.2。当只有 Agent A 进入新的请求轮次时，A 的信用更新为 6，B 继续保留 3.2。同一 Agent 在同一轮重复命中不会补回已支付的信用；一个引用结束也不会清除其他仍然有效的引用。

{{fig:design-agent-subleases}}

容量竞争只在可释放尾块集合 $Q$ 上进行。内部前缀、读取固定的块以及本次复制依赖的前缀不参与收租。每次竞争前，系统检查 $Q$ 中全部尾块的输入版本；版本不变时复用价值计算，发生变化时才刷新收益与符合条件的子租约。惰性计算减少重复求值，但不省略对竞争对象的检查。

准入使用临时账本计算容量释放与联合恢复损失。设候选收益为 $G_x$，拟淘汰集合的条件损失为 $D_Y$：无需淘汰时允许 $G_x\ge0$，发生替换时要求 $G_x>D_Y$。每次试删都在当前临时前缀上重新评价受影响的 Workflow。版本核验通过后，系统提交账本变更；物理释放完成后才为新副本分配地址，复制确认后才将其用于恢复。后续复制失败不会恢复已经释放的旧数据。

### 独立控制 Peer 显存借用

Algorithm 3 根据目标 GPU 的前台资源状态控制备份可用显存上限，独立于 Algorithm 2 的价值、信用与尾块集合。控制器区分三个量：硬上限 $C(t)$、允许借用额度 $Q(t)$ 和仍然占用物理空间的备份字节 $U(t)$。其中，$C(t)$ 在固定开销、当前前台分配、下一步新增需求及保留量之外计算，并受策略上限与分配器实际可借容量限制。

图 {{ref:design-guarded-aimd}} 使用同一张 40 GiB 显存布局说明这些区别。稳定且存在备份需求时，控制器在上一轮调整完成后逐步增加额度；forward 预警触发乘法退让；前台新增需求直接裁剪硬上限。撤销额度只改变分配权限，已经提交、复制中或回收中的对象仍计入 $U(t)$，直到释放确认到达。

本文配置每 50 ms 形成一个有效观测窗口，连续四个稳定窗口后至多增加 1 GiB，预警时将额度减半。无效或过期观测撤销借用权限。前台分配检查实际物理可行性，而不是仅检查发布后的较小额度。该机制约束显存使用；复制引起的执行干扰还需通过反馈与独立测量评估。

{{fig:design-guarded-aimd}}

### 独立提交与完整恢复终点

备份从分配到释放依次经历复制中、已提交和回收中等状态，物理占用始终包含尚未完成的操作。复制完成消息绑定对象身份、路由版本与分配代次，过期确认不能释放或发布新一代对象。读取固定和 DMA 结束之前，目标地址保持占用。

图 {{ref:commit-tier-timeline}} 中，源端故障发生在同一个 C1 的 Peer 确认与 DRAM 确认之间。Peer 可提供 C0–C1，DRAM 只可提供 C0；DRAM 的 pending C1 不具有恢复资格。恢复 Worker 首先分配新的 primary KV，再装入兼容的连续已提交前缀，重算缺失后缀，最后恢复解码。备份内存与恢复 primary 是两份不同的物理分配。

{{fig:commit-tier-timeline}}

这一执行路径也决定了评估终点。前缀装入完成仅表示恢复输入就绪，后续重算、调度等待以及 Workflow 的其他分支仍可能决定用户可见完成时间。我们因此同时测量前缀装入、恢复解码和完整 Workflow 的 WCT。

## Evaluation

### 实验方法

我们通过轨迹驱动的离散事件模拟和真实 GPU 组件微基准，分别评价保护策略的 Workflow 行为与物理资源干扰。模拟实验固定 Agent 子租约和 Guarded AIMD 的 source-v3 参考版本；本节数值不覆盖 Algorithm 2 此后的设计调整。GPU forward 使用既有轨迹服务模型，CPU 准入与派发报价进入共享控制器队列。模拟时序尚未按目标平台完成统一硬件标定，因而用于机制比较，不作为原生部署的性能测量。

**工作负载。** 我们从 [FanOutQA](https://aclanthology.org/2024.acl-short.2/) 的问题、分解和证据构造 160 个完整 Workflow，共 1,304 个原始模型请求。使用固定 Qwen3-8B tokenizer 保持跨系统 prompt 与前缀身份一致；请求时长和输出由输入协议规定。图 {{ref:workload-prompt_tokens}} 和图 {{ref:workload-workflow_call_counts}} 分别给出 prompt 长度与每个 Workflow 的调用数。最大总上下文为 86,214 tokens，每个 Workflow 最多包含 27 次原始调用。

为了同时观察冷访问和跨请求复用，我们对每个完整 DAG 执行两轮受控精确重访，共处理 2,608 个请求。这种重访构造提供明确的共享前缀压力，不代表真实用户重访频率。三系统在同一配置下使用相同 token、DAG 和入场顺序；闭环调度默认最多允许 16 个活跃 Workflow。

{{row:workload-prompt_tokens,workload-workflow_call_counts}}

**比较对象。** Mooncake 基线在模拟器中采用共享前缀 LRU DRAM Store；DRAM-only AegisKV 使用相同平台上的 Agent 子租约保护策略，但关闭 Peer HBM；完整 AegisKV 在相同 DRAM 策略上增加 Peer HBM 与独立动态控制。DRAM-only 是隔离 Peer 作用的消融，而非 Mooncake 的另一种名称。三者共用正常执行、路由、复制提交和故障恢复路径。

| 参数 | 默认配置 |
|---|---|
| 模型与并行方式 | Qwen3-8B BF16，DP=8，TP=1，PP=1 |
| GPU 显存 | 每张 40 GiB，共 8 张 |
| DRAM Store / 共享路径 | 1 TB / 25 GB/s，十进制单位 |
| KV chunk | 4,096 tokens，即 576 MiB |
| 活跃 Workflow | 16 |
| Peer 策略上限 / 前台保留量 | 每 GPU 8 GiB / 1 GiB |
| 动态控制 | 初始额度为零；50 ms 窗口，四个稳定窗口后增 1 GiB，预警减半 |
| 无故障与故障条件 | F0：无故障；F1：一次执行 GPU 故障，持续 120 s |

**故障与配对。** 故障焦点在运行处理组之前从 Mooncake F0 轨迹选定：选择基准完成进度最接近 25%、50% 和 75% 的合格第一轮长请求，在该请求 prefill 完成 60% 时触发故障。三个选点对应基准已完成 40、80 和 121 个 Workflow。不同系统针对同一逻辑请求与同一 prefill 进度执行干预，实际路由、绝对故障时刻和同卡受影响请求可以不同。

设 $W_{s,i}^{F}$ 为系统 $s$ 中 Workflow $i$ 在条件 $F$ 下的 WCT。我们分别报告正常服务差值 $W_{s,i}^{F0}-W_{\mathrm{Mooncake},i}^{F0}$、原始故障 WCT，以及配对故障增量

$$
\Delta_{s,i}=W_{s,i}^{F1}-W_{s,i}^{F0}.
$$

WCT 不包含活跃 Workflow 名额以外的入场等待。所有逐 Workflow 图按 seed 0 Mooncake F0 的同一 ID 序列排列，折线连接相邻对象，并非时间序列。TTFT 从请求释放到首 token，TPOT 则先在每个请求内计算首 token 之后的平均间隔。cache hit rate 采用实际复用 token 占全部 prompt token 的比例。

主矩阵包含 47 次完整执行，30% DMA 敏感性扩展另包含 4 次，共 51 次；每次执行均处理完整输入。不同配置与跨图复用的同一次执行不作为额外重复。seed 1、2 只改变同一批 Workflow 的入场顺序；相应包络描述顺序敏感性，不构成跨独立部署的置信区间。

### 无故障开销与逐 Workflow 差异

图 {{ref:f0-revisit-wct}} 对齐三个系统的全部 160 个 Workflow，图 {{ref:f0-revisit-wct-difference}} 给出同一对象相对 Mooncake 的 WCT 差值。完整 AegisKV 的平均 WCT 为 {{aegis_wct}} s，相对 Mooncake {{overhead}}。DRAM-only 的均值也高于基线，说明本配置下保护策略自身已经改变了正常服务代价，Peer 并非全部差异的来源。

{{healthy_results}}

{{fig:f0-revisit-wct}}

{{fig:f0-revisit-wct-difference}}

差异并不均匀分布：DRAM-only 和 AegisKV 分别有 85 和 77 个 Workflow 慢于 Mooncake，少于或接近总体的一半，但均值仍然增加。部分对象的较大延迟决定了聚合结果，因此我们同时保留绝对曲线和配对差值。整批输入的最终完成时间分别为 538.054、558.683 和 569.892 s，与平均 WCT 的变化方向一致。

### DRAM 准入对正常复用的影响

图 {{ref:f0-revisit-dram-hit}} 显示，改变保护价值与保留策略会改变同一 Workflow 的正常前缀命中。Mooncake、DRAM-only 和 AegisKV 的整体 DRAM token 命中率分别为 47.13%、40.78% 和 41.12%。AegisKV 相对 Mooncake 下降约 6.01 个百分点，表明以恢复价值为目标的保留规则在当前受控重访输入上付出了正常复用代价。

{{fig:f0-revisit-dram-hit}}

图 {{ref:f0-revisit-cache-sources}} 将全部 prompt token 分解为 Local HBM、Store DRAM、Peer HBM 和重新计算。三个系统的正常 Peer 命中均为零；AegisKV 的 Peer 写入属于保护活动，没有在该输入上形成额外的正常服务复用。其重新计算比例为 57.51%，高于 Mooncake 的 51.67%。这一分解说明，副本写入量与正常 cache hit 是不同的指标。

{{fig:f0-revisit-cache-sources}}

### HBM 压力、排队与请求延迟

我们将前台 HBM 分配等待与 GPU-ready 后的调度等待分别计量。图 {{ref:f0-revisit-scheduler-queue}} 和图 {{ref:f0-revisit-hbm-wait}} 给出每个 Workflow 内请求的平均等待，图 {{ref:f0-revisit-hbm-pressure}} 则按 GPU 统计 FREE 低于 1 GiB 的时间比例。后者反映显存余量，不直接表示 OOM 或 HBM 带宽饱和。

{{fig:f0-revisit-scheduler-queue}}

{{fig:f0-revisit-hbm-wait}}

{{fig:f0-revisit-hbm-pressure}}

在默认配置下，三个系统累计前台 HBM 等待分别为 188.634、150.208 和 116.597 s；请求级调度等待 P95 分别为 10.908、11.614 和 10.444 s。该结果没有显示开启 Peer 必然增加这两类等待。由于 DRAM 命中、入场进度和批处理组合同时变化，这些跨系统差异不能单独识别 Peer 的因果作用；后续静态控制消融和真实 DMA 微基准进一步分离其影响。

图 {{ref:f0-revisit-ttft-cdf}} 和图 {{ref:f0-revisit-tpot-tail}} 从请求端检查服务质量。AegisKV 的 P99 TTFT 为 22.653 s，低于 Mooncake 的 23.202 s，但平均 Workflow WCT 更高，说明请求尾部与依赖图的整体完成时间并不等价。TPOT 曲线包含 2,432 个定义有效的请求均值，描述请求之间的尾部差异。

{{row:f0-revisit-ttft-cdf,f0-revisit-tpot-tail}}

### 控制计算与传输争用

图 {{ref:reference-cpu-breakdown}} 测量参考实现的线程 CPU 时间，并按前台派发、准入与 DAG、提交、回收与 AIMD 分解。复杂保护策略增加的工作不仅发生在准入时，也发生在状态提交和物理回收时。该测量用于定位参考实现的计算组成，不能直接外推为原生服务进程的 CPU 利用率。

{{fig:reference-cpu-breakdown}}

图 {{ref:f0-revisit-controller-breakdown}} 单独报告已经进入模拟事件时序的 CPU 服务需求。三个系统的累计服务需求分别为 3.743、18.335 和 27.729 s。这里使用固定报价和共享控制器队列；提交、回收和 AIMD 的全部参考 CPU 时间尚未全部转换为模拟延迟。因此，正常 WCT 已包含一部分控制成本，但并非完整原生 CPU 开销的测量。

图 {{ref:f0-revisit-traffic-breakdown}} 同时区分正常 GET、DRAM 写入与 Peer 复制。AegisKV 产生约 0.109 TiB 的 Peer 流量，而正常 GET 与 DRAM 写入合计约 6.488 TiB。与 Mooncake 相比，其正常 GET 字节较少但 token 命中率也较低：未命中的 token 转为重算，减少读取量本身不构成缓存收益。

{{row:f0-revisit-controller-breakdown,f0-revisit-traffic-breakdown}}

图 {{ref:f0-revisit-transfer-service_slowdown}} 进一步将每次正常 GET 的实际服务时长除以同字节量独占路径时长。三个系统的 P95 倍率分别为 27.21、22.53 和 21.20，表明共享路径内存在显著的模拟争用。由于命中策略改变了发起 GET 的对象总体，分布之间的差异同时包含流量构成与共享服务的变化。

{{fig:f0-revisit-transfer-service_slowdown}}

### 故障恢复与 Workflow 完成时间

图 {{ref:f1-q50-workflow-penalty}} 展示中期故障下全部 Workflow 的配对增量。多数在故障前已经完成的对象不受影响，仍在执行的对象则会受到恢复与调度重排的共同作用。部分增量为负，反映故障干预后闭环批处理和资源竞争发生变化，不能解释为故障本身改善了服务能力。

{{fig:f1-q50-workflow-penalty}}

下表同时报告三种故障位置的绝对 WCT 与配对增量。AegisKV 在中期故障下的平均增量为 0.483 s，小于 Mooncake 的 0.874 s；但其绝对平均 WCT 为 55.713 s，仍高于 Mooncake 的 53.516 s。较小的故障增量没有抵消正常服务开销。

{{fault_results}}

图 {{ref:failure-focal-recovery-phases}} 将预先选定请求的恢复分为“故障至连续前缀装入”和“装入后至恢复解码”两段。早期选点中，AegisKV 的焦点恢复为 2.197 s，短于 Mooncake 的 6.923 s；中期选点则分别为 1.717 和 1.352 s，排名发生反转。三个主选点中 AegisKV 的焦点请求均未从 Peer 恢复 token，因此不能将这些焦点差异全部归因于 Peer 读取速度。

{{fig:failure-focal-recovery-phases}}

图 {{ref:failure-progress-p95-penalty}} 给出逐 Workflow 增量的 P95。AegisKV 在三个位置分别为 25.498、15.732 和 13.069 s，均低于相应 Mooncake 值；与 DRAM-only 相比，其晚期尾部增量略高。百分位统计包含全部 160 个 Workflow，故障位置越晚，已经完成的对象越多，跨位置曲线因此不等于单次恢复难度随时间下降。

{{fig:failure-progress-p95-penalty}}

### 入场顺序与价值策略消融

图 {{ref:order-normal-wct}} 和图 {{ref:order-failure-penalty}} 使用相同对象的三个预定入场顺序，分别展示正常 WCT 与配对故障增量。每个经验分位的线和阴影表示三个顺序的中位数及最小、最大值。分布的大部分区域接近，但尾部和个别 Workflow 会随调度顺序改变；这些结果将前述比较限定在固定输入及其入场排列上。

{{row:order-normal-wct,order-failure-penalty}}

我们进一步分别替换联合 DAG 价值、将空闲准入条件改为严格正收益，以及固定 Peer 容量。图 {{ref:ablation-normal-wct}} 显示，严格正收益门将 F0 平均 WCT 提高到 63.691 s，而去掉 DAG 联合价值的版本降至 53.065 s。正常开销的下降仍需结合故障行为解释：在配对中期故障下，联合 DAG 价值的平均增量为 0.483 s，简单恢复时间求和为 1.743 s，但后者的绝对 F1 WCT 仍较低。该消融揭示恢复增量与日常成本之间的取舍，尚未建立联合价值在总体完成时间上的优势。

{{dag_results}}

{{fig:ablation-normal-wct}}

图 {{ref:ablation-lazy-refresh}} 隔离惰性求值的计算效果。Lazy 与 Eager 均检查 299,957 个可释放尾块，完整的接纳、拒绝及牺牲块序列一致；Lazy 仅执行 8,087 次价值计算，相对 Eager 减少约 97.3%。该优化复用版本未变的结果，保留相同决策路径。由于消融使用相同 CPU 报价，计算次数减少不直接转换为该实验中的 WCT 加速。

{{fig:ablation-lazy-refresh}}

### 真实 GPU 上的容量与复制干扰

我们在一次独占的两张 L40S 分配上运行真实 Qwen3-8B BF16/SDPA forward，测量 Peer 输入、Peer 输出、DRAM 写入和无复制四种条件。batch、prompt 长度、额外触达分配量与复制方式组成 72 个条件；每个条件在五个随机交错测量块中各测量一次，共 360 个 forward 样本。图中标记为中位数，误差线为观测最小值与最大值。这些测量块共享同一次设备分配。

图 {{ref:native-forward-b1}} 和图 {{ref:native-forward-b4}} 按相同测量块内的无复制 forward 归一化。512-token prompt、batch 1 下，Peer 输入的 forward 时长倍率中位数对应 32.2% 的增幅；batch 4 下对应增幅为 9.6%。较长 prompt 的倍率更接近 1。干扰依赖复制方向与执行条件，不能仅依据可用显存判断备份是否影响推理。

{{row:native-forward-b1,native-forward-b4}}

图 {{ref:native-memory-occupancy}} 在 batch 4、4,096-token prompt 下，将额外触达分配从 0 增加到 8 和 16 GiB，分别比较容量占用与并发复制。整个组件实验没有出现 OOM；这一观察只覆盖所测分配与请求范围，不给出任意负载下的显存安全保证。

图 {{ref:native-release-ack}} 对 1、4 和 8 GiB 对象各测量 20 次释放，分别记录在途写入 fence 和分配器释放完成。两阶段均消耗非零时间，且随释放大小变化。这支持系统设计中将“撤销额度”和“内存已经可用”分开的处理方式。

{{row:native-memory-occupancy,native-release-ack}}

### 动态控制与资源敏感性

为检验复制干扰下的控制行为，我们在模拟器中显式设置 30% 的额外 forward 时长系数。该设置参考组件测量中观察到的干扰幅度，但不是从 L40S 到模拟平台的端到端标定。图 {{ref:aimd-quota-and-occupancy}} 按 50 ms 窗口汇总八张 GPU 的硬上限、授权与物理占用；图 {{ref:aimd-warning-windows}} 比较 Guarded AIMD 与保留相同显存硬上限的静态 Peer 控制。

{{fig:aimd-quota-and-occupancy}}

{{fig:aimd-warning-windows}}

动态控制在该条件下的平均 WCT 为 53.929 s，静态 Peer 为 55.017 s，下降约 1.98%；DRAM-only 为 53.970 s。动态反馈因而减轻了这一强争用假设下静态借用的代价，但相对 DRAM-only 的差异很小。图中的预警比例是控制器信号，而非请求 SLO 违约率。

{{aimd_results}}

图 {{ref:sensitivity-bandwidth}} 将共享带宽设为 5、25 和 50 GB/s。5 GB/s 下 AegisKV 与 Mooncake 的平均 WCT 分别为 73.876 和 75.123 s，而在 25 与 50 GB/s 下 AegisKV 更慢，表明相对排名会随带宽条件改变。图 {{ref:sensitivity-dram-capacity}} 将 DRAM 从 250 GB 增加到 1 TB，三系统的 token 命中率均提高，但 AegisKV 在两个容量点都低于 Mooncake。这里仅连接实际评估的设置，不对其间或更大范围拟合趋势。

{{row:sensitivity-bandwidth,sensitivity-dram-capacity}}

### 正常成本与故障收益的综合关系

最后，我们考察故障增量是否足以抵消日常保护成本。设一次完整输入以概率 $p$ 经历一个故障，在三个预定位置之间等概率选择。用已评估结果构造条件期望

$$
\mathbb{E}[W_s(p)]=(1-p)\,\overline{W_s^{F0}}
+\frac{p}{3}\sum_{q\in\{25,50,75\}}\overline{W_s^{F1(q)}}.
$$

图 {{ref:benefit-cost-fault-mixture}} 展示这一解析混合。在 $p\in[0,1]$ 内，AegisKV 与 Mooncake 的曲线没有交点：无故障时 AegisKV 较慢，三个故障位置等权后的平均 WCT 也较慢。因此，在这一有限输入和单故障混合假设下，故障概率提高仍不足以抵消当前正常服务成本。该横轴是分析假设，不是部署环境中的实测故障率。

{{fig:benefit-cost-fault-mixture}}

本节结果支持三个具体机制现象：版本复用可在保持准入决策一致的同时减少价值求值，部分故障条件下的 Workflow 增量较小，以及强复制干扰下动态借用优于静态 Peer 容量。与此同时，默认无故障及三个主故障条件的绝对平均 WCT 均未建立 AegisKV 相对 Mooncake 的总体优势，DRAM 正常复用也存在明显损失。

这些结论的适用范围由实验方法限定：输入来自一组受控重访的 FanOutQA 派生 Workflow，恢复时序与干扰系数尚未统一标定，原生测量覆盖 GPU 组件而非三系统完整服务。进一步评价需要在固定算法版本上联合测量真实服务的 WCT、吞吐、控制 CPU 与故障恢复，并检验在线预测误差、更广泛的重访行为以及多故障场景。
