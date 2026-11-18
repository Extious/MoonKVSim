# PaperBanana 优化前的 Agent 子租约图集

本页保存同一算法、同一数据在本次视觉优化前的 51 张图。

## M1 并行分支留下多少时间差

[PDF](motivation-branch-gap.pdf) · [SVG](motivation-branch-gap.svg)

![M1](motivation-branch-gap.png)

## M2 长上下文副本的容量代价

[PDF](motivation-kv-capacity.pdf) · [SVG](motivation-kv-capacity.svg)

![M2](motivation-kv-capacity.png)

## S1 数据路径与三个算法的职责

[PDF](system-overview.pdf) · [SVG](system-overview.svg)

![S1](system-overview.png)

## S2 按联合 Workflow 收益分账

[PDF](design-joint-wct.pdf) · [SVG](design-joint-wct.svg)

![S2](design-joint-wct.png)

## S3 信用跨请求保留，按 Agent 新轮更新

[PDF](design-agent-subleases.pdf) · [SVG](design-agent-subleases.svg)

![S3](design-agent-subleases.png)

## A1 单块试算、释放与提交

[PDF](design-prefix-admission.pdf) · [SVG](design-prefix-admission.svg)

![A1](design-prefix-admission.png)

## S4 独立的显存借用上限控制

[PDF](design-guarded-aimd.pdf) · [SVG](design-guarded-aimd.svg)

![S4](design-guarded-aimd.png)

## S5 独立提交决定故障后能恢复的前缀

[PDF](commit-tier-timeline.pdf) · [SVG](commit-tier-timeline.svg)

![S5](commit-tier-timeline.png)

## E1 输入的 Prompt 长度分布

[PDF](workload-prompt_tokens.pdf) · [SVG](workload-prompt_tokens.svg)

![E1](workload-prompt_tokens.png)

## E2 输入的 Workflow 规模

[PDF](workload-workflow_call_counts.pdf) · [SVG](workload-workflow_call_counts.svg)

![E2](workload-workflow_call_counts.png)

## E3 同配置逐 Workflow 的 WCT

[PDF](f0-revisit-wct.pdf) · [SVG](f0-revisit-wct.svg)

![E3](f0-revisit-wct.png)

## E4 逐 Workflow 的完成时间变化

[PDF](f0-revisit-wct-difference.pdf) · [SVG](f0-revisit-wct-difference.svg)

![E4](f0-revisit-wct-difference.png)

## A2 单一入场顺序的 WCT 分布

[PDF](f0-revisit-wct-cdf.pdf) · [SVG](f0-revisit-wct-cdf.svg)

![A2](f0-revisit-wct-cdf.png)

## E5 DRAM 准入是否保住正常复用

[PDF](f0-revisit-dram-hit.pdf) · [SVG](f0-revisit-dram-hit.svg)

![E5](f0-revisit-dram-hit.png)

## E6 实际复用来自哪一层

[PDF](f0-revisit-cache-sources.pdf) · [SVG](f0-revisit-cache-sources.svg)

![E6](f0-revisit-cache-sources.png)

## E7 正常请求的 GPU 调度排队

[PDF](f0-revisit-scheduler-queue.pdf) · [SVG](f0-revisit-scheduler-queue.svg)

![E7](f0-revisit-scheduler-queue.png)

## E8 前台因 HBM 准入而等待多久

[PDF](f0-revisit-hbm-wait.pdf) · [SVG](f0-revisit-hbm-wait.svg)

![E8](f0-revisit-hbm-wait.png)

## E9 GPU 的低空闲显存时间占比

[PDF](f0-revisit-hbm-pressure.pdf) · [SVG](f0-revisit-hbm-pressure.svg)

![E9](f0-revisit-hbm-pressure.png)

## E10 请求 TTFT 的完整分布

[PDF](f0-revisit-ttft-cdf.pdf) · [SVG](f0-revisit-ttft-cdf.svg)

![E10](f0-revisit-ttft-cdf.png)

## E11 请求平均 TPOT 的尾部

[PDF](f0-revisit-tpot-tail.pdf) · [SVG](f0-revisit-tpot-tail.svg)

![E11](f0-revisit-tpot-tail.png)

## A3 逐 Workflow 的 CPU 服务报价变化

[PDF](f0-revisit-controller-service-difference.pdf) · [SVG](f0-revisit-controller-service-difference.svg)

![A3](f0-revisit-controller-service-difference.png)

## E13 进入模拟时序的控制 CPU 服务

[PDF](f0-revisit-controller-breakdown.pdf) · [SVG](f0-revisit-controller-breakdown.svg)

![E13](f0-revisit-controller-breakdown.png)

## E12 Python 参考实现的实际 CPU 工作量

[PDF](reference-cpu-breakdown.pdf) · [SVG](reference-cpu-breakdown.svg)

![E12](reference-cpu-breakdown.png)

## E14 实际传输量的组成

[PDF](f0-revisit-traffic-breakdown.pdf) · [SVG](f0-revisit-traffic-breakdown.svg)

![E14](f0-revisit-traffic-breakdown.png)

## E15 保护流量是否拖慢前台 GET

[PDF](f0-revisit-transfer-service_slowdown.pdf) · [SVG](f0-revisit-transfer-service_slowdown.svg)

