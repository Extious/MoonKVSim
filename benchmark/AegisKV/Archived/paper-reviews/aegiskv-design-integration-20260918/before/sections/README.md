# AegisKV LaTeX sections

`background_and_motivation.tex` 是 `../draft/background_and_motivation.md` 的英文论文初稿。`motivation-figures.tex` 将分支差异分布、五分支 Workflow 结构、恢复损失组成跨双栏 Figure 1(a)–(c)，使用三个等宽 `subfigure`，共用总图注。`motivation-prefill-figure.tex` 为独立单栏 Figure 2（Full-prefill cost）；全文集成时由 LaTeX 自动编号。

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

仅更新 Figure 1 的两张统计子图时，追加 `--only figure1`；此选项保留现有 Figure 2 文件和清单记录。仅替换实例对应的 Figure 1(c) 时，追加 `--only example`，同时保留 Figure 1(a)。Workflow 另按下方命令重建。

该脚本复用原绘图脚本的数据读取与校验，不改原始数据、单栏图或共享清单。独立 `../figures/motivation-row/MANIFEST.json` 记录输入哈希、插入尺寸、字体及五个反事实的数值。图 1(a) 是每个工作流一个最大分支时间差样本，不能解释为故障时 Slack；图 1(b) 为同一五分支实例的聚合拓扑，标注分支完成时刻以解释汇合 Slack；图 1(c) 是跨模型代价替换的说明性反事实；图 2 区分 PCIe 实测与 SXM 静态估计。层序、热度与具体恢复机制由设计章承担。

此轮不修改 `draft/system_design.md` 或总览图。设计章旧的“图 4”重算交叉引用及其图号，需要在全文编号整合时同步；本节 LaTeX 已使用语义标签 `fig:motivation-recompute`，不硬编码该图号。总图标签为 `fig:motivation`；正文用 `Figure~\ref{fig:motivation}(\subref{fig:motivation-workflow})` 等形式引用子图；独立图 2 使用 `Figure~\ref{fig:motivation-recompute}`。


## Workflow 图源

`../figures/motivation-row/motivation-workflow.drawio` 保留可编辑节点与连线；`.drawio.pdf` 和 `.drawio.png` 是原生 Draw.io 导出，并嵌入图源。`motivation-workflow.json` 记录 CSV、trace 摘录、筛选清单的哈希，以及真实 branch/agent ID、完成时刻和 Slack。当前实例为 `81fad784ca8c3f4136179dc73184409d21a2` 的第一个扇出，保留 Main → A1–A5 → Main 的画法；节点内为**完成时刻**，不是持续时间；结构图不按时间比例绘制。A5 最晚完成，描边与字体加粗，灰度下仍能识别。

用户要求替换为 Agent 执行时间更短的实例。对相同 SHA-256 的 393 条原始 trace 重新筛选，15 个严格重叠五分支扇出中，当前实例的最长分支持续时间最短；五个持续时间为 50.309、40.618、59.117、54.677、46.721 s。保留全部真实时间戳，未缩放或移动时间原点。故障时刻为 76.0 s，处于五个分支均有活跃 LLM 请求的公共区间 75.855–76.226 s。该区间中点最接近分支公共重叠区间中点；取至 0.1 s 后仍在区间内。五个前缀为 57,984–95,744 tokens，均在实测代价曲线覆盖范围内。

`experiments/data/motivation-short-cc/SELECTION.json` 保留全部五分支候选和筛选规则，`selected-trace-excerpt.json` 保存选中分支的原始属性及故障时请求（含 hash IDs），`short-example-failure-position.csv` 为子图 (b)/(c) 的共同输入。原 `motivation-real-cc/` 数据不覆盖。这个刻意选择的短分支例子说明保护价值差异，不用于估计总体故障影响；代价仍是 MiniCPM4 实测内插，不是原服务系统的故障重放。

从原始 trace 重建选例数据（路径可替换为任意字节一致的副本）：

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_short_example.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only example
```

从仓库根目录重建：

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 3 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.png benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio.pdf benchmark/AegisKV/paper/figures/motivation-row/motivation-workflow.drawio
```
