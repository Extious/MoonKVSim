# 改版前的 36 张图

2026-09-08 获奖论文对照改版之前的文件快照。当前图见 [Paper_Figures.md](../../../../benchmark/AegisKV/experiments/Paper_Figures.md)。

## M1 并行分支的时间差

124 个存在观测重叠分支的真实工作流，每个样本取工作流内最大分支持续时间差；横轴为对数秒。持续时间差尚未验证为因果 CPM Slack。

[PDF](motivation-branch-gap.pdf) · [SVG](motivation-branch-gap.svg)

![并行分支的时间差](motivation-branch-gap.png)

## M2 相同恢复代价对应不同 Workflow 损失

固定 DAG 中仅一个分支受延迟、其余执行时间和资源条件不变时，暴露给 Workflow 的延迟为 max(恢复延迟 − Slack, 0)。0/5/10 s 是示意参数。

[PDF](motivation-exposed-recovery.pdf) · [SVG](motivation-exposed-recovery.svg)

![相同恢复代价对应不同 Workflow 损失](motivation-exposed-recovery.png)

## M3 额外 KV 副本的容量代价

Qwen3-8B BF16 按 147,456 B/token 计算；96 Ki tokens 的一份/两份 KV 为 13.5/27 GiB。灰线从 40 GiB 扣权重及 2 GiB runtime，未扣动态前台 KV。

[PDF](motivation-kv-capacity.pdf) · [SVG](motivation-kv-capacity.svg)

![额外 KV 副本的容量代价](motivation-kv-capacity.png)

## S1 整体数据流与控制职责

revision-3 设计。实线传 KV、虚线传控制；Source 分别写 Peer HBM 与 Store DRAM。恢复时已提交副本需装入新 primary。本轮执行范围由 Evaluation 配置表限定。

[PDF](system-overview.pdf) · [SVG](system-overview.svg)

![整体数据流与控制职责](system-overview.png)

## S2 Algorithm 1：从因果依赖得到 Slack ticket

残余 DAG 与剩余时间估计进入前向/后向 CPM；ES/LS 为最早/最晚开始时间，m 为保守余量。ticket 绑定 consumer、DAG 版本和有效期；信息不足的相关消费者回退为零 Slack。

[PDF](design-slack-tickets.pdf) · [SVG](design-slack-tickets.svg)

![Algorithm 1：从因果依赖得到 Slack ticket](design-slack-tickets.png)

## S3 Algorithm 2：共享前缀与删除闭包

C0/C1 由两个 consumer 共享，物理字节只计算一次。删除 C1 必须一并删除其已提交后代 C2-A/C2-B；虚线表示 consumer 引用，实线表示前缀父子关系。

[PDF](design-shared-prefix.pdf) · [SVG](design-shared-prefix.svg)

![Algorithm 2：共享前缀与删除闭包](design-shared-prefix.png)

## S4 Algorithm 3：前台约束先于保护

分配、复制、配额增长前同时检查 HBM 包络、传输许可和有效 QoS 证书。配额增长还需稳定余量、实际需求及已完成回收；失效即撤销，释放 ACK 前不能复用额度。

[PDF](design-foreground-budget.pdf) · [SVG](design-foreground-budget.svg)

![Algorithm 3：前台约束先于保护](design-foreground-budget.png)

## S5 复制完成与独立提交

同一 chunk 的 Peer copy ACK 先到，源故障时 DRAM 尚 pending，随后 abort。两个 tier 的提交状态独立；横轴只有逻辑先后，间距不是测得时长。

[PDF](commit-tier-timeline.pdf) · [SVG](commit-tier-timeline.svg)

![复制完成与独立提交](commit-tier-timeline.png)

## S6 故障时只有连续已提交前缀有效

承接图 S5，Peer 可恢复 chunks 0–1，DRAM 只有 chunk 0；aborted/absent 不计恢复 token。所有 chunk 均为示意对象。

