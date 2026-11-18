# AegisKV：面向多 Agent Workflow 的 KV 保护

<!-- 中文论文正文源。三部分共 12 张独立图：Motivation 3，System Design 1，Evaluation 8。
参考原论文的论证结构；实验结果绑定 source-v3，不覆盖 Algorithm 2 后续调整。
选图理由、来源、补充材料和可复现入口在 PAPER_FIGURE_REVIEW.md 中维护。 -->

## Motivation

### Observation 1：并行分支具有显著的执行时间差

多 Agent 应用将一次任务组织为模型调用、工具调用与汇合结点组成的依赖图。用户等待的是整个 Workflow 完成，而汇合结点必须等待所有前驱。因此，单个请求恢复得更快，只有在缩短依赖图的完成时间时才产生用户可见收益。我们以 Workflow Completion Time（WCT）作为保护目标，即从 Workflow 首个请求释放到最后一个请求完成的时间。

公开 [CC/Weka 轨迹](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)提供了分支执行不均衡的观测依据。我们保留存在共同重叠区间的并行分支组，并对每个 Workflow 取最大的最长与最短分支持续时间差。图 1 中，124 个符合条件的 Workflow 的中位差值为 140.6 s，P90 为 1,570.3 s。这些观测说明，不同分支距汇合完成的时间余量可能相差很大；持续时间差本身并不等于故障时刻可使用的 Slack。

### Observation 2：重算代价的排序不等于 Workflow 损失的排序

图 2 使用旧动机实验中的同一个五分支轨迹示例，分离恢复暂停中被并行执行吸收的部分与实际推迟汇合的部分。对每条分支分别在 349.5 s 注入一次模型化故障，保持其他分支的执行不变。若分支恢复需要额外时间 $T_i$、到原汇合时刻的剩余间隔为 $s_i$，暴露的延迟为

$$
J_i=\max(0,T_i-s_i).
$$

A3 的模型化重算时间最长，为 46.6 s，但其 52.4 s 的汇合间隔可吸收全部暂停；A4 的重算时间较短，为 35.9 s，却因处于关键分支而全部暴露给 Workflow。因而，仅按 KV 大小或重算时间选择保护对象，会把资源分配给不改变完成时间的分支。保护价值应根据当前依赖图中能够避免的 WCT 损失定义，多个共享分支的改善也需要联合评价。

<a id="paper-motivation-branch-gap"></a>
<a id="paper-motivation-recovery-exposure"></a>

| **图 1：并行分支的执行时间不均衡** | **图 2：重算代价与 Workflow 损失并不等价** |
|---|---|
| [<img src="../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.png" width="480" alt="1 并行分支的执行时间不均衡">](../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.pdf) | [<img src="../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.png" width="480" alt="2 重算代价与 Workflow 损失并不等价">](../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.pdf) |
| CC/Weka 中 124 个具有重叠分支的 Workflow；每个对象取最大分支持续时间差。横轴为对数秒。该观测描述不均衡，不直接估计可用 Slack。 | 同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。 |

这一例子是轨迹锚定的反事实推演。重算时间来自冻结的 AIConfigurator Qwen3-235B-A22B、A100-80GB、TP8/PP4/EP8 配置，输入长度由轨迹中的 64-token hash block 数重建；它不是实际故障测量，也不是后文的 Qwen3-8B 实验。该推演解释评价目标的差别，不估计部署收益。实际恢复还会改变排队、并行进度与关键路径，因此后文同时测量恢复终点与完整 WCT。

### Observation 3：长上下文使无差别保护受到容量约束

副本空间随上下文长度线性增长。对于具有 $L$ 个注意力层、每层 $h_{\mathrm{kv}}$ 个 KV head、head dimension 为 $d$、元素宽度为 $b$ 字节的模型，每个 token 的 KV 大小为 $2Lh_{\mathrm{kv}}db$。本文 Qwen3-8B BF16 布局对应 147,456 B/token，一个 4,096-token chunk 占用 576 MiB。