![E15](f0-revisit-transfer-service_slowdown.png)

## A4 逐 Workflow 的后台复制量

[PDF](f0-revisit-background-copy.pdf) · [SVG](f0-revisit-background-copy.svg)

![A4](f0-revisit-background-copy.png)

## A5 逐 Workflow 的 Peer 复制量

[PDF](f0-revisit-peer-copy.pdf) · [SVG](f0-revisit-peer-copy.svg)

![A5](f0-revisit-peer-copy.png)

## A6 25% 进度选点的逐 Workflow 故障代价

[PDF](f1-q25-workflow-penalty.pdf) · [SVG](f1-q25-workflow-penalty.svg)

![A6](f1-q25-workflow-penalty.png)

## E16 50% 进度选点的逐 Workflow 故障代价

[PDF](f1-q50-workflow-penalty.pdf) · [SVG](f1-q50-workflow-penalty.svg)

![E16](f1-q50-workflow-penalty.png)

## A7 75% 进度选点的逐 Workflow 故障代价

[PDF](f1-q75-workflow-penalty.pdf) · [SVG](f1-q75-workflow-penalty.svg)

![A7](f1-q75-workflow-penalty.png)

## E18 不同故障位置的尾部 Workflow 损失

[PDF](failure-progress-p95-penalty.pdf) · [SVG](failure-progress-p95-penalty.svg)

![E18](failure-progress-p95-penalty.png)

## E17 保护缩短的是哪个恢复阶段

[PDF](failure-focal-recovery-phases.pdf) · [SVG](failure-focal-recovery-phases.svg)

![E17](failure-focal-recovery-phases.png)

## E31 何种故障概率下才能抵消正常开销

[PDF](benefit-cost-fault-mixture.pdf) · [SVG](benefit-cost-fault-mixture.svg)

![E31](benefit-cost-fault-mixture.png)

## E19 更换入场顺序后的正常 WCT

[PDF](order-normal-wct.pdf) · [SVG](order-normal-wct.svg)

![E19](order-normal-wct.png)

## E20 更换入场顺序后的故障代价

[PDF](order-failure-penalty.pdf) · [SVG](order-failure-penalty.svg)

![E20](order-failure-penalty.png)

## E23 真实 forward 与 DMA 并发：batch 1

[PDF](native-forward-b1.pdf) · [SVG](native-forward-b1.svg)

![E23](native-forward-b1.png)

## E24 真实 forward 与 DMA 并发：batch 4

[PDF](native-forward-b4.pdf) · [SVG](native-forward-b4.svg)

![E24](native-forward-b4.png)

## E25 分配容量与复制争用分别测量

[PDF](native-memory-occupancy.pdf) · [SVG](native-memory-occupancy.svg)

![E25](native-memory-occupancy.png)

## A8 真实复制速率随前台计算变化

[PDF](native-concurrent-copy.pdf) · [SVG](native-concurrent-copy.svg)

![A8](native-concurrent-copy.png)

## E26 撤销备份后的实际释放延迟

[PDF](native-release-ack.pdf) · [SVG](native-release-ack.svg)

![E26](native-release-ack.png)

## A9 原生复制线程的 CPU 需求

[PDF](native-copy-cpu.pdf) · [SVG](native-copy-cpu.svg)

![A9](native-copy-cpu.png)

## E21 Algorithm 2 / 3 的正常服务消融

[PDF](ablation-normal-wct.pdf) · [SVG](ablation-normal-wct.svg)

![E21](ablation-normal-wct.png)

## E22 惰性计算是否保持同样的准入决策

[PDF](ablation-lazy-refresh.pdf) · [SVG](ablation-lazy-refresh.svg)

![E22](ablation-lazy-refresh.png)

## E27 AIMD 授权与实际副本占用

[PDF](aimd-quota-and-occupancy.pdf) · [SVG](aimd-quota-and-occupancy.svg)

![E27](aimd-quota-and-occupancy.png)

## E28 预警反馈是否随控制变化

[PDF](aimd-warning-windows.pdf) · [SVG](aimd-warning-windows.svg)

![E28](aimd-warning-windows.png)

## A10 强争用下动态控制的 WCT 影响

[PDF](ablation-aimd-interference.pdf) · [SVG](ablation-aimd-interference.svg)

![A10](ablation-aimd-interference.png)

## E29 共享路径带宽敏感性

[PDF](sensitivity-bandwidth.pdf) · [SVG](sensitivity-bandwidth.svg)

![E29](sensitivity-bandwidth.png)

## E30 DRAM 容量与正常命中

[PDF](sensitivity-dram-capacity.pdf) · [SVG](sensitivity-dram-capacity.svg)

![E30](sensitivity-dram-capacity.png)

## A11 活跃 Workflow 并发敏感性

[PDF](sensitivity-concurrency.pdf) · [SVG](sensitivity-concurrency.svg)

![A11](sensitivity-concurrency.png)

## A12 CPU 服务报价的敏感性

[PDF](sensitivity-cpu-quote.pdf) · [SVG](sensitivity-cpu-quote.svg)

![A12](sensitivity-cpu-quote.png)

## A13 硬件 DMA 争用系数的敏感性

[PDF](sensitivity-dma.pdf) · [SVG](sensitivity-dma.svg)

![A13](sensitivity-dma.png)
