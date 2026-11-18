# AegisKV 旧图与诊断归档

<!-- AGENT_LEASE_REVISION_START -->
## 版本边界：当前算法与旧 PrefixAdmission

当前 [Paper_Draft.md](Paper_Draft.md) 使用 Agent 子租约 / Guarded AIMD 的 source-v3 实验。此前 33 图叙述完整保存在 [旧版论文图](Paper_Figures_PrefixAdmission_20260908.md) 和 [旧审查记录](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)，旧 raw 与图像未改写，不能用旧数值描述新算法。

改写为论文初稿前的图集正文保存在 [38 图目录版正文](../../../output/pdf/aegiskv-agent-lease-20260908/before-paper-draft/Paper_Figures.md)；精简前的 38 图初稿见 [本次精简前归档](../../../output/pdf/aegiskv-agent-lease-20260908/before-compact-paper/FIGURES.md)。当前正文 12 张，另有 43 张补充图保留在下方。

本轮 PaperBanana 优化前的同版 51 图保存在 [视觉修改前的完整目录](../../../output/pdf/aegiskv-agent-lease-20260908/before-paperbanana/FIGURES.md)；两版采用同一组数据，差异为表达与布局。

<a id="agent-lease-supplements"></a>
## 新算法的补充与诊断图

这些图来自同一新实验或实际 GPU 微基准。它们因叙述层级或与主图互补而放入补充材料，并非因为结果为零或不利；主文也保留不利结果。

### A1｜按联合 Workflow 收益分账

同一 DAG 的两条分支共享一个物理块；按固定 Agent 顺序逐个加入恢复改善，WCT 为 12→12→10 ms，分账为 0+2 ms。单个分支的重算下降不等于整个 Workflow 等额缩短。数值为可核算示意。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.png" width="1008" alt="A1 按联合 Workflow 收益分账">](../../../output/pdf/aegiskv-agent-lease-20260908/design-joint-wct.pdf)

### A2｜信用跨请求保留，按 Agent 新轮更新

共享尾块 X 上 A/B 信用为 6/4，竞争尾块 Y 为 2；按物理容量收租后 X 为 4.8/3.2，Y 淘汰。仅 A 进入新轮时 X 变为 6/3.2；同轮命中不能补回已花信用。内部块 R 不参加尾块收租。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.png" width="1008" alt="A2 信用跨请求保留，按 Agent 新轮更新">](../../../output/pdf/aegiskv-agent-lease-20260908/design-agent-subleases.pdf)

### A3｜单块试算、释放与提交

每个状态都只画一个共享 R；只从可释放尾块 Q 选牺牲者。空闲门为 G≥0，替换门为 G>D。版本核验后应用试算，free 完成后分配，复制 ACK 后才可恢复；失败不复活已释放的旧块。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.png" width="1008" alt="A3 单块试算、释放与提交">](../../../output/pdf/aegiskv-agent-lease-20260908/design-prefix-admission.pdf)

### A4｜独立的显存借用上限控制

40 GiB 示意布局明确区分前台、保留量、备份和 FREE。C 是硬上限，Q 是允许借用的额度，均不是实际占用；增长、预警减半和容量裁剪单独展示。实现使用 50 ms 窗口、连续 4 个稳定窗口、每次增 1 GiB、β=0.5。 右列表示下一步前台需求增加 4 GiB，裁剪后旧副本仍占 4 GiB，物理 free ACK 到达才降至 2 GiB。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.png" width="1008" alt="A4 独立的显存借用上限控制">](../../../output/pdf/aegiskv-agent-lease-20260908/design-guarded-aimd.pdf)

### A5｜独立提交决定故障后能恢复的前缀

同一 C1 的 Peer ACK 已到、DRAM 尚 pending 时 Source 故障，两个 tier 因而留下不同前缀。恢复仍须装入新 primary 并重算缺失后缀；图中间距仅表示逻辑次序。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.svg) · [可编辑源](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.drawio) · 设计示意 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.png" width="1008" alt="A5 独立提交决定故障后能恢复的前缀">](../../../output/pdf/aegiskv-agent-lease-20260908/commit-tier-timeline.pdf)

### A6｜输入的 Prompt 长度分布

冻结输入的 1,304 个原始请求；Ki=1,024 tokens。两轮扩展不作为新原始样本。总上下文最大 86,214 tokens，不能据此声称覆盖 128K。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.csv) · 输入统计 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.png" width="480" alt="A6 输入的 Prompt 长度分布">](../../../output/pdf/aegiskv-agent-lease-20260908/workload-prompt_tokens.pdf)

### A7｜输入的 Workflow 规模

160 个原始 Workflow 的调用数分布，最大为 27。样本单位是 Workflow；不是 160 次完整系统运行。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.csv) · 输入统计 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.png" width="480" alt="A7 输入的 Workflow 规模">](../../../output/pdf/aegiskv-agent-lease-20260908/workload-workflow_call_counts.pdf)

### A8｜逐 Workflow 的完成时间变化

各系统 WCT 减同一 Workflow 的 Mooncake WCT；零线为 Mooncake，正值更慢、负值更快。与上一图使用同一 ID 映射，不按差值重新排序。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.png" width="1008" alt="A8 逐 Workflow 的完成时间变化">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-difference.pdf)

### A9｜单一入场顺序的 WCT 分布

seed 0 的完整 160 对象经验分布；主文使用三种入场顺序的分布包络补充稳健性，本图保留为单配置核对。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-cdf.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-cdf.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-cdf.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-cdf.png" width="480" alt="A9 单一入场顺序的 WCT 分布">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-wct-cdf.pdf)

### A10｜实际复用来自哪一层

将全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。Peer 备份写入量不会被计为正常服务的命中收益。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.png" width="480" alt="A10 实际复用来自哪一层">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-cache-sources.pdf)

### A11｜正常请求的 GPU 调度排队

每个 Workflow 内请求的平均 GPU-ready→运行等待。GET、CPU 和等待分配 HBM 分开计量，不能把它们都写成 scheduler queue。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.png" width="1008" alt="A11 正常请求的 GPU 调度排队">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-scheduler-queue.pdf)

### A12｜GPU 的低空闲显存时间占比

按每张 GPU 的时长加权，统计 FREE 低于 1 GiB 的执行时间比例；保持真实 GPU 编号和同一阈值。包含可回收的普通缓存，低余量不等于 OOM、HBM 带宽饱和或服务违约。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.png" width="1008" alt="A12 GPU 的低空闲显存时间占比">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-hbm-pressure.pdf)

### A13｜请求 TTFT 的完整分布

所有 2,608 个请求从 release 到第一个输出 token 的经验分布；与只量 GPU prefill 的耗时不同，包含执行路径上的等待。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.png" width="480" alt="A13 请求 TTFT 的完整分布">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-ttft-cdf.pdf)

### A14｜请求平均 TPOT 的尾部

每系统 2,432 个分母有效的请求先计算首 token 后的平均 TPOT，再绘制包含等号的经验生存比例；保留完整尾部。它不是逐 token ITL 分布，也不是跨运行置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.png" width="480" alt="A14 请求平均 TPOT 的尾部">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-tpot-tail.pdf)

### A15｜逐 Workflow 的 CPU 服务报价变化

对准入和前台派发的固定 CPU 服务报价按 Workflow 归因，再减 Mooncake；全局控制 CPU 单独计量。这条曲线不是每个 Workflow 的实测 CPU 利用率。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.png" width="1008" alt="A15 逐 Workflow 的 CPU 服务报价变化">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-service-difference.pdf)

### A16｜进入模拟时序的控制 CPU 服务

固定服务报价的总和，分为前台派发和准入；经过同一个控制器队列。提交、回收和 AIMD 的全部 CPU 工作量还没有完整转成因果延迟。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.png" width="480" alt="A16 进入模拟时序的控制 CPU 服务">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-controller-breakdown.pdf)

### A17｜Python 参考实现的实际 CPU 工作量

按线程 CPU 时间分解前台派发、准入与 DAG、提交、回收与 AIMD，扣除嵌套计量避免重复。它是本参考实现的组件工作量，未覆盖原生服务的全部 CPU。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.csv) · Python 参考 CPU 实测 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.png" width="1008" alt="A17 Python 参考实现的实际 CPU 工作量">](../../../output/pdf/aegiskv-agent-lease-20260908/reference-cpu-breakdown.pdf)

### A18｜实际传输量的组成

累计模拟内传输的字节，分为正常 GET、DRAM 写入和 Peer 复制，纵轴 TiB。更多副本写入与较少正常命中可能同时发生，不能仅比较总字节得出带宽无争用。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.png" width="480" alt="A18 实际传输量的组成">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-traffic-breakdown.pdf)

### A19｜保护流量是否拖慢前台 GET

每个成功正常 GET 的实际传输服务时长 / 同字节量独占链路时长；横轴倍率。不同系统的命中对象和 GET 数量会变，CDF 是描述性分布。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.png" width="480" alt="A19 保护流量是否拖慢前台 GET">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-transfer-service_slowdown.pdf)

### A20｜逐 Workflow 的后台复制量

DRAM 与 Peer 实际后台传输之和，按源 Workflow 归因；与固定 Workflow 顺序的 WCT 图配套诊断。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.png" width="1008" alt="A20 逐 Workflow 的后台复制量">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-background-copy.pdf)

### A21｜逐 Workflow 的 Peer 复制量

只统计实际 Peer 传输，不用 AegisKV 总流量减 DRAM-only 来估算。Mooncake 与 DRAM-only 为重合零线。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.png" width="1008" alt="A21 逐 Workflow 的 Peer 复制量">](../../../output/pdf/aegiskv-agent-lease-20260908/f0-revisit-peer-copy.pdf)

### A22｜25% 进度选点的逐 Workflow 故障代价

三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 25% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 三个故障位置使用同一纵轴范围。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q25-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q25-workflow-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q25-workflow-penalty.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f1-q25-workflow-penalty.png" width="1008" alt="A22 25% 进度选点的逐 Workflow 故障代价">](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q25-workflow-penalty.pdf)

### A23｜75% 进度选点的逐 Workflow 故障代价

三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 75% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 三个故障位置使用同一纵轴范围。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q75-workflow-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q75-workflow-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q75-workflow-penalty.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/f1-q75-workflow-penalty.png" width="1008" alt="A23 75% 进度选点的逐 Workflow 故障代价">](../../../output/pdf/aegiskv-agent-lease-20260908/f1-q75-workflow-penalty.pdf)

### A24｜不同故障位置的尾部 Workflow 损失

每个预定故障位置，对全部 160 个配对 Workflow 的 F1−F0 求 P95。三个位置是不同干预，不是同条件三次独立重复；实际参考进度另表给出。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.png" width="480" alt="A24 不同故障位置的尾部 Workflow 损失">](../../../output/pdf/aegiskv-agent-lease-20260908/failure-progress-p95-penalty.pdf)

### A25｜保护缩短的是哪个恢复阶段

每根柱追踪同一个预定焦点请求：从故障到前缀装入，再到后缀计算与解码恢复；Peer/DRAM 恢复 token 和重算 token 另存 CSV。只缩短前缀装入不等于总恢复获益。 每个故障位置的柱从左到右均为 Mooncake、DRAM-only AegisKV、AegisKV；颜色表示系统，纹理表示恢复阶段。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.png" width="1008" alt="A25 保护缩短的是哪个恢复阶段">](../../../output/pdf/aegiskv-agent-lease-20260908/failure-focal-recovery-phases.pdf)

### A26｜何种故障概率下才能抵消正常开销

解析混合 E[WCT]=(1−p)·F0+p·平均 F1，假定一次完整执行至多一个故障，三个预定位置等权。p 是分析参数，不能解释成观测故障率、MTBF 或多次故障结果。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.csv) · 模拟结果的解析混合 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.png" width="1008" alt="A26 何种故障概率下才能抵消正常开销">](../../../output/pdf/aegiskv-agent-lease-20260908/benefit-cost-fault-mixture.pdf)

### A27｜更换入场顺序后的正常 WCT

三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。无故障、资源和两轮输入均相同。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.png" width="480" alt="A27 更换入场顺序后的正常 WCT">](../../../output/pdf/aegiskv-agent-lease-20260908/order-normal-wct.pdf)

### A28｜更换入场顺序后的故障代价

三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。每个顺序各自从 Mooncake F0 选择中期故障，再减本系统对应 F0。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.png" width="480" alt="A28 更换入场顺序后的故障代价">](../../../output/pdf/aegiskv-agent-lease-20260908/order-failure-penalty.pdf)

### A29｜真实 forward 与 DMA 并发：batch 1

batch=1，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.png" width="480" alt="A29 真实 forward 与 DMA 并发：batch 1">](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b1.pdf)

### A30｜真实 forward 与 DMA 并发：batch 4

batch=4，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.png" width="480" alt="A30 真实 forward 与 DMA 并发：batch 4">](../../../output/pdf/aegiskv-agent-lease-20260908/native-forward-b4.pdf)

### A31｜分配容量与复制争用分别测量

batch=4、prompt=4,096，额外触达分配 0/8/16 GiB；比较四种 DMA 条件的真实 forward 时长。纵轴放大局部变化，零 OOM 只适用于这批条件。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.png" width="480" alt="A31 分配容量与复制争用分别测量">](../../../output/pdf/aegiskv-agent-lease-20260908/native-memory-occupancy.pdf)

### A32｜真实复制速率随前台计算变化

batch=1、额外占用 8 GiB，按每个块的实际复制字节 / 复制完成时间聚合；256 MiB 缓冲反复复制。这里的并发有效速率不是链路标称容量。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.png" width="480" alt="A32 真实复制速率随前台计算变化">](../../../output/pdf/aegiskv-agent-lease-20260908/native-concurrent-copy.pdf)

### A33｜撤销备份后的实际释放延迟

1/4/8 GiB 分配各 20 次：等待异步写入 fence 与 allocator free+empty_cache+同步分开测。两部分都是实测完成时间，不能直接替代原生服务的回收延迟。 标记和误差线为 20 次测量的中位数与最小/最大值。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.png" width="480" alt="A33 撤销备份后的实际释放延迟">](../../../output/pdf/aegiskv-agent-lease-20260908/native-release-ack.pdf)

### A34｜原生复制线程的 CPU 需求

batch=1、额外占用 8 GiB，测量整个 forward 窗口的进程 CPU / 墙钟时间，以核数表示；包含本微基准的复制线程与 CUDA 同步等待。它不等价于原生 AegisKV 准入 CPU 或整台服务器利用率。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.csv) · 真实 GPU 组件微基准 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.png" width="480" alt="A34 原生复制线程的 CPU 需求">](../../../output/pdf/aegiskv-agent-lease-20260908/native-copy-cpu.pdf)

### A35｜Algorithm 2 / 3 的正常服务消融

分别去掉 DAG 联合价值、将空闲门改为严格 G>0、或将动态 Peer 改为静态容量上限。相同输入与 CPU 报价，每次只改一个因素；减少保护可能降低正常开销，也可能损失恢复覆盖。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.png" width="1008" alt="A35 Algorithm 2 / 3 的正常服务消融">](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-normal-wct.pdf)

### A36｜惰性计算是否保持同样的准入决策

DRAM-only 上比较 Lazy / Eager：两者都检查全部可释放尾块，只允许跳过版本未变的价值计算。比较每次接纳/拒绝与牺牲块序列必须完全相同；计数包含被拒绝的试算。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.png" width="480" alt="A36 惰性计算是否保持同样的准入决策">](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-lazy-refresh.pdf)

### A37｜预警反馈是否随控制变化

同一 30% 争用假设下，比较 Guarded AIMD 和只保留显存上限的 Static Peer；1 s 桶内统计产生归一化 forward 预警的目标窗口比例。预警不是请求 SLO 违约率。 纵轴 0–20% 覆盖全部观测值。 两张控制时序图共用横轴范围，各曲线保留自身观测终点。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.csv) · 未标定机制模拟 · 7.00 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.png" width="1008" alt="A37 预警反馈是否随控制变化">](../../../output/pdf/aegiskv-agent-lease-20260908/aimd-warning-windows.pdf)

### A38｜强争用下动态控制的 WCT 影响

相同 30% DMA 假设，比较 DRAM-only、Guarded AIMD 和 Static Peer；静态版本仍尊重显存硬上限。容量守恒与前台时延保护是两个不同问题。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.png" width="480" alt="A38 强争用下动态控制的 WCT 影响">](../../../output/pdf/aegiskv-agent-lease-20260908/ablation-aimd-interference.pdf)

### A39｜共享路径带宽敏感性

实际执行 5/25/50 GB/s，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.png" width="480" alt="A39 共享路径带宽敏感性">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-bandwidth.pdf)

### A40｜DRAM 容量与正常命中

实际执行 250 GB / 1 TB，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.png" width="480" alt="A40 DRAM 容量与正常命中">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dram-capacity.pdf)

### A41｜活跃 Workflow 并发敏感性

实际执行 16/32 个活跃 Workflow，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.png" width="480" alt="A41 活跃 Workflow 并发敏感性">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-concurrency.pdf)

### A42｜CPU 服务报价的敏感性

实际执行 1×/2× 固定 CPU 报价，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 纵轴展示实际秒值的局部范围，以辨认小幅差异。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.png" width="480" alt="A42 CPU 服务报价的敏感性">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-cpu-quote.pdf)

### A43｜硬件 DMA 争用系数的敏感性

实际执行 0/5/30% 额外 forward 时长，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 纵轴展示实际秒值的局部范围，以辨认小幅差异。

[PDF](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.pdf) · [SVG](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.svg) · [逐点数据](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.csv) · 未标定机制模拟 · 3.33 inch

[<img src="../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.png" width="480" alt="A43 硬件 DMA 争用系数的敏感性">](../../../output/pdf/aegiskv-agent-lease-20260908/sensitivity-dma.pdf)

<!-- AGENT_LEASE_REVISION_END -->












[论文叙述与新图](Paper_Draft.md) · [逐图修改记录](PAPER_FIGURE_REVIEW.md) · [总导航](FIGURES.md)

这里保留 source-v6 的 186 张原版图、历史版本、格式副本和原审查记录。原图文件与原始数据均未覆盖。本轮对原论文版 21 张图全部重绘；新增机制与结果图在论文版按三部分叙述。归档保留零结果和不利结果，不能据是否入选判断数据真假。

[重写前的 21 图论文版](../../../output/paper-story-20260908/before-story-Paper_Figures.md) · [重写前的归档](../../../output/paper-story-20260908/before-story-Old_Figures.md)

[本次获奖论文对照改版前的 36 图](../../../output/pdf/aegiskv-paper-story-20260908/before-best-paper-review/FIGURES.md)

<!-- THREE_SYSTEM_REVIEW_START -->
<a id="three-system-review"></a>
## 2026-09-08 source-v6 完整图与诊断

本轮实验、逐图审查与独立导出已完成。

本节保留 source-v6 的 **186 张原始独立图**；它们的重绘版及新增证据见 [Paper_Draft.md](Paper_Draft.md)。

**图例固定为 Mooncake、DRAM-only AegisKV、AegisKV。** DRAM-only 是禁用 Peer HBM 的 AegisKV 消融，Mooncake 使用单独的 LRU Store 模拟基线。每个 workflow 图的横轴按 workflow ID 升序；三条线的同一索引对应同一 workflow，差值图中的 Mooncake 为零线。

**证据范围：本轮为新的机制模拟实验，仍不是原生 serving 性能或完整 Algorithm 3 的 QoS 认证结果。** AegisKV 的 Peer 主配置为受内存包络约束的资源探索；严格控制器在无证书时给出零配额。CPU 图实测 Python 参考准入线程时间，CPU 队列使用显式服务模型；未建模推理 kernel 与 DMA 的硬件 HBM 带宽竞争。旧论文图的版本与原始数据保留在后面的历史审查中。

[三系统定义、配置、指标公式、实现修复及证据边界](THREE_SYSTEM_PROTOCOL.md) · [新实验适配器](../../../python/moonkvsim/aegiskv/mechanism_experiment.py) · [实验入口](scripts/run_three_system_mechanisms.py) · [原始数据审计/CSV 提取](scripts/paper/three_system_data.py) · [独立图生成器](scripts/paper/render_three_system_figures.py)

基础配置：Qwen3-8B，DP=8/TP=PP=1，8×40 GiB GPU 模型，DRAM=10¹² B，共享路径 25 GB/s，chunk=4,096 tokens，C=16，seed=0。160 个原始 workflows 含 1,304 requests；受控 exact-input revisits 是同一 DAG 的两轮访问，含 2,608 requests，明确标记为 synthetic。每配置/系统一次执行，图中的 workflow 点不作为独立运行重复或置信区间样本。

| 原论文图 | 本轮审查与更新入口 |
|---|---|
| G01-01 / 11 / 12 / 13 | [观测分支差、具体工作流、旧模型反事实分别导出，分别交代观测/重建/反事实背景](#three-system-supporting) |
| G01-02 | [解析 KV 容量与 RTX4090 小规模传输样本分开](#three-system-supporting) |
| G01-03 / 04 | [架构图复查；提交时序、故障前缀、materialize/recompute 拆为三张独立图](#three-system-diagrams) |
| G01-05 | [prompt、workflow calls、context bins 分开，保留 128K 零样本](#three-system-supporting) |
| G01-06 | [三系统逐 workflow WCT、差值、cache hit rate、排队/HBM/CPU/带宽；原始 trace 对照另列](#three-system-f0-revisit) |
| G01-07 / 08 | [三系统故障 WCT、相对自身 F0 的罚时、同一逻辑请求的恢复来源与时序](#three-system-f1-natural) |
| G01-09 / 10 | [当前机制消融与单因素敏感性，保留不利或零效果，不沿用旧算法的 run 散点](#three-system-cross-case) |

[冻结矩阵协议](../../../output/three-system-20260908/campaign-final/PROTOCOL.json) · [执行状态](../../../output/three-system-20260908/campaign-final/STATUS.json)

[原始数据/统一源码/图像/链接总审计](../../../output/three-system-20260908/campaign-final/DELIVERY_AUDIT.json) · [逐图视觉审查记录](../../../output/three-system-20260908/campaign-final/VISUAL_REVIEW.json)

### 本轮数据回答了什么

以下数值均来自统一源码的受控两轮访问配置，按 Mooncake / DRAM-only AegisKV / AegisKV 顺序列出。它主动提供相同输入的再次访问机会，不是采集到的用户复用分布。

**DRAM 准入与复用。** 正常 DRAM token 命中贡献为 48.080% / 26.539% / 18.895%；Mean WCT 为 53.3891 s / 64.0476 s / 69.7440 s。AegisKV 相对 Mooncake 有 129/160 个 Workflow 的 WCT 更长；最大增量是索引 61（`552c8e5b3b63159e`）的 117.3271 s。

**Peer HBM 与前台等待。** 为正常 GET 取得目标 HBM 的累计等待为 414.333 s / 63.421 s / 4.155 s，调度抢占次数为 82 / 21 / 5，请求纯 GPU 排队 P95 为 9.4832 s / 13.1489 s / 16.7163 s。累计等待是跨请求求和，不能直接当成增加的 WCT；AegisKV 与 DRAM-only 的配对曲线用于观察加入 Peer 后的整体资源影响。

**CPU 与传输。** 冻结模型中的控制器服务工作量为 2.5815 s / 5.4426 s / 6.0538 s；实测 Python 参考准入线程 CPU 时间为 3.4576 s / 6.7010 s / 7.6142 s。两种口径分别绘制，后者受共享主机运行环境影响，不是原生 serving CPU 利用率。后台 DRAM 写入和 Peer 复制另列，GET 减速比依据每次读取自己的字节数与路径瓶颈归一化。

**解释限制。** GET 的样本数与读取量会随缓存命中变化，跨系统 GET P95 的差异包含这些变化；它不是单独关闭 Peer 流量后的反事实效应。图中同时保留逐 Workflow 命中、等待、复制量以及实际链路分项。原始一次访问 trace 的正常 DRAM hit 为零，因此只能作为低复用对照。

**配置敏感性与零结果。** 上述 25 GB/s 配置中的 WCT 方向不能推广到所有带宽。在其他设置相同的 5 GB/s 配置下，三系统 Mean WCT 为 150.4525 s / 81.0019 s / 82.0662 s，AegisKV 此时更快，但 DRAM 命中贡献仍更低。命中收益需要同时考虑读取成本；这组对比尚未独立分离各项调度与传输效应。

本轮 F0/F1 零 Slack 消融中，两个 AegisKV 变体的所有 Workflow WCT 均与各自基础配置相同；当前样本不能支持 Slack 带来性能改善的结论。


### 已完成数据与配置

Mean/P95 WCT 以 workflow 为单位，P95 GPU queue 以 request 为单位；DRAM hit 为 token 贡献比例。图与 CSV 保留全部工作流，不从每个系统分别排序取点。

| 配置 | 系统 | Mean WCT (s) | P95 WCT (s) | DRAM hit (%) | P95 GPU queue (s) | 来源 |
|---|---|---:|---:|---:|---:|---|
| `f0-cpu4x` | Mooncake | 39.0669 | 65.7925 | 0.000 | 15.1605 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-cpu4x/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-cpu4x/mooncake.json) |
| `f0-cpu4x` | DRAM-only AegisKV | 39.5117 | 69.4398 | 0.000 | 15.0778 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-cpu4x/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-cpu4x/dram.json) |
| `f0-cpu4x` | AegisKV | 39.5119 | 69.4400 | 0.000 | 15.0772 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-cpu4x/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-cpu4x/aegis.json) |
| `f0-guarded-no-certificate` | AegisKV | 39.0658 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-guarded-no-certificate/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-guarded-no-certificate/aegis.json) |
| `f0-natural` | Mooncake | 39.0656 | 65.7910 | 0.000 | 15.1609 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-natural/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-natural/mooncake.json) |
| `f0-natural` | DRAM-only AegisKV | 39.0658 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-natural/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-natural/dram.json) |
| `f0-natural` | AegisKV | 39.0658 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-natural/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-natural/aegis.json) |
| `f0-no-slack` | DRAM-only AegisKV | 39.0658 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-no-slack/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-no-slack/dram.json) |
| `f0-no-slack` | AegisKV | 39.0658 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-no-slack/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-no-slack/aegis.json) |
| `f0-revisit` | Mooncake | 53.3891 | 94.2596 | 48.080 | 9.4832 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit/mooncake.json) |
| `f0-revisit` | DRAM-only AegisKV | 64.0476 | 112.6966 | 26.539 | 13.1489 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit/dram.json) |
| `f0-revisit` | AegisKV | 69.7440 | 123.1135 | 18.895 | 16.7163 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit/aegis.json) |
| `f0-revisit-bw5` | Mooncake | 150.4525 | 324.2108 | 32.325 | 6.9809 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw5/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw5/mooncake.json) |
| `f0-revisit-bw5` | DRAM-only AegisKV | 81.0019 | 144.9199 | 3.590 | 20.0212 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw5/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw5/dram.json) |
| `f0-revisit-bw5` | AegisKV | 82.0662 | 132.9614 | 0.087 | 18.2895 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw5/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw5/aegis.json) |
| `f0-revisit-bw50` | Mooncake | 48.4002 | 89.0910 | 48.419 | 10.4199 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw50/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw50/mooncake.json) |
| `f0-revisit-bw50` | DRAM-only AegisKV | 55.8674 | 93.8344 | 35.074 | 11.8209 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw50/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw50/dram.json) |
| `f0-revisit-bw50` | AegisKV | 58.1801 | 92.6498 | 30.235 | 13.9958 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-bw50/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-bw50/aegis.json) |
| `f0-revisit-c32` | Mooncake | 92.3582 | 191.2242 | 46.314 | 14.3357 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c32/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c32/mooncake.json) |
| `f0-revisit-c32` | DRAM-only AegisKV | 108.3981 | 228.6398 | 26.185 | 20.5553 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c32/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c32/dram.json) |
| `f0-revisit-c32` | AegisKV | 123.4402 | 222.7399 | 16.893 | 28.3332 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c32/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c32/aegis.json) |
| `f0-revisit-c8` | Mooncake | 31.4517 | 56.1914 | 47.428 | 6.5701 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c8/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c8/mooncake.json) |
| `f0-revisit-c8` | DRAM-only AegisKV | 38.3082 | 69.3523 | 27.839 | 8.8856 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c8/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c8/dram.json) |
| `f0-revisit-c8` | AegisKV | 40.8135 | 68.7012 | 22.121 | 9.5645 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-c8/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-c8/aegis.json) |
| `f0-revisit-dram128` | Mooncake | 76.7099 | 130.2493 | 7.545 | 18.5786 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram128/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram128/mooncake.json) |
| `f0-revisit-dram128` | DRAM-only AegisKV | 76.0200 | 122.2839 | 7.531 | 16.2762 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram128/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram128/dram.json) |
| `f0-revisit-dram128` | AegisKV | 79.0756 | 128.5724 | 7.033 | 17.9081 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram128/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram128/aegis.json) |
| `f0-revisit-dram32` | Mooncake | 83.1382 | 130.5875 | 0.422 | 19.9126 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram32/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram32/mooncake.json) |
| `f0-revisit-dram32` | DRAM-only AegisKV | 81.6894 | 135.5831 | 0.745 | 17.3457 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram32/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram32/dram.json) |
| `f0-revisit-dram32` | AegisKV | 82.0348 | 126.1713 | 0.980 | 18.4248 | [Workflow CSV](../../../output/three-system-20260908/data-final/f0-revisit-dram32/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f0-revisit-dram32/aegis.json) |
| `f1-natural` | Mooncake | 39.0583 | 65.7910 | 0.000 | 15.1609 | [Workflow CSV](../../../output/three-system-20260908/data-final/f1-natural/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f1-natural/mooncake.json) |
| `f1-natural` | DRAM-only AegisKV | 39.0585 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f1-natural/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f1-natural/dram.json) |
| `f1-natural` | AegisKV | 39.0512 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f1-natural/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f1-natural/aegis.json) |
| `f1-no-slack` | DRAM-only AegisKV | 39.0585 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f1-no-slack/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f1-no-slack/dram.json) |
| `f1-no-slack` | AegisKV | 39.0512 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f1-no-slack/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f1-no-slack/aegis.json) |
| `f2-natural` | Mooncake | 39.0587 | 65.7910 | 0.000 | 15.1609 | [Workflow CSV](../../../output/three-system-20260908/data-final/f2-natural/mooncake-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f2-natural/mooncake.json) |
| `f2-natural` | DRAM-only AegisKV | 39.0589 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f2-natural/dram-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f2-natural/dram.json) |
| `f2-natural` | AegisKV | 39.0515 | 65.7911 | 0.000 | 15.1611 | [Workflow CSV](../../../output/three-system-20260908/data-final/f2-natural/aegis-workflows.csv) / [审计/配置](../../../output/three-system-20260908/data-final/f2-natural/aegis.json) |

原始单次访问 trace 中，短公共前缀可使请求命中比例很高，但 token 覆盖率很低；DRAM 正常复用为零的配置不绘制空 GET 延迟分布。受控 revisits 用于检验准入与缓存容量对长前缀正常复用的影响，不能当作真实用户复用分布。FREE HBM 很低也可能只是可回收缓存占用，需同时看 HBM 等待、抢占与纯 GPU 排队图。

<a id="three-system-supporting"></a>
### supporting

背景、原始数据与配置见上方逐图审查表及协议文档。此组属于观测、解析或机制图，无需强加三条系统性能曲线。

<details>
<summary>展开 7 张独立图及绘制说明</summary>

**motivation-branch-gap** — 124 个有观测重叠分支的工作流；原始持续时间差分布

审查记录：124 个满足观测重叠条件的真实工作流，每个样本取并行分支持续时间的最大差，横轴使用对数刻度。它说明分支持续时间不均衡，不等于经过因果 DAG 验证的可用 CPM Slack。来源：[观测 gap CSV](results/paper/data/motivation-real-cc/real-cc-workflow-parallel-gap.csv) / [原始重建审计](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)。