[PDF](commit-recoverable-prefix.pdf) · [SVG](commit-recoverable-prefix.svg)

![故障时只有连续已提交前缀有效](commit-recoverable-prefix.png)

## S7 前缀装入与恢复解码是不同阶段

备份 chunks 0–1 先复制进新的 primary buffers，再重算 suffix 2、恢复解码。箭头不表示字节量或时长，装入完成不等于恢复完成。

[PDF](commit-materialize-recompute.pdf) · [SVG](commit-materialize-recompute.svg)

![前缀装入与恢复解码是不同阶段](commit-materialize-recompute.png)

## E1 原始输入的 Prompt 分布

冻结 FanOutQA 派生输入的 1,304 个请求；Ki=1,024 tokens。仅含原始访问，总上下文最大 86,214 tokens，未宣称覆盖 128K。

[PDF](workload-prompt_tokens.pdf) · [SVG](workload-prompt_tokens.svg)

![原始输入的 Prompt 分布](workload-prompt_tokens.png)

## E2 Workflow 规模分布

同一输入中 160 个 Workflow 的原始调用数分布，最大为 27；样本单位是 Workflow，两轮重访不混入这张输入统计图。

[PDF](workload-workflow_call_counts.pdf) · [SVG](workload-workflow_call_counts.svg)

![Workflow 规模分布](workload-workflow_call_counts.png)

## E3 逐 Workflow 的 WCT

无故障两轮重访，160 个 Workflow 严格配对；按 Mooncake WCT 统一排序。均值依次为 53.39/64.05/69.74 s；WCT 不含活跃 slot 外的入场等待。

[PDF](f0-revisit-wct.pdf) · [SVG](f0-revisit-wct.svg)

![逐 Workflow 的 WCT](f0-revisit-wct.png)

## E4 逐 Workflow 的 WCT 增减

图 E3 的逐对象差值：各系统 WCT 减 Mooncake WCT；正值更慢，负值更快。AegisKV 有 129/160 个 Workflow 更慢；不按正负筛选样本。

[PDF](f0-revisit-wct-difference.pdf) · [SVG](f0-revisit-wct-difference.svg)

![逐 Workflow 的 WCT 增减](f0-revisit-wct-difference.png)

## E5 WCT 的整体分布

图 E3 中全部 160 个 Workflow 的经验分布；保留完整尾部。这里的分布描述同一次执行中的异质工作流，不提供跨独立重复置信区间。

[PDF](f0-revisit-wct-cdf.pdf) · [SVG](f0-revisit-wct-cdf.svg)

![WCT 的整体分布](f0-revisit-wct-cdf.png)

## E6 准入改变后的 DRAM 复用率

正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问与第二轮访问。总体 token 加权比例为 48.08%/26.54%/18.89%，不是请求命中比例。

[PDF](f0-revisit-dram-hit.pdf) · [SVG](f0-revisit-dram-hit.svg)

![准入改变后的 DRAM 复用率](f0-revisit-dram-hit.png)

## E7 正常服务的缓存来源分解

对全部 prompt token 做互斥分解：Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。本配置正常请求的 Peer 命中为零；Peer 备份字节不算正常复用收益。

[PDF](f0-revisit-cache-sources.pdf) · [SVG](f0-revisit-cache-sources.svg)

![正常服务的缓存来源分解](f0-revisit-cache-sources.png)

## E8 前台 GPU 调度排队

点为 Workflow 内请求首次实际入 GPU 队列到首次计算的平均等待；CPU、GET 和 HBM 申请等待另计。请求级 P95 依次为 9.48/13.15/16.72 s，不能把点误读为 P95。

[PDF](f0-revisit-scheduler-queue.pdf) · [SVG](f0-revisit-scheduler-queue.svg)

![前台 GPU 调度排队](f0-revisit-scheduler-queue.png)

## E9 GET 目标 HBM 的申请等待

