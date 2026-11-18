# 移除独立 DAG 插图并整理 Workflow runtime

用户原话（2026-10-05）：“Figure1没必要插入到论文中；Figure2中的workflow runtime我希望更美观一点，箭头更整洁”。

`paper/background.tex` 删除独立的两应用 DAG 浮动图。Introduction、Motivation 和 Evaluation 中原来的图引用改为 Background 小节引用。独立 DAG 图源和 PDF 均保留。图号由 LaTeX 自动更新：原 Figure 2 serving 图现在为 Figure 1。

Serving 图沿用现有 Libertine 字体、绿色节点、灰色容器、Router、TP rank 和 K/V 表示。只重新分配 runtime 空间与 DAG 节点位置：C/A/B 根节点对齐，E/D、F、G 从左向右排列；汇入节点使用分开的入口，B→F 使用底部通道。八条原依赖保持不变，箭头全部为直角走线，无内部交叉。下方 70 个图元的字体、标签、宽高和相对位置均保持，只整体下移 28 源坐标单位以容纳上方布局。

现有生成入口为 `../workflow-motivation-measured-20261005/build_serving_model.py` 与 `render_serving_model.py`，可编辑源在该目录的 `sources/serving_model.drawio`。Native Draw.io 导出保留嵌入源。`before/` 和 `BEFORE_SHA256.json` 保存本次修改前文件。

`review/ROUTING_AND_MANUSCRIPT_AUDIT.json` 记录 DAG、路径和正文核验。原生导出及 canonical `paper/main.pdf` 第 2、3 页按实际列宽查看了彩色和灰度版本。图宽 84.68 mm，最小嵌入字号 10.22 pt；没有缩小文字来整理布局。主文使用原有 `build_paper.sh` 编译，12 页，无致命错误、未定义引用或 Overfull 警告。实验和统计图数据未修改。

本次单图纠正记录在 `LESSON.json`，适用于本项目 Background serving 图。全局科研图经验库存在此前已报告的指纹异常，因此未向该库追加或修复旧记录；项目内记录没有冒充全局记忆条目。