图 3 显示，96 Ki tokens 的一份 KV 占用 13.5 GiB，两份占用 27 GiB。对一张 40 GiB GPU，仅扣除权重与固定运行时空间后，两份长上下文 KV 已超过剩余容量；前台推理还需要额外的动态 KV。因此，Peer HBM 的可借容量随前台需求变化，不能按静态空闲空间无限保留副本。

<a id="paper-motivation-kv-capacity"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.png" width="480" alt="3 长上下文 KV 的容量约束">](../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.pdf)

**图 3：长上下文 KV 的容量约束。** Qwen3-8B BF16 的解析容量，Ki=1,024。参考线从 40 GiB 扣除模型权重与 2 GiB runtime，尚未扣除动态前台 KV，不能当作可借备份额度。

</figure>

三条 Observation 导出 AegisKV 的设计目标：以联合 WCT 改善决定保护价值，对共享 KV 按物理对象计量，并随前台需求撤销 Peer 显存借用。DRAM 保留策略还可能改变正常前缀复用，复制与准入也消耗带宽及 CPU；这些代价需要与故障收益在同一实验配置下共同评价。

## System Design

### 系统架构与独立保护路径

图 4 展示 AegisKV 的整体架构。应用侧提供当前可见的 Workflow DAG 与 Agent 状态，价值接口将分支剩余执行时间映射为恢复对 WCT 的影响，池级准入决定保留哪些物理 chunk。目标 GPU 上独立的显存控制器根据前台内存需求和 forward 反馈限制备份借用。

源 Worker 持有正常推理的 primary KV。密封的 C0、C1 可以分别复制到 Peer HBM 与 DRAM Store，两条路径各自分配空间、执行复制并确认提交；某一层拒绝或丢失副本，不影响另一层已经提交的同名对象。共享 C0 的多个 Agent 引用不会在同一个池中重复占用 C0 的容量。Peer Worker 的前台 P0、P1 与借用空间中的备份 C0、C1 是不同物理对象。

<a id="paper-system-overview"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/system-overview.png" width="1008" alt="4 AegisKV System Overview">](../figures-legacy/aegiskv-evaluation-20260909/system-overview.pdf)

**图 4：AegisKV System Overview。** 源端独立向 Peer HBM 和 DRAM 复制同名 KV；复制确认后才可读取。Workflow 价值与池级准入决定保护对象，独立控制器约束 Peer 显存借用。故障后从可用层装入新的 primary C0、C1，再重算 C2。实线为数据，虚线为控制。

</figure>

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

### 实验方法与研究问题

评估围绕两个问题展开：第一，在相同负载与资源下，保护机制是否使正常服务出现可感知退化；第二，在同一个可控故障作用于同一个 Workflow 时，保护副本能否缩短完整完成时间，以及这一收益来自哪里。扩展实验分别研究故障频率与并发的影响，随后再评估模型与并行规模、其他基线以及算法消融。

我们比较 Mooncake、DRAM-only AegisKV 和完整 AegisKV。DRAM-only 使用 AegisKV 的 DRAM 准入并关闭 Peer HBM，用于分离 DRAM 策略与 Peer 的作用。三者应采用相同服务引擎、模型、物理资源、恢复路径与调度配置。原生实验需要完整系统实现；下面沿用的 source-v3 数据是未标定模拟中的策略对照，不能称为完整 Mooncake 和 AegisKV 的原生部署测量。

默认配置为 Qwen3-8B BF16、DP=8、TP=1、PP=1，8×40 GiB、1 TB DRAM Store、25 GB/s 共享路径，KV chunk 为 4096 tokens。输入包含 160 个 FanOutQA-derived Workflow，每个完整 DAG 执行两轮精确重访，共 2608 个请求；最大活跃 Workflow 数为 16。该重访构造用于施加可控复用压力，不代表生产重访频率。F0 表示无故障，F1 表示一次预定故障。一次运行处理整套输入；逐 Workflow 图的点代表同一个逻辑对象，运行重复仅用于估计不确定性。

WCT 从 Workflow 准入计到 DAG 完成。后续外部到达实验另报准入前等待和从 release 到完成的响应时间，防止并发上限掩盖排队成本。三系统按同一个 Workflow ID 配对，统一使用冻结的 Mooncake F0 排序。我们同时报告绝对秒、相对开销与尾部，避免较长 Workflow 的固有差异遮盖策略效应。

