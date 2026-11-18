# AegisKV：面向多 Agent Workflow 的 KV 保护

<!-- 中文论文初稿；Motivation 3 图，System Design 1 图，Evaluation 按证据组织。
设计接口与历史 source-v3 结果分开；Algorithm 2 后续实现仍待冻结。
图稿、来源、复现与投稿证据缺口见 PAPER_FIGURE_REVIEW.md。 -->

## Motivation

### Observation 1：并行分支具有显著的执行时间差

多 Agent 应用将一次任务组织为模型调用、工具调用与汇合结点组成的依赖图。用户等待整个 Workflow 完成，而汇合结点必须等待所有前驱。因此，恢复时间的节省只有传递到依赖图的完成时间时，才产生用户可见收益。本文以 Workflow Completion Time（WCT）作为保护目标，即从 Workflow 首个请求释放到最后一个请求完成的时间。

公开 [CC/Weka 轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)提供了分支执行不均衡的观测依据。我们保留存在共同重叠区间的并行分支组，并对每个 Workflow 取最大的最长与最短分支持续时间差。图 1 中，124 个符合条件的 Workflow 的中位差值为 140.6 s，P90 为 1,570.3 s。这说明不同分支距汇合完成的时间余量可能相差很大；持续时间差本身并不等于故障时刻可使用的 Slack。

### Observation 2：重算代价的排序不等于 Workflow 损失的排序

图 2 使用同一个五分支轨迹示例，分离恢复暂停中被并行执行吸收的部分与推迟汇合的部分。对每条分支分别在 349.5 s 假设一次故障，保持其他分支的执行不变。若恢复增加的时间为 $T_i$、分支到原汇合终点的间隔为 $s_i$，暴露的延迟为

$$
J_i=\max(0,T_i-s_i).
$$

A3 的假设重算时间最长，为 46.6 s，但其 52.4 s 的间隔可吸收全部暂停；A4 的重算时间较短，为 35.9 s，却因处于关键分支而全部暴露给 Workflow。仅按 KV 大小或重算时间选择保护对象，可能把资源分配给不改变完成时间的分支。保护优先级需要结合 Agent 的执行位置、恢复代价与剩余 Slack。

<a id="paper-motivation-branch-gap"></a>
<a id="paper-motivation-recovery-exposure"></a>

| **图 1：并行分支的执行时间不均衡** | **图 2：重算代价与 Workflow 损失并不等价** |
|---|---|
| [<img src="../figures-legacy/aegiskv-revision-20260909/motivation-branch-gap.png" width="480" alt="1 并行分支的执行时间不均衡">](../figures-legacy/aegiskv-revision-20260909/motivation-branch-gap.pdf) | [<img src="../figures-legacy/aegiskv-revision-20260909/motivation-recovery-exposure.png" width="480" alt="2 重算代价与 Workflow 损失并不等价">](../figures-legacy/aegiskv-revision-20260909/motivation-recovery-exposure.pdf) |
| CC/Weka 中 124 个具有重叠分支的 Workflow；每个对象取最大分支持续时间差。横轴为对数秒。该观测描述不均衡，不直接估计可用 Slack。 | 同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。 |

图 2 是轨迹锚定的反事实算例。其暂停参数沿用旧 Qwen3-235B/A100 模型预测，不能作为可部署并行配置的性能测量；该旧预测的 PP 配置未获得物理验证。这个算例说明评价目标的差别，不估计部署收益。真实故障还会改变排队和其他分支的进度，因而后文同时检查恢复过程与完整 WCT。

### Observation 3：长上下文放大故障后的重算代价

Agent 在多轮模型调用中积累上下文；当执行该请求的 GPU 故障，未保留的 KV 必须重新计算。图 3 固定模型和并行配置，只增加需要重建的前缀长度。上下文从 16 Ki 增至 128 Ki tokens 时，Qwen3-8B 的完整前缀重算预测由 0.49 s 增至 9.16 s，Qwen3-32B 则由 1.72 s 增至 32.82 s，分别增长 18.7 与 19.1 倍。

<a id="paper-motivation-recompute"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/motivation-recompute.png" width="480" alt="3 长上下文的完整前缀重算代价">](../figures-legacy/aegiskv-revision-20260909/motivation-recompute.pdf)