[PNG](../../../output/pdf/three-system-20260908/motivation-branch-gap.png) · [SVG](../../../output/pdf/three-system-20260908/motivation-branch-gap.svg) · [PDF](../../../output/pdf/three-system-20260908/motivation-branch-gap.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![motivation-branch-gap](../../../output/pdf/three-system-20260908/motivation-branch-gap.png)

**motivation-failure-position** — 历史 235B 模型反事实；不是 Qwen3-8B 实测恢复

审查记录：同一个五分支工作流的历史 Qwen3-235B-A22B/A100-80GB/TP8/PP4/EP8 反事实。暴露给 workflow 的恢复时间为 max(recompute−slack, 0)，其余为被 Slack 吸收的部分。五个分支不是五次故障实测，不与新 Qwen3-8B 结果合并。来源：[五分支重建与反事实 CSV](results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv)。

[PNG](../../../output/pdf/three-system-20260908/motivation-failure-position.png) · [SVG](../../../output/pdf/three-system-20260908/motivation-failure-position.svg) · [PDF](../../../output/pdf/three-system-20260908/motivation-failure-position.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![motivation-failure-position](../../../output/pdf/three-system-20260908/motivation-failure-position.png)

**motivation-kv-capacity** — Qwen3-8B BF16 KV 的解析容量关系；不是系统性能测量

审查记录：按 Qwen3-8B BF16 的 147,456 B/token 解析计算一份/两份 KV；96 Ki tokens 分别占 13.5/27 GiB。参考线从 40 GiB 扣除 16,381,470,720 B 权重及 2 GiB runtime，只是资源包络，未扣动态前台 KV；不是可直接借用的 Peer 配额。配置见 [三系统协议](THREE_SYSTEM_PROTOCOL.md)。

[PNG](../../../output/pdf/three-system-20260908/motivation-kv-capacity.png) · [SVG](../../../output/pdf/three-system-20260908/motivation-kv-capacity.svg) · [PDF](../../../output/pdf/three-system-20260908/motivation-kv-capacity.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![motivation-kv-capacity](../../../output/pdf/three-system-20260908/motivation-kv-capacity.png)

**motivation-physical-paths** — 2×RTX4090 host-staged 小规模物理路径样本，与 A100 模拟配置分开

审查记录：历史 2×RTX4090、Qwen3-8B、DP2/TP1/PP1 小规模物理样本；HBM write/DRAM write/HBM load/DRAM load 分别有 2/4/1/1 个样本。空心圆为逐样本字节数/时间，菱形为总字节数/总时间，均用十进制 GB/s。Peer 路径经 host staging，不能当作 CUDA P2P 或本轮 25 GB/s 模型的硬件标定。来源：[物理样本与导入来源](results/paper/data/physical-pilot/pilot-cost-profile.json)。

[PNG](../../../output/pdf/three-system-20260908/motivation-physical-paths.png) · [SVG](../../../output/pdf/three-system-20260908/motivation-physical-paths.svg) · [PDF](../../../output/pdf/three-system-20260908/motivation-physical-paths.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![motivation-physical-paths](../../../output/pdf/three-system-20260908/motivation-physical-paths.png)

**workload-context-bins** — 上下文分桶，96–128 Ki 桶保持零样本

审查记录：按 prompt 加预定输出的总上下文计数，桶边界为 0/8/16/32/64/96/128 Ki。96–128 Ki 桶为零，保留空桶以显示实际覆盖范围，不能宣称本输入覆盖 128K。来源：[冻结输入与统计数组](results/paper/data/publication-figure-inputs.json) / [原始精确 token trace](workloads/fanoutqa-dev-qwen3-8b-160.jsonl)。

[PNG](../../../output/pdf/three-system-20260908/workload-context-bins.png) · [SVG](../../../output/pdf/three-system-20260908/workload-context-bins.svg) · [PDF](../../../output/pdf/three-system-20260908/workload-context-bins.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![workload-context-bins](../../../output/pdf/three-system-20260908/workload-context-bins.png)

**workload-prompt_tokens** — 原始冻结 FanOutQA；1304 个 Requests

审查记录：展示 1,304 个原始请求的 prompt 长度 CDF，横轴 Ki=1,024 tokens。用于交代输入规模；不混入本轮人为追加的第二轮重访。来源：[冻结输入与统计数组](results/paper/data/publication-figure-inputs.json) / [原始精确 token trace](workloads/fanoutqa-dev-qwen3-8b-160.jsonl)。

[PNG](../../../output/pdf/three-system-20260908/workload-prompt_tokens.png) · [SVG](../../../output/pdf/three-system-20260908/workload-prompt_tokens.svg) · [PDF](../../../output/pdf/three-system-20260908/workload-prompt_tokens.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![workload-prompt_tokens](../../../output/pdf/three-system-20260908/workload-prompt_tokens.png)

**workload-workflow_call_counts** — 原始冻结 FanOutQA；160 个 Workflows

审查记录：展示 160 个原始 workflow 的调用数分布，横轴包含实际最大值 27。样本单位是 workflow；受控两轮负载的调用数不用于这张原始分布图。来源：[冻结输入与统计数组](results/paper/data/publication-figure-inputs.json) / [原始精确 token trace](workloads/fanoutqa-dev-qwen3-8b-160.jsonl)。

[PNG](../../../output/pdf/three-system-20260908/workload-workflow_call_counts.png) · [SVG](../../../output/pdf/three-system-20260908/workload-workflow_call_counts.svg) · [PDF](../../../output/pdf/three-system-20260908/workload-workflow_call_counts.pdf) · [图像清单](../../../output/pdf/three-system-20260908/supporting-figure-manifest.json)

![workload-workflow_call_counts](../../../output/pdf/three-system-20260908/workload-workflow_call_counts.png)

</details>

<a id="three-system-diagrams"></a>
### diagrams

背景、原始数据与配置见上方逐图审查表及协议文档。此组属于观测、解析或机制图，无需强加三条系统性能曲线。

<details>
<summary>展开 5 张独立图及绘制说明</summary>

**commit-materialize-recompute** — 备份先复制到独立 primary，再重算未保护 suffix；机制示意。

审查记录：承接前缀示例，先将 committed chunks 0–1 复制到新 primary，再重算未保护 suffix 2。图示区分前缀装入完成与恢复解码，不把 Peer 对象直接视作 primary KV；箭头长度无时间或字节比例。

[PNG](../../../output/pdf/three-system-20260908/commit-materialize-recompute.png) · [SVG](../../../output/pdf/three-system-20260908/commit-materialize-recompute.svg) · [PDF](../../../output/pdf/three-system-20260908/commit-materialize-recompute.pdf) · [Draw.io](../../../output/pdf/three-system-20260908/commit-materialize-recompute.drawio) · [图像清单](../../../output/pdf/three-system-20260908/diagrams-figure-manifest.json)

![commit-materialize-recompute](../../../output/pdf/three-system-20260908/commit-materialize-recompute.png)

**commit-recoverable-prefix** — 逻辑故障时 committed/aborted/absent 的区别，pending 不取得恢复收益。

审查记录：承接提交语义示例，HBM 的 chunk 0–1 committed，DRAM 只有 chunk 0 committed；aborted/absent 不提供恢复 token。两个 tier 分别计算连续可恢复前缀，不能把未完成复制或离散对象拼成有效前缀。图中三个 chunk 是示意对象。

[PNG](../../../output/pdf/three-system-20260908/commit-recoverable-prefix.png) · [SVG](../../../output/pdf/three-system-20260908/commit-recoverable-prefix.svg) · [PDF](../../../output/pdf/three-system-20260908/commit-recoverable-prefix.pdf) · [Draw.io](../../../output/pdf/three-system-20260908/commit-recoverable-prefix.drawio) · [图像清单](../../../output/pdf/three-system-20260908/diagrams-figure-manifest.json)

![commit-recoverable-prefix](../../../output/pdf/three-system-20260908/commit-recoverable-prefix.png)

**commit-tier-timeline** — 同一 chunk 的独立 tier 提交顺序；横轴无实测时间比例。

审查记录：示例中同一 chunk 已获得 HBM copy ACK，而 DRAM 写入在源故障时仍 pending，因此两个 tier 的最终状态不同。横轴只有事件先后，长度不表示实测传输时延；这是提交语义示意，不是一次性能运行。

[PNG](../../../output/pdf/three-system-20260908/commit-tier-timeline.png) · [SVG](../../../output/pdf/three-system-20260908/commit-tier-timeline.svg) · [PDF](../../../output/pdf/three-system-20260908/commit-tier-timeline.pdf) · [Draw.io](../../../output/pdf/three-system-20260908/commit-tier-timeline.drawio) · [图像清单](../../../output/pdf/three-system-20260908/diagrams-figure-manifest.json)

![commit-tier-timeline](../../../output/pdf/three-system-20260908/commit-tier-timeline.png)

**motivation-workflow** — 单个真实 trace 工作流的五分支重建；包含推断 join 与故障参考位置，非故障实测。

审查记录：重建一个观测五分支的执行区间，以最晚分支结束推断 join；红色故障线是 349.5 s 的反事实参考位置，绿色段是相对该 join 的剩余 Slack。横轴沿用 trace 时间，未声称该时刻真的发生过故障。来源：[五分支重建与反事实 CSV](results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv)。

[PNG](../../../output/pdf/three-system-20260908/motivation-workflow.png) · [SVG](../../../output/pdf/three-system-20260908/motivation-workflow.svg) · [PDF](../../../output/pdf/three-system-20260908/motivation-workflow.pdf) · [Draw.io](../../../output/pdf/three-system-20260908/motivation-workflow.drawio) · [图像清单](../../../output/pdf/three-system-20260908/diagrams-figure-manifest.json)

![motivation-workflow](../../../output/pdf/three-system-20260908/motivation-workflow.png)

**system-overview** — 架构与路径；实线 KV 数据、虚线控制。图表达设计，GBDT/QoS 证书等不是本轮已完成性能证据。

审查记录：表达 revision-3 的设计职责及 KV/控制路径：Source 分别写入 Peer 与 DRAM，故障后备份需装入独立 primary。实线为数据，虚线为控制。图中的 GBDT、完整 QoS 认证及原生服务组件不代表本轮均已执行；实现范围见 [协议的能力边界](THREE_SYSTEM_PROTOCOL.md)。

[PNG](../../../output/pdf/three-system-20260908/system-overview.png) · [SVG](../../../output/pdf/three-system-20260908/system-overview.svg) · [PDF](../../../output/pdf/three-system-20260908/system-overview.pdf) · [Draw.io](../../../output/pdf/three-system-20260908/system-overview.drawio) · [图像清单](../../../output/pdf/three-system-20260908/diagrams-figure-manifest.json)

![system-overview](../../../output/pdf/three-system-20260908/system-overview.png)

</details>

<a id="three-system-f0-natural"></a>
### f0-natural

配置：160 workflows / 1304 requests；C=16；revisit rounds=1；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details open>
<summary>展开 51 张独立图及绘制说明</summary>

**f0-natural-background-copy** — 逐 workflow 后台 DRAM/Peer 复制实际消耗字节，包含中止前已经传输的字节

审查记录：160 个配对 Workflow：Mooncake：中位数 19.62，范围 [1.846, 101.5] GiB；DRAM-only AegisKV：中位数 17.74，范围 [0.2812, 75.99] GiB；AegisKV：中位数 29.13，范围 [2.839, 131.5] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-background-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-background-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-background-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-background-copy](../../../output/pdf/three-system-20260908/f0-natural-background-copy.png)

**f0-natural-background-copy-difference** — Background copy difference from Mooncake (GiB)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 -1.477，范围 [-30.09, 14.17] GiB；AegisKV：中位数 8.222，范围 [-9.932, 58.04] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-background-copy-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-background-copy-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-background-copy-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-background-copy-difference](../../../output/pdf/three-system-20260908/f0-natural-background-copy-difference.png)

**f0-natural-cache-hit** — 正常服务的 token 加权 KV 命中率

审查记录：160 个配对 Workflow：Mooncake：中位数 0.3425，范围 [0.05353, 2.821] %；DRAM-only AegisKV：中位数 0.3425，范围 [0.05353, 2.821] %；AegisKV：中位数 0.3425，范围 [0.05353, 2.821] %。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cache-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cache-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cache-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cache-hit](../../../output/pdf/three-system-20260908/f0-natural-cache-hit.png)

**f0-natural-cache-hit-difference** — Cache-hit difference from Mooncake (pp)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] pp；DRAM-only AegisKV：中位数 0，范围 [0, 0] pp；AegisKV：中位数 0，范围 [0, 0] pp。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cache-hit-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cache-hit-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cache-hit-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cache-hit-difference](../../../output/pdf/three-system-20260908/f0-natural-cache-hit-difference.png)

**f0-natural-controller-service** — 逐 workflow 冻结 CPU 模型服务量（查询＋准入），用于可重复的控制面代价比较

审查记录：冻结 CPU 服务模型的工作量：Mooncake：中位数 8.01，范围 [2.902, 43.77] ms；DRAM-only AegisKV：中位数 16.01，范围 [5.517, 88.09] ms；AegisKV：中位数 17.44，范围 [5.982, 95.97] ms。相同报价用于整个矩阵；实测 Python 线程时间另图列出。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-controller-service.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-controller-service.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-controller-service.pdf) · [曲线 CSV](../../../output/pdf/three-system-20260908/f0-natural-controller-service.csv) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-controller-service](../../../output/pdf/three-system-20260908/f0-natural-controller-service.png)

**f0-natural-controller-service-difference** — 逐 workflow 冻结 CPU 模型服务量（查询＋准入），用于可重复的控制面代价比较

审查记录：冻结 CPU 服务模型的工作量：Mooncake：中位数 0，范围 [0, 0] ms；DRAM-only AegisKV：中位数 8.004，范围 [2.615, 44.33] ms；AegisKV：中位数 9.426，范围 [3.08, 52.2] ms。相同报价用于整个矩阵；实测 Python 线程时间另图列出。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-controller-service-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-controller-service-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-controller-service-difference.pdf) · [曲线 CSV](../../../output/pdf/three-system-20260908/f0-natural-controller-service-difference.csv) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-controller-service-difference](../../../output/pdf/three-system-20260908/f0-natural-controller-service-difference.png)

**f0-natural-cpu** — 逐 workflow Python 准入参考实现实测线程 CPU 时间

审查记录：160 个配对 Workflow：Mooncake：中位数 11.35，范围 [2.089, 81.28] ms；DRAM-only AegisKV：中位数 22.98，范围 [3.365, 109.3] ms；AegisKV：中位数 19.04，范围 [2.944, 104.6] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cpu.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cpu.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cpu.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cpu](../../../output/pdf/three-system-20260908/f0-natural-cpu.png)

**f0-natural-cpu-cdf** — 准入调用 CPU 时间分布，仅 Python 参考实现

审查记录：Mooncake：n=23025，中位数/P95=42.74/175.1 µs；DRAM-only AegisKV：n=23025，中位数/P95=26.6/1210 µs；AegisKV：n=46037，中位数/P95=11.86/453.7 µs。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cpu-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cpu-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cpu-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cpu-cdf](../../../output/pdf/three-system-20260908/f0-natural-cpu-cdf.png)

**f0-natural-cpu-difference** — Admission CPU difference from Mooncake (ms)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] ms；DRAM-only AegisKV：中位数 10.52，范围 [-18.08, 77] ms；AegisKV：中位数 6.083，范围 [-28.9, 75.88] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cpu-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cpu-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cpu-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cpu-difference](../../../output/pdf/three-system-20260908/f0-natural-cpu-difference.png)

**f0-natural-cpu-queue** — 逐 workflow 模型前台 CPU 排队时间总和

审查记录：160 个配对 Workflow：Mooncake：中位数 1.354，范围 [0.4221, 15.43] ms；DRAM-only AegisKV：中位数 2.123，范围 [0.5496, 15.87] ms；AegisKV：中位数 2.19，范围 [0.5723, 15.95] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-cpu-queue.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-cpu-queue.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-cpu-queue.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-cpu-queue](../../../output/pdf/three-system-20260908/f0-natural-cpu-queue.png)

**f0-natural-dram-copy** — 逐 workflow DRAM 写入实际字节，独立于 Peer 后台复制

审查记录：160 个配对 Workflow：Mooncake：中位数 19.62，范围 [1.846, 101.5] GiB；DRAM-only AegisKV：中位数 17.74，范围 [0.2812, 75.99] GiB；AegisKV：中位数 14.31，范围 [0.03516, 74.94] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-dram-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-dram-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-dram-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-dram-copy](../../../output/pdf/three-system-20260908/f0-natural-dram-copy.png)

**f0-natural-dram-hit** — DRAM 对正常 prompt 复用的贡献

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] %；DRAM-only AegisKV：中位数 0，范围 [0, 0] %；AegisKV：中位数 0，范围 [0, 0] %。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-dram-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-dram-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-dram-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-dram-hit](../../../output/pdf/three-system-20260908/f0-natural-dram-hit.png)

**f0-natural-dram-hit-difference** — DRAM-hit difference from Mooncake (pp)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] pp；DRAM-only AegisKV：中位数 0，范围 [0, 0] pp；AegisKV：中位数 0，范围 [0, 0] pp。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-dram-hit-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-dram-hit-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-dram-hit-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-dram-hit-difference](../../../output/pdf/three-system-20260908/f0-natural-dram-hit-difference.png)

**f0-natural-dram_put_gbs** — DRAM cache write traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=14.12 GB/s；DRAM-only AegisKV=15.11 GB/s；AegisKV=12.62 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-dram_put_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-dram_put_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-dram_put_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-dram_put_gbs](../../../output/pdf/three-system-20260908/f0-natural-dram_put_gbs.png)

**f0-natural-foreground-copy** — 逐 workflow 正常 DRAM GET 实际传输字节

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 0，范围 [0, 0] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-foreground-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-foreground-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-foreground-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-foreground-copy](../../../output/pdf/three-system-20260908/f0-natural-foreground-copy.png)

**f0-natural-foreground_gbs** — Foreground DRAM GET traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=0 GB/s；DRAM-only AegisKV=0 GB/s；AegisKV=0 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-foreground_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-foreground_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-foreground_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-foreground_gbs](../../../output/pdf/three-system-20260908/f0-natural-foreground_gbs.png)

**f0-natural-foreground_hbm_wait-cdf** — Foreground HBM reservation wait (s)；请求为样本

审查记录：Mooncake：n=1304，中位数/P95=0/0 s；DRAM-only AegisKV：n=1304，中位数/P95=0/0 s；AegisKV：n=1304，中位数/P95=0/0 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-foreground_hbm_wait-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-foreground_hbm_wait-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-foreground_hbm_wait-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-foreground_hbm_wait-cdf](../../../output/pdf/three-system-20260908/f0-natural-foreground_hbm_wait-cdf.png)

**f0-natural-gpu-0-free_gib** — gpu-0 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2963，范围 [0.01777, 21.75] GiB；DRAM-only AegisKV：中位数 0.2963，范围 [0.01777, 21.75] GiB；AegisKV：中位数 0.4969，范围 [0.01505, 21.75] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-0-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-free_gib.png)

**f0-natural-gpu-0-peer_gib** — gpu-0 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.703，范围 [0.002099, 6.228] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-0-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-0-peer_gib.png)

**f0-natural-gpu-1-free_gib** — gpu-1 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2499，范围 [0.006262, 21.75] GiB；DRAM-only AegisKV：中位数 0.2495，范围 [0.006262, 21.75] GiB；AegisKV：中位数 0.4968，范围 [0.01035, 21.65] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-1-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-free_gib.png)

**f0-natural-gpu-1-peer_gib** — gpu-1 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.718，范围 [0.1029, 6.317] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-1-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-1-peer_gib.png)

**f0-natural-gpu-2-free_gib** — gpu-2 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2963，范围 [0.02384, 21.84] GiB；DRAM-only AegisKV：中位数 0.2963，范围 [0.02384, 21.84] GiB；AegisKV：中位数 0.4967，范围 [0.01296, 21.84] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-2-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-free_gib.png)

**f0-natural-gpu-2-peer_gib** — gpu-2 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.704，范围 [0, 6.208] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-2-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-2-peer_gib.png)

**f0-natural-gpu-3-free_gib** — gpu-3 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2434，范围 [0.006262, 21.75] GiB；DRAM-only AegisKV：中位数 0.2434，范围 [0.006262, 21.75] GiB；AegisKV：中位数 0.4033，范围 [0.006262, 21.65] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-3-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-free_gib.png)

**f0-natural-gpu-3-peer_gib** — gpu-3 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.695，范围 [0.1048, 6.213] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-3-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-3-peer_gib.png)

**f0-natural-gpu-4-free_gib** — gpu-4 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2906，范围 [0.006262, 21.81] GiB；DRAM-only AegisKV：中位数 0.2905，范围 [0.006262, 21.81] GiB；AegisKV：中位数 0.512，范围 [0.01505, 21.81] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-4-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-free_gib.png)

**f0-natural-gpu-4-peer_gib** — gpu-4 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.689，范围 [0, 6.18] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-4-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-4-peer_gib.png)

**f0-natural-gpu-5-free_gib** — gpu-5 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2611，范围 [0.01505, 21.75] GiB；DRAM-only AegisKV：中位数 0.2611，范围 [0.01505, 21.75] GiB；AegisKV：中位数 0.4451，范围 [0.006262, 21.75] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-5-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-free_gib.png)

**f0-natural-gpu-5-peer_gib** — gpu-5 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.718，范围 [0, 6.337] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-5-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-5-peer_gib.png)

**f0-natural-gpu-6-free_gib** — gpu-6 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2546，范围 [0.006262, 21.76] GiB；DRAM-only AegisKV：中位数 0.2546，范围 [0.006262, 21.76] GiB；AegisKV：中位数 0.5357，范围 [0.006262, 21.54] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-6-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-free_gib.png)

**f0-natural-gpu-6-peer_gib** — gpu-6 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.76，范围 [0.2188, 6.171] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-6-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-6-peer_gib.png)

**f0-natural-gpu-7-free_gib** — gpu-7 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.2963，范围 [0.0222, 21.75] GiB；DRAM-only AegisKV：中位数 0.2967，范围 [0.02221, 21.75] GiB；AegisKV：中位数 0.4972，范围 [0.006262, 21.65] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-7-free_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-free_gib.png)

**f0-natural-gpu-7-peer_gib** — gpu-7 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.724，范围 [0.1021, 6.245] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-gpu-7-peer_gib](../../../output/pdf/three-system-20260908/f0-natural-gpu-7-peer_gib.png)

**f0-natural-hbm-pressure** — 逐 GPU 精确积分的低空闲显存时间比例

审查记录：八个 GPU 的低 FREE 时间占比：Mooncake：中位数 95.8，范围 [93.64, 96.29] %；DRAM-only AegisKV：中位数 95.8，范围 [93.64, 96.29] %；AegisKV：中位数 81.66，范围 [78.05, 86.42] %。需结合分配等待与抢占解释。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-hbm-pressure.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-hbm-pressure.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-hbm-pressure.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-hbm-pressure](../../../output/pdf/three-system-20260908/f0-natural-hbm-pressure.png)

**f0-natural-hbm-wait** — 逐 workflow 为 DRAM GET 目标申请 HBM 的等待时间

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0，范围 [0, 0] s；AegisKV：中位数 0，范围 [0, 0] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-hbm-wait](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait.png)

**f0-natural-hbm-wait-difference** — HBM wait difference from Mooncake (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0，范围 [0, 0] s；AegisKV：中位数 0，范围 [0, 0] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-hbm-wait-difference](../../../output/pdf/three-system-20260908/f0-natural-hbm-wait-difference.png)

**f0-natural-peer-copy** — 逐 workflow Peer HBM 后台复制实际字节；Mooncake/DRAM-only 没有这项流量

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 14.38，范围 [0.9492, 62.08] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-peer-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-peer-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-peer-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-peer-copy](../../../output/pdf/three-system-20260908/f0-natural-peer-copy.png)

**f0-natural-peer_put_gbs** — Peer backup copy traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=0 GB/s；DRAM-only AegisKV=0 GB/s；AegisKV=14.37 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-peer_put_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-peer_put_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-peer_put_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-peer_put_gbs](../../../output/pdf/three-system-20260908/f0-natural-peer_put_gbs.png)

**f0-natural-precompute_wait-cdf** — Precompute wait (s)；请求为样本

审查记录：Mooncake：n=1304，中位数/P95=3.313/15.16 s；DRAM-only AegisKV：n=1304，中位数/P95=3.313/15.16 s；AegisKV：n=1304，中位数/P95=3.313/15.16 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-precompute_wait-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-precompute_wait-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-precompute_wait-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-precompute_wait-cdf](../../../output/pdf/three-system-20260908/f0-natural-precompute_wait-cdf.png)

**f0-natural-preemptions** — 逐 workflow 因 KV 压力发生的抢占次数

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 2] 次；DRAM-only AegisKV：中位数 0，范围 [0, 2] 次；AegisKV：中位数 0，范围 [0, 2] 次。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-preemptions.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-preemptions.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-preemptions.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-preemptions](../../../output/pdf/three-system-20260908/f0-natural-preemptions.png)

**f0-natural-protection_gbs** — Background transfer traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=14.12 GB/s；DRAM-only AegisKV=15.11 GB/s；AegisKV=22.33 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-protection_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-protection_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-protection_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-protection_gbs](../../../output/pdf/three-system-20260908/f0-natural-protection_gbs.png)

**f0-natural-request-hit** — 正常请求至少命中一个前缀的比例

审查记录：160 个配对 Workflow：Mooncake：中位数 100，范围 [16.67, 100] %；DRAM-only AegisKV：中位数 100，范围 [16.67, 100] %；AegisKV：中位数 100，范围 [16.67, 100] %。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-request-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-request-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-request-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-request-hit](../../../output/pdf/three-system-20260908/f0-natural-request-hit.png)

**f0-natural-request_tpot-cdf** — Per-request mean time per output token (ms)；请求为样本

审查记录：Mooncake：n=1216，中位数/P95=393.2/417.4 ms；DRAM-only AegisKV：n=1216，中位数/P95=393.2/417.4 ms；AegisKV：n=1216，中位数/P95=393.2/417.4 ms。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-request_tpot-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-request_tpot-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-request_tpot-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-request_tpot-cdf](../../../output/pdf/three-system-20260908/f0-natural-request_tpot-cdf.png)

**f0-natural-scheduler-queue** — 逐 workflow 的纯 GPU 调度等待，起点为 KV 就绪后的调度准入

审查记录：160 个配对 Workflow：Mooncake：中位数 4.834，范围 [0.601, 14.59] s；DRAM-only AegisKV：中位数 4.834，范围 [0.6012, 14.59] s；AegisKV：中位数 4.834，范围 [0.6013, 14.59] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-scheduler-queue](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue.png)

**f0-natural-scheduler-queue-difference** — GPU queue difference from Mooncake (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 -3.645e-05，范围 [-0.0003098, 0.0003827] s；AegisKV：中位数 -4.292e-05，范围 [-0.0003648, 0.0004507] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-scheduler-queue-difference](../../../output/pdf/three-system-20260908/f0-natural-scheduler-queue-difference.png)

**f0-natural-scheduler_queue-cdf** — GPU scheduler queue delay (s)；请求为样本

审查记录：Mooncake：n=1304，中位数/P95=3.313/15.16 s；DRAM-only AegisKV：n=1304，中位数/P95=3.313/15.16 s；AegisKV：n=1304，中位数/P95=3.313/15.16 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-scheduler_queue-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-scheduler_queue-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-scheduler_queue-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-scheduler_queue-cdf](../../../output/pdf/three-system-20260908/f0-natural-scheduler_queue-cdf.png)

**f0-natural-total_gbs** — Shared PCIe traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=14.12 GB/s；DRAM-only AegisKV=15.11 GB/s；AegisKV=22.33 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-total_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-total_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-total_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-total_gbs](../../../output/pdf/three-system-20260908/f0-natural-total_gbs.png)

**f0-natural-ttft-cdf** — Time to first token (s)；请求为样本

审查记录：Mooncake：n=1304，中位数/P95=5.791/18.37 s；DRAM-only AegisKV：n=1304，中位数/P95=5.791/18.37 s；AegisKV：n=1304，中位数/P95=5.791/18.37 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-ttft-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-ttft-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-ttft-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-ttft-cdf](../../../output/pdf/three-system-20260908/f0-natural-ttft-cdf.png)

**f0-natural-wait** — 逐 workflow 请求平均首次计算前等待，包含 GET 和 CPU 排队

审查记录：160 个配对 Workflow：Mooncake：中位数 4.834，范围 [0.6012, 14.59] s；DRAM-only AegisKV：中位数 4.834，范围 [0.6015, 14.59] s；AegisKV：中位数 4.834，范围 [0.6015, 14.59] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-wait.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-wait.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-wait.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-wait](../../../output/pdf/three-system-20260908/f0-natural-wait.png)

**f0-natural-wct** — 逐 workflow 的 WCT

审查记录：160 个配对 Workflow：Mooncake：中位数 35.7，范围 [4.982, 131.2] s；DRAM-only AegisKV：中位数 35.7，范围 [4.982, 131.2] s；AegisKV：中位数 35.7，范围 [4.982, 131.2] s。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-wct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-wct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-wct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-wct](../../../output/pdf/three-system-20260908/f0-natural-wct.png)

**f0-natural-wct-difference** — WCT difference from Mooncake (ms)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] ms；DRAM-only AegisKV：中位数 0.1913，范围 [-0.4465, 1.02] ms；AegisKV：中位数 0.2253，范围 [-0.5258, 1.202] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-natural-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-natural-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-natural-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-natural-figure-manifest.json)

![f0-natural-wct-difference](../../../output/pdf/three-system-20260908/f0-natural-wct-difference.png)

</details>

<a id="three-system-f0-revisit"></a>
### f0-revisit

配置：160 workflows / 2608 requests；C=16；revisit rounds=2；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details open>
<summary>展开 55 张独立图及绘制说明</summary>

**f0-revisit-background-copy** — 逐 workflow 后台 DRAM/Peer 复制实际消耗字节，包含中止前已经传输的字节

审查记录：160 个配对 Workflow：Mooncake：中位数 19.62，范围 [1.846, 101.5] GiB；DRAM-only AegisKV：中位数 24.39，范围 [0.5186, 110.5] GiB；AegisKV：中位数 49.61，范围 [4.043, 225.9] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-background-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-background-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-background-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-background-copy](../../../output/pdf/three-system-20260908/f0-revisit-background-copy.png)

**f0-revisit-background-copy-difference** — Background copy difference from Mooncake (GiB)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 4.192，范围 [-16.7, 33.57] GiB；AegisKV：中位数 28.43，范围 [1.204, 124.4] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-background-copy-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-background-copy-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-background-copy-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-background-copy-difference](../../../output/pdf/three-system-20260908/f0-revisit-background-copy-difference.png)

**f0-revisit-cache-hit** — 正常服务的 token 加权 KV 命中率

审查记录：160 个配对 Workflow：Mooncake：中位数 50.13，范围 [12.8, 51.3] %；DRAM-only AegisKV：中位数 27.63，范围 [0.3516, 47.39] %；AegisKV：中位数 19.31，范围 [0.5277, 49.13] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cache-hit](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit.png)

**f0-revisit-cache-hit-difference** — Cache-hit difference from Mooncake (pp)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] pp；DRAM-only AegisKV：中位数 -21.51，范围 [-49.79, -3.218] pp；AegisKV：中位数 -29.95，范围 [-49.67, -1.042] pp。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cache-hit-difference](../../../output/pdf/three-system-20260908/f0-revisit-cache-hit-difference.png)

**f0-revisit-controller-service** — 逐 workflow 冻结 CPU 模型服务量（查询＋准入），用于可重复的控制面代价比较

审查记录：冻结 CPU 服务模型的工作量：Mooncake：中位数 13.59，范围 [5.133, 80.76] ms；DRAM-only AegisKV：中位数 29.64，范围 [10.41, 169.8] ms；AegisKV：中位数 32.47，范围 [11.69, 189.6] ms。相同报价用于整个矩阵；实测 Python 线程时间另图列出。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-controller-service.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-controller-service.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-controller-service.pdf) · [曲线 CSV](../../../output/pdf/three-system-20260908/f0-revisit-controller-service.csv) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-controller-service](../../../output/pdf/three-system-20260908/f0-revisit-controller-service.png)

**f0-revisit-controller-service-difference** — 逐 workflow 冻结 CPU 模型服务量（查询＋准入），用于可重复的控制面代价比较

审查记录：冻结 CPU 服务模型的工作量：Mooncake：中位数 0，范围 [0, 0] ms；DRAM-only AegisKV：中位数 15.72，范围 [5.277, 89.06] ms；AegisKV：中位数 18.67，范围 [6.558, 108.9] ms。相同报价用于整个矩阵；实测 Python 线程时间另图列出。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-controller-service-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-controller-service-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-controller-service-difference.pdf) · [曲线 CSV](../../../output/pdf/three-system-20260908/f0-revisit-controller-service-difference.csv) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-controller-service-difference](../../../output/pdf/three-system-20260908/f0-revisit-controller-service-difference.png)

**f0-revisit-cpu** — 逐 workflow Python 准入参考实现实测线程 CPU 时间

审查记录：160 个配对 Workflow：Mooncake：中位数 14.12，范围 [3.114, 96.38] ms；DRAM-only AegisKV：中位数 34.18，范围 [4.638, 180.8] ms；AegisKV：中位数 43.47，范围 [9.023, 210.6] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cpu.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cpu.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cpu.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cpu](../../../output/pdf/three-system-20260908/f0-revisit-cpu.png)

**f0-revisit-cpu-cdf** — 准入调用 CPU 时间分布，仅 Python 参考实现

审查记录：Mooncake：n=40160，中位数/P95=35.88/124.9 µs；DRAM-only AegisKV：n=42562，中位数/P95=21.18/1035 µs；AegisKV：n=86992，中位数/P95=15.99/495.9 µs。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cpu-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cpu-cdf](../../../output/pdf/three-system-20260908/f0-revisit-cpu-cdf.png)

**f0-revisit-cpu-difference** — Admission CPU difference from Mooncake (ms)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] ms；DRAM-only AegisKV：中位数 16.95，范围 [-14.27, 95.23] ms；AegisKV：中位数 24.37，范围 [-23.85, 118.7] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cpu-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cpu-difference](../../../output/pdf/three-system-20260908/f0-revisit-cpu-difference.png)

**f0-revisit-cpu-queue** — 逐 workflow 模型前台 CPU 排队时间总和

审查记录：160 个配对 Workflow：Mooncake：中位数 2.77，范围 [0.7831, 30.24] ms；DRAM-only AegisKV：中位数 4.421，范围 [1.149, 37.72] ms；AegisKV：中位数 4.819，范围 [1.272, 36.93] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-queue.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-cpu-queue.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-cpu-queue.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-cpu-queue](../../../output/pdf/three-system-20260908/f0-revisit-cpu-queue.png)

**f0-revisit-dram-copy** — 逐 workflow DRAM 写入实际字节，独立于 Peer 后台复制

审查记录：160 个配对 Workflow：Mooncake：中位数 19.62，范围 [1.846, 101.5] GiB；DRAM-only AegisKV：中位数 24.39，范围 [0.5186, 110.5] GiB；AegisKV：中位数 22.55，范围 [0.2637, 99.02] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-dram-copy](../../../output/pdf/three-system-20260908/f0-revisit-dram-copy.png)

**f0-revisit-dram-hit** — DRAM 对正常 prompt 复用的贡献

审查记录：160 个配对 Workflow：Mooncake：中位数 49.73，范围 [12.56, 49.92] %；DRAM-only AegisKV：中位数 26.25，范围 [0.06063, 46.48] %；AegisKV：中位数 18.64，范围 [0.09839, 48.77] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-dram-hit](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit.png)

**f0-revisit-dram-hit-difference** — DRAM-hit difference from Mooncake (pp)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] pp；DRAM-only AegisKV：中位数 -21.45，范围 [-49.79, 10.97] pp；AegisKV：中位数 -29.78，范围 [-49.67, -1.042] pp。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-dram-hit-difference](../../../output/pdf/three-system-20260908/f0-revisit-dram-hit-difference.png)

**f0-revisit-dram_put_gbs** — DRAM cache write traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=14.18 GB/s；DRAM-only AegisKV=14.6 GB/s；AegisKV=13.89 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram_put_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram_put_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram_put_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-dram_put_gbs](../../../output/pdf/three-system-20260908/f0-revisit-dram_put_gbs.png)

**f0-revisit-foreground-copy** — 逐 workflow 正常 DRAM GET 实际传输字节

审查记录：160 个配对 Workflow：Mooncake：中位数 19.16，范围 [1.828, 101.5] GiB；DRAM-only AegisKV：中位数 9.215，范围 [0.02637, 57.68] GiB；AegisKV：中位数 6.943，范围 [0.02637, 45.61] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-foreground-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-foreground-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-foreground-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-foreground-copy](../../../output/pdf/three-system-20260908/f0-revisit-foreground-copy.png)

**f0-revisit-foreground_gbs** — Foreground DRAM GET traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=25 GB/s；DRAM-only AegisKV=23.6 GB/s；AegisKV=19.31 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-foreground_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-foreground_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-foreground_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-foreground_gbs](../../../output/pdf/three-system-20260908/f0-revisit-foreground_gbs.png)

**f0-revisit-foreground_hbm_wait-cdf** — Foreground HBM reservation wait (s)；请求为样本

审查记录：Mooncake：n=2608，中位数/P95=0/0.01758 s；DRAM-only AegisKV：n=2608，中位数/P95=0/0 s；AegisKV：n=2608，中位数/P95=0/0 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-foreground_hbm_wait-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-foreground_hbm_wait-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-foreground_hbm_wait-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-foreground_hbm_wait-cdf](../../../output/pdf/three-system-20260908/f0-revisit-foreground_hbm_wait-cdf.png)

**f0-revisit-get-latency** — 每个 workflow 内成功 GET 的 P95 延迟，无 GET 的位置留空

审查记录：160 个配对 Workflow：Mooncake：中位数 1636，范围 [78.46, 8589] ms；DRAM-only AegisKV：中位数 481.3，范围 [1.969, 2561] ms；AegisKV：中位数 549.3，范围 [3.647, 2720] ms。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-get-latency.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-get-latency.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-get-latency.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-get-latency](../../../output/pdf/three-system-20260908/f0-revisit-get-latency.png)

**f0-revisit-get-slowdown** — 每个 workflow 内成功 GET 的 P95 数据服务减速比，无样本留空

审查记录：160 个配对 Workflow：Mooncake：中位数 14.07，范围 [3.968, 50.3] ×；DRAM-only AegisKV：中位数 4.733，范围 [1.224, 19.75] ×；AegisKV：中位数 5.908，范围 [1.992, 18.33] ×。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-get-slowdown.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-get-slowdown.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-get-slowdown.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-get-slowdown](../../../output/pdf/three-system-20260908/f0-revisit-get-slowdown.png)

**f0-revisit-gpu-0-free_gib** — gpu-0 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.4299，范围 [0.006262, 21.81] GiB；DRAM-only AegisKV：中位数 0.3234，范围 [0.006262, 21.81] GiB；AegisKV：中位数 0.5498，范围 [0.01164, 21.72] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-0-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-free_gib.png)

**f0-revisit-gpu-0-peer_gib** — gpu-0 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.732，范围 [0, 6.576] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-0-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-0-peer_gib.png)

**f0-revisit-gpu-1-free_gib** — gpu-1 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.4236，范围 [0.006262, 21.84] GiB；DRAM-only AegisKV：中位数 0.3051，范围 [0.006262, 21.84] GiB；AegisKV：中位数 0.4988，范围 [0.006262, 21.84] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-1-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-free_gib.png)