正常服务采用事前定义的非劣判据。当前草案将 WCT 均值及 P95 的服务退化边界暂定为 2%，以配对完整测量块形成的单侧区间判定；该目标尚待正式采集前冻结。TTFT、逐 token TBT、goodput 与完成率共同报告。CPU、显存及网络开销另行计量：异步操作即使不延长 WCT，也仍可能消耗额外资源。未发现显著差异不能作为零开销的证据。

本轮尚未执行上述新协议。以下七张图以冻结历史数据检验新画法和统计口径，保留正、负与零结果；它们不构成算法 2 后续修改版本的验证。实验清单、缺少的采集字段与重复方案见 [实验设计](EVALUATION_DESIGN.md)。

### 正常执行的服务代价

图 5 将每个 Workflow 的 WCT 除以同一对象的 Mooncake WCT，再减一，直接展示差异曲线。零表示基准服务时间，负值表示更快；不再用不同 Workflow 的原始时长高低判断系统收益。

<a id="paper-eval-healthy-workflow"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.png" width="1008" alt="5 正常执行的逐 Workflow 相对开销">](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.pdf)

**图 5：正常执行的逐 Workflow 相对开销。** 历史 source-v3 模拟的全部 160 个配对 Workflow；每点为同一对象相对 Mooncake 的 WCT 变化。零线为 Mooncake，负值更快。沿用基准 F0 排序；连线不是时间轴。每配置一次执行，不绘制跨重复置信区间。

</figure>

| 系统 | F0 平均 WCT (s) | WCT P95 (s) | TTFT P99 (s) | 请求平均 TPOT 的 P99 (s) |
|---|---|---|---|---|
| Mooncake | 52.642 | 93.479 | 23.202 | 0.824 |
| DRAM-only AegisKV | 54.158 | 97.554 | 21.302 | 0.450 |
| AegisKV | 55.230 | 102.809 | 22.653 | 0.577 |

历史模拟中，AegisKV 的平均 WCT 为 55.230 s，相对 Mooncake 增加 4.92%；这不是“无额外服务开销”的结果。该配置每个系统只有一次用于当前曲线的执行，不能据此构造跨部署置信区间或完成非劣判断。原始绝对 WCT 和其余服务分布保留在补充材料中。

### DRAM、HBM 与控制面的代价来自哪里

图 6 进一步对齐同一组 Workflow 的 DRAM token 命中率。该图使用百分点差值；总体命中率则按 prompt token 加权。历史结果中，完整 AegisKV 相对 Mooncake 下降 6.01 个百分点，表明正常复用需要与保护价值共同权衡。

<a id="paper-eval-healthy-reuse"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.png" width="1008" alt="6 DRAM 准入对正常复用的影响">](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.pdf)

**图 6：DRAM 准入对正常复用的影响。** 与前图相同的对象和顺序，纵轴为 DRAM token 命中率的百分点变化。分母包含所有冷访问与重访 prompt token，排除恢复 token；总体命中率按 token 加权，不能对这些点直接求平均。

</figure>

图 7 将前台等待、控制计算和传输逐项相对同指标 Mooncake 归一化。各行具有不同计量对象，不能相加成总开销。历史模拟中的 HBM 分配等待与调度队列未随 Peer 一同增加，但 Python 参考控制 CPU 和模拟 CPU 服务需求明显增加；正常 GET 变少也伴随命中率下降，不能单独解释为带宽效率改善。

<a id="paper-eval-healthy-resources"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.png" width="1008" alt="7 前台等待、控制计算与传输的分项成本">](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.pdf)

**图 7：前台等待、控制计算与传输的分项成本。** 各行独立除以同指标 Mooncake 值；横轴为对数倍率。参考 CPU 是 Python 实测，其余为未标定模拟。累计等待、队列分位数和流量不能相加；GET 样本总体随命中策略变化。该图不含尚未采集的原生进程 CPU 与逐 GPU HBM 峰值。

</figure>

