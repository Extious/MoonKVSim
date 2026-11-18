# 精简前的 38 图论文初稿

本目录保留本次精简前的图像与图注；当前正文见 [Paper_Draft.md](../../../../benchmark/AegisKV/experiments/Paper_Draft.md)。

### 图 1：并行分支的持续时间差

CC/Weka 轨迹中 124 个具有重叠分支的 Workflow，每个对象取最大分支持续时间差。横轴为对数秒，纵轴为经验累计比例。该观测描述分支不均衡，不直接估计故障发生时的可用 Slack。

[![motivation-branch-gap](../motivation-branch-gap.png)](../motivation-branch-gap.pdf)

### 图 2：KV 副本的解析容量

Qwen3-8B BF16 的 KV 占用为 147,456 B/token，Ki=1,024。参考线为 40 GiB 扣除模型权重与 2 GiB 固定运行时空间后的容量，尚未扣除动态前台 KV。

[![motivation-kv-capacity](../motivation-kv-capacity.png)](../motivation-kv-capacity.pdf)

### 图 3：AegisKV 系统架构

源 Worker 独立向 Peer HBM 和 Store DRAM 复制密封 chunk。实线表示数据路径，虚线表示控制关系。Agent 子租约管理共享物理块的恢复价值，独立的 Guarded AIMD 控制目标 GPU 的备份显存借用。

[![system-overview](output/pdf/aegiskv-agent-lease-20260908/system-overview.png)](output/pdf/aegiskv-agent-lease-20260908/system-overview.pdf)

### 图 4：共享 chunk 的联合 WCT 分账

可核算示意：按固定 Agent 顺序加入同一 chunk 的恢复改善，Workflow 完成时间依次为 12、12、10 ms。两个边际份额为 0 和 2 ms，其和等于一次联合收益。

[![design-joint-wct](../design-joint-wct.png)](../design-joint-wct.pdf)

### 图 5：Agent 子租约的收租与续租

示意账本中，X 的 A/B 信用由 6/4 降至 4.8/3.2，竞争尾块 Y 归零并释放。只有 A 进入新请求轮次时，其信用更新为 6；B 保留 3.2。内部前缀 R 不参与尾块收租。

[![design-agent-subleases](../design-agent-subleases.png)](../design-agent-subleases.pdf)

### 图 6：前台约束下的显存借用

40 GiB 示意布局中的硬上限 C、授权 Q 与物理占用 Used。稳定增长、预警退让与前台需求增加分别触发不同控制动作。裁剪授权后，旧副本仍占用空间，直到物理释放确认到达。

[![design-guarded-aimd](../design-guarded-aimd.png)](../design-guarded-aimd.pdf)

### 图 7：独立提交与故障恢复

C1 的 Peer 复制已提交而 DRAM 复制仍在进行时源端故障，两个层级保留不同的可恢复前缀。恢复需要将已提交前缀装入新 primary，并重算缺失后缀。横向间距表示逻辑次序。

[![commit-tier-timeline](../commit-tier-timeline.png)](../commit-tier-timeline.pdf)

### 图 8：请求的 prompt 长度分布

FanOutQA 派生输入中 1,304 个原始请求的经验累计分布，Ki=1,024 tokens。统计不重复计入受控重访请求；最大总上下文为 86,214 tokens。

[![workload-prompt_tokens](../workload-prompt_tokens.png)](../workload-prompt_tokens.pdf)

### 图 9：Workflow 的原始调用规模

160 个 Workflow 的原始模型调用数分布，最大为 27。每个样本对应一个 Workflow，两轮受控执行不增加原始对象数。

[![workload-workflow_call_counts](../workload-workflow_call_counts.png)](../workload-workflow_call_counts.pdf)

### 图 10：无故障条件下的逐 Workflow WCT

三系统使用相同的 160 个两轮 Workflow。横轴按 Mooncake F0 WCT 排序并固定对象 ID；WCT 从首次请求释放至最后请求完成，不含活跃名额外的入场等待。连线包含全部对象，每十个对象添加识别标记。

[![f0-revisit-wct](../f0-revisit-wct.png)](../f0-revisit-wct.pdf)

### 图 11：相对 Mooncake 的配对 WCT 差值

F0 条件下，各系统减去同一 Workflow 的 Mooncake WCT。正值表示更慢，负值表示更快；对象顺序与绝对 WCT 图相同，Mooncake 为零参考线。

[![f0-revisit-wct-difference](../f0-revisit-wct-difference.png)](../f0-revisit-wct-difference.pdf)

### 图 12：逐 Workflow 的 DRAM token 命中率

F0 条件下实际复用的 DRAM token 数除以全部 prompt token 数，同时包含冷访问和受控重访。恢复 token 不计入正常命中；对象顺序与 WCT 图一致。

[![f0-revisit-dram-hit](../f0-revisit-dram-hit.png)](../f0-revisit-dram-hit.pdf)

