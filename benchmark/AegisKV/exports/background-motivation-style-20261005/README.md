# Background / Motivation：恢复既有论文绘图风格

本次依据用户 2026-10-05 指令“我需要的Background and Motivation 部分的图像还要是之前的风格”，修改现有五张图的样式。保留新研究报告/仓库评审 DAG、连续多轮 Agent 语义、全部依赖关系、归一化示例和新实验协议。没有读取旧实验结果来生成这些图。

当前稿件为 [paper/main.pdf](../../paper/main.pdf)。Draw.io 源为 [sources/application-workflows.drawio](sources/application-workflows.drawio)，`native/` 保存嵌入源的 PDF/PNG/SVG。统计和机制图保存 PDF/PNG/SVG 及可重建 Python 源。编辑器仍使用原 Design 文件。

## 样式来源和修正

- 以既有 `serving_model.pdf` 为架构图参考：Libertine、淡绿色矩形 Agent、细灰色依赖连线。节点统一颜色，不暗示执行阶段有全层屏障。两张 DAG 按 168 mm 插入，压缩垂直留白；字体保持 10.38 pt。
- 以旧 `agent_value_b.pdf` 的外观为恢复暴露图参考：绿色斜线表示吸收部分，红色实心表示 Added WCT，顶部图例和右侧 ΔW 列。保留当前人为定义的 R=4u、Slack=3/0/5u 与 ΔW=1/4/0u。这里的 u 是任意单位。
- DRAM/HBM 与需求时序图沿用既有淡色矩形、细线和斜线编码；超出需求时间的 transfer 段单独表示 stall。它是符号顺序示意，没有物理延迟数据。
- HBM 空间图去掉图内大标题，采用细轴线和顶部图例。Serving 采用深蓝色，确保灰度下与 Fixed 和斜线 Replica space 有区别；斜线表示剩余空间。
- 后续重测得到的曲线继续采用旧 `kv_value.pdf` 的简洁风格：蓝/橙/绿、空心 circle/square/triangle、细水平网格和无边框图例。不能复用该旧图的数值。

既有 `serving_model.pdf` 按哈希确认未变。这里只恢复视觉样式，不把旧测量迁入新实验。新实验设计仍是 [docs/workflow-evaluation-20261005](../../docs/workflow-evaluation-20261005/README.md)，当前没有新增 LLM trace 或物理实验。

## 验证

[FIGURE_REVIEW.json](FIGURE_REVIEW.json) 包含独立依赖检查、可编辑 PNG/源一致性、实际 PDF 字号和边界、纯矢量检查、论文编译与人工查看结果。研究图 7 Agent/8 边；评审图 8 Agent/10 边。三张单栏机制图宽 84.68 mm、字号 10.5 pt。已查看五张图的实际导出、灰度和最终论文第 3–5 页；全稿 12 页，无编译错误、未解析引用或 overfull hbox。

本会话没有暴露 `compile_latex_document`；使用项目 canonical `build_paper.sh` 检查现有稿件并发布到 `paper/main.pdf`。本次没有打开其他编辑器页签。

历史纠正规则库中 `20260923T213943533276Z-d9d508c58b-scientific-figure-aegiskv-technical-page-count-includes-late-floats.md` 内容指纹不符，skill 禁止向异常库追加。[corrections-reviewed.json](corrections-reviewed.json) 只记录本项目本次修正，未宣称写入全局记忆。

## 重建

从仓库根目录执行。Draw.io 导出需要本地 Xvfb 的运行权限；保留源，不运行历史实验 renderer。

```bash
python3 benchmark/AegisKV/exports/background-motivation-style-20261005/build_style.py
python3 benchmark/AegisKV/exports/background-motivation-style-20261005/render_workflows.py
cp benchmark/AegisKV/exports/background-motivation-style-20261005/research-report-workflow.pdf benchmark/AegisKV/paper/figures/
cp benchmark/AegisKV/exports/background-motivation-style-20261005/repository-change-review-workflow.pdf benchmark/AegisKV/paper/figures/
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
python3 benchmark/AegisKV/exports/background-motivation-style-20261005/verify_style.py
```

`verify_style.py` 的静态检查不能替代人工检查；重建后按实际插入宽度查看 `review/` 的彩色、灰度和论文页面，再更新人工审查状态。`before/` 为样式修改前快照。