逐 Workflow 的请求平均 HBM 申请等待。跨请求累计为 414.33/63.42/4.15 s；方向与 GPU 排队不同，GET 样本量也随命中率变化，不能独立归因为 Peer。

[PDF](f0-revisit-hbm-wait.pdf) · [SVG](f0-revisit-hbm-wait.svg)

![GET 目标 HBM 的申请等待](f0-revisit-hbm-wait.png)

## E10 全部 GPU 的显存占用压力

按事件区间积分，统计每个 GPU 未分配 HBM 低于 1 GiB 的时间比例。包括可回收缓存占用，分母为各系统自身 workload makespan；不是硬件 HBM 带宽利用率。

[PDF](f0-revisit-hbm-pressure.pdf) · [SVG](f0-revisit-hbm-pressure.svg)

![全部 GPU 的显存占用压力](f0-revisit-hbm-pressure.png)

## E11 首 token 延迟分布

全部 2,608 个请求的 TTFT，横轴用对数秒以同时显示主体与完整尾部。P99 为 21.68/22.20/27.87 s；没有据此宣称满足原生 QoS 阈值。

[PDF](f0-revisit-ttft-cdf.pdf) · [SVG](f0-revisit-ttft-cdf.svg)

![首 token 延迟分布](f0-revisit-ttft-cdf.png)

## E12 请求平均 TPOT 的长尾

每系统 2,432 个 TPOT 有定义的请求；双对数生存曲线给出不小于横轴值的请求比例。每个请求先求平均 TPOT，不能当成逐 token 间隔分布。

[PDF](f0-revisit-tpot-tail.pdf) · [SVG](f0-revisit-tpot-tail.svg)

![请求平均 TPOT 的长尾](f0-revisit-tpot-tail.png)

## E13 逐 Workflow 的控制面代价

查询与准入的模型服务需求减 Mooncake 对应值；按相同 Workflow 配对。CPU 报价固定，前台查询 50 µs 为假设，不是原生 CPU 利用率。

[PDF](f0-revisit-controller-service-difference.pdf) · [SVG](f0-revisit-controller-service-difference.svg)

![逐 Workflow 的控制面代价](f0-revisit-controller-service-difference.png)

## E14 控制面服务需求的组成

按事件将前台查询与准入服务时间求和，总量为 2.58/5.44/6.05 s。该和不含排队，也不等于请求延迟或 CPU 使用百分比。

[PDF](f0-revisit-controller-breakdown.pdf) · [SVG](f0-revisit-controller-breakdown.svg)

![控制面服务需求的组成](f0-revisit-controller-breakdown.png)

## E15 逐 Workflow 的后台传输量

DRAM 写入与 Peer 复制的实际传输字节，含中止前已传部分及收尾阶段；按源请求归属 Workflow 累计。它表示累计流量，不能当作驻留副本容量。

[PDF](f0-revisit-background-copy.pdf) · [SVG](f0-revisit-background-copy.svg)

![逐 Workflow 的后台传输量](f0-revisit-background-copy.png)

## E16 新增 Peer 路径的传输成本

直接累计 Peer flow 的实际字节。Mooncake 和 DRAM-only 的两条零线重合，因为未启用该路径；不用两个系统的总流量之差估计 Peer 流量。

[PDF](f0-revisit-peer-copy.pdf) · [SVG](f0-revisit-peer-copy.svg)

![新增 Peer 路径的传输成本](f0-revisit-peer-copy.png)

## E17 前台读取与后台复制的组成

由实际传输记录互斥分解为正常 GET、DRAM 写入和 Peer 复制，含已传输的中止部分与收尾；TiB=2^40 bytes。Peer 开启后 DRAM 流量本身也会改变。

[PDF](f0-revisit-traffic-breakdown.pdf) · [SVG](f0-revisit-traffic-breakdown.svg)

![前台读取与后台复制的组成](f0-revisit-traffic-breakdown.png)