### 图 13：正常请求的 token 来源

F0 条件下，全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 与重新计算，合计 100%。Peer 副本写入不计入正常服务命中。

[![f0-revisit-cache-sources](../f0-revisit-cache-sources.png)](../f0-revisit-cache-sources.pdf)

### 图 14：逐 Workflow 的 GPU 调度等待

F0 条件下，每个 Workflow 内请求从 GPU-ready 到执行的平均等待。GET、控制 CPU 与前台 HBM 分配等待单独计量；横轴保留固定 Workflow ID 顺序。

[![f0-revisit-scheduler-queue](../f0-revisit-scheduler-queue.png)](../f0-revisit-scheduler-queue.pdf)

### 图 15：逐 Workflow 的前台 HBM 等待

F0 条件下，每个 Workflow 内请求等待前台 HBM 准入的平均时间。横轴与其余逐 Workflow 图一致；该指标与 GPU-ready 后的调度排队分开统计。

[![f0-revisit-hbm-wait](../f0-revisit-hbm-wait.png)](../f0-revisit-hbm-wait.pdf)

### 图 16：各 GPU 的低空闲显存时间比例

F0 条件下，按每张 GPU 的执行时长统计 FREE 低于 1 GiB 的比例。低余量可能伴随可回收的普通缓存，因此不等同于 OOM 或 HBM 带宽饱和。

[![f0-revisit-hbm-pressure](../f0-revisit-hbm-pressure.png)](../f0-revisit-hbm-pressure.pdf)

### 图 17：请求 TTFT 分布

三系统各 2,608 个请求从 release 至首个输出 token 的经验累计分布。TTFT 包含执行路径上的等待，横轴为对数秒并保留完整尾部。

[![f0-revisit-ttft-cdf](../f0-revisit-ttft-cdf.png)](../f0-revisit-ttft-cdf.pdf)

### 图 18：请求平均 TPOT 的尾部

每系统 2,432 个有效请求先计算首 token 后的平均 TPOT，再绘制不小于横轴值的经验比例。每个样本是请求均值，而非单个 token 间隔。

[![f0-revisit-tpot-tail](../f0-revisit-tpot-tail.png)](../f0-revisit-tpot-tail.pdf)

### 图 19：参考实现的线程 CPU 工作量

F0 执行中的实际线程 CPU 时间，按派发、准入与 DAG、提交、回收与 AIMD 分解，并扣除嵌套计量。该图描述 Python 参考实现，不表示原生服务的 CPU 利用率。

[![reference-cpu-breakdown](../reference-cpu-breakdown.png)](../reference-cpu-breakdown.pdf)

### 图 20：进入模拟时序的控制 CPU 服务

F0 执行中固定 CPU 服务报价的累计需求，分为前台派发与准入，两者经过同一个控制器队列。提交、回收与 AIMD 的全部参考 CPU 工作量尚未完整映射为因果时延。

[![f0-revisit-controller-breakdown](../f0-revisit-controller-breakdown.png)](../f0-revisit-controller-breakdown.pdf)

### 图 21：正常读取与保护复制流量

F0 执行中的实际模拟传输字节，分为正常 GET、DRAM 写入和 Peer 复制，TiB=2^40 B。计入已经传输的中止部分与执行收尾流量。

[![f0-revisit-traffic-breakdown](../f0-revisit-traffic-breakdown.png)](../f0-revisit-traffic-breakdown.pdf)

### 图 22：共享路径中的正常 GET 服务倍率

F0 条件下，每次成功正常 GET 的实际传输服务时长除以同字节量的独占路径时长。不同系统的命中对象与 GET 数量可以不同，曲线为相应请求总体的描述性分布。

[![f0-revisit-transfer-service_slowdown](../f0-revisit-transfer-service_slowdown.png)](../f0-revisit-transfer-service_slowdown.pdf)

### 图 23：中期故障的逐 Workflow 增量

在 Mooncake 基准完成进度最接近 50% 的预定请求上触发故障。每条曲线为本系统 F1 减配对 F0，包含全部 160 个 Workflow，沿用无故障对象顺序。

[![f1-q50-workflow-penalty](output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.png)](output/pdf/aegiskv-agent-lease-20260908/f1-q50-workflow-penalty.pdf)

### 图 24：预定故障请求的完整恢复阶段

每个故障位置的柱依次为 Mooncake、DRAM-only AegisKV、AegisKV。颜色表示系统，纹理区分故障至前缀装入与装入后至恢复解码；各段均包含对应的等待和服务时间。

[![failure-focal-recovery-phases](../failure-focal-recovery-phases.png)](../failure-focal-recovery-phases.pdf)

### 图 25：不同故障位置的尾部 WCT 增量

先对同一 Workflow 求 F1−F0，再对全部 160 个增量取 P95。横轴是故障选点在 Mooncake F0 中的实际完成比例；已完成对象也包含在统计中。