**图 3：长上下文的完整前缀重算代价。** 长上下文的完整前缀重算代价。Qwen3-8B 与 Qwen3-32B 在 A100-80GB、TP4/PP2、BF16 配置下，按 8 Ki-token 分块累加单请求 prefill 预测；Ki=1,024。每条线连接四个历史 AIConfigurator SILICON 配置预测点，无故障运行或重复测量。

</figure>

长上下文使一次故障后的状态重建成为不可忽略的计算开销。它能否转化为同等幅度的 Workflow 延迟，仍取决于分支 Slack、恢复来源与排队。该图沿用旧论文的上下文—重算曲线，使用历史 AIConfigurator SILICON 预测；不包含检测、传输、排队或故障实测，也不与后文 DP8/TP1 模拟混合统计。

三条 Observation 导出 AegisKV 的设计目标：优先保护会影响 Workflow 终点的 Agent 状态，通过已提交前缀减少长上下文重算，并在有限的 DRAM 与 Peer HBM 中保留高价值副本。保护同时可能改变正常复用、占用前台显存并消耗 CPU 与带宽，因此其正常成本与故障收益必须共同评价。

## System Design

### 面向物理 KV 对象的系统架构

图 4 展示 AegisKV 的系统架构。应用侧提供当前可见的 Workflow DAG 与 Agent 状态；价值接口结合恢复代价与 Slack 更新 Agent 的保护优先级，池级准入决定保留哪些物理 KV chunk。目标 GPU 上的独立显存控制器根据前台需求和 forward 反馈约束备份借用。

<a id="paper-system-overview"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/system-overview.png" width="1008" alt="4 AegisKV System Overview">](../figures-legacy/aegiskv-revision-20260909/system-overview.pdf)

**图 4：AegisKV System Overview。** 工作流上下文生成 Agent 保护优先级，源端独立向 Peer HBM 和 DRAM 复制同名 KV；副本在复制 ACK 后可读。Peer 控制器独立约束备份借用。故障后从存活层恢复新 primary C0/C1，再重算 C2。彩色箭头为 KV 传输，虚线为控制，灰色 DAG 边为依赖。

</figure>

源 Worker 持有正常推理的 primary KV。密封的 C0、C1 独立复制到 Peer HBM 和 DRAM Store；每条路径分别分配空间、执行传输并确认提交。一层拒绝或丢失副本，不改变另一层已提交的同名对象。多个 Agent 共享 C0 时，同一存储池只计一份物理容量。Peer Worker 的前台 P0、P1 与备份 C0、C1 占用不同物理地址。

本文考虑执行 Worker 的 fail-stop 故障，其本地 KV 丢失，而应用层、Router 与其他故障域继续运行。Router 撤销旧执行权限，将请求迁移到原有的健康 Worker，不增加未计费的恢复 GPU。图中的 Peer 与恢复 Worker 表示角色，可以由同一健康设备承担。恢复过程在新的 primary 分配中装入兼容、连续、已提交的前缀，再重算缺失后缀并恢复解码。图中恢复的是 C0、C1，重算的是 C2；pending 副本不可读。副本身份包含模型、数据类型、布局和分片，不能跨不兼容布局复用。

### Agent 价值、共享对象与池级准入

价值接口随请求进度与工具返回更新可见的剩余 DAG。对正在执行的结点估计剩余时间，对已知但尚未开始的结点估计完整时间；未知分支不预先计价。分支 Slack 由当前依赖关系和剩余执行时间估计，并随执行更新，不作为未来执行不变的保证。

准入以物理块为容量单位，以 Agent 的价值和信用为保护依据。多个 Agent 引用同一块时，先分别更新各 Agent 的价值，再按当前信用规则归集到物理对象，不能把物理字节重复计费。候选块与可释放尾块之间进行容量竞争；在读、未完成复制或受前缀依赖约束的对象不因账面淘汰立即变成可用空间。

价值估计、账本提交、复制发布和物理释放具有不同的完成条件。试算不改变真实可读集合；复制 ACK 决定副本何时可读，释放 ACK 决定容量何时可复用。算法 2 的授信、刷新与排序细节仍在调整，本稿保留接口和不变条件；后文 source-v3 数值不作为后续修改版本的运行证据。

### 前台约束下的 Peer HBM 控制

