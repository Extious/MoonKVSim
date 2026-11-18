# Abstract、Background/Motivation 与 System Design 集成预览

`../main.tex` 连接 `abstract.tex`、`background_and_motivation.tex` 与 `system_design.tex`。
它是摘要与 §2–§3 的英文集成初稿，不是完整投稿稿件。现有 Motivation 正文及图源未改写。
`abstract.tex` 使用 ACM 的 `abstract` 环境，在 `\maketitle` 前载入；内容依据当前英文正文，
从 Multi-Agent 场景引出多级存储中的 workflow-aware KV 容错管理，重点说明基于工作流依赖与
Slack 的请求间保护，以及基于稀疏访问需求的请求内块放置；摘要不绑定具体预测模型。

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
| `workflow_protection.tex` | §3.3：GBDT 剩余时间预测、agent 执行段、CPM Slack 传播与算法 1 | ① Tracker |
| `parallel_recovery.tex` | §3.4：请求到达时绑定 retry 目标和 Peer DP rank，故障后并发重路由 | ② Recovery Manager |
| `kv_placement.tex` | §3.5：固定 Z、R/D/P 层级、逐请求 L_r、候选热块和算法 2 | ③ KV Master |
| `kv_runtime.tex` | §3.6：逐窗口 Peer 总预算与前台容量保留 | ④ Adapter |
| `capacity_allocation.tex` | §3.6 内的物理容量检查、增量准入与引用保护，由 `kv_runtime.tex` 引入 | ④ Adapter |
| `design_discussion.tex` | §3.6 末尾的简短适用边界段落 | — |

Connector 仅作为传输执行接口出现，不设独立小节或编号。
`main.tex` 预加载 `subcaption`、`tabularx`，定义算法计数器，并加载两份既有 bibliography。
章节、公式和图全部使用语义标签，不手工在 LaTeX 中写图号。

