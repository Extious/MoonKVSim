# Evaluation 重新设计的图稿与证据审查

[论文初稿](Paper_Draft_BeforeDiagnosis_20260909.md) · [实验协议与图稿规格](EVALUATION_DESIGN.md) · [历史冻结审查](PAPER_FIGURE_REVIEW_BeforeEvaluation_20260909.md)

当前正文包含 3 张 Motivation、1 张 Overview、7 张 Evaluation，共 11 张独立图。Evaluation 七张是 source-v3 历史数据的新诊断视图；不是新算法实验，也尚不能支持无服务开销或稳定故障收益。四张空扫描布局单独保存在实验设计文档，后三类扩展保留文字位置。

本轮采用 PaperBanana 的参考检索、内容规划、统一风格、原生绘制与实际导出检查流程。统计图由真实历史数据计算，没有生成或修饰不存在的收益。每张图的点是 Workflow / 固定 case，而不是运行编号。

## 图稿

| 正文图 | 证据与边界 | 独立导出 |
|---|---|---|
| [1 并行分支的执行时间不均衡](Paper_Draft_BeforeDiagnosis_20260909.md#paper-motivation-branch-gap) | CC/Weka 中 124 个具有重叠分支的 Workflow；每个对象取最大分支持续时间差。横轴为对数秒。该观测描述不均衡，不直接估计可用 Slack。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.pdf) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.svg) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.png) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/motivation-branch-gap.csv) |
| [2 重算代价与 Workflow 损失并不等价](Paper_Draft_BeforeDiagnosis_20260909.md#paper-motivation-recovery-exposure) | 同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.pdf) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.svg) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.png) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/motivation-recovery-exposure.csv) |
| [3 长上下文 KV 的容量约束](Paper_Draft_BeforeDiagnosis_20260909.md#paper-motivation-kv-capacity) | Qwen3-8B BF16 的解析容量，Ki=1,024。参考线从 40 GiB 扣除模型权重与 2 GiB runtime，尚未扣除动态前台 KV，不能当作可借备份额度。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.pdf) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.svg) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.png) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/motivation-kv-capacity.csv) |
| [4 AegisKV System Overview](Paper_Draft_BeforeDiagnosis_20260909.md#paper-system-overview) | 源端独立向 Peer HBM 和 DRAM 复制同名 KV；复制确认后才可读取。Workflow 价值与池级准入决定保护对象，独立控制器约束 Peer 显存借用。故障后从可用层装入新的 primary C0、C1，再重算 C2。实线为数据，虚线为控制。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/system-overview.pdf) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/system-overview.svg) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/system-overview.png) · [DRAWIO](../figures-legacy/aegiskv-evaluation-20260909/system-overview.drawio) |
| [5 正常执行的逐 Workflow 相对开销](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-healthy-workflow) | 历史 source-v3 模拟的全部 160 个配对 Workflow；每点为同一对象相对 Mooncake 的 WCT 变化。零线为 Mooncake，负值更快。沿用基准 F0 排序；连线不是时间轴。每配置一次执行，不绘制跨重复置信区间。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-workflow.csv) |
| [6 DRAM 准入对正常复用的影响](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-healthy-reuse) | 与前图相同的对象和顺序，纵轴为 DRAM token 命中率的百分点变化。分母包含所有冷访问与重访 prompt token，排除恢复 token；总体命中率按 token 加权，不能对这些点直接求平均。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-reuse.csv) |
| [7 前台等待、控制计算与传输的分项成本](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-healthy-resources) | 各行独立除以同指标 Mooncake 值；横轴为对数倍率。参考 CPU 是 Python 实测，其余为未标定模拟。累计等待、队列分位数和流量不能相加；GET 样本总体随命中策略变化。该图不含尚未采集的原生进程 CPU 与逐 GPU HBM 峰值。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-healthy-resources.csv) |
| [8 同一故障焦点 Workflow 的完整 WCT](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-failure-wct) | C1–C3 是预选的三个不同故障实例；每组只比较同一个焦点 Workflow。分母是同例 Mooncake F1 WCT，1 为基准。历史触发只对齐逻辑请求和 token 进度，尚未固定全部受影响对象；这些点不是新协议结果。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-wct.csv) |
| [9 扣除正常成本后的配对故障增量](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-failure-increment) | 每个点先计算自身 F1−F0，再除以同例 Mooncake F0 WCT。三系统使用共同分母；保留负值。闭环调度可改变等待，因此负增量不能解释为故障有益。C1–C3 不是随机重复，未拟合趋势或置信区间。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-increment.csv) |
| [10 恢复阶段为何不能代替完整 Workflow 收益](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-failure-recovery) | 同一 C1–C3 焦点请求的两个相邻区间：故障至前缀可读（含检测、路由与装入），以及前缀可读至恢复解码（含后缀重算与排队）。区间内的操作尚未细分；柱终点未包含后续 DAG 终点。阶段较短并不保证完整 WCT 更短。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-recovery.csv) |
| [11 恢复来源与剩余重算](Paper_Draft_BeforeDiagnosis_20260909.md#paper-eval-failure-kv) | 三个焦点请求的历史 token 计数，系统与前图逐行对齐。Ki=1,024。仅统计 Peer 恢复、DRAM 恢复和重算，不是全部上下文的百分比。所有 Peer 恢复均为零；不能把前图的阶段改善归因于 Peer。 | [PDF](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.pdf) · [PNG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.png) · [SVG](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.svg) · [CSV](../figures-legacy/aegiskv-evaluation-20260909/eval-failure-kv.csv) |

## 本轮修正的解释问题

- 逐 Workflow 绝对 WCT 改为同 ID 相对开销，保留全部 160 个对象和极值。
- 故障图改为三个预选焦点 Workflow 的配对 WCT 与共同分母增量；完整批次的既有不利均值仍在正文陈述、原图归档。
- 从实际 FAILURE_INJECT 日志确认旧触发口径是总请求 token 进度 60%，并非精确的 prefill-only 60% 或新方案 decode 第 8 token；新旧协议分开。
- 明示历史 impact_contract_scope=OBSERVED_ONLY；布尔字段通过不等于三系统丢失集合相同。每例的目标、实际受害者和触发日志另存于 legacy-failure-contracts.json。
- 只分解能相加的两个恢复阶段；不把 suffix+queue+resume 统称 GPU 重算，不把 resume 当成 DAG 完成。
- 恢复来源保留 Peer=0；DRAM-only 完整标名，避免 M/D/A 等未解释缩写。
- 请求平均 TPOT 的 P99 与真实逐 token TBT P99 分开；后者仍待采集。
- 未执行的故障频率与并发扫描只显示标注 LAYOUT ONLY 的空轴，不填曲线。

## 复现和检查

绘图源：[render_evaluation_redesign.py](scripts/paper/render_evaluation_redesign.py)；正文源：[evaluation-draft.md](scripts/paper/templates/evaluation-draft.md)；生成入口：[build_evaluation_redesign.py](scripts/paper/build_evaluation_redesign.py)。旧 build_agent_lease_index.py 也会路由到当前版。

[逐点数据与文件哈希](../figures-legacy/aegiskv-evaluation-20260909/manifest.json) · [图像 LaTeX](../figures-legacy/aegiskv-evaluation-20260909/paper-figures.tex) · [可选同行组合](../figures-legacy/aegiskv-evaluation-20260909/paper-pairs.tex) · [实际插入尺寸 PDF](../figures-legacy/aegiskv-evaluation-20260909/paper-placement.pdf) · [中文浏览器预览](../figures-legacy/aegiskv-evaluation-20260909/paper-story.html)

[本版检查记录](../../../output/evaluation-redesign-20260909/DELIVERY_AUDIT.json) 只覆盖数据变换、图像和排版；不是原生性能证明。旧 source-v3 的 51 次执行与源码证据继承已冻结审查，本轮未再运行或改写。新协议仍缺冻结 case、SLO、原生硬件和正式 commit。