Peer 控制器与价值及信用计算独立。它区分备份可用显存硬上限 $C(t)$、授权额度 $Q(t)$ 和仍占用物理地址的备份 $U(t)$。硬上限扣除固定开销、前台分配、下一步需求与保留量，并受实际分配器限制，授权满足

$$
0\le Q(t)\le C(t).
$$

稳定且有备份需求时，Guarded AIMD 逐步增加授权；forward 预警触发乘法退让，新的前台需求直接裁剪硬上限。降低授权不等于立即释放物理地址：pending、committed 和 reclaiming 字节都持续计费，直到 DMA fence 与释放完成。前台分配必须检查真实物理可行性。

这一区分也决定评估方式。前台缓存已经占满 HBM 时，安全控制器可能不允许 Peer 备份；此时不能用“系统配置了 Peer HBM”代替“故障时存在可用 Peer 副本”。恢复前缀装入完成后，后缀重算、调度等待与其他分支仍会影响最终 WCT。

## Evaluation

### 实验设置与证据范围

评估回答三个相连的问题：正常保护是否影响完整 Workflow 服务；可控故障下，已保留状态是否缩短同一 Workflow 的完成时间；并发与故障频率如何改变成本和收益。三条系列为 Mooncake、DRAM-only AegisKV 和 AegisKV。DRAM-only 保留 AegisKV 的 DRAM 准入并关闭 Peer，用于分离两类机制。

默认模型为 Qwen3-8B BF16，DP=8、TP=PP=1；模拟资源为 8×40 GiB GPU、1 TB DRAM Store、25 GB/s 共享路径，KV chunk 为 4096 tokens。输入包含 160 个 FanOutQA-derived Workflow，每个完整 DAG 执行两轮精确重访，共 2608 个请求，默认最大活跃 Workflow 数为 16。这是控制复用压力的负载构造，不代表生产重访频率。

F0 表示无故障，F1 表示一次预定故障。一次运行处理整套输入；逐 Workflow 图中的点是同一逻辑对象，完整运行的重复才用于估计运行间不确定性。本节图像使用冻结参考算法的离散事件模拟，GPU 时序尚未经过目标硬件标定；Mooncake 系列是共享引擎中的策略基线，不能称为完整原生 Mooncake 部署。新扩展只改变预定并发或故障注入，算法 2/3 保持冻结。

WCT 从 Workflow 首个请求释放计到 DAG 完成。同一配置下按 Workflow ID 配对，逐对象曲线沿用冻结 Mooncake F0 顺序，三系统不各自排序。并发限制在 Workflow 释放前产生的等待不含在该 WCT 中；因此扩展同时报告完成速率或批次时长，不能仅用较小的已准入 WCT 宣称吞吐改善。

### 正常服务：先检验开销，再解释离群点

图 5 展示同一 Workflow 相对 Mooncake 的 WCT 差值，单位为秒；零表示基准，正值表示更慢。相对百分比与原始时长保存在逐点数据中，全部 160 个对象和尾部均保留。用绝对差值可以直接判断增加了多少等待，不改变不利结果。

<a id="paper-eval-workflow-delay"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-workflow-delay.png" width="1008" alt="5 正常场景的逐 Workflow 绝对延迟变化">](../figures-legacy/aegiskv-revision-20260909/eval-workflow-delay.pdf)

**图 5：正常场景的逐 Workflow 绝对延迟变化。** 同一无故障配置的全部 160 个配对 Workflow，固定 Mooncake 顺序；每点为同 ID 相对 Mooncake 的 WCT 差值，负值更快。最大离群对象 3d0739b1 增加 129.6 s，未裁切尾部；完整 WCT 和相对百分比保留在 CSV。每系统一次冻结模拟，连线不是时间演化，也不表示重复实验置信区间。

</figure>

| 系统 | F0 平均 WCT (s) | TTFT P99 (s) |
|---|---|---|
| Mooncake | 52.642 | 23.202 |
| DRAM-only AegisKV | 54.158 | 21.302 |
| AegisKV | 55.230 | 22.653 |

当前 AegisKV 的平均 WCT 增加 4.92%，逐 Workflow 也存在明显退化，尚不支持“几乎无额外服务开销”。其中 Workflow `3d0739b161908b67` 从 Mooncake 的 25.553 s 增至 155.130 s，差值为 129.577 s，即 +507.1%。这不是百分比小分母造成的假象；完整 WCT 已由释放和完成时间核验。不同 Workflow 的固有长度差异很大，因此不再用全体原始 WCT 的 P95 解释某个故障或机制的影响。