**f0-revisit-gpu-1-peer_gib** — gpu-1 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.693，范围 [0, 7.031] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-1-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-1-peer_gib.png)

**f0-revisit-gpu-2-free_gib** — gpu-2 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.4146，范围 [0.006262, 22.74] GiB；DRAM-only AegisKV：中位数 0.3139，范围 [0.006262, 22.74] GiB；AegisKV：中位数 0.5323，范围 [0.006262, 22.74] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-2-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-free_gib.png)

**f0-revisit-gpu-2-peer_gib** — gpu-2 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.706，范围 [0, 6.769] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-2-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-2-peer_gib.png)

**f0-revisit-gpu-3-free_gib** — gpu-3 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.4173，范围 [0.009456, 21.75] GiB；DRAM-only AegisKV：中位数 0.349，范围 [0.006262, 21.75] GiB；AegisKV：中位数 0.53，范围 [0.006729, 21.75] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-3-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-free_gib.png)

**f0-revisit-gpu-3-peer_gib** — gpu-3 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.704，范围 [0, 6.596] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-3-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-3-peer_gib.png)

**f0-revisit-gpu-4-free_gib** — gpu-4 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.3927，范围 [0.006262, 21.76] GiB；DRAM-only AegisKV：中位数 0.3335，范围 [0.01226, 21.76] GiB；AegisKV：中位数 0.5597，范围 [0.008333, 21.69] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-4-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-free_gib.png)

**f0-revisit-gpu-4-peer_gib** — gpu-4 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.7，范围 [0, 6.686] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-4-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-4-peer_gib.png)

**f0-revisit-gpu-5-free_gib** — gpu-5 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.3578，范围 [0.006262, 21.75] GiB；DRAM-only AegisKV：中位数 0.3051，范围 [0.006262, 21.75] GiB；AegisKV：中位数 0.4949，范围 [0.006262, 21.65] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-5-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-free_gib.png)

**f0-revisit-gpu-5-peer_gib** — gpu-5 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.694，范围 [0, 6.685] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-5-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-5-peer_gib.png)

**f0-revisit-gpu-6-free_gib** — gpu-6 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.3666，范围 [0.01194, 21.78] GiB；DRAM-only AegisKV：中位数 0.3093，范围 [0.006262, 21.78] GiB；AegisKV：中位数 0.4996，范围 [0.006262, 21.68] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-6-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-free_gib.png)

**f0-revisit-gpu-6-peer_gib** — gpu-6 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.687，范围 [0, 6.657] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-6-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-6-peer_gib.png)

**f0-revisit-gpu-7-free_gib** — gpu-7 Free HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0.3607，范围 [0.006262, 21.75] GiB；DRAM-only AegisKV：中位数 0.3312，范围 [0.006262, 21.75] GiB；AegisKV：中位数 0.4981，范围 [0.01222, 21.65] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-free_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-free_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-free_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-7-free_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-free_gib.png)

**f0-revisit-gpu-7-peer_gib** — gpu-7 Peer protection HBM (GiB)；按时间加权的 1 s 均值

审查记录：1 s 窗口均值：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 5.687，范围 [0, 6.697] GiB。窗口数由各系统的实际完成时长决定。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-peer_gib.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-peer_gib.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-peer_gib.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-gpu-7-peer_gib](../../../output/pdf/three-system-20260908/f0-revisit-gpu-7-peer_gib.png)

**f0-revisit-hbm-pressure** — 逐 GPU 精确积分的低空闲显存时间比例

审查记录：八个 GPU 的低 FREE 时间占比：Mooncake：中位数 87.78，范围 [83.08, 89.38] %；DRAM-only AegisKV：中位数 95.77，范围 [93.22, 96.31] %；AegisKV：中位数 78.74，范围 [71.26, 82.62] %。需结合分配等待与抢占解释。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-pressure.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-pressure.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-hbm-pressure.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-hbm-pressure](../../../output/pdf/three-system-20260908/f0-revisit-hbm-pressure.png)

**f0-revisit-hbm-wait** — 逐 workflow 为 DRAM GET 目标申请 HBM 的等待时间

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 4.076] s；DRAM-only AegisKV：中位数 0，范围 [0, 1.046] s；AegisKV：中位数 0，范围 [0, 0.06886] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-hbm-wait](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait.png)

**f0-revisit-hbm-wait-difference** — HBM wait difference from Mooncake (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0，范围 [-4.076, 0.6255] s；AegisKV：中位数 0，范围 [-4.076, 0.05601] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-hbm-wait-difference](../../../output/pdf/three-system-20260908/f0-revisit-hbm-wait-difference.png)

**f0-revisit-peer-copy** — 逐 workflow Peer HBM 后台复制实际字节；Mooncake/DRAM-only 没有这项流量

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] GiB；DRAM-only AegisKV：中位数 0，范围 [0, 0] GiB；AegisKV：中位数 26.05，范围 [2.927, 126.9] GiB。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-peer-copy.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-peer-copy.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-peer-copy.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-peer-copy](../../../output/pdf/three-system-20260908/f0-revisit-peer-copy.png)

**f0-revisit-peer_put_gbs** — Peer backup copy traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=0 GB/s；DRAM-only AegisKV=0 GB/s；AegisKV=19.53 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-peer_put_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-peer_put_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-peer_put_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-peer_put_gbs](../../../output/pdf/three-system-20260908/f0-revisit-peer_put_gbs.png)

**f0-revisit-precompute_wait-cdf** — Precompute wait (s)；请求为样本

审查记录：Mooncake：n=2608，中位数/P95=1.885/10.42 s；DRAM-only AegisKV：n=2608，中位数/P95=1.649/13.15 s；AegisKV：n=2608，中位数/P95=2.064/16.72 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-precompute_wait-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-precompute_wait-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-precompute_wait-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-precompute_wait-cdf](../../../output/pdf/three-system-20260908/f0-revisit-precompute_wait-cdf.png)

**f0-revisit-preemptions** — 逐 workflow 因 KV 压力发生的抢占次数

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 6] 次；DRAM-only AegisKV：中位数 0，范围 [0, 3] 次；AegisKV：中位数 0，范围 [0, 1] 次。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-preemptions.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-preemptions.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-preemptions.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-preemptions](../../../output/pdf/three-system-20260908/f0-revisit-preemptions.png)

**f0-revisit-protection_gbs** — Background transfer traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=14.18 GB/s；DRAM-only AegisKV=14.6 GB/s；AegisKV=24.73 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-protection_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-protection_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-protection_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-protection_gbs](../../../output/pdf/three-system-20260908/f0-revisit-protection_gbs.png)

**f0-revisit-request-hit** — 正常请求至少命中一个前缀的比例

审查记录：160 个配对 Workflow：Mooncake：中位数 100，范围 [58.33, 100] %；DRAM-only AegisKV：中位数 100，范围 [58.33, 100] %；AegisKV：中位数 100，范围 [58.33, 100] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-request-hit.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-request-hit.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-request-hit.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-request-hit](../../../output/pdf/three-system-20260908/f0-revisit-request-hit.png)

**f0-revisit-request_tpot-cdf** — Per-request mean time per output token (ms)；请求为样本

审查记录：Mooncake：n=2432，中位数/P95=120.1/418.5 ms；DRAM-only AegisKV：n=2432，中位数/P95=308.1/414.8 ms；AegisKV：n=2432，中位数/P95=364.3/416 ms。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-request_tpot-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-request_tpot-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-request_tpot-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-request_tpot-cdf](../../../output/pdf/three-system-20260908/f0-revisit-request_tpot-cdf.png)

**f0-revisit-scheduler-queue** — 逐 workflow 的纯 GPU 调度等待，起点为 KV 就绪后的调度准入

审查记录：160 个配对 Workflow：Mooncake：中位数 2.015，范围 [0.2788, 8.022] s；DRAM-only AegisKV：中位数 3.048，范围 [0.3145, 8.119] s；AegisKV：中位数 3.821，范围 [0.6178, 8.702] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-scheduler-queue](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue.png)

**f0-revisit-scheduler-queue-difference** — GPU queue difference from Mooncake (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0.9207，范围 [-5.189, 4.763] s；AegisKV：中位数 1.647，范围 [-2.235, 6.479] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-scheduler-queue-difference](../../../output/pdf/three-system-20260908/f0-revisit-scheduler-queue-difference.png)

**f0-revisit-scheduler_queue-cdf** — GPU scheduler queue delay (s)；请求为样本

审查记录：Mooncake：n=2608，中位数/P95=0.705/9.483 s；DRAM-only AegisKV：n=2608，中位数/P95=1.283/13.15 s；AegisKV：n=2608，中位数/P95=1.777/16.72 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler_queue-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-scheduler_queue-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-scheduler_queue-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-scheduler_queue-cdf](../../../output/pdf/three-system-20260908/f0-revisit-scheduler_queue-cdf.png)

**f0-revisit-total_gbs** — Shared PCIe traffic (GB/s)；1 s 时间窗

审查记录：1 s 窗内最大速率：Mooncake=25 GB/s；DRAM-only AegisKV=25 GB/s；AegisKV=25 GB/s。前台 GET 争用另由 GET slowdown 图量化。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-total_gbs.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-total_gbs.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-total_gbs.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-total_gbs](../../../output/pdf/three-system-20260908/f0-revisit-total_gbs.png)

**f0-revisit-transfer-duration_ms** — Foreground DRAM GET latency (ms)

审查记录：成功 GET：Mooncake：n=1284，中位数/P95=662.2/4365 ms；DRAM-only AegisKV：n=773，中位数/P95=298.9/1667 ms；AegisKV：n=662，中位数/P95=310.9/1639 ms。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-transfer-duration_ms.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-transfer-duration_ms.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-transfer-duration_ms.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-transfer-duration_ms](../../../output/pdf/three-system-20260908/f0-revisit-transfer-duration_ms.png)

**f0-revisit-transfer-service_slowdown** — Foreground GET service slowdown (×)

审查记录：成功 GET：Mooncake：n=1284，中位数/P95=8.326/33.56 ×；DRAM-only AegisKV：n=773，中位数/P95=3.204/10.71 ×；AegisKV：n=662，中位数/P95=4.71/12.65 ×。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-transfer-service_slowdown.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-transfer-service_slowdown.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-transfer-service_slowdown.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-transfer-service_slowdown](../../../output/pdf/three-system-20260908/f0-revisit-transfer-service_slowdown.png)

**f0-revisit-ttft-cdf** — Time to first token (s)；请求为样本

审查记录：Mooncake：n=2608，中位数/P95=3.173/13.3 s；DRAM-only AegisKV：n=2608，中位数/P95=3.517/15.9 s；AegisKV：n=2608，中位数/P95=4.092/18.98 s。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-ttft-cdf.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-ttft-cdf.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-ttft-cdf.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-ttft-cdf](../../../output/pdf/three-system-20260908/f0-revisit-ttft-cdf.png)

**f0-revisit-wait** — 逐 workflow 请求平均首次计算前等待，包含 GET 和 CPU 排队

审查记录：160 个配对 Workflow：Mooncake：中位数 2.714，范围 [0.316, 9.065] s；DRAM-only AegisKV：中位数 3.186，范围 [0.3517, 8.139] s；AegisKV：中位数 3.954，范围 [0.6347, 8.873] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-wait.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-wait.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-wait.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-wait](../../../output/pdf/three-system-20260908/f0-revisit-wait.png)

**f0-revisit-wct** — 逐 workflow 的 WCT

审查记录：160 个配对 Workflow：Mooncake：中位数 48.34，范围 [5.297, 173] s；DRAM-only AegisKV：中位数 59.48，范围 [7.146, 289.5] s；AegisKV：中位数 66.09，范围 [19.39, 186.1] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-wct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-wct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-wct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-wct](../../../output/pdf/three-system-20260908/f0-revisit-wct.png)

**f0-revisit-wct-difference** — WCT difference from Mooncake (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 9.968，范围 [-99.23, 222.9] s；AegisKV：中位数 17.9，范围 [-107.9, 117.3] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-figure-manifest.json)

![f0-revisit-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-wct-difference.png)

</details>

<a id="three-system-f1-natural"></a>
### f1-natural

配置：160 workflows / 1304 requests；C=16；revisit rounds=1；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 9 张独立图及绘制说明</summary>

**f1-natural-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] %；DRAM-only AegisKV：中位数 0，范围 [0, 0] %；AegisKV：中位数 0，范围 [0, 0] %。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-dram_hit_pct](../../../output/pdf/three-system-20260908/f1-natural-dram_hit_pct.png)

**f1-natural-failure-penalty** — 各系统相对自身匹配 F0 的逐 workflow 故障罚时

审查记录：相对各自 F0 的逐 Workflow 变化：Mooncake：中位数 0，范围 [-1.216, 0.02991] s；DRAM-only AegisKV：中位数 0，范围 [-1.216, 0.02991] s；AegisKV：中位数 0，范围 [-1.216, 0.02991] s。负值可能来自闭环调度的变化，原样保留。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-failure-penalty.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-failure-penalty.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-failure-penalty.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-failure-penalty](../../../output/pdf/three-system-20260908/f1-natural-failure-penalty.png)

**f1-natural-fault1-completed_ns** — Failure to request completion (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=8.32061 s；DRAM-only AegisKV=8.32061 s；AegisKV=9.07379 s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-fault1-completed_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-fault1-completed_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-fault1-completed_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-fault1-completed_ns](../../../output/pdf/three-system-20260908/f1-natural-fault1-completed_ns.png)

**f1-natural-fault1-prefix_materialized_ns** — Failure to restored prefix ready (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=0.315319 s；DRAM-only AegisKV=0.315319 s；AegisKV=0.242842 s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-fault1-prefix_materialized_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-fault1-prefix_materialized_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-fault1-prefix_materialized_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-fault1-prefix_materialized_ns](../../../output/pdf/three-system-20260908/f1-natural-fault1-prefix_materialized_ns.png)

**f1-natural-fault1-recovery-tokens** — 匹配逻辑故障请求的恢复来源和重算量；每柱是同一请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。按 local/Peer/DRAM/recompute tokens：Mooncake=64/0/49152/36982；DRAM-only AegisKV=64/0/49152/36982；AegisKV=64/40960/0/45174。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery-tokens.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery-tokens.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery-tokens.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-fault1-recovery-tokens](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery-tokens.png)

**f1-natural-fault1-recovery_ready_ns** — Failure to resumed decoding (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=4.43144 s；DRAM-only AegisKV=4.43144 s；AegisKV=5.18462 s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery_ready_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery_ready_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery_ready_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-fault1-recovery_ready_ns](../../../output/pdf/three-system-20260908/f1-natural-fault1-recovery_ready_ns.png)

**f1-natural-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 4.834，范围 [0.601, 14.59] s；DRAM-only AegisKV：中位数 4.834，范围 [0.6012, 14.59] s；AegisKV：中位数 4.834，范围 [0.6013, 14.59] s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f1-natural-mean_scheduler_queue_s.png)

**f1-natural-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0.0001913，范围 [-0.0004465, 0.00102] s；AegisKV：中位数 0.0002253，范围 [-1.182, 0.001202] s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-wct-difference](../../../output/pdf/three-system-20260908/f1-natural-wct-difference.png)

**f1-natural-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 35.7，范围 [4.982, 131.2] s；DRAM-only AegisKV：中位数 35.7，范围 [4.982, 131.2] s；AegisKV：中位数 35.7，范围 [4.982, 131.2] s。

[PNG](../../../output/pdf/three-system-20260908/f1-natural-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f1-natural-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f1-natural-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f1-natural-figure-manifest.json)

![f1-natural-wct_s](../../../output/pdf/three-system-20260908/f1-natural-wct_s.png)

</details>

<a id="three-system-f2-natural"></a>
### f2-natural

配置：160 workflows / 1304 requests；C=16；revisit rounds=1；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 13 张独立图及绘制说明</summary>

**f2-natural-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] %；DRAM-only AegisKV：中位数 0，范围 [0, 0] %；AegisKV：中位数 0，范围 [0, 0] %。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-dram_hit_pct](../../../output/pdf/three-system-20260908/f2-natural-dram_hit_pct.png)

**f2-natural-failure-penalty** — 各系统相对自身匹配 F0 的逐 workflow 故障罚时

审查记录：相对各自 F0 的逐 Workflow 变化：Mooncake：中位数 0，范围 [-1.216, 0.05507] s；DRAM-only AegisKV：中位数 0，范围 [-1.216, 0.05507] s；AegisKV：中位数 0，范围 [-1.216, 0.05507] s。负值可能来自闭环调度的变化，原样保留。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-failure-penalty.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-failure-penalty.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-failure-penalty.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-failure-penalty](../../../output/pdf/three-system-20260908/f2-natural-failure-penalty.png)

**f2-natural-fault1-completed_ns** — Failure to request completion (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=8.32061 s；DRAM-only AegisKV=8.32061 s；AegisKV=9.07379 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault1-completed_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault1-completed_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault1-completed_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault1-completed_ns](../../../output/pdf/three-system-20260908/f2-natural-fault1-completed_ns.png)

**f2-natural-fault1-prefix_materialized_ns** — Failure to restored prefix ready (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=0.315319 s；DRAM-only AegisKV=0.315319 s；AegisKV=0.242842 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault1-prefix_materialized_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault1-prefix_materialized_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault1-prefix_materialized_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault1-prefix_materialized_ns](../../../output/pdf/three-system-20260908/f2-natural-fault1-prefix_materialized_ns.png)

**f2-natural-fault1-recovery-tokens** — 匹配逻辑故障请求的恢复来源和重算量；每柱是同一请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。按 local/Peer/DRAM/recompute tokens：Mooncake=64/0/49152/36982；DRAM-only AegisKV=64/0/49152/36982；AegisKV=64/40960/0/45174。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery-tokens.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery-tokens.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery-tokens.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault1-recovery-tokens](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery-tokens.png)

**f2-natural-fault1-recovery_ready_ns** — Failure to resumed decoding (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:e50efc1e7ada5740`。故障后间隔：Mooncake=4.43144 s；DRAM-only AegisKV=4.43144 s；AegisKV=5.18462 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery_ready_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery_ready_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery_ready_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault1-recovery_ready_ns](../../../output/pdf/three-system-20260908/f2-natural-fault1-recovery_ready_ns.png)

**f2-natural-fault2-completed_ns** — Failure to request completion (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:final`。故障后间隔：Mooncake=0.242724 s；DRAM-only AegisKV=0.242724 s；AegisKV=0.242724 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault2-completed_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault2-completed_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault2-completed_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault2-completed_ns](../../../output/pdf/three-system-20260908/f2-natural-fault2-completed_ns.png)

**f2-natural-fault2-prefix_materialized_ns** — Failure to restored prefix ready (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:final`。故障后间隔：Mooncake=0.001 s；DRAM-only AegisKV=0.001 s；AegisKV=0.001 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault2-prefix_materialized_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault2-prefix_materialized_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault2-prefix_materialized_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault2-prefix_materialized_ns](../../../output/pdf/three-system-20260908/f2-natural-fault2-prefix_materialized_ns.png)

**f2-natural-fault2-recovery-tokens** — 匹配逻辑故障请求的恢复来源和重算量；每柱是同一请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:final`。按 local/Peer/DRAM/recompute tokens：Mooncake=64/0/0/215；DRAM-only AegisKV=64/0/0/215；AegisKV=64/0/0/215。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery-tokens.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery-tokens.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery-tokens.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault2-recovery-tokens](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery-tokens.png)

**f2-natural-fault2-recovery_ready_ns** — Failure to resumed decoding (s)；同一个逻辑请求

审查记录：配对请求 `fanoutqa:6f9b579bc0a11d6d:final`。故障后间隔：Mooncake=0.0889366 s；DRAM-only AegisKV=0.0889366 s；AegisKV=0.0889366 s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery_ready_ns.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery_ready_ns.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery_ready_ns.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-fault2-recovery_ready_ns](../../../output/pdf/three-system-20260908/f2-natural-fault2-recovery_ready_ns.png)

**f2-natural-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 4.834，范围 [0.601, 14.59] s；DRAM-only AegisKV：中位数 4.834，范围 [0.6012, 14.59] s；AegisKV：中位数 4.834，范围 [0.6013, 14.59] s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f2-natural-mean_scheduler_queue_s.png)

**f2-natural-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0.0001913，范围 [-0.0004465, 0.00102] s；AegisKV：中位数 0.0002253，范围 [-1.182, 0.001202] s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-wct-difference](../../../output/pdf/three-system-20260908/f2-natural-wct-difference.png)

**f2-natural-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 35.7，范围 [4.982, 131.2] s；DRAM-only AegisKV：中位数 35.7，范围 [4.982, 131.2] s；AegisKV：中位数 35.7，范围 [4.982, 131.2] s。

[PNG](../../../output/pdf/three-system-20260908/f2-natural-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f2-natural-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f2-natural-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f2-natural-figure-manifest.json)

![f2-natural-wct_s](../../../output/pdf/three-system-20260908/f2-natural-wct_s.png)

</details>

<a id="three-system-cross-case"></a>
### cross-case

<details>
<summary>展开 18 张独立图及绘制说明</summary>

**ablation-f0-slack** — 零 Slack 消融相对各自系统的逐 workflow WCT 变化；Mooncake 不使用 Slack，恒为零

审查记录：Mooncake 不使用 Slack，变化为零；DRAM-only AegisKV：中位数 0，范围 [0, 0] s；AegisKV：中位数 0，范围 [0, 0] s。

[PNG](../../../output/pdf/three-system-20260908/ablation-f0-slack.png) · [SVG](../../../output/pdf/three-system-20260908/ablation-f0-slack.svg) · [PDF](../../../output/pdf/three-system-20260908/ablation-f0-slack.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![ablation-f0-slack](../../../output/pdf/three-system-20260908/ablation-f0-slack.png)

**ablation-f1-slack** — 零 Slack 消融相对各自系统的逐 workflow WCT 变化；Mooncake 不使用 Slack，恒为零

审查记录：Mooncake 不使用 Slack，变化为零；DRAM-only AegisKV：中位数 0，范围 [0, 0] s；AegisKV：中位数 0，范围 [0, 0] s。

[PNG](../../../output/pdf/three-system-20260908/ablation-f1-slack.png) · [SVG](../../../output/pdf/three-system-20260908/ablation-f1-slack.svg) · [PDF](../../../output/pdf/three-system-20260908/ablation-f1-slack.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![ablation-f1-slack](../../../output/pdf/three-system-20260908/ablation-f1-slack.png)

**ablation-uncertified-guard** — 无 QoS 证书的严格控制器；AegisKV 不发放 Peer 配额

审查记录：严格无证书配置的 AegisKV 在所有 GPU、所有时间窗的 Peer 占用均为零；此图检验控制器的关闭行为，不能作为启用 Peer 后无干扰的证据。

[PNG](../../../output/pdf/three-system-20260908/ablation-uncertified-guard.png) · [SVG](../../../output/pdf/three-system-20260908/ablation-uncertified-guard.svg) · [PDF](../../../output/pdf/three-system-20260908/ablation-uncertified-guard.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![ablation-uncertified-guard](../../../output/pdf/three-system-20260908/ablation-uncertified-guard.png)

**sensitivity-bandwidth-dram_hit_pct** — Prompt tokens served by DRAM (%)；单变量改变 Shared transfer capacity (GB/s)

审查记录：按横轴配置顺序，Mooncake=32.32/48.08/48.42 %；DRAM-only AegisKV=3.59/26.54/35.07 %；AegisKV=0.08696/18.89/30.24 %。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-bandwidth-dram_hit_pct](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-dram_hit_pct.png)

**sensitivity-bandwidth-foreground_transfer_p95_ms** — P95 foreground DRAM GET latency (ms)；单变量改变 Shared transfer capacity (GB/s)

审查记录：按横轴配置顺序，Mooncake=8.506e+04/4365/1909 ms；DRAM-only AegisKV=1498/1667/967.8 ms；AegisKV=828.2/1639/816.5 ms。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-foreground_transfer_p95_ms.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-foreground_transfer_p95_ms.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-foreground_transfer_p95_ms.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-bandwidth-foreground_transfer_p95_ms](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-foreground_transfer_p95_ms.png)

**sensitivity-bandwidth-mean_wct_s** — Mean workflow completion time (s)；单变量改变 Shared transfer capacity (GB/s)

审查记录：按横轴配置顺序，Mooncake=150.5/53.39/48.4 s；DRAM-only AegisKV=81/64.05/55.87 s；AegisKV=82.07/69.74/58.18 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-mean_wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-mean_wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-mean_wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-bandwidth-mean_wct_s](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-mean_wct_s.png)

**sensitivity-bandwidth-p95_scheduler_queue_s** — P95 GPU scheduler queue delay (s)；单变量改变 Shared transfer capacity (GB/s)

审查记录：按横轴配置顺序，Mooncake=6.981/9.483/10.42 s；DRAM-only AegisKV=20.02/13.15/11.82 s；AegisKV=18.29/16.72/14 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-p95_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-p95_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-p95_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-bandwidth-p95_scheduler_queue_s](../../../output/pdf/three-system-20260908/sensitivity-bandwidth-p95_scheduler_queue_s.png)

**sensitivity-concurrency-dram_hit_pct** — Prompt tokens served by DRAM (%)；单变量改变 Active workflow concurrency

审查记录：按横轴配置顺序，Mooncake=47.43/48.08/46.31 %；DRAM-only AegisKV=27.84/26.54/26.18 %；AegisKV=22.12/18.89/16.89 %。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-concurrency-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-concurrency-dram_hit_pct](../../../output/pdf/three-system-20260908/sensitivity-concurrency-dram_hit_pct.png)

**sensitivity-concurrency-foreground_transfer_p95_ms** — P95 foreground DRAM GET latency (ms)；单变量改变 Active workflow concurrency

审查记录：按横轴配置顺序，Mooncake=3835/4365/4778 ms；DRAM-only AegisKV=1827/1667/1703 ms；AegisKV=1849/1639/1721 ms。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-foreground_transfer_p95_ms.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-foreground_transfer_p95_ms.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-concurrency-foreground_transfer_p95_ms.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-concurrency-foreground_transfer_p95_ms](../../../output/pdf/three-system-20260908/sensitivity-concurrency-foreground_transfer_p95_ms.png)

**sensitivity-concurrency-mean_wct_s** — Mean workflow completion time (s)；单变量改变 Active workflow concurrency

审查记录：按横轴配置顺序，Mooncake=31.45/53.39/92.36 s；DRAM-only AegisKV=38.31/64.05/108.4 s；AegisKV=40.81/69.74/123.4 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-mean_wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-mean_wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-concurrency-mean_wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-concurrency-mean_wct_s](../../../output/pdf/three-system-20260908/sensitivity-concurrency-mean_wct_s.png)

**sensitivity-concurrency-p95_scheduler_queue_s** — P95 GPU scheduler queue delay (s)；单变量改变 Active workflow concurrency

审查记录：按横轴配置顺序，Mooncake=6.57/9.483/14.34 s；DRAM-only AegisKV=8.886/13.15/20.56 s；AegisKV=9.565/16.72/28.33 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-p95_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-concurrency-p95_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-concurrency-p95_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-concurrency-p95_scheduler_queue_s](../../../output/pdf/three-system-20260908/sensitivity-concurrency-p95_scheduler_queue_s.png)

**sensitivity-cpu-service-dram_hit_pct** — Prompt tokens served by DRAM (%)；单变量改变 Controller service-cost multiplier

审查记录：按横轴配置顺序，Mooncake=0/0 %；DRAM-only AegisKV=0/0 %；AegisKV=0/0 %。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-cpu-service-dram_hit_pct](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-dram_hit_pct.png)

**sensitivity-cpu-service-mean_wct_s** — Mean workflow completion time (s)；单变量改变 Controller service-cost multiplier

审查记录：按横轴配置顺序，Mooncake=39.07/39.07 s；DRAM-only AegisKV=39.07/39.51 s；AegisKV=39.07/39.51 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-mean_wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-mean_wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-mean_wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-cpu-service-mean_wct_s](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-mean_wct_s.png)

**sensitivity-cpu-service-p95_scheduler_queue_s** — P95 GPU scheduler queue delay (s)；单变量改变 Controller service-cost multiplier

审查记录：按横轴配置顺序，Mooncake=15.16/15.16 s；DRAM-only AegisKV=15.16/15.08 s；AegisKV=15.16/15.08 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-p95_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-p95_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-p95_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-cpu-service-p95_scheduler_queue_s](../../../output/pdf/three-system-20260908/sensitivity-cpu-service-p95_scheduler_queue_s.png)

**sensitivity-dram-capacity-dram_hit_pct** — Prompt tokens served by DRAM (%)；单变量改变 DRAM cache capacity (GiB)

审查记录：按横轴配置顺序，Mooncake=0.4224/7.545/48.08 %；DRAM-only AegisKV=0.7454/7.531/26.54 %；AegisKV=0.9796/7.033/18.89 %。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-dram-capacity-dram_hit_pct](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-dram_hit_pct.png)

**sensitivity-dram-capacity-foreground_transfer_p95_ms** — P95 foreground DRAM GET latency (ms)；单变量改变 DRAM cache capacity (GiB)

审查记录：按横轴配置顺序，Mooncake=452.6/1450/4365 ms；DRAM-only AegisKV=967.9/812.5/1667 ms；AegisKV=550.4/1060/1639 ms。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-foreground_transfer_p95_ms.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-foreground_transfer_p95_ms.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-foreground_transfer_p95_ms.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-dram-capacity-foreground_transfer_p95_ms](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-foreground_transfer_p95_ms.png)

**sensitivity-dram-capacity-mean_wct_s** — Mean workflow completion time (s)；单变量改变 DRAM cache capacity (GiB)

审查记录：按横轴配置顺序，Mooncake=83.14/76.71/53.39 s；DRAM-only AegisKV=81.69/76.02/64.05 s；AegisKV=82.03/79.08/69.74 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-mean_wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-mean_wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-mean_wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-dram-capacity-mean_wct_s](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-mean_wct_s.png)

**sensitivity-dram-capacity-p95_scheduler_queue_s** — P95 GPU scheduler queue delay (s)；单变量改变 DRAM cache capacity (GiB)

审查记录：按横轴配置顺序，Mooncake=19.91/18.58/9.483 s；DRAM-only AegisKV=17.35/16.28/13.15 s；AegisKV=18.42/17.91/16.72 s。这些点是不同配置，未画重复运行置信区间。

[PNG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-p95_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-p95_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-p95_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/cross-case-figure-manifest.json)

![sensitivity-dram-capacity-p95_scheduler_queue_s](../../../output/pdf/three-system-20260908/sensitivity-dram-capacity-p95_scheduler_queue_s.png)

</details>

<a id="three-system-f0-cpu4x"></a>
### f0-cpu4x

配置：160 workflows / 1304 requests；C=16；revisit rounds=1；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-cpu4x-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] %；DRAM-only AegisKV：中位数 0，范围 [0, 0] %；AegisKV：中位数 0，范围 [0, 0] %。

[PNG](../../../output/pdf/three-system-20260908/f0-cpu4x-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-cpu4x-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-cpu4x-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-cpu4x-figure-manifest.json)

![f0-cpu4x-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-cpu4x-dram_hit_pct.png)

**f0-cpu4x-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 4.833，范围 [0.6016, 14.59] s；DRAM-only AegisKV：中位数 4.783，范围 [0.2078, 12.73] s；AegisKV：中位数 4.782，范围 [0.2078, 12.73] s。

[PNG](../../../output/pdf/three-system-20260908/f0-cpu4x-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-cpu4x-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-cpu4x-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-cpu4x-figure-manifest.json)

![f0-cpu4x-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-cpu4x-mean_scheduler_queue_s.png)

**f0-cpu4x-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0.0002551，范围 [-37.27, 35.72] s；AegisKV：中位数 0.0003115，范围 [-37.27, 35.71] s。

[PNG](../../../output/pdf/three-system-20260908/f0-cpu4x-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-cpu4x-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-cpu4x-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-cpu4x-figure-manifest.json)

![f0-cpu4x-wct-difference](../../../output/pdf/three-system-20260908/f0-cpu4x-wct-difference.png)

**f0-cpu4x-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 35.7，范围 [4.981, 131.2] s；DRAM-only AegisKV：中位数 37.5，范围 [3.299, 131.2] s；AegisKV：中位数 37.5，范围 [3.299, 131.2] s。

[PNG](../../../output/pdf/three-system-20260908/f0-cpu4x-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-cpu4x-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-cpu4x-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-cpu4x-figure-manifest.json)

![f0-cpu4x-wct_s](../../../output/pdf/three-system-20260908/f0-cpu4x-wct_s.png)

</details>

<a id="three-system-f0-revisit-bw5"></a>
### f0-revisit-bw5

配置：160 workflows / 2608 requests；C=16；revisit rounds=2；DRAM=931.323 GiB；链路=5 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-bw5-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 41.62，范围 [0, 49.92] %；DRAM-only AegisKV：中位数 3.044，范围 [0, 24.68] %；AegisKV：中位数 0，范围 [0, 4.558] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw5-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw5-figure-manifest.json)

![f0-revisit-bw5-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-bw5-dram_hit_pct.png)

**f0-revisit-bw5-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 1.17，范围 [0.05949, 6.325] s；DRAM-only AegisKV：中位数 4.948，范围 [1.061, 10.82] s；AegisKV：中位数 5.073，范围 [0.1815, 10.92] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw5-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw5-figure-manifest.json)

![f0-revisit-bw5-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-bw5-mean_scheduler_queue_s.png)

**f0-revisit-bw5-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 -67.4，范围 [-421.3, 114.2] s；AegisKV：中位数 -62.7，范围 [-422.7, 112.5] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw5-figure-manifest.json)

![f0-revisit-bw5-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct-difference.png)

**f0-revisit-bw5-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 144，范围 [2.996, 483.2] s；DRAM-only AegisKV：中位数 75.25，范围 [25.76, 203.3] s；AegisKV：中位数 78.91，范围 [11.17, 240.2] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw5-figure-manifest.json)

![f0-revisit-bw5-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-bw5-wct_s.png)

</details>

<a id="three-system-f0-revisit-bw50"></a>
### f0-revisit-bw50

配置：160 workflows / 2608 requests；C=16；revisit rounds=2；DRAM=931.323 GiB；链路=50 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-bw50-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 49.73，范围 [27.09, 49.92] %；DRAM-only AegisKV：中位数 34.45，范围 [4.534, 49.85] %；AegisKV：中位数 28.78，范围 [0.4003, 49.81] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw50-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw50-figure-manifest.json)

![f0-revisit-bw50-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-bw50-dram_hit_pct.png)

**f0-revisit-bw50-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 2.241，范围 [0.0774, 6.155] s；DRAM-only AegisKV：中位数 2.702，范围 [0.6306, 5.903] s；AegisKV：中位数 3.129，范围 [0.8067, 7.216] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw50-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw50-figure-manifest.json)

![f0-revisit-bw50-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-bw50-mean_scheduler_queue_s.png)

**f0-revisit-bw50-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 5.505，范围 [-63.04, 102.2] s；AegisKV：中位数 9.843，范围 [-74.26, 76.8] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw50-figure-manifest.json)

![f0-revisit-bw50-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct-difference.png)

**f0-revisit-bw50-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 45.73，范围 [7.168, 127.3] s；DRAM-only AegisKV：中位数 52.25，范围 [11.19, 148.1] s；AegisKV：中位数 54.68，范围 [14.85, 160.3] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-bw50-figure-manifest.json)

![f0-revisit-bw50-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-bw50-wct_s.png)

</details>

<a id="three-system-f0-revisit-c32"></a>
### f0-revisit-c32

配置：160 workflows / 2608 requests；C=32；revisit rounds=2；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-c32-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 49.7，范围 [0.03748, 49.92] %；DRAM-only AegisKV：中位数 24.58，范围 [0.09946, 48.79] %；AegisKV：中位数 14.82，范围 [0, 42.79] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c32-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c32-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c32-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c32-figure-manifest.json)

