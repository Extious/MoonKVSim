# AegisKV：论文图与叙述

[旧图归档](Old_Figures.md) · [逐图修改与获奖论文参考](PAPER_FIGURE_REVIEW.md) · [独立图 LaTeX](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-figures.tex) · [并排插图 LaTeX](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-pairs.tex) · [排版预览](../../../output/pdf/aegiskv-paper-story-20260908/paper-story-placement.pdf)

本文围绕一个问题展开：**怎样用有限 KV 保护资源减少工作流的故障损失，同时控制正常推理的代价？** Motivation 界定价值与成本，System Design 说明对象和状态，Evaluation 检查收益与代价是否实际出现。相邻图按同一问题并排；所有文件仍是独立矢量图，供论文分别编号和组合。单栏 3.33 inch，通栏 7 inch。

## Motivation

### 工作流依赖使保护价值不均等，而副本成本始终存在

图 M1、M2 分别呈现保护价值和资源成本这两个方面。真实 trace 中，并行分支的持续时间存在差异，提示恢复工作可能被其他分支吸收；这是观测动机，尚不能把持续时间差直接当作可消费的因果 Slack。另一方面，Qwen3-8B 在 96 Ki tokens 下保留两份 BF16 KV 就需要 27 GiB，保护会占用正式推理也需要的资源。

{{row:motivation-branch-gap|motivation-kv-capacity}}

这形成了设计的两个要求：保护策略需要知道一个前缀对后续工作流有多大价值；每一次复制、保留和回收还必须服从容量与传输约束。固定 DAG 的简化关系为 `暴露延迟 = max(恢复延迟 − Slack, 0)`，其具体依赖和时间安排在图 S2 中展开。

## System Design

### 以共享 KV 对象连接工作流和存储资源

图 S1 将工作流依赖、控制状态和物理 KV 缓冲区放在同一张图中。Source 对 Peer HBM 与 Store DRAM 分别复制，两个 tier 分别维护提交前缀；Peer 上的备份空间与正式推理 primary 空间相互区分。控制器中的 Slack ticket、共享对象引用、tier frontier 和资源许可分别回答价值、身份、可恢复范围和执行条件。

{{fig:system-overview}}

### Algorithm 1：用具体依赖计算可消费的时间余量

图 S2 使用同起点的两条分支：A 需要 3 s，B 需要 8 s，汇合由 B 决定。A 的最晚开始时间比最早开始时间晚 5 s；扣除 1 s 保守余量后，得到 4 s 的 ticket。这个例子把 DAG、时间线和 ticket 对应起来。ticket 还绑定消费者、DAG 版本和有效期，信息缺失或失效时回退为零。完整设计需要剩余时间预测器；后文模拟使用理想 trace duration，不验证 GBDT 准确率。

<a id="paper-motivation-exposed-recovery"></a>

{{fig:design-slack-tickets}}

### Algorithm 2：物理容量只计一次，删除损失覆盖全部引用

图 S3 中，A/B 各引用三个 chunk，但 C0/C1 是同一组物理对象。删除 C1 时，必须连同 C2-A/C2-B 一起删除，才能保持前缀连续；释放的是 3b 物理字节，两个 consumer 各损失 2b 的可复用前缀。这个差别决定了准入不能简单按逻辑引用大小收费，也不能只看被选中 chunk 自身的价值。

tier 内的预计损失使用 `Σ wᵢ·max(Tᵢ − Slackᵢ, 0)`。新候选从第一缺口形成连续组；stage、复制 ACK 复核和原子替换完成之后，才切换保护集合。复制失败时保留原集合。

{{fig:design-shared-prefix}}

### Algorithm 3：上限收缩之后，仍要等待物理释放

图 S4 将同一个 40 GiB 包络画成三个状态。primary 新增 4 GiB 需求时，允许借给 Peer 的容量从 6 降至 2 GiB；但撤销命令并没有让已经占用的 4 GiB 立即消失。只有收到 free ACK，账本和新的分配才能使用这部分空间。图中的显存数值用于解释机制。

复制还要获得源、目标和链路许可，并持有有效 QoS 证书；配额增长需要稳定余量、实际需求和已完成回收。后文主实验使用容量受限的 Peer 探索模式，完整 ForegroundBudget 的证书行为仍需独立验证。

{{fig:design-foreground-budget}}

### 用同一组 chunk 解释提交、故障和恢复

