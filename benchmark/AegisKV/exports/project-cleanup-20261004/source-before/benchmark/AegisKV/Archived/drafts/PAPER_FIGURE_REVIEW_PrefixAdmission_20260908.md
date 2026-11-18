# AegisKV 投稿图审查与修改记录

[三部分论文叙述](Paper_Figures_PrefixAdmission_20260908.md) · [旧图](Old_Figures.md)

按用户本次纠正，36 图版整理为 33 张独立图：公式示意并入 DAG 实例，三个提交/恢复小图合为同一对象的完整生命周期。5 张设计图以对象、布局和状态变化重新绘制；6 组互补图在 Markdown 与 LaTeX 中并排。统计口径和实验输入保持原来源。设计图有原生 Draw.io 源，定量图有逐点 CSV，均有 PDF/SVG/PNG。

[获奖论文实际图页与具体改法](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) · [改版前 36 图](../../../output/pdf/aegiskv-paper-story-20260908/before-best-paper-review/FIGURES.md)

## 原 21 张逐图处理

| 原编号 | 审查问题 | 修改后及验证重点 |
|---|---|---|
| P01 | 单条分布线仍占三行图例空间；观测 gap 容易被当成因果 Slack | [M1 并行分支的时间差](Paper_Figures_PrefixAdmission_20260908.md#paper-motivation-branch-gap)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P02 | 容量余量线名称含混，单栏中长图例与曲线相邻 | [M2 额外 KV 副本的容量代价](Paper_Figures_PrefixAdmission_20260908.md#paper-motivation-kv-capacity)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P03 | 架构内实现小字过多、恢复数据路径难追踪 | [S1 保护路径与资源所有权](Paper_Figures_PrefixAdmission_20260908.md#paper-system-overview)；原生重构；检查箭头/状态/实际 PDF 文字 |
| P04 | 逻辑时间与实测时间没有视觉区分；头尾空白过大 | [S5 从独立提交到故障后的前缀装入](Paper_Figures_PrefixAdmission_20260908.md#paper-commit-tier-timeline)；原生重构；检查箭头/状态/实际 PDF 文字 |
| P05 | 状态图重复留白；未强调各层独立连续前缀 | [S5 从独立提交到故障后的前缀装入](Paper_Figures_PrefixAdmission_20260908.md#paper-commit-tier-timeline)；原生重构；检查箭头/状态/实际 PDF 文字 |
| P06 | 示意链路标签悬空；前缀就绪与解码恢复易混同 | [S5 从独立提交到故障后的前缀装入](Paper_Figures_PrefixAdmission_20260908.md#paper-commit-tier-timeline)；原生重构；检查箭头/状态/实际 PDF 文字 |
| P07 | CDF 顶部重复图例、最大上下文覆盖需限定 | [E1 原始输入的 Prompt 分布](Paper_Figures_PrefixAdmission_20260908.md#paper-workload-prompt_tokens)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P08 | 离散调用数 CDF 被画得过高、最大 27 需保留 | [E2 Workflow 规模分布](Paper_Figures_PrefixAdmission_20260908.md#paper-workload-workflow_call_counts)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P09 | ID 顺序锯齿掩盖 WCT 差异，通栏缩小后难读 | [E3 逐 Workflow 的 WCT](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-wct)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P10 | 差值需要同一排序和清晰零基线，不能隐藏负值 | [E4 逐 Workflow 的 WCT 增减](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-wct-difference)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P11 | 命中分母与请求命中比例不易区分 | [E7 准入改变后的 DRAM 复用率](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-dram-hit)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P12 | GPU queue 与 GET/CPU/HBM 等待混淆风险 | [E8 前台 GPU 调度排队](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-scheduler-queue)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P13 | 更少 HBM 等待不能直接归因于 Peer；需要配对来源 | [E9 GET 目标 HBM 的申请等待](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-hbm-wait)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P14 | 过高单栏图和外置三行图例，GPU 间差异不够清楚 | [E10 全部 GPU 的显存占用压力](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-hbm-pressure)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P15 | CPU 服务需求容易被误称实测 utilization | [E13 逐 Workflow 的控制面代价](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-controller-service-difference)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P16 | 流量与容量语义相近，需要实际字节的独立分解 | [E16 逐 Workflow 的后台传输量](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-background-copy)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P17 | 两条零线重合，需要说明且不能通过跨系统相减估计 Peer | [E17 新增 Peer 路径的传输成本](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-peer-copy)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P18 | GET 样本数不同，原图缺乏可直接复用的总体说明 | [E18 正常 GET 的链路争用](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-transfer-service_slowdown)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P19 | 少量敏感性点需要真实数值横轴与独立 marker | [E24 带宽改变时的完成时间权衡](Paper_Figures_PrefixAdmission_20260908.md#paper-sensitivity-bandwidth-mean_wct_s)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P20 | 闭环并发扫描不能写成开放负载吞吐 | [E25 并发压力与 Workflow 完成时间](Paper_Figures_PrefixAdmission_20260908.md#paper-sensitivity-concurrency-mean_wct_s)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |
| P21 | 容量跨度大，需要真实的对数坐标和两轮分母 | [E26 DRAM 容量与正常复用率](Paper_Figures_PrefixAdmission_20260908.md#paper-sensitivity-dram-capacity-dram_hit_pct)；按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF |

## 新增图填补了什么

| 新图 | 补足的证据或解释 | 类型 |
|---|---|---|
| [S2 一个 DAG 中的 Slack 与保守 ticket](Paper_Figures_PrefixAdmission_20260908.md#paper-design-slack-tickets) | 同起点的 A/B 分支分别执行 3/8 s，在 8 s 汇合。A 的结构 Slack 为 5 s，扣 1 s 保守余量后 ticket 为 4 s；B 为零。epoch=7 和所有时长均为设计示例。 | design |
| [S3 共享前缀的物理容量与联合删除损失](Paper_Figures_PrefixAdmission_20260908.md#paper-design-shared-prefix) | A/B 各引用三个等长 chunk，其中 C0/C1 共享；六次逻辑引用对应 4b 物理字节。删除 C1 的后代闭包释放 3b，而两个 consumer 各损失 2b 可复用前缀；b 为一个 chunk 的字节数。 | design |
| [S4 显存包络收缩与 free ACK 前的计账](Paper_Figures_PrefixAdmission_20260908.md#paper-design-foreground-budget) | 40 GiB 示意包络：固定占用 16、primary 12、前台预留 6、Peer 6。primary 新增 4 GiB 使 Peer 上限降至 2；撤销后仍按 6 计账，收到 free ACK 后才降至 2。示意数值不代表实测 allocator 轨迹。 | design |
| [E5 WCT 的整体分布](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-wct-cdf) | 图 E3 中全部 160 个 Workflow 的经验分布；保留完整尾部。这里的分布描述同一次执行中的异质工作流，不提供跨独立重复置信区间。 | modeled_exploration |
| [E6 正常服务的缓存来源分解](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-cache-sources) | 对全部 prompt token 做互斥分解：Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。本配置正常请求的 Peer 命中为零；Peer 备份字节不算正常复用收益。 | modeled_exploration |
| [E11 首 token 延迟分布](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-ttft-cdf) | 全部 2,608 个请求的 TTFT，横轴用对数秒以同时显示主体与完整尾部。P99 为 21.68/22.20/27.87 s；没有据此宣称满足原生 QoS 阈值。 | modeled_exploration |
| [E12 请求平均 TPOT 的长尾](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-tpot-tail) | 每系统 2,432 个 TPOT 有定义的请求；双对数生存曲线给出不小于横轴值的请求比例。每个请求先求平均 TPOT，不能当成逐 token 间隔分布。 | modeled_exploration |
| [E14 控制面服务需求的组成](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-controller-breakdown) | 按事件将前台查询与准入服务时间求和，总量为 2.58/5.44/6.05 s。该和不含排队，也不等于请求延迟或 CPU 使用百分比。 | modeled_exploration |
| [E15 前台读取与后台复制的组成](Paper_Figures_PrefixAdmission_20260908.md#paper-f0-revisit-traffic-breakdown) | 由实际传输记录互斥分解为正常 GET、DRAM 写入和 Peer 复制，含已传输的中止部分与收尾；TiB=2^40 bytes。Peer 开启后 DRAM 流量本身也会改变。 | modeled_exploration |
| [E19 25% 进度附近故障的逐 Workflow 影响](Paper_Figures_PrefixAdmission_20260908.md#paper-f1-q25-workflow-penalty) | 按无故障基准完成进度选择最接近 25% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。 | modeled_exploration |
| [E20 50% 进度附近故障的逐 Workflow 影响](Paper_Figures_PrefixAdmission_20260908.md#paper-f1-q50-workflow-penalty) | 按无故障基准完成进度选择最接近 50% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。 | modeled_exploration |
| [E21 75% 进度附近故障的逐 Workflow 影响](Paper_Figures_PrefixAdmission_20260908.md#paper-f1-q75-workflow-penalty) | 按无故障基准完成进度选择最接近 75% 的合格请求，在其 prefill 60% 处触发逻辑 GPU 故障。各系统减自身 F0；保留全部 160 个 Workflow 的正负变化，沿用图 E3 的 ID 顺序。 | modeled_exploration |
| [E22 故障位置与尾部 WCT 代价](Paper_Figures_PrefixAdmission_20260908.md#paper-failure-progress-p95-penalty) | 三个预定故障位置的逐 Workflow WCT 差值之 P95，横轴为真实基准完成比例。先逐对象求差再求 P95；包含故障前已完成对象，因此跨位置的下降不能直接解释为单次恢复更容易。 | modeled_exploration |
| [E23 故障请求恢复的阶段分解](Paper_Figures_PrefixAdmission_20260908.md#paper-failure-focal-recovery-phases) | 每位置仅展示预先选定的焦点请求。前段为故障至连续前缀装入，后段为装入后至恢复解码；分别包括对应等待和实际服务。总长才是焦点请求恢复延迟。 | modeled_exploration |

## 参考论文与采取的具体改法

本次核验并实际查看了四篇 Best Paper：Ensō（OSDI 2023）Figs. 1–3、10–12，Anvil（OSDI 2024）Fig. 5，Mooncake（FAST 2025）Figs. 2、9–14，CausalSim（NSDI 2023）Figs. 2、6–7。所用表达手法、PDF 页码和官方获奖来源见上述对照记录。参考的是对象关系、状态反例与相邻证据图的组织，没有复制原图、数据或其专属视觉元素。

仓库 acmart 模板实编译得到 textwidth=505.89 TeX pt、columnwidth=240.94499 TeX pt；以 7 / 3.33 inch 导出。曲线用颜色与线型共同编码；敏感性点再用不同 marker。所有 Workflow 共用基线 WCT 排序并公开原 ID 映射，不能分别排序三系统。TPOT 改用完整生存尾图，图例移至图外避免盖住稀少尾样本；图下注明请求均值这一统计单位。

## 补实验与证据缺口

[故障补跑协议](PAPER_FAILURE_PROTOCOL.md) 预先固定三个进度位置及 matched F0，共 12 次执行。source-v7 相对 v6 只有 runner 选点发生改变；三组 F0 的全部 160 个 WCT 与 v6 一致。原故障实验过晚的问题由新增早、中、后三组受控位置补充，仍不构成多 workload 或原生故障统计。

原生三系统干扰、完整 Algorithm 3 QoS 证书、预测器/Slack 消融、故障泛化四类缺图的条件已逐一写在 Evaluation 末尾；没有用模拟假设、零值消融或旧 SlackLandlord/AIMD 图冒充这些结果。

## 复现与核对

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_paper_story.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_paper_story_diagrams.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_paper_story_failures.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_paper_story_index.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_paper_story.py
```

[逐图选择与英文图注](results/paper/data/paper-story-selection.json) · [定量图来源](../../../output/pdf/aegiskv-paper-story-20260908/statistics-manifest.json) · [设计图来源](../../../output/pdf/aegiskv-paper-story-20260908/diagrams-manifest.json) · [故障补跑图来源](../../../output/pdf/aegiskv-paper-story-20260908/failure-manifest.json) · [数据与文档核对](../../../output/paper-story-20260908/DELIVERY_AUDIT.json) · [实际 PDF 视觉检查](../../../output/paper-story-20260908/VISUAL_REVIEW.json)。