[![failure-progress-p95-penalty](../failure-progress-p95-penalty.png)](../failure-progress-p95-penalty.pdf)

### 图 26：入场顺序对正常 WCT 的影响

三种预定顺序包含相同的 160 个 Workflow。各经验分位的线为三顺序中位数，阴影为最小与最大值；该范围描述顺序敏感性，不是置信区间。

[![order-normal-wct](../order-normal-wct.png)](../order-normal-wct.pdf)

### 图 27：入场顺序对故障增量的影响

每个顺序从对应 Mooncake F0 选择中期故障，三系统各自减去配对 F0。线和阴影为相同对象三个入场顺序的分位中位数及最小、最大值。

[![order-failure-penalty](../order-failure-penalty.png)](../order-failure-penalty.pdf)

### 图 28：价值与容量策略的正常服务消融

在默认 F0 配置下，分别替换 DAG 联合价值、改用严格正收益空闲准入和固定 Peer 上限。每次改变一个因素，保留相同输入与 CPU 报价。

[![ablation-normal-wct](../ablation-normal-wct.png)](../ablation-normal-wct.pdf)

### 图 29：惰性刷新保留决策并减少求值

DRAM-only AegisKV 中，两种模式均检查全部可释放尾块；Lazy 仅跳过版本未变的价值计算。完整准入状态与牺牲块序列一致，计数包含被拒绝的试算。

[![ablation-lazy-refresh](../ablation-lazy-refresh.png)](../ablation-lazy-refresh.pdf)

### 图 30：batch 1 下的真实 forward 干扰

两张 L40S 上的 Qwen3-8B BF16/SDPA，额外触达分配为 8 GiB。按同测量块、同 prompt 的无复制 forward 归一化。每条件五个随机交错测量块，标记与误差线为中位数和最小、最大值。

[![native-forward-b1](../native-forward-b1.png)](../native-forward-b1.pdf)

### 图 31：batch 4 下的真实 forward 干扰

设备、模型与归一化方式与 batch 1 相同，额外触达分配为 8 GiB。每条件五个随机交错测量块；两图共用纵轴，误差线表示观测范围。

[![native-forward-b4](../native-forward-b4.png)](../native-forward-b4.pdf)

### 图 32：容量占用与 DMA 并发的分离测量

两张 L40S 上 batch=4、prompt=4,096 tokens，改变额外触达分配量。四种复制条件各含五个测量块；标记为中位数，误差线为最小与最大值，纵轴显示局部秒值。

[![native-memory-occupancy](../native-memory-occupancy.png)](../native-memory-occupancy.pdf)

### 图 33：撤销备份后的释放完成时长

两张 L40S 上对 1、4、8 GiB 对象各测量 20 次。分别计量在途写入 fence 与 allocator free、empty-cache 和同步完成；标记和误差线为中位数与最小、最大值。

[![native-release-ack](../native-release-ack.png)](../native-release-ack.pdf)

### 图 34：动态显存授权与物理占用

30% DMA 额外 forward 时长的模拟敏感性条件下，按 50 ms 窗口汇总八张 GPU 的 C、Q 与物理备份占用，后者包含 pending 复制。模拟释放在 fence 后同步完成。

[![aimd-quota-and-occupancy](../aimd-quota-and-occupancy.png)](../aimd-quota-and-occupancy.pdf)

### 图 35：动态与静态 Peer 的预警反馈

相同 30% DMA 模型条件下，1 s 桶汇总八张 GPU 的 50 ms 预警窗口比例。预警为归一化 forward 延迟信号，不是请求 SLO 违约率；各曲线止于各自执行终点。

[![aimd-warning-windows](../aimd-warning-windows.png)](../aimd-warning-windows.pdf)

### 图 36：共享路径带宽敏感性

分别执行 5、25、50 GB/s，其他参数保持默认。每个标记为该系统一次完整无故障执行的平均 WCT，连线只连接已评估设置。

[![sensitivity-bandwidth](../sensitivity-bandwidth.png)](../sensitivity-bandwidth.pdf)

### 图 37：DRAM 容量与正常 token 命中

分别执行 250 GB 与 1 TB DRAM，其余参数保持默认。每点为一次完整 F0 执行的 token 加权 DRAM 命中率；GB/TB 使用十进制单位。

[![sensitivity-dram-capacity](../sensitivity-dram-capacity.png)](../sensitivity-dram-capacity.pdf)

### 图 38：正常成本与单故障收益的解析混合

以概率 p 发生一次故障，三个预定位置等权混合已执行的 F1 结果，其余概率使用 F0。横轴概率为分析假设，曲线由模拟均值计算，不是新的运行或实测故障率。

[![benefit-cost-fault-mixture](../benefit-cost-fault-mixture.png)](../benefit-cost-fault-mixture.pdf)