图 6 比较第二轮精确重访中的逐 Workflow 初次 DRAM token 命中率，排除首轮冷访问。按重访 prompt token 加权，三系统分别为 94.257%、81.568% 和 82.245%，完整 AegisKV 下降 12.01 个百分点；两轮合计口径仍保留在数据中，为 47.13%、40.78% 和 41.12%。冻结准入以当前恢复价值驱动，未显式估计未来重访收益，因此不能假定它自然保持 LRU 的复用效果。初次读取成功只表示 KV 曾装入过；如果随后抢占丢失并重新 prefill，它并不等于最终避免了这些计算。

<a id="paper-eval-initial-reuse"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-initial-reuse.png" width="1008" alt="6 重访请求首次查询的 DRAM token 命中">](../figures-legacy/aegiskv-revision-20260909/eval-initial-reuse.pdf)

**图 6：重访请求首次查询的 DRAM token 命中。** 与前图相同的 160 个 Workflow 和排序，只统计第二轮 revisit-1；每个点以该 Workflow 第二轮全部 prompt token 为分母，排除首轮冷访问。三系统全局 token 加权命中率分别为 94.257%、81.568%、82.245%。首次查询命中不能代表抢占重算之后最终避免的计算量。CSV 同时保留两轮合计与重访口径的计数、分母和百分点差，不能等权平均 Workflow 得到全局值。

</figure>

图 7 跟踪上述最大离群 Workflow 的同一个长请求。AegisKV 在模拟绝对时刻 102.367 s 因 KV block 压力被抢占，直到 207.297 s 才重新进入 GPU，停顿约 104.929 s；随后需要从零重新 prefill。图内横轴对齐各系统该 Workflow 的首个释放时刻，因而与这些绝对时间不同。旧统计只记录首次入场前等待，漏掉了中途停算；它也保留了初次读取的 63,088 个 DRAM token，不能据此判断有效复用。

<a id="paper-eval-preemption-progress"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-preemption-progress.png" width="1008" alt="7 正常抢占使初次命中失效的具体轨迹">](../figures-legacy/aegiskv-revision-20260909/eval-preemption-progress.pdf)

**图 7：正常抢占使初次命中失效的具体轨迹。** 最坏 Workflow 3d0739b1 中同一个重访请求，三系统分别以该 Workflow 首次 release 为零对齐。阶梯仅由真实 scheduler prefill 步骤边界及已执行抢占的 token-counter 重置产生，不拟合中间吞吐。AegisKV 在全局 102.367 s 抢占，207.297 s 再准入，间隔 104.929 s；图中相对位置为 26.300–131.229 s。初次命中 63,152 token 后丢失进度并从 0 重算；这是无故障 HBM 压力抢占，不是故障注入。

</figure>

这条事件轨迹解释了该离群点中的长停顿。该抢占时刻附近的 Peer pending/committed 占用为零，因此不能直接归因于 Peer 副本挤占；路由顺序、正常缓存布局与调度竞争的贡献尚未隔离。下一轮机制实验需要同时计量每次入队/恢复入队、被丢弃的前缀和实际执行的 prefill token；不能仅通过改变绘图分母修复问题。

控制与传输成本按同一种指标列出绝对量，避免把平均等待、分位数和字节倍率画成一个可相加的总成本。

| 指标 | Mooncake | DRAM-only AegisKV | AegisKV |
|---|---|---|---|
| Python 参考控制 CPU (s) | 9.989 | 56.538 | 68.502 |
| 模拟入场/准入 CPU 服务需求 (s) | 3.743 | 18.335 | 27.729 |
| DRAM + Peer 写入 (TiB) | 3.549 | 3.471 | 3.643 |
| 正常 GET (TiB) | 3.386 | 2.930 | 2.954 |

Python 参考 CPU 与模拟服务报价来自不同计量过程，不能视为两个可相加阶段，也不代表原生服务进程的 CPU 利用率。GET 流量减少同时伴随命中下降，不能单独解释为带宽效率提高。正式“服务退化低于预定边界”结论仍需冻结阈值与独立配对重复，并测量逐 GPU 前台/备份占用、完整生命周期等待、真实 token 延迟以及逐路径争用；当前单次模拟不能完成该判断。

