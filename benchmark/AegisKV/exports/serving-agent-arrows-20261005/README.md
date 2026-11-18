# Figure 1：Agent 标签与箭头末端修正

用户要求（2026-10-05）：Figure 1 不再需要 A4/C4 调用序号；B 的两个箭头都应从右侧指出；修改紧贴转角或看起来没有线段的箭头头部。

本次沿用现有 Draw.io 图源：删除重复的 dispatch 请求标签，把 worker 内 A4/C4/B2 改为 KV 所属 Agent A/C/B。B→D 从右侧上部出发，B→F 从右侧下部出发后经底部通道到 F。全部八条任务依赖不变，62 个 worker/rank/KV 图元除调用序号外保持原标签、字体、几何和样式。

原 runtime→Router 间距只有 6 源单位，侧向返回线的最后一段也不足以容纳完整箭头与线段。本次调整 Router 位置；返回路径从 runtime 底部进入，末端增加连续的实线短段。14 个箭头均保留至少 26 源单位的直线末段。`review/NATIVE_ARROW_JOIN_AUDIT.json` 直接核验原生 SVG 中箭头底部与线段终点相等、方向一致，实际可见的末端直线最短为 19.03 源单位。`review/AGENT_AND_ROUTING_AUDIT.json` 核验 B 的右侧出口、依赖、无交叉、KV 图元和最终正文。

生成入口仍为 `../workflow-motivation-measured-20261005/build_serving_model.py`、`render_serving_model.py`；其 `sources/serving_model.drawio` 保持可编辑，native PDF/SVG/PNG 保留嵌入源。正文 `background.tex` 的 caption 和 Description 已同步。canonical PDF 和已有的 `paper/figures/preview/serving_model.png` 均更新。

最终列宽 84.68 mm，高 86.25 mm，最小文字 10.24 pt。查看最终图稿及 `paper/main.pdf` 第 2 页的彩色和灰度渲染，未见箭头与转角挤在一起、悬空箭头或裁切。主文通过原构建脚本编译，为 12 页，无编译错误、未定义引用或 Overfull；实验和统计图数据未修改。当前会话没有暴露 `compile_latex_document`，因此使用项目既有主文构建入口，没有独立编译章节文件或打开新 tab。

`before/` 和 `BEFORE_SHA256.json` 保存修改前文件。`LESSON.json` 保存本项目 serving 图的三项新纠正。全局科研图经验库此前的 `aegiskv-technical-page-count-includes-late-floats` 条目仍有指纹异常，未向该库追加、修改旧记录或绕过保护；此文件是项目内记录。