叙事参考 [RcLLM 的 Insights and Motivation → System Design](https://arxiv.org/pdf/2605.07443)：
先说明观察支持什么，再说明由此产生的机会与系统挑战，最后引出组件和机制。
方法依据保留在 System Design，Background/Motivation 继续承担问题动机。
该参考只影响组织方式，不作为 AegisKV 数据或算法正确性的证据。

## 设计图与复现

当前 Overview 保留 `../figures/system-overview-v11.drawio` 原生可编辑源与比例，按本轮外部评审修订明确允许的双栏 `width=\textwidth` 放置。普通标签最小值在独立论文预览中为 10.44 pt；不再使用产生约 4.97 pt 小字的单栏插入。没有通过非等比拉伸或缩小字号压图；历史单栏版本和纵向候选保留作追溯。编号 ①–④ 仍各一次，位于独立 `Paper annotations` 图层。
图源与导出说明见 [`system-overview-v11.md`](../figures/system-overview-v11.md)。

整稿编号为 Figure 1（Motivation 三子图）、2（三路径恢复延迟估计）、3（三项 Insight）、4（Overview）、5（恢复流水线）。
原 Figure 5（retry KV 预算敏感性）与原 Figure 7（等待/Peer 字节扫描）已移出正文，图源及数据保留供后续 Evaluation；
原 Figure 6 因此顺次成为 Figure 5；后续紧凑排版保持其四条流水线的数据不变。
Figure 3 的来源、负面结果和复现见 [`design-insights/README.md`](../figures/design-insights/README.md)。
第一项时间可预测性尚未获得正面验证；压缩没有将其改写为成立的结论。
只有 Figure 1 和 Figure 3 使用跨双栏 `figure*`，其余图均为单栏。
Figure 3(b) 已替换为旧图的十版本发布时间—上下文布局。
HBM/DRAM/Recompute 暂定静态估计及后续物理协议见 [`复用延迟实验设计`](../../experiments/plans/reuse-latency-insight.md)。
当前 Figure 5（原 Figure 6）的单栏生成命令：

```sh
MPLCONFIGDIR=/tmp/aegiskv-mpl .venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_pipeline_single.py
```

其源数据与调度模型沿用原脚本，原生尺寸为 3.34 × 3.05 inch，当前采用 Linux Libertine 10.05 pt 图中文字；
逐项断言等待、尾部完成时间、驻留层数与 Peer MiB 均等于之前版本。旧 7-inch/10-inch 图不覆盖。
单栏图及独立清单位于 `figures/design-single/`。脚本不运行旧串行恢复评估。
Figure 3 与移出的预算图使用 `figures/design-insights/` 独立清单；其他保留素材的数据与来源见 `figures/MANIFEST.json`。

本次核对材料位于 `output/pdf/aegiskv-design-integration-20260918/`，包括修订前快照、最终图宽检查、
实际论文页、编译日志和整合审查记录。当前正文明确区分原生轨迹、硬件代价校准、解析时间线与尚待验证的端到端系统。
后续 Overview v11 的逐轮导出与论文嵌入检查位于 `output/pdf/aegiskv-overview-v11/`。
当前单栏修订、图内页脚删除及旧 Figure 3(b) 查找记录在 `output/pdf/aegiskv-single-column-20260918/`。

## 当前组件职责（2026-09-19 外部评审修订）

§3.4 Recovery Manager 在到达时固定 retry/Peer 目标并组织并发恢复；§3.5 KV Master 在固定 Z、prefill 完成及策略事件中决定 tier、逐请求 L 和热集；§3.6 Adapter 只按时间窗口更新 Peer 总预算 Bp。

K 是每请求每层已提交的 Peer 驻留块数，候选 quota 另行声明。普通请求不能抢占活跃引用；owner 可以替换自己的热集，Adapter 必要缩容可以将带引用副本降级到 DRAM。物理释放遵守 DRAM commit、原子目录/lease 切换、drain、free 的顺序，共享对象与在途空间持续计账。

算法 2 给出条件故障样本上的深度评分和 profile/区间回退；算法 3 包含必要的受保护副本降级，不等整个长 decode 结束才回收。并发恢复保留公平资源份额与逐层就绪执行，不把 Slack 排序变为请求级串行恢复。具体复算接口见 [depth-policy-contract-20260919.md](../draft/supporting/depth-policy-contract-20260919.md)。

Figure 4 改用保持比例的双栏放置，实际普通标签 >=10 pt；Figure 3/5 数据与源图未变。摘要不再声称已验证的 WCT 收益或可忽略正常开销。独立编译与验证位于 `output/pdf/aegiskv-external-review-revision-20260919/`；已在动机任务完成后统一更新主 PDF：12 页、27 个引用解析成功，无 Overfull 或未定义引用；最终回执见同目录 FINAL_HANDOFF.md。新规则仍需实现与端到端实证。

## System Design 篇幅压缩（2026-09-18）

本轮保留三个 Insight、Overview、完整放置算法与四条恢复流水线，合并重复机制介绍、图注和局限说明。
移出预算/足迹敏感性图、详细校准与计数/带宽算例；删除单独的时间尺度表与重复的局限小节，必要条件留在对应机制处。
未缩小正文、图注、行距或页边距；Overview 沿用先前的等比单栏版本，约 5 pt 图内文字仍是投稿前要修正的已知问题。
正文源的空白分词计数（含 LaTeX 标记）由 4,638 降为约 2,100，System Design 从约 7 页降至约 3.5 页。
本次整稿 7 页含参考文献，正文延伸至第 6 页上部；Motivation 正文/图形未改。

长稿和后续 Evaluation 素材见 [`design-full-20260918`](../draft/supporting/design-full-20260918/README.md)。
修订前快照、编译日志、实际 PDF 页和语义/范围核对在 `output/pdf/aegiskv-design-condensed-20260918/`。

## Figure 3 / Figure 5 紧凑布局（2026-09-18）

Figure 3 的面板从 2.24 × 2.65 inch 改为 2.24 × 2.05 inch（高度减少约 23%），三图仍跨双栏，文字仍为 10.25 pt。压紧顶部图例、底部留白与子图标题间距，完整方法名及预算条件留在图注和来源说明。
Figure 5 从 3.34 × 4.70 inch 改为 3.34 × 3.40 inch（高度减少约 28%），保持单栏和 10.5 pt 文字；每条时间线用一行策略标题，右侧对齐总耗时/等待耗时，共用单位说明和横轴。
两图通过重排源图实现，无非等比缩放；所有数据、时间轴范围和误差线保持不变。实际导出及嵌入页检查位于 `output/pdf/aegiskv-compact-figures-20260918/`。

## 图引用与第二轮紧凑排版（2026-09-18）

正文三个 Insight 分别引用 Figure 3(a)、(b)、(c)，恢复流水线解释对应 Figure 5(a)–(d)；Figure 1、2、4 已有正文引用。原 §3.4 与 §3.5 合为 §3.4 KV Placement Planner，依次说明选块、层数与预算准入。保留 `capacity_allocation.tex` 作为内部段落文件，旧节标签仍指向合并后的 §3.4；Recovery Manager 和 Adapter 顺次成为 §3.5、§3.6。

Figure 3 面板当前为 2.24 × 1.85 inch，较上一轮再降低约 10%；Figure 5 当前为 3.34 × 3.05 inch，再降低约 10%。保留原字体和数据；Figure 5 仅底部显示公共时间轴，避免四行重复轴线。核对记录及编译页见 `output/pdf/aegiskv-design-followup-20260918/`。

## Figure 3 / Figure 5 字体调整（2026-09-18）

两轮尺寸压缩后，用户澄清主要问题是部分图中文字过大。本轮改用与正文一致的 Linux Libertine，将原生字号从 10.25/10.5 pt 调为 10.05 pt；Figure 5 仅 (a)–(d) 加粗，策略标题用常规字重。图宽、高度、数据、正文图引用和合并后的节结构保持不变。该字体调整仅用于 Figure 3/5，不改变 Motivation 的字体配置。复核与前后快照位于 `output/pdf/aegiskv-design-typography-20260918/`。

---

## GBDT 与 CPM 算法（2026-09-18）

按用户确认，§3.3 以算法 1 给出 GBDT 剩余时间预测、CPM 前向/后向传播和请求 Slack 更新。父子 agent 在 fork/join 处划分执行段，避免重复计算等待；输入仅包含当时可见的特征。未知依赖结构或缺失预测返回零 Slack。恢复代价、层级阈值与滞回移入 §3.4，原完整足迹放置顺次成为算法 2。图 3(a) 的负面诊断结果和图源数据保持不变，不将本轮论文算法规格视为新训练结果或完整 Tracker 的验证。中文草稿与图源说明同步更新；编译和 CPM 数学核对记录在 `output/pdf/aegiskv-gbdt-cpm-20260918/`。

# AegisKV LaTeX sections

`background_and_motivation.tex` 是 `../draft/background_and_motivation.md` 的英文初稿。`motivation-figures.tex` 将时长差分布、四分支真实 Workflow、同例恢复损失组成跨双栏 Figure 1(a)–(c)。`motivation-prefill-figure.tex` 保留稳定文件名和语义标签，内容已扩展为独立单栏 Figure 2 的三路径恢复估计。

## 格式与预览

按 [EuroSys 2027 CFP](https://2027.eurosys.org/cfp.html)（2026-09-18 核对）采用 ACM **SIGPLAN** 模板：双栏、内容位于 7 × 9 inch 版心内、栏间距至少 8 mm，正文、图内文字及图注至少 10 pt，行距至少 12 pt，并显示页码。仓库中的 `acmart.cls` 为 v2.19；独立预览入口是 `../motivation-preview.tex`。并排布局参考用户给出的 [RcLLM 论文](https://arxiv.org/pdf/2605.07443) PDF 第 4 页的跨双栏图区；Figure 1 按用户要求使用一个 Figure 的三个子图；三路径恢复延迟单独作为 Figure 2。

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

## 当前图与证据（2026-09-18）

按用户最新指令，暂停实机实验并采用暂定 AIConfigurator 数据。Figure 1 子图尺寸为 2.24 × 1.85 inch，为四个分支保留可读行距；图中文字至少 10 pt，采用紧凑横向布局，不压缩字形或非等比缩放。Workflow 的短条不再容纳标签：Agent ID 单列，持续时间单列，条形长度、起止位置和 Slack 虚线仍共享真实时间比例。

- (a) 数据不变：286 个时序 fan-in 组、121 个 workflow-max 样本；中位数 137.758 s，P90 1172.684 s。Main 在分支执行期间可以活动；后续 Main 请求仅支持时序 fan-in 推断，不证明结果依赖。
- (b) `631738ac31321409f3a8de750fd5cd0ea334` 第 20 组，4 个分支，时长 60.370/151.612/132.409/129.429 s，gap 91.242 s。属于同一批 fan-in 组，但不是所属 workflow 的最大值，不冒充 (a) 中的单个样本。首分支绝对起点 75943.648 s；A2 决定相对 151.618 s 的汇合，Main 在 157.354 s 继续。
- (c) 相对 29.452 s 的四个独立反事实；同一 Qwen3-14B 静态成本配置与 64-token 假设尾部，未改模型以改变效果。A1–A4 的成本 35.207/32.180/36.706/38.922 s，Slack 91.248/0/19.096/21.915 s，loss 0/32.180/17.610/17.007 s，分别展示全部吸收、全部暴露和部分吸收。
- Figure 2 原生 3.34 × 2.35 inch，单栏单坐标，颜色区分三路径、线型/标记区分四模型。Qwen3-14B（YaRN，TP1）到128K，Llama-3.1-70B（TP4）到128K，Qwen3-235B-A22B-Instruct-2507（TP/EP16）到1,010,000，DeepSeek-V3.2（DSA，TP/EP32）到官方配置160K。横轴为总长度C=M+64；Recompute统一8K连续分块，全部路径排除不参与KV重建的词表投影。H100-SXM80GiB/BF16/batch1/PP1；25个形状、75个路径值均通过静态容量检查，最大77.817GiB/卡。DRAM每rank64GB/s为假设。Qwen2507大于256K为全注意力成本外推，未建模DCA或稀疏内核加速；DSA表只到32K，cached-prefix查询使用解析前缀修正。所有值均为CPU估计，无实机或长文本精度验证。

数据、完整条件和仍缺的物理验证见 [`静态估计数据`](../../experiments/data/reuse-aiconfigurator-max-context-h100/README.md)、[`四分支实例`](../../experiments/data/motivation-compact-cc/README.md) 与 [`恢复延迟计划`](../../experiments/plans/reuse-latency-insight.md)。旧 `motivation-wide-cc`、`motivation-median-cc`、`motivation-short-cc` 和 `motivation-real-cc` 保留。设计章的 Overview 和 Insight 图源不在此次修改范围。

## 复现数据与图

从仓库根目录运行。当前 Figure 2 使用 H100 跨架构矩阵；Figure 1(c) 独立保留旧 A100/Qwen3-14B 成本及来源哈希。两图不再声称硬件配置相同，旧矩阵不要为排版而重跑。若重建 Figure 1 数据，先按实例 README 从固定 trace 重建 CSV，再生成其独立静态代价。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_compact_example.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/reuse-aiconfigurator-max-context-h100/estimate_reuse.py
MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/motivation-compact-cc/estimate_costs.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 3 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.png benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.pdf benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
sh benchmark/AegisKV/paper/build-motivation.sh
sh benchmark/AegisKV/paper/build.sh
```

统计图脚本支持 `--only gap`、`--only example`、`--only figure1`、`--only figure2`，用于分别更新 (a)、(c)、(a)+(c)、独立 Figure 2，保留其他统计图与清单记录；默认导出全部统计图。Draw.io 源和嵌入原生导出的 cells 应一致。`MANIFEST.json`、`motivation-workflow.json` 记录输入、输出、时序几何与反事实数值；`FIGURE_REVIEW.json` 记录最终插入尺寸、实际页面检查和证据边界。图号由 LaTeX 自动产生，总图标签 `fig:motivation`，独立 Figure 2 仍使用 `fig:motivation-recompute`。