![f0-revisit-c32-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-c32-dram_hit_pct.png)

**f0-revisit-c32-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 3.319，范围 [0.5139, 16.93] s；DRAM-only AegisKV：中位数 5.494，范围 [1.523, 19.26] s；AegisKV：中位数 7.235，范围 [2.121, 27.8] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c32-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c32-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c32-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c32-figure-manifest.json)

![f0-revisit-c32-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-c32-mean_scheduler_queue_s.png)

**f0-revisit-c32-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 15.44，范围 [-221.5, 422] s；AegisKV：中位数 31.7，范围 [-193.5, 400.4] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c32-figure-manifest.json)

![f0-revisit-c32-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct-difference.png)

**f0-revisit-c32-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 72.66，范围 [11.79, 479.8] s；DRAM-only AegisKV：中位数 92，范围 [24.59, 575.3] s；AegisKV：中位数 110.2，范围 [25.39, 458.2] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c32-figure-manifest.json)

![f0-revisit-c32-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-c32-wct_s.png)

</details>

<a id="three-system-f0-revisit-c8"></a>
### f0-revisit-c8

配置：160 workflows / 2608 requests；C=8；revisit rounds=2；DRAM=931.323 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-c8-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 49.64，范围 [25.04, 49.92] %；DRAM-only AegisKV：中位数 27.09，范围 [0, 49.68] %；AegisKV：中位数 20.84，范围 [0.07149, 45.59] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c8-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c8-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c8-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c8-figure-manifest.json)

![f0-revisit-c8-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-c8-dram_hit_pct.png)

**f0-revisit-c8-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 1.278，范围 [0.0258, 3.982] s；DRAM-only AegisKV：中位数 1.765，范围 [0.0561, 4.918] s；AegisKV：中位数 2.11，范围 [0.2937, 6.483] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c8-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c8-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c8-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c8-figure-manifest.json)

![f0-revisit-c8-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-c8-mean_scheduler_queue_s.png)

**f0-revisit-c8-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 5.883，范围 [-34.24, 59.62] s；AegisKV：中位数 8.027，范围 [-31.06, 61.76] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c8-figure-manifest.json)

![f0-revisit-c8-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct-difference.png)

**f0-revisit-c8-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 28.42，范围 [7.835, 82.79] s；DRAM-only AegisKV：中位数 36.41，范围 [3.513, 105.4] s；AegisKV：中位数 39.57，范围 [11.17, 83.7] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-c8-figure-manifest.json)

![f0-revisit-c8-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-c8-wct_s.png)

</details>

<a id="three-system-f0-revisit-dram128"></a>
### f0-revisit-dram128

配置：160 workflows / 2608 requests；C=16；revisit rounds=2；DRAM=128.000 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-dram128-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 49.88] %；DRAM-only AegisKV：中位数 4.689，范围 [0, 29.65] %；AegisKV：中位数 4.556，范围 [0, 29.65] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram128-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram128-figure-manifest.json)

![f0-revisit-dram128-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-dram128-dram_hit_pct.png)

**f0-revisit-dram128-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 4.669，范围 [0.4004, 12.04] s；DRAM-only AegisKV：中位数 4.531，范围 [0.8196, 10.2] s；AegisKV：中位数 4.371，范围 [0.5238, 9.846] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram128-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram128-figure-manifest.json)

![f0-revisit-dram128-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-dram128-mean_scheduler_queue_s.png)

**f0-revisit-dram128-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 -2.083，范围 [-72.02, 98.08] s；AegisKV：中位数 1.468，范围 [-97.78, 105.3] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram128-figure-manifest.json)

![f0-revisit-dram128-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct-difference.png)

**f0-revisit-dram128-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 74.36，范围 [10.69, 238.7] s；DRAM-only AegisKV：中位数 72.88，范围 [23.07, 210.5] s；AegisKV：中位数 75.84，范围 [21.16, 217.8] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram128-figure-manifest.json)

![f0-revisit-dram128-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-dram128-wct_s.png)

</details>

<a id="three-system-f0-revisit-dram32"></a>
### f0-revisit-dram32

配置：160 workflows / 2608 requests；C=16；revisit rounds=2；DRAM=32.000 GiB；链路=25 GB/s。源码 snapshot SHA-256：`38b90e905e57c1582f713886d89d63e44c8e1dfcc70a2e27edd491407a8119fc`。

<details>
<summary>展开 4 张独立图及绘制说明</summary>

**f0-revisit-dram32-dram_hit_pct** — Prompt tokens served by DRAM (%)

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 42.78] %；DRAM-only AegisKV：中位数 0，范围 [0, 26.83] %；AegisKV：中位数 0，范围 [0, 15.89] %。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-dram_hit_pct.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-dram_hit_pct.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram32-dram_hit_pct.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram32-figure-manifest.json)

![f0-revisit-dram32-dram_hit_pct](../../../output/pdf/three-system-20260908/f0-revisit-dram32-dram_hit_pct.png)

**f0-revisit-dram32-mean_scheduler_queue_s** — Mean GPU scheduler queue delay (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 4.751，范围 [0.819, 11] s；DRAM-only AegisKV：中位数 4.859，范围 [0.713, 10.32] s；AegisKV：中位数 4.997，范围 [0.3076, 12.79] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-mean_scheduler_queue_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-mean_scheduler_queue_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram32-mean_scheduler_queue_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram32-figure-manifest.json)

![f0-revisit-dram32-mean_scheduler_queue_s](../../../output/pdf/three-system-20260908/f0-revisit-dram32-mean_scheduler_queue_s.png)

**f0-revisit-dram32-wct-difference** — 逐 workflow 相对 Mooncake 的 WCT 差值

审查记录：160 个配对 Workflow：Mooncake：中位数 0，范围 [0, 0] s；DRAM-only AegisKV：中位数 0.3351，范围 [-166.3, 160] s；AegisKV：中位数 0.2762，范围 [-149, 51.96] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct-difference.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct-difference.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct-difference.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram32-figure-manifest.json)

![f0-revisit-dram32-wct-difference](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct-difference.png)

**f0-revisit-dram32-wct_s** — Workflow completion time (s)

审查记录：160 个配对 Workflow：Mooncake：中位数 77.74，范围 [9.947, 258.7] s；DRAM-only AegisKV：中位数 77.54，范围 [9.933, 222.9] s；AegisKV：中位数 81.86，范围 [14.51, 232] s。

[PNG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct_s.png) · [SVG](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct_s.svg) · [PDF](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct_s.pdf) · [图像清单](../../../output/pdf/three-system-20260908/f0-revisit-dram32-figure-manifest.json)

![f0-revisit-dram32-wct_s](../../../output/pdf/three-system-20260908/f0-revisit-dram32-wct_s.png)

</details>

<!-- THREE_SYSTEM_REVIEW_END -->





## 导航

