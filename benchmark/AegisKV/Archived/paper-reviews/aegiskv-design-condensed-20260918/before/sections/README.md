# Background/Motivation 与 System Design 集成预览

`../main.tex` 连接现有 `background_and_motivation.tex` 与新建 `system_design.tex`。
它是 §2–§3 的英文集成初稿，不是完整投稿稿件。现有 Motivation 正文及图源未改写。

```sh
sh benchmark/AegisKV/paper/build.sh
```

从仓库根目录运行，输出 `benchmark/AegisKV/paper/main.pdf`；编译中间件在 `paper/build/`。
沿用本地 SIGPLAN 10 pt 配置和 7 × 9 inch 版心，关闭此两节预览的末页自动平衡，避免参考文献从第二栏开始时的平衡警告。
现有 `build-motivation.sh` 仍可单独编译背景动机。

## System Design 文件与图中编号

| 文件 | 内容 | Overview 索引 |
|---|---|---|
| `system_design.tex` | 章节入口 | — |
| `design_insights.tex` | 三个观察、设计启示、待解决的系统问题 | — |
| `system_overview.tex` | 三层职责、正常路径、预定接管位置、决策时间尺度 | — |
| `workflow_protection.tex` | Slack 估计、恢复代价、三种保护层级 | ① Tracker |
| `kv_placement.tex` | 保护单位、K 的大小与身份、流水线、L/F | ② Planner |
| `capacity_allocation.tex` | 窗口预算、整体准入、算法 1、物理水位 | ② Planner |
| `parallel_recovery.tex` | 故障信号、恢复上下文、并行 retry | ③ Recovery Manager |
| `kv_runtime.tex` | 副本提交、前台回收、逐请求装载与正确性 | ④ Adapter |
| `design_discussion.tex` | Slack/画像误差、接入条件与证据边界 | — |

Connector 仅作为传输执行接口出现，不设独立小节或编号。
`main.tex` 预加载 `subcaption`、`tabularx`，定义算法计数器，并加载两份既有 bibliography。
章节、公式和图全部使用语义标签，不手工在 LaTeX 中写图号。

