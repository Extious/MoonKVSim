# 论文图稿与证据审查

<!-- AGENT80_REVIEW -->
## 2026-09-09：固定 Agent 80% 故障实验

当前正文为 14 图。新图 8 展示 A7 故障后的全部 Workflow 配对变化；新图 9 替换旧固定 180 s 的 Figure 8，比较同一 Workflow 的七个 Agent 位置。原图 9–13 顺延为 10–14。三策略 ×（1 个 F0 + 7 个 F1）=24 次完整单轮模拟；下面的旧 13 图审查与插入样张属于此前版本。

[新实验协议与证据边界](../../../output/agent80-20260909/EXPERIMENT_AND_FIGURE_SPEC.md) · [原始运行复算](../../../output/agent80-20260909/campaign/RUN_AUDIT.json) · [新图清单](../../../output/pdf/aegiskv-revision-20260909/agent80-figure-manifest.json) · [当前交付检查](../../../output/agent80-20260909/DELIVERY_AUDIT.json)

<!-- AGENT80_REVIEW_END -->

<!-- SINGLE_PASS_REVIEW_START -->

## 单轮正常服务图更新（2026-09-09）

原 Figure 5–7 的两轮口径退出正常服务论证。当前三图复用 Agent-80 会话的三个单轮 F0；各 160 个原始 DAG、1,304 个请求、seed 0。其余图仍按各自历史来源解释。

[当前单轮来源与审查](../../../output/aegiskv-single-pass-20260909/REPORT.md) · [逐 Workflow 配对表](../../../output/pdf/aegiskv-single-pass-20260909/all-workflows-paired.csv) · [单轮检查](../../../output/aegiskv-single-pass-20260909/AUDIT.json)

重建命令：`.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_single_pass_f0.py`，随后运行 `integrate_single_pass_f0.py`。旧版正文生成器已接入这一最终替换步骤。旧插入样张与旧总体审查只绑定其历史文件，不代表本次新正文。

<!-- SINGLE_PASS_REVIEW_END -->

[中文初稿](Paper_Draft.md) · [实验设计](EVALUATION_DESIGN.md) · [事件诊断](../../../output/aegiskv-revision-20260909/EVALUATION_DIAGNOSIS.md) · [修改前初稿](Paper_Draft_BeforeDiagnosis_20260909.md)

正文共 13 张独立图：3 张 Motivation、1 张 Overview、9 张 Evaluation。定量图的排版可直接插入 LaTeX；当前模拟结果尚不能作为“近零开销且稳定故障收益”的投稿证据。所有不利结果和旧图完整保留。

## 本轮修正

- Observation 3 改为长上下文的完整前缀重算预测，移出容量图；旧 235B/PP4 未验证配置不加入该新图。
- Overview 使用具体 primary/backup 对象、独立复制与 ACK、故障恢复路径；清理主文旧联合终点授信公式，保留当前 Agent 接口和不变条件。
- 正常 WCT 保留全部对象和离群点，以秒展示实际增加的延迟，并由同一请求的抢占/进度轨迹解释。
- 重访命中单独统计，区分初次读取与抢占后实际避免的计算；不把冷访问混入重访分母。
- 删除混合量纲归一资源图，分项绝对量进正文表；旧初始等待指标不能证明完整生命周期排队没有增长。
- 单故障改为同一 Workflow 的 F0→F1 配对，并邻接实际恢复来源；明确 Peer=0 和受害集合差异。
- 扩展曲线只使用完成并审计的真实模拟点，不插值缺测点、不添加不存在的收益或置信区间。

- 按用户新纠正，原始 WCT P95 移出正文图与服务表。并发使用最高并发点的同 ID 差值，故障细节使用共同历史下 K2−K1 的固定追加事件影响；释放时刻变化单独核对。

- 将固定追加故障比较提前到恢复机制之前；正文图注缩短，完整字段与来源保留在原图 manifest。
- 增加 8 组待绘位置、10 张独立候选的图型、坐标、条件预期与反证条件。所有候选均为未执行规格，不计入正文结果图或模拟次数。
- 补充故障范围、请求级 Slack 快照、当前 Agent 续租、物理发布/释放约束及 DMA-to-forward 未建模边界。

