# Figure 1：三个 PDF 批注的紧凑布局修正

用户批注（2026-10-05）：底部绕线“太占高度”；tokens 方向标识“和下面两个图例一行”；A–G “从上到下，从左到右”调整顺序。

现图按列从上向下、再从左向右读取：A/B/C、D/E、F、G。Agent 身份没有重新编号；八条任务依赖保持不变。B→F 从 B 右侧横向直连 F，避开 D/E 占用的行，移除之前专用的底部绕行。A→E 沿左边缘和浅底部弯折到 E，保持无交叉；其余依赖由独立端口连接。runtime 外框由 176 降为 152 源单位，原字体保持。

tokens 和其方向箭头移至底部，与 Reused KV/New KV 共用一行。Worker/TP rank、head 范围和每个 Agent 的 K/V 表示保持原几何和样式，62 个相关图元整体上移 24 源单位。新旧 KV 的颜色和斜线编码均保留。

生成入口仍为 `../workflow-motivation-measured-20261005/build_serving_model.py` 与 `render_serving_model.py`，源在该目录的 `sources/serving_model.drawio`，原生导出保留嵌入源。正文已有的 `serving_model.pdf`、preview PNG 与 Background Description 已更新。没有更换论文入口、创建替代论文或打开新 tab。

`review/COMPACT_ORDER_AUDIT.json` 核验按列 A–G 阅读顺序、原八条依赖、B 的两个右侧出口、B→F 直线、单行图例、无交叉/穿越其他节点，以及原生 SVG 中全部 14 个箭头的连续连接和方向。最终列宽 84.68 mm，图高由 86.25 mm 降到 78.34 mm，减少 7.91 mm / 9.17%；最小文字仍为 10.24 pt。已查看最终图稿与 canonical `paper/main.pdf` 第 2 页的彩色和灰度版本。原有构建脚本通过，12 页，无编译错误、未定义引用或 Overfull。当前会话没有暴露 `compile_latex_document`，核验使用项目既有主文入口。

`before/` 与 `BEFORE_SHA256.json` 保存本次修改前文件。实验、统计图与测量结果未修改。本次单图纠正保存在 `LESSON.json`；全局科研图经验库此前的指纹异常仍存在，未向该库追加、修改旧记录或绕过保护。