图 S5 连续追踪同一个 C1：Peer ACK 已到，而 DRAM 仍 pending 时 Source 故障，因此两个 tier 留下不同的可恢复前缀。下方的内存快照和恢复路径继续使用 C0/C1/C2，使提交状态、实际恢复内容与后缀重算直接对应。前缀装入只是一个里程碑；完整恢复还包括后缀计算、GPU 排队与解码恢复。Evaluation 使用相同的两个阶段计时。

<a id="paper-commit-recoverable-prefix"></a>
<a id="paper-commit-materialize-recompute"></a>

{{fig:commit-tier-timeline}}

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

{{row:workload-prompt_tokens|workload-workflow_call_counts}}

### 正常服务：从总体变化追踪到缓存复用

图 E3 给出同一配置、同一批 Workflow 的三条 WCT 曲线；图 E4 保留逐对象的增减，图 E5 展示整体分布。25 GB/s 条件下，平均 WCT 从 Mooncake 的 53.39 s 增加到 DRAM-only 的 64.05 s 和 AegisKV 的 69.74 s。AegisKV 相对 Mooncake 增加约 30.6%，且 129/160 个 Workflow 更慢。后面的分解需要解释这一不利结果。

{{fig:f0-revisit-wct}}

{{fig:f0-revisit-wct-difference}}

整体分布与缓存组成放在同一行：左图显示完成时间的整体变化，右图显示实际复用 token 来自哪里；后面的逐 Workflow 命中图再定位差异。

{{row:f0-revisit-wct-cdf|f0-revisit-cache-sources}}

首先检查准入是否改变正常 KV reuse。图 {{ref:f0-revisit-dram-hit}} 显示 DRAM 的 token 命中贡献从 48.08% 降至 26.54% 和 18.89%。图 {{ref:f0-revisit-cache-sources}} 将所有 prompt token 分解成互斥来源，避免将备份流量、请求命中比例与实际复用 token 混为一谈。当前保护准入目标并没有同时保住 Mooncake 的正常 DRAM 复用水平；两轮分母也解释了为什么第二轮大量命中时总体比例仍接近 50%。

{{fig:f0-revisit-dram-hit}}

### 前台干扰：分别检查 GPU 排队、显存等待与服务尾部

Peer HBM 是否伤害正式推理，不能只看一个 HBM 占用率。图 E8 的纯 GPU 排队变长，而图 E9 的 GET 目标 HBM 等待反而减少；图 E10 再检查全部 8 个 GPU 的低空闲 HBM 时间比例。由于正常命中和 GET 数量也改变，这些结果描述的是各系统整体运行状态，不能把差值直接解释成 Peer 的单独因果作用。

{{fig:f0-revisit-scheduler-queue}}

{{fig:f0-revisit-hbm-wait}}

{{fig:f0-revisit-hbm-pressure}}

图 E11、E12 将资源状态连接到前台可见时延：AegisKV 的 P99 TTFT 更长，但请求平均 TPOT 的极端尾部小于 Mooncake。这两个指标方向不同，说明平均 WCT、首 token 和持续输出体验不能相互替代。TPOT 使用请求内平均值，尚不足以验证逐 token 的停顿上界。

{{row:f0-revisit-ttft-cdf|f0-revisit-tpot-tail}}

### 控制与传输：先量化新增工作，再检查前台争用

图 {{ref:f0-revisit-controller-service-difference}} 按 Workflow 配对比较控制面 CPU 服务需求。图 {{ref:f0-revisit-controller-breakdown}}、{{ref:f0-revisit-traffic-breakdown}} 并排呈现两类可加总的代价：控制服务需求从 2.58 s 增至 5.44 s 和 6.05 s，Peer 还引入约 5,059.6 GiB 的复制。这两幅图共用系统顺序，纹理区分工作类型；CPU 数值是固定报价形成的服务需求，不是原生 CPU 利用率。

{{fig:f0-revisit-controller-service-difference}}

{{row:f0-revisit-controller-breakdown|f0-revisit-traffic-breakdown}}

图 {{ref:f0-revisit-background-copy}}、{{ref:f0-revisit-peer-copy}} 再按相同 Workflow 顺序显示后台总流量与 Peer 分项，避免用两系统总流量相减推测 Peer 流量。图 {{ref:f0-revisit-transfer-service_slowdown}} 衡量成功 GET 的共享路径减速；三系统的 GET 样本组成也会变化，因此这些分解描述整体执行状态，不能独立估计 Peer 的净因果效应。