## E18 正常 GET 的链路争用

GET 数据服务时间 / 相同字节量的独占瓶颈服务时间，不含固定 setup。成功 GET 样本数为 1,284/773/662，P95 为 33.56/10.71/12.65 倍；不是隔离 Peer 效应的因果对照。

[PDF](f0-revisit-transfer-service_slowdown.pdf) · [SVG](f0-revisit-transfer-service_slowdown.svg)

![正常 GET 的链路争用](f0-revisit-transfer-service_slowdown.png)

## E19 25% 进度附近故障的逐 Workflow 影响

按无故障基准完成进度选择最接近 25% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](f1-q25-workflow-penalty.pdf) · [SVG](f1-q25-workflow-penalty.svg)

![25% 进度附近故障的逐 Workflow 影响](f1-q25-workflow-penalty.png)

## E20 50% 进度附近故障的逐 Workflow 影响

按无故障基准完成进度选择最接近 50% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](f1-q50-workflow-penalty.pdf) · [SVG](f1-q50-workflow-penalty.svg)

![50% 进度附近故障的逐 Workflow 影响](f1-q50-workflow-penalty.png)

## E21 75% 进度附近故障的逐 Workflow 影响

按无故障基准完成进度选择最接近 75% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。

[PDF](f1-q75-workflow-penalty.pdf) · [SVG](f1-q75-workflow-penalty.svg)

![75% 进度附近故障的逐 Workflow 影响](f1-q75-workflow-penalty.png)

## E22 故障位置与尾部 WCT 代价

三个预定故障位置的逐 Workflow WCT 差值之 P95，横轴为真实基准完成比例。先逐对象求差再求 P95；包含故障前已完成对象，因此跨位置的下降不能直接解释为单次恢复更容易。

[PDF](failure-progress-p95-penalty.pdf) · [SVG](failure-progress-p95-penalty.svg)

![故障位置与尾部 WCT 代价](failure-progress-p95-penalty.png)

## E23 故障请求恢复的阶段分解

每位置仅展示预先选定的焦点请求。前段为故障至连续前缀装入，后段为装入后至恢复解码；分别包括对应等待和实际服务。总长才是焦点请求恢复延迟。

[PDF](failure-focal-recovery-phases.pdf) · [SVG](failure-focal-recovery-phases.svg)

![故障请求恢复的阶段分解](failure-focal-recovery-phases.png)

## E24 带宽改变时的完成时间权衡

5/25/50 GB/s 的实际测试点，线性横轴。其他配置相同，每点每系统一次执行、160 个 Workflow。5 GB/s 均值为 150.45/81.00/82.07 s，比较方向反转。

[PDF](sensitivity-bandwidth-mean_wct_s.pdf) · [SVG](sensitivity-bandwidth-mean_wct_s.svg)

![带宽改变时的完成时间权衡](sensitivity-bandwidth-mean_wct_s.png)

## E25 并发压力与 Workflow 完成时间

活跃 Workflow 并发 8/16/32，线性横轴，其他条件相同。点为 160 个 Workflow 的平均 WCT；闭环入场时间随先前完成变化，不能作为开放到达率吞吐曲线。

[PDF](sensitivity-concurrency-mean_wct_s.pdf) · [SVG](sensitivity-concurrency-mean_wct_s.svg)

![并发压力与 Workflow 完成时间](sensitivity-concurrency-mean_wct_s.png)

## E26 DRAM 容量与正常复用率

32/128/931.3 GiB 的实际容量，对数横轴（底 2）。token 命中率包含两轮全部 prompt token；C=16、25 GB/s，每点每系统一次执行。

[PDF](sensitivity-dram-capacity-dram_hit_pct.pdf) · [SVG](sensitivity-dram-capacity-dram_hit_pct.svg)

![DRAM 容量与正常复用率](sensitivity-dram-capacity-dram_hit_pct.png)