| 指标 | Mooncake | DRAM-only AegisKV | AegisKV |
|---|---|---|---|
| Python 参考 CPU 时间 (s) | 9.989 | 56.538 | 68.502 |
| 模拟 CPU 服务需求 (s) | 3.743 | 18.335 | 27.729 |
| 累计前台 HBM 等待 (s) | 188.634 | 150.208 | 116.597 |
| 请求调度等待 P95 (s) | 10.908 | 11.614 | 10.444 |
| DRAM + Peer 写入 (TiB) | 3.549 | 3.471 | 3.643 |
| 正常 GET (TiB) | 3.386 | 2.930 | 2.954 |

正式原生实验还需要逐 GPU 的前台与备份 HBM 峰值、分配失败/抢占、逐路径链路利用率、进程 CPU 分解与真实逐 token TBT。此前双 L40S 的组件微基准发现，512-token、batch 1 条件下 Peer 输入使 forward 中位时长增加约 32.2%；组件结果说明复制干扰需要测量，不能直接代替三系统端到端成本。相关原始图保留于 [补充材料](Old_Figures.md#agent-lease-supplements)。

### 固定单故障下的同一 Workflow 比较

固定绝对墙钟时刻并不保证三个系统的 Workflow 已执行到相同位置。主实验因而使用预定语义边界：冻结焦点 Workflow/span、输入/输出 token、source GPU、恢复目标和不可用时长，在同一 decode token 的 kernel 边界注入。受控条件下，故障 GPU 在干预区间只持有同一焦点请求的易失 primary；其他前台任务使用相同的剩余资源。各策略自然形成的已提交副本允许不同，不能等待 AegisKV 的复制完成后才注入故障。

对于每个 Workflow，分别计算绝对 F1 WCT、相对自身 F0 的增量，以及使用共同 Mooncake F0 分母的归一化增量。绝对 F1 回答最终是否更快；F1−F0 则检查故障代价是否下降。近零或负的故障增量不作为倍数收益的分母。

图 8 与图 9 使用历史数据中三个事前选定的焦点实例 C1–C3 说明这两个终点。每个实例只比较同一个 Workflow，避免大量未直接受损 Workflow 稀释差异。历史触发按同一请求的总 token 进度 60% 解析，并非固定新协议的 decode 边界；其余受影响对象尚未固定。因此这里的点仍是旧协议诊断。

<a id="paper-eval-failure-wct"></a>
<a id="paper-eval-failure-increment"></a>

| **图 8：同一故障焦点 Workflow 的完整 WCT** | **图 9：扣除正常成本后的配对故障增量** |
|---|---|
| [<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.png" width="480" alt="8 同一故障焦点 Workflow 的完整 WCT">](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.pdf) | [<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.png" width="480" alt="9 扣除正常成本后的配对故障增量">](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.pdf) |
| C1–C3 是预选的三个不同故障实例；每组只比较同一个焦点 Workflow。分母是同例 Mooncake F1 WCT，1 为基准。历史触发只对齐逻辑请求和 token 进度，尚未固定全部受影响对象；这些点不是新协议结果。 | 每个点先计算自身 F1−F0，再除以同例 Mooncake F0 WCT。三系统使用共同分母；保留负值。闭环调度可改变等待，因此负增量不能解释为故障有益。C1–C3 不是随机重复，未拟合趋势或置信区间。 |

| 故障实例 / Workflow ID | 系统 | F0 WCT (s) | F1 WCT (s) | F1−F0 (s) |
|---|---|---|---|---|
| C1 / 98ced84a1a9df028 | Mooncake | 82.911 | 110.178 | 27.268 |
| C1 / 98ced84a1a9df028 | DRAM-only AegisKV | 127.089 | 188.816 | 61.728 |
| C1 / 98ced84a1a9df028 | AegisKV | 106.503 | 137.852 | 31.350 |
| C2 / 220852c6d47dfd38 | Mooncake | 24.058 | 24.169 | 0.111 |
| C2 / 220852c6d47dfd38 | DRAM-only AegisKV | 27.143 | 63.717 | 36.574 |
| C2 / 220852c6d47dfd38 | AegisKV | 39.384 | 20.407 | -18.977 |
| C3 / 5aa09932011c8fcd | Mooncake | 74.906 | 65.988 | -8.918 |
| C3 / 5aa09932011c8fcd | DRAM-only AegisKV | 80.211 | 48.907 | -31.304 |
| C3 / 5aa09932011c8fcd | AegisKV | 77.774 | 68.272 | -9.502 |

三例的结果并不一致：C1 的 AegisKV 焦点 Workflow 更慢；C2 更快却具有负的 F1−F0；C3 也没有绝对 WCT 优势。负增量反映闭环调度与争用发生变化，不能解释为故障有益。历史全部 Workflow 的平均 F1 WCT 在三处注入中也均未优于 Mooncake。新的固定受害者协议需要重跑后，才可检验收益是否稳定传递到完整 Workflow。

### 从可恢复副本到 Workflow 终点

恢复分析沿同一焦点请求追踪故障检测、重路由、前缀装入、后缀重算、队列等待、恢复解码、分支完成及 DAG 汇合。图 10 先用现有日志中可加的两个聚合阶段展示这条原因链的前半段；柱终点为恢复解码，尚不是 Workflow 完成。正式图需要补齐后段事件，重叠操作以时间区间表达，不把并行阶段相加为 WCT。

<a id="paper-eval-failure-recovery"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.png" width="1008" alt="10 恢复阶段为何不能代替完整 Workflow 收益">](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.pdf)

**图 10：恢复阶段为何不能代替完整 Workflow 收益。** 同一 C1–C3 焦点请求的两个相邻区间：故障至前缀可读（含检测、路由与装入），以及前缀可读至恢复解码（含后缀重算与排队）。区间内的操作尚未细分；柱终点未包含后续 DAG 终点。阶段较短并不保证完整 WCT 更短。

</figure>

图 11 对照相同实例的恢复来源与重算 token。三例均未从 Peer 恢复 token，因此较短的局部恢复不能归因于 Peer HBM。只有当已提交的保护前缀实际减少重算或装入时间，并且节省未被其他分支或排队吸收时，才可能解释完整 Workflow 的收益。

<a id="paper-eval-failure-kv"></a>

<figure class="paper-figure">

[<img src="../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.png" width="1008" alt="11 恢复来源与剩余重算">](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.pdf)

**图 11：恢复来源与剩余重算。** 三个焦点请求的历史 token 计数，系统与前图逐行对齐。Ki=1,024。仅统计 Peer 恢复、DRAM 恢复和重算，不是全部上下文的百分比。所有 Peer 恢复均为零；不能把前图的阶段改善归因于 Peer。

</figure>

这组结果保留了当前证据的限制：局部恢复时间、保护字节数和完整 Workflow 收益不能相互替代。故障实验既要报告直接受害者，也要报告预定背景 cohort、完成率及系统 makespan，防止将成本转移给其他 Workflow。

### 故障频率扩展

【R1 / R2 结果待补】固定模型、DP=8 与并发上限 16，在一小时测量窗内分别注入 0、1、2、4、8 次预定故障，每次不可用 120 s。横轴明确为每 cluster-hour 注入次数；三系统重放相同外部到达与故障轨迹，报告实际故障次数和 unavailable GPU-seconds。两张独立图分别展示 SLO goodput 与 Workflow 响应时间 P95，旁列完成/删失比例。多故障结果需实际重跑，不能由一次故障曲线线性混合。

### Workflow 并发扩展

【C1 / C2 结果待补】固定模型、物理资源与一次预定故障，扫描最大活跃 Workflow 数 4、8、16、32、64。三系统在每个相同 C 下配对，主图分别展示 F1 goodput 和尾部响应时间，F0 作配对服务表。HBM、CPU 与链路观测用于解释容量拐点；Workflow 并发与单步 request batch size 分开报告。R1/R2/C1/C2 的空布局只放在 [实验设计](EVALUATION_DESIGN.md#仅供设计检查的扩展空布局)，不当作结果图插入正文。

### 模型与并行规模

【留空：DP size、Model 与 TP。】

### 与其他故障恢复基线比较

【留空：先匹配故障域、并行方式和资源预算，再比较 Related Works 中可复现的基线。】

### 算法消融

【留空：算法 2 与算法 3 分别消融，待算法 2 冻结。】