| 图组 | 目录记录 | 独立展示 | 副本引用 |
|---|---:|---:|---:|
| [当前论文图与 Motivation 子图](#group-current) | 13 | 13 | 0 |
| [历史 Qwen3-8B：Figure 1 工作负载与干预](#group-figure1) | 4 | 4 | 0 |
| [历史 Qwen3-8B：无故障开销 v12](#group-healthy-v12) | 4 | 4 | 0 |
| [历史 Qwen3-8B：故障与恢复 v13](#group-failure-v13) | 7 | 7 | 0 |
| [历史 Qwen3-8B：修复后小样本预览](#group-postfix) | 4 | 4 | 0 |
| [历史 FanOutQA 参数扫描 v5](#group-sweeps-v5) | 16 | 16 | 0 |
| [历史 FanOutQA 参数扫描 v3](#group-sweeps-v3) | 15 | 15 | 0 |
| [历史 FanOutQA 参数扫描 v2](#group-sweeps-v2) | 5 | 5 | 0 |
| [历史 FanOutQA 参数扫描 v1](#group-sweeps-v1) | 5 | 5 | 0 |
| [历史 E2：Qwen3-8B DP 全矩阵](#group-dp-all) | 14 | 14 | 0 |
| [历史 E2：流体争用与完整 HBM 账本](#group-fluid) | 3 | 3 | 0 |
| [历史 E2：Store 传输路径](#group-transport) | 1 | 1 | 0 |
| [历史 E2：Store 节点数](#group-store-nodes) | 1 | 1 | 0 |
| [历史 E2：初始图集](#group-initial) | 14 | 14 | 0 |
| [历史 E2：modeled-preliminary-complete 格式图集](#group-complete-export) | 14 | 14 | 0 |
| [归档：未纳入当前论文的 8B 图](#group-unused-paper) | 9 | 9 | 0 |
| [归档：更早的 SGLSim / 论文图](#group-legacy-paper) | 7 | 7 | 0 |
| [归档：算法 revision 3 前快照](#group-before-revision3) | 13 | 1 | 12 |
| [输出归档：September 5 压缩排版前图](#group-precompact) | 7 | 7 | 0 |
| [输出归档：September 6 版面预览图](#group-layout-preview) | 10 | 9 | 1 |
| [输出归档：September 6 重绘前图](#group-pre-revision) | 18 | 9 | 9 |
| [格式副本：参数扫描 v5 的 PDF 导出](#group-v5-pdf) | 16 | 0 | 16 |
| [格式副本：论文机制图与 Motivation 源目录](#group-drawio-copies) | 6 | 0 | 6 |
| [来源副本：导入的旧 Motivation PDF](#group-imported-motivation) | 1 | 0 | 1 |
| [格式副本：September 5 源码包中的图](#group-submission-copies) | 7 | 0 | 7 |
| [格式副本：September 6 previous-paper 图](#group-previous-copies) | 8 | 0 | 8 |
| [格式副本：output/pdf 扫描 v1](#group-output-pdf-v1) | 5 | 0 | 5 |
| [格式副本：output/pdf 扫描 v2](#group-output-pdf-v2) | 5 | 0 | 5 |
| [格式副本：output/pdf 扫描 v3](#group-output-pdf-v3) | 15 | 0 | 15 |

可直接查看[当前论文逐图背景与共同配置](#current-paper-review)，或跳转到[范围、缺项与核对说明](#coverage)。

<a id="group-current"></a>

## 重绘前论文图与 Motivation 子图（保留溯源）

10 幅正文图按论文顺序排列，另列 3 个 Motivation 子图。当前设计已修订到算法 2/3 revision 3；统计图仍评价修订前策略。来源说明中的 170 次 CPU 模拟使用五个配对 admission order，服务时序未做目标硬件校准；旧策略的结果不能作为新算法性能证据。Motivation 中的真实 trace、反事实模型和 RTX4090 pilot 样本按各图说明区分。当前主结果、消融和敏感性中的跨零区间应保留。

目录：[paper/figures](../paper/figures) · [paper/figures/motivation-panels](../paper/figures/motivation-panels)。

来源：[当前论文](../paper/README.md) · [算法版本与证据](../docs/paper/ALGORITHM_REVISION_V3.md) · [统计数据](results/paper/data/aligned-statistics.json) · [绘图输入](results/paper/data/publication-figure-inputs.json) · [图像哈希清单](results/paper/data/figure-manifest.json) · [逐图说明](../docs/paper/FIGURE_REVISION.md) · [定量图生成器](scripts/paper/render_submission_figures.py) · [机制图生成器](scripts/paper/build_submission_diagrams.py)。

**逐图审查时间：2026-09-07 17:28 +0800。**

<a id="current-paper-review"></a>

### 逐图审查范围与共同配置

本轮逐张查看了下面的 **10 幅正文图和 3 个 Motivation 子图**，并渲染核对当前论文第 2、3、4、6、8、10、11、12 页。检查覆盖图像、图注、绘图脚本、输入与冻结配置；这是当前论文图组的逐图审查，后面的历史图组保持索引用途。

**本历史分区的版本区别：旧图 3 表达 revision 3 的设计，旧图 6–10 来自 SlackLandlord/HBMQuotaAIMD 的 `mooncake_prompt_v1`。** [原 revision-3 状态文件](../docs/paper/REVISION_STATUS.json) 记录的是既有正式集成状态，不包含本轮机制实验适配器的新执行。旧图 4 表达共用的部分提交/恢复语义。最新三系统图及其模拟边界见[本轮更新](#three-system-review)。

以下配置适用于图 6–10 的模拟；图 5 使用相同冻结工作负载做描述统计。图 1 的反事实模型和图 2 的 RTX4090 样本另列，不能套用本表。

| 维度 | 冻结值及解释 |
|---|---|
| 实验版本 | `campaign-v2` 绑定 `source-v2` 的内容清单；协议 fingerprint 为 `1a63f33c60bf5a03d8724713ef10446f258cb765df4557cf162a6b086070ede6`。 |
| 模型 | `Qwen/Qwen3-8B`，revision `b968826d9c46dd6066d109eabc6255188de91218`；KV 布局按 BF16、2 bytes/element 计算。 |
| 并行与硬件模型 | DP=8、TP=1、PP=1；单节点 8×A100-40GB，每 GPU 40 GiB HBM。都是声明的模拟硬件参数。 |
| GPU 内存 | 权重 16,381,470,720 B/GPU，固定 runtime reserve 2 GiB/GPU；registered HBM capacity M=40 GiB。 |
| KV / 保护粒度 | 147,456 B/token；保护 sealed prompt 的 4,096-token chunk；模拟源分配粒度 64 tokens。布局推导中的 vLLM page 为 16 tokens，不能把两种粒度混写。 |
| Store / 通信 | 单个同机 DRAM Store，容量 10^12 B；Peer 与 Store 有效路径服务率基础值均为 25×10^9 B/s，setup 250 μs，reroute 1 ms。敏感性同时将两条路径改为 5 GB/s。 |
| 旧 AIMD | 初始 alpha=0.20、最大 0.50、乘性因子 0.50、加性步长 0.05、4 个稳定窗口、每窗口 1 s；Q=alpha×M。 |
| 工作负载 | FanOutQA dev 派生的 160 个完整 workflows、1,304 calls；精确 prompt token 身份，输出数量与服务时长为预先规定值。 |
| 上下文范围 | prompt 最大 86,198 tokens；prompt+output 最大 86,214；配置上限 131,072，128K bucket 实际计数为 0。 |
| 闭环并发 | 基础 C=16；一个 workflow 完成后才补入下一个，敏感性为 C=8/32。C 是活跃 workflow 数，不是 DP 数或单 GPU batch request 上限。 |
| 随机化与配对 | admission seeds 0–4 形成五种固定负载排列，跨策略/F0 配对；peer/routing binding seed 固定为 0。五个 seed 是推断单位，不是 800 个独立 workflows。 |
| 旧 Algorithm 1 信号 | 使用预先规定的理想节点时长进行 CPM；本模拟不训练或调用 GBDT，不能将曲线解释为真实预测器准确率。 |
| 批次服务假设 | 基础 serialization beta=0；敏感性 beta=0.5/1。单请求服务预算保持不变，改变的是共享 step 的服务组成假设，时序未做 A100 校准。 |
| 故障语义 | GPU/worker fail-stop，HBM 丢失；检测延迟 0，120 s 模拟时间后恢复为空的可用容量。 |
| 主故障计划 | 基础 F1 只注入 **1 次**故障。由未保护 reference 在 96K eligibility 桶中选取接近 50% 工作负载进度的逻辑请求，在其 prompt+output 进度达到 60% 时使实际承载 GPU 故障。 |
| 两次故障 | 仅 `failures2` 点使用 2 次，reference 目标靠近 1/3、2/3 工作负载进度；每次仍按 focus 请求自身 60% 进度注入。 |
| 对照策略 | None=不保护、全重算；DRAM=保留旧 SlackLandlord 的 AegisKV DRAM-only；Full=旧 AegisKV HBM+DRAM。DRAM 不是原生 Mooncake 或 GhostServe 的外部 baseline。 |
| WCT 起点 | workflow 首次请求 release 到 workflow 完成，排除入场 slot 等待；完整 batch makespan 是另一个指标。 |
| 置信区间 | 五个 seed 内先各自汇总，再作配对差值；双侧 95% Student-t，df=4。探索性区间，未做多重比较校正。 |

配置依据：[冻结实验协议](../../../output/paper-simulation-8b/20260906-alignment/campaign-v2/PROTOCOL.json)、[冻结 campaign runner](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/scripts/run_mooncake_aligned_paper.py)、[冻结 engine.json](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/configs/engine.json)、[冻结 requests.json](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/configs/requests.json)、[Qwen3-8B KV 布局](../../../output/paper-simulation-8b/20260906-alignment/source-v2/configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json)、[论文实验方法](../paper/sections/experimental-method.tex)、[实现与模拟对应关系](../paper/sections/implementation.tex)。

**不能仅抄三个 JSON 就概括论文配置。** [冻结 failure.json](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/configs/failure.json) 的默认 `failure_count=2` 被 campaign 各点显式覆盖；基础点使用 1 次。故障匹配的是逻辑请求和进度，不要求不同策略拥有完全相同的故障 wall-clock 时间、物理路由或连带受害请求。五个 seed 也不表示五次完全独立抽取的数据集。

170 次执行的组成是：基础 60（6 arms×F0/F1×5 seeds）、并发 40、批次服务 40、带宽 20、两次故障 10。图之间重用同一批运行，不应把各图所用样本数再相加。两次故障点复用基础 F0；用于选故障的 reference 运行不计入 170。

**本次核对结果。** 当前图像清单中的 45 个正文/组件文件与实物一致；191 个统计/绘图输入文件及 383 个冻结源码文件的哈希一致；重新计算的 26 组均值/95% 区间一致，四条实机路径聚合率与五组恢复 prompt 守恒也一致。来源为 [当前图像清单](results/paper/data/figure-manifest.json)、[冻结源码清单](../../../output/paper-simulation-8b/20260906-alignment/source-v2/SOURCE_SNAPSHOT.json)、[170-run acceptance](../../../output/paper-simulation-8b/20260906-alignment/campaign-v2/ACCEPTANCE.json)、[配对统计与恢复明细](results/paper/data/aligned-statistics.json)、[实际绘图输入](results/paper/data/publication-figure-inputs.json)。本轮没有重放大体积原始事件日志，也没有运行新实验；数值核对不替代原始执行审计或硬件校准。

**阅读改进项。** 当前渲染未见遮挡关键数据的明显重叠或截断。图 5(b) 的数据到 27 calls，但刻度只写 5/10/15，建议补 20/25 或最大值；图 8(a) 纵轴标签贴近左边界，建议增加留白。这两项仅记录审查意见，未改动已有图像。

<a id="figure-current-1"></a>

### G01-01 正文图 1：并行分支差异与恢复后果

观测时长差 ECDF、五分支工作流和恢复延迟分解；观测、推断依赖与冻结的反事实模型分别标注。

`motivation-real-cc` · [PNG](../paper/figures/motivation-real-cc.png) · [SVG](../paper/figures/motivation-real-cc.svg) · [PDF](../paper/figures/motivation-real-cc.pdf)

![G01-01 正文图 1：并行分支差异与恢复后果](../paper/figures/motivation-real-cc.png)

**绘制背景。** 这张 Motivation 图说明：恢复工作量相近的两个请求，若处在不同的并行分支，最终增加的 workflow 延迟可能不同。它是后文使用 Slack 评价保护价值的动机，而不是 AegisKV 加速实验。

**数据与配置。** (a) 从 CC/Weka trace 的 393 条会话中保留 124 个有严格共同重叠分支的 workflow；每个 workflow 只贡献一个最大 longest-minus-shortest 时长差，采用对数横轴。(b) 展示同一个五分支 trace，join 根据顺序与时间戳重建，在 349.5 s 标记故障位置。(c) 假设依次对 A1–A5 各单独施加一次故障，使用冻结的 AIConfigurator 预测：**Qwen3-235B-A22B、A100-80GB、TP8/PP4/EP8、SILICON 数据模式、8,192-token predictor chunk**。这个模型配置不属于后面的 Qwen3-8B DP8 实验。

**图中读数。** 最大分支时长差的中位数 140.611 s、P90 1,570.290 s。A3 的 Slack 为 52.447 s，可吸收 46.635 s 的模型重算；A4 的 Slack 为 0，35.903 s 重算全部暴露为延迟。A1/A2/A3/A4/A5 的暴露延迟依次约为 0、17.152、0、35.903、21.377 s。

**审查意见。** (a) 是观测统计，(b) 含依赖推断，(c) 是保持其他分支不变、忽略新增争用的反事实；这三种性质必须保留在图注中。五个分支是五个分别评估的故障位置，不是一次运行同时打坏五个分支。输入长度由 64-token hash block 计数而来；当前没有重新执行或实机校准该反事实模型。当前三联图及其第 2 页图注与这些限制一致。

追溯：[124-workflow gap CSV](results/paper/data/motivation-real-cc/real-cc-workflow-parallel-gap.csv)、[五分支与反事实 CSV](results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv)、[trace 重建记录](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)、[论文 Motivation](../paper/sections/motivation.tex)。

<a id="figure-current-2"></a>

### G01-02 正文图 2：KV 容量与传输代价

解析 KV 容量曲线与 RTX4090 pilot 传输样本；解析容量、host-staged 实测样本和 A100 模拟参数不能混为同一类证据。

`aligned-motivation-cost` · [PNG](../paper/figures/aligned-motivation-cost.png) · [SVG](../paper/figures/aligned-motivation-cost.svg) · [PDF](../paper/figures/aligned-motivation-cost.pdf)

![G01-02 正文图 2：KV 容量与传输代价](../paper/figures/aligned-motivation-cost.png)

**绘制背景。** 保护 KV 会占用原本用于推理的显存，也需要真实的数据搬运。左面板解释容量压力，右面板用物理样本展示有效传输服务代价，两者共同解释为何“多一份备份”需要代价核算。

**左图配置：解析计算。** Qwen3-8B 使用 36 层、8 个 KV heads、head dimension 128、2 B/element，因此每 token 的 K+V 是 147,456 B。横轴覆盖 0–96 Ki tokens，单/双份曲线按 token 数线性计算。红线是 40 GiB HBM 减去 16,381,470,720 B 权重与 2 GiB runtime reserve，剩余约 **22.744 GiB**。4,096-token chunk 为 576 MiB；这是容量公式，不是运行中分配测量。

**右图配置：物理小样本。** 来自同一次 Slurm 146426 分配中的双 RTX4090、Qwen3-8B、DP2/TP1/PP1，Peer-HBM 经过 host staging，含 D2H/H2D 和软件开销。每个样本是 (bytes, duration_ms)；菱形按总 bytes / 总 duration 计算，不是对各样本 GB/s 作算术平均。

| 路径 | 传输样本数 | 聚合有效速率 |
|---|---:|---:|
| HBM write | 2 | 0.587 GB/s |
| DRAM write | 4 | 0.336 GB/s |
| HBM load | 1 | 2.300 GB/s |
| DRAM load | 1 | 1.233 GB/s |

**审查意见。** 这四类样本来自独立的路径机制/校准记录，不是 170 次模拟，也不是把六工作流故障 pilot 当作多次性能重复。一个 load 样本不支持置信区间；测得的有效速率不是原始 HBM 峰值带宽，也没有校准模拟中的 A100/25 GB/s。pilot 的 registered HBM=2 GiB、初始 alpha=0.5、控制间隔=5 s，亦不同于模拟的 40 GiB/0.2/1 s。左右图的证据类型在标题和图注中已区分。

追溯：[Qwen3-8B KV 布局](../../../output/paper-simulation-8b/20260906-alignment/source-v2/configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json)、[四路径实机样本](results/paper/data/physical-pilot/pilot-cost-profile.json)、[论文实机配置](../paper/sections/physical-pilot.tex)、[论文 Motivation](../paper/sections/motivation.tex)；计算见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `cost()`。

<a id="figure-current-3"></a>

### G01-03 正文图 3：系统架构

组件所有权、备份路径与恢复关系；属于设计示意。

`system-overview` · [PNG](../paper/figures/system-overview.png) · [PDF](../paper/figures/system-overview.pdf) · [原生导出 PNG](../paper/figures/system-overview.native.png) · [原生导出 PDF](../paper/figures/system-overview.native.pdf) · [Draw.io 源](../paper/figures/system-overview.drawio)

![G01-03 正文图 3：系统架构](../paper/figures/system-overview.png)

**绘制背景。** 明确策略归谁、KV 由谁持有、两层备份怎样写入，以及恢复时为何还需要单独的 primary buffers。它对应当前 revision 3 的系统设计。

**图的设定。** Application 提供 GBDT+CPM 的版本化 Slack ticket；Router 负责主/备 worker 绑定、namespace 与输出 fence；Store Master 是策略所有者，标出 Algorithm 2 PrefixAdmission、Algorithm 3 ForegroundBudget。Source 在 forward 完成后 seal/group/stage，再独立复制到 standby HBM 和 Store DRAM；两层分别 reserve/ACK。实线表示 KV bytes，虚线表示控制，HBM load 和 DRAM load 都写入 separate primary KV。

**实验配置适用范围。** 本图没有 seed、故障次数或性能样本数；它不表示某一台实际节点的 DP=8 拓扑。后续模拟评估使用 TP=PP=1，且使用理想 CPM，并未调用图中所写的 GBDT。新算法只完成串行事件参考验证：159 个 revision-3 参考测试及 33 个旧契约回归不是 workload 性能实验。

**审查意见。** 当前图和第 4 页图注明确写有 revision 3 / event reference，和状态文件一致。不能用图 6–10 的旧策略曲线证明此图中的共享 prefix、staged replacement、ForegroundBudget 或 1% 干扰目标已经实现。图中没有 Peer→DRAM destage，HBM 和 DRAM 均由 source 独立写入，方向与设计说明一致。

追溯：[论文设计与图注](../paper/sections/system-design.tex)、[revision-3 状态](../docs/paper/REVISION_STATUS.json)、[算法修订说明](../docs/paper/ALGORITHM_REVISION_V3.md)、[实现与模拟对应关系](../paper/sections/implementation.tex)；可编辑源为上方 Draw.io，生成器为 [机制图生成器](scripts/paper/build_submission_diagrams.py)。

<a id="figure-current-4"></a>

### G01-04 正文图 4：提交与恢复机制

独立 tier 的提交前缀、故障与备份复制到主 KV 的关系；事件顺序属于机制示意。

`commit-recovery` · [PNG](../paper/figures/commit-recovery.png) · [PDF](../paper/figures/commit-recovery.pdf) · [原生导出 PNG](../paper/figures/commit-recovery.native.png) · [原生导出 PDF](../paper/figures/commit-recovery.native.pdf) · [Draw.io 源](../paper/figures/commit-recovery.drawio)

![G01-04 正文图 4：提交与恢复机制](../paper/figures/commit-recovery.png)

**绘制背景。** 解释“申请/开始复制”与“故障后可恢复”之间的区别，以及 HBM 与 DRAM 独立提交的含义，防止把 pending bytes 算进恢复收益。

**示意场景。** 对 chunk 1，source 先 seal/reserve，HBM ACK 先到，DRAM 仍 pending，此时 source 失效。故障后的 HBM committed 前缀为 chunks 0–1；DRAM 只有 chunk 0，chunk 1 aborted；chunk 2 在两层都不存在。恢复先将 HBM 0–1 复制到新的 primary buffers，再重算 suffix 2。

**实验配置。** 这是手工构造的逻辑事件序列，没有按比例的时间刻度、实际故障 timestamp、seed 或样本数。图中的 chunk 0/1/2 是语义例子，不能按画出的条长推导传输时延或故障恢复时间。

**审查意见。** 第 6 页图注说明这些是两版共用的提交/恢复语义。图可说明 pending 不可恢复、tier frontier 不同以及 backup→primary 复制，但没有覆盖 revision 3 的组替换、压力竞争、lease 撤销、物理释放 ACK 或 QoS 认证，不能用它证明这些行为已通过运行验证。

追溯：[论文设计与图注](../paper/sections/system-design.tex)、[机制图生成器](scripts/paper/build_submission_diagrams.py)、[实现与模拟对应关系](../paper/sections/implementation.tex)。

<a id="figure-current-5"></a>

### G01-05 正文图 5：工作负载覆盖

FanOutQA 派生工作负载的 prompt、工作流调用数和 context 分布；160 workflows、1,304 calls，128K bucket 为零。

`aligned-workload` · [PNG](../paper/figures/aligned-workload.png) · [SVG](../paper/figures/aligned-workload.svg) · [PDF](../paper/figures/aligned-workload.pdf)

![G01-05 正文图 5：工作负载覆盖](../paper/figures/aligned-workload.png)

**绘制背景。** 在讨论性能之前，交代研究实际使用了什么负载、分支规模和上下文长度，避免把配置上限当成观测覆盖。

**数据与配置。** FanOutQA dev 的问题、人工分解/依赖和证据，经固定 Qwen3-8B tokenizer 派生为 160 个完整 workflows、1,304 calls。(a) 使用 1,304 个 prompt 长度；(b) 使用 160 个 workflow 的 call 数，范围 **6–27**；(c) 使用 prompt+规定输出的 context 长度分桶。图是固定数据集的描述统计，没有单独运行故障实验，也没有对 ECDF 画推断区间。

| context 桶标签（Ki tokens 上界） | 8 | 16 | 32 | 64 | 96 | 128 |
|---|---:|---:|---:|---:|---:|---:|
| calls | 441 | 210 | 326 | 291 | 36 | 0 |

**图中读数与边界。** prompt 最大 86,198 tokens；context 最大 86,214 tokens。上限配置为 131,072 不意味着 workload 含有 128K 请求，图中的零桶正确保留；固定输出计数也不验证模型回答质量或 YaRN 外推数值正确性。图中的 160 不是五个 seed 合并后产生的新工作流数量。

**审查意见。** 三个面板的计数与原始 workload、绘图输入一致。图 5(b) 的横轴虽延伸到 27 calls，却只标了 5/10/15；建议补 20/25 或 27 的末端标注，便于读者看出长尾，不能将当前显示理解为只包含 15 calls 以下的任务。

追溯：[工作负载 manifest](workloads/fanoutqa-dev-qwen3-8b-160-manifest.json)、[实际绘图输入](results/paper/data/publication-figure-inputs.json)、[冻结 requests.json](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/configs/requests.json)、[论文实验方法](../paper/sections/experimental-method.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `workload()`。

<a id="figure-current-6"></a>

### G01-06 正文图 6：无故障保护开销

按 admission seed 配对的平均 WCT 差异与完整工作负载保护流量；单位分别为秒和 TiB。

`aligned-healthy` · [PNG](../paper/figures/aligned-healthy.png) · [SVG](../paper/figures/aligned-healthy.svg) · [PDF](../paper/figures/aligned-healthy.pdf)

![G01-06 正文图 6：无故障保护开销](../paper/figures/aligned-healthy.png)

**绘制背景。** 回答“即使没有故障，保护是否会拖慢工作流、搬运多少数据”。把健康时延差和实际复制流量分开，避免仅凭可重叠的模型时序宣称零资源成本。

**实验配置。** 使用共同配置的 base/F0，无故障；None、DRAM-only、Full 三策略，各 5 个 admission seed，共 **15 次完整 workload 执行**。每次 160 workflows、C=16，其他硬件、工作负载、routing seed 和调度假设一致。图 (a) 在每个 seed 内先取 160-workflow 平均 WCT，再计算 Full−control；图 (b) 是完整 workload 实际传输的 protection bytes，包括后来 abort 的复制已完成部分，单位 TiB。

**实际结果。** Full−DRAM 的健康平均 WCT 差为 **−0.077696 s**，95% CI **[−0.228503,+0.073110] s**；相对 None 的数据相同，因为这批 F0 控制时间相同。Full 流量均值约 **5,496.961 GiB（5.368 TiB）**，DRAM 约 **2,866.586 GiB（2.799 TiB）**，增加 **91.760%**。

**审查意见。** 这张图缺少 Mooncake 对照，不能回答完整 AegisKV 相对 Mooncake 的无故障开销。DRAM-only 是 AegisKV 关闭 Peer HBM 的内部消融，仍使用 AegisKV 的 DRAM 策略；它不等于 Mooncake。两个 WCT 区间都包含零，不能据此证明稳定加速；这也不是等效性或“开销≤1%”认证。大量流量可以在模拟中与计算重叠，且没有真实 controller/kernel 的全部成本。图保留五个 seed 的不同 marker，柱状/点的单位和图注吻合。

追溯：[配对统计与恢复明细](results/paper/data/aligned-statistics.json) 的 `healthy` / `endpoints.*.F0.protection_GiB`、[冻结实验协议](../../../output/paper-simulation-8b/20260906-alignment/campaign-v2/PROTOCOL.json)、[论文结果与图注](../paper/sections/results.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `healthy()`。

<a id="figure-current-6-redesign"></a>

**2026-09-08 更正：正文主对比是完整 AegisKV 与 Mooncake。** 此前把 Full 与 DRAM-only 的 W01/W02 推荐为正文主对比，选错了对照。DRAM-only 只关闭 AegisKV 的 Peer HBM 保护，保留改过的 DRAM 准入和淘汰策略；“only”限制的是这里的保护存储层，正常推理仍使用 GPU HBM。它只能帮助分析 AegisKV 内部增加 Peer HBM 后的变化，不能代表 Mooncake。

正文 WCT 图应使用同一实验版本、相同输入和入场顺序下的 **Mooncake 与完整 AegisKV**：一张独立图画两者的逐工作流 WCT CDF；另一张独立图按 workflow ID 配对，横轴为 Mooncake WCT、纵轴为 AegisKV WCT。图例直接写系统名称。其他独立图分别比较正常复用、前台显存与排队、CPU 决策成本和传输争用。运行间统计用于补充顺序敏感性。

**已有 Mooncake 数据的入口。** [历史无故障 v12 汇总](results/e2-qwen3-8b-no-failure-overhead-paper-v12/no-failure-overhead.json) 确实分别包含 `vanilla_mooncake_dram` 与 `aegiskv_unified`，不是将 DRAM-only 改名：两种系统 × 五种入场顺序，共十次完整执行，每对包含同一批 160 个工作流的 WCT。已核对汇总文件的 SHA-256 与其[图像清单](results/figures/qwen3-8b-no-failure-paper-v12/FIGURE_MANIFEST.json) 一致；对应图在[历史 v12 图组](#group-healthy-v12)。该数据绑定旧源码 `b10886754ed4890285d1320cbb5fe679a9979166`，证据字段为 `modeled/preliminary`、`not_calibrated`、`physical_execution=false`、`paper_ready=false`。这是历史 Mooncake 模型基线，不能与当前 campaign-v2 的 Full 配成比较，也不能作为 revision-3 或原生实机的结果。

**统一出图约定。** 每个文件只有一个坐标系，尺寸 3.45 inch × 3.2 inch，标签为 10.5 pt 或以上。主图中的曲线/圆点描述工作流，图例写策略名或 `Workflow`。一个 run 是固定一种策略和一个 seed，完整执行 160 个工作流、1,304 个请求的一次仿真；它是数据来源，不要求每张图都把它压缩成一个点。仅在下方补充图中保留 `Run`、`Paired sample` 与 `Mean (95% CI)`，分别表达单次汇总、同 seed 的策略汇总差和跨 seed 统计。图内保留坐标、单位与图例；配置、版本、解释和局限放进 LaTeX caption。

<a id="figure-current-6-workflow-view"></a>

**内部消融图 W01/W02，仅作工作流观察方式的示例。** 两张现有图没有 Mooncake，不能充当上述正文主对比。它们固定 admission seed 0、C=16，分别读取 None、DRAM-only、Full 的一次完整 F0 执行。这三次执行的工作流 ID 集合和实际入场顺序哈希相同。选择 seed 0 是取默认的第一个编号作为案例，不称其代表所有负载，也不根据收益挑选；全部五个顺序的逐工作流数据保留在 CSV 中。

数据与复现：[800 行配对工作流观察值](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-observations.csv) · [选择规则、逐 seed 汇总和输入哈希](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-review.json) · [工作流图生成器](scripts/paper/render_healthy_workflows.py)。800 行是同一批 160 个工作流在五种顺序下的观察，不是 800 个不同工作流或独立实验重复。脚本可通过 `--seed 0` 至 `--seed 4` 指定展示顺序，当前仅导出 seed 0 图稿。

**独立图 W01：一次匹配配置内的 WCT 分布。** [PNG](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-wct-cdf.png) · [SVG](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-wct-cdf.svg) · [PDF](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-wct-cdf.pdf)。

![W01 同一工作负载和入场顺序下的 WCT 分布](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-wct-cdf.png)

横轴为 workflow WCT，纵轴为 160 个工作流中 WCT 不超过该值的比例。每条经验 CDF 使用该策略单次执行中的全部 160 个 WCT，不先对它们求均值。None 与 DRAM-only 在这个案例中逐工作流时间完全相同，因此图例合并；Full 单独成线。这张图回答整体分布及尾部在哪里，不用五个 run 均值代替工作流分布。

W01 图注建议：*Workflow completion times for one matched no-failure workload execution per strategy (160 workflows, admission seed 0, C = 16). Each empirical CDF contains all workflow completion times from that execution. Unprotected and DRAM-only timings coincide. This descriptive example uses the uncalibrated legacy-policy simulator; admission-order sensitivity is reported separately.*

**独立图 W02：同一个工作流在两种策略下的 WCT。** [PNG](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-paired-wct.png) · [SVG](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-paired-wct.svg) · [PDF](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-paired-wct.pdf)。

![W02 按工作流 ID 匹配的 WCT 对比](../../../output/pdf/aegiskv-healthy-workflows-20260908/seed0/healthy-workflow-paired-wct.png)

**每个圆点是一个工作流。** 横轴是它在 DRAM-only 下的 WCT，纵轴是它在 Full 下的 WCT，按相同 workflow ID 配对。点在线上方表示 Full 更慢，下方表示更快，线上表示相同。这里保留了工作流身份；不能把两组 WCT 各自排序后再将相同名次配成一个点。

这个案例表明仅看均值或 CDF 仍会漏掉个体变化：seed 0 的平均 WCT 差只有 **+0.016587 s**，但 **32 个工作流变快、95 个相同、33 个变慢**。`6eabcceb8e365b7c` 从 **19.709 s 增至 61.428 s（+41.719 s）**；`fdc1b389c63ca222` 从 **56.063 s 降至 9.455 s（−46.608 s）**。正负变化会相互抵消，且两个系统的 CDF 可以接近，却由不同工作流承担长尾。因此“均值近零”不能替代工作流级的无干扰主张。

W02 图注建议：*Paired workflow completion times for the same admission-seed-0 example. Each point matches one workflow ID across DRAM-only and Full executions. Points above the equality line take longer under Full. The near-zero mean difference and similar marginal distributions conceal substantial changes for individual workflows. These observations do not isolate the causal contribution of memory pressure, routing, or transfer contention.*

**多个 run 的作用。** 绘图单位与重复单位可以不同。正文用工作流、请求或时间序列呈现机制；重复执行用于检查同一结论是否依赖输入顺序、负载条件或实机噪声。本例五个 seed 改变的是入场顺序，并非把完全相同的确定性仿真机械重复五遍。如果实现和全部输入固定且输出完全确定，原样重复确实不增加结果信息。

| 入场顺序 | Full 更快的工作流 | 时间相同 | Full 更慢的工作流 | 平均 WCT 差 Full−DRAM | 单个工作流最大增加 |
|---|---:|---:|---:|---:|---:|
| seed 0 | 32 | 95 | 33 | +0.016587 s | +41.718714 s |
| seed 1 | 6 | 153 | 1 | −0.004070 s | +0.003532 s |
| seed 2 | 3 | 154 | 3 | 0 s | +0.325613 s |
| seed 3 | 22 | 107 | 31 | −0.265682 s | +20.149596 s |
| seed 4 | 75 | 28 | 57 | −0.135315 s | +39.545784 s |

计数依据整数纳秒差的严格正负，包含很小的变化，不代表每个变化都有实际重要性。此表表明顺序敏感性本身是有效信息，但不要求在主图把 run 当成主要观察对象。单次执行中的 160 个工作流共享调度和内存资源，不能将它们直接当作 160 次独立系统实验来计算很窄的置信区间。

对于后续机制图，同样优先采用与问题匹配的观察粒度：reuse 用请求/唯一 token，排队用逐请求等待分布，HBM 用每 GPU 的时间序列，准入成本用逐决策计时，带宽用每条链路的时间窗口。多次执行在相同口径下提供误差条或补充表，不替代这些内部信息。

<details>
<summary>运行间汇总与资源诊断补充：H01–H04</summary>

本轮复用原来 **三策略 × 五个 seed = 15 次 F0 完整仿真**。所有新图仍是旧 SlackLandlord/HBMQuotaAIMD 的未校准 GlobalDES 结果。数据与复现：[逐 seed CSV](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-mechanism-observations.csv) · [完整统计、定义、缺项及输入哈希](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-standalone-review.json) · [独立图生成器](scripts/paper/render_healthy_standalone.py)。

**独立图 H01：无故障服务影响。** [PNG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-service-impact.png) · [SVG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-service-impact.svg) · [PDF](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-service-impact.pdf)。

![H01 无故障服务影响，独立图](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-service-impact.png)

三行依次为 Mean WCT、P95 WCT、Workload makespan，横轴为 Full 相对未保护的变化百分比，正值表示更慢，零处画虚线。每个 admission seed 先计算一次相对变化，再跨五个 seed 求均值与双侧 95% Student-t 区间：

$$
\delta_{s,m}=100\frac{M_{s,\mathrm{Full},m}-M_{s,\mathrm{None},m}}{M_{s,\mathrm{None},m}},\qquad s\in\{0,1,2,3,4\}.
$$

这里的 $M$ 是该次运行的相应指标。Mean/P95 WCT 分别由每次 160 个 workflow 求出，P95 沿用冻结协议的 nearest-rank 定义；makespan 是 `metrics.workload_end_ns`。DRAM-only 在这批执行中的三个时间指标均与 None 相同，因此 H01 的 Full−None 对比也等于 Full−DRAM；这个事实写在图注中。

| Full 相对 None | 五个配对百分比的均值 | 95% t 区间 | 补充这个指标的原因 |
|---|---:|---:|---|
| 平均 WCT | −0.182% | [−0.537%, +0.172%] | 整体工作流完成时延；未保护的跨 seed 平均值为 41.565 s。 |
| P95 WCT | −0.342% | [−1.197%, +0.512%] | 检查尾部；平均 WCT 的变化不能代替尾部变化。 |
| 完整 workload makespan | −0.074% | [−0.851%, +0.703%] | WCT 排除了入场 slot 等待，整批完成时间补充反映闭环处理效率。 |

这些是 **先配对归一化、后求均值** 的结果，不是跨 seed 总均值之比；不能直接把原图秒数 CI 除以一个统一基线来替代。新增指标属于本次探索性重审，未调整多重比较，也不将 5 × 160 个 WCT 当作 800 个独立重复。比如 seed 0 的整批完成时间增加 **0.648%**，这个正向开销点应保留。

H01 图注建议：*Healthy service impact in the uncalibrated, legacy-policy GlobalDES model (160 FanOutQA workflows, C = 16). Percentage changes are computed within five paired admission orders before aggregation. Positive values indicate slowdown. Open circles show individual orders; diamonds and whiskers show means and 95% Student-t intervals. DRAM-only has the same timing endpoints as unprotected execution in these runs. All three intervals include zero.*

**独立图 H02：实际复制流量。** [PNG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-protection-traffic.png) · [SVG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-protection-traffic.svg) · [PDF](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-protection-traffic.pdf)。

![H02 实际复制流量，独立图](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-protection-traffic.png)

用 DRAM-only、Full 两根堆叠柱，纵轴从零开始。DRAM 与 Peer HBM 写入采用不同颜色和纹理，并用图例明确区分。柱高及各分段是五次运行均值；空心圆为每次运行的总流量，菱形和误差线对应总流量均值及区间。None 的流量为零，说明放在图注。

| 策略 | DRAM 写入均值 | Peer HBM 写入均值 | 合计均值 |
|---|---:|---:|---:|
| None | 0 TiB | 0 TiB | 0 TiB |
| DRAM-only | 2.799 TiB | 0 TiB | 2.799 TiB |
| Full | 2.783 TiB | 2.585 TiB | 5.368 TiB |

分段来自各 run summary 的 `metrics.resource_cost.cause_bytes.AEGIS_STORE_DRAM_PROTECTION` 和 `AEGIS_PEER_HBM_PROTECTION`，逐 seed 之和与原图总流量一致。Full 的 DRAM 部分也会随调度改变，所以不能把 `Full 总量 − DRAM-only 总量` 直接当作 HBM 流量。这里的 **+91.8%** 是两组总流量均值之比减一；统计的是实际传输字节，包括后来 abort 的复制已经搬运的部分，既不是峰值驻留容量，也不是链路利用率。

H02 图注建议：*Protection traffic per complete workload in the same no-failure legacy-policy simulation. Stacks show the mean actual bytes transferred to DRAM and Peer HBM. Open circles and interval markers summarize total traffic over five paired admission orders. Unprotected execution transfers zero protection bytes. Traffic includes bytes moved by copies that are later aborted; TiB denotes 2^40 bytes.*

<a id="figure-current-6-mechanism-audit"></a>

**独立诊断图 H03：请求开始计算前的等待。** [PNG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-request-start-wait.png) · [SVG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-request-start-wait.svg) · [PDF](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-request-start-wait.pdf)。

![H03 请求开始计算前的等待，独立图](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-request-start-wait.png)

每个请求计算 `compute_start_ns − released_ns`；每次运行先对 1,304 个请求求均值或 nearest-rank P95，再按 seed 计算 Full−DRAM。正值表示 Full 等待更久。均值差为 **+0.015250 s，95% CI [−0.095837,+0.126337] s**；P95 差为 **+0.295288 s，95% CI [−0.296149,+0.886724] s**。

这张图补出了 WCT 汇总隐藏的变化：seed 3 的平均 WCT 减少约 0.266 s，但请求开始前 P95 等待增加 **1.047551 s**；seed 4 的 P95 等待增加 **0.492099 s**。两个跨 seed 区间仍包含零。这是请求 release 到首次 forward 的前置等待，不是 TTFT、纯 HBM 分配阻塞或 workflow 入场 slot 等待，也不能仅凭这一差值将原因全部归到 Peer HBM。

源码会在重计算时覆盖 `compute_start_ns`；本次逐请求检查了 F0 的 route version 为 0、recompute tokens 为 0、prompt recompute start 为空，才使用它作为首次计算时间。定义见[冻结调度回调](../../../output/paper-simulation-8b/20260906-alignment/source-v2/python/moonkvsim/aegiskv/experiment.py#L3719)。

H03 图注建议：*Change in pre-compute waiting under the legacy-policy no-failure simulation. Waiting spans request release to its first forward step. Mean and P95 are computed over 1,304 requests within each run, followed by a paired Full-minus-DRAM-only contrast across five admission orders. Positive values indicate longer waiting. This observable combines pre-compute scheduling delays and does not isolate memory-allocation stalls or measure TTFT.*

**独立诊断图 H04：Peer HBM 的时间平均占用。** [PNG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-peer-hbm-footprint.png) · [SVG](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-peer-hbm-footprint.svg) · [PDF](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-peer-hbm-footprint.pdf)。

![H04 Peer HBM 的时间平均占用，独立图](../../../output/pdf/aegiskv-healthy-standalone-20260908/healthy-peer-hbm-footprint.png)

每次运行的纵轴为 `peer_hbm_byte_ns / workload_end_ns / 2^30`，表示 **8 张 GPU 合计、包含 committed 与 pending 的保护占用时间平均值**。Full 五个 seed 分别为 **23.121、23.187、22.956、21.406、23.152 GiB**，均值 **22.764 GiB**，95% CI **[21.815,23.714] GiB**；None 和 DRAM-only 无 Peer HBM 占用。

这证明该策略会实际占用前台共用的 HBM 容量，但不单独证明前台已受损。不能把集群总量标成“每 GPU”，也不能把时间平均值写成容量上限。另有 `peer_hbm_peak_bytes` 可报告 committed 峰值，但它不包含 pending，与这里的账本口径不同，不在同一图中伪装为同一指标的 mean/peak。积分定义见[冻结池账本](../../../output/paper-simulation-8b/20260906-alignment/source-v2/python/moonkvsim/aegiskv/experiment.py#L1050)。

H04 图注建议：*Time-averaged Peer-HBM protection footprint in the legacy-policy no-failure simulation, summed over eight GPUs. The integral includes both committed and pending copies and is normalized by complete-workload duration. Open circles show five runs; diamonds and whiskers show means and 95% Student-t intervals. Footprint alone does not quantify foreground memory stalls.*

</details>

**现有数据中容易误读的四项。**

| 项目 | 本次核查结果 | 可用范围与缺项 |
|---|---|---|
| Mooncake 对照 | 当前 campaign 的六个 arms 是 None、AegisKV DRAM-only、Full 和三个消融；历史 v12 另有独立 Mooncake 模型对照。 | 当前 campaign 缺 Mooncake；`mooncake_aligned_paper` 是套件名，不能据此把 DRAM-only 改名为 Mooncake，也不能跨版本拼接历史基线。[runner](scripts/run_mooncake_aligned_paper.py#L21) |
| 正常 KV reuse | 15 份摘要的 normal HBM、Peer HBM、DRAM 复用 tokens 全为 0，逐请求字段也一致。 | 当前运行没有形成可分析的非零正常复用。即使按总 prompt tokens 定义得到零命中率，也不能用这组全零结果说明准入策略不影响 reuse；需要有明确重复前缀及再访问的输入和公平对照。故障恢复 tokens 要另计。 |
| HBM 压力计数 | Full 的 `hbm_pressure_observation_count` 为 30、21、8、12、10。 | 采样函数在 AIMD 未启用时直接返回，None/DRAM-only 的零并非同等插桩下测得的零压力。该计数可解释 Full 控制器行为，不能做跨策略压力柱状图。[采样条件](../../../output/paper-simulation-8b/20260906-alignment/source-v2/python/moonkvsim/aegiskv/experiment.py#L5640) |
| CPU / 带宽成本 | 有模拟器 `wall_seconds`、按 transfer cause 的等待/服务时长，以及模型资源忙时。 | `wall_seconds` 包含模拟、序列化与审计；transfer queue wait 是复制事务等待；busy time 按 cause 和多个资源累计。这些分别不能充当 serving CPU 开销、前台请求排队或单链路利用率。[计时范围](scripts/run_mooncake_aligned_paper.py#L130) · [传输聚合口径](../../../output/paper-simulation-8b/20260906-alignment/source-v2/python/moonkvsim/aegiskv/experiment.py#L14568) |

<a id="figure-current-6-mechanism-plan"></a>

**AegisKV 对比 Mooncake：应补的机制实验。** 以下是待实施的实验设计，未把它当作本次新增测量。正文各项先比较 M 与 F；D 与 H 作为补充消融，用于解释 DRAM 准入变化与 Peer HBM 变化各自的影响：

| 配置 | DRAM 准入/淘汰 | Peer HBM | 比较用途 |
|---|---|---|---|
| M：原生 Mooncake | 固定版本的原有策略 | 关闭 | 完整系统比较的外部基线；正常 KV reuse 保持开启。 |
| D：AegisKV DRAM-only | AegisKV 策略 | 关闭 | D−M 隔离 DRAM 策略变化。 |
| H：Mooncake-DRAM + Peer HBM | 保留 Mooncake 原有策略 | 开启，与 Full 相同的 Peer 控制 | H−M 检查原 DRAM 策略下增加 Peer 的影响；这是需要实现的消融配置。 |
| F：完整 AegisKV | AegisKV 策略 | 开启 | F−D 检查 Peer 的增量影响；F−M 回答整体比较；四配置还能检查两种改动的交互。 |

各配置共用 serving engine、模型、GPU/DRAM 容量、CPU 核数、传输路径、输入 token、可复用对象身份与 scope、批处理/路由设置和初始缓存状态。先固定实现版本及 feature flags，再冻结负载和实验协议。四配置不能直接用现有旧算法 CSV 冒充。仓库的[Mooncake 源码参考](../../../reference/mooncake-store-notes.md) 锁定了 `f161118c18dbea1b56dd5c7908b9eaa440353e2e`，但同时记录了模拟 Store 的容量压力/淘汰时序替代，源码参考并不等于已有原生性能基线。

**问题一：DRAM 准入是否损害正常 KV reuse？** 主图应画“token 命中率—缓存容量/工作集比例”曲线；在一个固定的共享前缀与再访问分布下，横轴改变 DRAM 容量，Mooncake 与完整 AegisKV 分别成线。D、H 的结果放到补充消融图中。另用独立图分析 reuse distance 或请求级命中率，避免把多个不同横轴塞到同一图。

- 主指标为 **实际从缓存服务的唯一 prefix tokens / 所有请求的 prompt tokens**；同时报告命中请求比例以及 DRAM lookup 的条件命中率。明确每个分母：全请求命中率与“到达 DRAM 查询阶段的命中率”不能互换。
- token 按实际服务来源归入 local HBM、Peer HBM 或 DRAM；同一 token 即使有两份备份，也只计一次。额外记录准入拒绝、容量淘汰、过期/生命周期清理、后续 miss、重复 put，以及预填充 token/时间，说明命中率变化来自哪里。
- 输入需要保留真实的共享前缀、分支再访问、复用间隔与工作集变化；明确 hash/salt、租户隔离、TTL 和对象生命周期，检查这些规则是否提前阻断跨请求复用。冷启动阶段与固定 warm-up 后的稳态阶段分开报告。全零 reuse 的负载不足以比较复用策略。
- 首先比较 F−M，检查整体正常复用是否变化；再用 D−M 分析 DRAM 策略的影响，并检查 F 是否将原本的 DRAM hit 转移到 Peer HBM。只看 DRAM hit 下降可能把层间迁移误判为整体缓存退化；结合总 token hit、TTFT 和预填充工作量判断。

**问题二：Peer HBM 是否挤占前台容量并增加排队？** 至少需要“HBM 占用构成”和“前台等待”两张独立图，横轴采用相同的请求到达率或并发数；负载覆盖轻载至接近饱和。若研究排队，优先用固定的开放式到达 trace，并在所有配置上保留相同到达时刻，避免闭环完成后补任务把压力差异隐藏起来。

- HBM 账本按 GPU 记录权重、运行时保留、active primary KV、inactive reusable KV、committed/pending 保护副本、staging 与 free。共享物理块按所有权/别名规则计一次；峰值不能由各项不同时间的峰值相加。报告最紧张的 donor GPU，不能只用集群均值掩盖局部耗尽。
- 统一在所有配置记录请求到达、进入队列、首次尝试分配、分配成功、首次 forward、首 token 与完成时间；分配阻塞、调度等待、preemption/recompute、HBM reclaim 及拒绝次数使用相同 hook。展示 P95/P99 前台等待、TTFT/TPOT 与 SLO 达标吞吐，指标过多时分别出图。
- F−M 衡量完整系统的显存占用和等待变化，F−D 补充分析新增 Peer 的影响；再在固定 HBM 占用的条件下切换后台 DMA，或做匹配 footprint 的 reserve-only 控制，以区分容量挤占与搬运争用。H03/H04 目前只提供旧模型中的总等待和占用观察，尚未完成这种原因分解。

**问题三：准入计算、CPU 和带宽争用花了多少成本？** CPU 与通信使用各自的独立图及量纲。

- **CPU 整体开销图：** 横轴请求到达率，纵轴服务进程合计 CPU core-seconds/request，或平均占用核数 `sum(user + system CPU seconds) / elapsed seconds`。统计 serving worker、控制器/Master、client 与 transfer-progress 线程；固定 CPU 配额、亲和性、NUMA、线程数和 warm-up。进程墙钟时间不能替代 CPU 时间。
- **准入计算图：** 记录每次准入的 CPU 时间/耗时，按特征构建、预测、候选评分、受害者选择、元数据同步分解；以实际候选数量为横轴，或单独画延迟分布，报告调用次数和尾部。微测可重放冻结的决策输入，但其结果要与真实 serving 路径的整体 CPU 开销分别陈述。
- **带宽争用图：** 固定前台请求流、DMA buffer/HBM 占用与路径，扫描后台保护搬运负载；画前台有效带宽或前台传输 P95 延迟随后台负载的变化。按实际链路记录 foreground/background 字节、等待、完成及忙时，区分同机 PCIe/P2P 与跨机网络。另报告 TTFT/TPOT 或 SLO goodput，说明链路争用是否传到服务层。
- 单链路利用率使用该链路在测量窗口内的实际传输量及有效容量，或该资源忙区间的并集。不能把多个 GPU 的 busy time、不同 cause 的重叠区间相加后，除以一次运行时长标成百分比；不能用 5.368 TiB 总量直接推断带宽拥塞。

**待补图与当前证据的对应关系。** 所有条目均独立导出，最后在 LaTeX 中选择正文组合。

| 图的用途 | 横轴 | 纵轴 | 对照重点 | 当前状态 |
|---|---|---|---|---|
| 正常 reuse 是否退化 | DRAM 容量/工作集 | token 命中率 | F−M；D−M 补充归因 | 当前 campaign 缺 M、有效再访问与 lookup 记录。 |
| 显存资源被谁占用 | 负载；或预先选定窗口的时间 | 每 GPU 物理账户占用 | F−M；F−D 补充归因 | 已有 H04 的集群时间平均占用；完整时序归因待补。 |
| 前台等待是否变差 | 负载 | P95 等待/TTFT | F−M，统一插桩 | 已有 H03 单一 C=16 的内部消融前置等待；分配阻塞归因待补。 |
| CPU 整体负担 | 请求到达率 | CPU core-seconds/request | F−M；D、H 补充归因 | 当前无对应 native CPU 测量。 |
| 准入算法自身代价 | 候选数；或延迟分布横轴 | CPU 时间；或 CDF | Mooncake 原策略与 AegisKV | 当前只有决策事件，缺真实计时。 |
| 保护传输是否抢带宽 | 后台复制负载 | 前台带宽或 P95 传输时延 | F−M；匹配 HBM 占用后补充归因 | 当前只有总字节及模型资源时间。 |

每个比较点先冻结 workload、指标、重复单位与 SLO，再按独立运行/请求到达顺序配对。记录全部运行，并对系统执行顺序做随机化以控制实机漂移。样本数应由试验方差和关注的最小效应决定；现有五个 seed 不自动满足新实验的精度需求。事件级或请求级数据用于机制分析，不能直接冒充独立运行重复来缩窄区间。

**本次完成与边界。** 已把正文主比较更正为 Mooncake 与完整 AegisKV；现有 W01/W02 属于内部消融，H01–H04 是对应的运行汇总及资源诊断，均不能替代 Mooncake 主对比。已核对全部 800 行工作流配对、15 行逐 seed/策略机制数据、冻结源码中的指标定义以及原有 60 个时间/流量值，并补充历史 v12 的独立 Mooncake 配对数据入口。本次更正没有产生新的主对比图或运行数据。[当前 revision-3 状态](../docs/paper/REVISION_STATUS.json) 仍记录 workload runs 为 0、native/full-DES 集成未完成；上述新实验应在对应实现固定后执行。新增图和分解计划都不能替代这些待补结果。

<details>
<summary>已替代的双面板候选，仅供版本追溯</summary>

此前的合图：[PNG](../../../output/pdf/aegiskv-healthy-review-20260908/healthy-service-traffic-candidate.png) · [SVG](../../../output/pdf/aegiskv-healthy-review-20260908/healthy-service-traffic-candidate.svg) · [PDF](../../../output/pdf/aegiskv-healthy-review-20260908/healthy-service-traffic-candidate.pdf) · [当时的数据与哈希](../../../output/pdf/aegiskv-healthy-review-20260908/healthy-service-traffic-candidate.json) · [原生成器](scripts/paper/render_healthy_review.py)。其内部消融的独立导出见上面的 H01/H02。

![已替代的 G01-06 双面板候选](../../../output/pdf/aegiskv-healthy-review-20260908/healthy-service-traffic-candidate.png)

</details>

<a id="figure-current-7"></a>

### G01-07 正文图 7：故障对完整工作流的影响

WCT ECDF 与各策略自身 F0 校正后的 F1 故障罚时；区分整体工作流和预选 focus 工作流。

`aligned-failure` · [PNG](../paper/figures/aligned-failure.png) · [SVG](../paper/figures/aligned-failure.svg) · [PDF](../paper/figures/aligned-failure.pdf)

![G01-07 正文图 7：故障对完整工作流的影响](../paper/figures/aligned-failure.png)

**绘制背景。** 检查故障后完整 workflow 是否受益，并把每种策略本身的健康基线扣掉，使“更早完成”不被直接等同于“更好地抵御故障”。

**实验配置。** base 点三策略 None/DRAM/Full，F0 与**一次故障** F1，各 5 seeds，共 **30 次执行**。图 (a) 每条 ECDF 汇合该策略 5 个 F1 运行×160 workflows=800 个描述性 task-runs，依然只有 5 个配对 admission order。图 (b) 对整体 mean WCT、图 (c) 对预选 focus workflow，计算 `(Full_F1-Full_F0) - (Control_F1-Control_F0)`，负值有利于 Full。

**实际结果。** 相对 DRAM，整体平均故障罚时差 **+0.031571 s**，95% CI **[−0.159076,+0.222218] s**；focus 差 **+1.661373 s**，区间 **[−2.931194,+6.253941] s**。相对 None，整体差 **−0.201230 s**，区间 **[−0.669281,+0.266822] s**。曲线高度重叠与这些不确定区间一致。

**审查意见。** 这组结果没有确定跨 admission order 的稳定 WCT 优势。800 个点不能当作 800 次独立重复。故障是配对逻辑请求/60% 进度；不同策略的实际注入时间和连带受害者可以不同，不能描述为完全相同的 wall-clock 冲击。PDF 第 10 页的右面板标题完整，没有在图像边界处被截掉。

追溯：[实际绘图输入](results/paper/data/publication-figure-inputs.json) 的 `failure_wct_s`、[配对统计与恢复明细](results/paper/data/aligned-statistics.json) 的 `primary`、[冻结实验协议](../../../output/paper-simulation-8b/20260906-alignment/campaign-v2/PROTOCOL.json)、[论文结果与图注](../paper/sections/results.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `failure()`。

<a id="figure-current-8"></a>

### G01-08 正文图 8：恢复来源与完成时间

五个预选 focus 请求的 HBM/DRAM/重算份额、prefix-ready 时间及工作流罚时；恢复准备更快不保证工作流更快。

`aligned-recovery` · [PNG](../paper/figures/aligned-recovery.png) · [SVG](../paper/figures/aligned-recovery.svg) · [PDF](../paper/figures/aligned-recovery.pdf)

![G01-08 正文图 8：恢复来源与完成时间](../paper/figures/aligned-recovery.png)

**绘制背景。** 把“用了哪层 KV”“多久准备好恢复前缀”“完整工作流最后如何”连接起来，检查局部恢复收益能否传到 WCT。

**实验配置。** base/F1 中 DRAM 与 Full 的 5 对预选 focus 请求，共 **10 个 F1 请求观测**；右图还使用对应 **10 次 F0** 的 focus WCT 作罚时校正，这些均重用同一 campaign。左图按 HBM copy、DRAM load、prompt 重算分解，每个请求三部分总和等于其完整 prompt；中图时间从故障到 prefix-ready，含排队与准备；右图横轴为 DRAM−Full 的 prefix-ready 时间，纵轴为 Full−DRAM 的 F0 校正后 WCT 罚时。

| seed | DRAM 的恢复 tokens（HBM/DRAM） | Full 的恢复 tokens（HBM/DRAM） | prefix-ready 节省（s） | focus WCT 罚时差（s） |
|---|---:|---:|---:|---:|
| 0 | 0 / 36,864 | 36,864 / 0 | +0.711340 | +0.029060 |
| 1 | 0 / 40,960 | 0 / 40,960 | 0 | 0 |
| 2 | 0 / 36,864 | 36,864 / 0 | +0.023782 | 0 |
| 3 | 0 / 40,960 | 28,672 / 12,288 | 0 | 0 |
| 4 | 0 / 36,864 | 32,768 / 0 | +1.966684 | +8.277806 |

**实际含义。** seed 0 用 HBM 替代相同长度的 DRAM 前缀，准备早约 0.711 s，但工作流罚时仍增加约 0.029 s。seed 4 恢复前缀更短、prompt 重算多 4,096 tokens，prefix-ready 却早约 1.967 s；最终 workflow 罚时增加约 8.278 s。原结果记录的分支竞争/最终 join 说明，prefix-ready saving 不是 WCT saving。

**审查意见。** 五个 focus 均保留，包括纯 DRAM、混合来源和不利结果；没有拟合线，也没有把重叠阶段拼成互斥耗时栈。source fractions 不表示额外的独立 token 副本收益。版面上首面板纵轴标签偏靠左：PDF 提取文字框 x_min≈−0.50 pt，但现有 PNG/PDF 页面中未见字形被明显截断；建议下一次重绘增加左留白。

追溯：[配对统计与恢复明细](results/paper/data/aligned-statistics.json) 的 `focus_recovery` / `primary.dram.focus` / `focus_workflow_traces`、[论文结果与图注](../paper/sections/results.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `recovery()`。

<a id="figure-current-9"></a>

### G01-09 正文图 9：策略消融

Slack、固定配额和 LRU 的整体/focus 故障罚时及健康复制流量；流量差异不等同于 WCT 收益。

`aligned-ablations` · [PNG](../paper/figures/aligned-ablations.png) · [SVG](../paper/figures/aligned-ablations.svg) · [PDF](../paper/figures/aligned-ablations.pdf)

![G01-09 正文图 9：策略消融](../paper/figures/aligned-ablations.png)

**绘制背景。** 检查旧策略的 Slack 信号、配额调节和保留规则分别改变了什么，避免只有 Full 与单一 baseline 的总体比较。

**实验配置。** base/C=16，Full 与三个消融 arm，F0/一次故障 F1，5 seeds，共 **40 次执行**。图中 Slack=将 Slack 信号置零，AIMD=禁用调节并固定初始 alpha=0.2，LRU=用 LRU 替换旧保留策略；其余 request ownership、candidate 范围、复制/提交与 cleanup 语义相同。前两图比较 `(Ablation_F1-Ablation_F0) - (Full_F1-Full_F0)`，右图比较健康 `Ablation-Full` 实际复制流量；**正值**有利于 Full，与图 7/10 的正负方向不同。

**实际结果。** 六个整体/focus 延迟区间都包含零；zero-Slack 的 focus 五个差值全部为零，区间退化为 [0,0]。健康流量均值：Full **5,496.961 GiB**，无 Slack **6,872.907 GiB**，固定配额 **5,107.286 GiB**，LRU **7,174.981 GiB**。因此旧 Slack/保留策略影响流量，但当前不能证明其不可替代的 WCT 收益；固定配额还出现较低流量，需保留。

**审查意见。** “Slack”“AIMD”“LRU”分别表示置零、固定和替换，不是三个完整外部系统。论文 caption 已解释这些处理。这里没有消融 revision-3 PrefixAdmission/ForegroundBudget，也没有实测 predictor 的准确率影响，不能拿它验证新算法收益。

追溯：[冻结 campaign runner](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/scripts/run_mooncake_aligned_paper.py) 的 `variant()`、[配对统计与恢复明细](results/paper/data/aligned-statistics.json) 的 `ablations` / `endpoints`、[论文实验方法](../paper/sections/experimental-method.tex)、[论文结果与图注](../paper/sections/results.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `ablations()`。

<a id="figure-current-10"></a>

### G01-10 正文图 10：敏感性

并发、批次服务组成、路径带宽和故障次数的配对比较；当前修订图保留全部 seed、均值与探索性区间。

`aligned-sensitivity` · [PNG](../paper/figures/aligned-sensitivity.png) · [SVG](../paper/figures/aligned-sensitivity.svg) · [PDF](../paper/figures/aligned-sensitivity.pdf)

![G01-10 正文图 10：敏感性](../paper/figures/aligned-sensitivity.png)

**绘制背景。** 检查旧策略的结论是否依赖闭环并发、服务时序假设、传输速率和故障压力。使用同一有限 workload，逐项改变一个主要设置。

**实验配置。** 全部点比较 DRAM 与 Full，admission seeds 0–4；下表的数值由冻结协议和 runner 的 `POINTS` 决定。

| 图中一行 | C | 批次序列化 beta | Peer / Store 速率 | 故障次数 |
|---|---:|---:|---:|---:|
| Base | 16 | 0 | 25 / 25 GB/s | 1 |
| C=8 | 8 | 0 | 25 / 25 GB/s | 1 |
| C=32 | 32 | 0 | 25 / 25 GB/s | 1 |
| Serial mix 0.5 | 16 | 0.5 | 25 / 25 GB/s | 1 |
| Serial mix 1 | 16 | 1 | 25 / 25 GB/s | 1 |
| Path 5 GB/s | 16 | 0 | 5 / 5 GB/s | 1 |
| Two faults | 16 | 0 | 25 / 25 GB/s | 2 |

六个单故障点各有 2 arms×F0/F1×5 seeds=20 次执行；双故障点只有 10 次 F1 并复用 base 的 10 次 F0，因此这张图合计引用 **130 个不同执行输出**，属于 170-run campaign 的子集。服务/带宽点重用 base 故障计划；C=8/32 和 two-faults 各有自身 reference 计划。

**读法与结果。** 左右面板分别是整体平均与 focus 的 `Full-DRAM` 故障罚时差，负值有利于 Full；两边横轴尺度不同，不能直接比较横线画出的长度。七设置×两总体的 **14 个区间全部包含零**。例如 5 GB/s 的 focus 均值为 **−2.239339 s**，95% CI **[−12.888639,+8.409960] s**；two-faults 的整体均值为 **+0.045706 s**，区间 **[−0.249220,+0.340632] s**。

**审查意见。** 图保留零线、所有 seed 和不利方向，但只能说明对未校准假设的条件性敏感性；不是物理带宽测试，也不是长期随机故障率研究。Two faults 的请求计划与 base 不同，不能只凭该行和 base 的差异宣称故障越多收益越高。

追溯：[冻结实验协议](../../../output/paper-simulation-8b/20260906-alignment/campaign-v2/PROTOCOL.json) 的 `points/jobs`、[冻结 campaign runner](../../../output/paper-simulation-8b/20260906-alignment/source-v2/benchmark/AegisKV/experiments/scripts/run_mooncake_aligned_paper.py) 的 `params()/plan_key()`、[配对统计与恢复明细](results/paper/data/aligned-statistics.json) 的 `sensitivity`、[论文结果与图注](../paper/sections/results.tex)；绘制见 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `sensitivity()`。

<a id="figure-current-11"></a>

### G01-11 Motivation 子图：观测分支时长差

每个合格 workflow 取一个严格并行分支的最大时长差，单位为秒；这是时长差，不是最长/最短比值。

`observed-gap` · [PNG](../paper/figures/motivation-panels/observed-gap.png) · [SVG](../paper/figures/motivation-panels/observed-gap.svg) · [PDF](../paper/figures/motivation-panels/observed-gap.pdf)

![G01-11 Motivation 子图：观测分支时长差](../paper/figures/motivation-panels/observed-gap.png)

**子图背景与配置。** 这是正文图 1(a) 的独立导出，复用同一份 124-workflow gap CSV，规则为 `max_start < min_end` 的严格共同重叠，每个 workflow 取最大分支时长差；对数横轴、ECDF 和 50%/90% 标记与组合图一致。

**审查意见。** 已查看独立 PNG；它没有增加新的 trace 样本或实验次数。读者只能据此了解该筛选总体的观测分支差异，不能把它解释为 GBDT 准确率、全部 workflow 的可用 Slack 或 AegisKV 故障收益。

追溯：[124-workflow gap CSV](results/paper/data/motivation-real-cc/real-cc-workflow-parallel-gap.csv)、[trace 重建记录](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)；生成器为 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `motivation_panels()`。

<a id="figure-current-12"></a>

### G01-12 Motivation 子图：具体工作流与 Slack

按 trace 起止时间绘制分支与到推断 join 的剩余时间；依赖关系含重建假设。

`motivation-workflow` · [PNG](../paper/figures/motivation-workflow.png) · [PDF](../paper/figures/motivation-workflow.pdf) · [原生导出 PNG](../paper/figures/motivation-workflow.native.png) · [原生导出 PDF](../paper/figures/motivation-workflow.native.pdf) · [Draw.io 源](../paper/figures/motivation-workflow.drawio)

![G01-12 Motivation 子图：具体工作流与 Slack](../paper/figures/motivation-workflow.png)

**子图背景与配置。** 这是正文图 1(b) 的独立导出，展示 workflow `8ab0a0892b0035b681a85c71d603caeb9e0f` 的五个分支。join 为 trace 起点后 433.812 s；A1–A5 的剩余 join Slack 分别约 27.226、17.174、52.447、0、10.783 s，故障参考线统一在 349.5 s。

**审查意见。** 已核对独立图的分支排序、时间比例、Slack 和故障线。实线是观测执行区间，虚线是到推断 join 的剩余时间；不是在这张时间线上重新执行了故障，也没有五个新的独立 workload。对应 Draw.io 源和 native 导出保留在上方链接中。

追溯：[五分支与反事实 CSV](results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv)、[trace 重建记录](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)、[机制图生成器](scripts/paper/build_submission_diagrams.py)。

<a id="figure-current-13"></a>

### G01-13 Motivation 子图：吸收与暴露的恢复延迟

冻结的 AIConfigurator 反事实分解；不代表在原 trace 上实测故障，也不是 Qwen3-8B 模拟结果。

`modeled-harm` · [PNG](../paper/figures/motivation-panels/modeled-harm.png) · [SVG](../paper/figures/motivation-panels/modeled-harm.svg) · [PDF](../paper/figures/motivation-panels/modeled-harm.pdf)

![G01-13 Motivation 子图：吸收与暴露的恢复延迟](../paper/figures/motivation-panels/modeled-harm.png)

**子图背景与配置。** 这是正文图 1(c) 的独立导出，使用相同五分支、349.5 s 故障位置，以及 Qwen3-235B-A22B / A100-80GB / TP8/PP4/EP8 的冻结重算预测。总条长为模型 `recompute_s`；红色为 `max(recompute_s-slack_s,0)`，绿色为剩余被吸收部分。

**审查意见。** 独立图的每条分解与 CSV 算术一致，条尾数字标注的是暴露秒数，不是总重算秒数。它与正文图 1(c) 是同一份模型示例，不增加硬件测量次数，也不能冒充 Qwen3-8B 的物理恢复时间。

追溯：[五分支与反事实 CSV](results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv)、[trace 重建记录](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)；生成器为 [定量图生成器](scripts/paper/render_submission_figures.py) 的 `motivation_panels()`。

<a id="group-figure1"></a>

## 历史 Qwen3-8B：Figure 1 工作负载与干预

<details>
<summary>展开本组图像与文件链接（4 条记录）</summary>

旧版 Figure 1 的四个独立面板。manifest 声明 modeled_uncalibrated=true、physical_execution=false、paper_ready=false；不替代当前正文图号。

目录：[experiments/results/figures/qwen3-8b-figure1-v1](results/figures/qwen3-8b-figure1-v1)。

来源：[图像与输入绑定](results/figures/qwen3-8b-figure1-v1/FIGURE_MANIFEST.json) · [工作负载及干预证据](results/qwen3-8b-figure1-evidence-v1.json) · [生成器](results/figures/generate_qwen3_8b_figure1.py)。

<a id="figure-figure1-1"></a>

### G02-01 Figure 1A：prompt token ECDF

冻结工作负载的 prompt 长度分布。

`figure_1a_prompt_token_ecdf` · [PNG](results/figures/qwen3-8b-figure1-v1/figure_1a_prompt_token_ecdf.png) · [SVG](results/figures/qwen3-8b-figure1-v1/figure_1a_prompt_token_ecdf.svg) · [PDF](results/figures/qwen3-8b-figure1-v1/figure_1a_prompt_token_ecdf.pdf)

![G02-01 Figure 1A：prompt token ECDF](results/figures/qwen3-8b-figure1-v1/figure_1a_prompt_token_ecdf.png)

<a id="figure-figure1-2"></a>

### G02-02 Figure 1B：每工作流请求数

160 个完整工作流的请求/span 数量分布。

`figure_1b_spans_per_workflow` · [PNG](results/figures/qwen3-8b-figure1-v1/figure_1b_spans_per_workflow.png) · [SVG](results/figures/qwen3-8b-figure1-v1/figure_1b_spans_per_workflow.svg) · [PDF](results/figures/qwen3-8b-figure1-v1/figure_1b_spans_per_workflow.pdf)

![G02-02 Figure 1B：每工作流请求数](results/figures/qwen3-8b-figure1-v1/figure_1b_spans_per_workflow.png)

<a id="figure-figure1-3"></a>

### G02-03 Figure 1C：context 与 focus 总体

上下文桶、总体和故障 focus 的覆盖；保留没有样本的桶。

`figure_1c_context_and_focus_population` · [PNG](results/figures/qwen3-8b-figure1-v1/figure_1c_context_and_focus_population.png) · [SVG](results/figures/qwen3-8b-figure1-v1/figure_1c_context_and_focus_population.svg) · [PDF](results/figures/qwen3-8b-figure1-v1/figure_1c_context_and_focus_population.pdf)

![G02-03 Figure 1C：context 与 focus 总体](results/figures/qwen3-8b-figure1-v1/figure_1c_context_and_focus_population.png)

<a id="figure-figure1-4"></a>

### G02-04 Figure 1D：故障干预核对

按 seed 检查逻辑请求、注入进度和物理目标的配对关系。

`figure_1d_intervention_audit` · [PNG](results/figures/qwen3-8b-figure1-v1/figure_1d_intervention_audit.png) · [SVG](results/figures/qwen3-8b-figure1-v1/figure_1d_intervention_audit.svg) · [PDF](results/figures/qwen3-8b-figure1-v1/figure_1d_intervention_audit.pdf)

![G02-04 Figure 1D：故障干预核对](results/figures/qwen3-8b-figure1-v1/figure_1d_intervention_audit.png)

</details>

<a id="group-healthy-v12"></a>

## 历史 Qwen3-8B：无故障开销 v12

<details>
<summary>展开本组图像与文件链接（4 条记录）</summary>

旧版无故障研究的四图。其对照明确为 `vanilla_mooncake_dram` 与 `aegiskv_unified`，即历史 Mooncake 模型基线与完整 AegisKV 模型；不是 AegisKV DRAM-only 消融。协议使用 Qwen3-8B、DP=8、C=16、160 个工作流/1,304 个请求、无故障，以及五种匹配的入场顺序；两种系统共十次完整执行。汇总保留每种顺序下 160 个按 workflow ID 匹配的 WCT。证据标记为未校准 E2 模拟、非实机、非 paper-ready。保留其输入和 acceptance 作用域，不与当前修订稿统计混用。

目录：[experiments/results/figures/qwen3-8b-no-failure-paper-v12](results/figures/qwen3-8b-no-failure-paper-v12)。

来源：[图像清单](results/figures/qwen3-8b-no-failure-paper-v12/FIGURE_MANIFEST.json) · [原始汇总](results/e2-qwen3-8b-no-failure-overhead-paper-v12/no-failure-overhead.json) · [历史 acceptance](results/qwen3-8b-paper-acceptance-v12.json) · [生成器](results/figures/generate_qwen3_8b_no_failure_overhead.py)。

<a id="figure-healthy-v12-1"></a>

### G03-01 Figure 2A：按 seed 的无故障 WCT

无故障保护对工作流完成时间的配对影响。

`fig2a_no_failure_wct_by_seed` · [PNG](results/figures/qwen3-8b-no-failure-paper-v12/fig2a_no_failure_wct_by_seed.png) · [SVG](results/figures/qwen3-8b-no-failure-paper-v12/fig2a_no_failure_wct_by_seed.svg) · [PDF](results/figures/qwen3-8b-no-failure-paper-v12/fig2a_no_failure_wct_by_seed.pdf)

![G03-01 Figure 2A：按 seed 的无故障 WCT](results/figures/qwen3-8b-no-failure-paper-v12/fig2a_no_failure_wct_by_seed.png)

<a id="figure-healthy-v12-2"></a>

### G03-02 Figure 2B：无故障系统开销

完整工作负载的 makespan、goodput 等开销指标。

`fig2b_no_failure_system_overhead` · [PNG](results/figures/qwen3-8b-no-failure-paper-v12/fig2b_no_failure_system_overhead.png) · [SVG](results/figures/qwen3-8b-no-failure-paper-v12/fig2b_no_failure_system_overhead.svg) · [PDF](results/figures/qwen3-8b-no-failure-paper-v12/fig2b_no_failure_system_overhead.pdf)

![G03-02 Figure 2B：无故障系统开销](results/figures/qwen3-8b-no-failure-paper-v12/fig2b_no_failure_system_overhead.png)

<a id="figure-healthy-v12-3"></a>

### G03-03 Figure 2C：无故障保护流量

保护提交、warmup 和中止等流量口径，具体定义见该版本生成器与 manifest。

`fig2c_no_failure_protection_traffic` · [PNG](results/figures/qwen3-8b-no-failure-paper-v12/fig2c_no_failure_protection_traffic.png) · [SVG](results/figures/qwen3-8b-no-failure-paper-v12/fig2c_no_failure_protection_traffic.svg) · [PDF](results/figures/qwen3-8b-no-failure-paper-v12/fig2c_no_failure_protection_traffic.pdf)

![G03-03 Figure 2C：无故障保护流量](results/figures/qwen3-8b-no-failure-paper-v12/fig2c_no_failure_protection_traffic.png)

<a id="figure-healthy-v12-4"></a>

### G03-04 Figure 2D：保护代价与效果

保护代价和完成时间变化的关系；资源消耗不保证延迟收益。

`fig2d_no_failure_cost_effect` · [PNG](results/figures/qwen3-8b-no-failure-paper-v12/fig2d_no_failure_cost_effect.png) · [SVG](results/figures/qwen3-8b-no-failure-paper-v12/fig2d_no_failure_cost_effect.svg) · [PDF](results/figures/qwen3-8b-no-failure-paper-v12/fig2d_no_failure_cost_effect.pdf)

![G03-04 Figure 2D：保护代价与效果](results/figures/qwen3-8b-no-failure-paper-v12/fig2d_no_failure_cost_effect.png)

</details>

<a id="group-failure-v13"></a>

## 历史 Qwen3-8B：故障与恢复 v13

<details>
<summary>展开本组图像与文件链接（7 条记录）</summary>

五个 admission seed 的旧版主故障 campaign。manifest 保留七个面板，并明确排除 FIGURE_4_A：没有证明完整且互斥的故障至完成阶段分解。目录中未出现的 Figure 4A 不是漏图。

目录：[experiments/results/figures/qwen3-8b-paper-f1-v13](results/figures/qwen3-8b-paper-f1-v13)。

来源：[图像及排除说明](results/figures/qwen3-8b-paper-f1-v13/FIGURE_MANIFEST.json) · [故障 campaign](results/e2-qwen3-8b-paper-f1-v13-campaign.json) · [历史 acceptance](results/qwen3-8b-paper-acceptance-v13.json) · [生成器](results/figures/generate_qwen3_8b_failure_campaign_figures.py)。

<a id="figure-failure-v13-1"></a>

### G04-01 Figure 3A：各总体的绝对 WCT

整体、focus、受影响联合集合等总体分别展示。

`figure_3a_absolute_wct_by_cohort` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_3a_absolute_wct_by_cohort.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_3a_absolute_wct_by_cohort.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_3a_absolute_wct_by_cohort.pdf)

![G04-01 Figure 3A：各总体的绝对 WCT](results/figures/qwen3-8b-paper-f1-v13/figure_3a_absolute_wct_by_cohort.png)

<a id="figure-failure-v13-2"></a>

### G04-02 Figure 3B：WCT ECDF

完整工作流的描述性分布；重复同一批工作流不能增加独立 seed 数。

`figure_3b_wct_ecdfs` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_3b_wct_ecdfs.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_3b_wct_ecdfs.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_3b_wct_ecdfs.pdf)

![G04-02 Figure 3B：WCT ECDF](results/figures/qwen3-8b-paper-f1-v13/figure_3b_wct_ecdfs.png)

<a id="figure-failure-v13-3"></a>

### G04-03 Figure 3C：平均 WCT 效果

旧版故障 campaign 中的配对平均 WCT 效果与区间。

`figure_3c_mean_wct_effect` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_3c_mean_wct_effect.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_3c_mean_wct_effect.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_3c_mean_wct_effect.pdf)

![G04-03 Figure 3C：平均 WCT 效果](results/figures/qwen3-8b-paper-f1-v13/figure_3c_mean_wct_effect.png)

<a id="figure-failure-v13-4"></a>

### G04-04 Figure 3D：P95 WCT 效果

旧版故障 campaign 中的配对 P95 WCT 效果。

`figure_3d_p95_wct_effect` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_3d_p95_wct_effect.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_3d_p95_wct_effect.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_3d_p95_wct_effect.pdf)

![G04-04 Figure 3D：P95 WCT 效果](results/figures/qwen3-8b-paper-f1-v13/figure_3d_p95_wct_effect.png)

<a id="figure-failure-v13-5"></a>

### G04-05 Figure 4B：直接恢复来源组成

预选 focus 请求的 Normal HBM、Peer、Store 与重算等来源。

`figure_4b_direct_recovery_composition` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_4b_direct_recovery_composition.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_4b_direct_recovery_composition.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_4b_direct_recovery_composition.pdf)

![G04-05 Figure 4B：直接恢复来源组成](results/figures/qwen3-8b-paper-f1-v13/figure_4b_direct_recovery_composition.png)

<a id="figure-failure-v13-6"></a>

### G04-06 Figure 4C：重算与恢复就绪

重算比例和恢复就绪时间的配对诊断。

`figure_4c_recompute_recovery_ready` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_4c_recompute_recovery_ready.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_4c_recompute_recovery_ready.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_4c_recompute_recovery_ready.pdf)

![G04-06 Figure 4C：重算与恢复就绪](results/figures/qwen3-8b-paper-f1-v13/figure_4c_recompute_recovery_ready.png)

<a id="figure-failure-v13-7"></a>

### G04-07 Figure 4D：选择器预测与实现结果

恢复源选择器的预测与实际模拟结果对照；保留不利和混合结果。

`figure_4d_selector_prediction_realization` · [PNG](results/figures/qwen3-8b-paper-f1-v13/figure_4d_selector_prediction_realization.png) · [SVG](results/figures/qwen3-8b-paper-f1-v13/figure_4d_selector_prediction_realization.svg) · [PDF](results/figures/qwen3-8b-paper-f1-v13/figure_4d_selector_prediction_realization.pdf)

![G04-07 Figure 4D：选择器预测与实现结果](results/figures/qwen3-8b-paper-f1-v13/figure_4d_selector_prediction_realization.png)

</details>

<a id="group-postfix"></a>

## 历史 Qwen3-8B：修复后小样本预览

<details>
<summary>展开本组图像与文件链接（4 条记录）</summary>

小样本开发诊断。该目录 FIGURE_MANIFEST 记录图名和 modeled_uncalibrated/paper_ready 标记，没有记录原始 artifact 路径及其哈希；本索引不凭近似目录名补认输入来源。

目录：[experiments/results/figures/qwen3-8b-postfix-small-v1](results/figures/qwen3-8b-postfix-small-v1)。

来源：[现有图像清单](results/figures/qwen3-8b-postfix-small-v1/FIGURE_MANIFEST.json) · [生成器](results/figures/generate_qwen3_8b_postfix_preview.py)。

<a id="figure-postfix-1"></a>

### G05-01 Postfix P1：无故障开销预览

修复后小样本的健康开销诊断。

`figp1_no_failure_overhead` · [PNG](results/figures/qwen3-8b-postfix-small-v1/figp1_no_failure_overhead.png) · [SVG](results/figures/qwen3-8b-postfix-small-v1/figp1_no_failure_overhead.svg) · [PDF](results/figures/qwen3-8b-postfix-small-v1/figp1_no_failure_overhead.pdf)

![G05-01 Postfix P1：无故障开销预览](results/figures/qwen3-8b-postfix-small-v1/figp1_no_failure_overhead.png)

<a id="figure-postfix-2"></a>

### G05-02 Postfix P2：故障延迟预览

小样本故障、恢复与完成延迟汇总。

`figp2_failure_latency_summary` · [PNG](results/figures/qwen3-8b-postfix-small-v1/figp2_failure_latency_summary.png) · [SVG](results/figures/qwen3-8b-postfix-small-v1/figp2_failure_latency_summary.svg) · [PDF](results/figures/qwen3-8b-postfix-small-v1/figp2_failure_latency_summary.pdf)

![G05-02 Postfix P2：故障延迟预览](results/figures/qwen3-8b-postfix-small-v1/figp2_failure_latency_summary.png)

<a id="figure-postfix-3"></a>

### G05-03 Postfix P3：故障阶段诊断

历史小样本阶段图；不能替代后续明确排除的完整互斥阶段分解。

`figp3_failure_phase_decomposition` · [PNG](results/figures/qwen3-8b-postfix-small-v1/figp3_failure_phase_decomposition.png) · [SVG](results/figures/qwen3-8b-postfix-small-v1/figp3_failure_phase_decomposition.svg) · [PDF](results/figures/qwen3-8b-postfix-small-v1/figp3_failure_phase_decomposition.pdf)

![G05-03 Postfix P3：故障阶段诊断](results/figures/qwen3-8b-postfix-small-v1/figp3_failure_phase_decomposition.png)

<a id="figure-postfix-4"></a>

### G05-04 Postfix P4：恢复 token 来源

小样本恢复前缀的来源与重算组成。

`figp4_recovery_token_sources` · [PNG](results/figures/qwen3-8b-postfix-small-v1/figp4_recovery_token_sources.png) · [SVG](results/figures/qwen3-8b-postfix-small-v1/figp4_recovery_token_sources.svg) · [PDF](results/figures/qwen3-8b-postfix-small-v1/figp4_recovery_token_sources.pdf)

![G05-04 Postfix P4：恢复 token 来源](results/figures/qwen3-8b-postfix-small-v1/figp4_recovery_token_sources.png)

</details>

<a id="group-sweeps-v5"></a>

## 历史 FanOutQA 参数扫描 v5

<details>
<summary>展开本组图像与文件链接（16 条记录）</summary>

CPU-only GlobalDES 开发结果，属于 E2 modeled/preliminary、未校准、paper_ready=false。基础场景与故障次数/并发扫描来自该版本自身输入；不同版本的前缀统计含义和模拟实现可能不同。当前源码中同名绘图脚本不保证与历史生成器哈希相同。

目录：[experiments/results/figures/paper-sweeps-v5](results/figures/paper-sweeps-v5)。

来源：[该版本图注](results/figures/paper-sweeps-v5/CAPTIONS.md) · [冻结扫描结果](results/e2-fanoutqa-paper-sweeps-v5/paper-sweeps.json) · [绘图脚本（当前工作区版本）](results/figures/generate_aegiskv_paper_sweeps.py) · [来源与生成器哈希](results/figures/paper-sweeps-v5/SOURCE_PROVENANCE.json)。

数据：[逐点 CSV](results/figures/paper-sweeps-v5/figure-data.csv)。

<a id="figure-sweeps-v5-1"></a>

### G06-01 基础场景 WCT ECDF

160 workflows、C=16、F=2 的历史基础场景；不同版本使用各自冻结的结果。

`fig1_base_wct_cdf` · [PNG](results/figures/paper-sweeps-v5/fig1_base_wct_cdf.png) · [SVG](results/figures/paper-sweeps-v5/fig1_base_wct_cdf.svg) · [PDF](results/figures/paper-sweeps-v5/fig1_base_wct_cdf.pdf)

![G06-01 基础场景 WCT ECDF](results/figures/paper-sweeps-v5/fig1_base_wct_cdf.png)

<a id="figure-sweeps-v5-2"></a>

### G06-02 基础场景 AIMD 与压力时间线

选定 GPU 的配额 alpha 与请求压力；选择规则和压力口径见本组图注。

`fig2_base_aimd_pressure` · [PNG](results/figures/paper-sweeps-v5/fig2_base_aimd_pressure.png) · [SVG](results/figures/paper-sweeps-v5/fig2_base_aimd_pressure.svg) · [PDF](results/figures/paper-sweeps-v5/fig2_base_aimd_pressure.pdf)

![G06-02 基础场景 AIMD 与压力时间线](results/figures/paper-sweeps-v5/fig2_base_aimd_pressure.png)

<a id="figure-sweeps-v5-3"></a>

### G06-03 故障时各 tier 独立可用的 KV 前缀

Normal HBM、Peer-HBM 与 DRAM 可覆盖同一逻辑前缀，各层值不能相加。

`fig3_base_failure_kv_available` · [PNG](results/figures/paper-sweeps-v5/fig3_base_failure_kv_available.png) · [SVG](results/figures/paper-sweeps-v5/fig3_base_failure_kv_available.svg) · [PDF](results/figures/paper-sweeps-v5/fig3_base_failure_kv_available.pdf)

![G06-03 故障时各 tier 独立可用的 KV 前缀](results/figures/paper-sweeps-v5/fig3_base_failure_kv_available.png)

<a id="figure-sweeps-v5-4"></a>

### G06-04 故障时的分层 KV 前缀

严格选定 focus 请求实际采用的连续前缀来源；Normal HBM 是机会性复用，Peer-HBM 与 Store DRAM 是 committed 保护来源。

`fig3_base_failure_kv_reuse` · [PNG](results/figures/paper-sweeps-v5/fig3_base_failure_kv_reuse.png) · [SVG](results/figures/paper-sweeps-v5/fig3_base_failure_kv_reuse.svg) · [PDF](results/figures/paper-sweeps-v5/fig3_base_failure_kv_reuse.pdf)

![G06-04 故障时的分层 KV 前缀](results/figures/paper-sweeps-v5/fig3_base_failure_kv_reuse.png)

<a id="figure-sweeps-v5-5"></a>

### G06-05 故障次数扫描：平均 alpha

保护配额的汇总；具体加权方式以该版本图注和输入为准。

`fig4_failure_scale_alpha` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha.pdf)

![G06-05 故障次数扫描：平均 alpha](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha.png)

<a id="figure-sweeps-v5-6"></a>

### G06-06 故障次数扫描：alpha 与压力

配额和压力指标联合展示，不能将控制事件比例解释为时间占比。

`fig4_failure_scale_alpha_pressure` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha_pressure.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha_pressure.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha_pressure.pdf)

![G06-06 故障次数扫描：alpha 与压力](results/figures/paper-sweeps-v5/fig4_failure_scale_alpha_pressure.png)

<a id="figure-sweeps-v5-7"></a>

### G06-07 故障次数扫描：故障时 KV 前缀

故障 focus 的 Peer-HBM / DRAM 前缀或恢复来源诊断；采用本组定义。

`fig4_failure_scale_failure_impact` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_failure_impact.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_failure_impact.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_failure_impact.pdf)

![G06-07 故障次数扫描：故障时 KV 前缀](results/figures/paper-sweeps-v5/fig4_failure_scale_failure_impact.png)

<a id="figure-sweeps-v5-8"></a>

### G06-08 故障次数扫描：收益分解

整体与故障局部 WCT gain 分开比较。

`fig4_failure_scale_gain_breakdown` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_gain_breakdown.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_gain_breakdown.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_gain_breakdown.pdf)

![G06-08 故障次数扫描：收益分解](results/figures/paper-sweeps-v5/fig4_failure_scale_gain_breakdown.png)

<a id="figure-sweeps-v5-9"></a>

### G06-09 故障次数扫描：绝对平均 WCT

不同策略的绝对平均工作流完成时间。

`fig4_failure_scale_mean_wct` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct.pdf)

![G06-09 故障次数扫描：绝对平均 WCT](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct.png)

<a id="figure-sweeps-v5-10"></a>

### G06-10 故障次数扫描：平均 WCT gain

相对于该版本基线的平均 WCT gain；保留负值与非单调变化。

`fig4_failure_scale_mean_wct_gain` · [PNG](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct_gain.png) · [SVG](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct_gain.svg) · [PDF](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct_gain.pdf)

![G06-10 故障次数扫描：平均 WCT gain](results/figures/paper-sweeps-v5/fig4_failure_scale_mean_wct_gain.png)

<a id="figure-sweeps-v5-11"></a>

### G06-11 工作流并发扫描：平均 alpha

保护配额的汇总；具体加权方式以该版本图注和输入为准。

`fig5_concurrency_scale_alpha` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha.pdf)

![G06-11 工作流并发扫描：平均 alpha](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha.png)

<a id="figure-sweeps-v5-12"></a>

### G06-12 工作流并发扫描：alpha 与压力

配额和压力指标联合展示，不能将控制事件比例解释为时间占比。

`fig5_concurrency_scale_alpha_pressure` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha_pressure.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha_pressure.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha_pressure.pdf)

![G06-12 工作流并发扫描：alpha 与压力](results/figures/paper-sweeps-v5/fig5_concurrency_scale_alpha_pressure.png)

<a id="figure-sweeps-v5-13"></a>

### G06-13 工作流并发扫描：故障时 KV 前缀

故障 focus 的 Peer-HBM / DRAM 前缀或恢复来源诊断；采用本组定义。

`fig5_concurrency_scale_failure_impact` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_failure_impact.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_failure_impact.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_failure_impact.pdf)

![G06-13 工作流并发扫描：故障时 KV 前缀](results/figures/paper-sweeps-v5/fig5_concurrency_scale_failure_impact.png)

<a id="figure-sweeps-v5-14"></a>

### G06-14 工作流并发扫描：收益分解

整体与故障局部 WCT gain 分开比较。

`fig5_concurrency_scale_gain_breakdown` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_gain_breakdown.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_gain_breakdown.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_gain_breakdown.pdf)

![G06-14 工作流并发扫描：收益分解](results/figures/paper-sweeps-v5/fig5_concurrency_scale_gain_breakdown.png)

<a id="figure-sweeps-v5-15"></a>

### G06-15 工作流并发扫描：绝对平均 WCT

不同策略的绝对平均工作流完成时间。

`fig5_concurrency_scale_mean_wct` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct.pdf)

![G06-15 工作流并发扫描：绝对平均 WCT](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct.png)

<a id="figure-sweeps-v5-16"></a>

### G06-16 工作流并发扫描：平均 WCT gain

相对于该版本基线的平均 WCT gain；保留负值与非单调变化。

`fig5_concurrency_scale_mean_wct_gain` · [PNG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct_gain.png) · [SVG](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct_gain.svg) · [PDF](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct_gain.pdf)

![G06-16 工作流并发扫描：平均 WCT gain](results/figures/paper-sweeps-v5/fig5_concurrency_scale_mean_wct_gain.png)

</details>

<a id="group-sweeps-v3"></a>

## 历史 FanOutQA 参数扫描 v3

<details>
<summary>展开本组图像与文件链接（15 条记录）</summary>

CPU-only GlobalDES 开发结果，属于 E2 modeled/preliminary、未校准、paper_ready=false。基础场景与故障次数/并发扫描来自该版本自身输入；不同版本的前缀统计含义和模拟实现可能不同。当前源码中同名绘图脚本不保证与历史生成器哈希相同。

目录：[experiments/results/figures/paper-sweeps-v3](results/figures/paper-sweeps-v3)。

来源：[该版本图注](results/figures/paper-sweeps-v3/CAPTIONS.md) · [冻结扫描结果](results/e2-fanoutqa-paper-sweeps-v3/paper-sweeps.json) · [绘图脚本（当前工作区版本）](results/figures/generate_aegiskv_paper_sweeps.py)。

数据：[逐点 CSV](results/figures/paper-sweeps-v3/figure-data.csv)。

<a id="figure-sweeps-v3-1"></a>

### G07-01 基础场景 WCT ECDF

160 workflows、C=16、F=2 的历史基础场景；不同版本使用各自冻结的结果。

`fig1_base_wct_cdf` · [PNG](results/figures/paper-sweeps-v3/fig1_base_wct_cdf.png) · [SVG](results/figures/paper-sweeps-v3/fig1_base_wct_cdf.svg) · [PDF](results/figures/paper-sweeps-v3/fig1_base_wct_cdf.pdf)

![G07-01 基础场景 WCT ECDF](results/figures/paper-sweeps-v3/fig1_base_wct_cdf.png)

<a id="figure-sweeps-v3-2"></a>

### G07-02 基础场景 AIMD 与压力时间线

选定 GPU 的配额 alpha 与请求压力；选择规则和压力口径见本组图注。

`fig2_base_aimd_pressure` · [PNG](results/figures/paper-sweeps-v3/fig2_base_aimd_pressure.png) · [SVG](results/figures/paper-sweeps-v3/fig2_base_aimd_pressure.svg) · [PDF](results/figures/paper-sweeps-v3/fig2_base_aimd_pressure.pdf)

![G07-02 基础场景 AIMD 与压力时间线](results/figures/paper-sweeps-v3/fig2_base_aimd_pressure.png)

<a id="figure-sweeps-v3-3"></a>

### G07-03 故障时的分层 KV 前缀

故障时各层独立 committed 的连续前缀；同一逻辑 token 可同时存在于多层，不能求和当成实际恢复量。

`fig3_base_failure_kv_reuse` · [PNG](results/figures/paper-sweeps-v3/fig3_base_failure_kv_reuse.png) · [SVG](results/figures/paper-sweeps-v3/fig3_base_failure_kv_reuse.svg) · [PDF](results/figures/paper-sweeps-v3/fig3_base_failure_kv_reuse.pdf)

![G07-03 故障时的分层 KV 前缀](results/figures/paper-sweeps-v3/fig3_base_failure_kv_reuse.png)

<a id="figure-sweeps-v3-4"></a>

### G07-04 故障次数扫描：平均 alpha

保护配额的汇总；具体加权方式以该版本图注和输入为准。

`fig4_failure_scale_alpha` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha.pdf)

![G07-04 故障次数扫描：平均 alpha](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha.png)

<a id="figure-sweeps-v3-5"></a>

### G07-05 故障次数扫描：alpha 与压力

配额和压力指标联合展示，不能将控制事件比例解释为时间占比。

`fig4_failure_scale_alpha_pressure` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha_pressure.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha_pressure.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha_pressure.pdf)

![G07-05 故障次数扫描：alpha 与压力](results/figures/paper-sweeps-v3/fig4_failure_scale_alpha_pressure.png)

<a id="figure-sweeps-v3-6"></a>

### G07-06 故障次数扫描：故障时 KV 前缀

故障 focus 的 Peer-HBM / DRAM 前缀或恢复来源诊断；采用本组定义。

`fig4_failure_scale_failure_impact` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_failure_impact.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_failure_impact.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_failure_impact.pdf)

![G07-06 故障次数扫描：故障时 KV 前缀](results/figures/paper-sweeps-v3/fig4_failure_scale_failure_impact.png)

<a id="figure-sweeps-v3-7"></a>

### G07-07 故障次数扫描：收益分解

整体与故障局部 WCT gain 分开比较。

`fig4_failure_scale_gain_breakdown` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_gain_breakdown.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_gain_breakdown.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_gain_breakdown.pdf)

![G07-07 故障次数扫描：收益分解](results/figures/paper-sweeps-v3/fig4_failure_scale_gain_breakdown.png)

<a id="figure-sweeps-v3-8"></a>

### G07-08 故障次数扫描：绝对平均 WCT

不同策略的绝对平均工作流完成时间。

`fig4_failure_scale_mean_wct` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct.pdf)

![G07-08 故障次数扫描：绝对平均 WCT](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct.png)

<a id="figure-sweeps-v3-9"></a>

### G07-09 故障次数扫描：平均 WCT gain

相对于该版本基线的平均 WCT gain；保留负值与非单调变化。

`fig4_failure_scale_mean_wct_gain` · [PNG](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct_gain.png) · [SVG](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct_gain.svg) · [PDF](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct_gain.pdf)

![G07-09 故障次数扫描：平均 WCT gain](results/figures/paper-sweeps-v3/fig4_failure_scale_mean_wct_gain.png)

<a id="figure-sweeps-v3-10"></a>

### G07-10 工作流并发扫描：平均 alpha

保护配额的汇总；具体加权方式以该版本图注和输入为准。

`fig5_concurrency_scale_alpha` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha.pdf)

![G07-10 工作流并发扫描：平均 alpha](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha.png)

<a id="figure-sweeps-v3-11"></a>

### G07-11 工作流并发扫描：alpha 与压力

配额和压力指标联合展示，不能将控制事件比例解释为时间占比。

`fig5_concurrency_scale_alpha_pressure` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha_pressure.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha_pressure.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha_pressure.pdf)

![G07-11 工作流并发扫描：alpha 与压力](results/figures/paper-sweeps-v3/fig5_concurrency_scale_alpha_pressure.png)

<a id="figure-sweeps-v3-12"></a>

### G07-12 工作流并发扫描：故障时 KV 前缀

故障 focus 的 Peer-HBM / DRAM 前缀或恢复来源诊断；采用本组定义。

`fig5_concurrency_scale_failure_impact` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_failure_impact.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_failure_impact.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_failure_impact.pdf)

![G07-12 工作流并发扫描：故障时 KV 前缀](results/figures/paper-sweeps-v3/fig5_concurrency_scale_failure_impact.png)

<a id="figure-sweeps-v3-13"></a>

### G07-13 工作流并发扫描：收益分解

整体与故障局部 WCT gain 分开比较。

`fig5_concurrency_scale_gain_breakdown` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_gain_breakdown.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_gain_breakdown.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_gain_breakdown.pdf)

![G07-13 工作流并发扫描：收益分解](results/figures/paper-sweeps-v3/fig5_concurrency_scale_gain_breakdown.png)

<a id="figure-sweeps-v3-14"></a>

### G07-14 工作流并发扫描：绝对平均 WCT

不同策略的绝对平均工作流完成时间。

`fig5_concurrency_scale_mean_wct` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct.pdf)

![G07-14 工作流并发扫描：绝对平均 WCT](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct.png)

<a id="figure-sweeps-v3-15"></a>

### G07-15 工作流并发扫描：平均 WCT gain

相对于该版本基线的平均 WCT gain；保留负值与非单调变化。

`fig5_concurrency_scale_mean_wct_gain` · [PNG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct_gain.png) · [SVG](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct_gain.svg) · [PDF](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct_gain.pdf)

![G07-15 工作流并发扫描：平均 WCT gain](results/figures/paper-sweeps-v3/fig5_concurrency_scale_mean_wct_gain.png)

</details>

<a id="group-sweeps-v2"></a>

## 历史 FanOutQA 参数扫描 v2

<details>
<summary>展开本组图像与文件链接（5 条记录）</summary>

CPU-only GlobalDES 开发结果，属于 E2 modeled/preliminary、未校准、paper_ready=false。基础场景与故障次数/并发扫描来自该版本自身输入；不同版本的前缀统计含义和模拟实现可能不同。当前源码中同名绘图脚本不保证与历史生成器哈希相同。

目录：[experiments/results/figures/paper-sweeps-v2](results/figures/paper-sweeps-v2)。

来源：[该版本图注](results/figures/paper-sweeps-v2/CAPTIONS.md) · [冻结扫描结果](results/e2-fanoutqa-paper-sweeps-v2/paper-sweeps.json) · [绘图脚本（当前工作区版本）](results/figures/generate_aegiskv_paper_sweeps.py)。

数据：[逐点 CSV](results/figures/paper-sweeps-v2/figure-data.csv)。

<a id="figure-sweeps-v2-1"></a>

### G08-01 基础场景 WCT ECDF

160 workflows、C=16、F=2 的历史基础场景；不同版本使用各自冻结的结果。

`fig1_base_wct_cdf` · [PNG](results/figures/paper-sweeps-v2/fig1_base_wct_cdf.png) · [SVG](results/figures/paper-sweeps-v2/fig1_base_wct_cdf.svg) · [PDF](results/figures/paper-sweeps-v2/fig1_base_wct_cdf.pdf)

![G08-01 基础场景 WCT ECDF](results/figures/paper-sweeps-v2/fig1_base_wct_cdf.png)

<a id="figure-sweeps-v2-2"></a>

### G08-02 基础场景 AIMD 与压力时间线

选定 GPU 的配额 alpha 与请求压力；选择规则和压力口径见本组图注。

`fig2_base_aimd_pressure` · [PNG](results/figures/paper-sweeps-v2/fig2_base_aimd_pressure.png) · [SVG](results/figures/paper-sweeps-v2/fig2_base_aimd_pressure.svg) · [PDF](results/figures/paper-sweeps-v2/fig2_base_aimd_pressure.pdf)

![G08-02 基础场景 AIMD 与压力时间线](results/figures/paper-sweeps-v2/fig2_base_aimd_pressure.png)

<a id="figure-sweeps-v2-3"></a>

### G08-03 故障时的分层 KV 前缀

各 tier 的 token 统计；实际使用量与独立可用量的定义随版本而异，以本组 CAPTIONS 为准。

`fig3_base_failure_kv_reuse` · [PNG](results/figures/paper-sweeps-v2/fig3_base_failure_kv_reuse.png) · [SVG](results/figures/paper-sweeps-v2/fig3_base_failure_kv_reuse.svg) · [PDF](results/figures/paper-sweeps-v2/fig3_base_failure_kv_reuse.pdf)

![G08-03 故障时的分层 KV 前缀](results/figures/paper-sweeps-v2/fig3_base_failure_kv_reuse.png)

<a id="figure-sweeps-v2-4"></a>

### G08-04 故障次数扫描：综合图

固定工作流并发，比较 WCT gain 与 alpha。

`fig4_failure_scale` · [PNG](results/figures/paper-sweeps-v2/fig4_failure_scale.png) · [SVG](results/figures/paper-sweeps-v2/fig4_failure_scale.svg) · [PDF](results/figures/paper-sweeps-v2/fig4_failure_scale.pdf)

![G08-04 故障次数扫描：综合图](results/figures/paper-sweeps-v2/fig4_failure_scale.png)

<a id="figure-sweeps-v2-5"></a>

### G08-05 工作流并发扫描：综合图

固定故障次数，比较 WCT gain 与 alpha。

`fig5_concurrency_scale` · [PNG](results/figures/paper-sweeps-v2/fig5_concurrency_scale.png) · [SVG](results/figures/paper-sweeps-v2/fig5_concurrency_scale.svg) · [PDF](results/figures/paper-sweeps-v2/fig5_concurrency_scale.pdf)

![G08-05 工作流并发扫描：综合图](results/figures/paper-sweeps-v2/fig5_concurrency_scale.png)

</details>

<a id="group-sweeps-v1"></a>

## 历史 FanOutQA 参数扫描 v1

<details>
<summary>展开本组图像与文件链接（5 条记录）</summary>

CPU-only GlobalDES 开发结果，属于 E2 modeled/preliminary、未校准、paper_ready=false。基础场景与故障次数/并发扫描来自该版本自身输入；不同版本的前缀统计含义和模拟实现可能不同。当前源码中同名绘图脚本不保证与历史生成器哈希相同。

目录：[experiments/results/e2-fanoutqa-paper-sweeps-v1/figures](results/e2-fanoutqa-paper-sweeps-v1/figures)。

来源：[该版本图注](results/e2-fanoutqa-paper-sweeps-v1/figures/CAPTIONS.md) · [冻结扫描结果](results/e2-fanoutqa-paper-sweeps-v1/paper-sweeps.json) · [绘图脚本（当前工作区版本）](results/figures/generate_aegiskv_paper_sweeps.py)。

数据：[逐点 CSV](results/e2-fanoutqa-paper-sweeps-v1/figures/figure-data.csv)。

<a id="figure-sweeps-v1-1"></a>

### G09-01 基础场景 WCT ECDF

160 workflows、C=16、F=2 的历史基础场景；不同版本使用各自冻结的结果。

`fig1_base_wct_cdf` · [PNG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig1_base_wct_cdf.png) · [SVG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig1_base_wct_cdf.svg) · [PDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig1_base_wct_cdf.pdf)

![G09-01 基础场景 WCT ECDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig1_base_wct_cdf.png)

<a id="figure-sweeps-v1-2"></a>

### G09-02 基础场景 AIMD 与压力时间线

选定 GPU 的配额 alpha 与请求压力；选择规则和压力口径见本组图注。

`fig2_base_aimd_pressure` · [PNG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig2_base_aimd_pressure.png) · [SVG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig2_base_aimd_pressure.svg) · [PDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig2_base_aimd_pressure.pdf)

![G09-02 基础场景 AIMD 与压力时间线](results/e2-fanoutqa-paper-sweeps-v1/figures/fig2_base_aimd_pressure.png)

<a id="figure-sweeps-v1-3"></a>

### G09-03 故障时的分层 KV 前缀

各 tier 的 token 统计；实际使用量与独立可用量的定义随版本而异，以本组 CAPTIONS 为准。

`fig3_base_failure_kv_reuse` · [PNG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig3_base_failure_kv_reuse.png) · [SVG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig3_base_failure_kv_reuse.svg) · [PDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig3_base_failure_kv_reuse.pdf)

![G09-03 故障时的分层 KV 前缀](results/e2-fanoutqa-paper-sweeps-v1/figures/fig3_base_failure_kv_reuse.png)

<a id="figure-sweeps-v1-4"></a>

### G09-04 故障次数扫描：综合图

固定工作流并发，比较 WCT gain 与 alpha。

`fig4_failure_scale` · [PNG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig4_failure_scale.png) · [SVG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig4_failure_scale.svg) · [PDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig4_failure_scale.pdf)

![G09-04 故障次数扫描：综合图](results/e2-fanoutqa-paper-sweeps-v1/figures/fig4_failure_scale.png)

<a id="figure-sweeps-v1-5"></a>

### G09-05 工作流并发扫描：综合图

固定故障次数，比较 WCT gain 与 alpha。

`fig5_concurrency_scale` · [PNG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig5_concurrency_scale.png) · [SVG](results/e2-fanoutqa-paper-sweeps-v1/figures/fig5_concurrency_scale.svg) · [PDF](results/e2-fanoutqa-paper-sweeps-v1/figures/fig5_concurrency_scale.pdf)

![G09-05 工作流并发扫描：综合图](results/e2-fanoutqa-paper-sweeps-v1/figures/fig5_concurrency_scale.png)

</details>

<a id="group-dp-all"></a>

## 历史 E2：Qwen3-8B DP 全矩阵

<details>
<summary>展开本组图像与文件链接（14 条记录）</summary>

旧 80-GiB HBM、117 个 Weka spans / 2 workflows 的模型快照，DP 扫描为 2/4/8。报告中当时的“current”不代表当前实现。F1–F11、F13–F15 共 14 图；F12 校准图被明确排除。

目录：[experiments/results/figures/e2-qwen3-8b-dp-all-v1](results/figures/e2-qwen3-8b-dp-all-v1)。

来源：[历史实验报告](results/e2-qwen3-8b-dp-all-v1/QWEN3_8B_DP_ALL_V1_REPORT.md) · [图像清单](results/figures/e2-qwen3-8b-dp-all-v1/manifest.json) · [矩阵清单](results/e2-qwen3-8b-dp-all-v1/manifest.json) · [F12 排除原因](results/figures/e2-qwen3-8b-dp-all-v1/f12-simulator-accuracy.excluded.json)。

<a id="figure-dp-all-1"></a>

### G10-01 F1：系统架构示意

历史 E2 图集中的组件与路径示意；不证明部署了对应实机组件。

`f1-system-architecture` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f1-system-architecture.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f1-system-architecture.provenance.json)

![G10-01 F1：系统架构示意](results/figures/e2-qwen3-8b-dp-all-v1/f1-system-architecture.svg)

<a id="figure-dp-all-2"></a>

### G10-02 F2：GPU 故障恢复时间线

故障、恢复传输、prompt 后缀重算、silent replay 与激活的虚拟时间诊断。

`f2-failure-recovery-timeline` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f2-failure-recovery-timeline.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f2-failure-recovery-timeline.provenance.json)

![G10-02 F2：GPU 故障恢复时间线](results/figures/e2-qwen3-8b-dp-all-v1/f2-failure-recovery-timeline.svg)

<a id="figure-dp-all-3"></a>

### G10-03 F3：Peer-HBM 保护池时间线

保护池的 committed、pending 与故障不可用容量；不等同于完整 GPU HBM 账本。

`f3-peer-hbm-timeline` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f3-peer-hbm-timeline.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f3-peer-hbm-timeline.provenance.json)

![G10-03 F3：Peer-HBM 保护池时间线](results/figures/e2-qwen3-8b-dp-all-v1/f3-peer-hbm-timeline.svg)

<a id="figure-dp-all-4"></a>

### G10-04 F4：Store DRAM 占用时间线

按 Store segment 绘制 committed 与 pending 占用。

`f4-store-dram-timeline` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f4-store-dram-timeline.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f4-store-dram-timeline.provenance.json)

![G10-04 F4：Store DRAM 占用时间线](results/figures/e2-qwen3-8b-dp-all-v1/f4-store-dram-timeline.svg)

<a id="figure-dp-all-5"></a>

### G10-05 F5：KV 迁移甘特图

终态传输记录中的排队、服务、提交与中止；显示的传输集合受版本的抽样规则限制。

`f5-kv-migration-gantt` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f5-kv-migration-gantt.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f5-kv-migration-gantt.provenance.json)

![G10-05 F5：KV 迁移甘特图](results/figures/e2-qwen3-8b-dp-all-v1/f5-kv-migration-gantt.svg)

<a id="figure-dp-all-6"></a>

### G10-06 F6：WCT 与 goodput

匹配 Vanilla 与 AegisKV 的整组工作负载指标；上下文 bucket 标识故障 focus cell。

`f6-wct-goodput` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f6-wct-goodput.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f6-wct-goodput.provenance.json)

![G10-06 F6：WCT 与 goodput](results/figures/e2-qwen3-8b-dp-all-v1/f6-wct-goodput.svg)

<a id="figure-dp-all-7"></a>

### G10-07 F7：恢复就绪 ECDF

跨运行的平均 recovery-ready 时间分布；不是原始请求完成延迟的 ECDF。

`f7-recovery-cdf` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f7-recovery-cdf.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f7-recovery-cdf.provenance.json)

![G10-07 F7：恢复就绪 ECDF](results/figures/e2-qwen3-8b-dp-all-v1/f7-recovery-cdf.svg)

<a id="figure-dp-all-8"></a>

### G10-08 F8：保护覆盖与重算

覆盖、恢复 token 与重算的历史模拟诊断。

`f8-coverage-recompute` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f8-coverage-recompute.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f8-coverage-recompute.provenance.json)

![G10-08 F8：保护覆盖与重算](results/figures/e2-qwen3-8b-dp-all-v1/f8-coverage-recompute.svg)

<a id="figure-dp-all-9"></a>

### G10-09 F9：策略消融

历史策略变体的 WCT 对比；不能据此评价 revision 3 新算法。

`f9-policy-ablation` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f9-policy-ablation.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f9-policy-ablation.provenance.json)

![G10-09 F9：策略消融](results/figures/e2-qwen3-8b-dp-all-v1/f9-policy-ablation.svg)

<a id="figure-dp-all-10"></a>

### G10-10 F10：资源预算敏感性

Peer-HBM 与 Store DRAM 预算轴分别比较；具体统计与基线以本组来源为准。

`f10-budget-sensitivity` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f10-budget-sensitivity.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f10-budget-sensitivity.provenance.json)

![G10-10 F10：资源预算敏感性](results/figures/e2-qwen3-8b-dp-all-v1/f10-budget-sensitivity.svg)

<a id="figure-dp-all-11"></a>

### G10-11 F11：扩展参数敏感性

DP、带宽或故障控制参数的历史敏感性；各版本的参数范围不同。

`f11-scale` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f11-scale.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f11-scale.provenance.json)

![G10-11 F11：扩展参数敏感性](results/figures/e2-qwen3-8b-dp-all-v1/f11-scale.svg)

<a id="figure-dp-all-12"></a>

### G10-12 F13：资源代价分解

保护内存、传输 byte-time、复制及重算相关代价；不同量纲分别解释。

`f13-resource-cost` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f13-resource-cost.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f13-resource-cost.provenance.json)

![G10-12 F13：资源代价分解](results/figures/e2-qwen3-8b-dp-all-v1/f13-resource-cost.svg)

<a id="figure-dp-all-13"></a>

### G10-13 F14：资源峰值与均值

事件边界峰值和时间加权平均占用；不能解释为 P95 占用。

`f14-peak-mean` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f14-peak-mean.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f14-peak-mean.provenance.json)

![G10-13 F14：资源峰值与均值](results/figures/e2-qwen3-8b-dp-all-v1/f14-peak-mean.svg)

<a id="figure-dp-all-14"></a>

### G10-14 F15：历史 trace 上下文覆盖

Weka 源数据的 hash-block 形状桶；不等于 Qwen3 tokenizer 的精确 128K 执行证据。

`f15-trace-coverage` · [SVG](results/figures/e2-qwen3-8b-dp-all-v1/f15-trace-coverage.svg) · [逐图 provenance](results/figures/e2-qwen3-8b-dp-all-v1/f15-trace-coverage.provenance.json)

![G10-14 F15：历史 trace 上下文覆盖](results/figures/e2-qwen3-8b-dp-all-v1/f15-trace-coverage.svg)

</details>

<a id="group-fluid"></a>

## 历史 E2：流体争用与完整 HBM 账本

<details>
<summary>展开本组图像与文件链接（3 条记录）</summary>

旧版七个 core 系统、两个 seed 的补充诊断；不能与 initial-v1 的消融/敏感性数据混成同一次实验。

目录：[experiments/results/figures/e2-fluid-core-v2](results/figures/e2-fluid-core-v2)。

来源：[实验报告](results/e2-fluid-core-v2/FLUID_CORE_V2_REPORT.md) · [图像清单](results/figures/e2-fluid-core-v2/manifest.json) · [生成器](results/figures/generate_aegiskv_fluid_preview.py)。

<a id="figure-fluid-1"></a>

### G11-01 F3V2：完整 GPU HBM 账本

事件边界上的完整 HBM account stack，包括故障后的不可用容量。

`f3v2-full-gpu-hbm-account-stack` · [SVG](results/figures/e2-fluid-core-v2/f3v2-full-gpu-hbm-account-stack.svg) · [逐图 provenance](results/figures/e2-fluid-core-v2/f3v2-full-gpu-hbm-account-stack.provenance.json)

![G11-01 F3V2：完整 GPU HBM 账本](results/figures/e2-fluid-core-v2/f3v2-full-gpu-hbm-account-stack.svg)

<a id="figure-fluid-2"></a>

### G11-02 F5V2：流体争用与利用率

Peer、Store 与 GPU HBM 的资源利用率；时间轴压缩到活跃 fluid epochs。

`f5v2-fluid-contention-utilization` · [SVG](results/figures/e2-fluid-core-v2/f5v2-fluid-contention-utilization.svg) · [逐图 provenance](results/figures/e2-fluid-core-v2/f5v2-fluid-contention-utilization.provenance.json)

![G11-02 F5V2：流体争用与利用率](results/figures/e2-fluid-core-v2/f5v2-fluid-contention-utilization.svg)

<a id="figure-fluid-3"></a>

### G11-03 F16：恢复预留与 staging

恢复目标的 reserve、staging、active KV 与 Peer-HBM 状态；零 staging 也可能是该运行的实际模拟结果。

`f16-recovery-reserve-staging` · [SVG](results/figures/e2-fluid-core-v2/f16-recovery-reserve-staging.svg) · [逐图 provenance](results/figures/e2-fluid-core-v2/f16-recovery-reserve-staging.provenance.json)

![G11-03 F16：恢复预留与 staging](results/figures/e2-fluid-core-v2/f16-recovery-reserve-staging.svg)

</details>

<a id="group-transport"></a>

## 历史 E2：Store 传输路径

<details>
<summary>展开本组图像与文件链接（1 条记录）</summary>

建模传输补充实验，包含 host staging；不是物理 RDMA/TCP/GDR 带宽测量。

目录：[experiments/results/figures/e2-transport-v1](results/figures/e2-transport-v1)。

来源：[实验报告](results/e2-transport-v1/TRANSPORT_V1_REPORT.md) · [图像清单](results/figures/e2-transport-v1/manifest.json) · [生成器](results/figures/generate_aegiskv_transport_preview.py)。

<a id="figure-transport-1"></a>

### G12-01 F17：Store 传输路径敏感性

GDR、RDMA host-staged 与 TCP host-staged 的 WCT、网络代价和主机 staging 对比；速率为模型假设。

`f17-store-transport-sensitivity` · [SVG](results/figures/e2-transport-v1/f17-store-transport-sensitivity.svg)

![G12-01 F17：Store 传输路径敏感性](results/figures/e2-transport-v1/f17-store-transport-sensitivity.svg)

</details>

<a id="group-store-nodes"></a>

## 历史 E2：Store 节点数

<details>
<summary>展开本组图像与文件链接（1 条记录）</summary>

总容量固定为 64 GiB 的旧版多 Store 模拟，两个 seed；端点速率是假设。

目录：[experiments/results/figures/e2-store-nodes-v1](results/figures/e2-store-nodes-v1)。

来源：[实验报告](results/e2-store-nodes-v1/STORE_NODE_V1_REPORT.md) · [图像清单](results/figures/e2-store-nodes-v1/manifest.json) · [生成器](results/figures/generate_aegiskv_store_node_preview.py)。

<a id="figure-store-nodes-1"></a>

### G13-01 F18：Store 节点数敏感性

总 Store 容量固定时比较 1、2、4 个模拟节点；不构成实机横向扩展结果。

`f18-store-node-sensitivity` · [SVG](results/figures/e2-store-nodes-v1/f18-store-node-sensitivity.svg)

![G13-01 F18：Store 节点数敏感性](results/figures/e2-store-nodes-v1/f18-store-node-sensitivity.svg)

</details>

<a id="group-initial"></a>

## 历史 E2：初始图集

<details>
<summary>展开本组图像与文件链接（14 条记录）</summary>

最早的 14 图预览。原报告指出该旧 bundle 早于显式 model_deployment 契约；历史 PASS 不等于现行审计通过。时间与资源都是 CPU 元数据模型结果。

目录：[experiments/results/figures/e2-initial-v1](results/figures/e2-initial-v1)。

来源：[历史实验报告](results/e2-initial-v1/INITIAL_REPORT.md) · [图像清单](results/figures/e2-initial-v1/manifest.json) · [F12 排除原因](results/figures/e2-initial-v1/f12-simulator-accuracy.excluded.json)。

<a id="figure-initial-1"></a>

### G14-01 F1：系统架构示意

历史 E2 图集中的组件与路径示意；不证明部署了对应实机组件。

`f1-system-architecture` · [SVG](results/figures/e2-initial-v1/f1-system-architecture.svg) · [逐图 provenance](results/figures/e2-initial-v1/f1-system-architecture.provenance.json)

![G14-01 F1：系统架构示意](results/figures/e2-initial-v1/f1-system-architecture.svg)

<a id="figure-initial-2"></a>

### G14-02 F2：GPU 故障恢复时间线

故障、恢复传输、prompt 后缀重算、silent replay 与激活的虚拟时间诊断。

`f2-failure-recovery-timeline` · [SVG](results/figures/e2-initial-v1/f2-failure-recovery-timeline.svg) · [逐图 provenance](results/figures/e2-initial-v1/f2-failure-recovery-timeline.provenance.json)

![G14-02 F2：GPU 故障恢复时间线](results/figures/e2-initial-v1/f2-failure-recovery-timeline.svg)

<a id="figure-initial-3"></a>

### G14-03 F3：Peer-HBM 保护池时间线

保护池的 committed、pending 与故障不可用容量；不等同于完整 GPU HBM 账本。

`f3-peer-hbm-timeline` · [SVG](results/figures/e2-initial-v1/f3-peer-hbm-timeline.svg) · [逐图 provenance](results/figures/e2-initial-v1/f3-peer-hbm-timeline.provenance.json)

![G14-03 F3：Peer-HBM 保护池时间线](results/figures/e2-initial-v1/f3-peer-hbm-timeline.svg)

<a id="figure-initial-4"></a>

### G14-04 F4：Store DRAM 占用时间线

按 Store segment 绘制 committed 与 pending 占用。

`f4-store-dram-timeline` · [SVG](results/figures/e2-initial-v1/f4-store-dram-timeline.svg) · [逐图 provenance](results/figures/e2-initial-v1/f4-store-dram-timeline.provenance.json)

![G14-04 F4：Store DRAM 占用时间线](results/figures/e2-initial-v1/f4-store-dram-timeline.svg)

<a id="figure-initial-5"></a>

### G14-05 F5：KV 迁移甘特图

终态传输记录中的排队、服务、提交与中止；显示的传输集合受版本的抽样规则限制。

`f5-kv-migration-gantt` · [SVG](results/figures/e2-initial-v1/f5-kv-migration-gantt.svg) · [逐图 provenance](results/figures/e2-initial-v1/f5-kv-migration-gantt.provenance.json)

![G14-05 F5：KV 迁移甘特图](results/figures/e2-initial-v1/f5-kv-migration-gantt.svg)

<a id="figure-initial-6"></a>

### G14-06 F6：WCT 与 goodput

匹配 Vanilla 与 AegisKV 的整组工作负载指标；上下文 bucket 标识故障 focus cell。

`f6-wct-goodput` · [SVG](results/figures/e2-initial-v1/f6-wct-goodput.svg) · [逐图 provenance](results/figures/e2-initial-v1/f6-wct-goodput.provenance.json)

![G14-06 F6：WCT 与 goodput](results/figures/e2-initial-v1/f6-wct-goodput.svg)

<a id="figure-initial-7"></a>

### G14-07 F7：恢复就绪 ECDF

跨运行的平均 recovery-ready 时间分布；不是原始请求完成延迟的 ECDF。

`f7-recovery-cdf` · [SVG](results/figures/e2-initial-v1/f7-recovery-cdf.svg) · [逐图 provenance](results/figures/e2-initial-v1/f7-recovery-cdf.provenance.json)

![G14-07 F7：恢复就绪 ECDF](results/figures/e2-initial-v1/f7-recovery-cdf.svg)

<a id="figure-initial-8"></a>

### G14-08 F8：保护覆盖与重算

覆盖、恢复 token 与重算的历史模拟诊断。

`f8-coverage-recompute` · [SVG](results/figures/e2-initial-v1/f8-coverage-recompute.svg) · [逐图 provenance](results/figures/e2-initial-v1/f8-coverage-recompute.provenance.json)

![G14-08 F8：保护覆盖与重算](results/figures/e2-initial-v1/f8-coverage-recompute.svg)

<a id="figure-initial-9"></a>

### G14-09 F9：策略消融

历史策略变体的 WCT 对比；不能据此评价 revision 3 新算法。

`f9-policy-ablation` · [SVG](results/figures/e2-initial-v1/f9-policy-ablation.svg) · [逐图 provenance](results/figures/e2-initial-v1/f9-policy-ablation.provenance.json)

![G14-09 F9：策略消融](results/figures/e2-initial-v1/f9-policy-ablation.svg)

<a id="figure-initial-10"></a>

### G14-10 F10：资源预算敏感性

Peer-HBM 与 Store DRAM 预算轴分别比较；具体统计与基线以本组来源为准。

`f10-budget-sensitivity` · [SVG](results/figures/e2-initial-v1/f10-budget-sensitivity.svg) · [逐图 provenance](results/figures/e2-initial-v1/f10-budget-sensitivity.provenance.json)

![G14-10 F10：资源预算敏感性](results/figures/e2-initial-v1/f10-budget-sensitivity.svg)

<a id="figure-initial-11"></a>

### G14-11 F11：扩展参数敏感性

DP、带宽或故障控制参数的历史敏感性；各版本的参数范围不同。

`f11-scale` · [SVG](results/figures/e2-initial-v1/f11-scale.svg) · [逐图 provenance](results/figures/e2-initial-v1/f11-scale.provenance.json)

![G14-11 F11：扩展参数敏感性](results/figures/e2-initial-v1/f11-scale.svg)

<a id="figure-initial-12"></a>

### G14-12 F13：资源代价分解

保护内存、传输 byte-time、复制及重算相关代价；不同量纲分别解释。

`f13-resource-cost` · [SVG](results/figures/e2-initial-v1/f13-resource-cost.svg) · [逐图 provenance](results/figures/e2-initial-v1/f13-resource-cost.provenance.json)

![G14-12 F13：资源代价分解](results/figures/e2-initial-v1/f13-resource-cost.svg)

<a id="figure-initial-13"></a>

### G14-13 F14：资源峰值与均值

事件边界峰值和时间加权平均占用；不能解释为 P95 占用。

`f14-peak-mean` · [SVG](results/figures/e2-initial-v1/f14-peak-mean.svg) · [逐图 provenance](results/figures/e2-initial-v1/f14-peak-mean.provenance.json)

![G14-13 F14：资源峰值与均值](results/figures/e2-initial-v1/f14-peak-mean.svg)

<a id="figure-initial-14"></a>

### G14-14 F15：历史 trace 上下文覆盖

Weka 源数据的 hash-block 形状桶；不等于 Qwen3 tokenizer 的精确 128K 执行证据。

`f15-trace-coverage` · [SVG](results/figures/e2-initial-v1/f15-trace-coverage.svg) · [逐图 provenance](results/figures/e2-initial-v1/f15-trace-coverage.provenance.json)

![G14-14 F15：历史 trace 上下文覆盖](results/figures/e2-initial-v1/f15-trace-coverage.svg)

</details>

<a id="group-complete-export"></a>

## 历史 E2：modeled-preliminary-complete 格式图集

<details>
<summary>展开本组图像与文件链接（14 条记录）</summary>

本目录有 14 组 PNG/PDF，没有独立 manifest 或输入绑定。保留为历史格式图集；文件夹名 complete 不代表完成了全部实验契约、校准或新算法评估。

目录：[experiments/results/figures/qwen3-8b-modeled-preliminary-complete-v1](results/figures/qwen3-8b-modeled-preliminary-complete-v1)。

来源：[E2 图集范围与证据定义](results/figures/README.md)。

<a id="figure-complete-export-1"></a>

### G15-01 F1：系统架构示意

历史 E2 图集中的组件与路径示意；不证明部署了对应实机组件。

`f1-system-architecture` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f1-system-architecture.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f1-system-architecture.pdf)

![G15-01 F1：系统架构示意](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f1-system-architecture.png)

<a id="figure-complete-export-2"></a>

### G15-02 F2：GPU 故障恢复时间线

故障、恢复传输、prompt 后缀重算、silent replay 与激活的虚拟时间诊断。

`f2-failure-recovery-timeline` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f2-failure-recovery-timeline.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f2-failure-recovery-timeline.pdf)

![G15-02 F2：GPU 故障恢复时间线](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f2-failure-recovery-timeline.png)

<a id="figure-complete-export-3"></a>

### G15-03 F3：Peer-HBM 保护池时间线

保护池的 committed、pending 与故障不可用容量；不等同于完整 GPU HBM 账本。

`f3-peer-hbm-timeline` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f3-peer-hbm-timeline.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f3-peer-hbm-timeline.pdf)