### 单次故障：同一 Workflow 的前后对照与恢复来源

图 8 对每个预选故障实例，同时展示同一个焦点 Workflow 的 F0 和 F1 WCT。每一行的空心与实心点属于同一系统、同一对象；跨系统比较 F1 终点，行内比较故障前后的增量。这样既保留故障代价，也不会将一个系统正常时已经较慢的部分隐藏在归一化分母中。

<a id="paper-eval-fault-paired-wct"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-fault-paired-wct.png" width="1008" alt="8 同一焦点 Workflow 的故障前后配对 WCT">](../figures-legacy/aegiskv-revision-20260909/eval-fault-paired-wct.pdf)

**图 8：同一焦点 Workflow 的故障前后配对 WCT。** C1–C3 分别为预选焦点 Workflow 98ced84a、220852c6、5aa09932；每组的三系统比较同一个对象。空心为无故障 F0，实心为单故障 F1，箭头连接本系统配对 WCT；近重合点直接标注差值。保留左向的负变化，不把调度差异解释为故障有益。历史协议只固定逻辑请求与 token 进度，未固定整个受害集合，因此不是新受控协议的因果结论。

</figure>

这三个历史实例在基准完成进度附近选定焦点请求，并在同一请求总 token 进度约 60% 时触发。三系统的焦点 Workflow 和源 GPU 相同，但完整受害请求集合并不相同，因而它们是自然混部下的配对诊断，尚不满足隔离直接受害者的新协议。负的 F1−F0 反映故障后调度发生变化，不能解释为故障本身有益。当前实例也没有展示一致的 AegisKV 完整 WCT 优势。

<a id="paper-eval-fault-token-source"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-fault-token-source.png" width="1008" alt="9 同一故障请求的恢复来源与重算量">](../figures-legacy/aegiskv-revision-20260909/eval-fault-token-source.pdf)

**图 9：同一故障请求的恢复来源与重算量。** 与配对 WCT 图相同的 C1–C3 和系统行序；每条柱为该焦点请求从 Peer、DRAM 恢复及重算的 token 数，Ki=1,024。Peer 的九条记录均为零，图例保留该来源但没有人为补出柱段。这些计数不包括后续 DAG 执行，不能单独解释完整 WCT，也不能把现有局部改善归因于 Peer。

</figure>

图 9 解释为何不能将这些结果归因于 Peer：三例焦点请求的 Peer 恢复 token 全部为零，故障前也没有焦点 Peer 准入事件。前两例故障前最近的 50 ms 控制采样中，八张 GPU 的备份硬上限、额度和物理备份均为零；第三例只有一张 GPU 存在非零硬上限，但当时物理备份仍为零。冻结实现从实际空闲字节扣除前台保留量后计算可借空间，不把可复用的正常 HBM cache 自动当成空闲容量。

因此，当前图表暴露的是“这三个焦点未形成可用于恢复的 Peer 副本”的条件；DRAM 保护已经参与恢复，不能把 Peer 缺位扩大为全部保护路径失效。后续单故障主实验应按输入预选短/长上下文及关键/非关键分支，固定焦点请求、故障域与 decode 边界，并逐例报告故障前连续已提交前缀、保护覆盖率、Peer 容量和被丢失 token。资源条件应同时覆盖无借用余量与有借用余量，不删除未形成保护或恢复无收益的案例，也不能等 AegisKV 复制完成后才注入。

### Workflow 并发扩展

并发扫描固定同一 160 个 Workflow、两轮重访、资源和输入顺序，只改变最大活跃 Workflow 数。图 10 展示完整批次完成速率 $160/T_{\mathrm{batch}}$，包含填充与排空，不等于带 SLO 约束的 goodput。图 11 则在最高并发 64 下，逐一比较相同 Workflow 相对同配置 Mooncake 的 WCT 差值，避免用异质 Workflow 的原始分位数代替对象级比较。

<a id="paper-eval-concurrency-throughput"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-concurrency-throughput.png" width="480" alt="10 并发扩展的完整批次完成速率">](../figures-legacy/aegiskv-revision-20260909/eval-concurrency-throughput.pdf)