[论文整体审查与落实修改](PAPER_DRAFT_REVIEW.md) · [未绘图的结构化规格](scripts/paper/templates/planned-figures.json) · [本次文字修订前初稿](Paper_Draft_BeforeStory_20260909.md)

## 图像与来源

| 图 | 科学口径与限制 | 文件 |
|---|---|---|
| [1 并行分支的执行时间不均衡](Paper_Draft.md#paper-motivation-branch-gap) | CC/Weka 中 124 个具有重叠分支的 Workflow；每个对象取最大分支持续时间差。横轴为对数秒。该观测描述不均衡，不直接估计可用 Slack。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/motivation-branch-gap.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/motivation-branch-gap.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/motivation-branch-gap.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/motivation-branch-gap.csv) |
| [2 重算代价与 Workflow 损失并不等价](Paper_Draft.md#paper-motivation-recovery-exposure) | 同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/motivation-recovery-exposure.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/motivation-recovery-exposure.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/motivation-recovery-exposure.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/motivation-recovery-exposure.csv) |
| [3 长上下文的完整前缀重算代价](Paper_Draft.md#paper-motivation-recompute) | Qwen3-8B/32B 在 A100-80GB、TP4/PP2、BF16 配置下的完整前缀重算预测；每点按 8 Ki-token 分块累计单请求 prefill 时间，Ki=1,024。共八个历史 AIConfigurator SILICON 预测点，不含故障检测、传输与排队，不是物理故障实验。 | [PNG](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute.png) · [PDF](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute.svg) · [CSV](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute.csv) |
| [4 AegisKV System Overview](Paper_Draft.md#paper-system-overview) | 工作流上下文生成 Agent 保护优先级，源端独立向 Peer HBM 和 DRAM 复制同名 KV；副本在复制 ACK 后可读。Peer 控制器独立约束备份借用。故障后从存活层恢复新 primary C0/C1，再重算 C2。彩色箭头为 KV 传输，虚线为控制，灰色 DAG 边为依赖。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/system-overview.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/system-overview.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/system-overview.png) · [DRAWIO](../../../output/pdf/aegiskv-revision-20260909/system-overview.drawio) |
| [5 原始 160 个 Workflow 单轮无故障的 WCT 差值](Paper_Draft.md#paper-eval-workflow-delay) | 每个原始 DAG 执行一次，共 1,304 个请求；三系统各一次完整无故障模拟，按同 ID 配对并共享单轮 Mooncake WCT 排序。AegisKV 有 85 个更慢、75 个更快；最大增量 34.589 s。均值 39.083/39.206/39.059 s；不作重复运行显著性推断。 | [PDF](../../../output/pdf/aegiskv-single-pass-20260909/eval-workflow-delay.pdf) · [PNG](../../../output/pdf/aegiskv-single-pass-20260909/eval-workflow-delay.png) · [SVG](../../../output/pdf/aegiskv-single-pass-20260909/eval-workflow-delay.svg) · [CSV](../../../output/pdf/aegiskv-single-pass-20260909/eval-workflow-delay.csv) |
| [6 原始 Workflow 全部请求的缓存命中](Paper_Draft.md#paper-eval-initial-reuse) | 与图 5 完全相同的单轮 F0 运行、160 个 ID 及排序。上图为每个 Workflow 全部请求命中的 token 数（本地 HBM + DRAM + Peer）除以其全部 prompt token 数，冷请求保留；下图为命中 token 数相对同 ID Mooncake 的差值。所有 Workflow 的 DRAM 和 Peer 命中均为零；总体命中率为 0.306603%、0.306603%、0.306842%。初次复用计数不直接等于全生命周期避免的计算量。 | [PDF](../../../output/pdf/aegiskv-single-pass-20260909/eval-initial-reuse.pdf) · [PNG](../../../output/pdf/aegiskv-single-pass-20260909/eval-initial-reuse.png) · [SVG](../../../output/pdf/aegiskv-single-pass-20260909/eval-initial-reuse.svg) · [CSV](../../../output/pdf/aegiskv-single-pass-20260909/eval-initial-reuse.csv) |
| [7 单轮最大变慢 Workflow 的完成时间构成](Paper_Draft.md#paper-eval-preemption-progress) | 图 5 中 AegisKV 增量最大的 Workflow 1fb9003757829127，三系统都统计相同对象。沿各系统实际最晚完成前驱回溯至根，分解 GPU batch 参与时段、等待/调度间隙及 CPU/GET/依赖释放间隔，互斥求和等于 WCT。三系统该对象都命中 448 个 token，执行相同 prefill 工作，均无抢占。Batch 参与历时不是该请求独占 GPU 的计算时间；关键路径可随系统改变。 | [PDF](../../../output/pdf/aegiskv-single-pass-20260909/eval-preemption-progress.pdf) · [PNG](../../../output/pdf/aegiskv-single-pass-20260909/eval-preemption-progress.png) · [SVG](../../../output/pdf/aegiskv-single-pass-20260909/eval-preemption-progress.svg) · [CSV](../../../output/pdf/aegiskv-single-pass-20260909/eval-preemption-progress.csv) |
| [8 固定追加故障对同一Workflow的WCT影响](Paper_Draft.md#paper-eval-fixed-event-wct) | 追加 180 s/GPU2 故障的同 ID 效应：K1/K2 共享 60 s/GPU0 故障，每次停机 120 s，纵轴为同系统 WCT(K2)−WCT(K1)。七个 ID 为三系统直接受害者的事后并集；实心、空心、叉号分别为含活跃受害请求、仅排队受害、无直接受害。21 对释放时刻相等，负值和零值保留。每系统每日程一次模拟。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-fixed-event-wct.csv) |
| [9 同一焦点 Workflow 的故障前后配对 WCT](Paper_Draft.md#paper-eval-fault-paired-wct) | C1/C2/C3 分别为 Workflow 98ced84a/220852c6/5aa09932，源 GPU 为 6/2/0。箭头从同系统、同 ID 的 F0 指向 F1；各例各系统一次 F1，复用相应 F0。故障固定焦点请求与 token 进度，其他受害者集合不同；该图为机制诊断。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-fault-paired-wct.pdf) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-fault-paired-wct.png) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-fault-paired-wct.svg) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-fault-paired-wct.csv) |
| [10 同一故障请求的恢复来源与重算量](Paper_Draft.md#paper-eval-fault-token-source) | 与前图相同焦点请求的 Peer、DRAM 恢复量与重算量，Ki=1,024；每行来自一次 F1 执行。Peer 恢复量全为零，仍保留其图例。本地 primary 复用未计入这些分段；这些 token 数不分解完整 DAG 时间。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-fault-token-source.pdf) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-fault-token-source.png) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-fault-token-source.svg) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-fault-token-source.csv) |
| [11 并发扩展的完整批次完成速率](Paper_Draft.md#paper-eval-concurrency-throughput) | 固定 160 个 Workflow、两轮重访和相同资源，改变最大活跃 Workflow 数，横轴为 log2 刻度。完成速率为 160 除以完整批次时长，包含填充与排空；不是 SLO goodput。每个系统每点一次冻结算法模拟，无重复置信区间。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-throughput.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-throughput.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-throughput.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-throughput.csv) |
| [12 并发64下同一 Workflow 的 WCT 差值](Paper_Draft.md#paper-eval-concurrency-workflow) | C64 下全部 160 个 Workflow 相对同 ID、同 C64 Mooncake 的 WCT 差值。横轴只沿用 C16 Mooncake 的排序，数值比较均在 C64；每系统一次模拟。AegisKV 有 65 个更快、95 个更慢，保留所有正负变化。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-concurrency-workflow.csv) |
| [13 固定时间窗口内的故障频率与完成速率](Paper_Draft.md#paper-eval-failure-rate-throughput) | 预定 480 s 窗口内注入 K=0/1/2/4 次故障，横轴为 K/480 s 的每集群小时换算。三系统使用相同外部时刻与 GPU，每次不可用 120 s；窗口内停机暴露分别为 0/120/240/420 GPU·s，末次修复越过窗口。纵轴为窗口内完成数/480 s。此范围为压力扫描；每点每系统一次模拟。 | [PDF](../../../output/pdf/aegiskv-revision-20260909/eval-failure-rate-throughput.pdf) · [SVG](../../../output/pdf/aegiskv-revision-20260909/eval-failure-rate-throughput.svg) · [PNG](../../../output/pdf/aegiskv-revision-20260909/eval-failure-rate-throughput.png) · [CSV](../../../output/pdf/aegiskv-revision-20260909/eval-failure-rate-throughput.csv) |

## 生成与实际检查

图稿采用 PaperBanana 的参考、规划、统一编码、原生生成与导出核对流程。Overview 参考 [Mooncake FAST25 Best Paper](https://www.usenix.org/conference/fast25/presentation/qin) 的资源拓扑与 [Ensō OSDI23 Best Paper](https://www.usenix.org/conference/osdi23/presentation/sadok) 的具体对象表达；Evaluation 参考 [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html) 的受控故障与进度跟踪。参考图与数据没有移植到本实验。

[Overview 审查](../../../output/pdf/aegiskv-revision-20260909/SYSTEM_OVERVIEW_REVIEW.md) · [重算预测来源](../../../output/pdf/aegiskv-revision-20260909/motivation-recompute-manifest.json) · [诊断图 manifest](../../../output/pdf/aegiskv-revision-20260909/diagnostics-manifest.json) · [扩展图 manifest](../../../output/pdf/aegiskv-revision-20260909/scaling-manifest.json)

[并发运行审计](../../../output/aegiskv-revision-20260909/scaling/RUN_AUDIT.json) · [并发原始证据归档](../../../output/aegiskv-revision-20260909/scaling/RAW_ARCHIVE.json) · [故障频率事件审计](../../../output/aegiskv-revision-20260909/scaling-rate/EVENT_AUDIT.json)。两扫描共享 C16/F0 三个点；24 个点对应 21 次不同的完整执行，其中 15 次为本轮新增。小回归单独计，不作为性能重复。

[独立 PDF 的 LaTeX](../../../output/pdf/aegiskv-revision-20260909/paper-figures.tex) · [可选同行组合](../../../output/pdf/aegiskv-revision-20260909/paper-pairs.tex) · [实际插入样张](../../../output/pdf/aegiskv-revision-20260909/paper-placement.pdf) · [中文预览](../../../output/pdf/aegiskv-revision-20260909/paper-story.html) · [交付检查](../../../output/aegiskv-revision-20260909/DELIVERY_AUDIT.json)

[逐 Workflow 并发配对](../../../output/pdf/aegiskv-revision-20260909/concurrency-workflow-manifest.json) · [固定追加故障图](../../../output/pdf/aegiskv-revision-20260909/fixed-event-wct-manifest.json) · [故障前日志核对](../../../output/aegiskv-revision-20260909/scaling-rate/FIXED_EVENT_PREFIX_AUDIT.json) · [全部 Workflow 的事件差值](../../../output/aegiskv-revision-20260909/scaling-rate/data/fixed-event-all-workflows.json)

绘图入口：[Motivation](scripts/paper/render_motivation_recompute.py)、[Overview](scripts/paper/build_revised_overview.py)、[诊断](scripts/paper/render_revision_diagnostics.py)、[吞吐扩展](scripts/paper/render_revision_scaling.py)、[并发逐对象比较](scripts/paper/render_concurrency_workflow.py)、[固定追加故障](scripts/paper/render_fixed_event_wct.py)。正文入口：[build_revision_story.py](scripts/paper/build_revision_story.py)，正文源：[revision-draft.md](scripts/paper/templates/revision-draft.md)。历史源快照、算法文件及原始图像保持冻结。
