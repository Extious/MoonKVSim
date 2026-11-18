# 两类 workflow 的论文集成与新实验设计

后续样式修正：用户要求 Background/Motivation 沿用之前的图像风格，现有五张图的最新可编辑源、生成器和审查在 [background-motivation-style-20261005](../background-motivation-style-20261005/README.md)。本目录保留应用/实验设计及其原始交付快照。重建本目录的旧外观后，必须再按该样式修正目录覆盖五张图，才与当前 `paper/main.pdf` 一致。

当前论文：[paper/main.pdf](../../paper/main.pdf)。本轮保留现有完整稿件及打开的 Design 源，在原文件中更新 Background/Motivation，同步失效的 Design 示例和其他章节的旧结果陈述。原内容保存在 `before/` 与 `BEFORE_MANIFEST.json`。没有将旧结果替换标签作为新测量。

## 已交付

- [两类 Agent-task DAG](application-workflows.pdf)：研究报告与仓库 issue/change review，节点7/8、边8/10，从左到右。内部多轮省略，任务依赖与原设计一致。研究角色扩展到适配的比较研究，不限于软件市场。
- [可编辑 DAG 源](sources/application-workflows.drawio)，以及 `native/` 中带嵌入源的 PNG/SVG/PDF。
- Motivation 的三个机制图：`schematics/workflow-recovery-exposure.pdf`、`recovery-demand-placement.pdf`、`foreground-replica-capacity.pdf`。均是标注为 illustrative 的机制示意，不是新实验观察。
- 同步后的 `schematics/master-selection.pdf`：采用同一归一化示例，不再引用旧秒数。
- [新 trace/配对实验协议图](evaluation-protocol.pdf)、[可编辑源](sources/evaluation-protocol.drawio)。真实应用运行与独立质量验证、保留依赖触发的服务回放分别定义。
- [完整实验协议](../../docs/workflow-evaluation-20261005/README.md)：E0–E11、baselines、故障/预算公平性、质量、统计、硬件/模型冻结与证据门槛。
- [11类测量图设计](../../docs/workflow-evaluation-20261005/FIGURE_PLAN.md)、[图谱](experiment-figure-atlas.pdf)、机器可读图/采集/campaign合同。图谱是排版与内容设计，不含测量值或假趋势。

## 验证和范围

`FIGURE_REVIEW.json` 记录独立依赖检查、可编辑 PNG 与所选页源结构一致、PDF 物理宽度、实际嵌入字体、编译和人工查看范围。两张 DAG 与协议图按168 mm；四个机制图按实际单栏84.68 mm，字体至少10 pt。所有最终 PDF 为矢量图，已查看彩色、灰度与实际论文页面；修正了图例碰轴、文字出界和协议连线穿过节点。

本会话未暴露 `compile_latex_document`，使用项目自带 `build_paper.sh` 检查同一 canonical 文稿并发布 `paper/main.pdf`。最终编译没有错误、未解析引用或 overfull hbox；未变更部分原有的版式/书目信息提示保留在 `build.log`。没有打开其他编辑器页签或创建另一份当前稿。

当前 **0次新LLM执行、0次新物理实验**。公开任务已经找到，但新完整应用trace需实际采集；实验结果图需由该数据生成。本文是可执行口径的实验设计稿，不能称为已经完成物理验证的投稿论文。当前本机没有可用NVIDIA驱动，实际平台在采集前冻结。

科研纠正规则库存在一条历史指纹异常，按skill约束不向异常库追加。本轮纠正只写入 `corrections-reviewed.json`，没有改写旧记忆。

## 重建

从仓库根目录执行（导出需要本地 Draw.io/Xvfb 可运行）：

```bash
python3 benchmark/AegisKV/exports/workflow-paper-revision-20261005/build_artifacts.py
python3 benchmark/AegisKV/exports/workflow-paper-revision-20261005/render_workflows.py
python3 benchmark/AegisKV/exports/workflow-paper-revision-20261005/render_protocol.py
```

两张 DAG 和 protocol 导出到本目录后，复制其 PDF 到 `paper/figures/`。`build_artifacts.py` 已直接保存四个机制图的 paper assets。随后运行项目构建脚本与 `verify_artifacts.py`。重新导出或改文稿后，要再次实际查看最终PDF和论文页面，不能只依赖静态PASS。