**图 10：并发扩展的完整批次完成速率。** 固定 160 个 Workflow、两轮重访和相同资源，改变最大活跃 Workflow 数，横轴为 log2 刻度。完成速率为 160 除以完整批次时长，包含填充与排空；不是 SLO goodput。每个系统每点一次冻结算法模拟，无重复置信区间。

</figure>

<a id="paper-eval-concurrency-workflow"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-concurrency-workflow.png" width="1008" alt="11 并发64下同一 Workflow 的 WCT 差值">](../figures-legacy/aegiskv-revision-20260909/eval-concurrency-workflow.pdf)

**图 11：并发64下同一 Workflow 的 WCT 差值。** 最高并发 C=64 时，同一无故障配置下全部 160 个 Workflow 的配对 WCT 差值：每个系统减去同 ID、同 C64 的 Mooncake WCT，负值更快。横轴为 C16 Mooncake 无故障 WCT 固定排序的 Workflow，不是并发轴；排序与正常开销图一致。三系统每个各执行一次，两轮精确输入复访；连线仅连接对象，无跨重复置信区间。AegisKV 有 65 个 Workflow 更快、95 个更慢，全部正负尾部均保留；CSV 保存绝对 WCT 与差值。

</figure>

并发 8 和 64 各补充三系统一次执行，16 和 32 复用同一冻结版本的既有执行；共 12 个配置—系统点，其中 6 次为本轮新增。每个点只有一次完整模拟，未绘制重复置信区间。并发 32 时，Mooncake 与 AegisKV 的完成速率分别为 0.318 与 0.302 Workflow/s。并发 64 时，完成速率从 Mooncake 的 0.285 提高到 AegisKV 的 0.296 Workflow/s，但同 ID 比较中有 65 个 Workflow 更快、95 个更慢。批次整体完成得更快，并不意味着各对象的 WCT 均降低。这些点体现配置相关的得失，不能外推为所有负载下均无开销。

### 故障频率扩展

频率扫描使用外部时钟预定干预，固定观察窗口 $H=480$ s、默认并发 16。四个负载点为 $K=0,1,2,4$ 次故障，依次取嵌套事件表的前 $K$ 个事件：(60 s, GPU0)、(180 s, GPU2)、(300 s, GPU4)、(420 s, GPU6)。每次故障不可用 120 s，三系统的时刻、目标和停机时长完全相同，不因副本是否完成或目标是否空闲而延后。

横轴为预定 $K/H$，换算为 0、7.5、15、30 次/集群小时。该高频范围用于压力测试，不是生产可靠性假设。窗口内停机暴露分别为 0、120、240、420 GPU·s，最后一次故障在窗口内覆盖 60 s，其修复发生在 540 s。固定窗口完成速率为窗口内完成 Workflow 数除以 480 s，未完成数量同时记录。

<a id="paper-eval-failure-rate-throughput"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-failure-rate-throughput.png" width="480" alt="12 固定时间窗口内的故障频率与完成速率">](../figures-legacy/aegiskv-revision-20260909/eval-failure-rate-throughput.pdf)

**图 12：固定时间窗口内的故障频率与完成速率。** 预定 480 s 窗口内注入 K=0/1/2/4 次故障，横轴为 K/480 s 的每集群小时换算。三系统使用相同外部时刻与 GPU，每次不可用 120 s；窗口内停机暴露分别为 0/120/240/420 GPU·s，末次修复越过窗口。纵轴为窗口内完成数/480 s。此范围为压力扫描；每点每系统一次模拟。

</figure>

四个频率点共 12 个系统—配置结果；每点每系统一次模拟，未构造跨运行置信区间。各点实际注入次数、受害集合、修复事件和完成率随原始结果一同记录。在每集群小时 30 次的压力点，Mooncake 与 AegisKV 的窗口完成速率分别为 0.263 与 0.258 Workflow/s，窗口内分别完成 126 与 124 个 Workflow。

### 固定追加故障的逐 Workflow 影响

全体原始 WCT 的 P95 可能属于一个天然很长、却未被故障直接影响的 Workflow，因而不再作为故障收益主指标。嵌套日程提供了更直接的配对：K1 与 K2 都在 60 s 使 GPU0 失效，只有 K2 在 180 s 追加 GPU2 故障。对同一系统和同一 Workflow，计算 $\Delta W_{s,i}^{180}=W_{s,i}^{K2}-W_{s,i}^{K1}$，比较一次固定追加故障的完整 WCT 变化，而不是不同 Workflow 的原始时长。