叙事参考 [RcLLM 的 Insights and Motivation → System Design](https://arxiv.org/pdf/2605.07443)：
先说明观察支持什么，再说明由此产生的机会与系统挑战，最后引出组件和机制。
方法依据保留在 System Design，Background/Motivation 继续承担问题动机。
该参考只影响组织方式，不作为 AegisKV 数据或算法正确性的证据。

## 设计图与复现

当前 Overview 使用 `../figures/system-overview-v11.drawio`，按 `width=\columnwidth` **等比缩小**原矢量 PDF。
原图约 1.11:1；单栏 84.65 mm 下高度约 76.2 mm。编号 ①–④ 各一次，位于独立 `Paper annotations` 图层。
按 2026-09-18 用户纠正，取消高约 153 mm 的纵向重排；该候选 `system-overview-single.drawio` 仍保留。
原版整体缩小也使最小文字缩至约 5 pt；这是本次保留原图比例的实际结果，不再声称单栏达到 10 pt。
图源与导出说明见 [`system-overview-v11.md`](../figures/system-overview-v11.md)。

整稿编号为 Figure 1（Motivation 三子图）、2（重算代价）、3（时间预测、模型采用、retry KV 预测三联图）、4（Overview）、
5（retry KV 预算曲线）、6（恢复流水线）、7（等待与 Peer 字节）。Figure 3/5 的数据、负面结果、来源边界和复现命令见
[`design-insights/README.md`](../figures/design-insights/README.md)。第一项时间可预测性尚未获得正面验证；当前是证据初稿。
只有 Figure 1 和 Figure 3 的三图并排使用跨双栏 `figure*`；其余图包括 Overview 和 Figure 6 均用单栏 `figure`。
Figure 6 已移除完整重算参考行，只保留共用毫秒轴的四条恢复流水线 (a)–(d)。
Figure 3(b) 已替换为旧图的十版本发布时间—上下文布局。
拟补充的 HBM/DRAM/Recompute 同条件比较见 [`复用延迟实验设计`](../../experiments/plans/reuse-latency-insight.md)。
Figure 6 的单栏版本：

```sh
MPLCONFIGDIR=/tmp/aegiskv-mpl .venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_pipeline_single.py
```

其源数据与调度模型沿用原脚本，仅重排为 3.34-inch 原生宽度，保留 10.5 pt 图中文字；
逐项断言等待、尾部完成时间、驻留层数与 Peer MiB 均等于之前版本。旧 7-inch/10-inch 图不覆盖。
单栏图及独立清单位于 `figures/design-single/`。脚本不运行旧串行恢复评估。
Figure 3/5 使用 `figures/design-insights/` 的独立清单；其余设计统计图沿用原 PDF，数据和来源见 `figures/MANIFEST.json`。

本次核对材料位于 `output/pdf/aegiskv-design-integration-20260918/`，包括修订前快照、最终图宽检查、
实际论文页、编译日志和整合审查记录。当前正文明确区分原生轨迹、硬件代价校准、解析时间线与尚待验证的端到端系统。
后续 Overview v11 的逐轮导出与论文嵌入检查位于 `output/pdf/aegiskv-overview-v11/`。
当前单栏修订、图内页脚删除及旧 Figure 3(b) 查找记录在 `output/pdf/aegiskv-single-column-20260918/`。

---

# AegisKV LaTeX sections

`background_and_motivation.tex` 是 `../draft/background_and_motivation.md` 的英文论文初稿。`motivation-figures.tex` 将分支差异分布、中位数对应的三分支 Workflow、同例恢复损失组成跨双栏 Figure 1(a)–(c)，使用三个等宽 `subfigure`，共用总图注。`motivation-prefill-figure.tex` 为独立单栏 Figure 2（Full-prefill cost）；全文集成时由 LaTeX 自动编号。

## 格式与预览

按 [EuroSys 2027 CFP](https://2027.eurosys.org/cfp.html)（2026-09-18 核对）采用 ACM **SIGPLAN** 模板：双栏、内容位于 7 × 9 inch 版心内、栏间距至少 8 mm，正文、图内文字及图注至少 10 pt，行距至少 12 pt，并显示页码。仓库中的 `acmart.cls` 为 v2.19；独立预览入口是 `../motivation-preview.tex`。并排布局参考用户给出的 [RcLLM 论文](https://arxiv.org/pdf/2605.07443) PDF 第 4 页的跨双栏图区；Figure 1 按用户要求使用一个 Figure 的三个子图；Full-prefill cost 单独作为 Figure 2。

预览使用 `sigplan,10pt,anonymous,nonacm`；`sigplan` 已启用双栏，`nonacm` 仅隐藏本节预览不需要的出版信息。预览显式将默认 8 pt 的参考文献和页码改为 10 pt，正文及图注使用模板的 10 pt / 12 pt 设置。全文主文件也需保留 `\renewcommand{\bibfont}{\normalfont\normalsize}`，不能依赖模板默认的参考文献字号。编译日志记录实际版心 505.89 × 646.0 TeX pt、栏间距 24 pt、正文行距 12 pt；未压缩页边距或行距。

从仓库根目录编译：

```sh
sh benchmark/AegisKV/paper/build-motivation.sh
```

输出为 `output/pdf/aegiskv-motivation-eurosys2027/motivation-preview.pdf`。这是本节的独立预览，不是完整投稿稿件。集成全文时，在 `paper/` 下的主文件中使用：

```latex
% In the preamble (acmart already loads caption):
\usepackage{subcaption}
% In the document body:
\input{sections/background_and_motivation}
% At the end of the manuscript:
\bibliographystyle{ACM-Reference-Format}
\bibliography{references,sections/background_and_motivation}
```

## 图与证据

并排版本位于 `../figures/motivation-row/`，原单栏图保留。Figure 1 的子图目标尺寸为 2.24 × 1.85 inch（宽度为 7 inch 的 0.32 倍），比前版 2.65 inch 高度减少约 30%；通过调整绘图区、单行横轴标签和 Workflow 节点间距实现，不对导出图进行非等比缩放。两张统计子图的文字为 10.25 pt；Workflow 原生 Draw.io PDF 按上述宽高上限等比插入后，文字约 10.76 pt。Figure 2 的原生宽度为 3.34 inch、文字为 10.25 pt，按模板单栏宽度插入后约 10.23 pt；不能进一步缩小后仍宣称满足 10 pt 要求。图内不放标题或 WCT 损失公式，图 1(a) 不放前缀重算参考线。图 1(c) 的图例、坐标和 Slack 数值保留；省略了与柱长重复的右侧 Loss 数值列。

重新导出三张统计图：

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py
```

仅更新 Figure 1(a) 时，追加 `--only gap`，保留 Figure 1(c) 和 Figure 2。仅更新 Figure 1 的两张统计子图时，追加 `--only figure1`；此选项保留现有 Figure 2 文件和清单记录。仅替换实例对应的 Figure 1(c) 时，追加 `--only example`，同时保留 Figure 1(a)。Workflow 另按下方命令重建。

该脚本复用原绘图脚本的数据读取与校验，不改原始数据、单栏图或共享清单。独立 `../figures/motivation-row/MANIFEST.json` 记录输入哈希、插入尺寸、字体及三个反事实的数值。图 1(a) 是通过时序 fan-in 筛选后每个工作流的最大分支时间差，不能解释为故障时 Slack；图 1(b) 为其中中位数样本对应的三分支时间线，以首个分支启动为零点，条长表示真实持续时间，末端虚线表示假设汇合关系下的 Slack；图 1(c) 是同例跨模型代价替换的说明性反事实；图 2 区分 PCIe 实测与 SXM 静态估计。层序、热度与具体恢复机制由设计章承担。

Figure 1(a) 当前使用 `experiments/data/motivation-fanin-cc/`：先检查全部 292 个严格重叠组，要求分支均完成、其后存在晚于或等于最后分支结束时刻的 Main 请求；允许 Main 在分支运行期间执行或提交其他请求。保留 286 组、121 个工作流，再按工作流取最大时长差；中位数 137.758 s，P90 1,172.684 s。被保留组中有 96 组存在期间提交的 Main 请求。此判据只能推断 fan-in，不能证明全部输出被后继消费；原轨迹没有显式依赖字段。审计包括每个组的完成状态、Main 时刻、保留/排除原因与源行哈希；原 124 工作流数据保留用于追溯。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_fanin_groups.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only gap
```

2026-09-18 全文整合已同步 `draft/system_design.md` 的图号及重算交叉引用；本节 LaTeX 使用语义标签 `fig:motivation-recompute`，不硬编码该图号。总图标签为 `fig:motivation`；正文用 `Figure~\ref{fig:motivation}(\subref{fig:motivation-workflow})` 等形式引用子图；独立图 2 使用 `Figure~\ref{fig:motivation-recompute}`。


## Workflow 图源

`../figures/motivation-row/motivation-workflow.drawio` 保留可编辑节点与连线；`.drawio.pdf` 和 `.drawio.png` 是原生 Draw.io 导出，并嵌入图源。`motivation-workflow.json` 记录 CSV、trace 摘录、筛选清单的哈希，以及真实 branch/agent ID、完成时刻和 Slack。当前实例为 `cfad46925e9d22c6ffb3e0cc4bb925a8a5e3` 的第二组：三分支时长差 137.758 s 恰为 Figure 1(a) 中位数，且该组是该工作流贡献给 ECDF 的最大差值组。选例先按与中位数的距离排序，不按恢复代价或 WCT 损失排序。

Main → A1–A3 → Main 为推断的依赖关系；分支最晚结束于 6,029.269 s，后续 Main 请求始于 6,032.459 s。显示时减去首个分支开始时刻 5,772.526 s，即汇合在 256.743 s；真实持续时间不缩放。A1–A3 持续时间分别为 178.842、253.542、115.784 s，A2 条形最长且最晚完成。条形末端虚线按同一比例表示 Slack。Main 方框及分叉连接不编码 Main 执行时长；`time_mapping` 保留原始时间原点、共同比例、条形几何及相对刻度。

故障时刻为原始工作流时钟 5,839.9 s，即扇出后 67.374 s，处于三个分支均有活跃 LLM 请求的区间 [5,838.619, 5,841.140] s。将分支公共重叠区间按请求边界分段，选择中点最接近公共区间中点的全活跃分段；取至 0.1 s 后仍须位于段内，不按恢复结果选择时刻。三个前缀为 99,520、107,968、111,168 tokens，均在实测代价曲线内；重算为 16.143、17.773、18.396 s，Slack 为 77.901、0、135.118 s，WCT 损失为 0、17.773、0 s。无需人为制造部分吸收。

`experiments/data/motivation-median-cc/SELECTION.json` 记录选例与时刻规则、总体输入哈希及精确中位数；`selected-trace-excerpt.json` 保存分支属性及活跃请求（含 hash IDs），`median-example-failure-position.csv` 是 (b)/(c) 的共同输入。旧 `motivation-short-cc/`、`motivation-real-cc/` 数据保留。本例代表中位数时长差，不代表总体平均故障损失；代价仍是 MiniCPM4 实测内插，不是原服务系统的故障重放。

从原始 trace 重建选例数据（路径可替换为任意字节一致的副本）：

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_median_example.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only example
```

从仓库根目录重建：

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 3 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.png benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.pdf benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
```