![G15-03 F3：Peer-HBM 保护池时间线](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f3-peer-hbm-timeline.png)

<a id="figure-complete-export-4"></a>

### G15-04 F4：Store DRAM 占用时间线

按 Store segment 绘制 committed 与 pending 占用。

`f4-store-dram-timeline` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f4-store-dram-timeline.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f4-store-dram-timeline.pdf)

![G15-04 F4：Store DRAM 占用时间线](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f4-store-dram-timeline.png)

<a id="figure-complete-export-5"></a>

### G15-05 F5：KV 迁移甘特图

终态传输记录中的排队、服务、提交与中止；显示的传输集合受版本的抽样规则限制。

`f5-kv-migration-gantt` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f5-kv-migration-gantt.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f5-kv-migration-gantt.pdf)

![G15-05 F5：KV 迁移甘特图](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f5-kv-migration-gantt.png)

<a id="figure-complete-export-6"></a>

### G15-06 F6：WCT 与 goodput

匹配 Vanilla 与 AegisKV 的整组工作负载指标；上下文 bucket 标识故障 focus cell。

`f6-wct-goodput` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f6-wct-goodput.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f6-wct-goodput.pdf)

![G15-06 F6：WCT 与 goodput](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f6-wct-goodput.png)

<a id="figure-complete-export-7"></a>