<a id="paper-eval-fixed-event-wct"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-revision-20260909/eval-fixed-event-wct.png" width="1008" alt="13 固定追加故障对同一Workflow的WCT影响">](../figures-legacy/aegiskv-revision-20260909/eval-fixed-event-wct.pdf)

**图 13：固定追加故障对同一Workflow的WCT影响。** 固定追加故障对同一 Workflow 的 WCT 影响。K1 和 K2 均在 60 s 对 GPU 0 注入一次故障；K2 仅额外在 180 s 对 GPU 2 注入一次故障，每次停机 120 s。每点为同系统、同 ID 的 WCT(K2)−WCT(K1)，不是相对无故障条件的增量；负值完整保留。横轴是三系统在追加故障中直接 active/queued 受害 Workflow 的共同并集，共 7 个对象，按已有 Mooncake 无故障 WCT 顺序排列，三系统均展示同一组对象。实心表示含 active 受害请求，空心表示只有 queued 受害请求，叉号表示该系统无直接受害请求；同时包含 active 和 queued 时采用实心。此并集是事后描述性分组，不是预定义因果 cohort，不代表全部 160 个 Workflow 的效果。每个系统每种日程一次模拟，共复用 6 次执行；7 个对象并非独立重复，连线只帮助按 ID 对照。该图不单独证明 Peer HBM 恢复收益。

</figure>

图中保留三个系统在 180 s 的直接受害 Workflow 并集，所有系统都比较同一组七个 ID；不同系统是否直接丢失 active KV、只被移出队列或未直接受害，由 marker 区分。并集按实际受害身份形成，是事后描述性分组，不能当作事前随机样本或宣称三系统丢失集合相同。未筛选的全部 160 个 Workflow 配对与释放/完成变化另存于 [完整事件配对数据](../../../output/aegiskv-revision-20260909/scaling-rate/data/fixed-event-all-workflows.json)。

60 s 的首个故障在三个系统中均没有 active/queued 直接受害请求，但会改变后续可用容量；它在两组中作为相同历史保留。180 s 是该嵌套日程中首个具有直接受害对象的事件，并未按 AegisKV 的收益选择案例。K2−K1 隔离的是给定共同历史后追加这个事件的影响；不能将 K4−K2 拆称 300 s 或 420 s 中任一次故障的独立代价。

保存的执行日志在 [0,180 s) 内通过语义前缀一致性核对，涵盖调度、输出位置与时刻、保护传输、CPU 模拟队列、路由和 HBM；这一核对不等同于完整 DES 内部状态快照比较。图中七个 Workflow 在两组中的首次释放时刻全部相等，因此这 21 对的 WCT 差值也等于从实验起点计的完成时刻差值。

闭环并发仍会改变后续 Workflow 首次释放时刻。因此，完整数据逐对象同时核查 $\Delta C=\Delta W+\Delta R$，其中 C 为完成时刻，R 为释放时刻；释放延后带来的短 WCT 不能直接解释为更早完成。正、负变化和完整计数均保留，结果仍未显示所有受害 Workflow 上一致的 AegisKV 优势。

注入适配器单独派生并审计，原 Algorithm 2/3 保持不变。输入频率从固定窗口定义，不使用各系统不同的 makespan 作为分母。480 s 后不再注入新故障，但旧故障继续按计划修复。原始 P95 仅保留在补充数据中，不用于本节的故障收益论证。

### 进一步的验证范围

以上诊断先检查正常成本、单故障可解释性与两个扩展维度。DP size、TP 和模型扩展需要固定实际分片布局与恢复兼容条件；其他 baseline 需要实现同一服务与故障契约；算法 2/3 消融需要在正式算法版本冻结后进行。这三类实验继续保留位置，尚无新结果。

本节当前能够说明长尾退化与 Peer 未形成恢复副本的具体问题，并给出可复算的扩展数据；它尚不能证明 AegisKV 对 Mooncake 具有近零正常开销和稳定故障收益。原生三系统端到端执行、严格控制的单故障集合与重复测量仍是投稿结论所缺的证据。实验协议、事件诊断与完整历史结果分别见 [实验设计](EVALUATION_DESIGN.md)、[逐图审查](PAPER_FIGURE_REVIEW.md) 和 [历史图像](Old_Figures.md)。