{{fig:f0-revisit-background-copy}}

{{fig:f0-revisit-peer-copy}}

{{fig:f0-revisit-transfer-service_slowdown}}

### 故障恢复：检查不同工作进度，并回到 Workflow 代价

故障影响随工作流完成进度而变化，因此实验使用三个预定进度位置：在 Mooncake 无故障参考执行中，选择最接近 25%、50%、75% 完成比例、prompt 至少 16 Ki tokens 的请求，再在同一焦点请求的 prefill 60% 处对三系统分别触发逻辑 GPU 故障。事件身份与进度配对，绝对触发时刻和同 GPU 上的其他请求状态可以随系统执行而变化。

{{fault_results}}

补跑也没有给出一致的 AegisKV 故障收益：早期位置的 P95 Workflow 差值反而更大；中期位置 DRAM-only 与 AegisKV 几乎相同、均小于 Mooncake；后期三系统近似相同。三个焦点请求中，AegisKV 的前缀装入阶段较短，但装入的保护 token 也更少，后缀重算更长，完整恢复解码均晚于 Mooncake。不能将较短的复制阶段单独写成恢复加速。

图 E19–E21 分别保留三个位置下全部 Workflow 的有符号变化，不能只展示焦点 Workflow 或受益对象。图 E22 对这些配对差值求 P95；越晚注入，分母中故障前已完成的对象越多，跨位置的下降不能单独解释为恢复更容易。图 E23 才缩小到预先选定的焦点请求，分开计算前缀装入和后续恢复解码阶段。前缀复制更快不必然意味着完整 Workflow 恢复更快。

{{fig:f1-q25-workflow-penalty}}

{{fig:f1-q50-workflow-penalty}}

{{fig:f1-q75-workflow-penalty}}

{{fig:failure-progress-p95-penalty}}

{{fig:failure-focal-recovery-phases}}

### 配置敏感性与本文能支持的结论

最后检查结论对资源条件的依赖。图 E24 中，5 GB/s 的平均 WCT 为 150.45/81.00/82.07 s，比较方向与 25 GB/s 不同。图 E25、E26 分别改变并发与 DRAM 容量，限制将单配置结论推广到其他负载的范围。所有连线仅连接实际测试点。

{{row:sensitivity-bandwidth-mean_wct_s|sensitivity-concurrency-mean_wct_s}}

{{fig:sensitivity-dram-capacity-dram_hit_pct}}

这组机制结果说明：保护引入的容量与传输工作可能改变正常复用、排队与尾部，方向随资源条件变化。原矩阵的零 Slack 消融没有改变 WCT，严格无证书模式关闭 Peer；零结果仍保留在 [归档](Old_Figures.md#three-system-cross-case)，不能据此宣称 Slack 已带来可测收益，或完整 QoS 目标已满足。

若论文的投稿主张是“完整 AegisKV 在真实部署中以有限正常开销获得稳定故障收益”，仍缺少以下证据。这里保留清晰的实验缺口，不用示意趋势填补结果图：

| 缺少的论文图 | 所需数据及本轮不能替代的部分 |
|---|---|
| 原生三系统正常服务与干扰 | 同硬件、同 trace、开放到达负载及独立重复下的 TTFT、逐 token 延迟、goodput、CPU 利用率、真实 allocator/显存及 DMA 争用；当前 CPU 报价和 DES 不能替代 |
| 完整 Algorithm 3 的有效性 | 有效/失效证书、突发前台压力、配额撤销与真实 free ACK 的对齐轨迹；本轮探索模式不是完整控制器实验 |
| Algorithm 1 与 Slack 价值 | Workflow 隔离的训练/校准/测试集，预测误差与保守覆盖率，以及确实触发不同准入选择的 Slack 消融；理想 duration 与零效应不能证明预测器有效 |
| 故障收益的泛化 | 多个独立 workload、更多预定故障对象与进度、不同故障数/故障域、足够独立重复；三个逻辑位置只补足本输入的受控机制覆盖 |

33 张独立图的来源、旧图映射、获奖论文对照与实际 PDF 检查记录集中在 [逐图审查](PAPER_FIGURE_REVIEW.md)。这份叙述可以支撑明确标明假设的机制分析稿；上述真实部署主张仍需相应实验结果。