### G15-07 F7：恢复就绪 ECDF

跨运行的平均 recovery-ready 时间分布；不是原始请求完成延迟的 ECDF。

`f7-recovery-cdf` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f7-recovery-cdf.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f7-recovery-cdf.pdf)

![G15-07 F7：恢复就绪 ECDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f7-recovery-cdf.png)

<a id="figure-complete-export-8"></a>

### G15-08 F8：保护覆盖与重算

覆盖、恢复 token 与重算的历史模拟诊断。

`f8-coverage-recompute` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f8-coverage-recompute.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f8-coverage-recompute.pdf)

![G15-08 F8：保护覆盖与重算](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f8-coverage-recompute.png)

<a id="figure-complete-export-9"></a>

### G15-09 F9：策略消融

历史策略变体的 WCT 对比；不能据此评价 revision 3 新算法。

`f9-policy-ablation` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f9-policy-ablation.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f9-policy-ablation.pdf)

![G15-09 F9：策略消融](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f9-policy-ablation.png)

<a id="figure-complete-export-10"></a>

### G15-10 F10：资源预算敏感性

Peer-HBM 与 Store DRAM 预算轴分别比较；具体统计与基线以本组来源为准。

`f10-budget-sensitivity` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f10-budget-sensitivity.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f10-budget-sensitivity.pdf)

![G15-10 F10：资源预算敏感性](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f10-budget-sensitivity.png)

<a id="figure-complete-export-11"></a>

### G15-11 F11：扩展参数敏感性

DP、带宽或故障控制参数的历史敏感性；各版本的参数范围不同。

`f11-scale` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f11-scale.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f11-scale.pdf)

![G15-11 F11：扩展参数敏感性](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f11-scale.png)

<a id="figure-complete-export-12"></a>

### G15-12 F13：资源代价分解

保护内存、传输 byte-time、复制及重算相关代价；不同量纲分别解释。

`f13-resource-cost` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f13-resource-cost.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f13-resource-cost.pdf)

![G15-12 F13：资源代价分解](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f13-resource-cost.png)

<a id="figure-complete-export-13"></a>

### G15-13 F14：资源峰值与均值

事件边界峰值和时间加权平均占用；不能解释为 P95 占用。

`f14-peak-mean` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f14-peak-mean.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f14-peak-mean.pdf)

![G15-13 F14：资源峰值与均值](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f14-peak-mean.png)

<a id="figure-complete-export-14"></a>

### G15-14 F15：历史 trace 上下文覆盖

Weka 源数据的 hash-block 形状桶；不等于 Qwen3 tokenizer 的精确 128K 执行证据。

`f15-trace-coverage` · [PNG](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f15-trace-coverage.png) · [PDF](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f15-trace-coverage.pdf)

![G15-14 F15：历史 trace 上下文覆盖](results/figures/qwen3-8b-modeled-preliminary-complete-v1/f15-trace-coverage.png)

</details>

<a id="group-unused-paper"></a>

## 归档：未纳入当前论文的 8B 图

<details>
<summary>展开本组图像与文件链接（9 条记录）</summary>

September 5 legacy-model 稿件及旧 Motivation 的归档图。使用当时的指标定义和证据边界，不是 Mooncake-aligned 修订稿的新结果。

目录：[docs/paper/archive/simulation-8b-unused/figures](../docs/paper/archive/simulation-8b-unused/figures)。

来源：[旧版逐图方法](../docs/paper/FIGURE_METHODS.md) · [归档绘图输入](results/paper/data/figure-inputs) · [归档目录](../docs/paper/archive/simulation-8b-unused)。

<a id="figure-unused-paper-1"></a>

### G16-01 历史论文：代价与消融

保护与恢复代价、消融对比和不利案例；使用旧版统计定义。

`cost-and-ablation` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/cost-and-ablation.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/cost-and-ablation.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/cost-and-ablation.pdf)

![G16-01 历史论文：代价与消融](../docs/paper/archive/simulation-8b-unused/figures/cost-and-ablation.png)

<a id="figure-unused-paper-2"></a>

### G16-02 历史论文：故障效果

旧策略绝对 WCT、描述性 ECDF 和 F0 校正后的故障罚时。

`failure-effects` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/failure-effects.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/failure-effects.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/failure-effects.pdf)

![G16-02 历史论文：故障效果](../docs/paper/archive/simulation-8b-unused/figures/failure-effects.png)

<a id="figure-unused-paper-3"></a>

### G16-03 历史 Motivation：Slack 示意

旧版工作流 Slack 动机素材；用于解释机制。

`motivation-slack` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/motivation-slack.png) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/motivation-slack.pdf) · [Draw.io 源](../docs/paper/archive/simulation-8b-unused/figures/motivation-slack.drawio)

![G16-03 历史 Motivation：Slack 示意](../docs/paper/archive/simulation-8b-unused/figures/motivation-slack.png)

<a id="figure-unused-paper-4"></a>

### G16-04 历史论文：无故障保护代价

旧策略在健康运行下的 WCT、系统指标和保护流量。

`no-failure-cost` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/no-failure-cost.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/no-failure-cost.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/no-failure-cost.pdf)

![G16-04 历史论文：无故障保护代价](../docs/paper/archive/simulation-8b-unused/figures/no-failure-cost.png)

<a id="figure-unused-paper-5"></a>

### G16-05 历史论文：恢复机制

预选 focus 请求的恢复 token 组成及配对延迟。

`recovery-mechanism` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/recovery-mechanism.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/recovery-mechanism.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/recovery-mechanism.pdf)

![G16-05 历史论文：恢复机制](../docs/paper/archive/simulation-8b-unused/figures/recovery-mechanism.png)

<a id="figure-unused-paper-6"></a>

### G16-06 历史论文：故障与并发敏感性

旧版 failure-count / concurrency 扫描的 WCT、配额、压力和恢复来源。

`sensitivity` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/sensitivity.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/sensitivity.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/sensitivity.pdf)

![G16-06 历史论文：故障与并发敏感性](../docs/paper/archive/simulation-8b-unused/figures/sensitivity.png)

<a id="figure-unused-paper-7"></a>

### G16-07 历史论文：服务时序敏感性

不同批次服务组成假设下的配对效果；模型参数不是实测延迟上下界。

`timing-robustness` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/timing-robustness.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/timing-robustness.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/timing-robustness.pdf)

![G16-07 历史论文：服务时序敏感性](../docs/paper/archive/simulation-8b-unused/figures/timing-robustness.png)

<a id="figure-unused-paper-8"></a>

### G16-08 历史论文：工作负载与故障干预

旧版工作负载描述和五个主故障干预的组合图。

`workload-and-intervention` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/workload-and-intervention.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/workload-and-intervention.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/workload-and-intervention.pdf)

![G16-08 历史论文：工作负载与故障干预](../docs/paper/archive/simulation-8b-unused/figures/workload-and-intervention.png)

<a id="figure-unused-paper-9"></a>

### G16-09 历史论文：工作负载特征

旧版 prompt、context 和 workflow 结构分布。

`workload-characteristics` · [PNG](../docs/paper/archive/simulation-8b-unused/figures/workload-characteristics.png) · [SVG](../docs/paper/archive/simulation-8b-unused/figures/workload-characteristics.svg) · [PDF](../docs/paper/archive/simulation-8b-unused/figures/workload-characteristics.pdf)

![G16-09 历史论文：工作负载特征](../docs/paper/archive/simulation-8b-unused/figures/workload-characteristics.png)

</details>

<a id="group-legacy-paper"></a>

## 归档：更早的 SGLSim / 论文图

<details>
<summary>展开本组图像与文件链接（7 条记录）</summary>

来自本仓库已保存的旧论文副本。DP8 是旧原型单次模拟；DP64 是模型投影；heavy-failure 是逻辑时间模拟 smoke。它们不能与后来的 FanOutQA 160-workflow 研究合并；Motivation 中的真实 trace 不把恢复反事实变成实测。

目录：[docs/paper/archive/legacy-paper/figures](../docs/paper/archive/legacy-paper/figures)。

来源：[原评估方法与图注](../docs/paper/archive/legacy-paper/sections/05-evaluation.tex) · [原 Motivation 图注](../docs/paper/archive/legacy-paper/sections/02-background-motivation.tex)。

<a id="figure-legacy-paper-1"></a>

### G17-01 Legacy：DP64 WCT 投影

由历史样本与尺度假设得到的模型投影，不是 DP64 实测 WCT。

`legacy-wct-dp64-projection` · [PNG](../docs/paper/archive/legacy-paper/figures/legacy-wct-dp64-projection.png) · [PDF](../docs/paper/archive/legacy-paper/figures/legacy-wct-dp64-projection.pdf)

![G17-01 Legacy：DP64 WCT 投影](../docs/paper/archive/legacy-paper/figures/legacy-wct-dp64-projection.png)

<a id="figure-legacy-paper-2"></a>

### G17-02 Legacy：重故障压力

Qwen3-32B 逻辑 TP1/PP4/DP4、20 workflows、16 次故障的历史模拟 smoke；标为 offline-unvalidated。

`legacy-wct-heavyfail-stress` · [PNG](../docs/paper/archive/legacy-paper/figures/legacy-wct-heavyfail-stress.png) · [PDF](../docs/paper/archive/legacy-paper/figures/legacy-wct-heavyfail-stress.pdf)

![G17-02 Legacy：重故障压力](../docs/paper/archive/legacy-paper/figures/legacy-wct-heavyfail-stress.png)

<a id="figure-legacy-paper-3"></a>

### G17-03 Legacy：DP8 策略 WCT 对比

24 workflows 的旧原型单次模拟对比，固定 alpha；不验证当前独立双层实现。

`legacy-wct-policy-comparison` · [PNG](../docs/paper/archive/legacy-paper/figures/legacy-wct-policy-comparison.png) · [PDF](../docs/paper/archive/legacy-paper/figures/legacy-wct-policy-comparison.pdf)

![G17-03 Legacy：DP8 策略 WCT 对比](../docs/paper/archive/legacy-paper/figures/legacy-wct-policy-comparison.png)

<a id="figure-legacy-paper-4"></a>

### G17-04 历史 Motivation：Real CC 三联图

观测 trace 与反事实恢复模型的旧排版；含源数据形状计数与推断依赖的限制。

`motivation-real-cc-three-panel-submission` · [PNG](../docs/paper/archive/legacy-paper/figures/motivation-real-cc-three-panel-submission.png) · [PDF](../docs/paper/archive/legacy-paper/figures/motivation-real-cc-three-panel-submission.pdf)

![G17-04 历史 Motivation：Real CC 三联图](../docs/paper/archive/legacy-paper/figures/motivation-real-cc-three-panel-submission.png)

<a id="figure-legacy-paper-5"></a>

### G17-05 Legacy：alpha 与占用时间线

归档 SGLSim 机制遥测；本目录只保留 PDF。

`sim-fig05_alpha_occupancy_timeline` · [PDF](../docs/paper/archive/legacy-paper/figures/sim-fig05_alpha_occupancy_timeline.pdf)

此版本仅有 PDF，点击上方 PDF 链接查看。

<a id="figure-legacy-paper-6"></a>

### G17-06 Legacy：复用与恢复

归档 SGLSim 的复用/恢复诊断，具体总体见原评估章节。

`sim-fig06_reuse_and_recovery` · [PNG](../docs/paper/archive/legacy-paper/figures/sim-fig06_reuse_and_recovery.png) · [PDF](../docs/paper/archive/legacy-paper/figures/sim-fig06_reuse_and_recovery.pdf)

![G17-06 Legacy：复用与恢复](../docs/paper/archive/legacy-paper/figures/sim-fig06_reuse_and_recovery.png)

<a id="figure-legacy-paper-7"></a>

### G17-07 Legacy：原论文系统架构

旧论文的设计示意，供历史版本核对。

`system-overview-submission.drawio` · [PNG](../docs/paper/archive/legacy-paper/figures/system-overview-submission.drawio.png) · [PDF](../docs/paper/archive/legacy-paper/figures/system-overview-submission.drawio.pdf)

![G17-07 Legacy：原论文系统架构](../docs/paper/archive/legacy-paper/figures/system-overview-submission.drawio.png)

</details>

<a id="group-before-revision3"></a>

## 归档：算法 revision 3 前快照

<details>
<summary>展开本组图像与文件链接（13 条记录）</summary>

保留修订前的图像文件。与当前图像逐字节一致的预览以链接引用；旧架构版本单独展示。预览相同只说明该图文件相同，不把两版算法的证据作用域等同。

目录：[docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures) · [docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels)。

来源：[修订范围](../docs/paper/ALGORITHM_REVISION_V3.md)。

<a id="figure-before-revision3-13"></a>

### G18-13 历史版：系统架构

组件所有权、备份路径与恢复关系；属于设计示意。

`system-overview` · [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.png) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.pdf) · [原生导出 PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.native.png) · [原生导出 PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.native.pdf) · [Draw.io 源](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.drawio)

![G18-13 历史版：系统架构](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/system-overview.png)

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `aligned-ablations` | [G01-09](#figure-current-9) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-ablations.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-ablations.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-ablations.pdf) |
| `aligned-failure` | [G01-07](#figure-current-7) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-failure.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-failure.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-failure.pdf) |
| `aligned-healthy` | [G01-06](#figure-current-6) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-healthy.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-healthy.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-healthy.pdf) |
| `aligned-motivation-cost` | [G01-02](#figure-current-2) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-motivation-cost.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-motivation-cost.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-motivation-cost.pdf) |
| `aligned-recovery` | [G01-08](#figure-current-8) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-recovery.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-recovery.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-recovery.pdf) |
| `aligned-sensitivity` | [G01-10](#figure-current-10) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-sensitivity.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-sensitivity.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-sensitivity.pdf) |
| `aligned-workload` | [G01-05](#figure-current-5) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-workload.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-workload.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/aligned-workload.pdf) |
| `commit-recovery` | [G01-04](#figure-current-4) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/commit-recovery.png) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/commit-recovery.pdf) · [原生导出 PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/commit-recovery.native.png) · [原生导出 PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/commit-recovery.native.pdf) · [Draw.io 源](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/commit-recovery.drawio) |
| `modeled-harm` | [G01-13](#figure-current-13) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/modeled-harm.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/modeled-harm.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/modeled-harm.pdf) |
| `motivation-real-cc` | [G01-01](#figure-current-1) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-real-cc.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-real-cc.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-real-cc.pdf) |
| `motivation-workflow` | [G01-12](#figure-current-12) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-workflow.png) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-workflow.pdf) · [原生导出 PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-workflow.native.png) · [原生导出 PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-workflow.native.pdf) · [Draw.io 源](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-workflow.drawio) |
| `observed-gap` | [G01-11](#figure-current-11) | [PNG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/observed-gap.png) · [SVG](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/observed-gap.svg) · [PDF](../docs/paper/archive/before-algorithm-revision-20260906-233150/paper/figures/motivation-panels/observed-gap.pdf) |

</details>

<a id="group-precompact"></a>

## 输出归档：September 5 压缩排版前图

<details>
<summary>展开本组图像与文件链接（7 条记录）</summary>

旧统计图的较早排版，按现有文件保留。图像重排不是新的实验重复。

目录：[output/paper-simulation-8b/20260905/precompact-figures](../../../output/paper-simulation-8b/20260905/precompact-figures)。

来源：[历史指标定义](../docs/paper/FIGURE_METHODS.md)。

<a id="figure-precompact-1"></a>

### G19-01 历史论文：代价与消融

保护与恢复代价、消融对比和不利案例；使用旧版统计定义。

`cost-and-ablation` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/cost-and-ablation.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/cost-and-ablation.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/cost-and-ablation.pdf)

![G19-01 历史论文：代价与消融](../../../output/paper-simulation-8b/20260905/precompact-figures/cost-and-ablation.png)

<a id="figure-precompact-2"></a>

### G19-02 历史论文：故障效果

旧策略绝对 WCT、描述性 ECDF 和 F0 校正后的故障罚时。

`failure-effects` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/failure-effects.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/failure-effects.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/failure-effects.pdf)

![G19-02 历史论文：故障效果](../../../output/paper-simulation-8b/20260905/precompact-figures/failure-effects.png)

<a id="figure-precompact-3"></a>

### G19-03 历史论文：无故障保护代价

旧策略在健康运行下的 WCT、系统指标和保护流量。

`no-failure-cost` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/no-failure-cost.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/no-failure-cost.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/no-failure-cost.pdf)

![G19-03 历史论文：无故障保护代价](../../../output/paper-simulation-8b/20260905/precompact-figures/no-failure-cost.png)

<a id="figure-precompact-4"></a>

### G19-04 历史论文：恢复机制

预选 focus 请求的恢复 token 组成及配对延迟。

`recovery-mechanism` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/recovery-mechanism.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/recovery-mechanism.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/recovery-mechanism.pdf)

![G19-04 历史论文：恢复机制](../../../output/paper-simulation-8b/20260905/precompact-figures/recovery-mechanism.png)

<a id="figure-precompact-5"></a>

### G19-05 历史论文：故障与并发敏感性

旧版 failure-count / concurrency 扫描的 WCT、配额、压力和恢复来源。

`sensitivity` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/sensitivity.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/sensitivity.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/sensitivity.pdf)

![G19-05 历史论文：故障与并发敏感性](../../../output/paper-simulation-8b/20260905/precompact-figures/sensitivity.png)

<a id="figure-precompact-6"></a>

### G19-06 历史论文：服务时序敏感性

不同批次服务组成假设下的配对效果；模型参数不是实测延迟上下界。

`timing-robustness` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/timing-robustness.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/timing-robustness.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/timing-robustness.pdf)

![G19-06 历史论文：服务时序敏感性](../../../output/paper-simulation-8b/20260905/precompact-figures/timing-robustness.png)

<a id="figure-precompact-7"></a>

### G19-07 历史论文：工作负载与故障干预

旧版工作负载描述和五个主故障干预的组合图。

`workload-and-intervention` · [PNG](../../../output/paper-simulation-8b/20260905/precompact-figures/workload-and-intervention.png) · [SVG](../../../output/paper-simulation-8b/20260905/precompact-figures/workload-and-intervention.svg) · [PDF](../../../output/paper-simulation-8b/20260905/precompact-figures/workload-and-intervention.pdf)

![G19-07 历史论文：工作负载与故障干预](../../../output/paper-simulation-8b/20260905/precompact-figures/workload-and-intervention.png)

</details>

<a id="group-layout-preview"></a>

## 输出归档：September 6 版面预览图

<details>
<summary>展开本组图像与文件链接（10 条记录）</summary>

Mooncake-aligned 稿件的历史版面预览，含部分仅有 PDF 的图；保留版本差异，不作为当前最终图稿。

目录：[output/paper-simulation-8b/20260906-alignment/layout-preview/figures](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures)。

<a id="figure-layout-preview-1"></a>

### G20-01 历史版：策略消融

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-ablations` · [PNG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-ablations.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-ablations.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-ablations.pdf)

![G20-01 历史版：策略消融](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-ablations.png)

<a id="figure-layout-preview-2"></a>

### G20-02 历史版：故障对完整工作流的影响

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-failure` · [PNG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-failure.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-failure.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-failure.pdf)

![G20-02 历史版：故障对完整工作流的影响](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-failure.png)

<a id="figure-layout-preview-3"></a>

### G20-03 历史版：无故障保护开销

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-healthy` · [PNG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-healthy.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-healthy.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-healthy.pdf)

![G20-03 历史版：无故障保护开销](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-healthy.png)

<a id="figure-layout-preview-4"></a>

### G20-04 历史版：KV 容量与传输代价

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-motivation-cost` · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-motivation-cost.pdf)

此版本仅有 PDF，点击上方 PDF 链接查看。

<a id="figure-layout-preview-5"></a>

### G20-05 历史版：恢复来源与完成时间

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-recovery` · [PNG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-recovery.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-recovery.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-recovery.pdf)

![G20-05 历史版：恢复来源与完成时间](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-recovery.png)

<a id="figure-layout-preview-6"></a>

### G20-06 历史版：敏感性

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-sensitivity` · [PNG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-sensitivity.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-sensitivity.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-sensitivity.pdf)

![G20-06 历史版：敏感性](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-sensitivity.png)

<a id="figure-layout-preview-7"></a>

### G20-07 历史版：工作负载覆盖

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-workload` · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/aligned-workload.pdf)

此版本仅有 PDF，点击上方 PDF 链接查看。

<a id="figure-layout-preview-8"></a>

### G20-08 历史版：提交与恢复机制

独立 tier 的提交前缀、故障与备份复制到主 KV 的关系；事件顺序属于机制示意。

`commit-recovery` · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/commit-recovery.pdf)

此版本仅有 PDF，点击上方 PDF 链接查看。

<a id="figure-layout-preview-10"></a>

### G20-10 历史版：系统架构

组件所有权、备份路径与恢复关系；属于设计示意。

`system-overview` · [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/system-overview.pdf)

此版本仅有 PDF，点击上方 PDF 链接查看。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `motivation-slack` | [G16-03](#figure-unused-paper-3) | [PDF](../../../output/paper-simulation-8b/20260906-alignment/layout-preview/figures/motivation-slack.pdf) |

</details>

<a id="group-pre-revision"></a>

## 输出归档：September 6 重绘前图

<details>
<summary>展开本组图像与文件链接（18 条记录）</summary>

重绘前完整素材快照，同时含 aligned 与更早的 legacy 图。内容不同的图单独展示，相同预览指向已有条目。

目录：[output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures)。

来源：[图像修订记录](../docs/paper/FIGURE_REVISION.md)。

<a id="figure-pre-revision-1"></a>

### G21-01 历史版：策略消融

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-ablations` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-ablations.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-ablations.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-ablations.pdf)

![G21-01 历史版：策略消融](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-ablations.png)

<a id="figure-pre-revision-2"></a>

### G21-02 历史版：故障对完整工作流的影响

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-failure` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-failure.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-failure.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-failure.pdf)

![G21-02 历史版：故障对完整工作流的影响](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-failure.png)

<a id="figure-pre-revision-3"></a>

### G21-03 历史版：无故障保护开销

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-healthy` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-healthy.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-healthy.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-healthy.pdf)

![G21-03 历史版：无故障保护开销](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-healthy.png)

<a id="figure-pre-revision-4"></a>

### G21-04 历史版：KV 容量与传输代价

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-motivation-cost` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-motivation-cost.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-motivation-cost.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-motivation-cost.pdf)

![G21-04 历史版：KV 容量与传输代价](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-motivation-cost.png)

<a id="figure-pre-revision-5"></a>

### G21-05 历史版：恢复来源与完成时间

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-recovery` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-recovery.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-recovery.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-recovery.pdf)

![G21-05 历史版：恢复来源与完成时间](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-recovery.png)

<a id="figure-pre-revision-6"></a>

### G21-06 历史版：敏感性

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-sensitivity` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-sensitivity.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-sensitivity.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-sensitivity.pdf)

![G21-06 历史版：敏感性](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-sensitivity.png)

<a id="figure-pre-revision-7"></a>

### G21-07 历史版：工作负载覆盖

对应主题的重绘前历史排版。指标含义参见当前图的说明与历史修订记录；这份文件保留当时的布局与标注。

`aligned-workload` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-workload.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-workload.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-workload.pdf)

![G21-07 历史版：工作负载覆盖](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/aligned-workload.png)

<a id="figure-pre-revision-8"></a>

### G21-08 历史版：提交与恢复机制

独立 tier 的提交前缀、故障与备份复制到主 KV 的关系；事件顺序属于机制示意。

`commit-recovery` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/commit-recovery.png) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/commit-recovery.pdf) · [Draw.io 源](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/commit-recovery.drawio)

![G21-08 历史版：提交与恢复机制](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/commit-recovery.png)

<a id="figure-pre-revision-15"></a>

### G21-15 历史版：系统架构

组件所有权、备份路径与恢复关系；属于设计示意。

`system-overview` · [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/system-overview.png) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/system-overview.pdf) · [Draw.io 源](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/system-overview.drawio)

![G21-15 历史版：系统架构](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/system-overview.png)

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `cost-and-ablation` | [G16-01](#figure-unused-paper-1) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/cost-and-ablation.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/cost-and-ablation.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/cost-and-ablation.pdf) |
| `failure-effects` | [G16-02](#figure-unused-paper-2) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/failure-effects.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/failure-effects.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/failure-effects.pdf) |
| `motivation-slack` | [G16-03](#figure-unused-paper-3) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/motivation-slack.png) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/motivation-slack.pdf) · [Draw.io 源](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/motivation-slack.drawio) |
| `no-failure-cost` | [G16-04](#figure-unused-paper-4) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/no-failure-cost.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/no-failure-cost.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/no-failure-cost.pdf) |
| `recovery-mechanism` | [G16-05](#figure-unused-paper-5) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/recovery-mechanism.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/recovery-mechanism.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/recovery-mechanism.pdf) |
| `sensitivity` | [G16-06](#figure-unused-paper-6) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/sensitivity.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/sensitivity.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/sensitivity.pdf) |
| `timing-robustness` | [G16-07](#figure-unused-paper-7) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/timing-robustness.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/timing-robustness.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/timing-robustness.pdf) |
| `workload-and-intervention` | [G16-08](#figure-unused-paper-8) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-and-intervention.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-and-intervention.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-and-intervention.pdf) |
| `workload-characteristics` | [G16-09](#figure-unused-paper-9) | [PNG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-characteristics.png) · [SVG](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-characteristics.svg) · [PDF](../../../output/paper-simulation-8b/20260906-figure-revision/pre-revision/figures/workload-characteristics.pdf) |

</details>

<a id="group-v5-pdf"></a>

## 格式副本：参数扫描 v5 的 PDF 导出

<details>
<summary>展开本组图像与文件链接（16 条记录）</summary>

保留独立导出目录的全部文件链接；与主图集相同的 PDF 按 SHA-256 关联，不重复展示。

目录：[experiments/results/figures/paper-sweeps-v5-pdf](results/figures/paper-sweeps-v5-pdf)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `fig1_base_wct_cdf` | [G06-01](#figure-sweeps-v5-1) | [PDF](results/figures/paper-sweeps-v5-pdf/fig1_base_wct_cdf.pdf) |
| `fig2_base_aimd_pressure` | [G06-02](#figure-sweeps-v5-2) | [PDF](results/figures/paper-sweeps-v5-pdf/fig2_base_aimd_pressure.pdf) |
| `fig3_base_failure_kv_available` | [G06-03](#figure-sweeps-v5-3) | [PDF](results/figures/paper-sweeps-v5-pdf/fig3_base_failure_kv_available.pdf) |
| `fig3_base_failure_kv_reuse` | [G06-04](#figure-sweeps-v5-4) | [PDF](results/figures/paper-sweeps-v5-pdf/fig3_base_failure_kv_reuse.pdf) |
| `fig4_failure_scale_alpha` | [G06-05](#figure-sweeps-v5-5) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_alpha.pdf) |
| `fig4_failure_scale_alpha_pressure` | [G06-06](#figure-sweeps-v5-6) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_alpha_pressure.pdf) |
| `fig4_failure_scale_failure_impact` | [G06-07](#figure-sweeps-v5-7) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_failure_impact.pdf) |
| `fig4_failure_scale_gain_breakdown` | [G06-08](#figure-sweeps-v5-8) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_gain_breakdown.pdf) |
| `fig4_failure_scale_mean_wct` | [G06-09](#figure-sweeps-v5-9) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_mean_wct.pdf) |
| `fig4_failure_scale_mean_wct_gain` | [G06-10](#figure-sweeps-v5-10) | [PDF](results/figures/paper-sweeps-v5-pdf/fig4_failure_scale_mean_wct_gain.pdf) |
| `fig5_concurrency_scale_alpha` | [G06-11](#figure-sweeps-v5-11) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_alpha.pdf) |
| `fig5_concurrency_scale_alpha_pressure` | [G06-12](#figure-sweeps-v5-12) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_alpha_pressure.pdf) |
| `fig5_concurrency_scale_failure_impact` | [G06-13](#figure-sweeps-v5-13) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_failure_impact.pdf) |
| `fig5_concurrency_scale_gain_breakdown` | [G06-14](#figure-sweeps-v5-14) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_gain_breakdown.pdf) |
| `fig5_concurrency_scale_mean_wct` | [G06-15](#figure-sweeps-v5-15) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_mean_wct.pdf) |
| `fig5_concurrency_scale_mean_wct_gain` | [G06-16](#figure-sweeps-v5-16) | [PDF](results/figures/paper-sweeps-v5-pdf/fig5_concurrency_scale_mean_wct_gain.pdf) |

</details>

<a id="group-drawio-copies"></a>

## 格式副本：论文机制图与 Motivation 源目录

<details>
<summary>展开本组图像与文件链接（6 条记录）</summary>

论文图像的源目录副本；native 导出与最终版导出分别保留格式链接。

目录：[docs/drawio/paper-figures](../docs/drawio/paper-figures) · [docs/drawio/paper-figures/motivation-panels](../docs/drawio/paper-figures/motivation-panels)。

来源：[源目录说明](../docs/drawio/paper-figures/README.md)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `commit-recovery` | [G01-04](#figure-current-4) | [PNG](../docs/drawio/paper-figures/commit-recovery.png) · [PDF](../docs/drawio/paper-figures/commit-recovery.pdf) · [原生导出 PNG](../docs/drawio/paper-figures/commit-recovery.native.png) · [原生导出 PDF](../docs/drawio/paper-figures/commit-recovery.native.pdf) · [Draw.io 源](../docs/drawio/paper-figures/commit-recovery.drawio) |
| `modeled-harm` | [G01-13](#figure-current-13) | [PNG](../docs/drawio/paper-figures/motivation-panels/modeled-harm.png) · [SVG](../docs/drawio/paper-figures/motivation-panels/modeled-harm.svg) · [PDF](../docs/drawio/paper-figures/motivation-panels/modeled-harm.pdf) |
| `motivation-real-cc` | [G01-01](#figure-current-1) | [PNG](../docs/drawio/paper-figures/motivation-real-cc.png) · [SVG](../docs/drawio/paper-figures/motivation-real-cc.svg) · [PDF](../docs/drawio/paper-figures/motivation-real-cc.pdf) |
| `motivation-workflow` | [G01-12](#figure-current-12) | [PNG](../docs/drawio/paper-figures/motivation-workflow.png) · [PDF](../docs/drawio/paper-figures/motivation-workflow.pdf) · [原生导出 PNG](../docs/drawio/paper-figures/motivation-workflow.native.png) · [原生导出 PDF](../docs/drawio/paper-figures/motivation-workflow.native.pdf) · [Draw.io 源](../docs/drawio/paper-figures/motivation-workflow.drawio) |
| `observed-gap` | [G01-11](#figure-current-11) | [PNG](../docs/drawio/paper-figures/motivation-panels/observed-gap.png) · [SVG](../docs/drawio/paper-figures/motivation-panels/observed-gap.svg) · [PDF](../docs/drawio/paper-figures/motivation-panels/observed-gap.pdf) |
| `system-overview` | [G01-03](#figure-current-3) | [PNG](../docs/drawio/paper-figures/system-overview.png) · [PDF](../docs/drawio/paper-figures/system-overview.pdf) · [原生导出 PNG](../docs/drawio/paper-figures/system-overview.native.png) · [原生导出 PDF](../docs/drawio/paper-figures/system-overview.native.pdf) · [Draw.io 源](../docs/drawio/paper-figures/system-overview.drawio) |

</details>

<a id="group-imported-motivation"></a>

## 来源副本：导入的旧 Motivation PDF

<details>
<summary>展开本组图像与文件链接（1 条记录）</summary>

旧三联图原件在本仓库中的导入副本。来源哈希和 trace 重建另有记录。

目录：[experiments/results/paper/data/motivation-real-cc](results/paper/data/motivation-real-cc)。

来源：[导入来源](results/paper/data/motivation-real-cc/IMPORT.json) · [trace 重建记录](results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `motivation-real-cc-three-panel-submission` | [G17-04](#figure-legacy-paper-4) | [PDF](results/paper/data/motivation-real-cc/motivation-real-cc-three-panel-submission.pdf) |

</details>

<a id="group-submission-copies"></a>

## 格式副本：September 5 源码包中的图

<details>
<summary>展开本组图像与文件链接（7 条记录）</summary>

历史源码包里的图像副本，不作为新的实验图或当前交付包。

目录：[output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `cost-and-ablation` | [G16-01](#figure-unused-paper-1) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/cost-and-ablation.pdf) |
| `failure-effects` | [G16-02](#figure-unused-paper-2) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/failure-effects.pdf) |
| `no-failure-cost` | [G16-04](#figure-unused-paper-4) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/no-failure-cost.pdf) |
| `recovery-mechanism` | [G16-05](#figure-unused-paper-5) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/recovery-mechanism.pdf) |
| `sensitivity` | [G16-06](#figure-unused-paper-6) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/sensitivity.pdf) |
| `timing-robustness` | [G16-07](#figure-unused-paper-7) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/timing-robustness.pdf) |
| `workload-and-intervention` | [G16-08](#figure-unused-paper-8) | [PDF](../../../output/paper-simulation-8b/20260905/submission-source/paper/simulation-8b/figures/workload-and-intervention.pdf) |

</details>

<a id="group-previous-copies"></a>

## 格式副本：September 6 previous-paper 图

<details>
<summary>展开本组图像与文件链接（8 条记录）</summary>

旧稿备份目录中的图像副本，保留路径便于定位。

目录：[output/paper-simulation-8b/20260906-alignment/previous-paper/figures](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `cost-and-ablation` | [G16-01](#figure-unused-paper-1) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/cost-and-ablation.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/cost-and-ablation.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/cost-and-ablation.pdf) |
| `failure-effects` | [G16-02](#figure-unused-paper-2) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/failure-effects.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/failure-effects.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/failure-effects.pdf) |
| `no-failure-cost` | [G16-04](#figure-unused-paper-4) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/no-failure-cost.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/no-failure-cost.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/no-failure-cost.pdf) |
| `recovery-mechanism` | [G16-05](#figure-unused-paper-5) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/recovery-mechanism.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/recovery-mechanism.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/recovery-mechanism.pdf) |
| `sensitivity` | [G16-06](#figure-unused-paper-6) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/sensitivity.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/sensitivity.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/sensitivity.pdf) |
| `timing-robustness` | [G16-07](#figure-unused-paper-7) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/timing-robustness.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/timing-robustness.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/timing-robustness.pdf) |
| `workload-and-intervention` | [G16-08](#figure-unused-paper-8) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-and-intervention.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-and-intervention.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-and-intervention.pdf) |
| `workload-characteristics` | [G16-09](#figure-unused-paper-9) | [PNG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-characteristics.png) · [SVG](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-characteristics.svg) · [PDF](../../../output/paper-simulation-8b/20260906-alignment/previous-paper/figures/workload-characteristics.pdf) |

</details>

<a id="group-output-pdf-v1"></a>

## 格式副本：output/pdf 扫描 v1

<details>
<summary>展开本组图像与文件链接（5 条记录）</summary>

独立 PDF 导出路径。是否相同由文件 SHA-256 判定，不仅依据同名文件。

目录：[output/pdf](../../../output/pdf)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `fig1_base_wct_cdf` | [G09-01](#figure-sweeps-v1-1) | [PDF](../../../output/pdf/fig1_base_wct_cdf.pdf) |
| `fig2_base_aimd_pressure` | [G09-02](#figure-sweeps-v1-2) | [PDF](../../../output/pdf/fig2_base_aimd_pressure.pdf) |
| `fig3_base_failure_kv_reuse` | [G09-03](#figure-sweeps-v1-3) | [PDF](../../../output/pdf/fig3_base_failure_kv_reuse.pdf) |
| `fig4_failure_scale` | [G09-04](#figure-sweeps-v1-4) | [PDF](../../../output/pdf/fig4_failure_scale.pdf) |
| `fig5_concurrency_scale` | [G09-05](#figure-sweeps-v1-5) | [PDF](../../../output/pdf/fig5_concurrency_scale.pdf) |

</details>

<a id="group-output-pdf-v2"></a>

## 格式副本：output/pdf 扫描 v2

<details>
<summary>展开本组图像与文件链接（5 条记录）</summary>

独立 PDF 导出路径。是否相同由文件 SHA-256 判定，不仅依据同名文件。

目录：[output/pdf/aegiskv-paper-sweeps-v2](../../../output/pdf/aegiskv-paper-sweeps-v2)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `fig1_base_wct_cdf` | [G08-01](#figure-sweeps-v2-1) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v2/fig1_base_wct_cdf.pdf) |
| `fig2_base_aimd_pressure` | [G08-02](#figure-sweeps-v2-2) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v2/fig2_base_aimd_pressure.pdf) |
| `fig3_base_failure_kv_reuse` | [G08-03](#figure-sweeps-v2-3) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v2/fig3_base_failure_kv_reuse.pdf) |
| `fig4_failure_scale` | [G08-04](#figure-sweeps-v2-4) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v2/fig4_failure_scale.pdf) |
| `fig5_concurrency_scale` | [G08-05](#figure-sweeps-v2-5) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v2/fig5_concurrency_scale.pdf) |

</details>

<a id="group-output-pdf-v3"></a>

## 格式副本：output/pdf 扫描 v3

<details>
<summary>展开本组图像与文件链接（15 条记录）</summary>

独立 PDF 导出路径。是否相同由文件 SHA-256 判定，不仅依据同名文件。

目录：[output/pdf/aegiskv-paper-sweeps-v3](../../../output/pdf/aegiskv-paper-sweeps-v3)。

同图预览与原路径：

| 图名 | 已展示的同图 | 本目录文件 |
|---|---|---|
| `fig1_base_wct_cdf` | [G07-01](#figure-sweeps-v3-1) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig1_base_wct_cdf.pdf) |
| `fig2_base_aimd_pressure` | [G07-02](#figure-sweeps-v3-2) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig2_base_aimd_pressure.pdf) |
| `fig3_base_failure_kv_reuse` | [G07-03](#figure-sweeps-v3-3) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig3_base_failure_kv_reuse.pdf) |
| `fig4_failure_scale_alpha` | [G07-04](#figure-sweeps-v3-4) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_alpha.pdf) |
| `fig4_failure_scale_alpha_pressure` | [G07-05](#figure-sweeps-v3-5) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_alpha_pressure.pdf) |
| `fig4_failure_scale_failure_impact` | [G07-06](#figure-sweeps-v3-6) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_failure_impact.pdf) |
| `fig4_failure_scale_gain_breakdown` | [G07-07](#figure-sweeps-v3-7) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_gain_breakdown.pdf) |
| `fig4_failure_scale_mean_wct` | [G07-08](#figure-sweeps-v3-8) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_mean_wct.pdf) |
| `fig4_failure_scale_mean_wct_gain` | [G07-09](#figure-sweeps-v3-9) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig4_failure_scale_mean_wct_gain.pdf) |
| `fig5_concurrency_scale_alpha` | [G07-10](#figure-sweeps-v3-10) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_alpha.pdf) |
| `fig5_concurrency_scale_alpha_pressure` | [G07-11](#figure-sweeps-v3-11) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_alpha_pressure.pdf) |
| `fig5_concurrency_scale_failure_impact` | [G07-12](#figure-sweeps-v3-12) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_failure_impact.pdf) |
| `fig5_concurrency_scale_gain_breakdown` | [G07-13](#figure-sweeps-v3-13) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_gain_breakdown.pdf) |
| `fig5_concurrency_scale_mean_wct` | [G07-14](#figure-sweeps-v3-14) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_mean_wct.pdf) |
| `fig5_concurrency_scale_mean_wct_gain` | [G07-15](#figure-sweeps-v3-15) | [PDF](../../../output/pdf/aegiskv-paper-sweeps-v3/fig5_concurrency_scale_mean_wct_gain.pdf) |

</details>

<a id="coverage"></a>

## 范围、缺项与核对说明

本次收录实验结果图、论文定量图、Motivation 子图，以及与实验解释直接相关的正文示意图。同一主题不同版本分别保留；各版本中的图号不构成一套连续编号。

| 项目 | 处理方式 |
|---|---|
| E2 F12 simulator accuracy | 原图集明确排除，需校准/物理对照；见 [排除记录](results/figures/e2-qwen3-8b-dp-all-v1/f12-simulator-accuracy.excluded.json)。 |
| 旧主故障 Figure 4A | 未证明完整互斥阶段分解；见 [manifest.omitted_panel_ids](results/figures/qwen3-8b-paper-f1-v13/FIGURE_MANIFEST.json)。 |
| 只有结果、checkpoint 或 staging，没有图像的目录 | 不因目录存在而生成图；本文件按已经存在的图像建立索引。 |
| 论文整页截图、contact sheet、完整论文 PDF | 属于版面审阅/文档产物，不逐页当作实验图；入口见 [论文审阅目录](results/paper/review) 和 [当前论文 PDF](../paper/main.pdf)。 |
| source-bundle-check 解包工作树 | 属于构建校验副本，不纳入图像计数；见 [解包目录](results/paper/source-bundle-check)。 |
| tmp/pdfs 临时图像 | 渲染 smoke、灰度/排版检查和测试 fixture 不计作实验结果图；保留[临时目录入口](../../../tmp/pdfs)。 |
| related_works 论文及外部论文截图 | 属于参考文献素材，不计作 AegisKV 实验图。 |
| 单独的拓扑、算法流程和专利架构图 | 保留分类入口：[硬件拓扑](configs/engine)、[设计图目录](../docs/drawio/README.md)；正文示意图已随论文图收录。 |
| output 中的历史排版与 PDF 导出 | 已收录图稿文件，纯页面截图与解包副本除外；相同预览按内容哈希关联。 |

核对范围：清点上述图稿目录中的 PNG/SVG/PDF，检查本文件的文件链接、图片链接和锚点；按 SHA-256 关联相同预览。当前论文 [figure-manifest.json](results/paper/data/figure-manifest.json) 中的 45 个正文/组件文件（含可编辑源及 native 导出）已与实际文件逐项核对一致。这项检查覆盖文件与索引，不是重跑全部历史实验或重新认证其统计、校准与因果主张。

新增图像时，按实验输入/实现版本放入对应图组，补上图像预览、已有格式和数据来源；更新页首整理时间及导航计数。不要仅凭文件名相同覆盖或合并不同版本的结果。
